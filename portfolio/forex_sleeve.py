"""Forex sleeve (V5.7.0): a small, concentrated forex book with its own gross budget.

Why a sleeve: forex was switched off because, as members of the pooled 6+6 equity book, the pairs sat at ~2% of NAV and
IB's $2 minimum commission cost ~8-10 bps per fill (Problems.md #142). A sleeve ranks the pairs among THEMSELVES, holds
`k` longs and `k` shorts, gives each leg a budget big enough that the minimum is small, rebalances slowly and skips
resizes below a dollar threshold. `scripts/forex_sleeve_research.py` decides offline (R-FX) whether any setting pays; this
module is the pure, shared piece `main.py` and that script both call, so the two cannot disagree.

Pure, no I/O, no Lean imports.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from portfolio.book_construction import BookAllocation


def build_forex_sleeve_weights(
    allocations: Mapping[str, BookAllocation], gross_budget: float, max_weight_per_pair: float | None = None
) -> dict[str, float]:
    """Signed target weight (fraction of NAV) per selected pair: each leg gets `gross_budget / 2`, split evenly over its
    names, optionally capped per pair. A one-sided book (no shorts, no longs) gets {} - the sleeve is dollar-neutral by
    construction, never a directional currency bet. Non-finite or non-positive budget -> {}."""
    if not allocations or not math.isfinite(float(gross_budget)) or gross_budget <= 0.0:
        return {}
    longs = [symbol for symbol, allocation in allocations.items() if allocation.role == "long"]
    shorts = [symbol for symbol, allocation in allocations.items() if allocation.role == "short"]
    if not longs or not shorts:
        return {}
    cap = abs(float(max_weight_per_pair)) if max_weight_per_pair else None
    weights: dict[str, float] = {}
    for legs, sign in ((longs, 1.0), (shorts, -1.0)):
        per_name = (gross_budget / 2.0) / len(legs)
        if cap is not None:
            per_name = min(per_name, cap)
        weights.update({symbol: sign * per_name for symbol in legs})
    return weights


def forex_resize_below_minimum(delta_units: float, price: float, min_trade_usd: float) -> bool:
    """True when a resize of `delta_units` base-currency units at `price` is worth less than `min_trade_usd` in notional:
    paying IB's dollar minimum to move such a small amount costs more bps than the move is worth. `min_trade_usd <= 0`
    disables the check (False). Non-finite inputs -> True (do not trade on garbage)."""
    if min_trade_usd <= 0.0:
        return False
    try:
        notional = abs(float(delta_units)) * float(price)
    except (TypeError, ValueError):
        return True
    return (not math.isfinite(notional)) or notional < float(min_trade_usd)
