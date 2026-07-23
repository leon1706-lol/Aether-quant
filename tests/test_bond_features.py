import math
import random

from features.bond_features import (
    CREDIT_SPREAD_LEVEL_NEUTRAL,
    YIELD_CURVE_CURVATURE_NEUTRAL,
    YIELD_CURVE_LEVEL_NEUTRAL,
    analytic_convexity,
    analytic_modified_duration,
    bond_dv01,
    credit_spread_level,
    empirical_duration_beta,
    nearest_yield_curve_point,
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


# ---------------------------------------------------------------------------
# analytic_modified_duration / analytic_convexity / bond_dv01 (V4.6,
# development/Problems.md #60, Roadmap "single-bond trading" reframed)
# ---------------------------------------------------------------------------


def test_analytic_modified_duration_zero_coupon_bond_equals_maturity_over_one_plus_period_yield():
    # A zero-coupon bond's Macaulay duration is EXACTLY its maturity (only
    # one cash flow, at maturity) - modified duration is then exactly
    # maturity / (1 + y/m), a precise analytic cross-check, not just a
    # plausibility range.
    md = analytic_modified_duration(yield_to_maturity=0.05, coupon_rate=0.0, years_to_maturity=5, payments_per_year=2)
    assert math.isclose(md, 5 / (1 + 0.05 / 2))


def test_analytic_modified_duration_par_bond_10y_5pct_matches_textbook_reference():
    # A 10-year, 5% semi-annual coupon bond priced at par (yield == coupon)
    # has a well-known textbook modified duration figure (~7.79 years).
    md = analytic_modified_duration(yield_to_maturity=0.05, coupon_rate=0.05, years_to_maturity=10, payments_per_year=2)
    assert 7.7 < md < 7.9


def test_analytic_modified_duration_longer_maturity_gives_longer_duration():
    short_md = analytic_modified_duration(0.05, 0.05, 2, payments_per_year=2)
    long_md = analytic_modified_duration(0.05, 0.05, 20, payments_per_year=2)
    assert long_md > short_md


def test_analytic_modified_duration_none_on_missing_input():
    assert analytic_modified_duration(None, 0.05, 10) is None
    assert analytic_modified_duration(0.05, None, 10) is None
    assert analytic_modified_duration(0.05, 0.05, None) is None


def test_analytic_modified_duration_none_on_non_positive_maturity():
    assert analytic_modified_duration(0.05, 0.05, 0) is None
    assert analytic_modified_duration(0.05, 0.05, -1) is None


def test_analytic_convexity_positive_for_a_normal_bond():
    convexity = analytic_convexity(0.05, 0.05, 10, payments_per_year=2)
    assert convexity is not None
    assert convexity > 0.0


def test_analytic_convexity_none_on_missing_input():
    assert analytic_convexity(None, 0.05, 10) is None


def test_analytic_convexity_longer_maturity_gives_higher_convexity():
    short_convexity = analytic_convexity(0.05, 0.05, 2, payments_per_year=2)
    long_convexity = analytic_convexity(0.05, 0.05, 20, payments_per_year=2)
    assert long_convexity > short_convexity


def test_bond_dv01_scales_linearly_with_notional():
    single = bond_dv01(price=100.0, modified_duration=7.8, notional=1.0)
    scaled = bond_dv01(price=100.0, modified_duration=7.8, notional=1_000_000.0)
    assert single is not None and scaled is not None
    assert math.isclose(scaled, single * 1_000_000.0)


def test_bond_dv01_matches_formula():
    dv01 = bond_dv01(price=100.0, modified_duration=7.8, notional=1_000_000.0)
    assert math.isclose(dv01, 100.0 * 7.8 * 0.0001 * 1_000_000.0)


def test_bond_dv01_none_on_missing_or_non_positive_input():
    assert bond_dv01(None, 7.8) is None
    assert bond_dv01(100.0, None) is None
    assert bond_dv01(0.0, 7.8) is None
    assert bond_dv01(100.0, 7.8, notional=0.0) is None


# ---------------------------------------------------------------------------
# nearest_yield_curve_point
# ---------------------------------------------------------------------------


def test_nearest_yield_curve_point_picks_closest_maturity():
    curve = {0.25: 0.05, 2.0: 0.045, 5.0: 0.043, 10.0: 0.042}
    assert nearest_yield_curve_point(17.5, curve) == 0.042  # nearest to 10.0 (the longest available point)
    assert nearest_yield_curve_point(6.0, curve) == 0.043  # |6-5|=1.0 < |6-10|=4.0 -> nearest to 5.0


def test_nearest_yield_curve_point_skips_none_valued_points():
    curve = {0.25: None, 2.0: 0.045, 5.0: None, 10.0: 0.042}
    assert nearest_yield_curve_point(9.0, curve) == 0.042


def test_nearest_yield_curve_point_none_when_no_points_have_values():
    assert nearest_yield_curve_point(5.0, {0.25: None, 2.0: None}) is None


def test_nearest_yield_curve_point_none_when_years_to_maturity_is_none():
    assert nearest_yield_curve_point(None, {0.25: 0.05}) is None
