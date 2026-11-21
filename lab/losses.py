"""The ranking and multitask losses (moved unchanged from train.py in V6.7.1): soft Spearman, ListNet, IC, long-short
Sharpe, the class-balanced and cost-aware variants, the masked heads and the combined multitask loss.
`train.py` re-exports every name.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn

from lab.architectures import horizon_head_specs
from lab.objectives import CONTEXT_CLASSES, CONTEXT_OBJECTIVES, RANKING_OBJECTIVES  # noqa: F401  (RANKING_OBJECTIVES re-exported for the trainers)

# ---------------------------------------------------------------------------
# V5.1 Phase 3 (item 1) - cross-sectional ranking losses. Hand-written
# (n ~= 70 assets/date => O(n^2) ~= 5k pairwise ops per date, trivial) -
# deliberately NOT a compiled dependency like torchsort/fast-soft-sort in a
# repo whose live inference is a hand-written NumPy interpreter
# (inference/exported_model.py); these losses only ever run at TRAINING
# time (never exported/interpreted), so there is no interpreter-parity
# concern here, but a new compiled dependency for training alone still
# isn't worth it when the pure-torch version is this cheap.
# ---------------------------------------------------------------------------


def soft_rank_within_groups(scores: torch.Tensor, group_ids: torch.Tensor, temperature: float) -> torch.Tensor:
    """Differentiable rank approximation: for each group (date), soft_rank_i
    = sum_j sigmoid((s_i - s_j) / temperature), normalized to [0, 1] via
    (raw_rank - 0.5) / (n - 1) - the -0.5 removes the self-comparison term
    (sigmoid(0) == 0.5 exactly), matching pandas' .rank(pct=True) convention
    of assigning the smallest score percentile 0 and the largest 1 in the
    low-temperature limit. As temperature -> 0, sigmoid((s_i-s_j)/temperature)
    approaches the hard step function 1[s_i > s_j], so soft_rank_i approaches
    the TRUE rank exactly (see tests/test_train_ranking_loss.py's
    cross-validation against _rank_ic_from_arrays()).

    A group of size 1 gets rank 0.5 (no information, the safe neutral
    midpoint - never divides by zero)."""
    soft_ranks = torch.zeros_like(scores)
    for group in torch.unique(group_ids):
        group_mask = group_ids == group
        group_scores = scores[group_mask]
        n = int(group_scores.shape[0])
        if n <= 1:
            soft_ranks = soft_ranks.masked_scatter(group_mask, torch.full((n,), 0.5, device=scores.device))
            continue
        pairwise = torch.sigmoid((group_scores.unsqueeze(1) - group_scores.unsqueeze(0)) / temperature)
        raw_rank = pairwise.sum(dim=1)
        normalized = (raw_rank - 0.5) / (n - 1)
        soft_ranks = soft_ranks.masked_scatter(group_mask, normalized)
    return soft_ranks


def soft_spearman_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    group_ids: torch.Tensor,
    mask: torch.Tensor,
    temperature: float,
    date_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    """Per date, Pearson correlation between soft_rank(predictions) and
    targets (already a [0,1] percentile rank, a positive affine transform
    of the true rank - Pearson is invariant to that, the EXACT argument
    _rank_ic_from_arrays()'s own docstring makes for why ranking the
    prediction alone reproduces the true Spearman correlation). Loss =
    -mean(correlation) across dates, so minimizing it maximizes rank-IC.

    Dates with fewer than 2 valid rows, or zero variance on either side
    (every asset tied - undefined correlation), are SKIPPED, not counted
    as a 0.0 correlation - same convention _rank_ic_from_arrays() uses for
    exactly the same reason (0.0 would misrepresent "undefined" as "no
    correlation", pulling the mean toward zero for no real reason).
    Returns a true zero (no gradient) when nothing is valid, matching
    masked_mse_loss()'s contract.

    date_weights (V5.2.8, development/Problems.md #94): optional, one
    weight per ROW aligned to `group_ids` (NOT per-group directly - see
    compute_gate_friendliness_weight_by_date()'s caller for how this is
    built). Within each date, the group's mean weight scales that date's
    contribution to the final average - a date entirely populated by
    gate-friendly rows (weight ~1.0) contributes normally, a date the
    live gates would have mostly blocked contributes less. None (the
    default) reproduces today's exact uniform mean - BYTE-IDENTICAL,
    enforced by tests/test_train_ranking_loss.py's own parity test, not
    just assumed."""
    valid = mask & ~torch.isnan(targets)
    if not torch.any(valid):
        return torch.zeros((), device=predictions.device)

    valid_predictions = predictions[valid]
    valid_targets = targets[valid]
    valid_group_ids = group_ids[valid]
    valid_date_weights = date_weights[valid] if date_weights is not None else None
    soft_ranks = soft_rank_within_groups(valid_predictions, valid_group_ids, temperature)

    correlations = []
    weights = []
    for group in torch.unique(valid_group_ids):
        group_mask = valid_group_ids == group
        group_rank = soft_ranks[group_mask]
        group_target = valid_targets[group_mask]
        if group_rank.shape[0] < 2:
            continue
        rank_variance = torch.var(group_rank, unbiased=False)
        target_variance = torch.var(group_target, unbiased=False)
        if rank_variance <= 1e-12 or target_variance <= 1e-12:
            continue
        rank_centered = group_rank - group_rank.mean()
        target_centered = group_target - group_target.mean()
        denominator = torch.sqrt((rank_centered**2).sum() * (target_centered**2).sum())
        correlation = (rank_centered * target_centered).sum() / denominator
        correlations.append(correlation)
        weights.append(valid_date_weights[group_mask].mean() if valid_date_weights is not None else torch.ones((), device=predictions.device))

    if not correlations:
        return torch.zeros((), device=predictions.device)
    stacked_correlations = torch.stack(correlations)
    if date_weights is None:
        return -stacked_correlations.mean()
    stacked_weights = torch.stack(weights)
    return -(stacked_correlations * stacked_weights).sum() / stacked_weights.sum()


def listnet_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    group_ids: torch.Tensor,
    mask: torch.Tensor,
    temperature: float,
    date_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    """Per date, cross-entropy H(softmax(targets/temperature),
    softmax(predictions/temperature)) - the standard ListNet objective
    (Cao et al. 2007), treating each date's cross-section as a probability
    distribution over "which asset is the top performer" rather than
    comparing pairwise ranks. Always >= 0 (cross-entropy of two
    distributions in [0,1] is non-negative by construction) and minimized
    when the two softmax distributions coincide, i.e. when predictions are
    a positive affine function of targets. Dates with fewer than 2 valid
    rows are skipped. Returns a true zero when nothing is valid.

    date_weights: see soft_spearman_loss()'s own docstring - identical
    contract and None-default parity guarantee."""
    valid = mask & ~torch.isnan(targets)
    if not torch.any(valid):
        return torch.zeros((), device=predictions.device)

    valid_predictions = predictions[valid]
    valid_targets = targets[valid]
    valid_group_ids = group_ids[valid]
    valid_date_weights = date_weights[valid] if date_weights is not None else None

    losses = []
    weights = []
    for group in torch.unique(valid_group_ids):
        group_mask = valid_group_ids == group
        group_predictions = valid_predictions[group_mask]
        group_targets = valid_targets[group_mask]
        if group_predictions.shape[0] < 2:
            continue
        prediction_log_softmax = torch.log_softmax(group_predictions / temperature, dim=0)
        target_softmax = torch.softmax(group_targets / temperature, dim=0)
        losses.append(-(target_softmax * prediction_log_softmax).sum())
        weights.append(valid_date_weights[group_mask].mean() if valid_date_weights is not None else torch.ones((), device=predictions.device))

    if not losses:
        return torch.zeros((), device=predictions.device)
    stacked_losses = torch.stack(losses)
    if date_weights is None:
        return stacked_losses.mean()
    stacked_weights = torch.stack(weights)
    return (stacked_losses * stacked_weights).sum() / stacked_weights.sum()




def ic_pearson_loss(
    predictions: torch.Tensor, targets: torch.Tensor, group_ids: torch.Tensor, mask: torch.Tensor, date_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    """R-LOSS1 L2: minus the mean over dates of the Pearson correlation of the raw prediction with the realised rank. Unlike
    soft_spearman_loss it never ranks the prediction, so a date's extreme predictions pull harder. Same skipping rules and date-weight
    contract as soft_spearman_loss."""
    valid = mask & ~torch.isnan(targets)
    if not torch.any(valid):
        return torch.zeros((), device=predictions.device)
    correlations, weights = [], []
    for group in torch.unique(group_ids[valid]):
        member = valid & (group_ids == group)
        prediction, target = predictions[member], targets[member]
        if prediction.shape[0] < 2 or torch.var(prediction, unbiased=False) <= 1e-12 or torch.var(target, unbiased=False) <= 1e-12:
            continue
        p, t = prediction - prediction.mean(), target - target.mean()
        correlations.append((p * t).sum() / torch.sqrt((p ** 2).sum() * (t ** 2).sum()))
        weights.append(date_weights[member].mean() if date_weights is not None else torch.ones((), device=predictions.device))
    if not correlations:
        return torch.zeros((), device=predictions.device)
    stacked, stacked_weights = torch.stack(correlations), torch.stack(weights)
    return -(stacked * stacked_weights).sum() / stacked_weights.sum()


def long_short_sharpe_loss(
    predictions: torch.Tensor, returns: torch.Tensor, group_ids: torch.Tensor, mask: torch.Tensor, temperature: float = 0.1,
) -> torch.Tensor:
    """R-LOSS1 L3: minus a shrunk Sharpe, across a batch's dates, of a softmax long-short book on the realised forward return.

    Per date, w = softmax(p / T) - softmax(-p / T) (long the top, short the bottom, net zero, gross 2) and the book's return r = w . ret,
    divided by that date's cross-sectional return dispersion so a volatile date does not dominate. Over the dates, loss = -mean(z) /
    sqrt(var(z) + 1): a Sharpe with a variance prior of one, so a batch of one date is minus its return and many dates approach the Sharpe.
    Dates with fewer than 2 valid rows or no dispersion are skipped."""
    valid = mask & ~torch.isnan(returns)
    scores = []
    for group in torch.unique(group_ids[valid]) if torch.any(valid) else ():
        member = valid & (group_ids == group)
        prediction, realised = predictions[member], returns[member]
        spread = torch.std(realised, unbiased=False)
        if prediction.shape[0] < 2 or spread <= 1e-12:
            continue
        weights = torch.softmax(prediction / temperature, dim=0) - torch.softmax(-prediction / temperature, dim=0)
        scores.append((weights * realised).sum() / spread)
    if not scores:
        return torch.zeros((), device=predictions.device)
    stacked = torch.stack(scores)
    return -stacked.mean() / torch.sqrt(torch.var(stacked, unbiased=False) + 1.0)


def row_context_targets(frame: pd.DataFrame, rows: np.ndarray) -> dict[str, torch.Tensor]:
    """The `_`-keyed row context an R-LOSS1 objective reads, for `frame`'s rows at `rows`: the asset class (index into CONTEXT_CLASSES from
    the `asset_class_<name>` one-hot context columns, len(CONTEXT_CLASSES) for anything else), a ticker id (consistent across the frame's
    splits) and the realised 5- and 20-day forward returns (NaN where the dataset lacks them)."""
    class_ids = np.full(len(frame), len(CONTEXT_CLASSES), dtype=np.float32)
    for index, name in enumerate(CONTEXT_CLASSES):
        column = f"asset_class_{name}"
        if column in frame.columns:
            class_ids[frame[column].to_numpy(dtype=np.float32) > 0.5] = index
    ticker_ids = pd.factorize(frame["ticker"])[0].astype(np.float32)
    context = {"_class_ids": class_ids[rows], "_ticker_ids": ticker_ids[rows]}
    for horizon in ("5d", "20d"):
        column = f"target_return_{horizon}"
        values = frame[column].to_numpy(dtype=np.float32) if column in frame.columns else np.full(len(frame), np.nan, dtype=np.float32)
        context[f"_return_{horizon}"] = values[rows]
    return {key: torch.from_numpy(np.ascontiguousarray(value)) for key, value in context.items()}


def class_group_ids(group_ids: torch.Tensor, class_ids: torch.Tensor) -> torch.Tensor:
    """One group per (date, asset class): a ranking within each class on each date, every class one group (R-LOSS1 L4)."""
    return group_ids.long() * (len(CONTEXT_CLASSES) + 1) + class_ids.long()


def rank_turnover_penalty(predictions: torch.Tensor, group_ids: torch.Tensor, ticker_ids: torch.Tensor, temperature: float) -> torch.Tensor:
    """R-LOSS1 L5's turnover term: the mean absolute change of a ticker's soft rank (within its date) between the consecutive dates of
    the batch it appears on. Zero when no ticker appears on two dates."""
    ranks = soft_rank_within_groups(predictions, group_ids, temperature)
    changes = []
    for ticker in torch.unique(ticker_ids):
        member = ticker_ids == ticker
        if int(member.sum()) < 2:
            continue
        order = torch.argsort(group_ids[member])
        changes.append(torch.abs(torch.diff(ranks[member][order])))
    if not changes:
        return torch.zeros((), device=predictions.device)
    return torch.cat(changes).mean()


def compute_cross_sectional_ranking_loss(
    head_output: torch.Tensor,
    head_target: torch.Tensor,
    group_ids: torch.Tensor,
    ranking_loss_config: dict[str, Any],
    date_weights: torch.Tensor | None = None,
    context: dict[str, torch.Tensor] | None = None,
) -> torch.Tensor:
    """Dispatcher on ranking_loss_config["objective"] in
    {"mse", "soft_spearman", "listnet"} (default "mse", reproducing
    masked_mse_loss() exactly - the byte-identical no-op path
    compute_combined_multitask_loss() falls back to when Phase 3's config
    is absent). For the two real ranking objectives, adds
    ranking_loss_config["mse_anchor_weight"] * masked_mse_loss() on top: a
    pure ranking loss is invariant to any affine rescaling of the head's
    raw output, so without this anchor term the output SCALE drifts
    unboundedly during training - harmless for ranking (only order
    matters) but it would make the exported head numerically unstable and
    would defeat the "raw" (non-normalized) diagnostic reading of the
    score. Defaults (temperature=0.05, listnet_temperature=0.1,
    mse_anchor_weight=0.1) live in config.json, not here - this function
    always reads them from ranking_loss_config, never hardcodes a
    fallback, so a caller can never silently diverge from what got
    logged/trained with.

    date_weights (V5.2.8, development/Problems.md #94): passed straight
    through to soft_spearman_loss()/listnet_loss() - see their own
    docstrings. Never applied to the mse_anchor_weight term (that term
    exists purely to anchor output SCALE, not to express the ranking
    objective itself - weighting it the same way would fight its own
    purpose). None (the default) is a strict no-op, same as those two
    functions' own contract."""
    mask = ~torch.isnan(head_target)
    objective = str(ranking_loss_config.get("objective", "mse"))
    if objective == "mse":
        return masked_mse_loss(head_output, head_target, mask)

    temperature = float(ranking_loss_config.get("temperature", 0.05))
    mse_anchor_weight = float(ranking_loss_config.get("mse_anchor_weight", 0.0))
    if objective == "soft_spearman":
        ranking_loss = soft_spearman_loss(head_output, head_target, group_ids, mask, temperature, date_weights)
    elif objective == "listnet":
        listnet_temperature = float(ranking_loss_config.get("listnet_temperature", temperature))
        ranking_loss = listnet_loss(head_output, head_target, group_ids, mask, listnet_temperature, date_weights)
    elif objective == "ic_pearson":
        ranking_loss = ic_pearson_loss(head_output, head_target, group_ids, mask, date_weights)
    elif objective in CONTEXT_OBJECTIVES:
        # V6.6.10 (R-LOSS1): these read per-row context the trainer adds to the batch (`_class_ids`, `_ticker_ids`, the head's returns)
        missing = [key for key in ("class_ids", "ticker_ids", "returns") if context is None or context.get(key) is None]
        if missing:
            raise ValueError(f"compute_cross_sectional_ranking_loss: objective {objective!r} needs row context {missing}")
        if objective == "ls_sharpe":
            ranking_loss = long_short_sharpe_loss(head_output, context["returns"], group_ids, mask, float(ranking_loss_config.get("ls_temperature", 0.1)))
        else:
            within = class_group_ids(group_ids, context["class_ids"])
            ranking_loss = soft_spearman_loss(head_output, head_target, within, mask, temperature, date_weights)
            if objective == "cost_aware":
                penalty = float(ranking_loss_config.get("turnover_penalty", 0.1))
                ranking_loss = ranking_loss + penalty * rank_turnover_penalty(head_output, group_ids, context["ticker_ids"], temperature)
    else:
        raise ValueError(f"compute_cross_sectional_ranking_loss: unknown objective {objective!r}")

    anchor_loss = masked_mse_loss(head_output, head_target, mask) if mse_anchor_weight else torch.zeros((), device=head_output.device)
    return ranking_loss + mse_anchor_weight * anchor_loss


def masked_bce_with_logits_loss(logits: torch.Tensor, targets: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Binary cross-entropy over only the rows where `mask` is True - used
    for the horizon-direction heads (direction_5d/20d), whose targets are
    NaN for the trailing few rows of each asset's history that don't yet
    have a full 5/20-day-forward close, rather than dropped from the
    dataset entirely (see engineer_features()'s docstring on why - dropping
    would also shrink every per-expert dataset slice downstream). Returns
    a true zero (no gradient contribution) rather than NaN/erroring when no
    row in this batch has a valid target for this head."""
    if not torch.any(mask):
        return torch.zeros((), device=logits.device)
    return nn.functional.binary_cross_entropy_with_logits(logits[mask], targets[mask])


def masked_mse_loss(predictions: torch.Tensor, targets: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Same masking convention as masked_bce_with_logits_loss() above, for
    regression targets - used by the cross-sectional rank_5d/20d heads
    (masked MSE against each row's percentile-rank target)."""
    if not torch.any(mask):
        return torch.zeros((), device=predictions.device)
    return nn.functional.mse_loss(predictions[mask], targets[mask])


def add_rank_label_noise(
    batch_targets: dict[str, Any], head_specs: dict[str, Any], noise_std: float, generator: torch.Generator | None
) -> dict[str, Any]:
    """V6.2.0 regulariser: Gaussian noise of `noise_std` x the batch's own target std on every "rank"-kind head's
    targets, clipped to the batch's observed range so a percentile target stays a percentile. NaN (masked) targets
    stay NaN and binary / regression heads are untouched. `noise_std <= 0` returns the input dict itself, so a run
    without the knob is bit-identical."""
    if noise_std <= 0.0:
        return batch_targets
    noisy = dict(batch_targets)
    for name, (_column, kind, _stride) in head_specs.items():
        target = batch_targets.get(name)
        if kind != "rank" or target is None:
            continue
        finite = torch.isfinite(target)
        if int(finite.sum()) < 2:
            continue
        values = target[finite]
        noise = torch.randn(target.shape, generator=generator, dtype=target.dtype) * (float(values.std()) * noise_std)
        noisy[name] = torch.where(finite, (target + noise).clamp(float(values.min()), float(values.max())), target)
    return noisy


def _pairwise_consistency_penalty(values_a: torch.Tensor, values_b: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Core of compute_horizon_consistency_loss() below - shared between the
    rank pair (rank_5d/rank_20d, already ~[0,1]-scaled by their own MSE
    objective) and the direction pair (direction_5d/direction_20d, sigmoid-
    applied first by the caller so they're on the same [0,1] scale). Both
    `values_a`/`values_b` are expected centered around 0.5 = "no opinion" -
    `-(a-0.5)*(b-0.5)` is negative (relu zeroes it - no penalty) whenever
    both sit on the SAME side of 0.5 (both bullish-of-median or both
    bearish-of-median), and positive (penalized) whenever they disagree.
    Returns a true zero (no gradient contribution) when the mask is empty,
    matching masked_bce_with_logits_loss()/masked_mse_loss()'s convention."""
    if not torch.any(mask):
        return torch.zeros((), device=values_a.device)
    a_centered = values_a[mask] - 0.5
    b_centered = values_b[mask] - 0.5
    return nn.functional.relu(-(a_centered * b_centered)).mean()


def compute_horizon_consistency_loss(outputs: dict[str, torch.Tensor], targets: dict[str, torch.Tensor]) -> torch.Tensor:
    """Stage 4 of the rank-pivot roadmap (development/Problems.md#43): an
    explicit regularizer penalizing the model for predicting the 5-day and
    20-day views of the SAME underlying signal on opposite sides of the
    cross-section/direction, rather than letting each head overfit its own
    horizon independently with no coherence constraint between them - the
    piece previously missing from Stage 4's regularization (rank-IC-based
    early stopping and seed-ensembling address the *epoch*/*seed* axes of
    overfitting; this addresses the *cross-head* axis).

    Two pairs, both using _pairwise_consistency_penalty() with the exact
    masking convention every other head loss already uses (only rows where
    BOTH targets in the pair are non-NaN contribute - trailing rows missing
    one horizon's forward window make "do these two heads agree"
    ill-posed, not just unsupervised):
    - rank_5d vs rank_20d: used directly (both already ~[0,1]-scaled by
      their own masked-MSE objective against a [0,1] percentile-rank
      target - no extra activation needed or wanted, since applying one
      would put this term on a different scale than the MSE loss actually
      training these heads).
    - direction_5d vs direction_20d: sigmoid-applied first, since these are
      raw BCEWithLogits logits (unbounded) - sigmoid(logit) has the same
      SIGN-relative-to-0.5 as the logit relative to 0, but keeps the
      product term boundedly scaled instead of letting large logit
      magnitudes dominate/destabilize the combined loss.

    Callers gate each pair on whether BOTH heads in it are actually enabled
    (horizon_head_config) - penalizing agreement between a disabled head's
    meaningless output and an enabled one's is not well-defined."""
    rank_mask = ~torch.isnan(targets["rank_5d"]) & ~torch.isnan(targets["rank_20d"])
    rank_penalty = _pairwise_consistency_penalty(outputs["rank_5d"], outputs["rank_20d"], rank_mask)

    direction_mask = ~torch.isnan(targets["direction_5d"]) & ~torch.isnan(targets["direction_20d"])
    direction_penalty = _pairwise_consistency_penalty(
        torch.sigmoid(outputs["direction_5d"]), torch.sigmoid(outputs["direction_20d"]), direction_mask
    )
    return rank_penalty + direction_penalty


def compute_combined_multitask_loss(
    outputs: dict[str, torch.Tensor],
    targets: dict[str, torch.Tensor],
    direction_criterion: nn.Module,
    magnitude_loss_weight: float,
    volatility_loss_weight: float,
    horizon_head_config: dict[str, Any],
    direction_loss_weight: float = 1.0,
    consistency_loss_weight: float = 0.0,
    date_group_ids: torch.Tensor | None = None,
    ranking_loss_config: dict[str, Any] | None = None,
    date_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    """Combined loss for both AetherNetMultiTaskHorizons and
    AetherNetSequenceMultiTaskHorizons (identical head-name dict shape,
    see each class's forward()) - BCEWithLogitsLoss(direction) + weighted
    MSE(magnitude)/MSE(volatility) + a masked BCE/MSE term per enabled
    horizon head (masked since direction_5d/20d/rank_5d/20d are NaN for
    the trailing few rows of an asset's history that lack a full forward
    window, see engineer_features()'s docstring).

    direction_loss_weight (Stage 4 of the rank-pivot roadmap,
    development/Problems.md#43): the primary 1-day "direction" head is a
    near-noise objective (backtest MCC ~0.02-0.04, and the sequence model's
    own copy of it collapsed to a constant during training - positive_rate
    0.0002) whose output main.py never even reads (only magnitude/
    volatility/rank_5d/rank_20d feed the trading decision) - it exists only
    as an artifact of this model's original single-task ancestor. Its loss
    was previously hardcoded at weight 1.0, forcing the shared trunk to keep
    fitting a target with no signal and no downstream consumer. Defaults to
    1.0 (fully backward-compatible - existing positional callers/tests are
    unaffected); config.json sets this low (not 0.0, so the head stays a
    harmless diagnostic rather than a dead weight-less no-op) for the
    multitask/sequence trainers specifically.

    consistency_loss_weight (Stage 4, same roadmap entry): scales
    compute_horizon_consistency_loss() above - see its own docstring.
    Defaults to 0.0 (fully backward-compatible - a zero-weighted term adds
    zero gradient contribution, so every existing positional caller/test is
    completely unaffected); only added when BOTH heads of a pair are
    enabled (horizon_head_config), matching this function's existing
    per-head enabled-gating convention immediately below.

    date_group_ids/ranking_loss_config (V5.1 Phase 3, item 1): when BOTH
    are provided, every enabled "rank"-kind head (HORIZON_HEAD_SPECS -
    rank_5d/20d, sector_neutral_rank_20d, residual_rank_5d/20d,
    beta_neutral_rank_20d, generically, no per-head special-casing) routes
    through compute_cross_sectional_ranking_loss() instead of a bare
    masked_mse_loss() call. GUARDRAIL: when either is None (the default),
    this is BYTE-IDENTICAL to the pre-Phase-3 code path - every existing
    positional caller/test is completely unaffected.

    date_weights (V5.2.8, development/Problems.md #94): optional, passed
    straight through to compute_cross_sectional_ranking_loss() whenever
    the ranking-loss path is active - built by
    compute_gate_friendliness_weight_by_date() and looked up per-row via
    date_group_ids by the caller (train_multitask.py/train_sequence.py),
    config-gated off by default
    (phase_v2.training.gate_aware_ranking_weights.enabled). None is a
    strict no-op - has no effect at all unless use_ranking_loss is also
    True, matching date_group_ids/ranking_loss_config's own contract."""
    loss = (
        direction_loss_weight * direction_criterion(outputs["direction"], targets["direction"])
        + magnitude_loss_weight * nn.functional.mse_loss(outputs["magnitude"], targets["magnitude"])
        + volatility_loss_weight * nn.functional.mse_loss(outputs["volatility"], targets["volatility"])
    )
    use_ranking_loss = date_group_ids is not None and ranking_loss_config is not None
    for head_name, (_column, kind, _stride) in horizon_head_specs(horizon_head_config).items():
        head_config = horizon_head_config[head_name]
        if not head_config.get("enabled", True):
            continue
        mask = ~torch.isnan(targets[head_name])
        if kind == "binary":
            head_loss = masked_bce_with_logits_loss(outputs[head_name], targets[head_name], mask)
        elif use_ranking_loss:
            # V6.6.10: the row context a trainer added under `_`-keys (absent for every objective that needs none)
            context = {
                "class_ids": targets.get("_class_ids"), "ticker_ids": targets.get("_ticker_ids"),
                "returns": targets.get("_return_5d" if "5d" in head_name else "_return_20d"),
            }
            head_loss = compute_cross_sectional_ranking_loss(
                outputs[head_name], targets[head_name], date_group_ids, ranking_loss_config, date_weights, context
            )
        else:
            head_loss = masked_mse_loss(outputs[head_name], targets[head_name], mask)
        loss = loss + float(head_config.get("loss_weight", 1.0)) * head_loss

    if consistency_loss_weight:
        rank_pair_enabled = horizon_head_config["rank_5d"].get("enabled", True) and horizon_head_config["rank_20d"].get(
            "enabled", True
        )
        direction_pair_enabled = horizon_head_config["direction_5d"].get(
            "enabled", True
        ) and horizon_head_config["direction_20d"].get("enabled", True)
        if rank_pair_enabled or direction_pair_enabled:
            consistency_targets = {
                "rank_5d": targets["rank_5d"] if rank_pair_enabled else torch.full_like(targets["rank_5d"], float("nan")),
                "rank_20d": targets["rank_20d"] if rank_pair_enabled else torch.full_like(targets["rank_20d"], float("nan")),
                "direction_5d": targets["direction_5d"]
                if direction_pair_enabled
                else torch.full_like(targets["direction_5d"], float("nan")),
                "direction_20d": targets["direction_20d"]
                if direction_pair_enabled
                else torch.full_like(targets["direction_20d"], float("nan")),
            }
            loss = loss + consistency_loss_weight * compute_horizon_consistency_loss(outputs, consistency_targets)
    return loss
