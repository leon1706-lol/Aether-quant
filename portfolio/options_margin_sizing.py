"""Margin-based sizing for the options strategies whose risk profile a
vega budget cannot safely represent - genuinely unbounded-risk shorts
(naked calls/puts, short straddles/strangles, and the two backspread
variants that invert into a net-short position) and bounded-but-
asymmetric-ratio structures (ladders' uncovered excess leg, backspreads'
defined max loss). portfolio/options_strategy.py's build_multi_leg_
position_sizing() explicitly refuses every strategy_name whose
StrategySpec.risk_tier isn't "vega_budget" - this module is where those
refused strategies get sized instead, mirroring risk/futures_risk.py's
own margin-utilization-targeted (soft target, hard ceiling) shape rather
than risk/position_sizing.py's volatility-of-notional model.

Every formula here is an explicitly documented FIRST APPROXIMATION, not
broker-accurate margin (development/Problems.md) - IB's real margin
engine (SPAN/Reg-T with portfolio margining nuances) is not modeled.
This entire family is hard-gated in main.py to runtime_mode == "backtest"
as a code-level invariant, not just a config flag a user could flip - see
main.py's own gate for why.

Two real corrections to this feature's own initial plan were found while
transcribing the ACTUAL Lean leg quantities in options_strategy.py (see
that module's own note): only bull_call_ladder/bear_put_ladder are
genuinely uncovered (bear_call_ladder/bull_put_ladder are net-long and
belong in the vega_budget tier instead), and only short_call_backspread/
short_put_backspread are genuinely unbounded (call_backspread/
put_backspread are net-long and bounded, staying in this module's
bounded-max-loss sub-model, not the naked one).
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio.options_strategy import (
    MULTI_LEG_STRATEGY_REGISTRY,
    OptionsSpreadLeg,
    _expiries_tuple_from_roles,
    _legs_tuple_from_roles,
    select_strategy_legs,
)


@dataclass(frozen=True)
class MarginSizingDecision:
    """Margin-tier sibling of OptionsMultiLegPositionDecision - same
    legs/expiries/contracts/strategy_name/sizing_reason shape (so
    main.py's record-building code can treat either decision type
    identically via duck typing), plus margin_required/margin_utilization
    in place of net_debit_or_credit/net_delta/net_vega (a margin-tier
    position's defining risk unit is margin consumed, not vega)."""

    strategy_name: str
    legs: tuple[OptionsSpreadLeg, ...]
    expiries: tuple[str, ...]
    contracts: int
    margin_required: float          # total $ margin consumed by `contracts` spread units
    margin_utilization: float        # margin_required / portfolio_value
    sizing_reason: str

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "legs": [
                {
                    "strike": leg.strike,
                    "right": leg.right,
                    "side": leg.side,
                    "contract_symbol": str(leg.contract_symbol) if leg.contract_symbol is not None else None,
                }
                for leg in self.legs
            ],
            "expiries": list(self.expiries),
            "contracts": self.contracts,
            "margin_required": self.margin_required,
            "margin_utilization": self.margin_utilization,
            "sizing_reason": self.sizing_reason,
        }


def _naked_margin_per_contract(
    underlying_price: float,
    strike: float,
    right: str,
    contract_multiplier: float,
    pct_of_underlying_value: float,
    min_pct_of_underlying_value: float,
) -> float:
    """Simplified Reg-T-style naked margin for ONE short contract:
    max(pct_of_underlying_value * underlying_price - otm_amount,
    min_pct_of_underlying_value * underlying_price) * contract_multiplier.
    otm_amount is strike-price for a short call (OTM when strike > price)
    or price-strike for a short put (OTM when price > strike), floored at
    0 (an ITM short option gets no OTM discount). Explicitly NOT
    broker-accurate - see module docstring."""
    if underlying_price <= 0.0 or contract_multiplier <= 0.0:
        return 0.0
    otm_amount = max(strike - underlying_price, 0.0) if right == "call" else max(underlying_price - strike, 0.0)
    per_contract = max(
        pct_of_underlying_value * underlying_price - otm_amount,
        min_pct_of_underlying_value * underlying_price,
    )
    return per_contract * contract_multiplier


def _contracts_from_margin_budget(
    margin_per_spread_unit: float, confidence: float, portfolio_value: float,
    target_margin_utilization: float, max_margin_utilization: float,
) -> int:
    """Same soft-target/hard-ceiling shape as
    risk/futures_risk.py::build_futures_position_sizing() - scales toward
    target_margin_utilization by confidence, never exceeding the hard
    max_margin_utilization ceiling regardless of confidence."""
    if margin_per_spread_unit <= 0.0:
        return 0
    confidence_multiplier = 0.5 + 0.5 * confidence
    max_affordable = int(portfolio_value * max_margin_utilization // margin_per_spread_unit)
    at_target = int(portfolio_value * target_margin_utilization // margin_per_spread_unit)
    return max(min(int(at_target * confidence_multiplier), max_affordable), 0)


def build_margin_position_sizing(
    strategy_name: str,
    signal_direction: str,
    confidence: float,
    available_chain: list[dict],
    underlying_price: float,
    portfolio_value: float,
    contract_multiplier: float = 100.0,
    target_delta_at_full_confidence: float = 0.60,
    target_margin_utilization: float = 0.20,
    max_margin_utilization: float = 0.40,
    pct_of_underlying_value: float = 0.20,
    min_pct_of_underlying_value: float = 0.10,
    **selector_tuning_kwargs,
) -> MarginSizingDecision | None:
    """The single public entry point for every margin-tier strategy
    (risk_tier in {"margin_naked", "margin_uncovered_leg",
    "margin_bounded_backspread"}) - dispatches leg selection via
    options_strategy.select_strategy_legs() (the SAME registry-driven
    selector every vega-budget strategy uses, so a ladder's or
    backspread's strikes are chosen identically regardless of which
    sizing model ultimately budgets it), then sizes via the sub-model its
    risk_tier maps to. Returns None for confidence/portfolio_value <= 0,
    an invalid signal_direction, a non-margin-tier strategy_name (sized by
    options_strategy.py instead), or when selection/margin-budget rounds
    to zero contracts - never raises."""
    spec = MULTI_LEG_STRATEGY_REGISTRY.get(strategy_name)
    if spec is None or spec.risk_tier not in (
        "margin_naked", "margin_uncovered_leg", "margin_bounded_backspread",
    ):
        return None

    confidence = max(0.0, min(float(confidence), 1.0))
    portfolio_value = max(float(portfolio_value), 0.0)
    underlying_price = max(float(underlying_price), 0.0)
    if confidence == 0.0 or portfolio_value <= 0.0 or underlying_price <= 0.0:
        return None
    if signal_direction not in ("buy", "sell", "short"):
        return None

    target_delta = target_delta_at_full_confidence * confidence
    legs_by_role = select_strategy_legs(strategy_name, available_chain, target_delta, **selector_tuning_kwargs)
    if legs_by_role is None:
        return None

    if spec.risk_tier == "margin_naked":
        margin_per_unit = _naked_margin_requirement_for_naked_tier(
            spec, legs_by_role, underlying_price, contract_multiplier, pct_of_underlying_value, min_pct_of_underlying_value,
        )
        reason = "reg_t_style_naked_margin_sizing"
    elif spec.risk_tier == "margin_uncovered_leg":
        margin_per_unit = _uncovered_leg_margin_requirement(
            spec, legs_by_role, underlying_price, contract_multiplier, pct_of_underlying_value, min_pct_of_underlying_value,
        )
        reason = "uncovered_ladder_leg_margin_sizing"
    else:
        margin_per_unit = _bounded_backspread_max_loss(spec, legs_by_role, contract_multiplier)
        reason = "bounded_max_loss_backspread_margin_sizing"

    contracts = _contracts_from_margin_budget(
        margin_per_unit, confidence, portfolio_value, target_margin_utilization, max_margin_utilization,
    )
    if contracts <= 0:
        return None

    margin_required = contracts * margin_per_unit
    return MarginSizingDecision(
        strategy_name=strategy_name,
        legs=_legs_tuple_from_roles(spec, legs_by_role),
        expiries=_expiries_tuple_from_roles(spec, legs_by_role),
        contracts=contracts,
        margin_required=margin_required,
        margin_utilization=margin_required / portfolio_value,
        sizing_reason=reason,
    )


def build_margin_position_sizing_for_legs(
    strategy_name: str,
    held_rows_by_role: dict[str, dict],
    underlying_price: float,
    portfolio_value: float,
    contract_multiplier: float = 100.0,
    max_margin_utilization: float = 0.40,
    pct_of_underlying_value: float = 0.20,
    min_pct_of_underlying_value: float = 0.10,
) -> MarginSizingDecision | None:
    """Resize-in-place sibling of build_margin_position_sizing() - sizes
    an ALREADY-HELD margin-tier position on its legs' own current chain
    rows, skipping selection entirely (held_rows_by_role must carry an
    entry for every role in MULTI_LEG_STRATEGY_REGISTRY[strategy_name].legs,
    same shape select_strategy_legs() returns). No confidence-scaled soft
    target here - the position already exists, so sizing is to the full
    max_margin_utilization ceiling directly, the same "size to budget on
    already-resolved greeks, no fresh confidence input" convention
    options_strategy.py's build_multi_leg_position_sizing_for_legs() and
    build_options_position_sizing_for_contract() already use."""
    spec = MULTI_LEG_STRATEGY_REGISTRY.get(strategy_name)
    if spec is None or spec.risk_tier not in (
        "margin_naked", "margin_uncovered_leg", "margin_bounded_backspread",
    ):
        return None
    portfolio_value = max(float(portfolio_value), 0.0)
    underlying_price = max(float(underlying_price), 0.0)
    if portfolio_value <= 0.0 or underlying_price <= 0.0:
        return None

    if spec.risk_tier == "margin_naked":
        margin_per_unit = _naked_margin_requirement_for_naked_tier(
            spec, held_rows_by_role, underlying_price, contract_multiplier, pct_of_underlying_value, min_pct_of_underlying_value,
        )
        reason = "held_legs_own_greeks_naked_margin_sizing"
    elif spec.risk_tier == "margin_uncovered_leg":
        margin_per_unit = _uncovered_leg_margin_requirement(
            spec, held_rows_by_role, underlying_price, contract_multiplier, pct_of_underlying_value, min_pct_of_underlying_value,
        )
        reason = "held_legs_own_greeks_uncovered_leg_margin_sizing"
    else:
        margin_per_unit = _bounded_backspread_max_loss(spec, held_rows_by_role, contract_multiplier)
        reason = "held_legs_own_greeks_bounded_backspread_margin_sizing"

    if margin_per_unit <= 0.0:
        return None
    contracts = int(portfolio_value * max_margin_utilization // margin_per_unit)
    if contracts <= 0:
        return None

    margin_required = contracts * margin_per_unit
    return MarginSizingDecision(
        strategy_name=strategy_name,
        legs=_legs_tuple_from_roles(spec, held_rows_by_role),
        expiries=_expiries_tuple_from_roles(spec, held_rows_by_role),
        contracts=contracts,
        margin_required=margin_required,
        margin_utilization=margin_required / portfolio_value,
        sizing_reason=reason,
    )


def _naked_margin_requirement_for_naked_tier(
    spec, legs_by_role: dict, underlying_price: float, contract_multiplier: float,
    pct_of_underlying_value: float, min_pct_of_underlying_value: float,
) -> float:
    """naked_call/naked_put: the single short leg's own naked margin.
    short_straddle/short_strangle: the broker convention of "margin on the
    greater side only" (both legs can't be assigned against the same
    move) - max() of the two legs' naked margin, NOT the sum; the premium
    credit from the other leg is ignored (conservative - overestimates
    margin required in the direction of safety). short_call_backspread/
    short_put_backspread: naked margin at the heavier-ratio (2x) SHORT
    leg's strike, per SPREAD UNIT (i.e. for the 2 short contracts one
    spread unit implies) - the 1 long contract's partial hedge is
    deliberately ignored, the same conservative-direction simplification."""
    short_legs = [leg for leg in spec.legs if leg.side == "short"]
    per_leg_margins = [
        _naked_margin_per_contract(
            underlying_price, float(legs_by_role[leg.role]["strike"]), leg.right, contract_multiplier,
            pct_of_underlying_value, min_pct_of_underlying_value,
        ) * leg.ratio
        for leg in short_legs
    ]
    if not per_leg_margins:
        return 0.0
    if len(short_legs) == 1:
        return per_leg_margins[0]
    return max(per_leg_margins)


def _uncovered_leg_margin_requirement(
    spec, legs_by_role: dict, underlying_price: float, contract_multiplier: float,
    pct_of_underlying_value: float, min_pct_of_underlying_value: float,
) -> float:
    """bull_call_ladder/bear_put_ladder only (risk_tier ==
    "margin_uncovered_leg") - of the ladder's 3 legs (1 long + 2 short,
    same ratio), exactly 1 short contract is genuinely uncovered (the
    other is offset 1:1 by the long leg); naked margin applies to ONE
    contract at the strike furthest from the long leg (the excess leg),
    never to both short legs (that would double-count the 1:1-hedged
    short)."""
    long_leg = next(leg for leg in spec.legs if leg.side == "long")
    short_legs = [leg for leg in spec.legs if leg.side == "short"]
    long_strike = float(legs_by_role[long_leg.role]["strike"])
    excess_leg = max(short_legs, key=lambda leg: abs(float(legs_by_role[leg.role]["strike"]) - long_strike))
    return _naked_margin_per_contract(
        underlying_price, float(legs_by_role[excess_leg.role]["strike"]), excess_leg.right, contract_multiplier,
        pct_of_underlying_value, min_pct_of_underlying_value,
    )


def _bounded_backspread_max_loss(spec, legs_by_role: dict, contract_multiplier: float) -> float:
    """call_backspread/put_backspread only (risk_tier ==
    "margin_bounded_backspread") - defined max loss per spread unit:
    (strike_width - net_credit) * contract_multiplier, occurring at the
    far (heavier-ratio) strike. net_credit uses bid/ask when present
    (short leg's bid minus long leg's ask * ratio), 0.0 when absent (the
    same "never let a missing diagnostic field gate sizing" convention as
    the vega-budget path's net_debit_or_credit) - a 0.0 credit assumption
    is the conservative (larger max-loss) direction."""
    short_leg = next(leg for leg in spec.legs if leg.side == "short")
    long_leg = next(leg for leg in spec.legs if leg.side == "long")
    short_row = legs_by_role[short_leg.role]
    long_row = legs_by_role[long_leg.role]
    strike_width = abs(float(long_row["strike"]) - float(short_row["strike"]))

    short_bid = short_row.get("bid")
    long_ask = long_row.get("ask")
    if short_bid is not None and long_ask is not None:
        net_credit = short_leg.ratio * float(short_bid) - long_leg.ratio * float(long_ask)
    else:
        net_credit = 0.0

    max_loss_per_unit = strike_width - net_credit
    return max(max_loss_per_unit, 0.0) * contract_multiplier
