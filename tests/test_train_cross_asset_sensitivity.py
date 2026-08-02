"""Tests for train.py::build_cross_asset_sensitivity_features() (V5.1
Phase 2, item 8 / F2, development/Problems.md) - dataset-level sibling of
tests/test_cross_asset_sensitivity.py's pure-function tests. Conventions
match tests/test_train_alt_data_features.py: hand-built FRED series
fixtures, no mocking.

The per-asset-values-genuinely-differ test at the bottom is the acceptance
test for F2's entire premise: every OTHER macro_*/bond_*/alt_* feature in
this codebase is a per-date broadcast constant, invisible to a
cross-sectional ranker. This one must NOT be - two assets with different
market behavior must end up with different sensitivity betas on the same
date.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from train import build_cross_asset_sensitivity_features


def _config(**overrides):
    sensitivity = {
        "enabled": True,
        "lookback_days": 0,  # whole-history, keeps fixtures small
        "min_observations": 20,
        "drivers": {
            "vix": "implied_volatility_vix",
            "real_rate": "treasury_10yr_real",
            "credit": "credit_spread_baa10y",
            "dollar": "dollar_index",
        },
    }
    sensitivity.update(overrides)
    return {"phase1": {"features": {"cross_asset_sensitivity": sensitivity}}}


def _asset_frame(dates: list, returns: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "close_to_close_return_1d": returns})


def _driver_series(dates: list, levels: list[float]) -> list[dict]:
    return [{"date": d, "value": v} for d, v in zip(dates, levels)]


def test_build_cross_asset_sensitivity_features_disabled_writes_all_zero_columns():
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(30)]
    frames = {"AAPL": _asset_frame(dates, [0.01] * 30)}
    config = _config(enabled=False)

    result = build_cross_asset_sensitivity_features(frames, config, fred_series={})

    for name in (
        "sens_vix_beta", "sens_vix_interaction", "sens_real_rate_beta", "sens_real_rate_interaction",
        "sens_credit_beta", "sens_credit_interaction", "sens_dollar_beta", "sens_dollar_interaction",
    ):
        assert name in result["AAPL"].columns
        assert (result["AAPL"][name] == 0.0).all()


def test_build_cross_asset_sensitivity_features_missing_series_neutral_defaults_never_raises():
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(30)]
    frames = {"AAPL": _asset_frame(dates, [0.01] * 30)}
    config = _config()

    result = build_cross_asset_sensitivity_features(frames, config, fred_series={})

    frame = result["AAPL"]
    assert (frame["sens_vix_beta"] == 0.0).all()
    assert (frame["sens_vix_interaction"] == 0.0).all()


def test_build_cross_asset_sensitivity_features_adds_all_8_columns_to_every_asset():
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(30)]
    frames = {"AAPL": _asset_frame(dates, [0.01] * 30), "BTCUSD": _asset_frame(dates, [-0.01] * 30)}
    config = _config()

    result = build_cross_asset_sensitivity_features(frames, config, fred_series={})

    for ticker, frame in result.items():
        for driver in ("vix", "real_rate", "credit", "dollar"):
            assert f"sens_{driver}_beta" in frame.columns
            assert f"sens_{driver}_interaction" in frame.columns


def test_build_cross_asset_sensitivity_features_per_asset_values_genuinely_differ():
    # F2's acceptance test: HIGH_BETA tracks VIX changes closely (beta ~3),
    # LOW_BETA is nearly uncorrelated with VIX (beta ~0) - a genuine
    # cross-sectional difference a ranker could actually use.
    rng = np.random.default_rng(5)
    n = 100
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    vix_levels = 20.0 + np.cumsum(rng.normal(scale=0.5, size=n))
    vix_changes = np.diff(vix_levels, prepend=vix_levels[0])

    high_beta_returns = 3.0 * vix_changes + rng.normal(scale=0.001, size=n)
    low_beta_returns = rng.normal(scale=0.01, size=n)

    frames = {
        "HIGH_BETA": _asset_frame(dates, high_beta_returns.tolist()),
        "LOW_BETA": _asset_frame(dates, low_beta_returns.tolist()),
    }
    config = _config(min_observations=30)
    fred_series = {"implied_volatility_vix": _driver_series(dates, vix_levels.tolist())}

    result = build_cross_asset_sensitivity_features(frames, config, fred_series)

    high_beta_final = result["HIGH_BETA"]["sens_vix_beta"].iloc[-1]
    low_beta_final = result["LOW_BETA"]["sens_vix_beta"].iloc[-1]

    assert high_beta_final != pytest.approx(low_beta_final, abs=0.5)
    assert high_beta_final > low_beta_final

    # Per-date cross-sectional dispersion is non-zero - the direct
    # acceptance criterion (a per-date std > 0, unlike every broadcast
    # macro_*/bond_*/alt_* feature which is identical across assets).
    last_date_values = [result[ticker]["sens_vix_beta"].iloc[-1] for ticker in frames]
    assert np.std(last_date_values) > 0.0


def test_build_cross_asset_sensitivity_features_interaction_uses_latest_delta():
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(30)]
    frames = {"AAPL": _asset_frame(dates, [0.01] * 30)}
    config = _config(min_observations=5)
    # A step change on the LAST date only, so the final interaction term is
    # driven by a known, hand-computable delta.
    levels = [20.0] * 29 + [25.0]
    fred_series = {"implied_volatility_vix": _driver_series(dates, levels)}

    result = build_cross_asset_sensitivity_features(frames, config, fred_series)

    interaction_final = result["AAPL"]["sens_vix_interaction"].iloc[-1]
    beta_final = result["AAPL"]["sens_vix_beta"].iloc[-1]
    assert interaction_final == pytest.approx(beta_final * 5.0)
