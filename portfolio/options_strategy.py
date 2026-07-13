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

from dataclasses import asdict, dataclass


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

    def to_dict(self) -> dict:
        return asdict(self)


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
        sizing_reason="delta_targeted_vega_budgeted_sizing",
    )
