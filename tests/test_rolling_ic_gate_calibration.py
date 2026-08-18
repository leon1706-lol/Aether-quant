"""Tests for evaluation/rolling_ic_gate_calibration.py (V5.3.5,
development/Problems.md #102). Conventions match
tests/test_rank_signal_calibration.py's style against
calibrate_book_confidence_spread() - this module's calibrate_rolling_ic_floor()
is its direct sibling for the new gate.
"""

import pandas as pd
import pytest

from evaluation.rolling_ic_gate_calibration import build_event_buffer, calibrate_rolling_ic_floor
from portfolio.rolling_ic_gate import compute_rolling_ic_state


def _synthetic_dataset(num_tickers: int = 4, num_days: int = 80) -> pd.DataFrame:
    """Two eras: a genuinely skillful first half (raw score cleanly
    predicts which ticker will close higher) and a shuffled, no-skill
    second half - gives calibrate_rolling_ic_floor() a real, non-degenerate
    distribution to derive a floor from, mirroring
    tests/test_rank_signal_calibration.py's own good/bad synthetic split."""
    rows = []
    tickers = [f"T{index}" for index in range(num_tickers)]
    # Each ticker's own close path is monotonic in its own fixed rank so
    # every date's forward return is fully explained by that ticker
    # identity - the raw score just needs to track the SAME per-ticker
    # rank to be "skillful", and be shuffled to be "unskillful".
    ticker_growth = {ticker: 1.0 + 0.01 * rank for rank, ticker in enumerate(tickers)}
    for day in range(num_days):
        date = f"2020-{1 + day // 28:02d}-{1 + day % 28:02d}"
        skillful_era = day < num_days // 2
        for rank, ticker in enumerate(tickers):
            close = 100.0 * (ticker_growth[ticker] ** day)
            raw_score = float(rank) if skillful_era else float(num_tickers - 1 - rank)
            rows.append({"ticker": ticker, "date": date, "close": close, "raw_score": raw_score})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# build_event_buffer
# ---------------------------------------------------------------------------


def test_build_event_buffer_shape_matches_rolling_ic_gate_expectations():
    dataset = pd.DataFrame(
        {"ticker": ["AAPL", "MSFT"], "date": ["2020-01-02", "2020-01-01"], "close": [101.0, 100.0], "raw_score": [0.5, 0.6]}
    )
    events = build_event_buffer(dataset, raw_score_column="raw_score")
    assert events == [
        {"ticker": "MSFT", "created_at": "2020-01-01T00:00:00Z", "resolved_predicted_rank_20d": 0.6, "close_price": 100.0},
        {"ticker": "AAPL", "created_at": "2020-01-02T00:00:00Z", "resolved_predicted_rank_20d": 0.5, "close_price": 101.0},
    ]


def test_build_event_buffer_skips_rows_missing_score_or_close():
    dataset = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT", "GOOG"],
            "date": ["2020-01-01", "2020-01-01", "2020-01-01"],
            "close": [100.0, float("nan"), 100.0],
            "raw_score": [float("nan"), 0.5, 0.5],
        }
    )
    events = build_event_buffer(dataset, raw_score_column="raw_score")
    assert [event["ticker"] for event in events] == ["GOOG"]


# ---------------------------------------------------------------------------
# calibrate_rolling_ic_floor
# ---------------------------------------------------------------------------


def test_calibrate_rolling_ic_floor_empty_dataset_is_degenerate_not_raise():
    dataset = pd.DataFrame(columns=["ticker", "date", "close", "raw_score"])
    result = calibrate_rolling_ic_floor(
        dataset, raw_score_column="raw_score", horizon_days=20, rolling_window_days=10
    )
    assert result["calibrated_min_rolling_mean_ic"] == -1e12
    assert result["num_samples_used"] == 0
    assert result["rolling_ic_distribution"]["min"] is None


def test_calibrate_rolling_ic_floor_thin_history_never_raises():
    # Enough rows to exist, but never enough resolved dates for any
    # sample point (horizon_days larger than the whole dataset's span).
    dataset = _synthetic_dataset(num_tickers=3, num_days=5)
    result = calibrate_rolling_ic_floor(
        dataset, raw_score_column="raw_score", horizon_days=20, rolling_window_days=10, sample_stride_days=1
    )
    assert result["num_samples_used"] == 0
    assert result["calibrated_min_rolling_mean_ic"] == -1e12


def test_calibrate_rolling_ic_floor_produces_real_distribution_on_skillful_data():
    # min_names_per_date=2 (this function's default is 10, tuned for a
    # real 70-100-name universe - see calibrate_rolling_ic_floor()'s own
    # docstring) - this fixture only has 4 tickers, so the default would
    # filter out every date and defeat the fixture's purpose.
    dataset = _synthetic_dataset(num_tickers=4, num_days=80)
    result = calibrate_rolling_ic_floor(
        dataset, raw_score_column="raw_score", horizon_days=5, rolling_window_days=10, sample_stride_days=2,
        min_names_per_date=2,
    )
    assert result["num_samples_used"] > 0
    assert result["rolling_ic_distribution"]["min"] is not None
    # p10 floor must be a real, finite number - not the never-trips sentinel -
    # once real samples exist.
    assert result["calibrated_min_rolling_mean_ic"] > -1e12


def test_calibrate_rolling_ic_floor_percentile_is_lower_than_median():
    dataset = _synthetic_dataset(num_tickers=4, num_days=80)
    result = calibrate_rolling_ic_floor(
        dataset, raw_score_column="raw_score", horizon_days=5, rolling_window_days=10,
        percentile=0.10, sample_stride_days=2, min_names_per_date=2,
    )
    distribution = result["rolling_ic_distribution"]
    assert distribution["p10"] <= distribution["median"]


def test_build_event_buffer_prefix_matches_full_buffer_sliced_to_same_cutoff():
    # The critical no-lookahead correctness property calibrate_rolling_ic_floor()
    # relies on: the event buffer "as of" some date must be identical
    # whether it was built from a dataset that only ever had rows up to
    # that date, or sliced out of a longer dataset with more rows AFTER
    # it - proves the walk-forward slicing can't leak future rows into an
    # earlier reading.
    full_dataset = _synthetic_dataset(num_tickers=4, num_days=80)
    cutoff_date = "2020-02-10"
    prefix_dataset = full_dataset[full_dataset["date"] <= cutoff_date]

    full_events = build_event_buffer(full_dataset, raw_score_column="raw_score")
    prefix_events = build_event_buffer(prefix_dataset, raw_score_column="raw_score")
    full_events_sliced = [event for event in full_events if str(event["created_at"])[:10] <= cutoff_date]

    assert full_events_sliced == prefix_events

    state_from_prefix = compute_rolling_ic_state(prefix_events, horizon_days=5, rolling_window_days=10)
    state_from_sliced_full = compute_rolling_ic_state(full_events_sliced, horizon_days=5, rolling_window_days=10)
    assert state_from_prefix == state_from_sliced_full
