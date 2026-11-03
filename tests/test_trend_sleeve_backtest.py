"""evaluation/trend_sleeve_backtest.py (V6.4.4): lag, costs, guard and the phase summary of the trend sleeve sim."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.trend_sleeve_backtest import simulate_trend_sleeve, summarize_daily, trend_phase_summary
from portfolio.sleeve_guard import SleeveGuardConfig
from portfolio.trend_sleeve import TrendSleeveConfig, trend_sleeve_weights


def _closes(n: int = 400, drift: float = 0.001) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=n).strftime("%Y-%m-%d")
    rng = np.random.default_rng(5)
    a = 100.0 * np.exp(np.cumsum(drift + 0.01 * rng.standard_normal(n)))
    b = 50.0 * np.exp(np.cumsum(-drift + 0.01 * rng.standard_normal(n)))
    return pd.DataFrame({"A": a, "B": b}, index=dates)


CONFIG = TrendSleeveConfig(enabled=True, symbols=("A", "B"), signal="sign_126", min_weight_change=0.0)


def test_positions_open_at_the_rebalance_close_and_earn_from_the_next_session():
    closes = _closes()
    start = closes.index[300]
    result = simulate_trend_sleeve(closes, CONFIG, start=start, end=closes.index[-1], commission_bps=0.0,
                                   min_commission_usd=0.0, half_spread_bps=0.0)
    assert result["daily"].iloc[0] == 0.0  # nothing held before the first rebalance close
    expected = trend_sleeve_weights({s: closes[s].iloc[:301].tolist() for s in ("A", "B")}, CONFIG)
    held = result["weights"].iloc[0]
    assert held["A"] == pytest.approx(expected["A"]) and held["B"] == pytest.approx(expected["B"])
    r_a = closes["A"].iloc[301] / closes["A"].iloc[300] - 1.0
    r_b = closes["B"].iloc[301] / closes["B"].iloc[300] - 1.0
    assert result["daily"].iloc[1] == pytest.approx(expected["A"] * r_a + expected["B"] * r_b)


def test_costs_are_charged_on_traded_notional():
    closes = _closes()
    free = simulate_trend_sleeve(closes, CONFIG, start=closes.index[300], end=closes.index[-1], commission_bps=0.0,
                                 min_commission_usd=0.0, half_spread_bps=0.0)
    paid = simulate_trend_sleeve(closes, CONFIG, start=closes.index[300], end=closes.index[-1], commission_bps=1.5,
                                 min_commission_usd=1.0, half_spread_bps=2.0)
    assert free["costs"] == 0.0 and paid["costs"] > 0.0
    assert paid["daily"].sum() < free["daily"].sum()


def test_guard_suspends_the_sleeve_after_a_loss():
    closes = _closes()
    # crash both legs against the positions right after the first rebalance
    idx = closes.index
    closes.loc[idx[305]:, "A"] *= 0.7
    closes.loc[idx[305]:, "B"] *= 1.4
    guard = SleeveGuardConfig(enabled=True, max_loss_fraction_nav=0.01, lookback_bars=60, cooldown_bars=30)
    result = simulate_trend_sleeve(closes, CONFIG, start=idx[300], end=idx[-1], guard=guard)
    gross = result["gross"]
    assert gross.loc[idx[310]:idx[330]].max() == 0.0


def test_phase_summary_shapes_and_summary_math():
    closes = _closes()
    out = trend_phase_summary(closes, CONFIG, start=closes.index[300], end=closes.index[-1], phases=4)
    assert out["phases"] == [0, 5, 10, 15]
    assert len(out["daily_phase0"]) == len(closes) - 300
    for key in ("median_net_sharpe", "min_max_drawdown", "max_turnover"):
        assert np.isfinite(out[key])
    flat = summarize_daily(pd.Series([0.0, 0.01, -0.01]))
    assert flat["max_drawdown"] == pytest.approx(0.01)
