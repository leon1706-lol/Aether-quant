"""Forex sleeve (V5.7.0): a small, concentrated forex book with its own gross budget.

Why a sleeve: forex was switched off because, as members of the pooled 6+6 equity book, the pairs sat at ~2% of NAV and
IB's $2 minimum commission cost ~8-10 bps per fill (Problems.md #142). A sleeve ranks the pairs among THEMSELVES, holds
`k` longs and `k` shorts, gives each leg a budget big enough that the minimum is small, rebalances slowly and skips
resizes below a dollar threshold. Since V5.8.0 the weights come from the generic `portfolio/class_sleeve.py` (bonds use
the same structure); these names stay as the forex entry points `main.py` and the research scripts import.

Pure, no I/O, no Lean imports.
"""

from __future__ import annotations

from collections.abc import Mapping

from portfolio.book_construction import BookAllocation
from portfolio.class_sleeve import build_class_sleeve_weights, resize_below_minimum


def build_forex_sleeve_weights(
    allocations: Mapping[str, BookAllocation], gross_budget: float, max_weight_per_pair: float | None = None
) -> dict[str, float]:
    """Signed target weight (fraction of NAV) per selected pair: each leg gets `gross_budget / 2`, split evenly over its
    names, optionally capped per pair. A one-sided book (no shorts, no longs) gets {} - the sleeve is dollar-neutral by
    construction, never a directional currency bet. Non-finite or non-positive budget -> {}."""
    return build_class_sleeve_weights(allocations, gross_budget, max_weight_per_pair)


def forex_resize_below_minimum(delta_units: float, price: float, min_trade_usd: float) -> bool:
    """True when a resize of `delta_units` base-currency units at `price` is worth less than `min_trade_usd` in notional:
    paying IB's dollar minimum to move such a small amount costs more bps than the move is worth. `min_trade_usd <= 0`
    disables the check (False). Non-finite inputs -> True (do not trade on garbage)."""
    return resize_below_minimum(delta_units, price, min_trade_usd)
