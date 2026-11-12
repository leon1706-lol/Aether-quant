"""risk/kelly.py (V6.6.5, #345)."""

from __future__ import annotations

import math

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from risk.kelly import kelly_fraction, kelly_weights


def test_full_kelly_is_mean_over_variance_and_the_default_is_half_capped():
    assert math.isclose(kelly_fraction(0.01, 0.04, fraction=1.0, cap=10.0), 0.25)
    assert math.isclose(kelly_fraction(0.01, 0.04), 0.125)
    assert kelly_fraction(1.0, 0.01) == 1.0
    assert kelly_fraction(-1.0, 0.01) == -1.0
    for bad in ((0.01, 0.0), (0.01, -1.0), (float("nan"), 0.04), (0.01, float("inf")), ("x", 1.0)):
        assert kelly_fraction(*bad) == 0.0


def test_kelly_weights_solve_the_system_and_scale_down_to_the_cap():
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    mu = np.array([0.002, 0.001])
    full = kelly_weights(mu, cov, fraction=1.0, gross_cap=100.0, ridge=0.0)
    assert np.allclose(cov @ full, mu)
    capped = kelly_weights(mu * 1000, cov, gross_cap=1.0)
    assert math.isclose(np.abs(capped).sum(), 1.0)
    assert not kelly_weights(mu, np.eye(3)).any()
    assert not kelly_weights(np.array([np.nan, 1.0]), cov).any()
    assert not kelly_weights(mu, np.zeros((2, 2)), ridge=0.0).any()


@settings(max_examples=150, deadline=None)
@given(arrays(float, 3, elements=st.floats(-1, 1)), st.floats(0.01, 5.0), st.floats(0.1, 3.0))
def test_kelly_weights_never_exceed_the_gross_cap(mu, fraction, cap):
    cov = np.array([[0.04, 0.0, 0.0], [0.0, 0.02, 0.0], [0.0, 0.0, 0.01]])
    weights = kelly_weights(mu, cov, fraction=fraction, gross_cap=cap)
    assert np.all(np.isfinite(weights)) and np.abs(weights).sum() <= cap + 1e-9
