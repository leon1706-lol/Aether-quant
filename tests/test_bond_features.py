import random

from features.bond_features import (
    CREDIT_SPREAD_LEVEL_NEUTRAL,
    YIELD_CURVE_CURVATURE_NEUTRAL,
    YIELD_CURVE_LEVEL_NEUTRAL,
    credit_spread_level,
    empirical_duration_beta,
    yield_curve_curvature,
    yield_curve_level,
    yield_curve_slope,
)


# ---------------------------------------------------------------------------
# yield_curve_level / slope / curvature - neutral defaults on missing input
# ---------------------------------------------------------------------------


def test_yield_curve_level_returns_value():
    assert yield_curve_level(0.045) == 0.045


def test_yield_curve_level_neutral_default_on_none():
    assert yield_curve_level(None) == YIELD_CURVE_LEVEL_NEUTRAL


def test_yield_curve_slope_computes_10yr_minus_3mo():
    assert yield_curve_slope(0.045, 0.052) == 0.045 - 0.052


def test_yield_curve_slope_negative_when_inverted():
    slope = yield_curve_slope(treasury_10yr_yield=0.04, treasury_3mo_yield=0.05)
    assert slope < 0.0


def test_yield_curve_slope_neutral_default_on_missing_input():
    assert yield_curve_slope(None, 0.05) == 0.0
    assert yield_curve_slope(0.05, None) == 0.0


def test_yield_curve_curvature_computes_butterfly():
    curvature = yield_curve_curvature(treasury_2yr_yield=0.04, treasury_5yr_yield=0.041, treasury_10yr_yield=0.043)
    assert abs(curvature - (2 * 0.041 - 0.04 - 0.043)) < 1e-12


def test_yield_curve_curvature_neutral_default_on_missing_input():
    assert yield_curve_curvature(None, 0.04, 0.045) == YIELD_CURVE_CURVATURE_NEUTRAL
    assert yield_curve_curvature(0.04, None, 0.045) == YIELD_CURVE_CURVATURE_NEUTRAL
    assert yield_curve_curvature(0.04, 0.041, None) == YIELD_CURVE_CURVATURE_NEUTRAL


# ---------------------------------------------------------------------------
# credit_spread_level
# ---------------------------------------------------------------------------


def test_credit_spread_level_returns_value():
    assert credit_spread_level(2.1) == 2.1


def test_credit_spread_level_neutral_default_on_none():
    assert credit_spread_level(None) == CREDIT_SPREAD_LEVEL_NEUTRAL


# ---------------------------------------------------------------------------
# empirical_duration_beta
# ---------------------------------------------------------------------------


def test_empirical_duration_beta_recovers_known_synthetic_slope():
    random.seed(42)
    true_beta = -0.15
    delta_yield = [random.uniform(-0.05, 0.05) for _ in range(200)]
    returns = [true_beta * dy + random.uniform(-0.0005, 0.0005) for dy in delta_yield]

    recovered = empirical_duration_beta(returns, delta_yield, min_observations=60)

    assert recovered is not None
    assert abs(recovered - true_beta) < 0.02


def test_empirical_duration_beta_none_below_min_observations():
    returns = [0.01, -0.01, 0.02]
    delta_yield = [0.001, -0.001, 0.002]
    assert empirical_duration_beta(returns, delta_yield, min_observations=60) is None


def test_empirical_duration_beta_drops_none_pairs():
    returns = [0.01, None, 0.02, 0.03] * 20
    delta_yield = [0.001, 0.002, None, 0.003] * 20
    # Every group of 4 has 2 valid pairs (index 0 and 3) -> 40 valid pairs,
    # above the default min_observations=60 floor unless explicitly lowered.
    recovered = empirical_duration_beta(returns, delta_yield, min_observations=10)
    assert recovered is not None


def test_empirical_duration_beta_none_when_delta_yield_has_zero_variance():
    returns = [0.01 * i for i in range(100)]
    delta_yield = [0.002] * 100  # constant -> zero variance, OLS slope undefined
    assert empirical_duration_beta(returns, delta_yield, min_observations=10) is None


def test_empirical_duration_beta_long_duration_beta_exceeds_short_duration_beta_in_magnitude():
    # A long-duration bond ETF should show a larger |beta| than a
    # short-duration one for the same yield-change series - sanity check
    # against the real-world TLT vs SHY comparison this feature is meant
    # to capture (see train.py's end-to-end dataset verification).
    random.seed(7)
    delta_yield = [random.uniform(-0.05, 0.05) for _ in range(200)]
    long_duration_returns = [-0.18 * dy + random.uniform(-0.0003, 0.0003) for dy in delta_yield]
    short_duration_returns = [-0.02 * dy + random.uniform(-0.0003, 0.0003) for dy in delta_yield]

    long_beta = empirical_duration_beta(long_duration_returns, delta_yield, min_observations=60)
    short_beta = empirical_duration_beta(short_duration_returns, delta_yield, min_observations=60)

    assert abs(long_beta) > abs(short_beta)
