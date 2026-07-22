# portfolio

Owns Stage-2 cross-sectional long/short book construction (Phase 3 of the
5/10 -> 9/10 roadmap) — the first use of the `rank_20d` signal that decides
*which direction* a symbol trades, not just how large an already-decided
trade should be.

## Why this is its own package, not `risk/` or `analyzer/`

Every prior integration of `rank_20d` into a trading decision (see
`risk/README.md`'s "Cross-sectional rank_20d → position sizing" section)
was deliberately **direction-preserving**: `rank_sizing_multiplier()` can
only scale an already-decided position's magnitude, never flip its sign.
Book construction is structurally different — it needs to decide, from
scratch, *which direction* each symbol trades, based on how its predicted
rank compares to the rest of the universe that bar. That doesn't fit
either existing home:

- **Not `risk/position_sizing.py`**: that module's functions are pure,
  single-symbol calculations by design — they have no way to see every
  other symbol's `rank_20d` for the same bar, which book construction
  fundamentally needs (rank the whole universe, then pick a top-N/bottom-N
  split).
- **Not `analyzer/market_analyzer.py`**: that module's per-symbol
  `trade`/`simulate`/`observe`/`reduce_risk` categorization stays
  deterministic and per-symbol by design (see `analyzer/README.md`). A
  book-selected symbol still passes through that exact same
  categorization afterward, unchanged — this package only decides the
  symbol's *role* (long/short) before that point, it never bypasses the
  analyzer's safety tiers.

## `book_construction.py::build_rank_based_book()`

Pure function, no Lean/torch dependency (same convention as
`risk/position_sizing.py`). Takes `book_candidates: dict[symbol, {...}]` —
one entry per symbol with `predicted_rank_20d` and `trading_eligible`,
collected by `main.py::on_data()`'s Pass 1 (see below) — and `top_n`/
`bottom_n`/`min_rank_confidence_spread`, returning a `dict[symbol,
BookAllocation]` covering **only** the symbols the book actively wants
long or short. A symbol absent from the returned dict means "the book has
no view on this symbol," not "the book says flat" — those symbols simply
fall through to whatever the existing (non-book) signal pipeline would
have decided anyway.

- **Discrete top-N/bottom-N selection**, not continuous rank-weighting —
  shipped first because it's simpler to reason about and test.
  Rank-weighted continuous sizing is a documented future extension, not
  built here.
- **`min_rank_confidence_spread`**: a floor on `(mean long-side rank -
  mean short-side rank)` before the book engages at all. On a day where
  the universe's predicted ranks are all clustered near 0.5 (no real
  cross-sectional dispersion), forcing a long/short split would be noise,
  not signal — the book disengages entirely (`{}`) rather than trading a
  meaningless split.
- **Observation-only exclusion is automatic**: a candidate is eligible
  only if `trading_eligible` is true, exactly the same
  `phase9.asset_quality`-gated flag every other trading decision already
  respects — observation-only assets can never be book candidates.
- **Graceful degradation**: `top_n`/`bottom_n` exceeding the number of
  eligible candidates degrades to however many are actually available
  (never raises), and a book that can't form both a long AND a short side
  returns `{}` rather than a one-sided book (not attempted in this pass).

## The one deliberate departure from the "never flips direction" convention

`BookAllocation.book_role_multiplier` (+1.0 long, -1.0 short) **sets**
direction, unlike every existing sizing multiplier
(`topology_sizing_multiplier()`, `rank_sizing_multiplier()`), which only
ever scale magnitude. This is intentional and necessary — a cross-sectional
book's entire purpose is deciding direction from relative rank, not
confirming a direction some other signal already picked.

Short-selling did not exist anywhere in this codebase before this phase
(`phase5.backtest.strategy_mode: "long_flat"` was the ceiling everywhere
else). Making it real required two small, additive changes outside this
package:

- `main.py::_apply_signal()` gained a new `signal_name == "short"` branch
  (parallel to the existing `"buy"`/`"sell"` branches), calling
  `self.SetHoldings(symbol, target_weight)` with a genuinely negative
  `target_weight` — Lean's `SetHoldings()` already opens a short position
  for a negative percentage; the branch that actually *did* this never
  existed before (the existing `"sell"` branch only ever liquidates to
  flat, ignoring `target_weight`'s sign entirely). A new
  `max_short_exposure` cap (`phase9.portfolio.max_short_exposure`, default
  `0.30`) bounds it, since nothing bounded short exposure before.
  `experience/simulated_portfolio.py::enter_long()` (despite its name)
  was already sign-generic — `simulate_fill()`'s `notional = target_weight
  * equity` math works unchanged for a negative weight — so the
  observation-mode path needed no new method, just reuse.
- `analyzer/market_analyzer.py::build_market_analysis_decision()`'s six
  `signal_name in {"buy", "sell"}` safety-tier checks (trade-lock,
  risk-off, elevated topology, liquidity block/thin-market, confidence
  threshold) now also include `"short"` — a real gap caught during
  implementation: without this, a book-selected short would have silently
  bypassed every one of those safety tiers, since none of them recognized
  the new signal name. A book-selected symbol now passes through the
  *exact same* deterministic categorization as any other signal, never
  bypassing it — see that function's own updated docstring note.

## `main.py::on_data()`'s two-pass restructuring

A cross-sectional book needs every symbol's `rank_20d` prediction for the
current bar before it can decide *any* single symbol's role — that
information doesn't exist until every symbol's inference has run once.
`on_data()` was restructured into two passes to make this possible:

- **Pass 1**: the existing per-symbol feature-build + inference chain
  (baseline/sequence/experts/multitask/gating), through the existing
  `predicted_rank_20d` resolution (see `risk/README.md`) and the
  pre-book `_derive_signal()` call — collected into `book_candidates` and
  a per-symbol state dict, not acted on yet.
- **Between passes**: `build_rank_based_book()` runs once, given every
  symbol's `book_candidates` entry for this bar.
- **Pass 2**: the existing sizing/liquidity/analyzer/order-application
  chain, unchanged — except a book-selected symbol's `signal_name`/
  `base_target_weight` are overridden (direction set by
  `book_role_multiplier`, magnitude derived from how extreme the
  symbol's own predicted rank is: `confidence = |rank - 0.5| * 2`) before
  entering that same existing pipeline.

**Byte-identical when disabled**: `signals[symbol]` dict objects are
inserted during Pass 1, in `self.symbols` order, for every symbol with a
bar — Pass 2 only ever `.update()`s those same dict objects in place,
never re-inserts. With `phase_v2.portfolio_book.enabled=false` (the
default), `build_rank_based_book()` is never called, `book_allocations` is
always `{}`, and every symbol's Pass 2 behavior — including exposure-cap
consumption *order* across symbols, since `pass1_state` preserves
`self.symbols` iteration order — is identical to the single-pass loop that
existed before this phase.

## Config (`phase_v2.portfolio_book`)

Off by default, same precedent as `rank_sizing_enabled` — this is a bigger
structural change (direction-setting, not direction-preserving) than any
prior `rank_20d` integration, and inherits the same non-overlapping-date
validation caveat documented in `risk/README.md`.

- `enabled` (default `false`)
- `top_n` / `bottom_n` (default `3` / `3`)
- `min_rank_confidence_spread` (default `0.2`)
- `per_asset_class_slots` (default absent — pooled combined-universe
  ranking via `top_n`/`bottom_n` above; see "Multi-asset-class book
  selection" below for the per-class alternative)

Also see `phase9.portfolio.max_short_exposure` (default `0.30`) — the
dedicated short-exposure cap, independent of this block's own on/off
switch, since it's a portfolio-wide risk ceiling that should stay in
effect regardless.

## Multi-asset-class book selection

`build_rank_based_book()` originally needed **zero signature change** to
select across a mixed equity/crypto/bond/future/option universe — it
operates purely on `predicted_rank_20d`/`trading_eligible` per symbol.
Once the model's widened, unified feature vector
(`train.py::add_asset_class_context_features()`, see `risk/README.md`)
produces `rank_20d` for bond/future/option symbols too, they become
automatically eligible book candidates alongside equities and crypto —
this is the direct mechanism satisfying "the model's final decision maker
should consider all enabled asset classes together as one coherent
portfolio." Ships with one combined-universe top-N/bottom-N ranking by
default (`per_asset_class_slots` absent) — simpler, and matches "one
coherent portfolio" directly.

`per_asset_class_slots` (development/Problems.md#29) is the optional
alternative: a `{asset_class: (top_n, bottom_n)}` map giving each asset
class its own independent long/short slot budget instead of one pooled
ranking, so e.g. a handful of high-conviction crypto symbols can't fill
every book slot and crowd out equities entirely. Each class is ranked and
`min_rank_confidence_spread`-gated independently; a class not listed in
the map is excluded from book selection entirely (explicit opt-in, same
convention `risk/asset_class_router.py` uses for future/option). Both
paths share the same core selection logic
(`book_construction.py::_select_book_group()`) so behavior is identical
per group either way — only the pooling boundary changes.

Per-asset-class exposure caps (`phase9.portfolio.max_bond_exposure`/
`max_futures_exposure`/`max_options_exposure`, mirroring the existing
`max_equity_exposure`/`max_crypto_exposure`) still apply AFTER book
selection, in `main.py::_apply_signal()`'s existing per-symbol cap check —
a book-selected bond/future/option symbol is not exempt from its class's
exposure ceiling just because the book picked it.

## `options_strategy.py` — greeks-sized options positions (single-leg default, optional 2-leg vertical spread)

A second, narrower "sets direction/instrument, not just magnitude"
decision layer, alongside `book_construction.py` above but for a different
reason: it lives here (not `risk/`) because sizing an options position
needs the whole option chain, not a scalar signal, and it lives here (not
`features/`) because it's a decision layer, not a feature. See
`risk/README.md`'s "Multi-asset-class risk dispatch" section for the full
design — `build_options_position_sizing()` translates the model's existing
direction+confidence prediction into a target delta, selects the nearest-
delta contract from the chain, and sizes contract count by a vega budget.
Single-leg is the default. Order placement against the selected contract
is real (`main.py::_apply_option_order()` resolves a live tradable
contract `Symbol` from Lean's `slice.OptionChains` and places a real
`LimitOrder()`/`MarketOrder()`) — this was closed in an earlier pass; see
`development/Problems.md` #34. A 2-leg vertical call/put spread is
available via `phase_v2.options_risk.spread_strategy: "vertical"`
(`select_vertical_spread_legs()`/`build_vertical_spread_position_sizing()`
below `build_options_position_sizing()` in this same file) — automatic
selection of anything beyond a vertical (straddles/strangles/iron
condors/butterflies) remains an explicit non-goal
(`development/Problems.md` #29/#38).

**Adding to an already-open position (V4.3.0)**: `main.py::_apply_option_order()`/
`_apply_option_spread_order()` compare this bar's freshly-selected
contract/legs against whatever's currently held for the chain symbol. A
match scales the position (`phase_v2.functionality.position_scaling.enabled`,
default off) — **both directions since V4.4**, not just up. See
`risk/README.md`'s "Allow adding to an existing position" section and
`development/Problems.md` #57 for the full design.

**Architecturally-sound options, multi-position book (V4.4)**: a
mismatch (the confidence-scaled target delta selected a different
strike/expiry than what's held) no longer means only "rotate or freeze."
Three additive pure functions/behaviors close the gap:

- `build_options_position_sizing_for_contract(held_contract, portfolio_value,
  max_vega_budget_pct_of_equity)` and `build_vertical_spread_position_sizing_for_legs(
  held_long, held_short, portfolio_value, max_vega_budget_pct_of_equity)` —
  new, additive siblings of `build_options_position_sizing()`/
  `build_vertical_spread_position_sizing()` above. Instead of re-running
  `select_single_leg_contract()`/`select_vertical_spread_legs()`, they
  size the contract/legs **actually held** on their own current greeks —
  what lets a drifted position keep being managed instead of frozen when
  `main.py` chooses not to rotate. Both are pure re-uses of the identical
  vega-budget arithmetic the chain-first sizers already had (factored
  into shared `_size_single_leg_contract()`/`_size_vertical_spread()`
  helpers) — neither existing sizer needed a signature or behavior
  change.
- **Spread scale-down** via a new `self.Sell(strategy, quantity)` combo
  primitive (the Sell-side sibling of the existing `self.Buy(strategy,
  quantity)` entry path) — spreads could previously only ever scale up.
- **Multi-position book** — `phase_v2.options_risk.max_positions_per_underlying`
  (default `1`, byte-identical to before) lets `main.py` hold more than
  one position per underlying at once instead of one slot always
  clobbering itself on drift; rotation now liquidates the *oldest* held
  position specifically (`main.py::_liquidate_option_record()`), not
  "whatever was there."

Both the spread Sell-combo and the new combo-limit-order path
(`main.py::_try_submit_spread_limit_order()`) are new Lean API surface
this codebase has never exercised before — code-complete but
IB-unverified, the same status the original Buy-combo entry path already
carried. See `development/Problems.md` #58 for the full design and what
remains deferred (rotation netting, anti-thrashing).

## Webui visibility

`signal_payload["portfolio_book_role"]` (set in `main.py`, see above) is
surfaced per-symbol as a "Book Role" column in
`webui/src/components/risk/AssetSizingTable.tsx` (long/short badge, or
`—` for non-book-controlled symbols / when the overlay is disabled) —
typed as `Signal.portfolio_book_role` in `webui/src/types/state.ts`.
