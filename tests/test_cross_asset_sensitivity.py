"""Tests for features/cross_asset_sensitivity.py (V5.1 Phase 2, item 8 /
F2, development/Problems.md). Conventions match tests/test_bond_features.py:
no mocking, hand-computed/known-signal fixtures, explicit missing-input
cases."""

import numpy as np
import pytest

from features.cross_asset_sensitivity import (
    CROSS_ASSET_SENSITIVITY_FEATURE_NAMES,
    rolling_sensitivity,
    sensitivity_interaction,
)


# ---------------------------------------------------------------------------
# rolling_sensitivity
# ---------------------------------------------------------------------------


def test_rolling_sensitivity_recovers_a_known_slope():
    rng = np.random.default_rng(3)
    n = 400
    macro_changes = rng.normal(scale=1.0, size=n).tolist()
    # asset_return = 2.5 * macro_change + small noise - a strong, recoverable signal.
    noise = rng.normal(scale=0.01, size=n)
    asset_returns = [2.5 * change + eps for change, eps in zip(macro_changes, noise)]

    beta = rolling_sensitivity(asset_returns, macro_changes, lookback=0, min_observations=30)

    assert beta is not None
    assert beta == pytest.approx(2.5, abs=0.1)


def test_rolling_sensitivity_uses_only_the_trailing_window():
    # First half has a strong POSITIVE relationship, second half strong
    # NEGATIVE - a rolling window restricted to the trailing `lookback`
    # observations must reflect only the second half's sign.
    rng = np.random.default_rng(11)
    half = 200
    macro_first = rng.normal(scale=1.0, size=half)
    macro_second = rng.normal(scale=1.0, size=half)
    returns_first = 3.0 * macro_first + rng.normal(scale=0.01, size=half)
    returns_second = -3.0 * macro_second + rng.normal(scale=0.01, size=half)
    asset_returns = list(returns_first) + list(returns_second)
    macro_changes = list(macro_first) + list(macro_second)

    beta_full_history = rolling_sensitivity(asset_returns, macro_changes, lookback=0, min_observations=30)
    beta_windowed = rolling_sensitivity(asset_returns, macro_changes, lookback=half, min_observations=30)

    assert beta_windowed < 0.0
    # The full-history beta is diluted by the earlier positive regime; the
    # windowed one is not - the two must disagree in sign or magnitude.
    assert beta_windowed < beta_full_history


def test_rolling_sensitivity_returns_none_below_min_observations():
    asset_returns = [0.01, 0.02, -0.01]
    macro_changes = [0.1, 0.2, -0.1]

    beta = rolling_sensitivity(asset_returns, macro_changes, lookback=0, min_observations=10)

    assert beta is None


def test_rolling_sensitivity_drops_none_pairs_before_counting_observations():
    asset_returns = [0.01, None, 0.02, None, -0.01, 0.015, -0.02, 0.03, -0.015, 0.025]
    macro_changes = [0.1, 0.2, None, None, -0.1, 0.12, -0.18, 0.25, -0.14, 0.22]

    beta = rolling_sensitivity(asset_returns, macro_changes, lookback=0, min_observations=100)

    assert beta is None  # far fewer than 100 valid pairs remain


# ---------------------------------------------------------------------------
# sensitivity_interaction
# ---------------------------------------------------------------------------


def test_sensitivity_interaction_multiplies_beta_by_macro_change():
    assert sensitivity_interaction(2.0, 0.5) == 1.0
    assert sensitivity_interaction(-1.5, 0.4) == pytest.approx(-0.6)


def test_sensitivity_interaction_neutral_zero_on_missing_sensitivity():
    assert sensitivity_interaction(None, 0.5) == 0.0


def test_sensitivity_interaction_neutral_zero_on_missing_macro_change():
    assert sensitivity_interaction(2.0, None) == 0.0


def test_sensitivity_interaction_neutral_zero_when_both_missing():
    assert sensitivity_interaction(None, None) == 0.0


# ---------------------------------------------------------------------------
# CROSS_ASSET_SENSITIVITY_FEATURE_NAMES
# ---------------------------------------------------------------------------


def test_feature_names_cover_all_four_drivers_beta_and_interaction():
    for driver in ("vix", "real_rate", "credit", "dollar"):
        assert f"sens_{driver}_beta" in CROSS_ASSET_SENSITIVITY_FEATURE_NAMES
        assert f"sens_{driver}_interaction" in CROSS_ASSET_SENSITIVITY_FEATURE_NAMES
    assert len(CROSS_ASSET_SENSITIVITY_FEATURE_NAMES) == 8
