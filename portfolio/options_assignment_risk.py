"""Early-call-assignment-risk signal (V4.7, development/Problems.md -
early-assignment probability/pricing modeling) - a genuinely distinct
concern from options_strategy.py's sizing/selection logic, so it lives in
its own module rather than folded in there.

Pure, stdlib-only functions (math only - no scipy/numpy, same convention
as features/options_greeks.py and every other portfolio/risk module),
every function degrades to a neutral "no risk detected" default (0.0/
False) on missing input rather than raising - main.py's
_apply_option_assignment_risk_sweep() is what actually acts on this
module's output, this module only ever computes the signal.

Scope, deliberately narrow: this module ONLY addresses dividend-driven
early exercise of a SHORT CALL leg - the one shape where the classic
textbook early-exercise-optimality rule (exercise early only when the
option's extrinsic value is less than the dividend about to be captured)
applies. A short PUT approaching expiry deep ITM is a pin-risk concern
already partly covered by portfolio/options_strategy.py::option_auto_close_due()'s
calendar-days-to-expiry safety net, not a dividend-driven concern - out of
scope here by construction (assignment_risk_score() below always scores a
put at 0.0).
"""

from __future__ import annotations

import math

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def extrinsic_value(option_price: float | None, spot: float, strike: float, right: str) -> float | None:
    """option_price minus intrinsic value. Returns None (not 0.0) when
    option_price is missing/non-positive - "unknown extrinsic value" must
    never be indistinguishable from "zero extrinsic value" (a real,
    meaningful early-exercise trigger condition in its own right), the
    same None-vs-neutral-default distinction features/bond_features.py's
    module docstring already establishes for this codebase."""
    if option_price is None or option_price <= 0.0:
        return None
    intrinsic = max(spot - strike, 0.0) if right.lower() == "call" else max(strike - spot, 0.0)
    return option_price - intrinsic


def early_exercise_optimal_for_dividend(extrinsic_value: float | None, expected_dividend_amount: float | None) -> bool:
    """Classic textbook rule: early call exercise is optimal only when the
    option's extrinsic value is LESS than the dividend the holder would
    capture by exercising before ex-div (they give up less time value than
    they gain in dividend). Returns False (never optimal) when either
    input is None - an unknown value never triggers a false-positive risk
    flag."""
    if extrinsic_value is None or expected_dividend_amount is None:
        return False
    return extrinsic_value < expected_dividend_amount


def days_to_next_ex_dividend(current_date, next_ex_dividend_date) -> int | None:
    """Pure date arithmetic, mirrors options_strategy.option_auto_close_due()'s
    own calendar-day-diff pattern. None when either input is missing -
    never raises."""
    if current_date is None or next_ex_dividend_date is None:
        return None
    return (next_ex_dividend_date - current_date).days


def assignment_risk_score(
    moneyness: float | None,
    right: str,
    extrinsic_value: float | None,
    expected_dividend_amount: float | None,
    days_to_next_ex_div: int | None,
    window_days: int,
) -> float:
    """0.0-1.0 composite early-call-assignment-risk score.

    Call-only by construction: a put always scores 0.0 (an upcoming
    dividend never makes early exercise of a long put rational - dividends
    only ever pull CALL exercise forward). Also 0.0 whenever: the leg
    isn't in-the-money (moneyness <= 1.0), there's no known upcoming
    ex-dividend date within window_days (including a negative
    days_to_next_ex_div - already past due, stale schedule), window_days
    itself is non-positive, or extrinsic_value/expected_dividend_amount is
    unknown (None) or expected_dividend_amount is non-positive.

    Within the risk window: scores at the time-proximity ceiling when
    early_exercise_optimal_for_dividend() is already True (extrinsic value
    below the expected dividend); otherwise decays smoothly via this
    module's own _normal_cdf() as the extrinsic-value cushion over the
    dividend widens (reusing this codebase's existing probabilistic
    vocabulary rather than inventing an ad hoc formula), further scaled by
    how close the ex-dividend date actually is within the window. Never
    raises."""
    if right.lower() != "call":
        return 0.0
    if moneyness is None or moneyness <= 1.0:
        return 0.0
    if window_days <= 0:
        return 0.0
    if days_to_next_ex_div is None or days_to_next_ex_div < 0 or days_to_next_ex_div > window_days:
        return 0.0
    if extrinsic_value is None or expected_dividend_amount is None or expected_dividend_amount <= 0.0:
        return 0.0

    time_factor = 1.0 - (days_to_next_ex_div / window_days)

    if early_exercise_optimal_for_dividend(extrinsic_value, expected_dividend_amount):
        return time_factor

    cushion_ratio = (extrinsic_value - expected_dividend_amount) / expected_dividend_amount
    cushion_factor = 2.0 * (1.0 - _normal_cdf(cushion_ratio))
    return time_factor * cushion_factor


def assignment_risk_flag(score: float, threshold: float) -> bool:
    """Pure threshold predicate - the sweep-trigger boundary."""
    return score >= threshold
