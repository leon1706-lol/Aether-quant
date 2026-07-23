"""Greeks-aware single-leg options position sizing.

Satisfies "options need a fundamentally different model output" WITHOUT a
new model architecture or training target: the EXISTING direction +
confidence (+ magnitude, unused here) prediction every model in this
codebase already produces becomes the *input* to a deterministic, non-ML
greeks-sizing function. Target delta scales linearly with confidence
(0 confidence -> 0 delta -> no position; full confidence ->
target_delta_at_full_confidence), and contract count is capped by a vega
risk budget (percent of portfolio equity), not a plain notional/weight cap
- vega, not price exposure, is the right risk unit for an options position.

Deliberately single-leg only (long calls or long puts, never short options
or multi-leg spreads/verticals/straddles/condors) - automatic multi-leg
spread SELECTION via ML is an explicit non-goal of this pass (see
development/Problems.md); this module is the sizing/selection layer for
the single-leg case only.

Its own package (not risk/ - options_strategy.py needs the whole option
chain, not just a scalar signal; not features/ - this is a decision layer,
not a feature) - same "new package, off by default, explicit safety-tier
extension" precedent portfolio/book_construction.py already established
for this codebase's newest decision-layer additions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionsPositionDecision:
    contracts: int
    right: str
    strike: float
    expiry: str
    target_delta: float
    actual_delta: float
    vega_budget_used: float
    sizing_reason: str
    # The actual Lean contract Symbol (from the selected chain row's
    # "symbol" key, see main.py::_build_options_chains_payload()) - needed
    # by main.py::_apply_signal() to place an order on the SPECIFIC
    # contract, not the canonical option chain Symbol. None whenever the
    # chain row didn't carry one (e.g. a synthetic test fixture) - callers
    # must treat that as "no order can be placed", never a crash.
    contract_symbol: object = None

    def to_dict(self) -> dict:
        """Deliberately NOT dataclasses.asdict(self) - asdict() deep-copies
        every field, and a raw Lean Symbol (a C#/.NET interop object) isn't
        guaranteed deepcopy-safe. Manual field access avoids that risk
        entirely and stringifies contract_symbol so the result is always
        JSON-serializable - required for main.py's dashboard state writer
        (see main.py::on_data()'s "dynamic_sizing_for_state" sanitization,
        which calls this before signals[...] ever reaches json.dumps())."""
        return {
            "contracts": self.contracts,
            "right": self.right,
            "strike": self.strike,
            "expiry": self.expiry,
            "target_delta": self.target_delta,
            "actual_delta": self.actual_delta,
            "vega_budget_used": self.vega_budget_used,
            "sizing_reason": self.sizing_reason,
            "contract_symbol": str(self.contract_symbol) if self.contract_symbol is not None else None,
        }


def select_single_leg_contract(available_chain: list[dict], target_delta: float, right: str) -> dict | None:
    """Picks the chain entry of the requested `right` ("call"/"put") whose
    |delta| is closest to |target_delta| - nearest-strike-by-delta
    selection, no ML, no spread construction. Each entry in
    available_chain must already carry a computed "delta" key (see
    features/options_greeks.py::compute_greeks() - this function does no
    pricing itself, purely a selection over already-priced rows).

    Returns None when available_chain is empty or has no entry of the
    requested right (e.g. IB disabled -> empty chain, or a chain with only
    calls when a put was requested) - degrade-to-absent, never a crash."""
    right_normalized = right.lower()
    candidates = [
        row for row in available_chain
        if str(row.get("right", "")).lower() == right_normalized and row.get("delta") is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: abs(abs(row["delta"]) - abs(target_delta)))


def _size_single_leg_contract(
    contract: dict,
    right: str,
    target_delta: float,
    portfolio_value: float,
    max_vega_budget_pct_of_equity: float,
    sizing_reason: str,
) -> OptionsPositionDecision | None:
    """Shared vega-budget arithmetic for a single ALREADY-RESOLVED contract
    row - factored out of build_options_position_sizing() so
    build_options_position_sizing_for_contract() (V4.4, sizes an
    already-HELD contract on its own greeks instead of re-selecting one)
    reuses the identical budget math rather than duplicating it. Returns
    None when the contract's vega is non-positive or the budget rounds
    down to zero contracts - never raises."""
    contract_vega = float(contract.get("vega", 0.0) or 0.0)
    if contract_vega <= 0.0:
        return None

    vega_budget = max_vega_budget_pct_of_equity * portfolio_value
    contracts = int(vega_budget // contract_vega)
    if contracts <= 0:
        return None

    return OptionsPositionDecision(
        contracts=contracts,
        right=right,
        strike=float(contract["strike"]),
        expiry=str(contract["expiry"]),
        target_delta=target_delta,
        actual_delta=float(contract["delta"]),
        vega_budget_used=(contracts * contract_vega) / portfolio_value,
        sizing_reason=sizing_reason,
        contract_symbol=contract.get("symbol"),
    )


def build_options_position_sizing(
    signal_direction: str,
    confidence: float,
    available_chain: list[dict],
    portfolio_value: float,
    target_delta_at_full_confidence: float = 0.60,
    max_vega_budget_pct_of_equity: float = 0.02,
) -> OptionsPositionDecision | None:
    """Translates the existing direction+confidence prediction into ONE
    single-leg options position. signal_direction == "buy" selects calls;
    {"sell", "short"} select puts (matches
    portfolio/book_construction.py's own "buy"/"short" role vocabulary and
    main.py::_apply_signal()'s signal_name values).

    target_delta scales linearly with confidence:
    target_delta_at_full_confidence * confidence. contract count is capped
    so total position vega stays under
    max_vega_budget_pct_of_equity * portfolio_value / contract_vega -
    vega (not notional) is the risk unit an options book should budget
    against, since a small-notional far-OTM option can carry
    disproportionate vega risk relative to its price.

    Returns None when: confidence is 0, signal_direction doesn't map to a
    right, available_chain has no usable contract for that right (e.g. IB
    disabled -> empty chain, or select_single_leg_contract() found no
    match), the selected contract's vega is non-positive, or
    portfolio_value is non-positive - degrade-to-absent, never a crash,
    matching risk/futures_risk.py::build_futures_position_sizing()'s
    "no active signal -> None/zero" convention."""
    confidence = max(0.0, min(float(confidence), 1.0))
    portfolio_value = max(float(portfolio_value), 0.0)

    if signal_direction == "buy":
        right = "call"
    elif signal_direction in ("sell", "short"):
        right = "put"
    else:
        return None

    if confidence == 0.0 or portfolio_value <= 0.0:
        return None

    target_delta = target_delta_at_full_confidence * confidence
    contract = select_single_leg_contract(available_chain, target_delta, right)
    if contract is None:
        return None

    return _size_single_leg_contract(
        contract, right, target_delta, portfolio_value, max_vega_budget_pct_of_equity,
        "delta_targeted_vega_budgeted_sizing",
    )


def build_options_position_sizing_for_contract(
    held_contract: dict,
    portfolio_value: float,
    max_vega_budget_pct_of_equity: float = 0.02,
) -> OptionsPositionDecision | None:
    """V4.4 - sizes the EXACT held contract on its own current greeks,
    skipping select_single_leg_contract() entirely (no re-selection).

    Closes a real architectural gap: without this, a position whose ideal
    strike has drifted away from what main.py is currently holding could
    only ever be handled by RE-SELECTING a contract (which picks a
    DIFFERENT one, forcing a binary rotate-or-freeze choice) - this lets
    the held position keep being managed - scaled up or down - on its own
    delta/vega, on bars where main.py chooses not to rotate.

    held_contract is a live chain row for the currently-held contract -
    same shape select_single_leg_contract() returns (must carry
    right/strike/expiry/delta/vega/symbol, e.g. found by matching the
    held contract_symbol against this bar's available_chain). There is no
    fresh confidence-scaled target here - the position already exists -
    so target_delta/actual_delta are both just the held contract's own
    current delta.

    Same degrade-to-None contract as build_options_position_sizing():
    non-positive portfolio_value, missing/non-positive vega, or a budget
    that rounds to zero contracts all return None, never raise."""
    portfolio_value = max(float(portfolio_value), 0.0)
    if portfolio_value <= 0.0:
        return None

    right = str(held_contract.get("right", "")).lower()
    held_delta = float(held_contract.get("delta", 0.0) or 0.0)
    return _size_single_leg_contract(
        held_contract, right, held_delta, portfolio_value, max_vega_budget_pct_of_equity,
        "held_contract_own_greeks_sizing",
    )


# ---------------------------------------------------------------------------
# 2-leg vertical spreads (call vertical / bull_call_spread, put vertical /
# bear_put_spread) - a deliberately minimal, explicit scope-in of the
# "multi-leg spread selection is a non-goal" note above. Straddles/
# strangles/iron condors/butterflies remain out of scope (see
# development/Problems.md #29/#38). OptionsPositionDecision/
# select_single_leg_contract()/build_options_position_sizing() above are
# completely untouched - these are new, parallel additions, not a
# generalization of the single-leg path.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionsSpreadLeg:
    """One leg of a 2-leg vertical spread. side is "long"/"short" (never a
    signed quantity) - keeps this symmetric with how Lean's own
    OptionStrategies/Leg model a spread: a strike, a side, a contract."""

    strike: float
    right: str  # "call" | "put" - both legs of a vertical share this
    side: str  # "long" | "short"
    # Same None-safe contract as OptionsPositionDecision.contract_symbol
    # above - a synthetic test fixture with no "symbol" key degrades to
    # None, never a crash.
    contract_symbol: object = None


@dataclass(frozen=True)
class OptionsSpreadPositionDecision:
    """2-leg vertical spread sibling of OptionsPositionDecision - a
    SEPARATE dataclass, not a generalization of it (OptionsPositionDecision
    stays single-leg-shaped, every existing caller untouched)."""

    strategy_name: str  # "bull_call_spread" | "bear_put_spread" - matches Lean's OptionStrategies factory name exactly, main.py uses this to pick which one to call
    legs: tuple[OptionsSpreadLeg, OptionsSpreadLeg]  # (long, short), exactly 2 for this pass's scope
    expiry: str
    contracts: int  # spread QUANTITY (number of spread units), not a per-leg contract count
    # Best-effort diagnostic only (mid/bid-ask based, per spread unit) -
    # 0.0 when bid/ask are absent from the chain rows. NEVER gates sizing,
    # matching this module's existing "never crash on missing chain
    # fields" contract.
    net_debit_or_credit: float
    net_delta: float  # long leg's delta minus short leg's delta, per spread unit
    net_vega: float  # fraction of portfolio_value the sized position's net vega consumes - same "budget used" semantic as OptionsPositionDecision.vega_budget_used, not a raw per-unit vega number
    sizing_reason: str

    def to_dict(self) -> dict:
        """Same manual-field-access convention as OptionsPositionDecision.to_dict()
        above - never dataclasses.asdict(), the legs' contract_symbol
        fields are real Lean Symbol objects, not deepcopy-safe."""
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
            "expiry": self.expiry,
            "contracts": self.contracts,
            "net_debit_or_credit": self.net_debit_or_credit,
            "net_delta": self.net_delta,
            "net_vega": self.net_vega,
            "sizing_reason": self.sizing_reason,
        }


def select_vertical_spread_legs(
    available_chain: list[dict],
    target_delta: float,
    right: str,
    short_leg_delta_offset: float,
) -> tuple[dict, dict] | None:
    """Picks two same-expiry, same-right chain rows for a vertical spread:
    the long leg via the EXACT same nearest-|delta| selection
    select_single_leg_contract() already uses (no new selection logic
    duplicated for it), and the short leg as the nearest-|delta| match to
    (target_delta - short_leg_delta_offset) among rows of the SAME expiry
    as the long leg, filtered to the side that caps risk (strike > long
    strike for a call vertical, strike < long strike for a put vertical -
    enforced explicitly by filtering on strike, not inferred from delta
    ordering, since assuming monotonic real-market delta-vs-strike
    ordering shouldn't be load-bearing here).

    Returns None when: no usable long leg (same degrade-to-absent
    condition as select_single_leg_contract()), or no candidate short leg
    exists at the long leg's expiry on the risk-capping side - a chain
    with only one usable strike degrades to "no spread", never a crash."""
    long_leg = select_single_leg_contract(available_chain, target_delta, right)
    if long_leg is None:
        return None

    long_strike = float(long_leg["strike"])
    long_expiry = long_leg["expiry"]
    right_normalized = right.lower()
    short_target_delta = target_delta - short_leg_delta_offset

    def _is_risk_capping_side(strike: float) -> bool:
        return strike > long_strike if right_normalized == "call" else strike < long_strike

    short_candidates = [
        row
        for row in available_chain
        if str(row.get("right", "")).lower() == right_normalized
        and row.get("delta") is not None
        and row.get("expiry") == long_expiry
        and _is_risk_capping_side(float(row["strike"]))
    ]
    if not short_candidates:
        return None

    short_leg = min(short_candidates, key=lambda row: abs(abs(row["delta"]) - abs(short_target_delta)))
    return long_leg, short_leg


def _size_vertical_spread(
    long_row: dict,
    short_row: dict,
    right: str,
    strategy_name: str,
    portfolio_value: float,
    max_vega_budget_pct_of_equity: float,
    sizing_reason: str,
) -> OptionsSpreadPositionDecision | None:
    """Shared net-vega-budget arithmetic for an already-resolved leg pair -
    factored out of build_vertical_spread_position_sizing() so
    build_vertical_spread_position_sizing_for_legs() (V4.4, sizes an
    already-HELD spread on its own greeks instead of re-selecting legs)
    reuses the identical budget math. Returns None when net_vega is
    non-positive or the budget rounds down to zero spread units."""
    long_vega = float(long_row.get("vega", 0.0) or 0.0)
    short_vega = float(short_row.get("vega", 0.0) or 0.0)
    net_vega_per_spread = long_vega - short_vega
    if net_vega_per_spread <= 0.0:
        return None

    vega_budget = max_vega_budget_pct_of_equity * portfolio_value
    contracts = int(vega_budget // net_vega_per_spread)
    if contracts <= 0:
        return None

    long_ask = long_row.get("ask")
    short_bid = short_row.get("bid")
    net_debit_or_credit = (
        float(long_ask) - float(short_bid) if long_ask is not None and short_bid is not None else 0.0
    )
    net_delta = float(long_row.get("delta", 0.0) or 0.0) - float(short_row.get("delta", 0.0) or 0.0)

    return OptionsSpreadPositionDecision(
        strategy_name=strategy_name,
        legs=(
            OptionsSpreadLeg(strike=float(long_row["strike"]), right=right, side="long", contract_symbol=long_row.get("symbol")),
            OptionsSpreadLeg(strike=float(short_row["strike"]), right=right, side="short", contract_symbol=short_row.get("symbol")),
        ),
        expiry=str(long_row["expiry"]),
        contracts=contracts,
        net_debit_or_credit=net_debit_or_credit,
        net_delta=net_delta,
        net_vega=(contracts * net_vega_per_spread) / portfolio_value,
        sizing_reason=sizing_reason,
    )


def build_vertical_spread_position_sizing(
    signal_direction: str,
    confidence: float,
    available_chain: list[dict],
    portfolio_value: float,
    target_delta_at_full_confidence: float = 0.60,
    short_leg_delta_offset: float = 0.20,
    max_vega_budget_pct_of_equity: float = 0.02,
) -> OptionsSpreadPositionDecision | None:
    """Vertical-spread sibling of build_options_position_sizing() above -
    same signal_direction -> right mapping ("buy" -> call vertical/
    bull_call_spread, "sell"/"short" -> put vertical/bear_put_spread),
    same confidence-scaled target_delta for the long leg.

    Sizes by NET vega (long leg vega minus short leg vega) rather than
    the long leg's vega alone - a vertical's defining risk reduction
    versus a single leg, and the correct risk unit to budget a spread
    position against. Returns None on the same degrade-to-absent
    conditions build_options_position_sizing() already documents, plus:
    no usable short leg found (select_vertical_spread_legs() returned
    None), or net_vega is non-positive (a spread with ~zero or negative
    net vega is unsizeable by this budget, not an error)."""
    confidence = max(0.0, min(float(confidence), 1.0))
    portfolio_value = max(float(portfolio_value), 0.0)

    if signal_direction == "buy":
        right, strategy_name = "call", "bull_call_spread"
    elif signal_direction in ("sell", "short"):
        right, strategy_name = "put", "bear_put_spread"
    else:
        return None

    if confidence == 0.0 or portfolio_value <= 0.0:
        return None

    target_delta = target_delta_at_full_confidence * confidence
    legs = select_vertical_spread_legs(available_chain, target_delta, right, short_leg_delta_offset)
    if legs is None:
        return None
    long_row, short_row = legs

    return _size_vertical_spread(
        long_row, short_row, right, strategy_name, portfolio_value, max_vega_budget_pct_of_equity,
        "delta_targeted_net_vega_budgeted_vertical_spread_sizing",
    )


def build_vertical_spread_position_sizing_for_legs(
    held_long: dict,
    held_short: dict,
    portfolio_value: float,
    max_vega_budget_pct_of_equity: float = 0.02,
) -> OptionsSpreadPositionDecision | None:
    """V4.4 - net-vega sibling of build_options_position_sizing_for_contract()
    for a held 2-leg vertical spread: sizes the EXACT held long/short legs
    on their own current greeks, skipping select_vertical_spread_legs()
    entirely. held_long/held_short are live chain rows for the currently-
    held legs (same shape select_vertical_spread_legs() returns each of
    its pair). strategy_name/right are derived from held_long's own
    "right" field rather than passed in - there is no fresh signal here,
    the spread already exists. Same degrade-to-None contract as
    build_vertical_spread_position_sizing()."""
    portfolio_value = max(float(portfolio_value), 0.0)
    if portfolio_value <= 0.0:
        return None

    right = str(held_long.get("right", "")).lower()
    strategy_name = "bull_call_spread" if right == "call" else "bear_put_spread"
    return _size_vertical_spread(
        held_long, held_short, right, strategy_name, portfolio_value, max_vega_budget_pct_of_equity,
        "held_legs_own_greeks_sizing",
    )


# ---------------------------------------------------------------------------
# V4.5 - full OptionStrategies coverage (41 additional factories beyond the
# 2-leg verticals above). Everything above this line is UNTOUCHED - existing
# callers (single-leg, bull_call_spread/bear_put_spread) keep working
# byte-identically; this section is purely additive.
#
# Design: one small MULTI_LEG_STRATEGY_REGISTRY data table (one StrategySpec
# per factory, sourced directly from QuantConnect.Securities.Option.
# OptionStrategies.cs - the real Lean C# leg quantities, not guessed from
# the factory's positional strike names) replaces what would otherwise be
# 41 near-duplicate selection/sizing functions. A handful of shared
# shape-family selectors (vertical/straddle/strangle/butterfly/iron/
# calendar/backspread/ladder/naked/covered-protective) dispatch off each
# StrategySpec's `shape_family` tag, parameterized by its `legs` (each
# already carrying the correct long/short side and call/put right straight
# from the registry) - so e.g. all 4 ladder variants or all 4 calendar
# variants share ONE selector implementation apiece, not four.
#
# Two real risk-tier corrections were found while transcribing the ACTUAL
# Lean leg quantities (not assumed from strike-name positions alone) -
# recorded here since they contradict this feature's own initial plan text:
#   - Of the 4 ladder strategies, only bull_call_ladder/bear_put_ladder are
#     genuinely net-short (one extra uncovered leg beyond a 1:1 hedge) and
#     unbounded-risk; bear_call_ladder/bull_put_ladder are net-long (an
#     extra long leg only adds cost, never risk) and belong in the SAME
#     vega-budget tier as verticals/butterflies, not the margin family.
#   - Of the 4 backspread strategies, short_call_backspread/
#     short_put_backspread are the genuinely unbounded ones (inverting a
#     backspread turns its 1:2 long-heavy ratio into a 1:2 SHORT-heavy
#     ratio) - naked-style margin, not the bounded-max-loss formula;
#     call_backspread/put_backspread (the un-inverted, long-heavy originals)
#     really are bounded and keep the bounded-max-loss treatment.
# See development/Problems.md for the full writeup.
# ---------------------------------------------------------------------------

import math


@dataclass(frozen=True)
class MultiLegSpec:
    """One leg of a multi-leg OptionStrategy factory result. `side`/`ratio`
    are transcribed directly from OptionStrategies.cs's actual Quantity
    field for that leg (e.g. a butterfly's body leg is ratio=2, side=
    "short" for a long butterfly) - never inferred from the factory's
    positional strike-name alone (a real bug this pass found and fixed,
    see the module-level note above). `is_anchor` marks a leg selected
    FIRST, by confidence-scaled target delta; every other leg in the same
    strategy is selected as a strike/expiry offset from an anchor leg.
    Iron condor/butterfly have TWO anchor legs (short_put, short_call) -
    one per composed vertical selection."""

    role: str            # unique per leg within one strategy, e.g. "short_call"
    right: str            # "call" | "put"
    side: str             # "long" | "short" - the real Lean leg direction
    ratio: int             # contracts per spread unit (1, or 2 for a butterfly body / backspread's heavy leg)
    strike_role: str       # key into the strikes-by-role dict this leg's strike is selected/passed under
    expiry_role: str = "single"  # "single" | "near" | "far"
    is_anchor: bool = False


@dataclass(frozen=True)
class StrategySpec:
    """One registry entry - everything main.py's generic order-placement
    layer needs to resolve and call the real OptionStrategies factory, plus
    everything the shape-family selectors below need to pick strikes/
    expiries for it. factory_name is resolved via
    getattr(OptionStrategies, factory_name) at the main.py call site (never
    imported per-strategy here - this module must not import Lean's
    AlgorithmImports, matching every other pure function in this file)."""

    factory_name: str
    arg_order: tuple[str, ...]      # exact positional strike-role order the real factory expects
    has_expiry_pair: bool
    legs: tuple[MultiLegSpec, ...]
    shape_family: str                # dispatch key for the shared selectors below
    risk_tier: str                   # "vega_budget" | "margin_naked" | "margin_uncovered_leg" | "margin_bounded_backspread" | "covered_protective" | "unreachable_arbitrage"
    covering_equity_side: str | None = None  # "long" | "short" - only set for risk_tier == "covered_protective"


def _leg(role, right, side, ratio, strike_role, expiry_role="single", is_anchor=False):
    return MultiLegSpec(role, right, side, ratio, strike_role, expiry_role, is_anchor)


MULTI_LEG_STRATEGY_REGISTRY: dict[str, StrategySpec] = {
    # -- existing 2-leg verticals (registry entries needed so main.py's
    #    generic order-placement/liquidation/bookkeeping can treat these
    #    uniformly with the other 41; their SIZING decision stays the
    #    dedicated build_vertical_spread_position_sizing() above, untouched) --
    "bull_call_spread": StrategySpec(
        "bull_call_spread", ("long", "short"), False,
        (_leg("long", "call", "long", 1, "long", is_anchor=True), _leg("short", "call", "short", 1, "short")),
        "vertical", "vega_budget",
    ),
    "bear_put_spread": StrategySpec(
        "bear_put_spread", ("long", "short"), False,
        (_leg("long", "put", "long", 1, "long", is_anchor=True), _leg("short", "put", "short", 1, "short")),
        "vertical", "vega_budget",
    ),
    # -- credit verticals --
    "bear_call_spread": StrategySpec(
        "bear_call_spread", ("short", "long"), False,
        (_leg("short", "call", "short", 1, "short", is_anchor=True), _leg("long", "call", "long", 1, "long")),
        "vertical", "vega_budget",
    ),
    "bull_put_spread": StrategySpec(
        "bull_put_spread", ("short", "long"), False,
        (_leg("short", "put", "short", 1, "short", is_anchor=True), _leg("long", "put", "long", 1, "long")),
        "vertical", "vega_budget",
    ),
    # -- straddles --
    "straddle": StrategySpec(
        "straddle", ("strike",), False,
        (_leg("call", "call", "long", 1, "strike", is_anchor=True), _leg("put", "put", "long", 1, "strike")),
        "straddle", "vega_budget",
    ),
    "short_straddle": StrategySpec(
        "short_straddle", ("strike",), False,
        (_leg("call", "call", "short", 1, "strike", is_anchor=True), _leg("put", "put", "short", 1, "strike")),
        "straddle", "margin_naked",
    ),
    # -- strangles --
    "strangle": StrategySpec(
        "strangle", ("call", "put"), False,
        (_leg("call", "call", "long", 1, "call", is_anchor=True), _leg("put", "put", "long", 1, "put")),
        "strangle", "vega_budget",
    ),
    "short_strangle": StrategySpec(
        "short_strangle", ("call", "put"), False,
        (_leg("call", "call", "short", 1, "call", is_anchor=True), _leg("put", "put", "short", 1, "put")),
        "strangle", "margin_naked",
    ),
    # -- call butterflies (butterfly_call/call_butterfly are real, separate
    #    aliased factory attrs on OptionStrategies - both registered) --
    "butterfly_call": StrategySpec(
        "butterfly_call", ("higher", "middle", "lower"), False,
        (
            _leg("higher", "call", "long", 1, "higher"),
            _leg("middle", "call", "short", 2, "middle", is_anchor=True),
            _leg("lower", "call", "long", 1, "lower"),
        ),
        "butterfly", "vega_budget",
    ),
    "call_butterfly": StrategySpec(
        "call_butterfly", ("higher", "middle", "lower"), False,
        (
            _leg("higher", "call", "long", 1, "higher"),
            _leg("middle", "call", "short", 2, "middle", is_anchor=True),
            _leg("lower", "call", "long", 1, "lower"),
        ),
        "butterfly", "vega_budget",
    ),
    "short_butterfly_call": StrategySpec(
        "short_butterfly_call", ("higher", "middle", "lower"), False,
        (
            _leg("higher", "call", "short", 1, "higher"),
            _leg("middle", "call", "long", 2, "middle", is_anchor=True),
            _leg("lower", "call", "short", 1, "lower"),
        ),
        "butterfly", "vega_budget",
    ),
    # -- put butterflies --
    "butterfly_put": StrategySpec(
        "butterfly_put", ("higher", "middle", "lower"), False,
        (
            _leg("higher", "put", "long", 1, "higher"),
            _leg("middle", "put", "short", 2, "middle", is_anchor=True),
            _leg("lower", "put", "long", 1, "lower"),
        ),
        "butterfly", "vega_budget",
    ),
    "put_butterfly": StrategySpec(
        "put_butterfly", ("higher", "middle", "lower"), False,
        (
            _leg("higher", "put", "long", 1, "higher"),
            _leg("middle", "put", "short", 2, "middle", is_anchor=True),
            _leg("lower", "put", "long", 1, "lower"),
        ),
        "butterfly", "vega_budget",
    ),
    "short_butterfly_put": StrategySpec(
        "short_butterfly_put", ("higher", "middle", "lower"), False,
        (
            _leg("higher", "put", "short", 1, "higher"),
            _leg("middle", "put", "long", 2, "middle", is_anchor=True),
            _leg("lower", "put", "short", 1, "lower"),
        ),
        "butterfly", "vega_budget",
    ),
    # -- calendar spreads (2 distinct expiries, 1 strike role shared by both legs) --
    "call_calendar_spread": StrategySpec(
        "call_calendar_spread", ("strike",), True,
        (
            _leg("near", "call", "short", 1, "strike", "near", is_anchor=True),
            _leg("far", "call", "long", 1, "strike", "far"),
        ),
        "calendar", "vega_budget",
    ),
    "short_call_calendar_spread": StrategySpec(
        "short_call_calendar_spread", ("strike",), True,
        (
            _leg("near", "call", "long", 1, "strike", "near", is_anchor=True),
            _leg("far", "call", "short", 1, "strike", "far"),
        ),
        "calendar", "vega_budget",
    ),
    "put_calendar_spread": StrategySpec(
        "put_calendar_spread", ("strike",), True,
        (
            _leg("near", "put", "short", 1, "strike", "near", is_anchor=True),
            _leg("far", "put", "long", 1, "strike", "far"),
        ),
        "calendar", "vega_budget",
    ),
    "short_put_calendar_spread": StrategySpec(
        "short_put_calendar_spread", ("strike",), True,
        (
            _leg("near", "put", "long", 1, "strike", "near", is_anchor=True),
            _leg("far", "put", "short", 1, "strike", "far"),
        ),
        "calendar", "vega_budget",
    ),
    # -- iron condors (composed from 2 independent credit verticals) --
    "iron_condor": StrategySpec(
        "iron_condor", ("long_put", "short_put", "short_call", "long_call"), False,
        (
            _leg("long_put", "put", "long", 1, "long_put"),
            _leg("short_put", "put", "short", 1, "short_put", is_anchor=True),
            _leg("short_call", "call", "short", 1, "short_call", is_anchor=True),
            _leg("long_call", "call", "long", 1, "long_call"),
        ),
        "iron_condor", "vega_budget",
    ),
    "short_iron_condor": StrategySpec(
        "short_iron_condor", ("short_put", "long_put", "long_call", "short_call"), False,
        (
            _leg("short_put", "put", "short", 1, "short_put", is_anchor=True),
            _leg("long_put", "put", "long", 1, "long_put"),
            _leg("long_call", "call", "long", 1, "long_call"),
            _leg("short_call", "call", "short", 1, "short_call", is_anchor=True),
        ),
        "iron_condor", "vega_budget",
    ),
    # -- iron butterflies (shared ATM strike between the 2 short/long-middle legs) --
    "iron_butterfly": StrategySpec(
        "iron_butterfly", ("otm_put", "atm", "otm_call"), False,
        (
            _leg("long_put", "put", "long", 1, "otm_put"),
            _leg("short_put", "put", "short", 1, "atm", is_anchor=True),
            _leg("short_call", "call", "short", 1, "atm", is_anchor=True),
            _leg("long_call", "call", "long", 1, "otm_call"),
        ),
        "iron_butterfly", "vega_budget",
    ),
    "short_iron_butterfly": StrategySpec(
        "short_iron_butterfly", ("otm_put", "atm", "otm_call"), False,
        (
            _leg("short_put", "put", "short", 1, "otm_put", is_anchor=True),
            _leg("long_put", "put", "long", 1, "atm"),
            _leg("long_call", "call", "long", 1, "atm"),
            _leg("short_call", "call", "short", 1, "otm_call", is_anchor=True),
        ),
        "iron_butterfly", "vega_budget",
    ),
    # -- backspreads (1:2 ratio; call_backspread/put_backspread are the
    #    genuinely bounded, long-heavy originals; short_* are the inverted,
    #    genuinely unbounded, short-heavy variants - see module note) --
    "call_backspread": StrategySpec(
        "call_backspread", ("lower", "higher"), False,
        (
            _leg("lower", "call", "short", 1, "lower", is_anchor=True),
            _leg("higher", "call", "long", 2, "higher"),
        ),
        "backspread", "margin_bounded_backspread",
    ),
    "short_call_backspread": StrategySpec(
        "short_call_backspread", ("lower", "higher"), False,
        (
            _leg("lower", "call", "long", 1, "lower", is_anchor=True),
            _leg("higher", "call", "short", 2, "higher"),
        ),
        "backspread", "margin_naked",
    ),
    "put_backspread": StrategySpec(
        "put_backspread", ("higher", "lower"), False,
        (
            _leg("higher", "put", "short", 1, "higher", is_anchor=True),
            _leg("lower", "put", "long", 2, "lower"),
        ),
        "backspread", "margin_bounded_backspread",
    ),
    "short_put_backspread": StrategySpec(
        "short_put_backspread", ("higher", "lower"), False,
        (
            _leg("higher", "put", "long", 1, "higher", is_anchor=True),
            _leg("lower", "put", "short", 2, "lower"),
        ),
        "backspread", "margin_naked",
    ),
    # -- ladders (1:1:1; bear_call_ladder/bull_put_ladder are net-long and
    #    bounded; bull_call_ladder/bear_put_ladder are net-short and
    #    unbounded - see module note) --
    "bear_call_ladder": StrategySpec(
        "bear_call_ladder", ("lower", "middle", "higher"), False,
        (
            _leg("lower", "call", "short", 1, "lower", is_anchor=True),
            _leg("middle", "call", "long", 1, "middle"),
            _leg("higher", "call", "long", 1, "higher"),
        ),
        "ladder", "vega_budget",
    ),
    "bull_call_ladder": StrategySpec(
        "bull_call_ladder", ("lower", "middle", "higher"), False,
        (
            _leg("lower", "call", "long", 1, "lower", is_anchor=True),
            _leg("middle", "call", "short", 1, "middle"),
            _leg("higher", "call", "short", 1, "higher"),
        ),
        "ladder", "margin_uncovered_leg",
    ),
    "bear_put_ladder": StrategySpec(
        "bear_put_ladder", ("higher", "middle", "lower"), False,
        (
            _leg("higher", "put", "long", 1, "higher", is_anchor=True),
            _leg("middle", "put", "short", 1, "middle"),
            _leg("lower", "put", "short", 1, "lower"),
        ),
        "ladder", "margin_uncovered_leg",
    ),
    "bull_put_ladder": StrategySpec(
        "bull_put_ladder", ("higher", "middle", "lower"), False,
        (
            _leg("higher", "put", "short", 1, "higher", is_anchor=True),
            _leg("middle", "put", "long", 1, "middle"),
            _leg("lower", "put", "long", 1, "lower"),
        ),
        "ladder", "vega_budget",
    ),
    # -- naked single-leg shorts --
    "naked_call": StrategySpec(
        "naked_call", ("strike",), False, (_leg("call", "call", "short", 1, "strike", is_anchor=True),),
        "naked", "margin_naked",
    ),
    "naked_put": StrategySpec(
        "naked_put", ("strike",), False, (_leg("put", "put", "short", 1, "strike", is_anchor=True),),
        "naked", "margin_naked",
    ),
    # -- covered/protective/collar (equity leg tracked separately, see
    #    main.py's corrected cross-asset design - never the bundled factory) --
    "covered_call": StrategySpec(
        "covered_call", ("strike",), False, (_leg("call", "call", "short", 1, "strike", is_anchor=True),),
        "covered_protective", "covered_protective", covering_equity_side="long",
    ),
    "covered_put": StrategySpec(
        "covered_put", ("strike",), False, (_leg("put", "put", "short", 1, "strike", is_anchor=True),),
        "covered_protective", "covered_protective", covering_equity_side="short",
    ),
    "protective_call": StrategySpec(
        "protective_call", ("strike",), False, (_leg("call", "call", "long", 1, "strike", is_anchor=True),),
        "covered_protective", "covered_protective", covering_equity_side="short",
    ),
    "protective_put": StrategySpec(
        "protective_put", ("strike",), False, (_leg("put", "put", "long", 1, "strike", is_anchor=True),),
        "covered_protective", "covered_protective", covering_equity_side="long",
    ),
    "protective_collar": StrategySpec(
        "protective_collar", ("call", "put"), False,
        (
            _leg("call", "call", "short", 1, "call", is_anchor=True),
            _leg("put", "put", "long", 1, "put", is_anchor=True),
        ),
        "collar", "covered_protective", covering_equity_side="long",
    ),
    # -- arbitrage (stubbed - registry/selector/tests exist; never in the
    #    default enabled_strategy_names, and no signal source ever produces
    #    these strategy_name values, see development/Problems.md) --
    "box_spread": StrategySpec(
        "box_spread", ("higher", "lower"), False,
        (
            _leg("long_put", "put", "long", 1, "higher", is_anchor=True),
            _leg("short_put", "put", "short", 1, "lower"),
            _leg("long_call", "call", "long", 1, "lower"),
            _leg("short_call", "call", "short", 1, "higher"),
        ),
        "arbitrage_box", "unreachable_arbitrage",
    ),
    "short_box_spread": StrategySpec(
        "short_box_spread", ("higher", "lower"), False,
        (
            _leg("short_put", "put", "short", 1, "higher", is_anchor=True),
            _leg("long_put", "put", "long", 1, "lower"),
            _leg("short_call", "call", "short", 1, "lower"),
            _leg("long_call", "call", "long", 1, "higher"),
        ),
        "arbitrage_box", "unreachable_arbitrage",
    ),
    "conversion": StrategySpec(
        "conversion", ("strike",), False,
        (
            _leg("short_call", "call", "short", 1, "strike", is_anchor=True),
            _leg("long_put", "put", "long", 1, "strike"),
        ),
        "arbitrage_conversion", "unreachable_arbitrage", covering_equity_side="long",
    ),
    "reverse_conversion": StrategySpec(
        "reverse_conversion", ("strike",), False,
        (
            _leg("long_call", "call", "long", 1, "strike", is_anchor=True),
            _leg("short_put", "put", "short", 1, "strike"),
        ),
        "arbitrage_conversion", "unreachable_arbitrage", covering_equity_side="short",
    ),
    "jelly_roll": StrategySpec(
        "jelly_roll", ("strike",), True,
        (
            _leg("near_call", "call", "short", 1, "strike", "near", is_anchor=True),
            _leg("far_call", "call", "long", 1, "strike", "far"),
            _leg("near_put", "put", "long", 1, "strike", "near"),
            _leg("far_put", "put", "short", 1, "strike", "far"),
        ),
        "arbitrage_jelly_roll", "unreachable_arbitrage",
    ),
    "short_jelly_roll": StrategySpec(
        "short_jelly_roll", ("strike",), True,
        (
            _leg("near_call", "call", "long", 1, "strike", "near", is_anchor=True),
            _leg("far_call", "call", "short", 1, "strike", "far"),
            _leg("near_put", "put", "short", 1, "strike", "near"),
            _leg("far_put", "put", "long", 1, "strike", "far"),
        ),
        "arbitrage_jelly_roll", "unreachable_arbitrage",
    ),
}


def _group_chain_by_expiry(available_chain: list[dict]) -> dict[str, list[dict]]:
    """Single O(n) pass grouping chain rows by expiry - built ONCE per
    selector call and reused for every leg lookup within it, rather than
    re-scanning the full chain per leg (this is the "latency-efficient"
    requirement for a function that runs every bar, per candidate
    strategy, per symbol). Also the mechanism that makes expiry-anchoring
    possible: every leg after the anchor is selected ONLY from
    grouped[anchor_expiry], never re-scanning the other expiries."""
    grouped: dict[str, list[dict]] = {}
    for row in available_chain:
        grouped.setdefault(row.get("expiry"), []).append(row)
    return grouped


def _nearest_by_delta(rows: list[dict], right: str, target_delta: float) -> dict | None:
    candidates = [r for r in rows if str(r.get("right", "")).lower() == right and r.get("delta") is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda r: abs(abs(r["delta"]) - abs(target_delta)))


def _nearest_by_strike(rows: list[dict], right: str, target_strike: float) -> dict | None:
    candidates = [r for r in rows if str(r.get("right", "")).lower() == right and r.get("strike") is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda r: abs(float(r["strike"]) - target_strike))


def _outer_strike_predicate(right: str, anchor_strike: float):
    """True for a strike further OTM than anchor_strike, for `right` -
    higher for calls, lower for puts. Pure geometry, independent of which
    leg is long/short (the fix for the debit/credit leg-role inversion
    bug: the OLD select_vertical_spread_legs() baked "outer == short" in
    by always returning long=anchor - this predicate is direction-neutral,
    role assignment happens separately in select_vertical_legs() below)."""
    if right == "call":
        return lambda strike: strike > anchor_strike
    return lambda strike: strike < anchor_strike


def select_vertical_legs(
    spec: StrategySpec, available_chain: list[dict], target_delta: float, short_leg_delta_offset: float = 0.20,
) -> dict[str, dict] | None:
    """Shared 2-leg vertical selector for shape_family == "vertical" -
    covers debit (bull_call_spread/bear_put_spread) AND credit
    (bear_call_spread/bull_put_spread) verticals identically: the ANCHOR
    leg (spec's is_anchor=True role) is picked by nearest-|delta| exactly
    like the existing single-leg selector; the OUTER leg is the
    nearest-|delta - short_leg_delta_offset| match among the SAME expiry's
    rows on the further-OTM side (_outer_strike_predicate). Which role
    ends up "long" vs "short" is irrelevant to this SELECTION geometry -
    that's already fixed by the registry (spec.legs[*].side) - so the same
    function is correct for both debit and credit shapes, closing the
    debit/credit leg-role-inversion bug without needing 2 separate
    selection algorithms."""
    anchor_leg = next(leg for leg in spec.legs if leg.is_anchor)
    outer_leg = next(leg for leg in spec.legs if not leg.is_anchor)

    anchor_row = _nearest_by_delta(available_chain, anchor_leg.right, target_delta)
    if anchor_row is None:
        return None
    anchor_expiry = anchor_row.get("expiry")
    anchor_strike = float(anchor_row["strike"])

    same_expiry_rows = [r for r in available_chain if r.get("expiry") == anchor_expiry]
    is_outer = _outer_strike_predicate(outer_leg.right, anchor_strike)
    outer_candidates = [
        r for r in same_expiry_rows
        if str(r.get("right", "")).lower() == outer_leg.right and r.get("delta") is not None
        and is_outer(float(r["strike"]))
    ]
    if not outer_candidates:
        return None
    outer_target_delta = target_delta - short_leg_delta_offset
    outer_row = min(outer_candidates, key=lambda r: abs(abs(r["delta"]) - abs(outer_target_delta)))
    return {anchor_leg.role: anchor_row, outer_leg.role: outer_row}


def select_straddle_legs(spec: StrategySpec, available_chain: list[dict], target_delta: float) -> dict[str, dict] | None:
    """shape_family == "straddle" (straddle/short_straddle) - same-strike,
    same-expiry call+put pair. Anchors on the call leg by delta, then
    requires a put at the EXACT same strike/expiry (never a nearest-delta
    put pick - a straddle's defining property is one shared strike)."""
    call_leg = next(leg for leg in spec.legs if leg.right == "call")
    put_leg = next(leg for leg in spec.legs if leg.right == "put")

    call_row = _nearest_by_delta(available_chain, "call", target_delta)
    if call_row is None:
        return None
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == call_row.get("expiry")]
    put_row = next(
        (r for r in same_expiry_rows if str(r.get("right", "")).lower() == "put" and float(r.get("strike", -1)) == float(call_row["strike"])),
        None,
    )
    if put_row is None:
        return None
    return {call_leg.role: call_row, put_leg.role: put_row}


def select_strangle_legs(
    spec: StrategySpec, available_chain: list[dict], target_delta: float, strangle_delta_offset: float = 0.15,
) -> dict[str, dict] | None:
    """shape_family == "strangle" (strangle/short_strangle) - offset-strike,
    same-expiry call+put pair (call strike above put strike, enforced by
    _outer_strike_predicate-style filtering anchored on the call leg's
    expiry, so both legs land on the same expiry by construction)."""
    call_leg = next(leg for leg in spec.legs if leg.right == "call")
    put_leg = next(leg for leg in spec.legs if leg.right == "put")

    call_row = _nearest_by_delta(available_chain, "call", target_delta)
    if call_row is None:
        return None
    call_strike = float(call_row["strike"])
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == call_row.get("expiry")]
    put_candidates = [
        r for r in same_expiry_rows
        if str(r.get("right", "")).lower() == "put" and r.get("delta") is not None and float(r["strike"]) < call_strike
    ]
    if not put_candidates:
        return None
    put_target_delta = target_delta - strangle_delta_offset
    put_row = min(put_candidates, key=lambda r: abs(abs(r["delta"]) - abs(put_target_delta)))
    return {call_leg.role: call_row, put_leg.role: put_row}


def select_butterfly_legs(
    spec: StrategySpec,
    available_chain: list[dict],
    target_delta: float,
    wing_width_delta_offset: float = 0.20,
    max_strike_asymmetry_tolerance: float = 0.15,
) -> dict[str, dict] | None:
    """shape_family == "butterfly" - middle strike anchored by delta (the
    2x-ratio body leg), then wings picked as the nearest available strikes
    ABOVE/BELOW it within the same expiry, degrading to None (never a
    forced/asymmetric fill) when the two wing strikes aren't within
    max_strike_asymmetry_tolerance of being equidistant from the middle -
    real discrete strike ladders widen away from spot, so "best-effort
    near-symmetric" is documented here as the honest contract, not exact
    equidistance."""
    middle_leg = next(leg for leg in spec.legs if leg.is_anchor)
    higher_leg = next(leg for leg in spec.legs if leg.strike_role == "higher")
    lower_leg = next(leg for leg in spec.legs if leg.strike_role == "lower")
    right = middle_leg.right

    middle_row = _nearest_by_delta(available_chain, right, target_delta)
    if middle_row is None:
        return None
    middle_strike = float(middle_row["strike"])
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == middle_row.get("expiry")]

    higher_candidates = sorted(
        (r for r in same_expiry_rows if str(r.get("right", "")).lower() == right and float(r.get("strike", middle_strike)) > middle_strike),
        key=lambda r: float(r["strike"]),
    )
    lower_candidates = sorted(
        (r for r in same_expiry_rows if str(r.get("right", "")).lower() == right and float(r.get("strike", middle_strike)) < middle_strike),
        key=lambda r: float(r["strike"]),
        reverse=True,
    )
    if not higher_candidates or not lower_candidates:
        return None
    higher_row = higher_candidates[0]
    lower_row = lower_candidates[0]

    higher_width = float(higher_row["strike"]) - middle_strike
    lower_width = middle_strike - float(lower_row["strike"])
    wider, narrower = max(higher_width, lower_width), min(higher_width, lower_width)
    if wider <= 0 or abs(wider - narrower) / wider > max_strike_asymmetry_tolerance:
        return None

    return {middle_leg.role: middle_row, higher_leg.role: higher_row, lower_leg.role: lower_row}


def select_iron_condor_legs(
    spec: StrategySpec,
    available_chain: list[dict],
    target_delta: float,
    short_leg_delta_offset: float = 0.20,
    wing_delta_offset: float = 0.10,
) -> dict[str, dict] | None:
    """shape_family == "iron_condor" - composed from 2 independent
    credit-vertical-style selections (put side, call side), both anchored
    to the SAME expiry (the put side's anchor expiry is picked first and
    passed down to the call side, closing the same expiry-drift risk
    select_vertical_legs() closes for a plain 2-leg vertical)."""
    short_put_leg = next(leg for leg in spec.legs if leg.role == "short_put")
    long_put_leg = next(leg for leg in spec.legs if leg.role == "long_put")
    short_call_leg = next(leg for leg in spec.legs if leg.role == "short_call")
    long_call_leg = next(leg for leg in spec.legs if leg.role == "long_call")

    short_put_row = _nearest_by_delta(available_chain, "put", target_delta)
    if short_put_row is None:
        return None
    anchor_expiry = short_put_row.get("expiry")
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == anchor_expiry]
    short_put_strike = float(short_put_row["strike"])

    long_put_candidates = [
        r for r in same_expiry_rows
        if str(r.get("right", "")).lower() == "put" and r.get("delta") is not None and float(r["strike"]) < short_put_strike
    ]
    if not long_put_candidates:
        return None
    long_put_row = min(long_put_candidates, key=lambda r: abs(abs(r["delta"]) - abs(target_delta - wing_delta_offset)))

    short_call_row = _nearest_by_delta(same_expiry_rows, "call", target_delta - short_leg_delta_offset)
    if short_call_row is None:
        return None
    short_call_strike = float(short_call_row["strike"])
    long_call_candidates = [
        r for r in same_expiry_rows
        if str(r.get("right", "")).lower() == "call" and r.get("delta") is not None and float(r["strike"]) > short_call_strike
    ]
    if not long_call_candidates:
        return None
    long_call_row = min(long_call_candidates, key=lambda r: abs(abs(r["delta"]) - abs(target_delta - short_leg_delta_offset - wing_delta_offset)))

    return {
        short_put_leg.role: short_put_row, long_put_leg.role: long_put_row,
        short_call_leg.role: short_call_row, long_call_leg.role: long_call_row,
    }


def select_iron_butterfly_legs(
    spec: StrategySpec,
    available_chain: list[dict],
    target_delta: float,
    wing_delta_offset: float = 0.20,
    max_strike_asymmetry_tolerance: float = 0.15,
) -> dict[str, dict] | None:
    """shape_family == "iron_butterfly" - the ATM strike is shared by BOTH
    middle legs (short_put and short_call both sit at the same strike, per
    OptionStrategies.cs's IronButterfly == IronCondor with its 2 middle
    strikes collapsed together), with the OTM wings picked equidistant
    (tolerance-based, same contract as select_butterfly_legs()) rather than
    independently re-selected by delta on each side."""
    call_middle_leg = next(leg for leg in spec.legs if leg.right == "call" and leg.strike_role == "atm")
    put_middle_leg = next(leg for leg in spec.legs if leg.right == "put" and leg.strike_role == "atm")
    otm_call_leg = next(leg for leg in spec.legs if leg.strike_role == "otm_call")
    otm_put_leg = next(leg for leg in spec.legs if leg.strike_role == "otm_put")

    atm_call_row = _nearest_by_delta(available_chain, "call", target_delta)
    if atm_call_row is None:
        return None
    atm_strike = float(atm_call_row["strike"])
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == atm_call_row.get("expiry")]
    atm_put_row = next(
        (r for r in same_expiry_rows if str(r.get("right", "")).lower() == "put" and float(r.get("strike", -1)) == atm_strike),
        None,
    )
    if atm_put_row is None:
        return None

    otm_call_candidates = sorted(
        (r for r in same_expiry_rows if str(r.get("right", "")).lower() == "call" and float(r.get("strike", atm_strike)) > atm_strike),
        key=lambda r: float(r["strike"]),
    )
    otm_put_candidates = sorted(
        (r for r in same_expiry_rows if str(r.get("right", "")).lower() == "put" and float(r.get("strike", atm_strike)) < atm_strike),
        key=lambda r: float(r["strike"]),
        reverse=True,
    )
    if not otm_call_candidates or not otm_put_candidates:
        return None
    otm_call_row = otm_call_candidates[0]
    otm_put_row = otm_put_candidates[0]

    call_wing_width = float(otm_call_row["strike"]) - atm_strike
    put_wing_width = atm_strike - float(otm_put_row["strike"])
    wider, narrower = max(call_wing_width, put_wing_width), min(call_wing_width, put_wing_width)
    if wider <= 0 or abs(wider - narrower) / wider > max_strike_asymmetry_tolerance:
        return None

    return {
        call_middle_leg.role: atm_call_row, put_middle_leg.role: atm_put_row,
        otm_call_leg.role: otm_call_row, otm_put_leg.role: otm_put_row,
    }


def select_calendar_legs(spec: StrategySpec, available_chain: list[dict], target_delta: float) -> dict[str, dict] | None:
    """shape_family == "calendar" - a genuinely new primitive (nothing
    before this pass compares two DIFFERENT expiries): groups the chain by
    expiry first (_group_chain_by_expiry(), O(n) once), requires at least
    2 distinct expiries, picks the near leg's strike by delta within the
    nearest expiry, then requires the SAME strike be present in every
    LATER expiry group - the far leg uses the closest-dated expiry that
    has it. Returns None for a chain with fewer than 2 expiries (routine
    for a thinly configured universe, never a crash)."""
    near_leg = next(leg for leg in spec.legs if leg.expiry_role == "near")
    far_leg = next(leg for leg in spec.legs if leg.expiry_role == "far")
    right = near_leg.right

    grouped = _group_chain_by_expiry(available_chain)
    expiries = sorted(e for e in grouped if e is not None)
    if len(expiries) < 2:
        return None

    near_expiry = expiries[0]
    near_row = _nearest_by_delta(grouped[near_expiry], right, target_delta)
    if near_row is None:
        return None
    strike = float(near_row["strike"])

    for far_expiry in expiries[1:]:
        far_row = _nearest_by_strike(grouped[far_expiry], right, strike)
        if far_row is not None and float(far_row["strike"]) == strike:
            return {near_leg.role: near_row, far_leg.role: far_row}
    return None


def select_backspread_legs(
    spec: StrategySpec, available_chain: list[dict], target_delta: float, backspread_delta_offset: float = 0.20,
) -> dict[str, dict] | None:
    """shape_family == "backspread" - 1:2-ratio 2-leg selector shared by
    all 4 variants (call_backspread/short_call_backspread/put_backspread/
    short_put_backspread); which strike_role ("lower"/"higher") is the
    anchor and which side each role maps to both come from the registry,
    so this one function is correct for every variant without branching
    on strategy_name."""
    anchor_leg = next(leg for leg in spec.legs if leg.is_anchor)
    other_leg = next(leg for leg in spec.legs if not leg.is_anchor)
    right = anchor_leg.right

    anchor_row = _nearest_by_delta(available_chain, right, target_delta)
    if anchor_row is None:
        return None
    anchor_strike = float(anchor_row["strike"])
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == anchor_row.get("expiry")]
    is_outer = _outer_strike_predicate(right, anchor_strike) if anchor_leg.strike_role == "lower" else (
        lambda strike: strike < anchor_strike
    )
    other_candidates = [
        r for r in same_expiry_rows
        if str(r.get("right", "")).lower() == right and r.get("delta") is not None and is_outer(float(r["strike"]))
    ]
    if not other_candidates:
        return None
    other_target_delta = target_delta - backspread_delta_offset
    other_row = min(other_candidates, key=lambda r: abs(abs(r["delta"]) - abs(other_target_delta)))
    return {anchor_leg.role: anchor_row, other_leg.role: other_row}


def select_ladder_legs(
    spec: StrategySpec, available_chain: list[dict], target_delta: float, ladder_wing_delta_offset: float = 0.15,
) -> dict[str, dict] | None:
    """shape_family == "ladder" - 3-strike, 1:1:1-ratio selector shared by
    all 4 variants (bear_call_ladder/bull_call_ladder/bear_put_ladder/
    bull_put_ladder). Anchors on the spec's anchor leg by delta, then picks
    the other 2 legs as the nearest available strikes further from the
    anchor in the direction _outer_strike_predicate defines for this
    right - same expiry-anchoring guarantee as every other selector here."""
    anchor_leg = next(leg for leg in spec.legs if leg.is_anchor)
    other_legs = [leg for leg in spec.legs if not leg.is_anchor]
    right = anchor_leg.right

    anchor_row = _nearest_by_delta(available_chain, right, target_delta)
    if anchor_row is None:
        return None
    anchor_strike = float(anchor_row["strike"])
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == anchor_row.get("expiry")]
    is_outer = _outer_strike_predicate(right, anchor_strike)
    outer_candidates = sorted(
        (r for r in same_expiry_rows if str(r.get("right", "")).lower() == right and is_outer(float(r.get("strike", anchor_strike)))),
        key=lambda r: abs(float(r["strike"]) - anchor_strike),
    )
    if len(outer_candidates) < 2:
        return None

    result = {anchor_leg.role: anchor_row}
    # other_legs is exactly 2 roles (registry order matches increasing
    # distance from the anchor strike, e.g. "middle" then "higher" for
    # bear_call_ladder) - zip against the 2 nearest outer candidates by
    # strike distance, honoring that ordering.
    for leg, row in zip(other_legs, outer_candidates[:2]):
        result[leg.role] = row
    return result


def select_naked_leg(spec: StrategySpec, available_chain: list[dict], target_delta: float) -> dict[str, dict] | None:
    """shape_family == "naked" (naked_call/naked_put) - a single short leg,
    nearest-|delta| selection, no expiry-anchoring needed (only 1 leg)."""
    leg = spec.legs[0]
    row = _nearest_by_delta(available_chain, leg.right, target_delta)
    if row is None:
        return None
    return {leg.role: row}


def select_covered_protective_leg(spec: StrategySpec, available_chain: list[dict], target_delta: float) -> dict[str, dict] | None:
    """shape_family in {"covered_protective", "collar"} - the OPTION leg(s)
    only (never the equity side - see main.py's corrected cross-asset
    design, the equity leg is read from the currently-held quantity, not
    selected from a chain). protective_collar has 2 anchor legs (call and
    put), each selected independently by delta since a collar's call/put
    strikes are deliberately NOT required to be equidistant from spot
    (call_strike > put_strike is the only real constraint, enforced
    upstream by OptionStrategies.ProtectiveCollar itself)."""
    result = {}
    for leg in spec.legs:
        row = _nearest_by_delta(available_chain, leg.right, target_delta)
        if row is None:
            return None
        result[leg.role] = row
    if spec.shape_family == "collar" and len(result) == 2:
        rows = list(result.values())
        if float(rows[0]["strike"]) == float(rows[1]["strike"]):
            # ProtectiveCollar requires call_strike > put_strike strictly -
            # degrade to None rather than let main.py hand Lean's factory
            # two equal strikes it will itself reject with an exception.
            return None
    return result


def select_arbitrage_box_legs(spec: StrategySpec, available_chain: list[dict], target_delta: float) -> dict[str, dict] | None:
    """shape_family == "arbitrage_box" (box_spread/short_box_spread) -
    wired-but-unreachable (development/Problems.md): registry/selector
    exist and are unit-tested, but no signal source in this codebase ever
    calls this - a real box spread requires a mispricing detector (rich/
    cheap vs. the risk-free-rate-implied fair value), a separate future
    project. Reuses select_vertical_legs()-style same-expiry anchoring:
    the "higher"-strike-role legs (long_put, short_call) anchor by delta,
    the "lower"-strike-role legs (short_put, long_call) share the SAME
    strike as one of the anchor legs by construction (a box spread is a
    single strike pair, not 4 independent strikes)."""
    long_put_leg = next(leg for leg in spec.legs if leg.role == "long_put")
    short_put_leg = next(leg for leg in spec.legs if leg.role == "short_put")
    long_call_leg = next(leg for leg in spec.legs if leg.role == "long_call")
    short_call_leg = next(leg for leg in spec.legs if leg.role == "short_call")

    put_anchor_row = _nearest_by_delta(available_chain, "put", target_delta)
    if put_anchor_row is None:
        return None
    higher_strike = float(put_anchor_row["strike"])
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == put_anchor_row.get("expiry")]
    lower_candidates = sorted(
        (r for r in same_expiry_rows if str(r.get("right", "")).lower() == "put" and float(r.get("strike", higher_strike)) < higher_strike),
        key=lambda r: float(r["strike"]),
        reverse=True,
    )
    if not lower_candidates:
        return None
    lower_strike = float(lower_candidates[0]["strike"])

    put_rows = {"higher": put_anchor_row, "lower": lower_candidates[0]}
    call_higher_row = _nearest_by_strike(same_expiry_rows, "call", higher_strike)
    call_lower_row = _nearest_by_strike(same_expiry_rows, "call", lower_strike)
    if call_higher_row is None or call_lower_row is None:
        return None
    call_rows = {"higher": call_higher_row, "lower": call_lower_row}

    return {
        long_put_leg.role: put_rows[long_put_leg.strike_role],
        short_put_leg.role: put_rows[short_put_leg.strike_role],
        long_call_leg.role: call_rows[long_call_leg.strike_role],
        short_call_leg.role: call_rows[short_call_leg.strike_role],
    }


def select_arbitrage_conversion_legs(spec: StrategySpec, available_chain: list[dict], target_delta: float) -> dict[str, dict] | None:
    """shape_family == "arbitrage_conversion" (conversion/reverse_conversion)
    - wired-but-unreachable, same caveat as select_arbitrage_box_legs()
    above. Single shared strike for both legs (same-expiry, same-strike
    call+put pair - identical selection shape to select_straddle_legs())."""
    call_leg = next(leg for leg in spec.legs if leg.right == "call")
    put_leg = next(leg for leg in spec.legs if leg.right == "put")
    anchor_leg, other_leg = (call_leg, put_leg) if call_leg.is_anchor else (put_leg, call_leg)

    anchor_row = _nearest_by_delta(available_chain, anchor_leg.right, target_delta)
    if anchor_row is None:
        return None
    same_expiry_rows = [r for r in available_chain if r.get("expiry") == anchor_row.get("expiry")]
    other_row = next(
        (
            r for r in same_expiry_rows
            if str(r.get("right", "")).lower() == other_leg.right and float(r.get("strike", -1)) == float(anchor_row["strike"])
        ),
        None,
    )
    if other_row is None:
        return None
    return {anchor_leg.role: anchor_row, other_leg.role: other_row}


def select_arbitrage_jelly_roll_legs(spec: StrategySpec, available_chain: list[dict], target_delta: float) -> dict[str, dict] | None:
    """shape_family == "arbitrage_jelly_roll" (jelly_roll/short_jelly_roll)
    - wired-but-unreachable, same caveat as the other 2 arbitrage selectors
    above. Same expiry-grouping primitive as select_calendar_legs(), but
    requires all 4 legs (near call, far call, near put, far put) to share
    ONE strike across both expiries."""
    near_call_leg = next(leg for leg in spec.legs if leg.role == "near_call")
    far_call_leg = next(leg for leg in spec.legs if leg.role == "far_call")
    near_put_leg = next(leg for leg in spec.legs if leg.role == "near_put")
    far_put_leg = next(leg for leg in spec.legs if leg.role == "far_put")

    grouped = _group_chain_by_expiry(available_chain)
    expiries = sorted(e for e in grouped if e is not None)
    if len(expiries) < 2:
        return None
    near_expiry = expiries[0]
    near_call_row = _nearest_by_delta(grouped[near_expiry], "call", target_delta)
    if near_call_row is None:
        return None
    strike = float(near_call_row["strike"])

    for far_expiry in expiries[1:]:
        far_call_row = _nearest_by_strike(grouped[far_expiry], "call", strike)
        near_put_row = _nearest_by_strike(grouped[near_expiry], "put", strike)
        far_put_row = _nearest_by_strike(grouped[far_expiry], "put", strike)
        if (
            far_call_row is not None and float(far_call_row["strike"]) == strike
            and near_put_row is not None and float(near_put_row["strike"]) == strike
            and far_put_row is not None and float(far_put_row["strike"]) == strike
        ):
            return {
                near_call_leg.role: near_call_row, far_call_leg.role: far_call_row,
                near_put_leg.role: near_put_row, far_put_leg.role: far_put_row,
            }
    return None


_SHAPE_FAMILY_SELECTORS = {
    "straddle": select_straddle_legs,
    "strangle": select_strangle_legs,
    "butterfly": select_butterfly_legs,
    "iron_condor": select_iron_condor_legs,
    "iron_butterfly": select_iron_butterfly_legs,
    "calendar": select_calendar_legs,
    "backspread": select_backspread_legs,
    "ladder": select_ladder_legs,
    "naked": select_naked_leg,
    "covered_protective": select_covered_protective_leg,
    "collar": select_covered_protective_leg,
    "arbitrage_box": select_arbitrage_box_legs,
    "arbitrage_conversion": select_arbitrage_conversion_legs,
    "arbitrage_jelly_roll": select_arbitrage_jelly_roll_legs,
}


def select_strategy_legs(strategy_name: str, available_chain: list[dict], target_delta: float, **tuning_kwargs) -> dict[str, dict] | None:
    """Single dispatch point every caller (main.py, tests) should use
    instead of calling a shape-family selector directly - looks up
    strategy_name's StrategySpec then its shape_family's selector, a plain
    dict lookup (O(1)) rather than an if/elif chain over 43 names, matching
    this module's "registry, not 41 near-duplicate functions" design goal.
    "vertical" strategies use select_vertical_legs() directly (not in the
    dispatch dict above, since it takes the full spec + is reused by 4
    strategy_names identically). tuning_kwargs passes through to whichever
    selector is chosen (e.g. short_leg_delta_offset, wing_width_delta_offset)
    - unrecognized kwargs for a given selector are simply not in its
    signature and would raise, exactly like any other Python call; callers
    should only pass kwargs relevant to the strategy family they're
    invoking, or none at all to accept every selector's own defaults."""
    spec = MULTI_LEG_STRATEGY_REGISTRY.get(strategy_name)
    if spec is None:
        return None
    if spec.shape_family == "vertical":
        return select_vertical_legs(spec, available_chain, target_delta, **tuning_kwargs)
    selector = _SHAPE_FAMILY_SELECTORS.get(spec.shape_family)
    if selector is None:
        return None
    return selector(spec, available_chain, target_delta, **tuning_kwargs)


@dataclass(frozen=True)
class OptionsMultiLegPositionDecision:
    """N-leg sibling of OptionsSpreadPositionDecision - generalized to any
    leg count/ratio and to 1 OR 2 distinct expiries (the calendar family),
    rather than OptionsSpreadPositionDecision's fixed 2-leg/1-expiry shape.
    A SEPARATE dataclass, not a generalization of it - every existing
    caller of OptionsSpreadPositionDecision (bull_call_spread/
    bear_put_spread's own dedicated sizing path) is completely untouched."""

    strategy_name: str
    legs: tuple[OptionsSpreadLeg, ...]   # one per StrategySpec.legs entry, in registry order
    expiries: tuple[str, ...]            # 1 entry for every family except calendar/jelly-roll (2: near, far)
    contracts: int                        # spread-unit quantity, NOT a per-leg contract count (ratio legs bake their own multiple in via main.py's factory call, same convention the 2-leg vertical already established)
    net_debit_or_credit: float            # best-effort diagnostic only, 0.0 when bid/ask are absent
    net_delta: float                      # sum of side-signed, ratio-weighted per-leg deltas
    net_vega: float                       # fraction of portfolio_value the sized position's net vega consumes
    sizing_reason: str

    def to_dict(self) -> dict:
        """Same manual-field-access convention as every other decision
        dataclass in this module - never dataclasses.asdict()."""
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
            "net_debit_or_credit": self.net_debit_or_credit,
            "net_delta": self.net_delta,
            "net_vega": self.net_vega,
            "sizing_reason": self.sizing_reason,
        }


def _legs_tuple_from_roles(spec: StrategySpec, legs_by_role: dict[str, dict]) -> tuple[OptionsSpreadLeg, ...]:
    """Shared OptionsSpreadLeg-tuple builder - every multi-leg sizing path
    (vega-budget, margin, covered/protective) produces the exact same leg
    shape from a role->chain-row dict, so this is written once."""
    return tuple(
        OptionsSpreadLeg(
            strike=float(legs_by_role[leg_spec.role]["strike"]),
            right=leg_spec.right,
            side=leg_spec.side,
            contract_symbol=legs_by_role[leg_spec.role].get("symbol"),
        )
        for leg_spec in spec.legs
    )


def _expiries_tuple_from_roles(spec: StrategySpec, legs_by_role: dict[str, dict]) -> tuple[str, ...]:
    """1-entry tuple for every family except the 2 calendar-shaped ones
    (near, far) - shared by every multi-leg sizing path, same rationale as
    _legs_tuple_from_roles() above."""
    if spec.has_expiry_pair:
        near_role = next(leg.role for leg in spec.legs if leg.expiry_role == "near")
        far_role = next(leg.role for leg in spec.legs if leg.expiry_role == "far")
        return (str(legs_by_role[near_role]["expiry"]), str(legs_by_role[far_role]["expiry"]))
    any_row = next(iter(legs_by_role.values()))
    return (str(any_row["expiry"]),)


def _net_vega_and_delta_per_unit(spec: StrategySpec, legs_by_role: dict[str, dict]) -> tuple[float, float]:
    """Signed, ratio-weighted sum of vega/delta across every leg - the
    generalization of the 2-leg vertical's `long_vega - short_vega` to N
    legs at arbitrary ratios (a butterfly's body leg contributes
    side_sign * 2 * its own vega, not 1x)."""
    net_vega = 0.0
    net_delta = 0.0
    for leg_spec in spec.legs:
        row = legs_by_role.get(leg_spec.role)
        if row is None:
            continue
        side_sign = 1.0 if leg_spec.side == "long" else -1.0
        net_vega += side_sign * leg_spec.ratio * float(row.get("vega", 0.0) or 0.0)
        net_delta += side_sign * leg_spec.ratio * float(row.get("delta", 0.0) or 0.0)
    return net_vega, net_delta


def _size_multi_leg(
    strategy_name: str,
    legs_by_role: dict[str, dict],
    portfolio_value: float,
    max_vega_budget_pct_of_equity: float,
    sizing_reason: str,
) -> OptionsMultiLegPositionDecision | None:
    """Shared net-vega-budget arithmetic for an already-resolved leg set -
    the N-leg generalization of _size_vertical_spread() above. Only used
    for risk_tier == "vega_budget" strategies (margin-tier strategies are
    sized by portfolio/options_margin_sizing.py instead - kept OUT of this
    function, matching the plan's hard separation between the two sizing
    paradigms). Returns None when net_vega is non-positive or the budget
    rounds down to zero spread units - never raises."""
    spec = MULTI_LEG_STRATEGY_REGISTRY[strategy_name]
    net_vega, net_delta = _net_vega_and_delta_per_unit(spec, legs_by_role)
    # UNLIKE the 2-leg debit vertical's long_vega - short_vega (always
    # positive by construction there - the anchor/long leg is always
    # nearer money, hence higher-vega, than the short leg), a credit
    # vertical or iron condor/butterfly's anchor leg is the SHORT
    # (near-money, higher-vega) one - net_vega is structurally NEGATIVE
    # for those, by design (a short-vol structure IS a net-short-vega
    # position). Budget by magnitude, not sign - only a truly flat (zero)
    # net vega is unsizeable.
    abs_net_vega = abs(net_vega)
    if abs_net_vega == 0.0:
        return None

    vega_budget = max_vega_budget_pct_of_equity * portfolio_value
    contracts = int(vega_budget // abs_net_vega)
    if contracts <= 0:
        return None

    legs = _legs_tuple_from_roles(spec, legs_by_role)
    expiries = _expiries_tuple_from_roles(spec, legs_by_role)

    net_debit_or_credit = 0.0
    for leg_spec in spec.legs:
        row = legs_by_role.get(leg_spec.role, {})
        price = row.get("ask") if leg_spec.side == "long" else row.get("bid")
        if price is None:
            net_debit_or_credit = 0.0
            break
        side_sign = 1.0 if leg_spec.side == "long" else -1.0
        net_debit_or_credit += side_sign * leg_spec.ratio * float(price)

    return OptionsMultiLegPositionDecision(
        strategy_name=strategy_name,
        legs=legs,
        expiries=expiries,
        contracts=contracts,
        net_debit_or_credit=net_debit_or_credit,
        net_delta=net_delta,
        net_vega=(contracts * abs_net_vega) / portfolio_value,
        sizing_reason=sizing_reason,
    )


def build_multi_leg_position_sizing(
    strategy_name: str,
    signal_direction: str,
    confidence: float,
    available_chain: list[dict],
    portfolio_value: float,
    target_delta_at_full_confidence: float = 0.60,
    max_vega_budget_pct_of_equity: float = 0.02,
    **selector_tuning_kwargs,
) -> OptionsMultiLegPositionDecision | None:
    """The single public entry point for every NEW (V4.5) vega-budget-tier
    strategy - dispatches leg selection via select_strategy_legs(), then
    sizes via _size_multi_leg(). Returns None for any margin-tier or
    unreachable-arbitrage strategy_name (those are sized by
    portfolio/options_margin_sizing.py, or never sized at all,
    respectively) - a caller passing the wrong tier's strategy_name here
    gets a clean None, not a wrong/unsafe budget calculation."""
    spec = MULTI_LEG_STRATEGY_REGISTRY.get(strategy_name)
    if spec is None or spec.risk_tier != "vega_budget":
        return None

    confidence = max(0.0, min(float(confidence), 1.0))
    portfolio_value = max(float(portfolio_value), 0.0)
    if confidence == 0.0 or portfolio_value <= 0.0:
        return None
    if signal_direction not in ("buy", "sell", "short"):
        return None

    target_delta = target_delta_at_full_confidence * confidence
    legs_by_role = select_strategy_legs(strategy_name, available_chain, target_delta, **selector_tuning_kwargs)
    if legs_by_role is None:
        return None

    return _size_multi_leg(
        strategy_name, legs_by_role, portfolio_value, max_vega_budget_pct_of_equity,
        "delta_targeted_net_vega_budgeted_multi_leg_sizing",
    )


def build_multi_leg_position_sizing_for_legs(
    strategy_name: str,
    held_rows_by_role: dict[str, dict],
    portfolio_value: float,
    max_vega_budget_pct_of_equity: float = 0.02,
) -> OptionsMultiLegPositionDecision | None:
    """Resize-in-place sibling of build_multi_leg_position_sizing() - sizes
    an ALREADY-HELD position on its legs' own current greeks, skipping
    selection entirely. held_rows_by_role must carry an entry for every
    role in MULTI_LEG_STRATEGY_REGISTRY[strategy_name].legs (same shape
    select_strategy_legs() returns) - same degrade-to-None contract as
    build_multi_leg_position_sizing() for non-positive portfolio_value or
    non-positive net vega."""
    portfolio_value = max(float(portfolio_value), 0.0)
    if portfolio_value <= 0.0:
        return None
    if strategy_name not in MULTI_LEG_STRATEGY_REGISTRY:
        return None
    return _size_multi_leg(
        strategy_name, held_rows_by_role, portfolio_value, max_vega_budget_pct_of_equity,
        "held_legs_own_greeks_multi_leg_sizing",
    )


# ---------------------------------------------------------------------------
# Volatility-view signal (drives straddle/strangle/iron condor/butterfly/
# credit-vs-debit selection within the enabled_strategy_names allowlist).
# ---------------------------------------------------------------------------

ANNUALIZATION_FACTOR_DAILY_TO_ANNUAL = math.sqrt(252)


def atm_implied_volatility(available_chain: list[dict], expiry: str) -> float | None:
    """Nearest-to-spot call+put average IV for one expiry - "nearest to
    spot" approximated here as the LOWEST |delta - 0.5| call combined with
    its same-strike put (a call delta near 0.50 is the standard ATM proxy
    when a real spot/strike distance isn't threaded through this function).
    Returns None when the expiry has no usable call (chain empty, IB
    disabled, or no "iv"/"implied_volatility" field present) - never a
    crash, matching this module's degrade-to-absent convention."""
    rows = [r for r in available_chain if r.get("expiry") == expiry]
    calls = [r for r in rows if str(r.get("right", "")).lower() == "call" and r.get("delta") is not None]
    if not calls:
        return None
    atm_call = min(calls, key=lambda r: abs(abs(r["delta"]) - 0.50))
    call_iv = atm_call.get("iv", atm_call.get("implied_volatility"))
    put_row = next(
        (r for r in rows if str(r.get("right", "")).lower() == "put" and float(r.get("strike", -1)) == float(atm_call["strike"])),
        None,
    )
    put_iv = put_row.get("iv", put_row.get("implied_volatility")) if put_row is not None else None
    ivs = [float(v) for v in (call_iv, put_iv) if v is not None]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def classify_volatility_view(predicted_volatility_annualized: float, atm_iv: float, margin: float = 0.05) -> str:
    """Pure, unit-agnostic classifier: "long_vol" when the model's own
    annualized volatility forecast exceeds the chain's current ATM implied
    vol by more than `margin`, "short_vol" when it's below by more than
    `margin`, else "neutral". The annualization (predicted_volatility *
    ANNUALIZATION_FACTOR_DAILY_TO_ANNUAL) MUST happen at the call site,
    never inside this function - train.py's target_volatility_next_day is
    a raw daily high-low-range proxy, not annualized, and comparing it
    against chain IV (always annualized) unit-mismatched would produce an
    almost-always-false signal. Documented approximation regardless of
    units: a range-based estimator and a lognormal-return-implied vol
    aren't the same statistical object even after unit-matching."""
    if predicted_volatility_annualized > atm_iv + margin:
        return "long_vol"
    if predicted_volatility_annualized < atm_iv - margin:
        return "short_vol"
    return "neutral"


# Which strategy_names are eligible for each volatility_view bucket -
# purely a lookup over shape_family/risk_tier, no chain/confidence
# involved (main.py tries each eligible, ENABLED name in priority order
# via build_multi_leg_position_sizing()/margin sizing until one actually
# sizes - see order_enabled_strategies() below for the ordering itself).
_LONG_VOL_SHAPE_FAMILIES = frozenset({"straddle_long", "strangle_long"})
_SHORT_VOL_SHAPE_FAMILIES = frozenset({"straddle_short", "strangle_short", "iron_condor", "iron_butterfly"})


def strategies_for_volatility_view(volatility_view: str) -> frozenset[str]:
    """Pure lookup: which registered strategy_names express `volatility_view`
    ("long_vol" -> long straddle/strangle; "short_vol" -> short straddle/
    strangle + iron condor/butterfly, both defined- and unbounded-risk
    variants included so risk_tier_preference below can choose between
    them; "neutral" -> empty, no strategy actively expresses a neutral
    view here). Iron condor/butterfly are "short_vol" regardless of the
    long/short spelling of their own name (short_iron_condor is itself
    already the credit/short-vol side; there is no long_iron_condor
    concept in this shape family)."""
    if volatility_view == "long_vol":
        return frozenset({"straddle", "strangle"})
    if volatility_view == "short_vol":
        return frozenset({
            "short_straddle", "short_strangle",
            "iron_condor", "short_iron_condor", "iron_butterfly", "short_iron_butterfly",
        })
    return frozenset()


_DEFINED_RISK_STRATEGY_NAMES = frozenset({"iron_condor", "short_iron_condor", "iron_butterfly", "short_iron_butterfly"})
_UNBOUNDED_RISK_STRATEGY_NAMES = frozenset({"short_straddle", "short_strangle"})


def order_enabled_strategies(enabled_strategy_names: list[str], risk_tier_preference: str = "defined_risk_first") -> list[str]:
    """Pure reordering (§9.2): enabled_strategy_names is a PRIORITY list,
    not just a membership set - the first enabled name (in the returned
    order) that matches the current bucket and successfully sizes wins.
    "defined_risk_first" (the safe default) stable-sorts every
    defined-risk name (iron condor/butterfly variants) ahead of every
    unbounded-risk name (short straddle/strangle), preserving the
    caller's own relative order within each group;
    "premium_maximizing_first" inverts that. Names outside both known sets
    (every other strategy) keep their original relative position,
    interleaved after the reordered ones - this function only ever
    reorders, never drops or adds a name."""
    if risk_tier_preference == "premium_maximizing_first":
        primary, secondary = _UNBOUNDED_RISK_STRATEGY_NAMES, _DEFINED_RISK_STRATEGY_NAMES
    else:
        primary, secondary = _DEFINED_RISK_STRATEGY_NAMES, _UNBOUNDED_RISK_STRATEGY_NAMES

    primary_names = [name for name in enabled_strategy_names if name in primary]
    secondary_names = [name for name in enabled_strategy_names if name in secondary]
    other_names = [name for name in enabled_strategy_names if name not in primary and name not in secondary]
    return primary_names + secondary_names + other_names


# ---------------------------------------------------------------------------
# Covered/protective/collar sizing (§6/§9.3/§9.6) - a THIRD sizing paradigm
# alongside vega-budget and margin: the option leg(s) are sized as a ratio
# against the EQUITY leg's currently-held quantity, never against a
# confidence-scaled vega/margin budget of their own. main.py never submits
# the bundled OptionStrategies.covered_call/etc. factory as an order (it
# would bundle an independent equity trade into the combo, fighting the
# standalone equity asset's own signal) - only this sizing decision's
# option leg(s) are ever placed, via the existing single-leg order
# machinery, see main.py's own corrected design note.
# ---------------------------------------------------------------------------


def build_covered_protective_position_sizing(
    strategy_name: str,
    confidence: float,
    available_chain: list[dict],
    equity_quantity: float,
    contract_multiplier: float = 100.0,
    target_delta_at_full_confidence: float = 0.30,
) -> OptionsMultiLegPositionDecision | None:
    """Sizes covered_call/covered_put/protective_call/protective_put/
    protective_collar's option leg(s) purely as floor(|equity_quantity| /
    contract_multiplier) - the number of contracts the CURRENTLY HELD
    equity position actually covers, never a vega/confidence-scaled
    target of its own (§9.3's floor-rounding: any fractional remainder is
    carried as plain uncovered equity, never partially hedged).

    equity_quantity must carry the correct SIGN for this strategy's
    covering_equity_side (positive/long for covered_call, protective_put,
    protective_collar; negative/short for covered_put, protective_call) -
    a mismatched sign (e.g. a short equity holding passed for
    covered_call, which needs a LONG holding) returns None rather than
    sizing against the wrong side of the book. Returns None for any
    strategy_name whose risk_tier isn't "covered_protective", for
    confidence <= 0, or when floor rounding or leg selection yields
    nothing - never raises."""
    spec = MULTI_LEG_STRATEGY_REGISTRY.get(strategy_name)
    if spec is None or spec.risk_tier != "covered_protective":
        return None

    confidence = max(0.0, min(float(confidence), 1.0))
    if confidence == 0.0 or contract_multiplier <= 0.0:
        return None
    if spec.covering_equity_side == "long" and equity_quantity <= 0.0:
        return None
    if spec.covering_equity_side == "short" and equity_quantity >= 0.0:
        return None

    contracts = int(math.floor(abs(equity_quantity) / contract_multiplier))
    if contracts <= 0:
        return None

    target_delta = target_delta_at_full_confidence * confidence
    legs_by_role = select_strategy_legs(strategy_name, available_chain, target_delta)
    if legs_by_role is None:
        return None

    return OptionsMultiLegPositionDecision(
        strategy_name=strategy_name,
        legs=_legs_tuple_from_roles(spec, legs_by_role),
        expiries=_expiries_tuple_from_roles(spec, legs_by_role),
        contracts=contracts,
        net_debit_or_credit=0.0,
        net_delta=0.0,
        net_vega=0.0,
        sizing_reason="equity_ratio_covered_protective_sizing",
    )


def option_auto_close_due(current_date, expiry_date, auto_close_days_before_expiry: int = 2) -> bool:
    """§9.5 - the narrow expiry-day safety net: True once `expiry_date` is
    within auto_close_days_before_expiry calendar days of current_date.
    Pure date comparison, mirroring risk/futures_risk.py::rollover_due()'s
    own pattern exactly (generalized from futures rollover to options
    expiry) - a diagnostic/trigger signal only, main.py's own force-
    liquidate call is what actually acts on it. Returns False when
    expiry_date is unparseable/unknown - never raises, matching every
    other pure predicate in this module's degrade-to-absent convention."""
    if current_date is None or expiry_date is None:
        return False
    return (expiry_date - current_date).days <= auto_close_days_before_expiry
