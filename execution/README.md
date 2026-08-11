# execution

Pure, Lean-free order gating, cost/slippage math, and paper/live readiness
checks shared between `main.py` and the test suite. Nothing here imports
`AlgorithmImports`/`QCAlgorithm` — every module is unit-testable without a
Lean runtime; `main.py` is the only place that touches Lean's runtime types
and wires these modules to it.

## Core order gating (`order_gate.py`)

- `resolve_runtime_mode(raw_mode)` — normalizes `phase_v2.runtime.mode`,
  failing safe to `"observation"`. Valid modes: `backtest`, `observation`,
  `paper`, `live`.
- `resolve_order_permission(mode, allow_live_orders, broker_config_present,
  risk_locks_healthy)` — the mode → real-vs-simulated order decision table.
  `observation` always returns `False` regardless of other flags (the one
  safety invariant this phase depends on); `backtest` always unrestricted;
  `paper`/`live` need the matching flags (`live` also needs
  `risk_locks_healthy`).
- `simulate_fill(close_price, target_weight, equity, slippage_bps=0.0)` —
  hypothetical fill-price/quantity/notional math used by
  `experience/simulated_portfolio.py`. `fill_price = close_price +
  slippage_amount(...)`; quantity/notional = `target_weight * equity` at
  that price. All-zero for non-positive `close_price`.
- `is_real_order_placement(execution_note, orders_allowed)` — classifies an
  execution note as a genuine real order vs. simulated (`"simulated_"`
  prefix) or a known no-op (denylists `_NO_OP_EXECUTION_NOTES` +
  `_NO_OP_EXECUTION_NOTE_SUFFIXES`). Backs the real-order audit-log hook in
  `on_data()`'s Pass 2.

## Expected-net-edge cost model (`cost_model.py`)

Entry-decision side of cost-awareness (sibling to, not a replacement for,
the fill/pricing math below): does this trade's expected edge clear its
expected cost.

- `estimate_round_trip_cost_bps(liquidity_payload, *, commission_bps_per_side,
  min_commission_usd, order_value, extra_slippage_bps)` — reads
  `liquidity_payload["estimated_round_trip_cost"]`, **never recomputes
  slippage**; adds a commission leg (bps of order value, `min_commission_usd`
  floor) plus an optional `extra_slippage_bps` buffer.
- `expected_edge_bps(predicted_rank, *, edge_bps_per_rank_unit, holding_bars,
  horizon_days, trade_direction=1)` — linear in rank deviation from the
  median (0.5), scaled down when `holding_bars` < the rank head's forward
  horizon. `trade_direction` (+1 long/-1 short) must be the sign of the
  trade being evaluated — measures edge in the direction of the trade, not
  just the long-side edge; without it every short was vetoed
  unconditionally (Problems.md — net-edge gate blocked 100% of shorts).
  `None` prediction → `0.0`.
- `build_net_edge_decision(predicted_rank, liquidity_payload, order_value,
  cost_config, *, trade_direction=1)` — consumed by
  `analyzer/market_analyzer.py`'s Priority 6.5 tier and
  `risk/position_sizing.py::cost_sizing_multiplier()`. **Fail-open,
  always**: `passes=True` when the gate is disabled, `edge_bps_per_rank_unit`
  is uncalibrated (`0.0`), or the rank prediction is missing. Config:
  `phase_v2.costs` (`enabled: false` until calibrated via
  `aq evaluate --calibrate-edge`).

## Position reconciliation (`reconciliation.py`)

`reconcile_positions(expected_by_symbol, actual_by_symbol, *,
weight_tolerance, value_tolerance_usd, portfolio_value,
max_tolerated_drift=None) -> ReconciliationReport` — compares the book's
intended weights against what a broker (or simulated portfolio) actually
holds. Classifies each symbol `matched` (within both `weight_tolerance` and
`value_tolerance_usd`), `drifted` (outside tolerance), `orphan_broker`
(held, not in book) or `missing_broker` (in book, not held).
`max_abs_weight_drift` = largest drift among non-matched symbols;
`breach=True` past `max_tolerated_drift`. `main.py` calls it once per bar
(portfolio-book path); a breach feeds `risk/kill_switch.py`'s trigger
inputs, so it can actually stop trading, not just log.

## Real fill slippage

`liquidity/market_liquidity.py`'s `estimated_round_trip_cost` was
sizing/routing input only; now wired into real and simulated fills too.

- `resolve_slippage_bps(symbol_key, slippage_bps_by_symbol, max_bps=
  MAX_LIQUIDITY_SLIPPAGE_BPS)` — lookup + clamp. Missing symbol → `0.0`;
  clamp default `MAX_LIQUIDITY_SLIPPAGE_BPS = 500.0` (5%, a guard against a
  degenerate estimate — normal participation never approaches it).
- `slippage_amount(reference_price, slippage_bps)` — the one bps→price
  formula in the codebase, shared by real and simulated fills.
- `resolve_fill_slippage(symbol_key, reference_price, slippage_bps_by_symbol,
  max_bps=...)` — composes the two above; used by `main.py`'s real Lean
  fill path.
- `liquidity_cost_fraction(liquidity_payload, source)` — picks
  `estimated_round_trip_cost` vs `estimated_slippage` per config.
  `resolve_fill_slippage_source(raw_source)` normalizes/fails-safe (same
  pattern as `resolve_runtime_mode()`).

Config `phase_v2.liquidity.fill_slippage` (`main.py::_ensure_ready()`):
`source` (default `"round_trip"` = impact+spread combined — the default
because Lean's own fill model has no bid-ask awareness, so this is the only
place spread cost ever reaches a fill price; `"impact_only"` = impact
alone), `max_bps` (default `500.0`).

**Real Lean fills**: `_LiquidityAwareSlippageModel` (`main.py`, duck-typed
against Lean's `ISlippageModel.GetSlippageApproximation(asset, order)`) is
attached per-security via `security.SetSlippageModel(...)` in `_add_asset()`;
reads `self.latest_liquidity_slippage_bps` (refreshed every bar in
`on_data()` Pass 2) and delegates to `resolve_fill_slippage()`.
**Observation-mode fills**: `simulated_portfolio.py::enter_long()` takes
`slippage_bps: float = 0.0` threaded to `simulate_fill()`; every `main.py`
call site passes `resolve_slippage_bps(...)` so real and simulated fills
charge the identical estimate.

## Real limit orders

Config-gated alternative to market orders, default **off** (disabled =
every routing call site byte-for-byte unchanged).

**Casing convention**: this codebase calls the Lean API in **PascalCase**
(`self.MarketOrder`, `self.SetHoldings`, `self.SetSlippageModel`) but
overrides Lean's virtual callbacks in **snake_case** (`initialize`,
`on_data`) — `quantconnect-stubs` is all-snake_case and does not match this
project's proven precedent. Limit-order code follows the same split:
PascalCase calls (`self.LimitOrder(...)`, `ticket.Cancel()`,
`OrderStatus.Filled`), snake_case override (`on_order_event`).

- `resolve_limit_price(reference_price, spread_fraction, is_buy,
  offset_multiplier=1.0)` — reuses `liquidity_payload["spread_proxy"]`. Buy
  limits below reference price, sell/short above, offset by half the
  spread × `offset_multiplier`. Fails safe to the unchanged reference price
  for non-positive price/spread.
- `classify_order_status(status_name)` — classifies into `"pending"` /
  `"filled"` / `"canceled"` / `"unknown"` (unrecognized → `"unknown"`,
  treated as pending). Backed by three tuples (one-line spelling fix if
  Lean's real enum differs):
  - `PENDING_ORDER_STATUS_NAMES` = `New`, `Submitted`, `PartiallyFilled`,
    `UpdateSubmitted`, `CancelPending`
  - `TERMINAL_FILLED_STATUS_NAMES` = `Filled`
  - `TERMINAL_CANCELED_STATUS_NAMES` = `Canceled`, `Invalid`

  `CancelPending` (V5.2.8) was added after scanning 33 real
  `order-events.json` files — `OrderStatus.CancelPending` appeared 23 times,
  1:1 with confirmed unfilled-timeout cancels (previously fell through to
  `"unknown"`, already treated as pending — a precision fix, not a behavior
  change). `PartiallyFilled` has never appeared in that sample.

Config `phase_v2.limit_orders` (`main.py::_ensure_ready()`): `enabled`
(default `false`, global kill switch), `asset_classes` (default all 5),
`offset_multiplier` (default `1.0`; `<1.0` more aggressive/likely to fill,
`>1.0` more passive), `unfilled_timeout_bars` (default `3`),
`fallback_to_market_on_timeout` — **per-asset-class dict**, not a single
bool (mirrors `exposure_caps_by_asset_class`): `true` for equity/crypto/bond
(fallback = what `SetHoldings` would've placed anyway), `false` for
future/option (a silent fallback fill is a real, model-unchosen position
under margin/expiry mechanics — safer to stay flat).

**Real Lean fills** (`main.py`): `_try_submit_limit_order()` — shared helper
called from every real-order branch in `_apply_signal()`/
`_apply_option_order()`; returns `False` immediately when disabled/asset
class not configured (caller's market-order call runs instead). Quantity
from the caller's already-computed
`_futures_contract_count_for_weight()`/`options_decision.contracts`, or
`self.CalculateOrderQuantity(symbol, target_weight)` for equity/crypto/bond.
`OrderTicket` tracked in `self.pending_limit_orders` (keyed by `str(symbol)`).
`_process_pending_limit_order_timeouts()` runs once per bar (right after
`_refresh_risk_state()`): cancels anything past `unfilled_timeout_bars`, and
per the fallback flag optionally places a real `MarketOrder()`.
`on_order_event(self, order_event)` is Lean's fill/cancel callback — maps
back to the `pending_limit_orders` entry via
`self.symbol_key_by_option_contract_symbol` for options (fires on the
contract symbol) or `str(order_event.Symbol)` otherwise; fill stamps
`last_trade_bar_by_symbol` and clears the entry, cancel just clears it.

**Cooldown-timing change (feature-on only)**: `last_trade_bar_by_symbol`
normally stamps at order-placement time; with limit orders enabled it
stamps at confirmed-fill time instead, so a flipped signal isn't blocked by
a cooldown for a trade that never happened. Disabled: no change. Risk: if
`on_order_event` never fires, the cooldown stamp is silently skipped.

**Observation-mode fills untouched** — `_try_submit_limit_order()` only
runs inside `if orders_allowed:`, unreachable from simulated `enter_long()`;
no fill-uncertainty modeling was added to `SimulatedPortfolioState`.

**Unverified until a real Lean backtest confirms**, priority order:
`OrderStatus` enum casing (highest risk — if wrong, `classify_order_status()`
returns `"unknown"` for everything and orders sit until timeout-cancel,
degrading safely); whether `ticket.Cancel()`/`self.LimitOrder(...)` work via
PascalCase at all; whether `on_order_event` is dispatched by the real
engine; whether it fires with the option contract symbol (assumed) vs.
chain symbol; whether `CalculateOrderQuantity` gives `SetHoldings`-parity
quantities for every asset type (never called elsewhere before this pass);
real fill-rate sanity (does this beat `fallback_to_market_on_timeout`
firing on most trades anyway).

## Config-read caching (`config_cache.py`)

`read_cached(config_path, loader)` — shared, mtime-gated cache used by
`paper_readiness_io.py::read_paper_trading_config()`,
`runtime_config_io.py::read_runtime_mode()`, and (outside this package)
`risk/manual_override.py::read_manual_trade_lock_override()`. Avoids
redundant `open()`+`json.load()` on every call while still picking up an
edit as soon as the file's mtime changes.

**Cache key is `(config_path, loader)`, not just `config_path`** — several
readers share `config.json` within the same bar
(`main.py::_refresh_risk_state()` calls the manual-override and
paper-trading readers back-to-back); a path-only cache let one reader's
value leak into another's result. See `development/Problems.md` #13,
`tests/test_config_cache.py::test_two_different_loaders_on_the_same_path_do_not_collide`.

## Paper/live broker readiness

- `paper_readiness.py` (pure) — `evaluate_broker_config()` is the single
  entrypoint `main.py` calls regardless of mode; dispatches to
  `evaluate_paper_broker_config()` (Lean's built-in `PaperBrokerage`, no
  real credentials — brokerage/live-data-provider/manual-review
  attestation flags only) or `evaluate_live_broker_config()` (real
  credentials + `evaluate_live_risk_posture()`). Also
  `evaluate_observation_readiness()`, codifying
  `development/infrastructure.md`'s readiness checklist.
- `paper_readiness_io.py` (IO) — mtime-cached `read_paper_trading_config()`
  of `phase_v2.paper_trading`, plus `fetch_observation_mode_events()`
  (first `mode='observation'`-filtered `experience_events` query).
- `paper_readiness_report.py` — offline report (`aq paper-readiness`,
  `build_paper_readiness_view()`/`write_paper_readiness_file()`); writes
  `visualization/grafana/paper_readiness_report.json` (`main.py` has no
  Postgres connection to compute this itself).
- `live_credentials.py` (pure: `credentials_present()`,
  `describe_missing_fields()`, `postgres_dsn_is_live_safe()`) +
  `live_credentials_io.py` (IO: `load_live_credentials()`,
  `load_postgres_dsn()`) — pre-flight validation for real broker
  credentials (`ib_config.py` or `AETHER_IB_*` via `.env.live`). Does not
  wire Lean itself — Lean reads `ib-*` fields directly from `lean.json`.
- `runtime_config_io.py::read_runtime_mode()` — mtime-cached read of
  `phase_v2.runtime.mode`, used by `retraining/worker.py`'s
  auto-promote-blocked-in-live-mode safety net (separate process from
  `main.py`).

See the Paper Trading Readiness Contract (V2-21) and Live Deployment
Contract (V2-22) in `development/architecture.md` for the full picture.

## Scheduled readiness reporting (`paper_readiness_scheduler.py`)

`PaperReadinessScheduler` — periodic loop around
`build_paper_readiness_view()`/`write_paper_readiness_file()`, so the
readiness report (already dashboard-visible via `monitoring/api_server.py`'s
`/api/state` merge + `get_paper_readiness()` endpoint) doesn't go stale
between manual `aq paper-readiness` runs. Mirrors
`performance/trigger_worker.py::TriggerWorker`: sync-only, DSN via
`AETHER_POSTGRES_DSN`, `--once` flag, `_pg_conn` injection for tests. Run as
its own process: `python -m execution.paper_readiness_scheduler
--poll-interval 3600` (not folded into `retraining/worker.py`'s loop —
different cadence). Purely additive — never touches
`phase_v2.paper_trading` config or order-routing behavior.

## Secret handling (`secret_scan.py`, `lean_config_render.py`)

The tracked `lean.json` ships as the stock Lean template with every
brokerage/API-secret field empty; these keep it that way while still
letting live/paper deployment use real credentials.

- `secret_scan.py` — backs `aq secrets-check` / `.githooks/pre-commit`.
  `find_populated_secret_fields(lean_config)` flags any field whose name
  looks like a credential (`is_secret_field()`, suffix match on
  `-api-key`/`-password`/etc. plus IB identity fields) and is non-empty.
  `is_tracked_env_secret(filename)` flags a `.env`-style filename that
  isn't a committed `*.example` template. Pure — only field names are ever
  returned, never values.
- `lean_config_render.py` — Lean does not expand env vars inside
  `lean.json` (read literally), so `render_lean_config()` (pure) overlays
  real values from `.env.live`/`AETHER_*` env vars (`SECRET_ENV_MAP`) onto
  the empty template; `write_rendered_config()` (IO) writes a gitignored
  `lean.live.json` that live/paper deployment points Lean at via
  `--lean-config`. Backtests use the plain `lean.json` untouched.
  `load_env_file()`/`parse_env_file()` handle `.env.live` parsing.

## Activating real paper-trading fills — manual step

Everything here today produces **synthetic** fills
(`order_gate.py::simulate_fill()`, via `simulated_portfolio.py`'s
`enter_long()`/`exit()`/`liquidate_all()`), never a real Lean
`PaperBrokerage` fill event. Switching the fill *source* to real fills is a
distinct, deliberately unbuilt follow-up ("Phase 7b") — the rest of the
pipeline (experience store, triggers, retraining, `rank_ic_monitor.py`)
needs no change when that happens.

The manual gate already exists as config, not code:
`paper_readiness.py::evaluate_paper_broker_config()` blocks activation
until a human sets, in `config.json`,
`phase_v2.paper_trading.live_data_provider_configured: true` and
`phase_v2.paper_trading.manual_review_confirmed: true`. Neither is touched
by any automated process — both stay `false` until a human flips them, and
`aq paper-readiness`/`PaperReadinessScheduler` keep reporting `ready: false`
(via `blocking_reasons`) until they do.
