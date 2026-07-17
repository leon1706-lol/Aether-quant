"""Tests for train.py's find_optimal_threshold() degeneracy guard and
is_new_best_epoch() skill-metric early-stopping (development/Problems.md).

Root cause these fix: with near-flat model logits, MCC's weak maximum tends
to sit at a near-degenerate operating point (positive_rate near 0 or 1), and
monitoring validation LOSS for early stopping shipped the checkpoint from
epoch 1 - essentially the untrained random initialization - for the
baseline, multitask AND sequence models alike.
"""

import torch
import torch.nn as nn

from train import compute_binary_metrics, find_optimal_threshold, is_new_best_epoch


def test_is_new_best_epoch_refuses_before_min_epoch():
    # Even a big improvement is refused before min_epoch - forces at least a
    # few real gradient updates before any checkpoint becomes eligible.
    assert is_new_best_epoch(candidate_metric=0.9, best_metric_so_far=0.5, epoch=1, min_epoch=3) is False
    assert is_new_best_epoch(candidate_metric=0.9, best_metric_so_far=0.5, epoch=2, min_epoch=3) is False


def test_is_new_best_epoch_accepts_improvement_at_or_after_min_epoch():
    assert is_new_best_epoch(candidate_metric=0.6, best_metric_so_far=0.5, epoch=3, min_epoch=3) is True
    assert is_new_best_epoch(candidate_metric=0.6, best_metric_so_far=0.5, epoch=10, min_epoch=3) is True


def test_is_new_best_epoch_rejects_non_improvement():
    assert is_new_best_epoch(candidate_metric=0.5, best_metric_so_far=0.5, epoch=5, min_epoch=3) is False
    assert is_new_best_epoch(candidate_metric=0.4, best_metric_so_far=0.5, epoch=5, min_epoch=3) is False


def _flat_logits_and_targets(n: int = 200, positive_rate: float = 0.55) -> tuple[torch.Tensor, torch.Tensor]:
    """Near-constant logits (all close to 0, i.e. sigmoid ~= 0.5) with a
    fixed target positive rate - simulates a model with ~no discriminative
    power, the exact regime that made the old unconstrained threshold
    search pick a degenerate corner (confirmed live: threshold 0.46 ->
    positive_rate 0.91, or 0.545 -> positive_rate 0.0004)."""
    torch.manual_seed(0)
    logits = torch.randn(n) * 0.05  # tiny spread around 0 -> sigmoid ~0.5 +- noise
    n_positive = int(n * positive_rate)
    targets = torch.cat([torch.ones(n_positive), torch.zeros(n - n_positive)])
    return logits, targets


def test_find_optimal_threshold_avoids_degenerate_positive_rate_on_flat_logits():
    logits, targets = _flat_logits_and_targets(positive_rate=0.55)
    criterion = nn.BCEWithLogitsLoss()

    threshold, metrics = find_optimal_threshold(
        logits, targets, criterion, "mcc", 0.05, 0.95, 91, min_positive_rate=0.15, max_positive_rate=0.85
    )

    assert 0.15 <= metrics["positive_rate"] <= 0.85, (
        f"selected threshold {threshold} produced a degenerate positive_rate {metrics['positive_rate']}"
    )


def test_find_optimal_threshold_falls_back_to_unconstrained_when_everything_degenerate():
    # Every logit pushes hard toward one class - even the best UNCONSTRAINED
    # threshold across the whole sweep can't avoid a near-0/near-1
    # positive_rate. The function must still return something (not raise),
    # falling back to the plain best-scoring threshold rather than the
    # never-searched default 0.5.
    torch.manual_seed(0)
    n = 200
    logits = torch.cat([torch.full((190,), 5.0), torch.full((10,), -5.0)])
    targets = torch.cat([torch.ones(190), torch.zeros(10)])
    criterion = nn.BCEWithLogitsLoss()

    threshold, metrics = find_optimal_threshold(
        logits, targets, criterion, "mcc", 0.05, 0.95, 91, min_positive_rate=0.15, max_positive_rate=0.85
    )

    assert 0.0 <= threshold <= 1.0
    assert metrics["positive_rate"] > 0.85  # confirms the degenerate case was actually hit


def test_find_optimal_threshold_respects_band_bounds_and_scores_faithfully():
    # A well-separated, genuinely discriminative logit distribution should
    # comfortably find a non-degenerate threshold matching the unconstrained
    # optimum (band shouldn't distort an already-good search).
    torch.manual_seed(0)
    positive_logits = torch.randn(100) * 0.3 + 2.0
    negative_logits = torch.randn(100) * 0.3 - 2.0
    logits = torch.cat([positive_logits, negative_logits])
    targets = torch.cat([torch.ones(100), torch.zeros(100)])
    criterion = nn.BCEWithLogitsLoss()

    threshold, metrics = find_optimal_threshold(logits, targets, criterion, "mcc", 0.05, 0.95, 91)

    assert 0.15 <= metrics["positive_rate"] <= 0.85
    assert metrics["mcc"] > 0.8  # well-separated data should score close to perfect
