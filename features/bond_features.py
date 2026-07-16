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
