"""features/fx_signals.py (V5.8.0): carry / time-series momentum scores for the forex sleeve."""

from __future__ import annotations

import math

import pytest

from features.fx_signals import FX_SIGNALS, fx_sleeve_scores, ts_momentum_score


def _trend(start: float, daily: float, n: int, wiggle: float = 0.001) -> list[float]:
    values, level = [], start
    for index in range(n):
        level *= math.exp(daily + (wiggle if index % 2 else -wiggle))
        values.append(level)
    return values


def test_momentum_sign_follows_the_trend_and_needs_enough_history():
    assert ts_momentum_score(_trend(1.0, 0.001, 200)) > 0 > ts_momentum_score(_trend(1.0, -0.001, 200))
    assert ts_momentum_score(_trend(1.0, 0.001, 100)) is None  # shorter than the 120-day lookback + 1
    assert ts_momentum_score([1.0] * 200) is None  # zero volatility


def test_momentum_is_vol_comparable_across_pairs():
    calm = ts_momentum_score(_trend(1.0, 0.0005, 200, wiggle=0.001))
    noisy = ts_momentum_score(_trend(1.0, 0.0005, 200, wiggle=0.01))
    assert calm > noisy > 0


def test_scores_per_signal_and_unknown_signal_rejected():
    closes = {"EURUSD": _trend(1.1, 0.001, 200), "USDJPY": _trend(110, -0.001, 200), "AUDUSD": _trend(0.7, 0.0, 50)}
    carry = {"EURUSD": -1.5, "USDJPY": 2.0, "AUDUSD": 0.5}
    assert fx_sleeve_scores("carry", carry_by_pair=carry) == carry
    momentum = fx_sleeve_scores("ts_momentum", closes_by_pair=closes)
    assert set(momentum) == {"EURUSD", "USDJPY"}  # AUDUSD lacks history: left out, not scored 0
    blend = fx_sleeve_scores("carry_momentum", closes_by_pair=closes, carry_by_pair=carry)
    assert set(blend) == {"EURUSD", "USDJPY"} and blend["EURUSD"] == pytest.approx(-blend["USDJPY"])
    assert fx_sleeve_scores("model_rank", model_scores={"EURUSD": 0.3, "X": float("nan")}) == {"EURUSD": 0.3}
    assert "carry" in FX_SIGNALS
    with pytest.raises(ValueError):
        fx_sleeve_scores("carry_trade")


def test_vectorised_momentum_series_equals_the_scalar_score_at_every_row():
    import numpy as np
    import pandas as pd

    from features.fx_signals import ts_momentum_series

    rng = np.random.default_rng(6)
    closes = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, 300))))
    series = ts_momentum_series(closes)
    for index in (119, 120, 121, 150, 299):
        scalar = ts_momentum_score(closes.iloc[: index + 1].tolist())
        if scalar is None:
            assert np.isnan(series.iloc[index])
        else:
            assert series.iloc[index] == pytest.approx(scalar, rel=1e-9)
    assert series.iloc[:120].isna().all()
