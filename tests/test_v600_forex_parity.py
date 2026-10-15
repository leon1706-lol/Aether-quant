"""V6.0.0 (todo lead 4): forex features in live equal the dataset's once Lean's fill-forward bars are flattened.

Lean's fill-forward QuoteBar is `previous.Clone(true)`: the previous bar's whole range, flagged IsFillForward. The
dataset (`train.fill_forward_forex_frame`) makes a filled day flat at the previous close, and its sensitivity betas
regress over real-bar rows only, with driver levels dated by the row. With `phase1.features.forex_fill_forward_bars:
"flat"` main.py builds the same windows.
"""

from __future__ import annotations

import datetime
import sys
import types
from collections import deque
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from data_pipeline.bar_synthesis import flatten_fill_forward_bar, midpoint_bar_from_quote_bar
from features.technical_indicators import average_true_range_pct

WINDOWS = {
    "training": {"start": "2019-01-01", "end": "2019-12-31"},
    "validation": {"start": "2020-01-01", "end": "2020-12-31"},
    "backtest": {"start": "2021-01-01", "end": "2021-12-31"},
}
DRIVERS = {"vix": "implied_volatility_vix", "real_rate": "treasury_10yr_real", "credit": "credit_spread_baa10y",
           "dollar": "dollar_index"}


@pytest.fixture(scope="module")
def main_module():
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = type("QCAlgorithm", (), {})
    stub.Slice = object
    stub.time = datetime.time
    patcher = pytest.MonkeyPatch()
    patcher.setitem(sys.modules, "AlgorithmImports", stub)
    patcher.delitem(sys.modules, "main", raising=False)
    import main  # noqa: PLC0415

    yield main
    sys.modules.pop("main", None)
    patcher.undo()


def _weekday_frame(weeks: int = 40, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-03-04", periods=5 * weeks)
    closes = 1.10 + np.cumsum(rng.normal(0, 0.004, len(dates)))
    spread = np.abs(rng.normal(0.003, 0.001, len(dates)))
    return pd.DataFrame({"timestamp": dates, "date": dates, "open": closes - spread / 3, "high": closes + spread,
                         "low": closes - spread, "close": closes, "volume": 0.0, "ticker": "EURUSD",
                         "security_type": "forex", "market": "oanda"})


def test_the_midpoint_bar_carries_the_fill_forward_flag_and_its_end_time():
    side = SimpleNamespace(Open=1.0, High=1.2, Low=0.9, Close=1.1)
    end = datetime.datetime(2024, 1, 8, 0, 0)
    bar = midpoint_bar_from_quote_bar(SimpleNamespace(Bid=side, Ask=side, IsFillForward=True, EndTime=end))
    assert bar.is_fill_forward is True and bar.end_time == end and bar.high == 1.2
    assert midpoint_bar_from_quote_bar(SimpleNamespace(Bid=side, Ask=side)).is_fill_forward is False


def test_flattened_lean_bars_rebuild_the_datasets_filled_calendar():
    import train

    frame = _weekday_frame(4)
    filled = train.fill_forward_forex_frame(frame)
    window: list[dict] = []
    previous = None
    for _, row in filled.iterrows():
        real = row["date"] in set(frame["date"])
        lean_bar = dict(row[["open", "high", "low", "close", "volume"]]) if real else dict(previous)  # Lean clones it
        window.append(lean_bar if real else flatten_fill_forward_bar(lean_bar, window[-1]["close"]))
        previous = lean_bar
    rebuilt = pd.DataFrame(window)
    pd.testing.assert_frame_equal(rebuilt, filled[["open", "high", "low", "close", "volume"]].reset_index(drop=True), check_dtype=False)


def test_atr_after_a_weekend_matches_only_with_flat_bars():
    import train

    frame = _weekday_frame(8)
    kwargs = dict(max_abs_daily_return={"forex": 0.5}, max_abs_return_5d={"forex": 0.9}, max_abs_return_20d={"forex": 1.5})
    dataset = train.engineer_forex_features_on_lean_calendar(frame, train.BASE_FEATURE_NAMES, WINDOWS, **kwargs)
    filled = train.fill_forward_forex_frame(frame).reset_index(drop=True)
    real_dates = set(frame["date"])
    flat_window, cloned_window, last_real = deque(maxlen=25), deque(maxlen=25), None
    checked = 0
    for _, row in filled.iterrows():
        bar = dict(row[["open", "high", "low", "close", "volume"]])
        if row["date"] in real_dates:
            last_real = bar
            flat_window.append(bar)
            cloned_window.append(bar)
        else:
            flat_window.append(flatten_fill_forward_bar(last_real, flat_window[-1]["close"]))
            cloned_window.append(dict(last_real))
        match = dataset[dataset["date"] == row["date"]]
        if row["date"].dayofweek == 0 and len(match) and len(flat_window) == 25:
            expected = float(match["atr_pct_14"].iloc[0])
            highs, lows, closes = ([bar[key] for bar in flat_window] for key in ("high", "low", "close"))
            assert average_true_range_pct(highs, lows, closes) == pytest.approx(expected, rel=1e-9)
            c_highs, c_lows, c_closes = ([bar[key] for bar in cloned_window] for key in ("high", "low", "close"))
            assert average_true_range_pct(c_highs, c_lows, c_closes) != pytest.approx(expected, rel=1e-6)
            checked += 1
    assert checked >= 3


def test_forex_sensitivity_betas_use_real_bars_dated_by_the_bar(main_module):
    import train

    frame = _weekday_frame(30)
    frame["close_to_close_return_1d"] = frame["close"].pct_change()
    rng = np.random.default_rng(3)
    days = pd.date_range("2019-03-01", "2019-12-31")
    fred = {name: [{"date": day.date(), "value": float(value)} for day, value in zip(days, np.cumsum(rng.normal(0, 1, len(days))))]
            for name in DRIVERS.values()}
    sensitivity = {"enabled": True, "lookback_days": 40, "min_observations": 15, "drivers": DRIVERS}
    config = {"phase1": {"features": {"cross_asset_sensitivity": sensitivity}}}
    built = train.build_cross_asset_sensitivity_features({"EURUSD": frame}, config, fred)["EURUSD"]

    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    algorithm.phase1 = config["phase1"]
    algorithm.fred_series = fred
    algorithm.forex_fill_forward_mode = "flat"
    algorithm.asset_lookup = {"EURUSD": {"asset_class": "forex", "security_type": "forex"}}
    algorithm.long_bar_history_size = 260
    algorithm.symbol_real_bar_closes = {"EURUSD": deque(maxlen=260)}
    algorithm.symbol_real_bar_driver_history = {"EURUSD": {key: deque(maxlen=260) for key in DRIVERS}}
    for index, row in frame.iterrows():
        # a daily forex bar ends at 00:00 UTC of the next day; the tick that delivers it is that next day
        end_time = pd.Timestamp(row["date"]).to_pydatetime() + datetime.timedelta(days=1)
        algorithm.Time = end_time + datetime.timedelta(hours=1)
        algorithm._append_real_forex_bar("EURUSD", SimpleNamespace(close=float(row["close"]), end_time=end_time))
        live = algorithm._cross_asset_sensitivity_for_symbol("EURUSD")
        for key in DRIVERS:
            assert live[f"sens_{key}_beta"] == pytest.approx(built[f"sens_{key}_beta"].iloc[index], rel=1e-9, abs=1e-12), (index, key)
            assert live[f"sens_{key}_interaction"] == pytest.approx(built[f"sens_{key}_interaction"].iloc[index], rel=1e-9, abs=1e-12)
    assert built["sens_vix_beta"].iloc[-1] != 0.0
