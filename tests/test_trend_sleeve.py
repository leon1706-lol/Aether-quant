"""portfolio/trend_sleeve.py (V6.4.4): signals, inverse-vol sizing, caps and the min-change filter."""

from __future__ import annotations

import math

import numpy as np
import pytest

from portfolio.trend_sleeve import (
    TrendSleeveConfig,
    annualised_vol,
    apply_min_change,
    resolve_trend_sleeve_config,
    trend_signal,
    trend_sleeve_weights,
)


def _series(drift: float, n: int = 300, vol: float = 0.01, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(100.0 * np.exp(np.cumsum(drift + vol * rng.standard_normal(n))))


def test_signals_follow_the_trailing_return():
    up, down = _series(0.002), _series(-0.002)
    for signal in ("sign_252", "sign_126", "sign_63"):
        assert trend_signal(up, signal) == 1.0
        assert trend_signal(down, signal) == -1.0
    assert trend_signal(up, "sign_blend") == 1.0
    mixed = [100.0] * 200 + [50.0] * 60 + [200.0] * 3  # only the endpoints matter: 200 > 100
    assert trend_signal(mixed, "sign_252") == 1.0
    assert trend_signal([100.0] * 300, "sign_252") == 0.0


def test_short_or_invalid_history_gives_none():
    assert trend_signal(_series(0.001, n=100), "sign_252") is None
    bad = _series(0.001)
    bad[-5] = float("nan")
    assert trend_signal(bad, "sign_252") is None
    assert trend_signal(_series(0.001), "bogus") is None
    assert annualised_vol([100.0] * 80, 60) is None


def test_inverse_vol_sizing_targets_the_sleeve_vol_and_respects_caps():
    config = TrendSleeveConfig(enabled=True, symbols=("A", "B"), signal="sign_126", target_vol=0.03,
                               max_weight_per_name=1.0, gross_cap=10.0)
    closes = {"A": _series(0.002, vol=0.01, seed=1), "B": _series(-0.002, vol=0.02, seed=2)}
    weights = trend_sleeve_weights(closes, config)
    vol_a, vol_b = annualised_vol(closes["A"], 60), annualised_vol(closes["B"], 60)
    assert weights["A"] == pytest.approx(0.03 / math.sqrt(2) / vol_a)
    assert weights["B"] == pytest.approx(-0.03 / math.sqrt(2) / vol_b)
    capped = trend_sleeve_weights(closes, TrendSleeveConfig(enabled=True, symbols=("A", "B"), signal="sign_126",
                                                            target_vol=0.5, max_weight_per_name=0.08, gross_cap=0.1))
    assert sum(abs(w) for w in capped.values()) == pytest.approx(0.1)
    assert all(abs(w) <= 0.08 + 1e-12 for w in capped.values())


def test_disabled_or_unknown_symbols_give_nothing():
    closes = {"A": _series(0.002)}
    assert trend_sleeve_weights(closes, TrendSleeveConfig(enabled=False, symbols=("A",))) == {}
    assert trend_sleeve_weights(closes, TrendSleeveConfig(enabled=True, symbols=("Z",))) == {}


def test_min_change_keeps_small_moves_and_always_closes_or_opens():
    previous = {"A": 0.05, "B": -0.04, "C": 0.02}
    target = {"A": 0.053, "B": 0.04, "D": 0.01}
    out = apply_min_change(previous, target, 0.005)
    assert out == {"A": 0.05, "B": 0.04, "D": 0.01}  # C closes, B flips, A kept, D opens


def test_resolve_defaults_and_bad_values():
    config = resolve_trend_sleeve_config({"enabled": True, "symbols": ["SPY"], "signal": "nope", "target_vol": -1,
                                          "vol_window": "x"})
    assert config.enabled and config.symbols == ("SPY",) and config.signal == "sign_252"
    assert config.target_vol == 0.03 and config.vol_window == 60
    assert resolve_trend_sleeve_config(None) == TrendSleeveConfig()
    assert TrendSleeveConfig(signal="sign_blend").history_needed == 253
