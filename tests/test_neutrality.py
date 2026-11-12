"""portfolio/neutrality.py (V6.6.5, #345)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from portfolio.neutrality import beta_neutralize, estimate_betas, factor_neutralize, net_beta


def test_estimate_betas_recovers_a_known_beta():
    rng = np.random.default_rng(0)
    market = pd.Series(rng.normal(0, 0.01, 300))
    returns = pd.DataFrame({"hi": 1.5 * market + rng.normal(0, 1e-4, 300), "lo": 0.5 * market + rng.normal(0, 1e-4, 300), "short": [np.nan] * 290 + list(rng.normal(size=10))})
    betas = estimate_betas(returns, market, window=120, min_obs=60)
    assert abs(betas["hi"] - 1.5) < 0.01 and abs(betas["lo"] - 0.5) < 0.01 and math.isnan(betas["short"])


def test_projection_and_hedge_both_zero_the_net_beta():
    weights, betas = {"A": 0.4, "B": 0.3, "C": -0.2}, {"A": 1.2, "B": 0.8, "C": 1.0, "H": 1.0}
    projected = beta_neutralize(weights, betas)
    assert abs(net_beta(projected, betas)) < 1e-12
    hedged = beta_neutralize(weights, betas, hedge="H")
    assert abs(net_beta(hedged, betas)) < 1e-12 and hedged["A"] == 0.4
    with pytest.raises(ValueError):
        beta_neutralize(weights, {"A": 1.0}, hedge="H")


def test_names_without_beta_are_untouched():
    out = beta_neutralize({"A": 0.5, "X": 0.5}, {"A": 1.0})
    assert out["X"] == 0.5 and abs(out["A"]) < 1e-12


def test_factor_neutralize_has_zero_exposure():
    rng = np.random.default_rng(1)
    names = [f"N{i}" for i in range(20)]
    exposures = pd.DataFrame(rng.normal(size=(20, 3)), index=names, columns=["size", "value", "mom"])
    weights = pd.Series(rng.normal(size=20), index=names)
    out = factor_neutralize(weights, exposures, ridge=0.0)
    assert np.allclose(exposures.T.to_numpy() @ out.to_numpy(), 0.0, atol=1e-10)
    partial = factor_neutralize(pd.concat([weights, pd.Series({"EXTRA": 1.0})]), exposures)
    assert partial["EXTRA"] == 1.0


@settings(max_examples=200, deadline=None)
@given(st.dictionaries(st.sampled_from(list("ABCDEF")), st.floats(-1, 1), min_size=1), st.dictionaries(st.sampled_from(list("ABCDEF")), st.floats(-3, 3), min_size=1))
def test_beta_neutralize_always_gives_net_beta_zero(weights, betas):
    out = beta_neutralize(weights, betas)
    known = sum(b * b for name, b in betas.items() if name in weights)
    if known > 1e-12:
        assert abs(net_beta(out, betas)) < 1e-9
