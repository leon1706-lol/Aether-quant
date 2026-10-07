"""Tests for evaluation/volatility_threshold_calibration.py (V5.5.0, Problems.md
#129): the per-asset-class elevated-volatility cutoff. Conventions match the
rest of this repo: no test classes, module-level helpers, synthetic frames."""

import math

import numpy as np
import pandas as pd
import pytest

from evaluation.volatility_threshold_calibration import (
    calibrate_elevated_volatility_thresholds,
    rolling_annualized_volatility,
)


def _frame(daily_vol_by_ticker: dict[str, float], days=120, seed=11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [str(d.date()) for d in pd.bdate_range("2020-01-01", periods=days)]
    rows = []
    for ticker, daily_vol in daily_vol_by_ticker.items():
        closes = 100.0 * np.cumprod(1.0 + rng.normal(0.0, daily_vol, days))
        rows.extend({"date": d, "ticker": ticker, "close": c} for d, c in zip(dates, closes))
    return pd.DataFrame(rows)


def test_rolling_volatility_matches_the_topology_statistic():
    frame = _frame({"AAA": 0.02})
    volatility = rolling_annualized_volatility(frame, window=24)
    returns = frame["close"].pct_change()
    expected = returns.iloc[-24:].std(ddof=1) * math.sqrt(252)
    assert volatility.iloc[-1] == pytest.approx(expected)
    assert volatility.iloc[:24].isna().all()  # needs a full window of returns
    assert list(volatility.index) == list(frame.index)


def test_volatility_is_computed_per_ticker_not_across_the_boundary():
    frame = _frame({"AAA": 0.001, "BBB": 0.05})
    volatility = rolling_annualized_volatility(frame, window=24)
    by_ticker = volatility.groupby(frame["ticker"]).median()
    assert by_ticker["BBB"] > 10 * by_ticker["AAA"]
    first_bbb = frame.index[frame["ticker"] == "BBB"][0]
    assert math.isnan(volatility.loc[first_bbb])  # no leak from AAA's last rows


def test_a_structurally_volatile_class_gets_its_own_threshold_and_calm_ones_do_not():
    frame = _frame({"BTCUSD": 0.06, "LTCUSD": 0.07, "AAPL": 0.012, "MSFT": 0.011, "EURUSD": 0.004})
    classes = {"BTCUSD": "crypto", "LTCUSD": "crypto", "AAPL": "equity", "MSFT": "equity", "EURUSD": "forex"}
    report = calibrate_elevated_volatility_thresholds(frame, classes, percentile=0.8, current_default=0.45, min_samples=30)
    assert report["status"] == "OK"
    assert report["by_asset_class"]["crypto"]["share_at_or_above_current_default"] > 0.9
    assert report["by_asset_class"]["equity"]["share_at_or_above_current_default"] < 0.1
    assert report["suggested_config"]["default"] == 0.45
    assert report["suggested_config"]["crypto"] > 0.45
    assert "equity" not in report["suggested_config"] and "forex" not in report["suggested_config"]
    assert report["suggested_config"]["crypto"] == report["by_asset_class"]["crypto"]["p80"]


def test_a_class_with_too_few_samples_is_reported_but_never_suggested():
    frame = _frame({"BTCUSD": 0.06}, days=40)  # 16 rolling-vol samples
    report = calibrate_elevated_volatility_thresholds(frame, {"BTCUSD": "crypto"}, min_samples=60)
    assert report["by_asset_class"]["crypto"]["num_samples"] == 16
    assert report["suggested_config"] == {"default": 0.45}


def test_unmapped_tickers_are_ignored_and_missing_close_degrades():
    frame = _frame({"AAA": 0.05, "ZZZ": 0.05})
    report = calibrate_elevated_volatility_thresholds(frame, {"AAA": "crypto"}, min_samples=10)
    assert set(report["by_asset_class"]) == {"crypto"}
    skipped = calibrate_elevated_volatility_thresholds(frame.drop(columns=["close"]), {"AAA": "crypto"})
    assert skipped["status"] == "SKIPPED"


def test_the_suggested_config_round_trips_through_the_topology_resolver():
    from topology import resolve_elevated_volatility_thresholds

    frame = _frame({"BTCUSD": 0.06, "AAPL": 0.012})
    classes = {"BTCUSD": "crypto", "AAPL": "equity"}
    suggestion = calibrate_elevated_volatility_thresholds(frame, classes, min_samples=30)["suggested_config"]
    default, by_symbol = resolve_elevated_volatility_thresholds(suggestion, classes)
    assert default == 0.45
    assert by_symbol == {"BTCUSD": suggestion["crypto"]}
