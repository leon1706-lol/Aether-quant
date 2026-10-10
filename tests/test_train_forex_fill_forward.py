"""train.py: forex rows are engineered on Lean's fill-forward calendar, labelled on the real bars (Problems.md #135).

Live forex windows carry flat Sunday bars (and filled gap days); the dataset's trailing features must too, while no
fake zero-return day may leak into a target.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from train import (
    FOREX_CALENDAR_FEATURE_COLUMNS,
    engineer_features,
    engineer_forex_features_on_lean_calendar,
    fill_forward_forex_frame,
    add_liquidity_features,
)

FEATURE_NAMES = [
    "close_to_close_return_1d", "close_to_close_return_5d", "close_to_close_return_20d",
    "rolling_volatility_5d", "rolling_volatility_20d", "momentum_5d", "momentum_20d",
    "high_low_range_pct", "open_close_range_pct", "volume_change_1d",
]
WINDOWS = {
    "training": {"start": "2019-01-01", "end": "2019-12-31"},
    "validation": {"start": "2020-01-01", "end": "2020-12-31"},
    "backtest": {"start": "2021-01-01", "end": "2021-12-31"},
}


def _weekday_forex_frame(n_weeks: int = 12, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-03-04", periods=5 * n_weeks)  # Monday start, weekdays only (no Sunday rows)
    closes = 1.10 + np.cumsum(rng.normal(0, 0.004, len(dates)))
    return pd.DataFrame(
        {
            "timestamp": dates, "date": dates, "open": closes - 0.001, "high": closes + 0.002, "low": closes - 0.002,
            "close": closes, "volume": 0.0, "ticker": "EURUSD", "security_type": "forex", "market": "oanda",
        }
    )


def test_fill_forward_adds_flat_sunday_bars_between_friday_and_monday():
    frame = _weekday_forex_frame(3)

    filled = fill_forward_forex_frame(frame)

    sundays = filled[filled["date"].dt.dayofweek == 6]
    assert len(filled) == len(frame) + 2  # Sundays between the three weeks
    assert (filled["date"].dt.dayofweek != 5).all()
    for _, row in sundays.iterrows():
        friday = frame[frame["date"] == row["date"] - pd.Timedelta(days=2)].iloc[0]
        assert row["close"] == friday["close"] and row["open"] == row["high"] == row["low"] == friday["close"]
        assert row["volume"] == 0.0 and row["ticker"] == "EURUSD"
    assert filled["date"].is_monotonic_increasing


def test_fill_forward_is_a_no_op_when_there_is_nothing_to_fill():
    dates = pd.to_datetime(["2019-03-04", "2019-03-05", "2019-03-06"])
    frame = pd.DataFrame({"date": dates, "open": 1.0, "high": 1.0, "low": 1.0, "close": [1.0, 1.1, 1.2], "volume": 0.0})
    assert fill_forward_forex_frame(frame)["close"].tolist() == [1.0, 1.1, 1.2]


def test_rows_and_labels_are_those_of_the_real_bars_but_trailing_features_use_the_filled_calendar():
    frame = _weekday_forex_frame(12)
    kwargs = dict(max_abs_daily_return={"forex": 0.5}, max_abs_return_5d={"forex": 0.9}, max_abs_return_20d={"forex": 1.5})

    lean = engineer_forex_features_on_lean_calendar(frame, FEATURE_NAMES, WINDOWS, **kwargs)
    plain = engineer_features(add_liquidity_features(frame, "forex"), FEATURE_NAMES, WINDOWS, security_type="forex", **kwargs)

    assert lean["date"].tolist() == plain["date"].tolist()
    for label in ("target_return_1d", "target_direction", "target_return_5d", "target_return_20d", "target_volatility_next_day", "split"):
        pd.testing.assert_series_equal(lean[label], plain[label], check_names=False)
    assert (lean["date"].dt.dayofweek < 5).all()  # no Sunday filler row leaks into the dataset

    filled = fill_forward_forex_frame(frame)
    monday = pd.Timestamp("2019-04-15")
    position = filled.index[filled["date"] == monday][0]
    closes = filled["close"].to_numpy()
    expected_momentum_5d = closes[position] / closes[position - 5] - 1.0  # five FILLED bars back (includes the Sunday bar)
    row = lean[lean["date"] == monday].iloc[0]
    assert row["momentum_5d"] == pytest.approx(expected_momentum_5d)
    assert row["momentum_5d"] != pytest.approx(plain[plain["date"] == monday].iloc[0]["momentum_5d"])
    # the Friday->Monday weekend move is still the Friday label (not split by a zero-return Sunday)
    friday = pd.Timestamp("2019-04-12")
    friday_row = lean[lean["date"] == friday].iloc[0]
    expected_target = frame.loc[frame["date"] == monday, "close"].iloc[0] / frame.loc[frame["date"] == friday, "close"].iloc[0] - 1.0
    assert friday_row["target_return_1d"] == pytest.approx(expected_target)
    assert set(FOREX_CALENDAR_FEATURE_COLUMNS) <= set(lean.columns)
