"""Tests for train.py's V5.1 Phase 3 (item 1) cross-sectional ranking
losses: soft_rank_within_groups(), soft_spearman_loss(), listnet_loss(),
compute_cross_sectional_ranking_loss(). Conventions match
tests/test_train_pipeline.py's rank-IC tests: hand-built synthetic groups,
no mocking."""

import numpy as np
import pytest
import torch

from train import (
    _rank_ic_from_arrays,
    compute_cross_sectional_ranking_loss,
    listnet_loss,
    masked_mse_loss,
    soft_rank_within_groups,
    soft_spearman_loss,
)


# ---------------------------------------------------------------------------
# soft_rank_within_groups
# ---------------------------------------------------------------------------


def test_soft_rank_within_groups_low_temperature_approaches_true_percentile_rank():
    scores = torch.tensor([3.0, 1.0, 4.0, 2.0])
    group_ids = torch.zeros(4, dtype=torch.int64)

    soft_ranks = soft_rank_within_groups(scores, group_ids, temperature=0.001)

    # True pandas-style pct rank (0-indexed/(n-1)): value 1.0 is smallest
    # (rank 0.0), 4.0 is largest (rank 1.0).
    expected = torch.tensor([2.0 / 3.0, 0.0, 1.0, 1.0 / 3.0])
    assert torch.allclose(soft_ranks, expected, atol=1e-3)


def test_soft_rank_within_groups_respects_group_boundaries():
    scores = torch.tensor([10.0, 1.0, 20.0, 2.0])
    group_ids = torch.tensor([0, 0, 1, 1])

    soft_ranks = soft_rank_within_groups(scores, group_ids, temperature=0.001)

    # Within group 0: 10.0 > 1.0 -> ranks [1.0, 0.0]. Within group 1: 20.0 > 2.0 -> ranks [1.0, 0.0].
    assert torch.allclose(soft_ranks, torch.tensor([1.0, 0.0, 1.0, 0.0]), atol=1e-3)


def test_soft_rank_within_groups_singleton_group_gets_neutral_half():
    scores = torch.tensor([5.0, 1.0, 2.0])
    group_ids = torch.tensor([0, 1, 1])

    soft_ranks = soft_rank_within_groups(scores, group_ids, temperature=0.001)

    assert soft_ranks[0].item() == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# soft_spearman_loss
# ---------------------------------------------------------------------------


def test_soft_spearman_loss_perfectly_ordered_group_approaches_minus_one():
    predictions = torch.tensor([1.0, 2.0, 3.0, 4.0], requires_grad=True)
    targets = torch.tensor([0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0])  # same order, already a pct rank
    group_ids = torch.zeros(4, dtype=torch.int64)
    mask = torch.ones(4, dtype=torch.bool)

    loss = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.01)

    assert loss.item() == pytest.approx(-1.0, abs=1e-2)


def test_soft_spearman_loss_perfectly_reversed_group_approaches_plus_one():
    predictions = torch.tensor([1.0, 2.0, 3.0, 4.0], requires_grad=True)
    targets = torch.tensor([1.0, 2.0 / 3.0, 1.0 / 3.0, 0.0])  # exactly reversed order
    group_ids = torch.zeros(4, dtype=torch.int64)
    mask = torch.ones(4, dtype=torch.bool)

    loss = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.01)

    assert loss.item() == pytest.approx(1.0, abs=1e-2)


def test_soft_spearman_loss_gradients_are_finite():
    torch.manual_seed(0)
    predictions = torch.randn(30, requires_grad=True)
    targets = torch.rand(30)
    group_ids = torch.randint(0, 4, (30,))
    mask = torch.ones(30, dtype=torch.bool)

    loss = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05)
    loss.backward()

    assert torch.isfinite(predictions.grad).all()


def test_soft_spearman_loss_empty_mask_returns_exact_zero():
    predictions = torch.randn(5)
    targets = torch.rand(5)
    group_ids = torch.zeros(5, dtype=torch.int64)
    mask = torch.zeros(5, dtype=torch.bool)

    loss = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05)

    assert loss.item() == 0.0


def test_soft_spearman_loss_all_nan_targets_returns_exact_zero():
    predictions = torch.randn(5)
    targets = torch.full((5,), float("nan"))
    group_ids = torch.zeros(5, dtype=torch.int64)
    mask = torch.ones(5, dtype=torch.bool)

    loss = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05)

    assert loss.item() == 0.0


def test_soft_spearman_loss_skips_zero_variance_group_rather_than_scoring_zero():
    # A group where every target is tied (zero variance) has an undefined
    # correlation - it must be SKIPPED, not counted as a 0.0 contribution -
    # verified here by comparing against a second group that has a real,
    # strong negative correlation: if the tied group were incorrectly
    # counted as 0.0, the mean would be pulled toward zero (roughly -0.5
    # instead of -1.0).
    predictions = torch.tensor([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])
    targets = torch.tensor([0.0, 0.5, 1.0, 0.5, 0.5, 0.5])  # group 1 (last 3) is all-tied
    group_ids = torch.tensor([0, 0, 0, 1, 1, 1])
    mask = torch.ones(6, dtype=torch.bool)

    loss = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.01)

    assert loss.item() == pytest.approx(-1.0, abs=1e-2)


def test_soft_spearman_loss_cross_validates_against_rank_ic_from_arrays_as_temperature_shrinks():
    # The single most valuable test in this phase (per the plan): as
    # temperature -> 0, soft_spearman_loss's per-group correlation must
    # converge to the SAME true Spearman correlation
    # _rank_ic_from_arrays() (the existing, already-trusted rank-IC metric)
    # computes on the identical data.
    rng = np.random.default_rng(11)
    n_per_date = 25
    num_dates = 6
    predictions_list = []
    targets_list = []
    dates_list = []
    for date_index in range(num_dates):
        raw_returns = rng.normal(size=n_per_date)
        predictions_list.append(raw_returns + rng.normal(scale=0.05, size=n_per_date))
        # target is the TRUE percentile rank of raw_returns (matches
        # build_cross_sectional_rank_targets()'s own convention).
        target_rank = np.argsort(np.argsort(raw_returns)) / (n_per_date - 1)
        targets_list.append(target_rank)
        dates_list.append(np.full(n_per_date, date_index))

    predictions_np = np.concatenate(predictions_list)
    targets_np = np.concatenate(targets_list)
    dates_np = np.concatenate(dates_list)

    true_ic = _rank_ic_from_arrays(predictions_np, targets_np, dates_np)["mean_ic"]

    predictions = torch.tensor(predictions_np, dtype=torch.float32)
    targets = torch.tensor(targets_np, dtype=torch.float32)
    group_ids = torch.tensor(dates_np, dtype=torch.int64)
    mask = torch.ones(len(predictions_np), dtype=torch.bool)

    loss_low_temp = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=1e-4)
    recovered_ic = -loss_low_temp.item()

    assert recovered_ic == pytest.approx(true_ic, abs=0.02)


# ---------------------------------------------------------------------------
# listnet_loss
# ---------------------------------------------------------------------------


def test_listnet_loss_is_never_negative():
    torch.manual_seed(1)
    predictions = torch.randn(20)
    targets = torch.rand(20)
    group_ids = torch.randint(0, 3, (20,))
    mask = torch.ones(20, dtype=torch.bool)

    loss = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1)

    assert loss.item() >= 0.0


def test_listnet_loss_is_smaller_when_predictions_agree_with_targets():
    group_ids = torch.zeros(5, dtype=torch.int64)
    mask = torch.ones(5, dtype=torch.bool)
    targets = torch.tensor([0.1, 0.9, 0.5, 0.3, 0.7])

    agreeing_predictions = targets.clone()
    disagreeing_predictions = torch.tensor([0.9, 0.1, 0.5, 0.7, 0.3])  # reversed

    loss_agreeing = listnet_loss(agreeing_predictions, targets, group_ids, mask, temperature=0.1)
    loss_disagreeing = listnet_loss(disagreeing_predictions, targets, group_ids, mask, temperature=0.1)

    assert loss_agreeing.item() < loss_disagreeing.item()


def test_listnet_loss_empty_mask_returns_exact_zero():
    predictions = torch.randn(4)
    targets = torch.rand(4)
    group_ids = torch.zeros(4, dtype=torch.int64)
    mask = torch.zeros(4, dtype=torch.bool)

    loss = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1)

    assert loss.item() == 0.0


def test_listnet_loss_gradients_are_finite():
    torch.manual_seed(2)
    predictions = torch.randn(15, requires_grad=True)
    targets = torch.rand(15)
    group_ids = torch.randint(0, 3, (15,))
    mask = torch.ones(15, dtype=torch.bool)

    loss = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1)
    loss.backward()

    assert torch.isfinite(predictions.grad).all()


# ---------------------------------------------------------------------------
# compute_cross_sectional_ranking_loss - the dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_mse_objective_matches_masked_mse_loss_exactly():
    predictions = torch.randn(10)
    targets = torch.rand(10)
    group_ids = torch.randint(0, 2, (10,))

    dispatched = compute_cross_sectional_ranking_loss(predictions, targets, group_ids, {"objective": "mse"})
    direct = masked_mse_loss(predictions, targets, ~torch.isnan(targets))

    assert torch.isclose(dispatched, direct)


def test_dispatcher_default_objective_is_mse_when_absent():
    predictions = torch.randn(10)
    targets = torch.rand(10)
    group_ids = torch.randint(0, 2, (10,))

    dispatched = compute_cross_sectional_ranking_loss(predictions, targets, group_ids, {})
    direct = masked_mse_loss(predictions, targets, ~torch.isnan(targets))

    assert torch.isclose(dispatched, direct)


def test_dispatcher_soft_spearman_adds_mse_anchor_term():
    predictions = torch.tensor([1.0, 2.0, 3.0, 4.0])
    targets = torch.tensor([0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0])
    group_ids = torch.zeros(4, dtype=torch.int64)

    no_anchor = compute_cross_sectional_ranking_loss(
        predictions, targets, group_ids, {"objective": "soft_spearman", "temperature": 0.01, "mse_anchor_weight": 0.0}
    )
    with_anchor = compute_cross_sectional_ranking_loss(
        predictions, targets, group_ids, {"objective": "soft_spearman", "temperature": 0.01, "mse_anchor_weight": 1.0}
    )

    # Adding a positive-weighted MSE anchor on top of a (near -1) ranking
    # loss strictly increases the combined value here (predictions are not
    # numerically identical to targets, so the MSE term is > 0).
    assert with_anchor.item() > no_anchor.item()


def test_dispatcher_unknown_objective_raises():
    predictions = torch.randn(4)
    targets = torch.rand(4)
    group_ids = torch.zeros(4, dtype=torch.int64)

    with pytest.raises(ValueError):
        compute_cross_sectional_ranking_loss(predictions, targets, group_ids, {"objective": "not_a_real_objective"})


def test_dispatcher_listnet_uses_listnet_temperature_when_provided():
    torch.manual_seed(3)
    predictions = torch.randn(10)
    targets = torch.rand(10)
    group_ids = torch.zeros(10, dtype=torch.int64)

    result_a = compute_cross_sectional_ranking_loss(
        predictions, targets, group_ids, {"objective": "listnet", "listnet_temperature": 0.01, "mse_anchor_weight": 0.0}
    )
    result_b = compute_cross_sectional_ranking_loss(
        predictions, targets, group_ids, {"objective": "listnet", "listnet_temperature": 5.0, "mse_anchor_weight": 0.0}
    )

    # Different temperatures on the same inputs must produce different
    # loss values (temperature genuinely changes the softmax sharpness).
    assert result_a.item() != pytest.approx(result_b.item())


# ---------------------------------------------------------------------------
# date_weights (V5.2.8, development/Problems.md #94)
# ---------------------------------------------------------------------------


def test_soft_spearman_loss_date_weights_none_matches_omitted():
    torch.manual_seed(5)
    predictions = torch.randn(8)
    targets = torch.rand(8)
    group_ids = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    mask = torch.ones(8, dtype=torch.bool)

    omitted = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05)
    explicit_none = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05, date_weights=None)

    assert torch.equal(omitted, explicit_none)


def test_soft_spearman_loss_uniform_weights_match_unweighted():
    torch.manual_seed(6)
    predictions = torch.randn(8)
    targets = torch.rand(8)
    group_ids = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    mask = torch.ones(8, dtype=torch.bool)

    unweighted = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05)
    uniformly_weighted = soft_spearman_loss(
        predictions, targets, group_ids, mask, temperature=0.05, date_weights=torch.ones(8)
    )

    assert torch.allclose(unweighted, uniformly_weighted, atol=1e-6)


def test_soft_spearman_loss_down_weighting_a_date_changes_the_loss():
    torch.manual_seed(7)
    predictions = torch.randn(8)
    targets = torch.rand(8)
    group_ids = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    mask = torch.ones(8, dtype=torch.bool)
    weights = torch.tensor([1.0, 1.0, 1.0, 1.0, 0.1, 0.1, 0.1, 0.1])

    unweighted = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05)
    weighted = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05, date_weights=weights)

    assert unweighted.item() != pytest.approx(weighted.item())


def test_listnet_loss_date_weights_none_matches_omitted():
    torch.manual_seed(8)
    predictions = torch.randn(8)
    targets = torch.rand(8)
    group_ids = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    mask = torch.ones(8, dtype=torch.bool)

    omitted = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1)
    explicit_none = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1, date_weights=None)

    assert torch.equal(omitted, explicit_none)


def test_listnet_loss_uniform_weights_match_unweighted():
    torch.manual_seed(9)
    predictions = torch.randn(8)
    targets = torch.rand(8)
    group_ids = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    mask = torch.ones(8, dtype=torch.bool)

    unweighted = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1)
    uniformly_weighted = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1, date_weights=torch.ones(8))

    assert torch.allclose(unweighted, uniformly_weighted, atol=1e-6)


def test_listnet_loss_down_weighting_a_date_changes_the_loss():
    torch.manual_seed(10)
    predictions = torch.randn(8)
    targets = torch.rand(8)
    group_ids = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    mask = torch.ones(8, dtype=torch.bool)
    weights = torch.tensor([1.0, 1.0, 1.0, 1.0, 0.1, 0.1, 0.1, 0.1])

    unweighted = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1)
    weighted = listnet_loss(predictions, targets, group_ids, mask, temperature=0.1, date_weights=weights)

    assert unweighted.item() != pytest.approx(weighted.item())


def test_dispatcher_date_weights_none_matches_omitted_for_soft_spearman():
    torch.manual_seed(11)
    predictions = torch.randn(8)
    targets = torch.rand(8)
    group_ids = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    config = {"objective": "soft_spearman", "temperature": 0.05, "mse_anchor_weight": 0.1}

    omitted = compute_cross_sectional_ranking_loss(predictions, targets, group_ids, config)
    explicit_none = compute_cross_sectional_ranking_loss(predictions, targets, group_ids, config, date_weights=None)

    assert torch.equal(omitted, explicit_none)


def test_dispatcher_date_weights_does_not_affect_mse_anchor_term():
    """The mse_anchor_weight term anchors output SCALE, not the ranking
    objective itself - date_weights must never reach it. Isolate this by
    comparing the "with weights" case against a manually-computed
    weighted-ranking-loss-plus-UNWEIGHTED-anchor value."""
    torch.manual_seed(12)
    predictions = torch.randn(8)
    targets = torch.rand(8)
    group_ids = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])
    mask = torch.ones(8, dtype=torch.bool)
    weights = torch.tensor([1.0, 1.0, 1.0, 1.0, 0.1, 0.1, 0.1, 0.1])
    config = {"objective": "soft_spearman", "temperature": 0.05, "mse_anchor_weight": 0.3}

    combined = compute_cross_sectional_ranking_loss(predictions, targets, group_ids, config, date_weights=weights)
    expected_ranking = soft_spearman_loss(predictions, targets, group_ids, mask, temperature=0.05, date_weights=weights)
    expected_anchor = masked_mse_loss(predictions, targets, mask)

    assert combined.item() == pytest.approx((expected_ranking + 0.3 * expected_anchor).item(), abs=1e-6)
