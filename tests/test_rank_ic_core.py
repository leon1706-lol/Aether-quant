"""Tests for evaluation/rank_ic_core.py (V5.3.5, development/Problems.md
#102) - the canonical home for this codebase's rank-IC correlation math
and realized-outcome resolution, extracted from train.py/
performance/rank_ic_monitor.py so main.py's live decision path can import
it without pulling in the training stack. Imports directly from this
module (not via the train.py/rank_ic_monitor.py re-export aliases, which
have their own exhaustive coverage in tests/test_train_ranking_loss.py
and tests/test_rank_ic_monitor.py respectively - those files being
re-run unmodified and still passing is itself the proof the move is
behavior-preserving). This file's job is narrower: prove the new
canonical module is correct on its own, directly.
"""

import numpy as np
import pytest

from evaluation.rank_ic_core import (
    aggregate_rank_ic_observations,
    rank_ic_from_arrays,
    resolve_realized_rank_ic_observations,
)


# ---------------------------------------------------------------------------
# rank_ic_from_arrays
# ---------------------------------------------------------------------------


def test_rank_ic_from_arrays_perfect_correlation_gives_ic_of_one():
    predictions = np.array([0.9, 0.5, 0.1])
    targets = np.array([1.0, 0.5, 0.0])
    dates = np.array(["2020-01-01"] * 3)

    result = rank_ic_from_arrays(predictions, targets, dates)

    assert result["mean_ic"] == pytest.approx(1.0)
    assert result["num_dates"] == 1


def test_rank_ic_from_arrays_perfect_inverse_correlation_gives_ic_of_minus_one():
    predictions = np.array([0.1, 0.5, 0.9])
    targets = np.array([1.0, 0.5, 0.0])
    dates = np.array(["2020-01-01"] * 3)

    result = rank_ic_from_arrays(predictions, targets, dates)

    assert result["mean_ic"] == pytest.approx(-1.0)


def test_rank_ic_from_arrays_empty_input_is_degenerate_not_raise():
    result = rank_ic_from_arrays(np.array([]), np.array([]), np.array([]))
    assert result == {"mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0, "num_dates": 0, "ic_values": []}


def test_rank_ic_from_arrays_skips_dates_with_fewer_than_two_assets():
    predictions = np.array([0.9, 0.1, 0.9])
    targets = np.array([1.0, 0.0, 1.0])
    dates = np.array(["2020-01-01", "2020-01-01", "2020-01-02"])  # second date has only 1 row

    result = rank_ic_from_arrays(predictions, targets, dates)

    assert result["num_dates"] == 1


def test_rank_ic_from_arrays_min_names_per_date_excludes_thin_dates():
    # A 2-name date is mathematically forced to +-1 (two points always fit
    # a line) regardless of real skill - min_names_per_date=3 must exclude
    # it, leaving only the well-populated date.
    predictions = np.array([0.9, 0.1, 0.9, 0.5, 0.1])
    targets = np.array([1.0, 0.0, 1.0, 0.5, 0.0])
    dates = np.array(["2020-01-01", "2020-01-01", "2020-01-02", "2020-01-02", "2020-01-02"])

    default_result = rank_ic_from_arrays(predictions, targets, dates)
    filtered_result = rank_ic_from_arrays(predictions, targets, dates, min_names_per_date=3)

    assert default_result["num_dates"] == 2
    assert filtered_result["num_dates"] == 1


def test_rank_ic_from_arrays_min_names_per_date_default_preserves_original_behavior():
    predictions = np.array([0.9, 0.1])
    targets = np.array([1.0, 0.0])
    dates = np.array(["2020-01-01", "2020-01-01"])

    result = rank_ic_from_arrays(predictions, targets, dates)

    assert result["num_dates"] == 1  # unchanged: default min_names_per_date=2 still allows a 2-name date


def test_rank_ic_from_arrays_non_overlapping_stride_subsamples_dates():
    rng = np.random.default_rng(0)
    dates = np.repeat([f"2020-01-{day:02d}" for day in range(1, 11)], 3)
    predictions = rng.normal(size=len(dates))
    targets = rng.normal(size=len(dates))

    full = rank_ic_from_arrays(predictions, targets, dates, non_overlapping_stride=1)
    strided = rank_ic_from_arrays(predictions, targets, dates, non_overlapping_stride=5)

    assert strided["num_dates"] < full["num_dates"]


# ---------------------------------------------------------------------------
# resolve_realized_rank_ic_observations
# ---------------------------------------------------------------------------


def test_resolve_realized_rank_ic_observations_resolves_after_horizon_elapses():
    events = [
        {"ticker": "AAPL", "created_at": f"2020-01-{day:02d}T00:00:00Z", "resolved_predicted_rank_20d": 0.5, "close_price": 100.0 + day}
        for day in range(1, 26)
    ]

    observations = resolve_realized_rank_ic_observations(events, horizon_days=20)

    assert len(observations) == 5
    assert observations[0]["ticker"] == "AAPL"


def test_resolve_realized_rank_ic_observations_computes_correct_realized_return():
    closes = [100.0] * 21
    closes[20] = 110.0
    events = [
        {"ticker": "AAPL", "created_at": f"2020-01-{day:02d}T00:00:00Z", "resolved_predicted_rank_20d": 0.5, "close_price": closes[day - 1]}
        for day in range(1, 22)
    ]

    observations = resolve_realized_rank_ic_observations(events, horizon_days=20)

    assert len(observations) == 1
    assert observations[0]["realized_return_20d"] == pytest.approx(0.10)


def test_resolve_realized_rank_ic_observations_empty_events_returns_empty():
    assert resolve_realized_rank_ic_observations([], horizon_days=20) == []


# ---------------------------------------------------------------------------
# aggregate_rank_ic_observations
# ---------------------------------------------------------------------------


def test_aggregate_rank_ic_observations_empty_is_degenerate_not_raise():
    result = aggregate_rank_ic_observations([])
    assert result == {"mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0, "num_dates": 0, "ic_values": []}


def test_aggregate_rank_ic_observations_perfect_correlation():
    observations = [
        {"origin_date": "2020-01-01", "resolved_predicted_rank_20d": 0.9, "realized_rank_20d": 1.0},
        {"origin_date": "2020-01-01", "resolved_predicted_rank_20d": 0.5, "realized_rank_20d": 0.5},
        {"origin_date": "2020-01-01", "resolved_predicted_rank_20d": 0.1, "realized_rank_20d": 0.0},
    ]

    result = aggregate_rank_ic_observations(observations)

    assert result["mean_ic"] == pytest.approx(1.0)
