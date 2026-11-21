"""Training mechanics shared by the trainers and the lab (moved unchanged from train.py in V6.7.1): seeding, optimizer
and scheduler, weight averaging, early stopping, whole-date batches. `train.py` re-exports every name.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import Sampler


def set_seed(seed: int) -> None:
    """Seed Python, numpy and torch (CPU and CUDA) for a reproducible run."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# ---------------------------------------------------------------------------
# V5.1 Phase 3 (items 10, 11) - optimizer/schedule/SWA/smoothing helpers
# shared by train_multitask.py and train_sequence.py (the train.py-as-
# master-module convention every other trainer utility in this file
# already follows).
# ---------------------------------------------------------------------------


def build_optimizer(model: nn.Module, training_config: dict[str, Any]) -> torch.optim.Optimizer:
    """Dispatches on training_config["optimizer"] in {"adam", "adamw"} -
    "adam" is the FUNCTION default (preserving every existing caller's
    behavior byte-for-byte when the config key is absent), "adamw" is
    config.json's new default for the multitask/sequence trainers
    specifically.

    GUARDRAIL: weight_decay under AdamW is DECOUPLED from the learning
    rate (Loshchilov & Hutter 2019) - not comparable to the same numeric
    value under plain Adam (coupled, effectively scaled by lr).
    config.json's weight_decay was re-tuned upward (1e-4 -> 1e-2)
    specifically alongside this switch - never carry the old Adam-tuned
    value over to AdamW unchanged."""
    optimizer_name = str(training_config.get("optimizer", "adam")).lower()
    learning_rate = float(training_config.get("learning_rate", 0.0007))
    weight_decay = float(training_config.get("weight_decay", 0.0001))
    if optimizer_name == "adamw":
        return torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    return torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)


def build_lr_scheduler(optimizer: torch.optim.Optimizer, training_config: dict[str, Any], max_epochs: int) -> torch.optim.lr_scheduler.LRScheduler | None:
    """Dispatches on training_config["lr_schedule"] in {"none", "cosine"} -
    "none" is the FUNCTION default (returns None - a caller that never
    calls scheduler.step() is completely unaffected by this function
    existing). "cosine" is config.json's new default: CosineAnnealingLR
    decaying the optimizer's current LR down to lr * lr_min_factor over
    max_epochs."""
    schedule_name = str(training_config.get("lr_schedule", "none")).lower()
    if schedule_name != "cosine":
        return None
    lr_min_factor = float(training_config.get("lr_min_factor", 0.05))
    base_lr = float(optimizer.param_groups[0]["lr"])
    return torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=max(int(max_epochs), 1), eta_min=base_lr * lr_min_factor
    )


def swa_accumulate(averaged_state: dict[str, Any] | None, model_state: dict[str, Any], count: int) -> tuple[dict, int]:
    """Elementwise running mean over state_dict()s - a plain, from-scratch
    accumulator, deliberately NOT torch.optim.swa_utils.AveragedModel.

    GUARDRAIL: AveragedModel wraps the model with a `module.`-prefixed
    state_dict, which would silently break export_state_dict()/
    export_*_architecture() (both read the raw module's own keys). No
    update_bn() pass is needed either - neither model has any BatchNorm
    (LayerNorm only, which carries no running statistics to recompute).

    GUARDRAIL (pre-empting the obvious objection): this is WITHIN-RUN
    averaging of late-training checkpoints along a SINGLE SGD trajectory -
    the weights are aligned by construction (same init, same optimizer
    path, different epochs), which is the valid case (Izmailov et al.
    2018, Stochastic Weight Averaging). This is NOT the CROSS-SEED weight
    averaging average_ensemble_predictions()'s own docstring correctly
    rejects on permutation-symmetry grounds (two independently-seeded
    runs' hidden units are not aligned, so averaging THEIR weights is
    invalid) - averaging one run's own late-epoch weights against itself
    is a different, well-established technique. Do not conflate the two,
    and do not "fix" this into calling average_ensemble_predictions()'s
    machinery instead.

    averaged_state=None (first call) seeds the accumulator with
    model_state verbatim (count becomes 1, an exact copy - not yet an
    "average" of anything). Returns (new_averaged_state, new_count)."""
    if averaged_state is None:
        return {key: value.clone() for key, value in model_state.items()}, 1
    new_count = count + 1
    new_averaged_state = {key: (averaged_state[key] * count + model_state[key]) / new_count for key in averaged_state}
    return new_averaged_state, new_count


def swa_finalize(averaged_state: dict[str, Any]) -> dict[str, Any]:
    """No-op passthrough today, kept as a named step pairing with
    swa_accumulate() in case a future normalization-recompute pass is ever
    needed here (there is none currently - see swa_accumulate()'s own
    docstring on why no update_bn() equivalent is needed)."""
    return averaged_state


def smoothed_metric(history: list[dict], key: str, window: int) -> float | None:
    """Mean of the last `window` non-None values of history[i][key] - the
    early-stopping monitor for a noisy per-epoch metric. A 365-day
    validation split at stride 20 gives ~18 non-overlapping rank-IC
    observations, so epoch-to-epoch that metric is noisy enough that
    early-stopping on the RAW value reliably picks a lucky epoch rather
    than a genuinely-better one. window=1 reproduces "monitor the raw
    latest value" exactly (today's behavior, byte-for-byte).

    Returns None (never 0.0 - a missing metric must not look like a
    genuine zero) when no history entry has this key with a non-None
    value yet."""
    values = [entry[key] for entry in history if entry.get(key) is not None]
    if not values:
        return None
    window = max(int(window), 1)
    recent = values[-window:]
    return sum(recent) / len(recent)


def is_new_best_epoch(
    candidate_metric: float,
    best_metric_so_far: float,
    epoch: int,
    min_epoch: int = 3,
) -> bool:
    """Shared early-stopping decision for every direction-classification
    trainer (train_model/_train_expert_classifier here; train_multitask.py/
    train_sequence.py/train_gating.py call this too). Monitors a SKILL
    metric (validation balanced_accuracy - higher is better), not raw
    validation loss.

    Root cause this fixes (development/Problems.md): with near-flat logits,
    validation BCE loss was observed lowest at epoch 1 and rising every
    epoch after - so the old "epoch with min validation loss" rule shipped
    best_epoch=1 for the baseline, multitask AND sequence models alike: the
    checkpoint shipped was essentially the random initialization. Loss and
    balanced-accuracy are not the same surface - the network can still
    improve its decision boundary (balanced-accuracy) for a few epochs even
    while its calibration (BCE loss) degrades, which is exactly what a
    near-noise label produces. `min_epoch` additionally refuses to
    ship an epoch-1/2 checkpoint at all (returns False for epoch <
    min_epoch), forcing at least a few real gradient updates before any
    checkpoint becomes eligible, so a network that never improves past its
    initialization is at least given the chance to."""
    if epoch < min_epoch:
        return False
    return candidate_metric > best_metric_so_far


# ---------------------------------------------------------------------------
# V5.1 Phase 3 (items 1, 10, 11) - cross-sectional date batching, so a
# training batch is a set of WHOLE dates (every asset trading that day)
# rather than a random row sample - the ranking losses below need this to
# compute a per-date rank/softmax, exactly the same grouping
# build_cross_sectional_rank_targets()/_rank_ic_from_arrays() already use
# offline. Pure numpy, no torch - fully unit-testable without a model.
# ---------------------------------------------------------------------------


def build_cross_sectional_date_batches(
    dates: np.ndarray, *, batch_dates: int, min_group_size: int, shuffle: bool, seed: int
) -> list[np.ndarray]:
    """Groups row indices by date, drops dates with fewer than
    min_group_size rows (same "too few names is meaningless" rationale as
    build_cross_sectional_rank_targets()'s min_universe_size), then packs
    `batch_dates` whole dates per batch. Returns a list of row-index arrays
    (dtype int64) - each array is one training batch's row selection into
    the ORIGINAL `dates` array (and, by extension, into a parallel
    features/targets tensor built in the same row order).

    shuffle=True shuffles the DATE order (not rows within a date - every
    row of a kept date always lands in the same batch as its peers) with a
    seeded RNG, so batch composition is reproducible per (seed, epoch).
    shuffle=False keeps dates in their natural sorted order - deterministic,
    used by validation/backtest passes that iterate the whole split once.

    batch_dates <= 0 is treated as 1 (never an empty/negative batch)."""
    batch_dates = max(int(batch_dates), 1)
    frame = pd.DataFrame({"date": np.asarray(dates), "row": np.arange(len(dates))})
    group_sizes = frame.groupby("date")["row"].transform("size")
    eligible = frame[group_sizes >= min_group_size]

    unique_dates = eligible["date"].unique().tolist()
    if shuffle:
        rng = np.random.default_rng(seed)
        rng.shuffle(unique_dates)
    else:
        unique_dates = sorted(unique_dates)

    rows_by_date = {date_value: group["row"].to_numpy(dtype=np.int64) for date_value, group in eligible.groupby("date")}

    batches: list[np.ndarray] = []
    for start in range(0, len(unique_dates), batch_dates):
        chunk_dates = unique_dates[start : start + batch_dates]
        batch_rows = np.concatenate([rows_by_date[date_value] for date_value in chunk_dates])
        batches.append(batch_rows)
    return batches


class CrossSectionalDateBatchSampler(Sampler[list[int]]):
    """torch Sampler wrapper around build_cross_sectional_date_batches() -
    yields one list[int] (row indices) per whole-date batch, for use as
    DataLoader's `batch_sampler`. set_epoch() re-derives the shuffle seed
    per epoch (seed + epoch) so batch composition varies epoch to epoch
    the same way a random-sampling DataLoader's shuffle=True already does,
    while every batch still contains only whole dates."""

    def __init__(self, dates: np.ndarray, *, batch_dates: int, min_group_size: int, shuffle: bool, seed: int) -> None:
        self.dates = np.asarray(dates)
        self.batch_dates = batch_dates
        self.min_group_size = min_group_size
        self.shuffle = shuffle
        self.seed = seed
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        self.epoch = epoch

    def _batches(self) -> list[np.ndarray]:
        return build_cross_sectional_date_batches(
            self.dates,
            batch_dates=self.batch_dates,
            min_group_size=self.min_group_size,
            shuffle=self.shuffle,
            seed=self.seed + self.epoch,
        )

    def __iter__(self):
        for batch in self._batches():
            yield batch.tolist()

    def __len__(self) -> int:
        return len(self._batches())


def build_date_group_ids(dates: np.ndarray) -> np.ndarray:
    """Dense integer group id per row (0, 1, 2, ... one id per unique date,
    in sorted-date order) - the ranking losses below scatter/loop by this
    id rather than the raw date value (a torch.Tensor of ids is simpler to
    index with than a tensor of dates/strings). Pure numpy, int64."""
    _, inverse = np.unique(np.asarray(dates), return_inverse=True)
    return inverse.astype(np.int64)


def select_device(prefer: str = "auto") -> str:
    """'cuda' when asked for (or 'auto') and available, else 'cpu'. The production trainers stay on CPU; the lab may use a GPU."""
    if prefer == "cpu":
        return "cpu"
    if prefer in {"auto", "cuda"} and torch.cuda.is_available():
        return "cuda"
    if prefer == "cuda":
        raise RuntimeError("train.device = cuda, but torch sees no CUDA device")
    return "cpu"
