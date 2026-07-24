"""Pure Black-Scholes-Merton option pricing/greeks/implied-volatility - the
real-math foundation for greeks-aware options position sizing
(portfolio/options_strategy.py), per the user's explicit requirement: real
Black-Scholes greeks/IV computed from actual option chain data (when IB is
enabled), not proxies.

Stdlib only (math.erf for the normal CDF - no scipy dependency), same
"pure function, no I/O" convention as features/bond_features.py and
features/macro_features.py. Every function is a straight textbook
implementation, unit-tested against known closed-form values
(tests/test_options_greeks.py) and the put-call parity invariant.

`right` is always "call" or "put" (case-insensitive), matching the
vocabulary portfolio/options_strategy.py's chain rows use.

V4.7 (development/Problems.md - early-assignment/corporate-action
modeling) added baw_american_price(), a Barone-Adesi-Whaley American-
exercise approximation built entirely from this module's own European
bs_price()/_d1_d2()/_normal_cdf() - see its own docstring for the
degrade-to-European safety contract. Everything above it in this file
remains pure European BSM, unchanged.
"""

from __future__ import annotations

import math

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1_d2(spot: float, strike: float, time_to_expiry_years: float, risk_free_rate: float, volatility: float, dividend_yield: float) -> tuple[float, float]:
    variance_term = volatility * math.sqrt(time_to_expiry_years)
    d1 = (
        math.log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * volatility * volatility) * time_to_expiry_years
    ) / variance_term
    d2 = d1 - variance_term
    return d1, d2


def bs_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    dividend_yield: float,
    right: str,
) -> float:
    """European option price under Black-Scholes-Merton with a continuous
    dividend yield. Callers must ensure spot/strike/time_to_expiry_years/
    volatility are all strictly positive - this function does not
    neutral-default (unlike features/bond_features.py's pure functions):
    an option price is meaningless for a degenerate input, so callers
    (options_greeks.implied_volatility(), portfolio/options_strategy.py)
    are responsible for filtering those cases before calling in."""
    d1, d2 = _d1_d2(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
    discounted_spot = spot * math.exp(-dividend_yield * time_to_expiry_years)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    if right.lower() == "call":
        return discounted_spot * _normal_cdf(d1) - discounted_strike * _normal_cdf(d2)
    return discounted_strike * _normal_cdf(-d2) - discounted_spot * _normal_cdf(-d1)


def delta(spot: float, strike: float, time_to_expiry_years: float, risk_free_rate: float, volatility: float, dividend_yield: float, right: str) -> float:
    """dPrice/dSpot. Calls: [0, 1]. Puts: [-1, 0]."""
    d1, _ = _d1_d2(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
    discount = math.exp(-dividend_yield * time_to_expiry_years)
    if right.lower() == "call":
        return discount * _normal_cdf(d1)
    return discount * (_normal_cdf(d1) - 1.0)


def gamma(spot: float, strike: float, time_to_expiry_years: float, risk_free_rate: float, volatility: float, dividend_yield: float) -> float:
    """d^2Price/dSpot^2 - identical for calls and puts (no `right` param)."""
    d1, _ = _d1_d2(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
    return math.exp(-dividend_yield * time_to_expiry_years) * _normal_pdf(d1) / (spot * volatility * math.sqrt(time_to_expiry_years))


def vega(spot: float, strike: float, time_to_expiry_years: float, risk_free_rate: float, volatility: float, dividend_yield: float) -> float:
    """dPrice/dVolatility, per 1.0 (100 percentage points) of volatility -
    identical for calls and puts (no `right` param). Divide by 100 for the
    conventional "per 1 vol point" quoting convention if needed."""
    d1, _ = _d1_d2(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
    return spot * math.exp(-dividend_yield * time_to_expiry_years) * _normal_pdf(d1) * math.sqrt(time_to_expiry_years)


def theta(spot: float, strike: float, time_to_expiry_years: float, risk_free_rate: float, volatility: float, dividend_yield: float, right: str) -> float:
    """dPrice/dTime, annualized (divide by 365 for a per-calendar-day
    figure)."""
    d1, d2 = _d1_d2(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
    discounted_spot = spot * math.exp(-dividend_yield * time_to_expiry_years)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    decay_term = -(discounted_spot * _normal_pdf(d1) * volatility) / (2.0 * math.sqrt(time_to_expiry_years))
    if right.lower() == "call":
        return decay_term - risk_free_rate * discounted_strike * _normal_cdf(d2) + dividend_yield * discounted_spot * _normal_cdf(d1)
    return decay_term + risk_free_rate * discounted_strike * _normal_cdf(-d2) - dividend_yield * discounted_spot * _normal_cdf(-d1)


def rho(spot: float, strike: float, time_to_expiry_years: float, risk_free_rate: float, volatility: float, dividend_yield: float, right: str) -> float:
    """dPrice/dRiskFreeRate, per 1.0 (100 percentage points) of rate."""
    _, d2 = _d1_d2(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    if right.lower() == "call":
        return discounted_strike * time_to_expiry_years * _normal_cdf(d2)
    return -discounted_strike * time_to_expiry_years * _normal_cdf(-d2)


def compute_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    dividend_yield: float,
    right: str,
) -> dict:
    """Single call site wrapping the 5 functions above, for
    portfolio/options_strategy.py/main.py call-site brevity."""
    return {
        "delta": delta(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield, right),
        "gamma": gamma(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield),
        "theta": theta(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield, right),
        "vega": vega(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield),
        "rho": rho(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield, right),
        "iv": volatility,
    }


def implied_volatility(
    option_price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    dividend_yield: float,
    right: str,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> float | None:
    """Safeguarded Newton-Raphson (Newton step when it stays inside the
    current bracket, bisection step otherwise) - vega can be ~0 deep
    ITM/OTM or near expiry, which would blow up pure Newton-Raphson.
    bs_price() is monotonically increasing in volatility for T>0, so the
    [low, high] bracket only ever narrows and bisection alone is already
    guaranteed to converge; Newton just speeds that up when it's safe to
    use.

    Returns None (never raises, never NaN) when: option_price is
    non-positive, any of spot/strike/time_to_expiry_years is non-positive,
    option_price violates the no-arbitrage intrinsic-value bound, the
    market price falls outside the achievable range for the search
    bracket [1e-6, 5.0] (500% vol), or the solver fails to converge within
    max_iterations - same "None = failed to compute, never a crash"
    convention as features/bond_features.py::empirical_duration_beta()."""
    if option_price is None or option_price <= 0.0 or spot <= 0.0 or strike <= 0.0 or time_to_expiry_years <= 0.0:
        return None

    right_normalized = right.lower()
    discounted_spot = spot * math.exp(-dividend_yield * time_to_expiry_years)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    intrinsic = max(discounted_spot - discounted_strike, 0.0) if right_normalized == "call" else max(discounted_strike - discounted_spot, 0.0)
    if option_price < intrinsic - tolerance:
        return None

    low, high = 1e-6, 5.0
    price_at_low = bs_price(spot, strike, time_to_expiry_years, risk_free_rate, low, dividend_yield, right_normalized) - option_price
    price_at_high = bs_price(spot, strike, time_to_expiry_years, risk_free_rate, high, dividend_yield, right_normalized) - option_price
    if price_at_low > 0.0 or price_at_high < 0.0:
        return None

    sigma = 0.2
    for _ in range(max_iterations):
        price_diff = bs_price(spot, strike, time_to_expiry_years, risk_free_rate, sigma, dividend_yield, right_normalized) - option_price
        if abs(price_diff) < tolerance:
            return sigma

        if price_diff > 0.0:
            high = sigma
        else:
            low = sigma

        option_vega = vega(spot, strike, time_to_expiry_years, risk_free_rate, sigma, dividend_yield)
        newton_sigma = sigma - price_diff / option_vega if option_vega > 1e-10 else None
        if newton_sigma is not None and low < newton_sigma < high:
            sigma = newton_sigma
        else:
            sigma = (low + high) / 2.0

    return None


def baw_american_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    dividend_yield: float,
    volatility: float,
    right: str,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> float:
    """Barone-Adesi & Whaley (1987) quadratic approximation for American
    option prices - "Efficient Analytic Approximation of American Option
    Values," Journal of Finance 42(2). Built entirely from this module's
    existing bs_price()/_d1_d2()/_normal_cdf() - the European price IS the
    approximation's own building block, not a separately-derived formula.
    Verified numerically against a 3000-step CRR binomial tree across
    several call/put/ITM/OTM/dividend combinations during development
    (differences of a few cents on option prices in the $6-14 range,
    consistent with BAW's known ~1-2% approximation error).

    Never raises. Degrades to the European bs_price() value whenever: the
    dividend yield is non-positive for a call (a call should never be
    exercised early with zero dividend drag - the standard textbook
    shortcut, not an approximation gap), any input is degenerate
    (time/vol/spot/strike non-positive - returns intrinsic value in that
    case instead), or the critical-price search fails to find a
    bracketing sign change / doesn't converge within max_iterations. This
    is a SAFE direction to degrade in: the American price is always >= the
    European price, so under-pricing by falling back to the European
    value never overstates risk in the direction that matters for a short
    option holder (the whole reason this function exists).

    Uses a safeguarded bisection search for the critical price (rather
    than implied_volatility()'s Newton-primary approach) - the BAW
    matching condition has no simple closed-form derivative the way vega
    is for the IV solve, so bisection (guaranteed convergence given a
    verified sign-changing bracket, checked explicitly before iterating)
    is the more directly verifiable choice for a per-bar risk signal that
    must never silently mis-converge."""
    right_normalized = right.lower()
    if time_to_expiry_years <= 0.0 or volatility <= 0.0 or spot <= 0.0 or strike <= 0.0:
        return max(spot - strike, 0.0) if right_normalized == "call" else max(strike - spot, 0.0)

    european_price = bs_price(spot, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield, right_normalized)

    if right_normalized == "call" and dividend_yield <= 0.0:
        return european_price

    cost_of_carry = risk_free_rate - dividend_yield
    variance = volatility * volatility
    big_m = 2.0 * risk_free_rate / variance
    big_n = 2.0 * cost_of_carry / variance
    big_k = 1.0 - math.exp(-risk_free_rate * time_to_expiry_years)
    if big_k <= 0.0:
        return european_price

    discriminant = (big_n - 1.0) ** 2 + 4.0 * big_m / big_k
    if discriminant < 0.0:
        return european_price

    if right_normalized == "call":
        q_root = (-(big_n - 1.0) + math.sqrt(discriminant)) / 2.0
        if q_root <= 0.0:
            return european_price

        def matching_residual(critical_price: float) -> float:
            d1, _ = _d1_d2(critical_price, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
            euro_at_critical = bs_price(
                critical_price, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield, "call"
            )
            term = (1.0 - math.exp(-dividend_yield * time_to_expiry_years) * _normal_cdf(d1)) * critical_price / q_root
            return critical_price - strike - euro_at_critical - term

        low, high = strike, max(strike, spot) * 50.0
    else:
        q_root = (-(big_n - 1.0) - math.sqrt(discriminant)) / 2.0
        if q_root >= 0.0:
            return european_price

        def matching_residual(critical_price: float) -> float:
            d1, _ = _d1_d2(critical_price, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
            euro_at_critical = bs_price(
                critical_price, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield, "put"
            )
            term = (1.0 - math.exp(-dividend_yield * time_to_expiry_years) * _normal_cdf(-d1)) * critical_price / q_root
            return strike - critical_price - euro_at_critical + term

        low, high = 1e-6, strike

    residual_low = matching_residual(low)
    residual_high = matching_residual(high)
    if residual_low == 0.0:
        critical_price = low
    elif residual_high == 0.0:
        critical_price = high
    elif (residual_low > 0.0) == (residual_high > 0.0):
        return european_price
    else:
        critical_price = None
        for _ in range(max_iterations):
            midpoint = (low + high) / 2.0
            residual_mid = matching_residual(midpoint)
            if abs(residual_mid) < tolerance:
                critical_price = midpoint
                break
            if (residual_mid > 0.0) == (residual_low > 0.0):
                low = midpoint
                residual_low = residual_mid
            else:
                high = midpoint
        if critical_price is None:
            return european_price

    if right_normalized == "call":
        if spot >= critical_price:
            return max(spot - strike, 0.0)
        d1, _ = _d1_d2(critical_price, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
        coefficient = (critical_price / q_root) * (
            1.0 - math.exp(-dividend_yield * time_to_expiry_years) * _normal_cdf(d1)
        )
        return european_price + coefficient * (spot / critical_price) ** q_root

    if spot <= critical_price:
        return max(strike - spot, 0.0)
    d1, _ = _d1_d2(critical_price, strike, time_to_expiry_years, risk_free_rate, volatility, dividend_yield)
    coefficient = -(critical_price / q_root) * (
        1.0 - math.exp(-dividend_yield * time_to_expiry_years) * _normal_cdf(-d1)
    )
    return european_price + coefficient * (spot / critical_price) ** q_root
