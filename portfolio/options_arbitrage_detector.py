"""Mispricing detector for the 6 stubbed arbitrage strategies (box_spread,
short_box_spread, conversion, reverse_conversion, jelly_roll,
short_jelly_roll) - V4.6 (development/Problems.md #59/Roadmap).

These 6 strategies have had full registry entries, leg selectors, and
unit tests since V4.5, but were never invoked from the live signal path
by design: driving them correctly requires comparing an observed
structure's market price against its risk-free-rate-implied FAIR value
(a genuine arbitrage/mispricing signal), not a directional or volatility
view like every other strategy family in this codebase. This module is
that signal source.

Off by default (phase_v2.options_risk.arbitrage_detector.enabled) - an
explicit, SEPARATE opt-in from enabling these 6 names in
enabled_strategy_names, matching every other new-capability gate in this
project's history (ship available, default off, opt in per-item).

Every fair-value formula here is the standard, textbook closed-form
result for its structure - not a fitted/calibrated model - since the
whole premise of arbitrage detection is comparing an OBSERVED price
against a THEORETICALLY-derived one, not a statistical estimate. Ignores
dividends (dividend_yield=0.0), matching features/options_greeks.py's
own existing convention for this codebase.
"""

from __future__ import annotations

import math
from datetime import date

from portfolio.options_strategy import (
    MULTI_LEG_STRATEGY_REGISTRY,
    OptionsMultiLegPositionDecision,
    _expiries_tuple_from_roles,
    _legs_tuple_from_roles,
    _net_vega_and_delta_per_unit,
    select_strategy_legs,
)
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Iterable


def box_spread_fair_value(
    higher_strike: float, lower_strike: float, risk_free_rate: float, time_to_expiry_years: float,
) -> float:
    """A box spread (long put + short call at the higher strike, short
    put + long call at the lower strike, same expiry) synthesizes a
    risk-free zero-coupon bond paying (higher_strike - lower_strike) at
    expiry - its fair value today is that payoff discounted at the
    risk-free rate. Standard textbook result."""
    return (higher_strike - lower_strike) * math.exp(-risk_free_rate * max(time_to_expiry_years, 0.0))


def pv_dividends_to_expiry(payments: Iterable[tuple[date, float]] | None, current_date: date, expiry_date_str: str, risk_free_rate: float) -> float:
    """Present value of the dividends going ex after `current_date` and on or before the expiry. `payments` holds
    (ex_date, cash_per_share) pairs. A row it can't read counts as no dividend, as the detector did before it knew of any."""
    total = 0.0
    for ex_date, amount in payments or ():
        try:
            years = _years_between(current_date, str(ex_date))
            to_expiry = _years_between(current_date, str(expiry_date_str))
            cash = float(amount)
        except (TypeError, ValueError):
            continue
        if 0.0 < years <= to_expiry and math.isfinite(cash) and cash > 0.0:
            total += cash * math.exp(-risk_free_rate * years)
    return total


def conversion_parity_value(
    call_price: float, put_price: float, spot: float, strike: float, risk_free_rate: float, time_to_expiry_years: float,
    pv_dividends: float = 0.0,
) -> float:
    """Put-call parity: call_price - put_price should equal
    spot - pv_dividends - strike * exp(-r*T). Returns the SIGNED
    discrepancy (actual minus theoretical). A conversion (long stock, long
    put, short call) locks in call - put - spot + PV(strike) + PV(dividends), which is this
    discrepancy, so it profits when it is positive (calls rich against
    puts); a reverse conversion profits when it is negative. Without
    `pv_dividends`, a dividend payer's calls read cheap: a reverse conversion is short the
    stock and owes each dividend, which is why it fired on AAPL at fair prices."""
    theoretical = spot - pv_dividends - strike * math.exp(-risk_free_rate * max(time_to_expiry_years, 0.0))
    actual = call_price - put_price
    return actual - theoretical


def jelly_roll_fair_value(
    strike: float, risk_free_rate: float, near_time_to_expiry_years: float, far_time_to_expiry_years: float,
) -> float:
    """The interest-rate-implied fair cost of a jelly roll (rolling a
    synthetic position from the near expiry to the far one) - the
    discounted strike difference between the two expiries, the standard
    cost-of-carry result for extending a synthetic forward's expiry."""
    near_discount = math.exp(-risk_free_rate * max(near_time_to_expiry_years, 0.0))
    far_discount = math.exp(-risk_free_rate * max(far_time_to_expiry_years, 0.0))
    return strike * (near_discount - far_discount)


def detect_mispricing(actual_net_cost: float, fair_value: float, min_mispricing_bps: float, notional: float) -> bool:
    """Shared threshold predicate for all 3 families above: True when the
    discrepancy between actual_net_cost and fair_value exceeds
    min_mispricing_bps of notional - requiring a MINIMUM edge (not a bare
    non-zero difference) accounts for real bid/ask spread and transaction
    costs a genuine arbitrage must clear to be worth trading. Returns
    False (never trades, never raises) when notional is non-positive."""
    if notional <= 0.0:
        return False
    mispricing_bps = abs(actual_net_cost - fair_value) / notional * 10_000.0
    return mispricing_bps >= min_mispricing_bps


def detect_executable_edge(edge: float, min_mispricing_bps: float, notional: float) -> bool:
    """True when entering the structure at executable prices beats its fair value by at least the threshold. One-sided: a
    structure priced dear is no arbitrage for the side that would pay up, and only its opposite may fire."""
    if notional <= 0.0:
        return False
    return edge / notional * 10_000.0 >= min_mispricing_bps


def _years_between(current_date, expiry_date_str: str) -> float:
    """ISO-date-string expiry minus current_date, in years (365-day
    convention, matching main.py::_build_options_chains_payload()'s own
    time_to_expiry_years computation for greeks). Returns 0.0 (never
    negative, never raises) for an unparseable/past expiry."""
    try:
        expiry_date = date.fromisoformat(expiry_date_str)
    except (TypeError, ValueError):
        return 0.0
    return max((expiry_date - current_date).days, 0) / 365.0


def _actual_net_cost(spec, legs_by_role: dict[str, Any]) -> float:
    """Signed cost to enter the FULL spread unit at current market
    bid/ask: pay ask for every LONG leg, receive bid for every SHORT leg
    - read from each leg's own `.side` (registry-driven), never hardcoded
    per strategy_name, since box_spread/short_box_spread and jelly_roll/
    short_jelly_roll invert which role is long vs. short while keeping
    the SAME role names (see MULTI_LEG_STRATEGY_REGISTRY's own docstring)
    - the exact bug this generic formula avoids versus hand-writing one
    signed formula per strategy_name."""
    net_cost = 0.0
    for leg_spec in spec.legs:
        row = legs_by_role[leg_spec.role]
        price = float(row["ask"]) if leg_spec.side == "long" else float(row["bid"])
        sign = 1.0 if leg_spec.side == "long" else -1.0
        net_cost += sign * price
    return net_cost


def select_arbitrage_signal(
    strategy_name: str,
    available_chain: list[dict],
    current_date: date,
    risk_free_rate: float,
    min_mispricing_bps: float,
    target_delta: float = 0.5,
    dividend_payments: Iterable[tuple[date, float]] | None=None,
) -> bool:
    """Composes the existing V4.5 arbitrage leg selectors
    (select_strategy_legs(), already registry-driven) with the fair-value/
    threshold functions above: True iff THIS bar's chain shows an
    exploitable mispricing for strategy_name, using each leg's own
    bid/ask and days-to-expiry. Strike/expiry ROLES (which role is
    "higher"/"lower"/"near"/"far") are resolved from
    MULTI_LEG_STRATEGY_REGISTRY, never hardcoded per strategy_name - the
    short_* variants invert which role holds which strike/side while
    keeping the same role NAMES. Returns False (never a crash) on any
    missing selection/pricing/date data, or for any strategy_name outside
    the 6 arbitrage families - degrade-to-absent, matching every other
    selector's convention in this module's sibling file."""
    spec = MULTI_LEG_STRATEGY_REGISTRY.get(strategy_name)
    if spec is None or current_date is None:
        return False
    legs_by_role = select_strategy_legs(strategy_name, available_chain, target_delta)
    if legs_by_role is None:
        return False

    try:
        if strategy_name in ("box_spread", "short_box_spread"):
            higher_role = next(leg.role for leg in spec.legs if leg.strike_role == "higher")
            lower_role = next(leg.role for leg in spec.legs if leg.strike_role == "lower")
            higher_row = legs_by_role[higher_role]
            lower_row = legs_by_role[lower_role]
            higher_strike = float(higher_row["strike"])
            lower_strike = float(lower_row["strike"])
            time_to_expiry_years = _years_between(current_date, higher_row["expiry"])
            fair_value = box_spread_fair_value(higher_strike, lower_strike, risk_free_rate, time_to_expiry_years)
            actual_net_cost = _actual_net_cost(spec, legs_by_role)
            # long: pay the cost, collect the discounted payoff. short: the cost is a credit, and the payoff is owed.
            edge = fair_value - actual_net_cost if strategy_name == "box_spread" else -actual_net_cost - fair_value
            return detect_executable_edge(edge, min_mispricing_bps, higher_strike - lower_strike)

        if strategy_name in ("conversion", "reverse_conversion"):
            call_role = next(leg.role for leg in spec.legs if leg.right == "call")
            put_role = next(leg.role for leg in spec.legs if leg.right == "put")
            call_row = legs_by_role[call_role]
            put_row = legs_by_role[put_role]
            strike = float(call_row["strike"])
            spot = float(call_row.get("underlying_price") or strike)
            time_to_expiry_years = _years_between(current_date, call_row["expiry"])
            # at the prices one could trade: a conversion sells the call and buys the put, a reverse does the opposite
            if strategy_name == "conversion":
                call_price, put_price, sign = float(call_row["bid"]), float(put_row["ask"]), 1.0
            else:
                call_price, put_price, sign = float(call_row["ask"]), float(put_row["bid"]), -1.0
            pv_dividends = pv_dividends_to_expiry(dividend_payments, current_date, call_row["expiry"], risk_free_rate)
            discrepancy = conversion_parity_value(call_price, put_price, spot, strike, risk_free_rate, time_to_expiry_years, pv_dividends)
            return detect_executable_edge(sign * discrepancy, min_mispricing_bps, strike)

        if strategy_name in ("jelly_roll", "short_jelly_roll"):
            near_call_role = next(leg.role for leg in spec.legs if leg.right == "call" and leg.expiry_role == "near")
            far_call_role = next(leg.role for leg in spec.legs if leg.right == "call" and leg.expiry_role == "far")
            near_row = legs_by_role[near_call_role]
            far_row = legs_by_role[far_call_role]
            strike = float(near_row["strike"])
            near_time_to_expiry_years = _years_between(current_date, near_row["expiry"])
            far_time_to_expiry_years = _years_between(current_date, far_row["expiry"])
            fair_value = jelly_roll_fair_value(strike, risk_free_rate, near_time_to_expiry_years, far_time_to_expiry_years)
            actual_net_cost = _actual_net_cost(spec, legs_by_role)
            edge = fair_value - actual_net_cost if strategy_name == "jelly_roll" else -actual_net_cost - fair_value
            return detect_executable_edge(edge, min_mispricing_bps, strike)
    except (KeyError, TypeError, ValueError):
        return False

    return False


def build_arbitrage_position_sizing(
    strategy_name: str,
    available_chain: list[dict],
    current_date: date,
    risk_free_rate: float,
    min_mispricing_bps: float,
    max_contracts_per_signal: int = 1,
    target_delta: float = 0.5,
) -> OptionsMultiLegPositionDecision | None:
    """The ONLY sizing path for the 6 arbitrage strategies - deliberately
    NOT vega-budget or margin-tier sized (an arbitrage structure is
    delta/vega-neutral by construction, so a vega budget has nothing
    meaningful to scale against). Sized instead to a small, FIXED
    `max_contracts_per_signal` (default 1) whenever
    select_arbitrage_signal() confirms a real mispricing this bar - a
    deliberately conservative first-cut sizing model for a genuinely new
    capability, not a risk-budgeted one; a real margin-aware arbitrage
    sizer is a reasonable future follow-up once this is IB-verified.
    Returns None when no mispricing is detected, selection fails, or
    max_contracts_per_signal isn't positive - never raises."""
    if max_contracts_per_signal <= 0:
        return None
    if not select_arbitrage_signal(strategy_name, available_chain, current_date, risk_free_rate, min_mispricing_bps, target_delta):
        return None
    spec = MULTI_LEG_STRATEGY_REGISTRY.get(strategy_name)
    if spec is None:
        return None
    legs_by_role = select_strategy_legs(strategy_name, available_chain, target_delta)
    if legs_by_role is None:
        return None

    net_vega, net_delta = _net_vega_and_delta_per_unit(spec, legs_by_role)
    return OptionsMultiLegPositionDecision(
        strategy_name=strategy_name,
        legs=_legs_tuple_from_roles(spec, legs_by_role),
        expiries=_expiries_tuple_from_roles(spec, legs_by_role),
        contracts=int(max_contracts_per_signal),
        net_debit_or_credit=_actual_net_cost(spec, legs_by_role),
        net_delta=net_delta,
        net_vega=net_vega,
        sizing_reason="arbitrage_mispricing_fixed_size_sizing",
    )
