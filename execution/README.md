# execution

Pure order gating, cost math and paper/live readiness, shared by `main.py` and the tests. Nothing here imports Lean; `main.py` wires it to Lean's runtime.

## Order gate: `order_gate.py`

- **`resolve_runtime_mode()`:** normalizes `phase_v2.runtime.mode`, failing safe to `observation`.
- **`resolve_order_permission()`:** `observation` never trades, `backtest` always may, and `paper` or `live` need the flags **and** healthy risk locks (proved in `formal/AetherFormal/OrderGate.lean`).
- **`simulate_fill()`:** hypothetical fills for `experience/simulated_portfolio.py`.
- **`is_real_order_placement()`:** backs the audit log's real-order hook.
- **`resolve_pending_order_action()`:** one order per symbol. Keep a same-direction order, replace an opposite or timed-out one.
- **`should_skip_for_open_order()`:** no second entry on an order already working.
- **`compute_fill_slippage_divergence_bps()`:** realized minus expected slippage, adverse only, against the fill bar's open.

## Cost model: `cost_model.py`

Does an entry's expected edge clear its cost?

- **`estimate_round_trip_cost_bps()`:** reads liquidity's estimate, never recomputes it, and adds both commission sides. Non-finite estimates fail closed (#117).
- **`expected_edge_bps()`:** linear in rank distance from the median, scaled by holding period.
- **`build_net_edge_decision()`:** read by the analyzer and `cost_sizing_multiplier()`. Fails open when disabled, uncalibrated or missing a rank.
- **Per-class fees (`phase_v2.costs.fee_by_type`):** `{"model": "coinbase", ...}` also sets Lean's `CoinbaseFeeModel`, because Lean's default charges crypto $0. A fee model must be set through `SetFeeModel` to take effect.
- **Calibrate:** `aq evaluate --calibrate-edge`.

## Reconciliation: `reconciliation.py`

`reconcile_positions()` compares intended and actual weights, classifying each symbol `matched`, `drifted`, `orphan_broker` or `missing_broker`. A breach feeds the kill switch, so it can stop trading.

## Real fill slippage

Lean's fill model has no bid-ask awareness, so this is where spread reaches a fill price.

- **Shared formula:** `slippage_amount()`, `resolve_slippage_bps()`, `resolve_fill_slippage()`, clamped by `MAX_LIQUIDITY_SLIPPAGE_BPS`.
- **Source:** `liquidity_cost_fraction()` by `phase_v2.liquidity.fill_slippage.source`; `per_side` is half a round trip.
- **Fills:** `_LiquidityAwareSlippageModel` in `main.py`; observation-mode fills charge the same estimate.

## Real limit orders

`phase_v2.limit_orders` routes orders as limits, on for the classes it lists; the target-weights path uses market orders and rests crypto exits as limits.

- **`resolve_limit_price()`:** half the spread from the reference price, times `offset_multiplier`.
- **`classify_order_status()`:** `pending`, `filled`, `canceled` or `unknown` (treated as pending), verified against real order events.
- **`main.py`:** `_try_submit_limit_order()`, then `_process_pending_limit_order_timeouts()` cancels past `unfilled_timeout_bars`, with a market fallback per class (`fallback_to_market_on_timeout`; off for futures and options, where a silent fill is a real unchosen position).
- **Cooldown:** stamps at confirmed fill, not placement, so an unfilled order doesn't block a flipped signal.
- **Casing:** call Lean's API in PascalCase (`self.MarketOrder`), and override its callbacks in snake_case (`on_order_event`).

## Config cache: `config_cache.py`

`read_cached(path, loader)` is mtime-gated. The key includes the loader, because several readers share `config.json` within a bar (#13).

## Paper and live readiness

- **`paper_readiness.py` (pure):** `evaluate_broker_config()`, `evaluate_observation_readiness()`, `evaluate_live_risk_posture()`.
- **`paper_readiness_io.py`, `paper_readiness_report.py`:** `aq paper-readiness`, writing `visualization/grafana/paper_readiness_report.json`.
- **`paper_readiness_scheduler.py`:** keeps that report fresh.
- **`live_credentials.py`, `live_credentials_io.py`:** credential checks, without ever printing a secret.

## Secrets

- **`secret_scan.py`:** `aq secrets-check`, the pre-commit guard.
- **`lean_config_render.py`:** `aq render-lean-config`. Secrets stay in the gitignored `lean.live.json`, and the tracked `lean.json` stays empty. It warns that IB can't fill crypto (#192).

## Going to paper

Follow RUNBOOK's "Deploy checklist" and "When the keys arrive".
