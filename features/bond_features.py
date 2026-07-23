"""Shared, pure real-yield-curve/credit-spread/duration feature
implementations - additive sibling to features/macro_features.py, using
data_pipeline/fred_backfill.py's actual FRED Treasury-yield/credit-spread
series rather than macro_features.py's bond-ETF-price-momentum proxies.

Broadcast identically to EVERY asset's model input (not just bond-tagged
assets) - same "compute once per date/bar, every asset sees it" shape as
macro_features.py, and the concrete mechanism by which bond/yield-curve
signal becomes usable for equity/crypto/future/option predictions too, not
just bonds themselves.

Imported by BOTH train.py (offline, per-date FRED-series lookup) and
main.py (runtime, once per bar) for parity by construction - same
convention as features/technical_indicators.py and features/macro_features.py.

Every function neutral-defaults to 0.0 on missing input - never raises -
except empirical_duration_beta(), which returns None (not 0.0) below its
minimum-observation floor: an unknown duration sensitivity must never be
indistinguishable from a genuinely-zero one, the same "None = absent, 0.0 =
neutral" distinction risk/position_sizing.py::rank_sizing_multiplier()
already draws for missing rank predictions.

V4.6 (development/Problems.md, Roadmap "Assets" - "single-bond trading")
added analytic_modified_duration()/analytic_convexity()/bond_dv01(), a
real closed-form bond-math sibling to empirical_duration_beta() above -
NOT a replacement for it. Individual-bond trading was confirmed
INFEASIBLE under this Lean version's security model (no SecurityType.Bond,
no AddBond, no Common/Securities/Bond/ implementation anywhere in the real
Lean source tree - every "bond" Lean supports is an equity-typed ETF
wrapper, exactly what this codebase already does) - these 3 functions
instead deepen the EXISTING bond-ETF sleeve's analytics, using
bond_metadata.duration_proxy_years (already configured per-ETF in
config.json) as an assumed maturity and bond_metadata.assumed_coupon_rate
(or, when absent, the treasury yield-curve point nearest that maturity, as
an at-par-pricing proxy coupon) as an assumed coupon - explicitly an
ETF-level APPROXIMATION, not real per-bond cash-flow data. Deliberately
informational only (not merged into base_features/BOND_FEATURE_NAMES,
which feed the TRAINED model's fixed-dimensionality input tensor - adding
a feature there would require a coordinated retrain); surfaced instead via
main.py's own per-symbol bond-analytics computation for dashboard/state
visibility, same "additive, doesn't touch the model" precedent
_bond_empirical_duration_beta_for_symbol() already establishes for
per-symbol (as opposed to broadcast) bond features.
"""

from __future__ import annotations

YIELD_CURVE_LEVEL_NEUTRAL = 0.0
YIELD_CURVE_SLOPE_NEUTRAL = 0.0
YIELD_CURVE_CURVATURE_NEUTRAL = 0.0
CREDIT_SPREAD_LEVEL_NEUTRAL = 0.0

BOND_FEATURE_NAMES = [
    "bond_yield_curve_level",
    "bond_yield_curve_slope",
    "bond_yield_curve_curvature",
    "bond_credit_spread_level",
    "bond_empirical_duration_beta",
]


def yield_curve_level(treasury_10yr_yield: float | None) -> float:
    """Raw level of the 10yr Treasury yield (e.g. 0.045 for 4.5%). Returns
    YIELD_CURVE_LEVEL_NEUTRAL (0.0) when unavailable."""
    if treasury_10yr_yield is None:
        return YIELD_CURVE_LEVEL_NEUTRAL
    return float(treasury_10yr_yield)


def yield_curve_slope(treasury_10yr_yield: float | None, treasury_3mo_yield: float | None) -> float:
    """10yr - 3mo - the standard recession-signal curve slope (negative =
    inverted curve). Real-data replacement for
    macro_features.yield_curve_slope_proxy()'s price-momentum proxy.
    Returns YIELD_CURVE_SLOPE_NEUTRAL (0.0) when either input is missing."""
    if treasury_10yr_yield is None or treasury_3mo_yield is None:
        return YIELD_CURVE_SLOPE_NEUTRAL
    return float(treasury_10yr_yield) - float(treasury_3mo_yield)


def yield_curve_curvature(
    treasury_2yr_yield: float | None,
    treasury_5yr_yield: float | None,
    treasury_10yr_yield: float | None,
) -> float:
    """2*5yr - 2yr - 10yr - the standard butterfly/curvature measure of
    curve shape independent of its overall level or slope. Returns
    YIELD_CURVE_CURVATURE_NEUTRAL (0.0) when any input is missing."""
    if treasury_2yr_yield is None or treasury_5yr_yield is None or treasury_10yr_yield is None:
        return YIELD_CURVE_CURVATURE_NEUTRAL
    return 2.0 * float(treasury_5yr_yield) - float(treasury_2yr_yield) - float(treasury_10yr_yield)


def credit_spread_level(baa10y_spread: float | None) -> float:
    """Raw BAA10Y (Moody's Baa corporate bond yield relative to the 10yr
    Treasury) level - widens when credit risk appetite deteriorates.
    Real-data replacement for macro_features.credit_spread_proxy()'s
    momentum-based proxy. Returns CREDIT_SPREAD_LEVEL_NEUTRAL (0.0) when
    unavailable."""
    if baa10y_spread is None:
        return CREDIT_SPREAD_LEVEL_NEUTRAL
    return float(baa10y_spread)


def empirical_duration_beta(
    etf_daily_returns: list[float | None],
    delta_10yr_yield_daily: list[float | None],
    min_observations: int = 60,
) -> float | None:
    """Rolling OLS slope of ETF daily returns regressed on same-day
    Delta-10yr-yield: an empirical "how much does this ETF move per unit of
    yield change" duration proxy, since these are ETFs with no single
    stated maturity, not individual bonds with a textbook duration figure.

    Pairs the two series positionally (index i of each list must already
    correspond to the same trading date - callers are responsible for
    alignment), drops any pair where either side is None, and requires at
    least min_observations valid pairs. Returns None (not 0.0) below that
    floor - a missing/insufficient-history duration estimate must be
    distinguishable from "genuinely zero duration sensitivity"."""
    paired = [
        (x, y)
        for x, y in zip(etf_daily_returns, delta_10yr_yield_daily)
        if x is not None and y is not None
    ]
    if len(paired) < min_observations:
        return None

    xs = [float(pair[1]) for pair in paired]
    ys = [float(pair[0]) for pair in paired]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    # An exact `== 0.0` check is not robust here: for a mathematically
    # constant xs, whether mean_x/variance_x round to exactly 0.0 depends on
    # sum()'s internal summation algorithm, which CPython changed (naive
    # left-to-right -> compensated) between 3.11 and 3.12 - the same input
    # can produce a true 0.0 on one Python version and a tiny rounding-noise
    # variance (~1e-20 scale, versus real delta-yield variance on the order
    # of 1e-4 to 1e-8) on another, silently producing a wild
    # covariance/near-zero-noise ratio instead of the intended None. See
    # development/Problems.md#10.
    if variance_x < 1e-12:
        return None
    return covariance / variance_x


def _bond_cash_flows(coupon_rate: float, years_to_maturity: float, payments_per_year: int, face_value: float = 100.0) -> list[float]:
    """Coupon + principal cash-flow schedule for a plain-vanilla,
    fixed-coupon bond priced at face_value=100 (a standard convention -
    duration/convexity are scale-invariant per-unit-price ratios, so the
    actual face value used doesn't affect the resulting figures). One
    entry per period; the LAST entry additionally includes the face_value
    repayment. Returns [] for a non-positive period count."""
    num_periods = max(int(round(years_to_maturity * payments_per_year)), 0)
    if num_periods == 0:
        return []
    coupon_per_period = coupon_rate / payments_per_year * face_value
    cash_flows = [coupon_per_period] * num_periods
    cash_flows[-1] += face_value
    return cash_flows


def analytic_modified_duration(
    yield_to_maturity: float | None,
    coupon_rate: float | None,
    years_to_maturity: float | None,
    payments_per_year: int = 2,
) -> float | None:
    """Standard closed-form modified duration from a plain-vanilla,
    fixed-coupon cash-flow schedule: Macaulay duration (the price-weighted
    average time to each cash flow, in years) divided by
    (1 + yield_to_maturity/payments_per_year).

    A genuinely DIFFERENT estimate from empirical_duration_beta() above,
    not a replacement for it: empirical_duration_beta() measures how much
    an ETF's OWN observed price actually moved per unit of yield change (a
    market-realized sensitivity); this function computes what a
    HYPOTHETICAL plain-vanilla bond with the given yield/coupon/maturity
    would theoretically be sensitive to, from cash-flow math alone - see
    this module's own docstring for the ETF-level-approximation caveat on
    what yield_to_maturity/coupon_rate/years_to_maturity should be sourced
    from in practice.

    Returns None (never raises) when any input is missing, years_to_maturity
    is non-positive, or the computed price is non-positive (a degenerate/
    extreme-negative-yield edge case) - an unknown/undefined duration must
    never be indistinguishable from a genuinely-zero one, the same
    convention empirical_duration_beta() already established."""
    if yield_to_maturity is None or coupon_rate is None or years_to_maturity is None or years_to_maturity <= 0:
        return None
    period_yield = float(yield_to_maturity) / payments_per_year
    if period_yield <= -1.0:
        return None
    cash_flows = _bond_cash_flows(float(coupon_rate), float(years_to_maturity), payments_per_year)
    if not cash_flows:
        return None

    discounted = [cf / (1.0 + period_yield) ** (t + 1) for t, cf in enumerate(cash_flows)]
    price = sum(discounted)
    if price <= 0.0:
        return None
    weighted_time = sum(((t + 1) / payments_per_year) * pv for t, pv in enumerate(discounted))
    macaulay_duration = weighted_time / price
    return macaulay_duration / (1.0 + period_yield)


def analytic_convexity(
    yield_to_maturity: float | None,
    coupon_rate: float | None,
    years_to_maturity: float | None,
    payments_per_year: int = 2,
) -> float | None:
    """Standard closed-form convexity (the second derivative of bond price
    with respect to yield, annualized) from the same plain-vanilla
    cash-flow schedule analytic_modified_duration() uses - same
    ETF-level-approximation caveat and degrade-to-None convention."""
    if yield_to_maturity is None or coupon_rate is None or years_to_maturity is None or years_to_maturity <= 0:
        return None
    period_yield = float(yield_to_maturity) / payments_per_year
    if period_yield <= -1.0:
        return None
    cash_flows = _bond_cash_flows(float(coupon_rate), float(years_to_maturity), payments_per_year)
    if not cash_flows:
        return None

    discounted = [cf / (1.0 + period_yield) ** (t + 1) for t, cf in enumerate(cash_flows)]
    price = sum(discounted)
    if price <= 0.0:
        return None
    convexity_sum = sum(
        (t + 1) * (t + 2) * pv / (1.0 + period_yield) ** 2 for t, pv in enumerate(discounted)
    )
    return convexity_sum / (price * payments_per_year ** 2)


def bond_dv01(price: float | None, modified_duration: float | None, notional: float = 1.0) -> float | None:
    """Dollar duration per 1bp yield move (DV01):
    price * modified_duration * 0.0001 * notional - a directly useful
    risk-sizing number (expected dollar P&L for a 1 basis point yield
    change). Returns None (never raises) when price/modified_duration is
    missing, or price/notional is non-positive."""
    if price is None or modified_duration is None or price <= 0.0 or notional <= 0.0:
        return None
    return float(price) * float(modified_duration) * 0.0001 * float(notional)


def nearest_yield_curve_point(years_to_maturity: float | None, curve_points: dict) -> float | None:
    """Picks the yield-curve observation whose maturity (in years, the
    dict's keys) is CLOSEST to years_to_maturity - the at-par-pricing
    proxy coupon/yield fallback analytic_modified_duration()/
    analytic_convexity() need when bond_metadata.assumed_coupon_rate isn't
    explicitly configured for an ETF. A coarse approximation by
    construction (this codebase's own Treasury curve only has 4 points -
    3mo/2yr/5yr/10yr - so a long-duration ETF's true maturity is
    necessarily approximated by the longest available point); callers
    already document that limitation, this function just picks the
    nearest one rather than guessing further. Skips any None-valued point
    (a FRED series with no observation as-of the current date) - returns
    None (never raises) when no curve point has a value at all, or
    years_to_maturity is None."""
    if years_to_maturity is None:
        return None
    usable_points = {maturity: yield_value for maturity, yield_value in curve_points.items() if yield_value is not None}
    if not usable_points:
        return None
    nearest_maturity = min(usable_points, key=lambda maturity: abs(maturity - years_to_maturity))
    return usable_points[nearest_maturity]
