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


def normalize_per_asset_class_slots(
    raw: dict[str, object] | None,
) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """Validates and coerces a raw `phase_v2.portfolio_book.per_asset_class_slots`
    config dict into build_rank_based_book()'s expected shape.
    `build_rank_based_book()` unpacks each value unconditionally
    (`for asset_class, (top_n, bottom_n) in per_asset_class_slots.items()`),
    so a malformed entry (wrong length, wrong type) would otherwise hard-
    crash every bar instead of degrading gracefully like every other
    optional config-driven feature in this codebase - development/
    Problems.md. Each value must be a 2-element `[top_n, bottom_n]`
    list/tuple; anything else is skipped, not fatal.

    Returns `(valid_slots, skipped_asset_classes)` - pure and no-logging
    by design (so it stays independently testable); callers with access
    to a logger (main.py's `self.Debug()`) should report the skipped
    list themselves."""
    valid: dict[str, tuple[int, int]] = {}
    skipped: list[str] = []
    for asset_class, slots in (raw or {}).items():
        if isinstance(slots, (list, tuple)) and len(slots) == 2:
            valid[asset_class] = tuple(slots)
        else:
            skipped.append(asset_class)
    return valid, skipped


def _select_book_group(
    eligible_ranks: dict[str, float],
    top_n: int,
    bottom_n: int,
    min_rank_confidence_spread: float,
) -> dict[str, BookAllocation]:
    """Core discrete top-N-long / bottom-N-short selection over an already-
    filtered `{symbol: predicted_rank_20d}` pool - shared by the pooled
    (build_rank_based_book()'s default) and per-asset-class
    (`per_asset_class_slots`) paths, so both apply identical selection
    logic to whatever pool they're given, just scoped differently. See
    build_rank_based_book()'s docstring for the full behavior contract."""
    if len(eligible_ranks) < 2 or top_n <= 0:
        return {}

    ranked_symbols = sorted(eligible_ranks, key=lambda symbol: eligible_ranks[symbol], reverse=True)
    long_symbols = ranked_symbols[:top_n]
    remaining_symbols = [symbol for symbol in ranked_symbols if symbol not in long_symbols]
    short_symbols = remaining_symbols[-bottom_n:] if bottom_n > 0 else []

    if not long_symbols:
        return {}
    # bottom_n > 0 means a short side was actually requested - if nothing
    # was left over to fill it (long_n consumed the whole eligible pool),
    # stay strict and refuse the whole book, matching this function's
    # original behavior. bottom_n == 0 (main.py passes this for
    # phase5.backtest.strategy_mode == "long_flat" - see main.py's own
    # strategy_mode enforcement) is a deliberate long-only request, not a
    # degenerate case - falls through to the long-only book below.
    if bottom_n > 0 and not short_symbols:
        return {}

    if short_symbols:
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


def build_rank_based_book(
    book_candidates: dict[str, dict],
    top_n: int,
    bottom_n: int,
    min_rank_confidence_spread: float = 0.0,
    per_asset_class_slots: dict[str, tuple[int, int]] | None = None,
) -> dict[str, BookAllocation]:
    """Discrete top-N-long / bottom-N-short book construction from each
    symbol's predicted_rank_20d for this bar. Continuous rank-weighted
    sizing (rather than a hard top/bottom-N cutoff) is a documented future
    extension, not built here - the discrete version is simpler to reason
    about and test first.

    `book_candidates` is `{symbol: {"predicted_rank_20d": float | None,
    "trading_eligible": bool, "asset_class": str | None, ...}}` - one entry
    per symbol Pass 1 of main.py::on_data() collected this bar (extra keys
    like probability_up/confidence are ignored here, kept only so callers
    can pass the same dict they already built for other purposes). A
    symbol is eligible for book selection only if `trading_eligible` is
    true (this is exactly how phase9.asset_quality's observation-only
    assets get excluded - main.py already computes this per-symbol flag
    identically for every other decision) and `predicted_rank_20d` is not
    None (model unavailable/still warming up that bar).

    `bottom_n == 0` requests a deliberate long-only book (no shorts at all) -
    used by main.py to honor `phase5.backtest.strategy_mode == "long_flat"`
    while still getting rank-driven entry/rotation on the long side. Any
    `bottom_n > 0` still requires at least one eligible symbol on EACH side
    to form a book at all - a one-sided book isn't attempted when a short
    side was actually requested but nothing was available for it; returns
    {} in that case, same as every other degenerate-input case below.
    `top_n`/`bottom_n` (or each
    asset class's own pair, see `per_asset_class_slots` below) exceeding
    the number of eligible symbols degrades gracefully to however many are
    actually available (never raises) - same "pad/truncate rather than
    error on a thin universe" convention as topology/market_topology.py's
    rank_correlated_peers().

    `min_rank_confidence_spread` is a floor on (mean long-side rank - mean
    short-side rank) before a book (or, with `per_asset_class_slots`, each
    individual asset class's own book) engages at all - on a day where the
    ranked pool's predicted ranks are all clustered near 0.5 (no real
    dispersion), forcing a long/short split would be noise, not signal;
    the book disengages entirely (returns {} for that pool) rather than
    trading a meaningless split. Every symbol then falls through to
    whatever non-book decision main.py's Pass 2 would have made anyway -
    byte-identical to this module not existing at all, the same "missing/
    degraded signal never changes trading behavior" contract this
    codebase's other optional overlays already guarantee.

    `per_asset_class_slots` (default None - pooled ranking, this function's
    original and only behavior before this parameter existed) is an
    optional `{asset_class: (top_n, bottom_n)}` map. When provided, `top_n`/
    `bottom_n` are ignored and every eligible symbol is ranked *within its
    own asset_class group only* instead of one combined-universe pool - so
    e.g. equities and crypto each get their own long/short slot budget
    instead of one side potentially being filled entirely by a single
    dominant asset class. A symbol whose `asset_class` isn't a key in
    `per_asset_class_slots` is excluded from book selection entirely (not
    silently folded into some catch-all group) - same explicit-opt-in
    convention risk/asset_class_router.py already uses for future/option.
    `min_rank_confidence_spread` is applied independently per asset class
    (each class's own long/short spread must individually clear the bar -
    pooling the check across classes with potentially very different rank
    distributions would be misleading). Results from every class are
    unioned into one returned dict, same shape as the pooled path.

    Returns a dict covering ONLY the symbols the book actively wants long
    or short (not a "flat" entry for every candidate) - callers should
    treat "symbol absent from the returned dict" as "book has no view on
    this symbol," not "book says flat.\""""
    eligible = {
        symbol: candidate
        for symbol, candidate in book_candidates.items()
        if candidate.get("trading_eligible") and candidate.get("predicted_rank_20d") is not None
    }

    if per_asset_class_slots is None:
        eligible_ranks = {symbol: candidate["predicted_rank_20d"] for symbol, candidate in eligible.items()}
        return _select_book_group(eligible_ranks, top_n, bottom_n, min_rank_confidence_spread)

    allocations: dict[str, BookAllocation] = {}
    for asset_class, (class_top_n, class_bottom_n) in per_asset_class_slots.items():
        class_eligible_ranks = {
            symbol: candidate["predicted_rank_20d"]
            for symbol, candidate in eligible.items()
            if candidate.get("asset_class") == asset_class
        }
        allocations.update(
            _select_book_group(class_eligible_ranks, class_top_n, class_bottom_n, min_rank_confidence_spread)
        )
    return allocations


def should_rebalance_this_bar(
    bar_index: int,
    rebalance_every_bars: int,
    has_previous_allocation: bool,
) -> bool:
    """Stage 2 of the rank-pivot roadmap (development/Problems.md#43): the
    book previously re-ranked and re-formed on EVERY bar, churning positions
    far faster than rank_20d's actual ~20-trading-day horizon can support
    (653 orders/~2yr, no edge left after costs). This is a pure, main.py-
    independent extraction of main.py::on_data()'s rebalance-gating decision
    so it's unit-testable without a running Lean/QCAlgorithm instance (this
    module has no Lean import, main.py does).

    `bar_index` is main.py's 1-indexed `self.bar_index` (incremented to 1 on
    the very first `on_data()` call, before any bar has been processed).
    `rebalance_every_bars` is `phase_v2.portfolio_book.rebalance_every_bars`
    (1 reproduces the previous every-bar-rebalance behavior exactly, since
    `(n - 1) % 1 == 0` for every n). `has_previous_allocation` should be
    False only on a genuinely fresh run (no cached book yet) - it forces a
    rebalance regardless of the modulo so the book is never left empty.

    Returns True on bar_index 1, 1+N, 1+2N, ... (i.e. 0, N, 2N, ... in
    0-indexed bar terms) - False on every bar in between, where the caller
    should reuse its previously cached allocation and simply hold."""
    if not has_previous_allocation:
        return True
    return (bar_index - 1) % max(1, rebalance_every_bars) == 0
