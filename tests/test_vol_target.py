"""risk/vol_target.py (V6.6.5, #345)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from risk.vol_target import realized_vol, volatility_target_weights

COV = pd.DataFrame([[1e-4, 2e-5], [2e-5, 4e-4]], index=["A", "B"], columns=["A", "B"])


def test_realized_vol_is_rolling_std_annualised():
    returns = pd.Series([0.01, -0.01] * 20)
    vol = realized_vol(returns, window=10, annualization=252)
    assert vol.iloc[:9].isna().all()
    assert math.isclose(vol.iloc[-1], returns.iloc[-10:].std(ddof=1) * math.sqrt(252))


def test_scales_to_the_target_volatility():
    weights = volatility_target_weights({"A": 0.3, "B": 0.2}, COV, target_annual_vol=0.10, max_leverage=10.0)
    w = np.array([weights["A"], weights["B"]])
    assert math.isclose(math.sqrt(w @ COV.to_numpy() @ w * 252), 0.10, rel_tol=1e-12)
    assert math.isclose(weights["A"] / weights["B"], 1.5)


def test_leverage_cap_missing_names_and_degenerate_risk():
    capped = volatility_target_weights({"A": 0.01, "B": 0.01}, COV, target_annual_vol=1.0, max_leverage=1.0)
    assert math.isclose(sum(abs(v) for v in capped.values()), 1.0)
    assert "C" not in volatility_target_weights({"A": 0.5, "C": 0.5}, COV, target_annual_vol=0.1)
    zero = pd.DataFrame(0.0, index=["A"], columns=["A"])
    assert volatility_target_weights({"A": 0.5}, zero, target_annual_vol=0.1) == {"A": 0.5}


@settings(max_examples=150, deadline=None)
@given(st.floats(-2, 2), st.floats(-2, 2), st.floats(0.01, 2.0), st.floats(0.1, 5.0))
def test_never_exceeds_max_leverage(a, b, target, leverage):
    weights = volatility_target_weights({"A": a, "B": b}, COV, target_annual_vol=target, max_leverage=leverage)
    assert sum(abs(v) for v in weights.values()) <= leverage + 1e-9
