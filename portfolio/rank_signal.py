"""Rank signal resolution and cross-sectional normalization (V5.1 Phase 1,
development/Problems.md #73 - the sigmoid-at-inference/raw-at-training
mismatch). Two responsibilities, both pure:

1. WHICH head(s) drive live trading - previously hardcoded in main.py
   (always prefer the sequence model's rank_20d, fall back to multitask's),
   now a config-driven, promotion-gate-aware blend resolved once per run.
2. HOW that raw score becomes a [0,1] rank - previously a raw model output
   passed straight through (which, combined with a since-fixed sigmoid/raw
   training mismatch, meant live values compressed into roughly
   [0.5, 0.7] instead of spanning [0,1] - IC is invariant to any monotone
   transform, which is exactly why no rank-IC-based gate ever caught it).
   Cross-sectional percentile normalization, computed fresh each bar over
   whichever symbols have a raw score, is the fix that survives regardless
   of what scale the underlying model head happens to output at - the
   same reasoning train.py::_rank_ic_from_arrays() already documents for
   why it ranks predictions before comparing them.
"""

from __future__ import annotations


def resolve_rank_signal_policy(training_metrics_by_model: dict[str, dict | None], config: dict) -> dict:
    """Resolved ONCE in main.py::Initialize() (never per-bar - the
    promotion-gate verdicts this reads only change when a new model is
    installed). Reads phase_v2.rank_signal:

      heads: {"rank_20d": 1.0, "rank_5d": 0.0} - the blend weights.
      model_priority: ["sequence", "multitask"] - which model's value for
        a given head wins when both are available.
      demote_not_promotable_heads: when true, a head whose backtest
        promotion-gate verdict (backtest.{head}_ranking_quality.quality_status,
        checked against the FIRST model in model_priority that has a
        verdict for it - the same precedence select_raw_rank_score() uses
        at runtime) is not in min_promotion_status has its weight zeroed
        and redistributed proportionally across the surviving heads.

    Returns {"heads": {...}, "model_priority": [...], "normalization": ...,
    "demoted": [...], "reason": "..."}.

    FAIL-OPEN, always: never raises. Missing/unreadable metrics for a head
    leave that head's configured weight untouched (a promotion verdict
    that cannot be checked is not evidence of a problem). If demotion
    would zero out EVERY head's weight, the entire operation is skipped
    and the originally configured policy is returned unchanged, with
    reason recording why - demoting every head would silently stop the
    book from ever engaging, a far bigger behavior change than "prefer a
    different head" implies.
    """
    rank_signal_config = config.get("phase_v2", {}).get("rank_signal", {})
    heads = dict(rank_signal_config.get("heads", {"rank_20d": 1.0}))
    model_priority = list(rank_signal_config.get("model_priority", ["sequence", "multitask"]))
    normalization = str(rank_signal_config.get("normalization", "cross_sectional"))
    demote_enabled = bool(rank_signal_config.get("demote_not_promotable_heads", True))
    min_promotion_status = set(rank_signal_config.get("min_promotion_status", ["promotable", "watchlist"]))

    if not demote_enabled or not heads:
        return {
            "heads": heads, "model_priority": model_priority, "normalization": normalization,
            "demoted": [], "reason": "demotion_disabled_or_no_heads_configured",
        }

    demoted: list[str] = []
    surviving_heads: dict[str, float] = {}
    for head_name, weight in heads.items():
        if weight <= 0.0:
            continue
        status = _resolve_head_quality_status(head_name, model_priority, training_metrics_by_model)
        if status is None or status in min_promotion_status:
            surviving_heads[head_name] = weight
        else:
            demoted.append(head_name)

    if not surviving_heads:
        # Demoting every head would silently stop the book from ever
        # engaging - a far bigger behavior change than "prefer a
        # different head" implies. Leave the configured policy untouched.
        return {
            "heads": heads, "model_priority": model_priority, "normalization": normalization,
            "demoted": [], "reason": "all_heads_would_be_demoted_policy_unchanged",
        }

    total_weight = sum(surviving_heads.values())
    redistributed = {name: weight / total_weight for name, weight in surviving_heads.items()}
    # Zero-weighted entries for demoted heads are kept (not dropped) so
    # select_raw_rank_score()'s blend loop can still see - and skip - them
    # without a KeyError, and so state.json's rank_head_weights stays a
    # complete, auditable record of every configured head.
    for head_name in heads:
        redistributed.setdefault(head_name, 0.0)

    reason = "no_demotion_needed" if not demoted else f"demoted:{','.join(demoted)}"
    return {
        "heads": redistributed, "model_priority": model_priority, "normalization": normalization,
        "demoted": demoted, "reason": reason,
    }


def _resolve_head_quality_status(
    head_name: str, model_priority: list[str], training_metrics_by_model: dict[str, dict | None]
) -> str | None:
    """First model in model_priority that has a backtest ranking_quality
    verdict for `head_name` wins - the same precedence
    select_raw_rank_score() uses to pick which model's VALUE feeds the
    blend, so the demotion decision and the runtime value come from the
    same model whenever possible. Returns None (never raises) when no
    configured model has a verdict for this head - e.g. an older metrics
    file predating this head, or the metrics file missing entirely."""
    for model_name in model_priority:
        metrics = training_metrics_by_model.get(model_name)
        if not metrics:
            continue
        quality = (metrics.get("backtest", {}) or {}).get(f"{head_name}_ranking_quality")
        if quality:
            return quality.get("quality_status")
    return None


def select_raw_rank_score(
    sequence_prediction: dict | None, multitask_payload: dict | None, policy: dict
) -> tuple[float | None, str]:
    """Replaces main.py's previous hardcode (always prefer the sequence
    model's rank_20d, fall back to multitask's). Now a weighted blend
    across policy["heads"], each head's own value resolved via
    policy["model_priority"] (sequence before multitask, by default).

    Returns (score, source) where source records exactly which heads/
    models contributed, e.g. "sequence:0.6*rank_5d+0.4*rank_20d" or
    "sequence:1.0*rank_20d,multitask:1.0*rank_5d" when different heads
    come from different models. Returns (None, "no_rank_available") when
    no configured head has a value from any model this bar (e.g. every
    model still warming up)."""
    payload_by_model = {"sequence": sequence_prediction, "multitask": multitask_payload}
    model_priority = policy.get("model_priority", ["sequence", "multitask"])
    heads = policy.get("heads", {})

    weighted_sum = 0.0
    total_weight_used = 0.0
    contributions: list[str] = []

    for head_name, weight in heads.items():
        if weight <= 0.0:
            continue
        value, model_used = _resolve_head_value(head_name, model_priority, payload_by_model)
        if value is None:
            continue
        weighted_sum += weight * float(value)
        total_weight_used += weight
        contributions.append(f"{model_used}:{weight:g}*{head_name}")

    if total_weight_used <= 0.0:
        return None, "no_rank_available"

    score = weighted_sum / total_weight_used
    source = ",".join(contributions)
    return score, source


def _resolve_head_value(
    head_name: str, model_priority: list[str], payload_by_model: dict[str, dict | None]
) -> tuple[float | None, str | None]:
    for model_name in model_priority:
        payload = payload_by_model.get(model_name)
        if payload and payload.get(head_name) is not None:
            return float(payload[head_name]), model_name
    return None, None


def cross_sectional_rank_scores(scores_by_symbol: dict[str, float]) -> dict[str, float]:
    """Per-bar percentile rank across whatever symbols have a raw score
    this bar, ties averaged (matching pandas' `.rank(pct=True)` semantics -
    the same transform train.py::_rank_ic_from_arrays() applies to
    predictions before computing rank-IC, so a raw score's absolute scale
    can never matter, only its ordering within this bar's cross-section).
    Pure Python - no pandas import on the runtime hot path.

    <=1 eligible symbol returns {} (no meaningful cross-section to rank
    within, so the book has no view this bar) - NEVER a spurious 0.5 for
    a lone symbol, which would silently look like "predicted median"
    rather than "no ranking possible."."""
    if len(scores_by_symbol) <= 1:
        return {}

    ordered = sorted(scores_by_symbol.items(), key=lambda item: item[1])
    n = len(ordered)

    # Average-rank tie handling: every symbol sharing a raw score value
    # gets the mean of the positions that tied group would have spanned.
    ranks: dict[str, float] = {}
    index = 0
    while index < n:
        group_end = index
        while group_end + 1 < n and ordered[group_end + 1][1] == ordered[index][1]:
            group_end += 1
        # Positions are 1-indexed for the standard rank formula; percentile
        # rank then divides by n so ties land on the correct SHARED
        # percentile rather than each tied member getting a distinct one.
        average_position = (index + 1 + group_end + 1) / 2.0
        percentile = average_position / n
        for tied_index in range(index, group_end + 1):
            symbol = ordered[tied_index][0]
            ranks[symbol] = percentile
        index = group_end + 1

    return ranks
