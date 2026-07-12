"""Tests for train.py's Phase 4 (5/10 -> 9/10 roadmap) walk-forward
retraining functions: generate_walk_forward_windows(), summarize_walk_forward_run().
"""

import pandas as pd
import pytest

from train import generate_walk_forward_windows, summarize_walk_forward_run


def _common_window(start: str, end: str) -> dict:
    return {"start": start, "end": end}


def _to_date(value: str) -> pd.Timestamp:
    return pd.Timestamp(value)


# ---------------------------------------------------------------------------
# generate_walk_forward_windows
# ---------------------------------------------------------------------------


def test_generate_walk_forward_windows_returns_empty_when_range_too_short():
    common_window = _common_window("2020-01-01", "2020-01-10")

    windows = generate_walk_forward_windows(
        common_window, train_span_days=100, validation_span_days=30, backtest_span_days=30, step_days=30
    )

    assert windows == []


def test_generate_walk_forward_windows_produces_at_least_one_window_when_range_fits():
    common_window = _common_window("2020-01-01", "2020-12-31")

    windows = generate_walk_forward_windows(
        common_window, train_span_days=200, validation_span_days=60, backtest_span_days=60, step_days=60
    )

    assert len(windows) >= 1
    first = windows[0]
    assert set(first.keys()) == {"training", "validation", "backtest"}
    assert first["training"]["start"] == "2020-01-01"


def test_generate_walk_forward_windows_rolling_shifts_train_start_each_window():
    common_window = _common_window("2020-01-01", "2021-12-31")

    windows = generate_walk_forward_windows(
        common_window, train_span_days=180, validation_span_days=30, backtest_span_days=30, step_days=60, mode="rolling"
    )

    assert len(windows) >= 2
    # Rolling: fixed-length train span, start shifts forward by step_days.
    first_start = windows[0]["training"]["start"]
    second_start = windows[1]["training"]["start"]
    assert second_start > first_start
    first_span = (
        _to_date(windows[0]["training"]["end"]) - _to_date(windows[0]["training"]["start"])
    ).days + 1
    second_span = (
        _to_date(windows[1]["training"]["end"]) - _to_date(windows[1]["training"]["start"])
    ).days + 1
    assert first_span == second_span == 180


def test_generate_walk_forward_windows_expanding_keeps_train_start_fixed():
    common_window = _common_window("2020-01-01", "2021-12-31")

    windows = generate_walk_forward_windows(
        common_window, train_span_days=180, validation_span_days=30, backtest_span_days=30, step_days=60, mode="expanding"
    )

    assert len(windows) >= 2
    # Expanding: train_start fixed, train_end grows each window.
    assert all(window["training"]["start"] == "2020-01-01" for window in windows)
    first_end = windows[0]["training"]["end"]
    second_end = windows[1]["training"]["end"]
    assert second_end > first_end


def test_generate_walk_forward_windows_sub_ranges_are_contiguous_within_a_window():
    common_window = _common_window("2020-01-01", "2020-12-31")

    windows = generate_walk_forward_windows(
        common_window, train_span_days=100, validation_span_days=30, backtest_span_days=30, step_days=30
    )

    window = windows[0]
    one_day = pd.Timedelta(days=1)
    assert _to_date(window["validation"]["start"]) == _to_date(window["training"]["end"]) + one_day
    assert _to_date(window["backtest"]["start"]) == _to_date(window["validation"]["end"]) + one_day


def test_generate_walk_forward_windows_never_exceeds_common_window_end():
    common_window = _common_window("2020-01-01", "2020-06-30")

    windows = generate_walk_forward_windows(
        common_window, train_span_days=60, validation_span_days=20, backtest_span_days=20, step_days=15
    )

    for window in windows:
        assert _to_date(window["backtest"]["end"]) <= _to_date("2020-06-30")


# ---------------------------------------------------------------------------
# summarize_walk_forward_run
# ---------------------------------------------------------------------------


def test_summarize_walk_forward_run_counts_windows():
    summary = summarize_walk_forward_run([0.02, 0.03, 0.01])

    assert summary["num_windows"] == 3
    assert summary["per_window_metric_values"] == [0.02, 0.03, 0.01]


def test_summarize_walk_forward_run_includes_cross_window_bootstrap():
    summary = summarize_walk_forward_run([0.05, 0.04, 0.06, 0.05, 0.03])

    assert "cross_window_bootstrap" in summary
    assert summary["cross_window_bootstrap"]["num_observations"] == 5
    assert summary["cross_window_bootstrap"]["lower_bound"] <= summary["cross_window_bootstrap"]["mean_ic"]


def test_summarize_walk_forward_run_empty_list_is_degenerate_not_raise():
    summary = summarize_walk_forward_run([])

    assert summary["num_windows"] == 0
    assert summary["cross_window_bootstrap"]["num_observations"] == 0
