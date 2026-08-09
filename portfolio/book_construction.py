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
    # V5.1 Phase 0/1 (development/Problems.md - item 6 of the V5.1 roadmap):
    # both defaulted, so every existing positional construction and
    # asdict()/to_dict() consumer is unaffected. rank_head records which
    # blended signal (see portfolio/rank_signal.py) drove this allocation;
    # target_weight is filled in by callers that run the neutrality pass
    # (portfolio/book_neutrality.py) - None means "neutrality not applied,
    # read book_role_multiplier * the caller's own weight formula instead",
    # same convention as every other Optional payload field in this codebase.
    rank_head: str = "blend"
    target_weight: float | None = None

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


def _hysteresis_adjusted_selection(
    strength_ordered_candidates: list[str],
    eligible_ranks: dict[str, float],
    n: int,
    role: str,
    previous_allocations: dict[str, BookAllocation] | None,
    hysteresis_rank_margin: float,
) -> list[str]:
    """Sticky top/bottom-N selection (V5.1 Phase 0/1, development/Problems.md
    #43's rebalance-churn work continued): an incumbent (same `role` in
    `previous_allocations`) whose rank has fallen just outside the natural
    n-slot cutoff, but is still within `hysteresis_rank_margin` of it, keeps
    its slot rather than being dropped and immediately re-entered on the
    next small rank wobble - directly reduces turnover/fees, the whole point
    of this parameter (see book_neutrality.py's module docstring).

    `strength_ordered_candidates` must already be sorted BEST-FIRST for this
    leg - i.e. descending by predicted_rank_20d for role="long" (highest
    rank = most long-worthy), ascending by predicted_rank_20d for
    role="short" (lowest rank = most short-worthy). Normalizing both legs to
    "best first" here (rather than each leg carrying its own sign
    convention) is what keeps this function's cutoff/margin arithmetic
    identical for both roles - only the caller's ordering differs.

    Bounded at exactly `n` slots (never grows the book past what was
    requested). `previous_allocations` empty/None or `hysteresis_rank_margin
    <= 0` returns `strength_ordered_candidates[:n]` unchanged - BYTE-
    IDENTICAL to the pre-hysteresis plain top-n slice, so every existing
    caller/test that doesn't pass these new params is unaffected."""
    natural = strength_ordered_candidates[:n]
    if not previous_allocations or hysteresis_rank_margin <= 0.0 or n <= 0 or not natural:
        return natural

    cutoff_rank = eligible_ranks[natural[-1]]
    incumbents = [
        symbol
        for symbol in strength_ordered_candidates
        if symbol in previous_allocations and previous_allocations[symbol].role == role
    ]
    if role == "long":
        retained_incumbents = [
            symbol for symbol in incumbents if eligible_ranks[symbol] >= cutoff_rank - hysteresis_rank_margin
        ]
    else:
        retained_incumbents = [
            symbol for symbol in incumbents if eligible_ranks[symbol] <= cutoff_rank + hysteresis_rank_margin
        ]
    # Cap incumbents at n slots, keeping the strongest ones first (order
    # already inherited from strength_ordered_candidates) - an incumbent
    # list longer than n would otherwise grow the book past what was
    # requested, which hysteresis is meant to reduce churn within, not
    # override entirely.
    retained_incumbents = [
        symbol for symbol in strength_ordered_candidates if symbol in retained_incumbents
    ][:n]

    final = list(retained_incumbents)
    for symbol in strength_ordered_candidates:
        if len(final) >= n:
            break
        if symbol not in final:
            final.append(symbol)
    return final[:n]


def compute_confidence_spread(
    long_symbols: list[str],
    short_symbols: list[str],
    spread_ranks: dict[str, float],
    eligible_ranks: dict[str, float],
) -> float | None:
    """mean(long-side score) - mean(short-side score), the exact quantity
    _select_book_group()'s min_rank_confidence_spread gate compares
    against a floor. Public (not module-private) so a calibration tool can
    compute the identical statistic against historical data without
    re-deriving the formula - the two can then never disagree on what
    "spread" means for a given day's selection.

    `spread_ranks.get(symbol, eligible_ranks[symbol])` - a symbol missing
    from spread_ranks (e.g. a caller-supplied dict that doesn't cover
    every eligible symbol) falls back to its own eligible_ranks value
    rather than a KeyError, same defensive convention as every other
    optional-override lookup in this module.

    None if either list is empty - spread is undefined without both
    sides (mirrors the caller never reaching this check for a long-only
    book)."""
    if not long_symbols or not short_symbols:
        return None
    long_mean = sum(spread_ranks.get(symbol, eligible_ranks[symbol]) for symbol in long_symbols) / len(long_symbols)
    short_mean = sum(spread_ranks.get(symbol, eligible_ranks[symbol]) for symbol in short_symbols) / len(short_symbols)
    return long_mean - short_mean


def _select_book_group(
    eligible_ranks: dict[str, float],
    top_n: int,
    bottom_n: int,
    min_rank_confidence_spread: float,
    previous_allocations: dict[str, BookAllocation] | None = None,
    hysteresis_rank_margin: float = 0.0,
    spread_check_ranks: dict[str, float] | None = None,
) -> dict[str, BookAllocation]:
    """Core discrete top-N-long / bottom-N-short selection over an already-
    filtered `{symbol: predicted_rank_20d}` pool - shared by the pooled
    (build_rank_based_book()'s default) and per-asset-class
    (`per_asset_class_slots`) paths, so both apply identical selection
    logic to whatever pool they're given, just scoped differently. See
    build_rank_based_book()'s docstring for the full behavior contract.

    `previous_allocations`/`hysteresis_rank_margin` (V5.1 Phase 0/1,
    defaults None/0.0): optional sticky-selection pass over the natural
    top/bottom-N slice - see _hysteresis_adjusted_selection()'s docstring.
    Both defaults are a strict no-op, reproducing the pre-hysteresis
    selection exactly.

    `spread_check_ranks` (V5.1 Phase 1, development/Problems.md #77):
    optional separate `{symbol: raw_score}` dict used ONLY for the
    min_rank_confidence_spread comparison below - defaults to
    `eligible_ranks` itself when not given (byte-identical to before this
    parameter existed). Selection (WHICH symbols end up long/short) is
    unaffected either way, since sorting is invariant under a monotone
    transform - `eligible_ranks` may already be a per-bar cross-sectional
    percentile (portfolio/rank_signal.py::cross_sectional_rank_scores()),
    and a fixed top-N/bottom-N split out of that ALWAYS shows a large
    spread by construction (e.g. ~0.9 for top-6/bottom-6 of ~74 names),
    regardless of whether the underlying model had any real conviction
    that day - a normalized-scale spread check is statistically
    meaningless, it can never distinguish a genuinely dispersed day from a
    noisy one. Passing the pre-normalization raw scores here restores the
    gate's actual purpose: does the RAW output show real dispersion."""
    if len(eligible_ranks) < 2 or top_n <= 0:
        return {}
    spread_ranks = spread_check_ranks if spread_check_ranks is not None else eligible_ranks

    ranked_symbols = sorted(eligible_ranks, key=lambda symbol: eligible_ranks[symbol], reverse=True)
    natural_long_symbols = ranked_symbols[:top_n]
    remaining_symbols = [symbol for symbol in ranked_symbols if symbol not in natural_long_symbols]

    long_symbols = _hysteresis_adjusted_selection(
        ranked_symbols, eligible_ranks, top_n, "long", previous_allocations, hysteresis_rank_margin
    )
    # Short leg's "best first" ordering is ascending rank (lowest = most
    # short-worthy) - the mirror image of ranked_symbols' descending order.
    short_ordered_candidates = sorted(remaining_symbols, key=lambda symbol: eligible_ranks[symbol])
    short_symbols = _hysteresis_adjusted_selection(
        short_ordered_candidates, eligible_ranks, bottom_n, "short", previous_allocations, hysteresis_rank_margin
    )
    # Guard against a pathological case: hysteresis retaining a symbol on
    # both legs simultaneously (only possible if previous_allocations
    # itself was inconsistent - it never is, since a symbol can only ever
    # hold ONE role) - re-derive remaining_symbols/short candidates from the
    # ACTUAL long_symbols chosen above so the two legs never overlap.
    if long_symbols != natural_long_symbols:
        remaining_symbols = [symbol for symbol in ranked_symbols if symbol not in long_symbols]
        short_ordered_candidates = sorted(remaining_symbols, key=lambda symbol: eligible_ranks[symbol])
        short_symbols = _hysteresis_adjusted_selection(
            short_ordered_candidates, eligible_ranks, bottom_n, "short", previous_allocations, hysteresis_rank_margin
        )

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
        # compute_confidence_spread() (module-level, above) - shared with
        # the calibration tool that derives min_rank_confidence_spread
        # from real data, so the two can never disagree on what "spread"
        # means for a given selection.
        spread = compute_confidence_spread(long_symbols, short_symbols, spread_ranks, eligible_ranks)
        if spread is not None and spread < min_rank_confidence_spread:
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
    previous_allocations: dict[str, BookAllocation] | None = None,
    hysteresis_rank_margin: float = 0.0,
    spread_check_ranks: dict[str, float] | None = None,
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
    this symbol," not "book says flat."

    `previous_allocations`/`hysteresis_rank_margin` (V5.1 Phase 0/1,
    defaults None/0.0 - a strict no-op reproducing pre-hysteresis selection
    exactly): threaded straight through to _select_book_group() (pooled
    path) or applied identically within each asset class (per-asset-class
    path) - see _hysteresis_adjusted_selection()'s docstring for the actual
    sticky-selection behavior.

    `spread_check_ranks` (V5.1 Phase 1, development/Problems.md #77):
    optional `{symbol: raw_score}` override for the min_rank_confidence_spread
    check only - see _select_book_group()'s docstring for why this must be
    the PRE-normalization score when the caller's `book_candidates`
    predicted_rank_20d values are already a cross-sectional percentile.
    Defaults to None (falls back to book_candidates' own predicted_rank_20d,
    byte-identical to before this parameter existed)."""
    eligible = {
        symbol: candidate
        for symbol, candidate in book_candidates.items()
        if candidate.get("trading_eligible") and candidate.get("predicted_rank_20d") is not None
    }

    if per_asset_class_slots is None:
        eligible_ranks = {symbol: candidate["predicted_rank_20d"] for symbol, candidate in eligible.items()}
        return _select_book_group(
            eligible_ranks, top_n, bottom_n, min_rank_confidence_spread,
            previous_allocations, hysteresis_rank_margin, spread_check_ranks,
        )

    allocations: dict[str, BookAllocation] = {}
    for asset_class, (class_top_n, class_bottom_n) in per_asset_class_slots.items():
        class_eligible_ranks = {
            symbol: candidate["predicted_rank_20d"]
            for symbol, candidate in eligible.items()
            if candidate.get("asset_class") == asset_class
        }
        allocations.update(
            _select_book_group(
                class_eligible_ranks, class_top_n, class_bottom_n, min_rank_confidence_spread,
                previous_allocations, hysteresis_rank_margin, spread_check_ranks,
            )
        )
    return allocations


def should_rebalance_this_bar(
    bar_index: int,
    rebalance_every_bars: int,
    has_previous_allocation: bool,
    is_trading_day_bar: bool = True,
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

    `is_trading_day_bar` (V5.2.4, development/Problems.md #91) - default
    True, fully backward-compatible with every existing caller. False on a
    tick main.py has determined isn't the equity-session tick (e.g. an
    off-session crypto/forex-only Lean Slice, see main.py's own
    `is_equity_session_bar`) - never rebalances on such a tick, full stop,
    regardless of `bar_index`'s modulo or `has_previous_allocation`. This
    exists because `main.py`'s `bar_index` only advances on equity-session
    ticks post-V5.2.4 - without this explicit gate, several consecutive
    off-session ticks following a real rebalance-eligible bar would keep
    re-evaluating the SAME already-satisfied modulo condition and could
    re-trigger a rebalance that already happened.

    Returns True on bar_index 1, 1+N, 1+2N, ... (i.e. 0, N, 2N, ... in
    0-indexed bar terms) - False on every bar in between, where the caller
    should reuse its previously cached allocation and simply hold."""
    if not is_trading_day_bar:
        return False
    if not has_previous_allocation:
        return True
    return (bar_index - 1) % max(1, rebalance_every_bars) == 0


def should_exit_non_selected_book_symbol(
    book_is_active: bool,
    portfolio_book_enabled: bool,
    is_currently_invested: bool,
) -> bool:
    """V5.2.4 (development/Problems.md #91) - whether main.py's Pass 2
    should force-close a currently-invested, book-managed position because
    the book engaged this bar and didn't select it (the "rotation exit").

    Returns False whenever `book_is_active` is False (this bar's
    `book_allocations` came back empty) - matching `build_rank_based_book()`'s
    own documented contract just above: a disengaged book
    (`min_rank_confidence_spread` gate failure, or - pre-V5.2.4 - a thin/
    off-session-tick artifact) is "byte-identical to this module not
    existing at all", never a liquidation trigger. Before this function
    existed, main.py's own Pass 2 violated that documented contract -
    force-selling EVERY currently-invested book symbol whenever
    `book_allocations` didn't contain it, without distinguishing "the whole
    book disengaged today" from "this specific symbol got rotated out of a
    REAL, active book" (the only case that should ever force an exit).

    Callers pass `book_is_active=bool(book_allocations)` - `symbol_key not
    in book_allocations` (i.e. "this symbol specifically wasn't selected")
    is the caller's own responsibility to check separately, same as before;
    this function only answers "is a force-exit ever appropriate given the
    book's overall state this bar", not "for this particular symbol"."""
    return portfolio_book_enabled and book_is_active and is_currently_invested


def build_book_history_record(
    date_str: str,
    book_allocations: dict[str, BookAllocation],
    raw_scores_by_symbol: dict[str, float],
    target_weights_by_symbol: dict[str, float],
    sector_by_symbol: dict[str, str],
    rank_signal_policy: dict,
    full_universe_signals: dict[str, dict] | None = None,
) -> dict:
    """V5.2.2 (development/Problems.md) - a diagnostic snapshot of one
    rebalance bar's book, for `main.py`'s optional (config-gated, off by
    default, backtest-only) book-history log. Exists to make a real,
    ground-truth reconciliation possible between what a live/backtest run
    actually selected and what `evaluation/rank_book_simulator.py`'s
    offline simulator would select for the identical date - the tool
    this project needed after six other hypotheses for a large live-vs-
    offline Sharpe gap were tested and ruled out without finding the
    cause (see Problems.md #89-#90).

    Pure: no I/O, no `self`, never raises on well-formed inputs - every
    per-symbol field degrades via `.get(..., None)` rather than
    `KeyError`, since a symbol missing from `raw_scores_by_symbol` or
    `target_weights_by_symbol` (e.g. `target_weight` is never populated
    when `phase_v2.portfolio_book.neutrality.enabled` is False - see
    `BookAllocation.target_weight`'s own `None`-means-"not applicable"
    convention) is expected, not exceptional.

    `rank_signal_policy` (main.py's own `self._rank_signal_policy`,
    resolved once in `Initialize()`) is embedded INLINE in every record,
    not referenced externally - deliberately, so the log stays self-
    contained and correctly interpretable even if config or training
    metrics change between when a run produced this line and when a
    later reconciliation reads it back.

    `full_universe_signals` (V5.2.3, opt-in via
    `phase_v2.diagnostics.book_history.include_full_universe`): `None`
    (default) reproduces this function's exact V5.2.2 return shape - no
    `"universe"` key at all, so every existing caller/log consumer is
    unaffected. When given `{symbol: {"raw_rank_score", "feature_ready",
    "reason", "trading_eligible", "security_type"}}` (main.py's own Phase
    1a `signals` payload, one entry per symbol with a bar this tick,
    selected or not), adds a `"universe"` key with the same shape -
    closes the exact gap that made the V5.2.2 tool unable to see WHY a
    symbol was never selected (e.g. crypto/FX consistently absent from
    every live book - Problems.md #91): the V5.2.2 log only ever recorded
    `book_allocations`, i.e. symbols that already made the cut, with no
    way to see what score/readiness a NON-selected symbol had that day.
    Each per-symbol sub-dict degrades the same `.get(..., None)` way as
    every other field here - a caller-supplied dict missing a key never
    raises."""
    record = {
        "date": date_str,
        "rank_signal_policy": {
            "heads": dict(rank_signal_policy.get("heads", {})),
            "model_priority": list(rank_signal_policy.get("model_priority", [])),
            "demoted": list(rank_signal_policy.get("demoted", [])),
            "normalization": rank_signal_policy.get("normalization", "cross_sectional"),
        },
        "allocations": {
            symbol_key: {
                "role": allocation.role,
                "book_role_multiplier": allocation.book_role_multiplier,
                "predicted_rank_20d": allocation.predicted_rank_20d,
                "rank_head": allocation.rank_head,
                "raw_rank_score": raw_scores_by_symbol.get(symbol_key),
                "target_weight": target_weights_by_symbol.get(symbol_key),
                "sector": sector_by_symbol.get(symbol_key, "Unknown"),
            }
            for symbol_key, allocation in book_allocations.items()
        },
    }
    if full_universe_signals is not None:
        record["universe"] = {
            symbol_key: {
                "raw_rank_score": signal.get("raw_rank_score"),
                "feature_ready": signal.get("feature_ready"),
                "reason": signal.get("reason"),
                "trading_eligible": signal.get("trading_eligible"),
                "security_type": signal.get("security_type"),
            }
            for symbol_key, signal in full_universe_signals.items()
        }
    return record
