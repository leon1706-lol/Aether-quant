"""V6.0.0 (latency, rule R-LAT): the array sensitivity features equal the list-and-loop definition to rounding level."""

from __future__ import annotations

import random

import pytest

from features.bond_features import _scalar_duration_beta, duration_beta_from_arrays, empirical_duration_beta
from features.cross_asset_sensitivity import (
    CROSS_ASSET_SENSITIVITY_FEATURE_NAMES,
    rolling_sensitivity,
    sensitivity_features_vector,
    sensitivity_interaction,
)

DRIVERS = ("vix", "real_rate", "credit", "dollar")


def _list_path(closes, levels_by_driver, lookback, min_observations):
    """The definition main.py used before V6.0.0 (and train.py still uses): lists, None for a missing value."""
    tail = lookback + 1
    closes = closes[-tail:]
    returns = [None] + [(closes[i] / closes[i - 1] - 1.0) if closes[i - 1] else None for i in range(1, len(closes))]
    result = {}
    for driver, levels in levels_by_driver.items():
        levels = levels[-tail:]
        deltas = [None] * len(levels)
        for index in range(1, len(levels)):
            if levels[index] is not None and levels[index - 1] is not None:
                deltas[index] = levels[index] - levels[index - 1]
        beta = rolling_sensitivity(returns[-lookback:], deltas[-lookback:], lookback=lookback, min_observations=min_observations)
        result[f"sens_{driver}_beta"] = beta if beta is not None else 0.0
        result[f"sens_{driver}_interaction"] = sensitivity_interaction(beta, deltas[-1] if deltas else None)
    return result


def _series(rng, n, hole_rate=0.0, zero_close_at=None):
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + rng.gauss(0, 0.01)))
    if zero_close_at is not None and zero_close_at < n:
        closes[zero_close_at] = 0.0
    levels = {}
    for driver in DRIVERS:
        level, values = 20.0, []
        for _ in range(n):
            level += rng.gauss(0, 0.5)
            values.append(None if rng.random() < hole_rate else level)
        levels[driver] = values
    return closes, levels


@pytest.mark.parametrize("n", [1, 2, 30, 60, 140, 253, 260])
@pytest.mark.parametrize("hole_rate", [0.0, 0.05, 0.6])
def test_vector_features_equal_the_list_path(n, hole_rate):
    rng = random.Random(n * 7 + int(hole_rate * 10))
    closes, levels = _series(rng, n, hole_rate, zero_close_at=n // 2 if n > 40 else None)
    expected = _list_path(closes, levels, 252, 60)
    actual = sensitivity_features_vector(closes, levels, lookback=252, min_observations=60)
    assert set(actual) == set(expected) <= set(CROSS_ASSET_SENSITIVITY_FEATURE_NAMES)
    for name, value in expected.items():
        assert actual[name] == pytest.approx(value, rel=1e-9, abs=1e-12), name


def test_a_short_history_gives_the_neutral_zero_for_every_feature():
    rng = random.Random(3)
    closes, levels = _series(rng, 20)
    assert set(sensitivity_features_vector(closes, levels, lookback=252, min_observations=60).values()) == {0.0}


def test_a_constant_driver_has_no_beta():
    rng = random.Random(4)
    closes, levels = _series(rng, 260)
    levels["vix"] = [20.0] * 260
    out = sensitivity_features_vector(closes, levels, lookback=252, min_observations=60)
    assert out["sens_vix_beta"] == 0.0 and out["sens_vix_interaction"] == 0.0


def test_the_vector_ols_matches_the_scalar_one_to_1e12_and_keeps_nan_semantics():
    rng = random.Random(1)
    worst = 0.0
    for _ in range(400):
        n = rng.choice([60, 100, 252])
        ys = [rng.gauss(0, 0.01) if rng.random() > 0.03 else None for _ in range(n)]
        xs = [rng.gauss(0, 0.05) if rng.random() > 0.03 else None for _ in range(n)]
        vector = empirical_duration_beta(ys, xs, 40)
        scalar = _scalar_duration_beta(ys, xs, 40)
        assert (vector is None) == (scalar is None)
        if scalar is not None:
            worst = max(worst, abs(vector - scalar) / max(abs(scalar), 1e-30))
    assert worst < 1e-12
    nan_ys = [float("nan")] + [rng.gauss(0, 0.01) for _ in range(99)]
    xs = [rng.gauss(0, 0.05) for _ in range(100)]
    assert str(empirical_duration_beta(nan_ys, xs, 40)) == str(_scalar_duration_beta(nan_ys, xs, 40))  # a genuine NaN stays NaN


def test_array_ols_treats_nan_as_missing_and_applies_the_variance_guard():
    import numpy as np

    ys = np.array([0.01, 0.02, np.nan, 0.03, 0.04] * 20)
    xs = np.array([1.0, 2.0, 3.0, np.nan, 5.0] * 20)
    assert duration_beta_from_arrays(ys, xs, 20) is not None
    assert duration_beta_from_arrays(ys, np.ones(100), 20) is None  # zero variance
    assert duration_beta_from_arrays(ys, xs, 90) is None  # too few pairs
