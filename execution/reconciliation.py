"""V5.1 Phase 6 (production safety): position reconciliation - compares
the book's INTENDED per-symbol weights against what the broker (Lean's
own `self.Portfolio`, or an IB snapshot once Problems.md #72 clears)
actually holds, and classifies every discrepancy.

Pure, Lean-free - no QCAlgorithm/self.Portfolio dependency here at all, so
this is fully unit-testable with plain dicts (same "compute the math in a
pure module, let the live caller supply real data" split every other
risk/execution module in this codebase already follows) and directly
reusable against a future IB portfolio snapshot with zero changes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ReconciliationReport:
    matched: list[str] = field(default_factory=list)
    drifted: list[dict] = field(default_factory=list)
    orphan_broker: list[dict] = field(default_factory=list)
    missing_broker: list[dict] = field(default_factory=list)
    max_abs_weight_drift: float = 0.0
    breach: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def reconcile_positions(
    expected_by_symbol: dict[str, float],
    actual_by_symbol: dict[str, float],
    *,
    weight_tolerance: float,
    value_tolerance_usd: float,
    portfolio_value: float,
    max_tolerated_drift: float | None = None,
) -> ReconciliationReport:
    """Classifies every symbol appearing in EITHER dict:
      - "matched": both expected and actual are present and within
        weight_tolerance (as a fraction of portfolio weight) AND within
        value_tolerance_usd (the dollar-value equivalent of that weight
        difference) - both must hold, since a large-value portfolio can
        have a tiny weight_tolerance breach that is still a huge dollar
        drift, and a small-value portfolio can have a huge weight_tolerance
        breach that is a trivial dollar amount.
      - "drifted": both present, but outside tolerance - full per-symbol
        delta detail (expected_weight, actual_weight, delta_weight,
        delta_usd).
      - "orphan_broker": held by the broker but not in the expected book at
        all (expected_weight treated as 0.0) - e.g. a position main.py's
        book no longer wants but the broker never closed.
      - "missing_broker": expected by the book but the broker holds nothing
        for it (actual_weight treated as 0.0) - e.g. an order that never
        filled.

    max_abs_weight_drift is the single largest |delta_weight| across every
    NON-matched symbol (drifted + orphan_broker + missing_broker combined -
    a symbol classified "matched" is, by construction, already within both
    tolerances, so including it could only ever pull the max down toward a
    value the genuine drifts already exceed - excluding it keeps this
    field's value exactly matching what its name and this docstring claim).
    breach is that value compared against max_tolerated_drift (typically
    phase_v2.reconciliation.max_tolerated_drift) - the one field a caller
    checks to decide whether this reconciliation should trip the kill
    switch (risk/kill_switch.py's "reconciliation_breach" trigger) without
    re-deriving the comparison itself. max_tolerated_drift=None (the
    default) always reports breach=False - an unconfigured caller gets a
    strict no-op, matching every other fail-open contract in this codebase.

    Tolerance is checked BEFORE presence: a symbol held/expected only on
    one side but within weight_tolerance/value_tolerance_usd of the other
    side's implicit 0.0 (a dust position - a fractional share leftover, a
    rounding remainder) is "matched", never "orphan_broker"/"missing_broker".
    Without this, every dust amount was a permanent, unfixable "orphan" no
    matter how negligible, even though it could never move max_abs_weight_drift
    past a real drift either - pure report-quality noise.

    Pure dict-in/dict-out - result does not depend on either dict's
    insertion order (both are iterated via a sorted union of keys). Empty
    inputs (both dicts empty) return an all-empty, non-breaching report,
    never raise."""
    all_symbols = sorted(set(expected_by_symbol) | set(actual_by_symbol))

    matched: list[str] = []
    drifted: list[dict] = []
    orphan_broker: list[dict] = []
    missing_broker: list[dict] = []
    max_abs_weight_drift = 0.0

    for symbol in all_symbols:
        expected_weight = float(expected_by_symbol.get(symbol, 0.0))
        actual_weight = float(actual_by_symbol.get(symbol, 0.0))
        delta_weight = actual_weight - expected_weight
        delta_usd = delta_weight * portfolio_value

        within_tolerance = abs(delta_weight) <= weight_tolerance and abs(delta_usd) <= value_tolerance_usd

        if within_tolerance:
            matched.append(symbol)
        elif symbol not in expected_by_symbol:
            max_abs_weight_drift = max(max_abs_weight_drift, abs(delta_weight))
            orphan_broker.append(
                {"symbol": symbol, "expected_weight": 0.0, "actual_weight": actual_weight,
                 "delta_weight": delta_weight, "delta_usd": delta_usd}
            )
        elif symbol not in actual_by_symbol:
            max_abs_weight_drift = max(max_abs_weight_drift, abs(delta_weight))
            missing_broker.append(
                {"symbol": symbol, "expected_weight": expected_weight, "actual_weight": 0.0,
                 "delta_weight": delta_weight, "delta_usd": delta_usd}
            )
        else:
            max_abs_weight_drift = max(max_abs_weight_drift, abs(delta_weight))
            drifted.append(
                {"symbol": symbol, "expected_weight": expected_weight, "actual_weight": actual_weight,
                 "delta_weight": delta_weight, "delta_usd": delta_usd}
            )

    breach = max_tolerated_drift is not None and max_abs_weight_drift > max_tolerated_drift

    return ReconciliationReport(
        matched=matched,
        drifted=drifted,
        orphan_broker=orphan_broker,
        missing_broker=missing_broker,
        max_abs_weight_drift=max_abs_weight_drift,
        breach=breach,
    )
