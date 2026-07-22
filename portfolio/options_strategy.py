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
