# execution

Pure, Lean-free order gating and simulated-fill math shared between `main.py`
and its test suite (V2-15, Observation Mode). Owns the
`phase_v2.runtime.mode` -> real-vs-simulated order decision table
(`resolve_order_permission`), the safe-fallback mode normalizer
(`resolve_runtime_mode`), and the hypothetical fill-price/quantity math used
by `experience/simulated_portfolio.py` (`simulate_fill`). No `AlgorithmImports`
or QCAlgorithm dependency, so it is unit-testable without a Lean runtime.

## Real fill slippage (execution/risk realism pass)

Closes the gap `development/v2_architecture.md`'s own HFT-gap analysis
already documented: `liquidity/market_liquidity.py`'s
`estimated_round_trip_cost` (price impact + bid-ask spread, computed every
bar for every symbol) used to be a pre-trade sizing/routing signal only —
it fed `reduce_size`/`block`/`simulate_instead` decisions but never touched
an actual fill price. No Lean security ever had a `SlippageModel` attached
(default zero-slippage fills), and `simulate_fill()` below always ran with
a hardcoded `slippage_bps=0.0`. Both are now wired to the same estimate:

- `order_gate.py::resolve_slippage_bps(symbol_key, slippage_bps_by_symbol,
  max_bps=MAX_LIQUIDITY_SLIPPAGE_BPS)` — pure lookup + clamp (missing
  symbol -> `0.0`, clamped to `max_bps`, default `MAX_LIQUIDITY_SLIPPAGE_BPS`
  = 500bps/5% as a guard against a degenerate estimate, never a
  normal-path limiter — see the constant's docstring for why 500bps is
  unreachable under normal participation). `max_bps` is overridable per
  the config flag below.
- `order_gate.py::slippage_amount(reference_price, slippage_bps)` — pure
  bps -> absolute price-delta math, shared by both fill paths below so
  there is exactly one bps -> price formula in the codebase.
- `order_gate.py::resolve_fill_slippage(symbol_key, reference_price,
  slippage_bps_by_symbol, max_bps=...)` — composes the two above; this is
  what `main.py`'s real Lean fill path calls.
- `order_gate.py::liquidity_cost_fraction(liquidity_payload, source)` —
  picks which `LiquidityDecision` field (`estimated_round_trip_cost` or
  `estimated_slippage`) feeds the bps estimate, per the config flag below.
  `resolve_fill_slippage_source(raw_source)` normalizes/fails-safe on the
  raw config value, same pattern as `resolve_runtime_mode()`.
- `simulate_fill()` below now computes `fill_price = close_price +
  slippage_amount(close_price, slippage_bps)` instead of duplicating the
  bps math inline — same output as before for any given `slippage_bps`
  (pure refactor, zero behavior change to existing callers).

**Config flags** (`phase_v2.liquidity.fill_slippage`, read once in
`main.py::_ensure_ready()`, both settable via `aq config set` — no code
change needed to retune either):

- `source` (`"round_trip"` default, or `"impact_only"`) — which
  `LiquidityDecision` field to charge (see the design decision below for
  the default's rationale). `aq config set
  phase_v2.liquidity.fill_slippage.source impact_only`
- `max_bps` (default `500.0`) — the clamp ceiling. `aq config set
  phase_v2.liquidity.fill_slippage.max_bps 100`

**Real Lean fills** (`main.py`): a new `_LiquidityAwareSlippageModel` class
(duck-typed against Lean's `ISlippageModel` — a `GetSlippageApproximation(
asset, order)` method, no explicit base class needed) is attached to every
security via `security.SetSlippageModel(...)` in `_add_asset()`. It reads
`self.latest_liquidity_slippage_bps` (a plain `dict[str, float]` keyed by
`str(symbol)`, refreshed every bar in `on_data()`'s Pass 2 right after
`build_liquidity_decision()` runs) and delegates to
`resolve_fill_slippage()` above. Lives in `main.py`, not this package,
matching this repo's convention that only `main.py` imports
`AlgorithmImports`/touches Lean's runtime types — this class is a thin
adapter, all the real logic is the pure functions above.

**Observation-mode simulated fills**: `experience/simulated_portfolio.py`'s
`enter_long()` gained an optional `slippage_bps: float = 0.0` parameter,
threaded through to `simulate_fill()`. Every one of `main.py`'s ~5
`enter_long(...)` call sites now passes
`slippage_bps=resolve_slippage_bps(symbol_key, self.latest_liquidity_slippage_bps)`
instead of relying on the old implicit zero default — so a real broker
fill (backtest/paper/live) and a simulated observation-mode fill now
charge the identical, already-computed cost estimate.

**Design decision**: `estimated_round_trip_cost` (impact + spread
combined) is the *default* `source` over `estimated_slippage` alone
(impact only) because Lean's own fill model has no bid-ask awareness at
all (fills happen at bar close, no quote data) — folding the spread
component into the single per-fill cost applied here is the only place
spread cost ever reaches an actual price in this codebase, not
double-counting against a bid-ask model that doesn't exist. This is a
default, not a hardcoded assumption — flip `phase_v2.liquidity.fill_slippage.source`
to `impact_only` (see the config flag above) if the combined estimate
ever proves too aggressive against a real backtest, no code change
required.

## Real limit orders (execution/risk realism pass, part 2)

Closes the other half of `development/v2_architecture.md`'s HFT-gap item
3: *"no limit-order/queue-position-aware execution exists — fills are
still all-or-nothing market fills."* Every real order in `main.py` was a
`MarketOrder()`/`SetHoldings()` market fill; this pass adds real `LimitOrder()`
support as a config-gated alternative, for every tradable asset class
(equity, crypto, bond, future, option). Default **off** — when disabled,
every routing call site takes the exact same market-order branch it always
has, byte-for-byte.

**Design decision — casing risk, stated up front, not buried**: this
codebase's existing, already-proven-working-via-a-completed-real-Lean-
backtest code calls the Lean API with **PascalCase** (`self.MarketOrder`,
`self.SetHoldings`, `self.Liquidate`, `self.SetFilter`,
`self.SetSlippageModel`) but overrides Lean's virtual callback methods
with **snake_case** (`def initialize(self)`, `def on_data(self, data)`) —
not PascalCase. The locally installed `quantconnect-stubs` package, by
contrast, declares the *entire* API in snake_case only and has zero
PascalCase entries anywhere — it does not actually match whatever Lean
version is really running here, and isn't authoritative over this
codebase's own working precedent. This pass matches the proven mixed
convention exactly: PascalCase for every new API call (`self.LimitOrder(...)`,
`ticket.Cancel()`, `OrderStatus.Filled`) and snake_case for the new
override method (`def on_order_event(self, order_event):`, matching
`initialize`/`on_data`). This is a real, unverified-until-a-real-backtest
risk — see the Verification list below.

- `order_gate.py::resolve_limit_price(reference_price, spread_fraction,
  is_buy, offset_multiplier=1.0)` — pure limit-price placement, reusing
  `liquidity_payload["spread_proxy"]` (already computed every bar, no new
  estimate invented) rather than a bespoke one. Buy limits sit below the
  reference price, sell/short limits sit above it, offset by half the
  spread times `offset_multiplier`. Fails safe to the reference price
  unchanged for non-positive price/spread.
- `order_gate.py::classify_order_status(status_name)` — pure string
  classification into `"pending"`/`"filled"`/`"canceled"`/`"unknown"`,
  isolating the one place this pass has to guess at Lean's real
  `OrderStatus` enum member spelling into a single small function — if the
  real spelling differs, this is a one-function fix, not a hunt through
  `main.py`.

**Config flags** (`phase_v2.limit_orders`, read once in
`main.py::_ensure_ready()`, all settable via `aq config set` — no code
change needed to retune any of them):

- `enabled` (default `false`) — global kill switch.
  `aq config set phase_v2.limit_orders.enabled true`
- `asset_classes` (default all 5) — scope the feature to a subset.
  `aq config set phase_v2.limit_orders.asset_classes '["equity","crypto"]'`
- `offset_multiplier` (default `1.0`) — scales the limit-price offset;
  `<1.0` more aggressive/likely to fill, `>1.0` more passive.
  `aq config set phase_v2.limit_orders.offset_multiplier 1.5`
- `unfilled_timeout_bars` (default `3`) — bars to wait before canceling a
  stale pending order.
  `aq config set phase_v2.limit_orders.unfilled_timeout_bars 5`
- `fallback_to_market_on_timeout` — **per-asset-class dict, not a single
  global bool** (mirrors the existing `exposure_caps_by_asset_class`
  precedent). Defaults `true` for equity/crypto/bond (a fallback fill
  there is the same trade `SetHoldings` would have placed anyway) and
  `false` for future/option (margin/expiry mechanics make a silent
  fallback fill a real position the model didn't choose at that price;
  safer to stay flat and let the model re-decide next bar). A partial
  override only changes the classes it mentions:
  `aq config set phase_v2.limit_orders.fallback_to_market_on_timeout.future true`

**Real Lean fills** (`main.py`): `_try_submit_limit_order()` is the shared
helper called from every real-order branch in `_apply_signal()`/
`_apply_option_order()` (buy/short × equity-crypto-bond/future/option).
Returns `False` immediately when disabled or the asset class isn't
configured — the only possible behavior in that case, by construction —
so the caller's existing `MarketOrder()`/`SetHoldings()` call is what
actually runs. Quantity comes from whatever the caller already computed
for future/option (`_futures_contract_count_for_weight()`'s
target-weight-signed result, or `options_decision.contracts`' always-
positive convention — options are never shorted) used exactly as-is, or
`self.CalculateOrderQuantity(symbol, target_weight)` for equity/crypto/bond
— reusing Lean's own built-in weight→quantity math (the same thing
`SetHoldings` calls internally) instead of writing new custom sizing
logic. On success, the `OrderTicket` is tracked in
`self.pending_limit_orders` (keyed by `str(symbol)` — the chain symbol
string, deliberately **not** following `last_trade_bar_by_symbol`'s
existing raw-Symbol-object keying, a pre-existing inconsistency not worth
copying).

`_process_pending_limit_order_timeouts()` runs once per bar, immediately
after `_refresh_risk_state()` — the same "resolve stale/urgent state
before this bar's fresh signal computation" anchor point that method's
own global drawdown-breach `Liquidate()` already uses. Cancels anything
past `unfilled_timeout_bars`, and (per the per-asset-class fallback flag)
optionally places a real `MarketOrder()` for the remainder.

`on_order_event(self, order_event)` is Lean's real order-fill callback
(new). Maps a fill/cancel back to a `pending_limit_orders` entry — via
`self.symbol_key_by_option_contract_symbol` for options (the event fires
on the CONTRACT symbol, not the chain symbol other dicts key by — the
same indirection `_order_target_symbol()` already needs), else
`str(order_event.Symbol)` directly. On a confirmed fill: stamps
`last_trade_bar_by_symbol` and clears the entry. On cancel: clears with no
cooldown stamp.

**Cooldown-timing semantics change (feature-on only)**: today,
`last_trade_bar_by_symbol` is stamped synchronously at order-*placement*
time. With limit orders enabled, it's stamped at confirmed-*fill* time
instead (`on_order_event`) — so a signal that flips while an order sits
unfilled isn't blocked by a cooldown for a trade that never happened.
Disabled (default): zero change, every stamp stays exactly where it is
today. One residual risk: if `on_order_event` never fires for some
Lean-runtime reason, the cooldown stamp is silently skipped for that fill
— only a real backtest can confirm this doesn't happen (see Verification
below).

**Observation-mode simulated fills are completely untouched.**
`_try_submit_limit_order()` is only ever called from inside
`if orders_allowed:` blocks, structurally unreachable from the simulated
`self._simulated_portfolio.enter_long(...)` path. No fill-uncertainty
modeling was added to `SimulatedPortfolioState` — that class is already
documented as a fast hypothetical abstraction, not a real-broker-mechanics
model, and there is no real order book for a simulated limit order to
queue against. Real execution realism (this pass's goal) and
observation-mode realism are different, separately-scoped topics.

**Verification — only a real Lean backtest can confirm these, in priority
order:**

1. **`OrderStatus` enum member casing** (`OrderStatus.Filled` etc.) — the
   single highest-risk guess in this whole feature. If wrong,
   `classify_order_status()` returns `"unknown"` for everything and every
   limit order sits until the timeout sweep force-cancels it — degrades
   safely (no silent bad trade), but the feature is functionally inert
   until fixed. Likely a one-line spelling fix in `execution/order_gate.py`'s
   `PENDING_ORDER_STATUS_NAMES`/`TERMINAL_FILLED_STATUS_NAMES`/
   `TERMINAL_CANCELED_STATUS_NAMES` once real log output shows the real
   spelling.
2. Whether `ticket.Cancel()`/`self.LimitOrder(...)` work via PascalCase at
   all against this project's actual running Lean version.
3. Whether `on_order_event` actually gets dispatched by the real engine —
   only `initialize`/`on_data` are proven snake_case override precedents
   in this exact codebase.
4. Whether `on_order_event` fires with the option CONTRACT symbol
   (assumed) vs. the chain symbol — if wrong, option pending entries are
   only ever cleared by the timeout sweep, never a genuine fill
   confirmation.
5. Whether `CalculateOrderQuantity` produces `SetHoldings`-parity
   quantities for every asset type in this universe — never called
   anywhere in this codebase before this pass.
6. Real fill-rate/behavior sanity — does this actually improve realized
   execution price, or does `fallback_to_market_on_timeout` end up firing
   on most trades anyway (effectively "market order with extra
   bookkeeping")? A pure strategy-quality judgment call no automated check
   here can answer.

## Config-read caching (latency-optimization pass, post-V2-23)

`config_cache.py::read_cached(config_path, loader)` — a shared, mtime-gated
cache used by `paper_readiness_io.py::read_paper_trading_config()` and
`runtime_config_io.py::read_runtime_mode()` below (plus
`risk/manual_override.py::read_manual_trade_lock_override()`, outside this
package but following the same pattern). All three read `config.json` far
more often than the file actually changes — once per bar in a Lean
backtest, once per poll-loop iteration in `retraining/worker.py` — so this
avoids a redundant `open()`+`json.load()` on every call while still picking
up an edit as soon as the file's mtime changes.

**Cache key is `(config_path, loader)`, not just `config_path`** — several
distinct readers share the same `config.json` path within the same bar
(`main.py::_refresh_risk_state()` calls the manual-override reader and the
paper-trading reader back-to-back). An earlier path-only cache let one
reader's cached value leak into another's result, caught only by the real
`lean backtest .` integration test, not by unit tests — see
`development/Problems.md` #13 and `tests/test_config_cache.py`'s
`test_two_different_loaders_on_the_same_path_do_not_collide`.

## Paper/live broker readiness (V2-21/V2-22)

- `paper_readiness.py` (pure) — `evaluate_broker_config()` is the single
  entrypoint `main.py` calls regardless of mode; dispatches to
  `evaluate_paper_broker_config()` (Lean's built-in `PaperBrokerage`, no real
  credentials needed — just brokerage/live-data-provider/manual-review
  attestation flags) or `evaluate_live_broker_config()` (also requires real
  credentials and `evaluate_live_risk_posture()` to pass). Also
  `evaluate_observation_readiness()`, which codifies most of
  `development/infrastructure.md`'s "Bereit fuer Paper Trading?" checklist.
- `paper_readiness_io.py` (IO) — mtime-cached reads (see above) of
  `phase_v2.paper_trading` from `config.json`, plus the first
  `mode='observation'`-filtered `experience_events` query.
- `paper_readiness_report.py` — offline report (`aq paper-readiness`) that
  `main.py` can't compute itself (no Postgres connection there); writes
  `visualization/grafana/paper_readiness_report.json`.
- `live_credentials.py` (pure) + `live_credentials_io.py` (IO) — pre-flight
  validation only for real broker credentials (`ib_config.py` or
  `AETHER_IB_*` env vars via `.env.live`). Does not wire Lean itself — Lean
  reads its own `ib-*` fields directly from `lean.json`.
- `runtime_config_io.py` — mtime-cached read (see above) of
  `phase_v2.runtime.mode`, used by `retraining/worker.py`'s
  auto-promote-blocked-in-live-mode safety net (V2-22) since that worker is
  a separate process from `main.py`.

See the Paper Trading Readiness Contract (V2-21) and Live Deployment
Contract (V2-22) in `development/v2_architecture.md` for the full picture.

## Scheduled readiness reporting (Phase 7 of the 5/10 -> 9/10 roadmap)

`paper_readiness_report.py`'s evaluation logic and dashboard wiring were
already correct and already dashboard-visible before this pass —
`monitoring/api_server.py` already merges
`visualization/grafana/paper_readiness_report.json` into `/api/state`,
with a dedicated `get_paper_readiness()` endpoint. The one real gap: the
report only ever regenerated when a human ran `aq paper-readiness` by
hand, so the dashboard tile could silently go stale between manual runs.

`paper_readiness_scheduler.py::PaperReadinessScheduler` closes that gap —
a periodic loop around the exact same `build_paper_readiness_view()`/
`write_paper_readiness_file()` calls, mirroring
`performance/trigger_worker.py::TriggerWorker`'s shape (sync-only, DSN via
`AETHER_POSTGRES_DSN`, `--once` CLI flag, `_pg_conn` injection for tests).
Run it as its own small process/Docker service
(`python -m execution.paper_readiness_scheduler --poll-interval 3600`) —
deliberately **not** folded into `retraining/worker.py`'s poll loop, which
has a different cadence and responsibility. Purely additive reporting: it
never touches `phase_v2.paper_trading`'s config flags or changes
`main.py`'s order-routing behavior in any way.

## Activating real paper-trading fills — manual step

Everything in this package today (`experience/simulated_portfolio.py`'s
`enter_long()`/`exit()`/`liquidate_all()`, called from ~15 sites in
`main.py` — order application, exposure/position-count accounting, PnL
snapshots) is a **synthetic** fill model (`execution/order_gate.py::simulate_fill()`),
never a real Lean `PaperBrokerage` fill event. Switching the fill *source*
from simulated to real is a distinct, deliberately unbuilt follow-up
("Phase 7b") — not attempted by this roadmap pass, per the user's explicit
scope boundary. The rest of the pipeline (experience store, triggers,
retraining, `performance/rank_ic_monitor.py`) is designed to need no
change when that happens — only the fill *source* changes, the schema
that receives it stays the same.

**The "distinct, clearly-marked manual step" this requires already
exists — it is the existing config flags, not new code.**
`execution/paper_readiness.py::evaluate_paper_broker_config()` already
blocks activation until a human deliberately sets, in `config.json`:

- `phase_v2.paper_trading.live_data_provider_configured: true`
- `phase_v2.paper_trading.manual_review_confirmed: true`

Neither flag is touched by anything in this roadmap — both stay `false`
until a human flips them outside of any automated process, and
`aq paper-readiness`/`PaperReadinessScheduler` will keep reporting
`ready: false` (via `blocking_reasons`) until they do. When "Phase 7b"
(real fills) is eventually built, it will introduce its own additional
flag with the same manual-flip contract — never auto-enabled.
