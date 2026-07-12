"""Stage-2 cross-sectional long/short book construction (Phase 3 of the
5/10 -> 9/10 roadmap) - the first use of the rank_20d signal that decides
*which direction* a symbol trades, not just how large an already-decided
trade should be.

Every existing sizing multiplier in this codebase (topology_sizing_multiplier(),
rank_sizing_multiplier() in risk/position_sizing.py) is deliberately
bounded and direction-PRESERVING: it can only shrink or (for rank_sizing_multiplier())
modestly scale an already-decided position, never flip its sign. This
module is the one deliberate departure from that convention -
build_rank_based_book()'s `book_role_multiplier` (+1.0 long, -1.0 short)
SETS direction for the symbols it selects, because that is the entire
point of a cross-sectional book (rank the universe, go long the top,
short the bottom) - short-selling doesn't exist anywhere else in this
codebase today (`phase5.backtest.strategy_mode: "long_flat"` is the
existing ceiling everywhere else).

Deliberately its own package, not folded into risk/ or analyzer/:
- Not risk/position_sizing.py: book construction needs the WHOLE-universe
  view (every symbol's rank_20d for this bar, seen at once) that
  position_sizing.py's pure single-symbol functions structurally don't
  have - see main.py::on_data()'s two-pass restructuring, which collects
  every symbol's candidate data in Pass 1 before this module ever runs.
- Not analyzer/market_analyzer.py: that module's per-symbol trade/simulate/
  observe/reduce_risk categorization stays deterministic and per-symbol by
  design (see analyzer/README.md) - a book-selected symbol still passes
  through that exact same categorization afterward, unchanged; this module
  only ever decides the role (long/short) BEFORE that, never bypasses it.

Ships config-gated OFF by default (phase_v2.portfolio_book.enabled: false)
- same precedent as rank_sizing_enabled - since this is a bigger structural
  change (direction-setting, not just direction-preserving) than any prior
  rank_20d integration, and the same non-overlapping-date-subsample caveat
  documented in risk/position_sizing.py::rank_sizing_multiplier() applies
  here too.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BookAllocation:
    role: str
    book_role_multiplier: float
    predicted_rank_20d: float
    book_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_rank_based_book(
    book_candidates: dict[str, dict],
    top_n: int,
    bottom_n: int,
    min_rank_confidence_spread: float = 0.0,
) -> dict[str, BookAllocation]:
    """Discrete top-N-long / bottom-N-short book construction from each
    symbol's predicted_rank_20d for this bar. Continuous rank-weighted
    sizing (rather than a hard top/bottom-N cutoff) is a documented future
    extension, not built here - the discrete version is simpler to reason
    about and test first.

    `book_candidates` is `{symbol: {"predicted_rank_20d": float | None,
    "trading_eligible": bool, ...}}` - one entry per symbol Pass 1 of
    main.py::on_data() collected this bar (extra keys like
    probability_up/confidence are ignored here, kept only so callers can
    pass the same dict they already built for other purposes). A symbol is
    eligible for book selection only if `trading_eligible` is true (this is
    exactly how phase9.asset_quality's observation-only assets get excluded
    - main.py already computes this per-symbol flag identically for every
    other decision) and `predicted_rank_20d` is not None (model
    unavailable/still warming up that bar).

    Requires at least one eligible symbol on EACH side (long and short) to
    form a book at all - a one-sided book (all longs, no shorts, or vice
    versa) isn't attempted in this pass; returns {} in that case, same as
    every other degenerate-input case below. `top_n`/`bottom_n` exceeding
    the number of eligible symbols degrades gracefully to however many are
    actually available (never raises) - same "pad/truncate rather than
    error on a thin universe" convention as topology/market_topology.py's
    rank_correlated_peers().

    `min_rank_confidence_spread` is a floor on (mean long-side rank - mean
    short-side rank) before the book engages at all - on a day where the
    universe's predicted ranks are all clustered near 0.5 (no real
    dispersion), forcing a long/short split would be noise, not signal;
    the book disengages entirely (returns {}) rather than trading a
    meaningless split. Every symbol then falls through to whatever
    non-book decision main.py's Pass 2 would have made anyway - byte-
    identical to this module not existing at all, the same "missing/
    degraded signal never changes trading behavior" contract this
    codebase's other optional overlays already guarantee.

    Returns a dict covering ONLY the symbols the book actively wants long
    or short (not a "flat" entry for every candidate) - callers should
    treat "symbol absent from the returned dict" as "book has no view on
    this symbol," not "book says flat.\""""
    eligible_ranks = {
        symbol: candidate["predicted_rank_20d"]
        for symbol, candidate in book_candidates.items()
        if candidate.get("trading_eligible") and candidate.get("predicted_rank_20d") is not None
    }
    if len(eligible_ranks) < 2 or top_n <= 0 or bottom_n <= 0:
        return {}

    ranked_symbols = sorted(eligible_ranks, key=lambda symbol: eligible_ranks[symbol], reverse=True)
    long_symbols = ranked_symbols[:top_n]
    remaining_symbols = [symbol for symbol in ranked_symbols if symbol not in long_symbols]
    short_symbols = remaining_symbols[-bottom_n:] if bottom_n > 0 else []

    if not long_symbols or not short_symbols:
        return {}

    long_mean_rank = sum(eligible_ranks[symbol] for symbol in long_symbols) / len(long_symbols)
    short_mean_rank = sum(eligible_ranks[symbol] for symbol in short_symbols) / len(short_symbols)
    if (long_mean_rank - short_mean_rank) < min_rank_confidence_spread:
        return {}

    allocations: dict[str, BookAllocation] = {}
    for symbol in long_symbols:
        allocations[symbol] = BookAllocation(
            role="long",
            book_role_multiplier=1.0,
            predicted_rank_20d=eligible_ranks[symbol],
            book_reason="rank_based_book_long",
        )
    for symbol in short_symbols:
        allocations[symbol] = BookAllocation(
            role="short",
            book_role_multiplier=-1.0,
            predicted_rank_20d=eligible_ranks[symbol],
            book_reason="rank_based_book_short",
        )
    return allocations
