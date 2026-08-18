"""Tests for evaluation/rolling_ic_gate_replay.py (V5.3.5,
development/Problems.md #102). Conventions match
tests/test_kill_switch_replay.py's style against
replay_kill_switch_over_dataset() - this module's
replay_rolling_ic_gate_over_dataset() is its direct sibling for the new
gate.
"""

import pandas as pd
import pytest

from evaluation.rolling_ic_gate_replay import (
    replay_rolling_ic_gate_over_dataset,
    summarize_rolling_ic_gate_replay,
)


def _two_era_dataset(num_tickers: int = 4, num_days: int = 60, flip_at: int = 30) -> pd.DataFrame:
    """Skillful (score tracks per-ticker rank) for the first `flip_at`
    days, then shuffled/no-skill for the rest - same synthetic shape as
    tests/test_rolling_ic_gate_calibration.py's _synthetic_dataset(), reused
    here to test the REPLAY (per-date decision), not the calibration
    (aggregate distribution)."""
    rows = []
    tickers = [f"T{index}" for index in range(num_tickers)]
    ticker_growth = {ticker: 1.0 + 0.01 * rank for rank, ticker in enumerate(tickers)}
    for day in range(num_days):
        date = f"2020-{1 + day // 28:02d}-{1 + day % 28:02d}"
        skillful_era = day < flip_at
        for rank, ticker in enumerate(tickers):
            close = 100.0 * (ticker_growth[ticker] ** day)
            raw_score = float(rank) if skillful_era else float(num_tickers - 1 - rank)
            rows.append({"ticker": ticker, "date": date, "close": close, "raw_score": raw_score})
    return pd.DataFrame(rows)


def _all_dates(dataset: pd.DataFrame) -> list[str]:
    return sorted(dataset["date"].unique())


# ---------------------------------------------------------------------------
# replay_rolling_ic_gate_over_dataset - no-lookahead correctness
# ---------------------------------------------------------------------------


def test_replay_decision_at_a_date_unaffected_by_rows_appended_after_it():
    # The single most important property: truncating the dataset to end
    # right after some date D must not change the recorded decision AT D.
    full_dataset = _two_era_dataset(num_days=60, flip_at=30)
    cutoff_date = "2020-02-05"
    truncated_dataset = full_dataset[full_dataset["date"] <= cutoff_date]

    gate_config = {"enabled": True, "min_rolling_mean_ic": 0.0, "min_resolved_dates_required": 5}
    common_kwargs = dict(
        raw_score_column="raw_score", horizon_days=5, rolling_window_days=10, gate_config=gate_config,
    )

    full_records = replay_rolling_ic_gate_over_dataset(
        full_dataset, rebalance_dates=[cutoff_date], **common_kwargs
    )
    truncated_records = replay_rolling_ic_gate_over_dataset(
        truncated_dataset, rebalance_dates=[cutoff_date], **common_kwargs
    )

    assert full_records == truncated_records


def test_replay_produces_one_record_per_rebalance_date_in_order():
    dataset = _two_era_dataset(num_days=60, flip_at=30)
    rebalance_dates = _all_dates(dataset)[::5]
    gate_config = {"enabled": True, "min_rolling_mean_ic": 0.0, "min_resolved_dates_required": 5}

    records = replay_rolling_ic_gate_over_dataset(
        dataset, raw_score_column="raw_score", horizon_days=5, rolling_window_days=10,
        rebalance_dates=rebalance_dates, gate_config=gate_config,
    )

    assert [record["date"] for record in records] == rebalance_dates


def test_replay_disabled_gate_never_disengages():
    dataset = _two_era_dataset(num_days=60, flip_at=30)
    rebalance_dates = _all_dates(dataset)[::5]
    gate_config = {"enabled": False, "min_rolling_mean_ic": 0.0}

    records = replay_rolling_ic_gate_over_dataset(
        dataset, raw_score_column="raw_score", horizon_days=5, rolling_window_days=10,
        rebalance_dates=rebalance_dates, gate_config=gate_config,
    )

    assert all(record["engaged"] for record in records)
    assert all(record["reason"] == "rolling_ic_gate_disabled" for record in records)


def test_replay_early_dates_fail_open_insufficient_history():
    dataset = _two_era_dataset(num_days=60, flip_at=30)
    gate_config = {"enabled": True, "min_rolling_mean_ic": 0.0, "min_resolved_dates_required": 5}

    records = replay_rolling_ic_gate_over_dataset(
        dataset, raw_score_column="raw_score", horizon_days=5, rolling_window_days=10,
        rebalance_dates=[_all_dates(dataset)[0]], gate_config=gate_config,
    )

    assert records[0]["reason"] == "rolling_ic_gate_insufficient_history"
    assert records[0]["engaged"] is True


# ---------------------------------------------------------------------------
# summarize_rolling_ic_gate_replay
# ---------------------------------------------------------------------------


def test_summarize_overall_fraction_matches_manual_count():
    records = [
        {"date": "2020-01-01", "engaged": True, "reason": "rolling_ic_above_floor"},
        {"date": "2020-01-02", "engaged": False, "reason": "rolling_ic_below_floor"},
        {"date": "2020-01-03", "engaged": False, "reason": "rolling_ic_below_floor"},
        {"date": "2020-01-04", "engaged": True, "reason": "rolling_ic_gate_insufficient_history"},
    ]
    summary = summarize_rolling_ic_gate_replay(records)
    assert summary["overall"]["total_dates"] == 4
    assert summary["overall"]["disengaged_days"] == 2
    assert summary["overall"]["disengaged_day_fraction"] == pytest.approx(0.5)
    assert summary["overall"]["disengaged_days_below_floor"] == 2


def test_summarize_empty_records_is_degenerate_not_raise():
    summary = summarize_rolling_ic_gate_replay([])
    assert summary["overall"]["total_dates"] == 0
    assert summary["overall"]["disengaged_day_fraction"] == 0.0


def test_summarize_by_era_attributes_dates_to_the_correct_named_era():
    records = [
        {"date": "2019-02-15", "engaged": True, "reason": "rolling_ic_above_floor"},  # era_0_good
        {"date": "2019-05-01", "engaged": False, "reason": "rolling_ic_below_floor"},  # era_1_bad_apr_sep_2019
        {"date": "2019-05-15", "engaged": False, "reason": "rolling_ic_below_floor"},  # era_1_bad_apr_sep_2019
        {"date": "2021-01-01", "engaged": True, "reason": "rolling_ic_above_floor"},  # outside every named era
    ]
    summary = summarize_rolling_ic_gate_replay(records)
    assert summary["by_era"]["era_0_good"]["total_dates"] == 1
    assert summary["by_era"]["era_0_good"]["disengaged_days"] == 0
    assert summary["by_era"]["era_1_bad_apr_sep_2019"]["total_dates"] == 2
    assert summary["by_era"]["era_1_bad_apr_sep_2019"]["disengaged_day_fraction"] == pytest.approx(1.0)
    # The out-of-era date counts toward "overall" but no by_era bucket.
    assert summary["overall"]["total_dates"] == 4
    assert sum(bucket["total_dates"] for bucket in summary["by_era"].values()) == 3


def test_summarize_era_with_zero_dates_reports_none_fraction_not_zero_division():
    summary = summarize_rolling_ic_gate_replay([{"date": "2025-01-01", "engaged": True, "reason": "x"}])
    assert summary["by_era"]["era_0_good"]["total_dates"] == 0
    assert summary["by_era"]["era_0_good"]["disengaged_day_fraction"] is None
