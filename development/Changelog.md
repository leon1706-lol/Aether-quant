# Changelog

Detailed phase results for Aether Quant, moved out of `README.md` (see there
for the current status, project structure, and runbook). Newest entries at
the bottom, ordered chronologically by phase.

Each entry follows: **Summary** (what/why) → **Shipped** (concrete changes)
→ **Verification** (how it was confirmed — real Lean backtest, unit tests,
or manual review; omitted when an entry has none).

## V1 — Finished

**Summary:** The first working pipeline, over a small mixed universe (`AAPL`, `SPY`, `QQQ`, `BTCUSD`), 2014-12-01 to 2018-08-13 daily bars.

**Shipped:**
- Train/validation/backtest windows; next-day-direction label; 1d/5d/20d return/volatility/momentum, daily range, and volume-change features.

## Phase 2 Result

**Shipped:**
- Loads Lean ZIPs, normalizes prices, computes features/target, produces train/validation/backtest splits, fits and saves the scaler.

## Phase 3 Result

**Shipped:**
- PyTorch MLP with layer norm/dropout, asset context as a model input, validation-loss early stopping, optimized decision threshold, saved metrics/checkpoint, and a JSON export for Lean inference.

## Phase 4 Result

**Shipped:**
- Loads exported artifacts (weights/schema/manifest/scaler) and runs the model forward pass directly in Lean, producing real buy/sell/hold signals written to `visualization/state.json`.

## Phase 5 Result

**Shipped:**
- Strategy-return computation vs. buy-and-hold, Sharpe/volatility/max-drawdown export, equity curves, and a `backtests/strategy_report.json` summary.

## Phase 6 Result

**Shipped:**
- Separated Lean/dev dependencies; runs in the real local Lean Docker runtime; daily/total drawdown risk controls with trade-blocking/liquidation; minimum confidence + trade cooldown.

## Phase 8 Result

**Shipped:**
- Extended `state.json` with dashboard/monitoring/scene data; Grafana-friendly CSV/JSON exports; scorecards, asset heatmap, risk band, positions, and a 3D-like scene in the dashboard.

## Phase 9 Result

**Summary:** Expanded the universe to equities, ETFs, and 3 crypto coins, with a data-quality-aware training pipeline.

**Shipped:**
- Derives ETHUSD/LTCUSD daily series from Coinbase minute data; per-asset data-quality scoring; trains only on robust assets; flags thin series `observation_only` (blocked from real trades, still shown in UI); position/exposure caps.

**Verification:**
- A successful Lean backtest over the expanded universe.

## Phase 10 Result

**Shipped:**
- Kept large artifacts out of git; documented core commands; structured runtime logs; first `pytest` tests (features, asset quality, scaler, risk controls); pre-flight artifact/config validation.

## Phase V2-1 Result

**Summary:** Started the V2 fork on top of the stable V1/Phase 10 codebase.

**Shipped:**
- V2 module structure (MoE, experts, regime, topology, experience, risk, monitoring); documented the planned architecture and tech stack (Docker, Lean, PyTorch, Postgres, Grafana, Telegram, HTML dashboard).

## Phase V2-2 Result

**Shipped:**
- `data_pipeline/` as a stable V2 layer over `train.py`; a V2 pipeline manifest (data source, universe, features, windows, asset quality); tests locking in the Lean data contract.

## Phase V2-3 Result

**Shipped:**
- `risk/position_sizing.py`: volatility-classified (`low`/`normal`/`high`) dynamic position sizing (`base_target_weight`, `target_weight`, `leverage_factor`), written into runtime state, the dashboard heatmap, and the Grafana CSV.

## Phase V2-4 Result

**Shipped:**
- `volatility_dashboard.html`, a 5s-refresh live view reading `state.json` directly — portfolio/risk/drawdown plus per-asset signal/regime/volatility/sizing/confidence. Works without a broker key.

## Phase V2-6 Result

**Shipped:**
- `regime/market_regime.py`: trend (`bullish`/`bearish`/`sideways`) from momentum, volatility regime from rolling vol, combined into `risk_on`/`risk_neutral`/`risk_off`. Written into runtime state and the Grafana CSV.

## Phase V2-7 Result

**Shipped:**
- `experts/expert_datasets.py`: regime-sliced (bullish/bearish/sideways/volatility) expert training datasets, filtered to `training_eligible` assets, with a manifest (row counts, splits, routing filters). Generated artifacts kept out of git.

## Phase V2-8 Result

**Shipped:**
- Separate PyTorch expert models per regime slice (same MLP family as baseline); `train.py --experts-only`; per-expert weights/metrics under `ml/expert_models/`. Artifacts kept out of git.

## Phase V2-8.5 Result

**Shipped:**
- Smaller expert networks with stronger regularization; a quality gate (validation/backtest/MCC/train-backtest gap) flagging each expert `stable`/`watchlist`/`disabled_for_gating`, so a later gating network never blindly trusts a weak or overfit expert.

## Phase V2-9 Result

**Shipped:**
- `moe/gating.py`: weights experts by quality gate, regime fit, and stability (ignoring `disabled_for_gating`), combining baseline + expert probabilities into one final MoE probability. Falls back to the baseline model if expert artifacts are missing.

## Phase V2-10 Result

**Summary:** A single, pure, deterministic decision layer replacing an ad-hoc if/elif chain in `main.py`.

**Shipped:**
- `analyzer/market_analyzer.py::build_market_analysis_decision()` combines expert/regime/topology/risk output into exactly one of `observe`/`simulate`/`trade`/`reduce_risk`/`retrain_candidate`, priority-ordered (risk containment > model health > profit action > paper tracking > observation). `_apply_signal` still only runs for `trade` — no order-placement behavior change.

**Verification:**
- 13 new tests in `tests/test_market_analyzer.py` (all 5 categories, topology absence, two priority tiebreaks).

## Phase V2-11 Result

**Summary:** A pure, deterministic cross-asset topology layer that starts influencing real trading decisions.

**Shipped:**
- `topology/market_topology.py`: pairwise correlation, union-find clustering, 3D coordinates (correlated assets near each other, volatility on z). Computed once per bar before the per-asset loop, no lookahead.
- New priority tiers in the analyzer: `topology_risk=="elevated"` forces `reduce_risk`; an isolated asset can't reach `trade`, falls back to `simulate`.
- New `/topology` webui tab + `/api/topology`.

**Verification:**
- New tests in `tests/test_market_topology.py` plus 4 new cases in `test_market_analyzer.py`.

## Phase V2-12 Result

**Summary:** A pure, deterministic per-asset liquidity/market-impact layer.

**Shipped:**
- `liquidity/market_liquidity.py`: daily-dollar-volume/participation-rate/slippage/round-trip-cost estimation from OHLCV alone; classifies orders `normal`/`thin`/`high_impact`/`blocked`, recommending `allow`/`reduce_size`/`simulate_instead`/`block`.
- Two new analyzer priority tiers (`liquidity_blocked`, `liquidity_thin`, both force `simulate`).
- Real per-asset transaction costs in Lean (`ConstantPercentageFeeModel` for crypto, `ConstantFeeModel` for equities); new `LiquidityTable.tsx` webui panel; `Dockerfile` + extended `docker-compose.yml`.

**Verification:**
- 9 new tests in `test_market_liquidity.py`, 4 new cases in `test_market_analyzer.py`. LTCUSD (thin data) correctly hits `blocked`/`simulate` without disrupting the rest of the decision tree.

## Phase V2-13 Result

**Summary:** A fire-and-forget Redis experience-event stream, the first step toward a durable trade/decision history.

**Shipped:**
- `experience/redis_queue.py`: `build_experience_event()` + `ExperienceQueue` (XADD after every asset decision, capped `maxlen=100000`); fails silently on Redis errors, never blocks the Lean loop; deferred `redis` import so Lean environments stay importable without it.

**Verification:**
- 8 tests in `test_experience_queue.py` (schema, disabled no-op, Redis-unreachable safety, all 4 modes, uniqueness).

## Phase V2-14 Result

**Summary:** Durable PostgreSQL persistence for the experience stream.

**Shipped:**
- `experience/postgres_worker.py`: standalone worker (`XREADGROUP` → `experience_events` table, embedded DDL, no migrations), idempotent via `ON CONFLICT DO NOTHING`, malformed messages routed to a dead-letter stream, exponential backoff/reconnect. New `experience-worker` Docker service.

**Verification:**
- 7 tests in `test_postgres_worker.py` (scalar/full-payload persistence, idempotency, dead-letter routing, PG-error-leaves-pending, empty-stream).

## Phase V2-15 Result

**Summary:** Observation Mode — runs the full decision pipeline with zero real orders, tracking a fully simulated portfolio in parallel.

**Shipped:**
- `phase_v2.runtime.mode` (`backtest`/`observation`/`paper`/`live`, default `backtest` — unchanged behavior); `execution/order_gate.py` (`resolve_order_permission`: observation mode is **never** allowed to place real orders, regardless of any other flag).
- `experience/simulated_portfolio.py::SimulatedPortfolioState` — fake cash/holdings/equity/drawdown/exposure entirely in memory, never touching the real broker.
- Cooldown/position-limit/exposure/drawdown checks all made mode-aware (run against the simulated portfolio when real orders are blocked).
- `experience/observation_metrics.py` (pure summary functions); new dashboard exports and `ObservationPanel.tsx`.

**Verification:**
- 33 new tests (80 → 113 total), including the safety-critical `test_observation_mode_never_allows_orders_even_if_flags_true`.
- Real Lean backtest with `mode="observation"`: Lean's own stats show `"Total Orders": "0"`, unchanged end equity, while the observation panel showed real simulated activity.
- Two Docker bugs found and fixed post-hoc (`Dockerfile.worker` missing `execution/`; `requirements-worker.txt` missing `numpy` — see Problems.md).

## Phase V2-16 Result

**Summary:** Performance Triggers — automated, threshold-based health monitoring over the experience stream.

**Shipped:**
- `performance/triggers.py`: 8 pure trigger functions (drawdown, Sharpe degradation, win rate, confidence decay, regime shift, liquidity warning, risk-lock, observation count) plus `evaluate_all_triggers()`; each event carries severity/scope/recommended_action/`retrain_candidate`.
- Dedicated `performance_triggers` Postgres table, a standalone `performance/trigger_worker.py`, an in-memory fast-path view in `main.py`, new `PerformanceTriggersPanel.tsx`.

**Verification:**
- 37 new tests (113 → 150 total).

## Visualization Unification Result

**Summary:** Replaced two separate HTML dashboards with a single React/Vite webui plus a FastAPI JSON backend.

**Shipped:**
- `monitoring/api_server.py` (FastAPI, serves `state.json`/`scene.json`/Grafana exports); Overview + Risk pages mapped 1:1 onto the old dashboards; genuinely 3D rotatable market scene (`@react-three/fiber`), foundation for V2-11's topology view.

## Phase V2-17 Result

**Summary:** Controlled Retraining — closes the loop left open by V2-16's triggers with a full plan/train/validate/backtest/commit/promote/rollback pipeline.

**Shipped:**
- New `retraining/` package (pure/IO/worker split): `planning.py`, `postgres_registry.py` (`model_versions`/`retraining_events` DDL, one-active-model DB constraint), `validation_gate.py`, `backtest_gate.py`/`lean_backtest.py`, `vault_commands.py`/`vault_client.py` (external `av` subprocess wrapper, missing-binary-safe), `artifacts.py`, `status_export.py`, `orchestrator.py` (CLI), `worker.py`.
- `train.py` gets a `--candidate --version-id` mode writing exclusively to `ml/versions/<id>/`, never touching active paths.
- Promotion requires a successful Aether-Vault commit; rollback verifies SHA-256 hashes before activating files.
- `RetrainingWorker.auto_promote` defaults `false` — actual model takeover stays a manual `promote` call even with the worker running.

**Verification:**
- 90 new tests (150 → 244 total).

## Phase V2-17.5 Result

**Summary:** A probabilistic overlay on topology plus richer retrain-trigger logic — strictly additive, never replacing the deterministic decision path.

**Shipped:**
- `topology/learned_topology.py`: per-node cluster probabilities/confidence/uncertainty/stress/neighbor-drift, falling back to the deterministic position whenever the model is missing or unconfident.
- `train_topology.py`: fits KMeans prototypes from real experience-event outcomes, writes to `ml/versions/<id>/` only, skips (not errors) with insufficient data.
- 5 new persistence-guarded triggers (topology uncertainty/mismatch/drift, model-disagreement, trigger-frequency-spike); `retraining/planning.py` now picks candidates by priority score, not just timestamp.

**Verification:**
- 69 new tests (244 → 313 total).

## Phase V2-18 Result

**Summary:** Removed Grafana in favor of a native React tracing dashboard — Grafana had no computation path of its own, so this was purely a new consumer of already-existing JSON/CSV exports.

**Shipped:**
- Removed the `grafana` Docker service/volume; new `/tracing` webui page with 4 panels (metrics snapshot, asset performance, backtest equity, observation equity) and two dependency-free SVG chart primitives.

## Phase V2-19 Result

**Summary:** Telegram Alerts for both trigger events and end-of-session summaries.

**Shipped:**
- New `notifications/` package (pure/IO/worker split); trigger channel polls the existing `performance_triggers` table directly (no new detection logic); session-summary channel adds a new experience event pushed at session rollover in `main.py`.
- Fixed a real gap caught during implementation: `event_to_row()` would have `KeyError`'d on session-summary events (no ticker/symbol/signal/action fields) — silently dead-lettering every one forever; fixed with `.get()` defaults.

**Verification:**
- 24 new tests plus 7 extensions (313 → 364 total with V2-19.5).

## Phase V2-19.5 Result

**Summary:** A manual, offline Yahoo Finance backfill script for thin local Lean data (mainly ETHUSD/LTCUSD) — never runs from training/runtime/Docker.

**Shipped:**
- `data_pipeline/yfinance_backfill.py`: dry-run by default (`--apply` to write), existing real Lean rows always win on overlap, `yfinance` stays a dev-only dependency.

**Verification:**
- 20 new tests (all using an injected fetch stub, never importing `yfinance` itself).

## Phase V2-23.1 Result

**Summary:** Data-driven liquidity spread estimation — closed differently than planned, since no real fill-slippage telemetry existed to calibrate from.

**Shipped:**
- `estimate_high_low_spread()`: the Corwin & Schultz (2012) closed-form high-low spread estimator, computed from data already collected every bar — replaces the static per-security-type spread lookup as the primary path (which remains a fallback for the first few bars).

**Verification:**
- 10 new tests (independently recomputed reference calc, monotonicity, fallback behavior).

## Phase V2-23.2 Result

**Summary:** Found during a static-vs-dynamic config audit: three `phase_v2` config blocks `main.py` had read since V2-3/V2-6/V2-9 were never actually present in `config.json`, silently forcing hardcoded Python defaults; separately, `average_correlation` had never been fed a real value since V2-6.

**Shipped:**
- Added the three missing config blocks (values match the prior hardcoded defaults — no behavior change). Wired `average_correlation` from topology's already-computed `correlation_strength`.

**Verification:**
- 1 new test confirming `average_correlation` is passed through and affects `risk_score`/`reasons`.

## Phase V2-23.3 Result

**Summary:** Same audit — topology's 3D layout was purely cosmetic (angle-based placement), never actually reflecting correlation distance beyond radius.

**Shipped:**
- `_stress_majorize_2d()`: SMACOF stress-majorization over the full pairwise correlation-distance matrix, deterministically seeded, isometrically rescaled back into the existing display bounds. Chosen over classical MDS to stay numpy-free.

**Verification:**
- 3 new tests (correlated assets spatially closer, bounds respected, `embedding_iterations` actually affects layout).

## Test Suite

313 → 378 tests total after the V2-23.x audit pass (14 new: 10 liquidity, 1 regime, 3 topology).

## Phase V2-20 Result

**Summary:** Confirmed a normal `lean backtest .` already exercises the entire ML system end to end (baseline, all 4 experts, MoE gating, regime, topology) — no runtime logic needed rebuilding, just proof of existing coverage.

**Shipped:**
- `tests/test_lean_backtest_ml_coverage.py`: the first real integration test running `lean backtest .` via subprocess and asserting all subsystems populated `state.json` correctly — closing the gap that `main.py` had zero tests of its own (Problems.md #8/#66).
- A Lean-vs-Lean4/`elan` binary-name-collision safeguard for the skip check.
- New `/neural-network` webui page: interactive 3D view of all 5 trained networks plus live stats.

## Phase V2-21 Result

**Summary:** Paper Trading Preparation — replaced a previously no-op readiness check with real, code-enforced gates (targeting Lean's built-in `PaperBrokerage`, not a real IBKR paper account).

**Shipped:**
- `execution/paper_readiness.py`: `evaluate_paper_broker_config()` (3 required confirmations) and `evaluate_observation_readiness()` (4 of 5 checklist items, the 5th deliberately left as a human review).
- New `aq paper-readiness` CLI gate, `PaperReadinessPanel.tsx`, and a `lean-live` Docker Compose service (opt-in profile).

**Verification:**
- New tests across `test_paper_readiness.py`/`_io.py`/`_report.py`.

## Phase V2-22 Result

**Summary:** Live Deployment Structure — purely structural groundwork so the paper→live switch becomes a config/credential change, not a code rewrite. No real broker credentials or live trades configured or tested.

**Shipped:**
- `execution/live_credentials.py`/`live_credentials_io.py` (tries `ib_config.py`, falls back to env vars); `evaluate_live_broker_config()`/`evaluate_live_risk_posture()` (extra safety-ceiling checks on top of the paper gate).
- Auto-promote safety net: retraining forces manual promotion whenever `runtime.mode=="live"`.
- New `live_order_permission_blocked_trigger` (critical severity, not retrain-eligible — a broker misconfiguration isn't fixed by a new model).

**Verification:**
- New tests across `test_live_credentials.py`/`_io.py`/`test_runtime_config_io.py`, plus retraining/trigger test extensions.

## Latency Optimization + Docker Image Consolidation

**Summary:** A static complexity analysis of `main.py`'s per-bar hot path found three real bugs plus two CPU bottlenecks (pure-Python NN forward pass, pure-Python O(N²×100-iter) topology embedding); in parallel, Docker images were consolidated 5→3 as groundwork for a later latency-optimized variant (explicitly not an HFT conversion).

**Shipped:**
- Fixed 3 bugs (Problems.md #11-#13): `main.py::_write_state()`'s useless throttle guard (unreachable comparison) rewrote all 7 state files every bar; `simulated_portfolio.py::mark_to_market()` called once per symbol per bar instead of once per bar caused `O((bars·symbols)²)` CSV rebuild work — fixed via `close_prices_by_symbol` collection + new `main.py::_flush_observation_equity_csv()`; new `execution/config_cache.py::read_cached()` mtime-cached config reads, keyed by `(config_path, loader)` after a real bug (found only via `lean backtest .`) where same-path readers overwrote each other's cache entries
- Deliberately left open: skipping `experience/redis_queue.py::push()` in backtest mode (Problems.md #14, open at the time)
- Docker: `experience-worker`, `performance-trigger-worker`, `telegram-worker` merged into one `Dockerfile.workers` image (5→3 custom images); `aether-quant`/`retraining-worker` unchanged
- NN inference extracted from private `main.py` methods into `inference/exported_model.py` (free functions) and vectorized with `numpy` (previously pure Python, run 5x per symbol per bar)
- `topology/market_topology.py::_stress_majorize_2d()` (SMACOF embedding) vectorized with numpy, same inputs/outputs/iteration count/seeding; pairwise correlation loop and `learned_topology.py`'s smaller O(N²×5) portion deliberately stay unvectorized (non-uniform window lengths / negligible cost)
- Behavior-changing: `build_market_topology()` now accepts `previous_positions` for a warm-started SMACOF (new `convergence_tolerance` param for early exit); new config keys `phase_v2.topology.warm_start_enabled` (default `true`) and `convergence_tolerance` (default `0.01`) — changes topology coordinates bar-by-bar, breaking bit-for-bit reproducibility vs. old always-cold-seeded behavior; `warm_start_enabled: false` is an exact rollback

**Verification:**
- Docker consolidation verified via `docker compose build`/`up` and clean startup of all three containers
- New tests: `tests/test_config_cache.py`, `tests/test_exported_model.py`, plus extensions to `test_simulated_portfolio.py`, `test_manual_override.py`, `test_paper_readiness_io.py`, `test_runtime_config_io.py`, `test_market_topology.py` (parity tests for vectorized SMACOF and NN inference against hand-computed/reference values)

## 20-Asset Universe Expansion + Genuine Held-Out Backtest Window

**Summary:** Grew the trading universe from 10 to 20 assets on real (non-synthetic) data and restructured the train/validation/backtest split so the backtest is finally a genuine out-of-sample period instead of re-running over the full training history.

**Shipped:**
- 8 new equities (`AIG`, `BNO`, `FB`, `GOOG`, `GOOGL`, `USO`, `WM`, `AAA`) added at zero backfill cost from existing on-disk Lean data through 2021-03-31
- 2 new crypto assets (`XRPUSD`, `ADAUSD`) backfilled from scratch via `yfinance_backfill.py --apply`; dry run revealed real earliest history starts 2017-11-09, not the originally guessed dates
- `BTCUSD`/`ETHUSD`/`LTCUSD` extended forward to 2021-03-31 via new/updated `backfill`/`backfill_to` config blocks
- Genuine held-out window: `common_window` end moved 2018-08-13 → 2021-03-31; `phase1.windows` restructured to training 2014-12-01→2017-12-31, validation 2018-01-01→2018-03-31, backtest 2018-04-01→2021-03-31 (~3 years; previously backtest == full common_window)
- Real bug fixed (Problems.md #15): `train.py::ensure_derived_crypto_daily_series()` unconditionally overwrote `ETHUSD`/`LTCUSD` daily zips from minute data, discarding yfinance-backfilled rows; fixed to merge by date instead of clobber
- Dataset manifest: 16/20 assets landed `training_eligible`/`trading_eligible`; `AAA`, `ETHUSD`, `XRPUSD`, `ADAUSD` stayed `observation_only` for genuine data-sparsity reasons (not a bug)
- README gained a "Universe Size" section + Mermaid diagram; `development/logo.png` fixed (stray border artifact removed, recomposited for light/dark theme correctness)
- Real bug fixed (Problems.md #16), found only via `lean backtest .`: `main.py::initialize()` exceeded Lean's hardcoded 90s isolator timeout — fixed by splitting into a minimal Lean-critical path plus new `_ensure_ready()` deferred to the first `on_data()` call; `initialize()` now 1.85s, full isolator window ~51s (under the 90s cap)
- Follow-up fix (Problems.md #17): intermittent 90s timeouts traced to Lean's `matplotlib` font cache rebuilding every ephemeral container run; fixed via `MPLCONFIGDIR` pointed at a persistent `.matplotlib_cache/` directory
- `tests/test_lean_backtest_ml_coverage.py::LEAN_BACKTEST_TIMEOUT_SECONDS` bumped 7200→14400

**Verification:**
- New regression test: `tests/test_train_pipeline.py::test_ensure_derived_crypto_daily_series_merges_with_existing_backfill`
- Real `lean backtest .` diagnostic runs (stopped early) confirmed the #16/#17 fixes; the full multi-hour 3-year 20-asset backtest was deliberately left for manual, out-of-band execution

## `aq fetch` — ad-hoc Yahoo Finance ticker fetch

**Summary:** New `aq fetch <crypto|stock> --ticker ... --start ... --end ... [--apply]` CLI command, requested by the user, to replace the multi-step manual process (run `yfinance_backfill.py`, inspect output, hand-edit `config.json`) needed to onboard a new ticker.

**Shipped:**
- New `data_pipeline/fetch.py`, reusing `yfinance_backfill.py`'s config-independent pure functions (`fetch_yahoo_ohlcv`, `scale_for_lean`, `write_lean_zip`) unchanged; `ASSET_CLASS_CONFIG` dict drives the Lean path per asset class
- Deliberate policy difference: unlike `yfinance_backfill.py` (never touches config.json), `fetch.py` writes `config.json` on `--apply` since adding a new ticker is its whole purpose; if the ticker already has a config entry, `fetch.py` leaves it alone and points at `yfinance_backfill.py` instead
- `aq_cli.py`: new `cmd_fetch` (in-process, no subprocess, alongside `trade-lock`); new `_iso_date` argparse validator
- Required packaging fix: `pyproject.toml`'s `packages` list gained `"data_pipeline"` — same `ModuleNotFoundError` bug class as a prior `execution` fix
- New tests: `tests/test_fetch.py` (13 tests, `fetch_fn` injected, never real yfinance) + 7 wiring tests in `tests/test_aq_cli.py`

**Verification:**
- Manually verified end-to-end with real yfinance calls (`DOGEUSD`, `MSFT`): dry run writes nothing, `--apply` writes a correctly-scaled zip and config block, re-running `--apply` reports `already_exists`, `derivative` rejected by argparse; the packaging fix was verified via the *installed* `aq fetch --help`, not `python aq_cli.py`; test artifacts removed after verification

## Trade-frequency tuning — statistical/diagnostic backtest mode

**Summary:** A real 3-year 20-asset backtest produced only 12 filled trades due to compounding suppression across several gates plus two structural traps (a gate that fires once effectively never clears), so a new opt-in backtest-only bypass mode and several threshold loosenings were added purely for statistical/diagnostic evaluation.

**Shipped:**
- New opt-in flag `phase_v2.backtest.bypass_safety_gates` (default `false`), a standalone key separate from `aq trade-lock`; new `risk_controls.py::is_backtest_safety_bypass_active(runtime_mode, bypass_flag)` returns `True` only when `runtime_mode == "backtest"` and the flag is explicitly `true`
- Bypasses the sticky total-drawdown lock (`main.py::_refresh_risk_state()`) and the regime detector's `risk_off` drawdown branch (`main.py::_build_regime_payload()`, passes `float("inf")` instead of the real threshold) — the only two mechanisms affected; all other gates (liquidity/topology/cooldown/exposure, other regime branches) stay active
- Explicitly scoped to statistical/model-quality evaluation, not a live-representative equity curve — in live/paper mode both gates remain real, designed behavior
- Config-only threshold loosening: `phase6.risk.min_confidence_to_trade` 0.12→0.05; `phase5.backtest.buy_threshold_offset`/`sell_threshold_offset` 0.08→0.04 each; `phase6.risk.trade_cooldown_bars` 3→1; `phase_v2.liquidity.thin_participation_threshold` 0.002→0.01; `blocked_participation_threshold` 0.05→0.10; `phase9.portfolio.max_active_positions` 5→10; `max_crypto_exposure` 0.25→0.35
- `phase9.asset_quality.min_training_rows` 100→50: unlocked `ETHUSD`/`XRPUSD`/`ADAUSD` as training/trading-eligible (19/20 assets now training_eligible, only `AAA` remains observation-only — its usable data starts entirely after both training and validation windows)
- Deliberately out of scope: real short-selling (confirmed `main.py::_apply_signal`'s `sell` branch only ever calls `self.Liquidate()`); the hardcoded topology `ELEVATED_VOLATILITY_THRESHOLD = 0.45` left unchanged

**Verification:**
- New tests: `tests/test_risk_controls.py` (+4 for `is_backtest_safety_bypass_active`)
- The real Lean backtest with `bypass_safety_gates: true` confirming actual resulting trade count against the ~200 target was left for the user to run manually

## Real learned gating weights + learned topology wired into position sizing

**Summary:** Closed two gaps flagged as deferred by V3's completeness assessment: `moe/gating.py`'s gating network was still hand-tuned arithmetic, and the learned topology overlay (V2-17.5) computed per-symbol confidence/uncertainty but never reached an actual trade decision.

**Shipped:**
- New pure function `risk/position_sizing.py::topology_sizing_multiplier(...)`: a strict no-op (`1.0`) unless `topology_source == "learned"`, otherwise a bounded, continuous, shrink-only multiplier composed as a third factor in `build_dynamic_position_sizing()`'s existing chain — changes only trade size, never the trade decision itself. New config keys `phase_v2.dynamic_risk.topology_sizing_enabled` (default `true`), `min_topology_multiplier` (0.5), `max_topology_multiplier` (1.0)
- `moe/gating.py`: additive, always-falls-back real learned gating — new `GATING_MODEL_FEATURE_KEYS` (26-dim) and `build_gating_model_features()`; `build_gating_decision()` gains optional `gating_model`/`gating_feature_schema` params; on success `decision_source` becomes `"learned_gating"`; any failure silently falls back to the hardcoded blend. Wired via new `main.py::_load_gating_model()`, gated by `phase_v2.gating_network.learned_model_enabled` (default `true`)
- New offline trainer `train_gating.py` (sibling of `train_topology.py`): trains on the dataset's `validation` split (avoids stacking-circularity), replayed through exported models via `inference/exported_model.py::run_exported_model()`; evaluates on the `backtest` split; model is `AetherNet(26 → [16] → 1)` restricted to relu/layernorm; smoke-tested against real dataset (1,304 validation rows, 16,184 backtest rows), writes a valid model in ~90s. New config block `phase_v2.retraining.gating_training`
- Retraining pipeline: `retraining/artifacts.py` gained `OPTIONAL_GATING_FILES` + `check_gating_artifacts()`; `retraining/orchestrator.py` gained `train_gating()` + CLI subparser; `retraining/worker.py` calls it after `train_topology()`. `config.json`'s `promotion.active_artifact_files` extended
- New `aq train --gating-only` flag: writes a throwaway version-id then copies artifacts straight into active `ml/`
- Neural-network webui tab now shows gating: `monitoring/neural_network_state.py` reads `ml/gating_model.json`, reports a `"learned"` quality badge; `NeuralNetworkScene3D.tsx`'s render order gained `'gating'` (violet)

**Verification:**
- New tests: `tests/test_position_sizing.py` (+7), `tests/test_gating_network.py` (+5), `tests/test_train_gating.py` (8), extensions to `test_retraining_artifacts.py`/`test_retraining_orchestrator.py`/`test_retraining_worker.py`, `tests/test_aq_cli.py` (+3), `tests/test_neural_network_state.py` (+2 new, 2 rewritten). Full suite: 581 passed
- Problems.md #14 (Redis push in backtest mode) marked resolved — user confirmed no downstream process reads backtest-mode experience events
- `train_gating.py`/`aq train --gating-only` smoke-tested but its model was **not** installed into active `ml/` or promoted — user runs the real training/backtest themselves

## `aq config`/`aq lean` full read/write CLI + `analyzer/market_analyzer.py` real composite scoring

**Summary:** Added full read/write CLI access to `config.json`/`lean.json` (replacing hand-editing) and gave `analyzer/market_analyzer.py` a real, config-gated composite signal-quality score instead of pure if/elif single-field routing.

**Shipped:**
- `aq config`/`aq lean`: share one generic dispatcher `aq_cli.py::_dispatch_json_config_command()`, no hardcoded key list — dotted-path walker/setter (`_get_config_value`/`_set_config_value`/`_iter_leaf_paths`) operates on whatever's on disk
- `aq config` (bare) pretty-prints the file; `get <dotted.key>`, `set <dotted.key> <value>`, `keys [<prefix>]` for discoverability; `aq lean` is the identical tool for `lean.json`
- Deliberately unrestricted: `set` can target list/dict paths, value parsed as JSON first, falling back to string
- Safety via transparency: every `set` backs up to `<file>.json.bak` (gitignored) and prints old→new; type changes warn but still write
- Small fix: `aq retrain`'s stage `choices` list was missing `train_gating` even though the orchestrator subparser existed — added
- `analyzer/market_analyzer.py`: new `compute_signal_quality_score(confidence, regime_confidence, topology, liquidity)` — bounded [0,1] weighted composite (confidence 0.45, regime confidence 0.20, topology peer-support 0.20, liquidity friction 0.15), mirroring `moe/gating.py`'s scoring style
- `MarketAnalysisDecision` gains `signal_quality_score`/`signal_quality_breakdown`, always computed regardless of flag
- New flag `phase_v2.market_analyzer.use_composite_signal_score` (default `false`) — only when `true` does the composite score replace raw `confidence` in the `trade` gate (priority 7) and `simulate`-vs-`observe` split (priority 8); hard safety-override tiers (priorities 1-6) never affected

**Verification:**
- New tests: `tests/test_aq_cli.py` (+18: 12 for `aq config`, 6 for `aq lean`)
- Default `false` confirmed byte-identical: all 21 pre-existing `tests/test_market_analyzer.py` tests pass unchanged, zero edits
- New tests: `tests/test_market_analyzer.py` (+11: 7 pure-function tests, 1 confirming always-populated, 3 confirming flag-gated up/downgrade behavior)

## Multi-task prediction (direction + magnitude + volatility) — Phase 1

**Summary:** A root-cause investigation found every model (baseline + 4 experts) sat at backtest MCC 0.02-0.07 (noise) and Sharpe -0.758, and that `AetherNet` predicted only binary direction with no magnitude/volatility forecast for position sizing to use; this phase adds multi-task direction+magnitude+volatility prediction (a real sequence encoder, Phase 2, is explicitly scoped out).

**Shipped:**
- `train.py::export_multitask_architecture(model)`: new branching `{"trunk": [...], "heads": {direction, magnitude, volatility}}` export alongside unchanged `export_architecture()`; `inference/exported_model.py::run_exported_multitask_model()` + new `_softplus()` helper (guarantees volatility ≥ 0); `run_exported_model()` itself untouched
- New model `train.py::AetherNetMultiTask`: shared trunk + 3 heads (direction logit, magnitude regression, volatility via Softplus); new engineered column `target_volatility_next_day`; new `compute_regression_metrics()` (MAE/RMSE/bias)
- New `train_multitask.py` (repo root): reads the active dataset, same input feature set as baseline; loss = `BCEWithLogitsLoss(direction) + magnitude_loss_weight*MSE + volatility_loss_weight*MSE` (both weights default 1.0); writes `ml/versions/<id>/multitask_model.json`/`multitask_feature_schema.json`/`multitask_training_metrics.json`; exits 0 (not error) on insufficient data
- Runtime (`main.py`, additive): new optional artifact pair loaded by `_load_multitask_model()` (graceful fallback), gated by `phase_v2.multitask_model.enabled` (default `true`); `_run_multitask_model()` runs alongside `_run_model()`; new fields threaded into signal_payload, `MarketAnalysisDecision` (informational only), dashboard heatmap, runtime CSV export
- Position sizing (opt-in): `build_dynamic_position_sizing()` gains `predicted_volatility`/`use_predicted_volatility` params; `phase_v2.dynamic_risk.use_predicted_volatility` (default `false`) replaces backward-looking `rolling_volatility_20d` when true; new `volatility_source` field (`"rolling"`/`"predicted"`)
- Retraining pipeline: `OPTIONAL_MULTITASK_FILES` + `check_multitask_artifacts()`, `train_multitask()` orchestrator stage, new `aq train --multitask-only` flag, `Dockerfile.retraining_worker` gained `COPY train_multitask.py .` and (found via audit) a missing `COPY risk/ ./risk/` fix (Problems.md #20) — **image needs a rebuild**
- Scope decisions documented, not implemented this pass: regime/liquidity/topology as genuine model input features; gating does not blend per-expert magnitude/volatility (multitask model trained once at baseline scale, not per expert)

**Verification:**
- Smoke-tested end-to-end against real dataset (30,332 rows, 20 assets): backtest direction MCC 0.0174 (same noisy range as baseline/experts), magnitude MAE 0.0259, volatility MAE 0.0236
- Interpreter parity independently verified: `run_exported_multitask_model()` vs. a from-scratch PyTorch forward pass matched to ~1e-7 (float32)
- New tests: `tests/test_exported_model.py` (+7), `tests/test_train_multitask_architecture.py` (new, 8), `tests/test_train_multitask.py` (new, 8), `tests/test_position_sizing.py` (11 existing unchanged), `tests/test_market_analyzer.py` (32 existing unchanged), retraining test extensions (+13), `tests/test_aq_cli.py` (+3)
- Model was **not** installed into active `ml/`; no real Lean backtest run — left to the user
- Note: the two scope decisions above and Phase 2 were subsequently implemented later in the same session (see next entry)

## Phase 1 remainder + Phase 2: regime/liquidity/topology as inputs, per-expert multitask, sequence encoder

**Summary:** Same-session continuation implementing the two pieces scoped out of the prior entry (regime/liquidity/topology as genuine model inputs, per-expert multitask blending) plus Phase 2 (a causal-TCN sequence encoder), all verified against the real dataset.

**Shipped:**
- Regime/liquidity/topology as model inputs: `train.py::build_feature_dataset()` gains `add_regime_features()` (9 one-hot + 3 continuous, renamed `regime_signal_confidence`/`_trend_score`/`_risk_score` to fix a naming collision with `expert_datasets.py::annotate_dataset_with_regimes()`), `add_liquidity_features()` (`liquidity_log_dollar_volume`, `liquidity_spread_proxy`; deliberately excludes participation_rate/slippage), `build_topology_features_by_date()` (new, per-date cross-asset topology call, `embedding_iterations=1` since only correlation_strength/topology_risk are consumed). **Model input dimensionality: 30 → 48** — baseline, all 4 experts, gating, and multitask all retrained together
- `main.py` reordering: regime now computed once in `_build_model_input()` (was recomputed twice before); liquidity `spread_proxy` computed once and reused
- Real off-by-one bug found and fixed: `add_liquidity_features()` originally ran after `engineer_features()`'s dropna (which drops each asset's first raw row), silently missing the true first bar for roughly each asset's first `CROSS_SECTIONAL_WINDOW_BARS` rows vs. live `self.symbol_windows`; fixed by running it on the raw per-asset frame before `engineer_features()`. Verified via standalone parity script (ETHUSD's 6th row: mismatch before, exact match after)
- Per-expert multitask: `train.py::_train_expert_multitask()`/`_write_expert_multitask_export()` (mirrors `_train_expert_classifier()`) writes `ml/expert_models/<name>/multitask_model.json`; gracefully skips datasets lacking multitask columns (found via a real pre-existing test failure, fixed with a column-presence guard)
- `moe/gating.py::build_gating_decision()` gains `expert_magnitudes`/`expert_volatilities`/`baseline_magnitude`/`baseline_volatility` params, `final_magnitude`/`final_volatility` on `GatingDecision`; new `_weighted_blend()` helper returns `None` (not `0.0`) when no expert has data. `main.py`'s magnitude/volatility now come from the full gating blend instead of the single baseline-scale multitask model
- Phase 2 sequence encoder: `inference/exported_model.py` gains 4 new primitives (`_softmax`, `_layernorm_axis`, `_conv1d_causal` — verified 9.1e-8 vs real `nn.Conv1d` — `_multihead_attention` — verified 5.6e-8 vs real `nn.MultiheadAttention`, infrastructure only, not wired to a trained export this pass) and `run_exported_sequence_multitask_model()`
- New `train.py::AetherNetSequenceMultiTask`: causal TCN trunk (dilation doubling), chosen over a Transformer for bit-for-bit verifiability; new `train_sequence.py` writes `ml/versions/<id>/sequence_model.json` etc.; smoke-tested (30,193 rows, ~3.5 min, backtest direction MCC 0.0219 — same noisy range, proving pipeline not fixing noise)
- `main.py` integration additive/informational-only: new `self.symbol_feature_history` buffer (deque maxlen=30, separate from `symbol_windows`); `_run_sequence_model()` output threads into `signal_payload`/dashboard only — does not feed gating/analyzer/sizing this pass
- Retraining pipeline extended for both pieces: `OPTIONAL_SEQUENCE_FILES`, `train_sequence()` stage, `aq train --sequence-only`, `Dockerfile.retraining_worker` gains `COPY train_sequence.py .`

**Verification:**
- Full suite green after every stage; one real regression found and fixed (`tests/test_expert_models.py` column-presence gap)
- Real end-to-end runs: full dataset rebuild (~1m47s, up from ~28s pre-session), baseline+expert retraining, gating/multitask/sequence retraining, full interpreter smoke test chaining every model
- New tests: `tests/test_train_cross_sectional_features.py` (new, 13), `tests/test_gating_network.py` (+7), `tests/test_exported_model.py` (+11), `tests/test_train_sequence_architecture.py` (new, 13), retraining/CLI test extensions (+~20)
- `Dockerfile.retraining_worker` needs a rebuild; no real Lean backtest was run (per established preference); baseline/experts/gating/multitask/sequence all retrained on the final 48-dim feature set and installed into active `ml/`

## Multitask/sequence pipeline integration — closing the 7 remaining gaps

**Summary:** Follow-up pass closing 7 open integration points between the new multitask/sequence model layer (built in the two prior entries) and the rest of the stack.

**Shipped:**
- `tests/test_lean_backtest_ml_coverage.py` gains 4 tests exercising a real `lean backtest .` run against the 48-dim pipeline, baseline multitask, per-expert multitask contribution to `moe_gating.final_magnitude`, and the sequence model
- `experience/redis_queue.py::build_experience_event()` gains optional `sequence_model` field (defaults `None`); `main.py` passes the already-computed prediction through; no Postgres migration needed (JSONB column)
- Neural-network webui extended to all 12 real networks: `monitoring/neural_network_state.py::_parse_network_export()` dispatches flat vs. branching `{trunk, heads}` shapes; `_weight_stats()`'s flatten made recursive for `conv1d_causal`'s 3D weights; `NeuralNetworkScene3D.tsx`'s new `headColumnsFor()` expands each multitask/sequence network into per-head diagram columns; `NETWORK_ORDER` extended with 6 new names (previously a silent filter, Problems.md #19); stale "gating has no learned weight matrix" claim in `architecture.md` corrected
- `development/architecture.md` updated: all 12 networks documented, "model input dimensionality is 48, not 30" note, gating magnitude/volatility blend Follow-up, new Phase 2 Sequence Encoder Contract section, Redis schema updated
- Retraining promotion-cycle tests confirm `OPTIONAL_MULTITASK_FILES`/`OPTIONAL_SEQUENCE_FILES` survive `commit()`'s hashing; `development/infrastructure.md`'s runbook now lists the full stage order and notes per-expert multitask artifacts are not tracked by `retraining/artifacts.py`
- Problems.md #21 documented (not benchmarked): forward-pass count went from 5 to 11 per symbol per bar — both new model families are informational-only or off-by-default, so not measured
- README architecture diagrams updated to match prose
- One item, `requirements-retraining-worker.txt` already covering `train_sequence.py`'s deps, needed no action (confirmed, not fixed)

**Verification:**
- `pytest tests/` full suite green; `tests/test_lean_backtest_ml_coverage.py`'s new assertions self-skip when Lean CLI unavailable
- `npx tsc -b --noEmit` in `webui/` — clean, no type errors

## Phase 2 sequence encoder wired into the gating decision (optional, off by default)

**Summary:** Closes the scope boundary restated by every prior entry — the sequence encoder was informational-only; this pass wires it into gating specifically (the one funnel all other prediction sources pass through), while deliberately keeping the market analyzer and position sizing without a second direct sequence input.

**Shipped:**
- `moe/gating.py::build_gating_decision()` gains `sequence_prediction` (the `{direction, magnitude, volatility}` dict) and `sequence_weight` (default `0.0`), applied last as the same anchor-blend shape `baseline_weight` uses; new `GatingDecision.sequence_blended: bool`
- Off by default, matching `use_predicted_volatility`'s convention — byte-identical behavior until `phase_v2.gating_network.sequence_weight` is set above `0.0` (e.g. `0.2`, same order of magnitude as `baseline_weight`'s default `0.25`)
- `main.py`: new `self.gating_sequence_weight`; runtime state's `config.model.sequence.informational_only` flag is now dynamic (`self.gating_sequence_weight <= 0.0`) instead of hardcoded `True`
- New config key `phase_v2.gating_network.sequence_weight: 0.0`
- Docs updated: `moe/README.md` full design writeup; `inference/README.md`, `analyzer/README.md`, `risk/README.md`, `development/architecture.md`'s Gating Network Contract and Phase 2 Sequence Encoder Contract get Follow-up notes correcting now-stale "informational only" claims

**Verification:**
- New tests in `tests/test_gating_network.py`: zero-weight no-op, `None` prediction with positive weight, full blend arithmetic, blending on top of `"learned_gating"` decision_source
- `pytest tests/test_gating_network.py` — 23 passed (18 pre-existing + 5 new); full-suite `aq test` run pending

## Frontier-model edge investigation — target redesign, real bug fixes, cross-sectional ranking (model input 48 → 59)

**Summary:** Every model (baseline, 4 experts, multitask, sequence encoder) sat at backtest MCC 0.017-0.07 on next-day binary direction — noise. This session fixed confounding data/pipeline bugs, redesigned targets (5d/20d horizons, cross-sectional percentile-rank), added peer-return and technical-indicator features, and surfaced rank-IC end-to-end. Details in `development/Problems.md` #22-26.

**Shipped:**
- Phase 1 bug fixes: `volume_change_1d` clamped `[-1.0, 20.0]`; winsorization + `±scaled_feature_clip_sigma` (default 10.0) in `train.py::fit_and_apply_scaler()`, persisted to `ml/scaler_stats.json` (Problems.md #23). Real split/dividend adjustment via `train.py::load_factor_file()`/`apply_split_adjustments()` reading Lean factor files (train-only gap; Lean's own feed was already correct) (Problems.md #24). New `assess_regression_quality()` gate wired into `train_multitask.py`/`train_sequence.py` (Problems.md #25). `inference/exported_model.py::resolve_sequence_window_size()` fixes a `window_size` compat gap (Problems.md #26). Fixed 7 of 10 `test_retraining_worker.py` tests that silently ran real training subprocesses for up to ~30 min each (Problems.md #22).
- Phase 2: widened `config.json` validation window to `2018-01-01→2018-12-31` and backtest to `2019-01-01→2021-03-31` (old 3-month validation window gave too few non-overlapping 5d/20d observations). Pre/post-change backtests not directly comparable (deliberate).
- Phase 3: new `target_return_5d/20d` and `target_direction_5d/20d` targets; new `AetherNetMultiTaskHorizons`/`AetherNetSequenceMultiTaskHorizons` sibling model classes (experts/baseline/gating stay 1d-only); masked loss/metric helpers (`masked_bce_with_logits_loss`, `masked_mse_loss`, etc.) and per-head tuned thresholds (`find_optimal_masked_threshold()`) to avoid a horizon head silently collapsing to always-positive.
- Phase 4: `build_cross_sectional_rank_targets()` (per-date percentile rank, min universe size 10) producing `target_rank_5d/20d`; new `rank_5d`/`rank_20d` heads; new `compute_rank_ic()` (Spearman rank-IC, mean/std/t-stat/non-overlapping-stride variant). Informational-only this pass — not wired into gating/sizing. Documented promotion criterion: mean rank-IC > 0.02, t-stat > 2 on non-overlapping dates.
- Phase 5: `topology/market_topology.py` gains `TopologyNode.top_peers`/`top_peer_returns` + `rank_correlated_peers()`; new `phase_v2.topology.top_peers_n` (default 3). Offline/runtime both emit `peer_rank1/2/3_return_1d` + `peer_mean_return_1d`. Model input 48 → 52.
- Phase 6: new `features/technical_indicators.py`, shared by `train.py` and `main.py`: `rsi_14`, `atr_pct_14`, `bollinger_pctb_20`, `volume_zscore_20` (short-lookback), `macd_histogram_norm`, `dist_52w_high` (long-lookback, new `main.py::self.symbol_long_windows` deque maxlen=260), `cs_momentum_rank_20` (cross-sectional). Model input 52 → 59.
- Phase 7: `monitoring/neural_network_state.py::NetworkSummary` gains `horizon_mcc`/`rank_ic`/`regression_quality`; webui `NeuralNetworkStatsPanel.tsx` renders the new block.
- Phase 8: full R2 retrain on the final 59-dim feature set (baseline+experts, gating, multitask, sequence).

**Verification:**
- Real result: sequence model backtest `rank_20d` mean IC 0.073, t-stat 4.40 (561/546 dates); multitask `rank_20d` mean IC 0.037, t-stat 2.10. 1d-direction MCC stayed at noise level throughout, as predicted.
- `pytest tests/` — 817 passed, 11 pre-existing Docker-unavailable errors (unrelated). `npx tsc -b --noEmit` clean. Real end-to-end dataset rebuild + full retrain performed; no real `lean backtest .` run this session (user's own manual step per convention).

## Follow-up — rank_20d wired into position sizing

**Summary:** Closes the informational-only gap from Phase 4 above for `rank_20d`, the one signal with a statistically significant full-series result, wiring it into position sizing as an optional off-by-default factor.

**Shipped:**
- New `risk/position_sizing.py::rank_sizing_multiplier()`: bounded, direction-preserving, `multiplier = min_rank_multiplier + (max_rank_multiplier - min_rank_multiplier) * rank_prediction` (defaults 0.75-1.25, median rank = no-op). `PositionSizingDecision` gains `rank_multiplier`/`rank_sizing_reason`.
- `main.py` extracts `predicted_rank_20d` (sequence-preferred, multitask-fallback) and threads it into dynamic sizing; surfaces it on `signal_payload`.
- New config: `phase_v2.dynamic_risk.rank_sizing_enabled` (default `false` — non-overlapping subsample t-stat only 1.20 vs. 4.40 full-series, not yet independently significant), `min_rank_multiplier` (0.75), `max_rank_multiplier` (1.25).

**Verification:**
- `tests/test_position_sizing.py` (+9 new tests covering disabled/median/top/bottom cases, sizing scale-up respecting `max_position_weight`, short-direction sign preservation). `pytest tests/test_position_sizing.py` — 19 passed.

## 5/10 → 9/10 frontier-readiness roadmap (Phases 1–7)

**Summary:** Follow-up to the rank_20d wiring above (rated 5/10 since the signal wasn't independently significant on the then-20-asset universe). This 7-phase pass closes that gap and other structural weaknesses.

**Shipped:**
- **Phase 1 — Bond sleeve + macro features**: universe 20 → 30 assets (10 bond ETFs: SHY/IEF/TLT/AGG/LQD/HYG/TIP/MBB/EMB/MUB, registered as `security_type: "equity"`). New `features/macro_features.py`: `macro_yield_curve_slope_proxy` (TLT-SHY 20d momentum spread), `macro_credit_spread_proxy` (HYG-LQD), `macro_crypto_risk_appetite_proxy` (BTCUSD 20d momentum). Model input 59 → 62.
- **Phase 2 — Validation rigor**: `train.py::purged_embargoed_folds()`, `split_into_non_overlapping_eras()`, `bootstrap_ic_confidence_interval()`, `assess_ranking_quality()` (code-enforced `promotable`/`watchlist`/`not_promotable` gate: non-overlapping t-stat < 2.0, bootstrap CI lower bound < 0, or any single sign-contradicting era fails it), `assess_ranking_quality_from_predictions()`. Real bug found and fixed (Problems.md #27): era/fold functions assumed datetime input but real callers pass stringified dates, causing `TypeError`; fixed via explicit `pd.to_datetime()` coercion, new regression tests using real object-array string dates.
- **Phase 5 — Sector-neutral ranking**: new `data/reference/sector_mapping.json`, `train.py::load_sector_mapping()` (graceful "Unknown" fallback). New `target_sector_neutral_rank_5d/20d` targets and `sector_neutral_rank_20d` head (purely additive, existing rank heads untouched).
- **Phase 3 — Stage-2 long/short book** (the one direction-setting departure): new `portfolio/` package, `book_construction.py::build_rank_based_book()` (top-N long/bottom-N short by `predicted_rank_20d`). `main.py::on_data()` restructured into two passes; provably byte-identical when off (default `phase_v2.portfolio_book.enabled: false`). Added real short-selling (`"short"` signal branch, `main.py::_apply_signal()`), `max_short_exposure` cap (default 0.30). Real gap found and fixed: `analyzer/market_analyzer.py`'s six safety-tier checks only gated on `{"buy","sell"}`, missing `"short"` entirely — extended to all three.
- **Phase 4 — Walk-forward retraining**: `train.py::generate_walk_forward_windows()` (rolling/expanding), `summarize_walk_forward_run()`, new `python train.py --walk-forward --step-days N --mode {rolling,expanding}` CLI. Config `phase_v2.retraining.walk_forward` (`enabled: false`). Infrastructure built/tested (9 tests, verified against real `common_window` producing 6 expanding windows) but a full multi-window run was NOT executed (~45 min/window).
- **Phase 6 — Production rank-IC decay monitoring**: `experience/redis_queue.py::build_experience_event()` gains `resolved_predicted_rank_20d`/`close_price`. New `performance/rank_ic_monitor.py::compute_realized_rank_ic_observations()`/`compute_production_rank_ic()`. New `performance/triggers.py::rank_ic_decay_trigger()`, registered in `_MODEL_QUALITY_TRIGGERS`/weight 3 in `retraining/planning.py`.
- **Phase 7 — Live-loop closure groundwork**: confirmed `paper_readiness_report.py`/dashboard wiring already correct; new `execution/paper_readiness_scheduler.py::PaperReadinessScheduler` (periodic loop, mirrors `TriggerWorker`), new profile-gated `docker-compose.yml` service.

**Verification:**
- Real retrain (30 assets, 62 features, 46,242 rows): `rank_20d` (multitask) clears its own promotion gate for the first time — non-overlapping t-stat 2.52 (vs. 2.0 threshold), bootstrap 95% CI [0.035, 0.308] (all positive), zero opposite-sign eras across 9. Full-series mean IC 0.173, t-stat 10.40. `rank_5d` not promotable (t-stat 2.81, but 1/10 eras flip sign). `sector_neutral_rank_20d` not promotable (t-stat 3.40, 2/9 eras flip sign).
- Sequence model retrain did NOT complete this session — `numpy.core._exceptions._ArrayMemoryError` building the (rows,30,72) tensor, consistent with a session-specific memory ceiling. Active `ml/sequence_model.json` remained the prior 59-input model, confirmed to degrade safely (existing exception handling + fallback to multitask's rank_20d).
- `pytest tests/` — 928 passed, 11 pre-existing Docker-unavailable errors, 0 failures. `npx tsc -b --noEmit` clean.

## Follow-up — closing the roadmap's CLI/webui/backend wiring gaps

**Summary:** An audit of the 5/10 → 9/10 roadmap found backend logic for three phases existed but was unreachable from any user-facing surface; all three fixed.

**Shipped:**
- `rank_ic_decay_trigger()` was backend-only (unit-tested, never invoked). `performance/triggers.py::evaluate_all_triggers()` gained optional `rank_ic_observations=` kwarg; `performance/trigger_worker.py::TriggerWorker.run_once()` now builds and passes it every cycle. New config: `rank_ic_decay_rolling_window` (100), `rank_ic_decay_min_mean_ic` (0.02), `rank_ic_decay_min_t_stat` (2.0), `rank_ic_resolution_horizon_days` (20).
- `aq train` had no `--walk-forward` flag despite `train.py` supporting it natively — added the 3 flags as straight passthrough (no copy-to-active-`ml/` step).
- Two Phase 2/3 fields never reached the webui: `{head}_ranking_quality` (promotion-gate verdict) and `portfolio_book_role`. Fixed: extended extractor + `NetworkSummary`/`NeuralNetworkModel` with `ranking_quality` field + new "20d promotion gate" badge in `NeuralNetworkStatsPanel.tsx`; added `portfolio_book_role` to `Signal` type + new "Book Role" column in `AssetSizingTable.tsx`. New Badge tones: `promotable`/`not_promotable`/`long`/`short`/`flat`.

**Verification:**
- `tests/test_trigger_worker.py` (+1), `tests/test_triggers.py` (+2), `tests/test_aq_cli.py` (+3), `tests/test_neural_network_state.py` (extended).
- `pytest tests/` — 934 passed, 11 pre-existing Docker-unavailable errors, 0 real failures. `npx tsc -b --noEmit` clean.
- Final rating after this pass: **9/10** (up from 7/10).

## Multi-Asset-Class Support — Bonds, Futures, Options + Interactive Brokers Integration

**Summary:** V3's headline scope item — futures and options trading alongside equity/crypto/bonds, with real Black-Scholes greeks and margin-based futures risk sizing (not a bolt-on to the equity/crypto sizer), plus bonds moving to real yield-curve/duration-aware treatment. Interactive Brokers is the data source, toggled end-to-end via `phase_v2.ib.enabled` (default off, system works exactly as before with IB disabled).

**Shipped:**
- New modules: `data_pipeline/fred_backfill.py` (no-key FRED CSV backfill), `features/bond_features.py` (yield-curve level/slope/curvature, credit-spread level, `empirical_duration_beta()`), `data/reference/futures_contract_specs.json` + `risk/futures_risk.py` (`build_futures_position_sizing()`, contract-count-based, `rollover_due()` diagnostic-only), `features/options_greeks.py` (real Black-Scholes-Merton, Newton-Raphson+bisection IV), `portfolio/options_strategy.py` (single-leg greeks-sized construction, delta scales with model confidence, vega-budget-capped), `data_pipeline/ib_backfill.py` (offline historical-bars-to-Lean-zip via `ib_insync`, dev-only, raises `IBNotConfiguredError` when disabled), `risk/asset_class_router.py::route_position_sizing()` (single dispatch point, adapts all asset classes onto the same `PositionSizingDecision` shape), `features/derivatives_macro_features.py` (futures term-structure slope, options put/call ratio/IV-skew, neutral 0.0 by default per Problems.md #29).
- New `asset_class` field on `config.json` universe entries (distinct from Lean's `security_type`; falls back to `security_type` when absent). `train.py::add_asset_class_context_features()` (5-column one-hot, reuses `"asset_"` prefix so existing manifest filter picks it up). `phase1.features.input_set` 30 → 38 features (breaking change requiring full retrain).
- New `phase9.portfolio` exposure caps (`max_bond_exposure` 0.30, `max_futures_exposure` 0.20, `max_options_exposure` 0.10). Bug fix: `main.py::_asset_class_exposure()` previously keyed on raw `security_type`, silently counting bond ETFs as equity exposure.
- `main.py::_add_asset()` gained `"future"`/`"option"` branches; futures execute via `MarketOrder(symbol, contract_count)` instead of `SetHoldings()`. Options order placement deliberately out of scope this pass (Problems.md #29) — sizing/exposure accounting runs, no order placed.
- New CLI: `aq fetch futures --ticker ... --expiry ...`, `aq fetch options --ticker ... --expiry ... --strike ... --right ...`, `aq ib status`.
- Real bug found and fixed: portfolio book's `"short"` signal was silently zeroed to no position (Problems.md #28), never observed since the book is off by default.

**Verification:**
- New: `test_options_greeks.py` (22), `test_fred_backfill.py` (17), `test_bond_features.py` (14), `test_futures_risk.py` (19), `test_options_strategy.py` (16), `test_ib_backfill.py` (26, fully mocked), `test_asset_class_router.py` (11), `test_derivatives_macro_features.py` (15), plus 3 more train-side test files. `pytest tests/` — 1106 passed, 11 pre-existing Docker-unavailable errors, 0 real failures.
- Bond features spot-verified: TLT's duration beta (-0.181) ~17x SHY's (-0.011), matching real-world long- vs. short-duration hierarchy. Black-Scholes verified against Hull's textbook (call ≈ 4.76), put-call parity exact to 1e-9, IV round-trip recovers 0.35 to 1e-4.
- Full model zoo retrain on 38-feature/85-input dataset (46,242 rows): baseline val accuracy 0.5165, gating balanced accuracy 0.5000, multitask direction MCC 0.0249 (rank_20d t-stat 3.17), sequence direction MCC 0.0055 (rank_20d t-stat 2.34, sector_neutral_rank_20d t-stat 3.79). Every head across both trainers marked `not_promotable` uniformly on `era_sign_instability` — not a regression, consistent with prior small-sample-era noise; `rank_sizing_enabled`/`portfolio_book_enabled` correctly remain off.
- Environment note: ~4GB RAM machine; sequence tensor build (85 features, up from 59) OOM'd once while Docker Desktop was also running; resolved by stopping Docker.

## Infrastructure/latency pass — `aq test` speed, inference-hot-path profiling, CI Docker cache

**Summary:** Research-first pass (3 parallel Explore agents before any code change) into four infrastructure/latency requests. Full writeup in `development/Problems.md` #31.

**Shipped:**
- `aq test` was silently running a real `lean backtest .` on every invocation (its `skipif` checked binary availability, not intent — this repo's `.venv` has a real Lean CLI, so it always ran, taking over an hour). Fixed via new `lean_backtest` pytest marker (excluded by default, opt-in via `aq test --lean`/`--full`) plus 11 combinable per-subsystem flags (`--cli`, `--risk`, `--portfolio`, `--features`, `--data-pipeline`, `--webui`, `--ml`, `--retraining`, `--notifications`, `--storage`, `--live`) and opt-in `--parallel` (pytest-xdist, off by default given this machine's earlier OOM). Default `aq test` now runs 1153 tests in under a minute.
- New `scripts/profile_inference.py` (no prior profiling harness existed). Found and fixed two hot-path costs: `inference/exported_model.py::_conv1d_causal()`'s per-timestep Python loop rewritten as one vectorized fancy-index-gather-plus-batched-einsum call; `main.py`'s 4-expert loop batched into one NumPy call per layer (new `run_exported_models_batched()`/`run_exported_multitask_models_batched()`) with safe fallback to the per-model loop when architectures don't match.
- CI Docker builds never cached: `.github/workflows/release.yml`'s `docker/build-push-action@v6` step had no cache configured; added `cache-from: type=gha` / `cache-to: type=gha,mode=max`.
- Documentation audit: linked `features/`, `portfolio/`, `backtests/` READMEs into the main README; added a new `scripts/` README; test-count prose now shares the `AQ:TEST_COUNT` marker mechanism the badge already used.

**Verification:**
- Net latency win: **448.4s → 290.6s, -35.2%** on the harness's 10,000-iteration synthetic workload. Numba JIT evaluated and not added (remaining costs already vectorized). Parity-tested: new batched-vs-individual tests in `tests/test_exported_model.py` (synthetic + real `ml/expert_models/*` exports); conv1d rewrite verified bit-identical across 200 random-parameter fuzz trials.
- `pytest tests/ -m "not lean_backtest"` — 1153 passed, 11 deselected, 0 failures, re-run after every inference-path change. `test_exported_model.py` alone: 41 passed (13 new). `test_aq_cli.py` alone: 103 passed. Not verified this pass: a real `lean backtest .` run or real IB connection (user's manual step).

## Latency deep-dive follow-up — weight/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension

**Summary:** Direct follow-up after re-profiling the already-batched/vectorized hot path found `numpy.asarray()` conversions as the largest remaining cost. Full writeup in `development/Problems.md` #32.

**Shipped:**
- New `convert_state_dict_arrays()` converts a model export's `state_dict` from Python lists to NumPy arrays once at load time (every downstream `np.asarray()` call becomes a no-op). New `build_layer_stacks()`/`BatchedLayerStackCache`/`build_models_batched_cache()` (+ multitask siblings) precompute batched weight/bias stacks once instead of rebuilding via `np.stack()` every call. Zero API/behavior change; 14 new parity tests.
- Profiling harness rebuilt: inputs pre-generated outside the profiled region (original harness measured its own `random.uniform` overhead); added independent wall-clock tail-latency reporting (p50/p95/p99/max/mean). New `aq profile` CLI command.
- Opt-in per-symbol multiprocessing (`phase_v2.inference_parallelism.enabled`, default `false`): `main.py::on_data()` Pass 1 restructured into three phases so the middle (inference) phase can optionally run across a persistent `ProcessPoolExecutor`. New `inference/parallel_inference.py::run_symbol_inference()` (picklable worker function). Shipped default-off — per-symbol inference is now fast enough (~4.8ms) that IPC overhead may exceed any win; never enabled for this pass's own backtest verification (Windows `spawn` inside Lean's embedded Python is untested territory).
- New C++/pybind11 extension (switched from an initially-proposed Rust approach): `cpp_inference_ext/` package accelerating `_linear_batched()`. Installed MSVC Build Tools from scratch via `winget`. Wired into `inference/exported_model.py` as an optional accelerated path (deferred import, falls back to NumPy on any failure, never a hard dependency). Two real bugs found and fixed: (1) source folder was originally named identically to the module it builds (`cpp_inference/`), silently shadowing the real installed extension as an empty namespace package; (2) extension was first installed into system Python, not the project's `.venv`, making an early comparison silently measure the NumPy fallback both times.

**Verification:**
- **Measured: 448.4s → 48.4s, -89.2%** on the same 10,000-iteration workload (mean per-symbol-bar latency ~44.8ms → 4.83ms) from weight/stack caching alone. C++ extension added a further **-16.7% and -40.9%** across two paired comparisons (real, modest, noisy in magnitude — small matrix sizes limit compiled-loop benefit).
- Full non-lean suite green throughout, re-run after each phase. New: `tests/test_profile_inference.py` (13), `tests/test_parallel_inference.py` (9, including a real `ProcessPoolExecutor` round-trip). `tests/test_exported_model.py` extended with 14 caching-parity tests. See Problems.md #32 for the C++ extension's exact build outcome and final real `lean backtest .` result.

## Execution/risk realism — real `SlippageModel` wired to fills

**Summary:** `liquidity/market_liquidity.py`'s real per-bar price-impact + spread estimate was computed every bar purely to drive sizing/routing decisions and then discarded — no Lean security ever had a `SlippageModel` attached, and `simulate_fill()` always used `slippage_bps=0.0`. Every backtest/observation-mode run reported systematically too-good fills.

**Shipped:**
- `execution/order_gate.py` gained `slippage_amount()` (pure bps→price math), `resolve_slippage_bps()` (lookup + clamp to `MAX_LIQUIDITY_SLIPPAGE_BPS`=500bps), `resolve_fill_slippage()` (composes both).
- `main.py` gained `_LiquidityAwareSlippageModel`, a thin Lean `ISlippageModel` adapter attached via `SetSlippageModel()`, reading a per-symbol bps dict refreshed every bar.
- `experience/simulated_portfolio.py::enter_long()` gained optional `slippage_bps` parameter, now populated from the same estimate everywhere instead of the old implicit zero.
- Design decision: combined impact+spread estimate used (not impact alone) since Lean's fill model has no bid-ask awareness — documented in `execution/README.md`.
- Follow-up: made both judgment calls (round-trip vs. impact-only source, 500bps clamp) configurable via `phase_v2.liquidity.fill_slippage.{source,max_bps}`, settable via `aq config set`. New `liquidity_cost_fraction()`/`resolve_fill_slippage_source()`.

**Verification:**
- 12 new tests (`test_order_gate.py`, `test_simulated_portfolio.py` including a parity test that default behavior is byte-identical to explicit `slippage_bps=0.0`). Lean-side adapter class not unit-testable in isolation (main.py can't be imported outside Lean's runtime) — logic lives in pure, tested `order_gate.py` functions instead. See Problems.md #33.
- Follow-up: 13 new tests (10 pure-function, 3 CLI-reachability).

## Real limit-order support — every tradable asset class, config-gated

**Summary:** Closed the other half of the prior entry's gap — all 5 order call sites (option buy, future buy/short, equity/crypto/bond buy/short) were market-fill only. Added real `LimitOrder()` support, config-gated (`phase_v2.limit_orders`, default off), for every asset class.

**Shipped:**
- New pure functions in `execution/order_gate.py`: `resolve_limit_price()` (buy limits below reference, sell/short above, offset by half the liquidity spread estimate) and `classify_order_status()` (isolates the one place this pass guesses at Lean's real `OrderStatus` enum spelling).
- `main.py` gained `_try_submit_limit_order()` (shared routing helper, no-op when disabled), `on_order_event()` (Lean's fill callback — stamps trade cooldown at confirmed-fill time, not order-placement time), `_process_pending_limit_order_timeouts()` (per-bar stale-order sweep, per-asset-class fallback-to-market policy: equity/crypto/bond default on, future/option default off).
- All 5 config knobs (`enabled`, `asset_classes`, `offset_multiplier`, `unfilled_timeout_bars`, `fallback_to_market_on_timeout`) settable via existing generic `aq config set`.
- Two real sign/keying bugs caught and fixed during implementation (not left for backtest to find): a naive `is_buy`-derived sign transform would have flipped already-correctly-signed futures quantities; option pending-order entries initially recorded the wrong symbol under the key `last_trade_bar_by_symbol` reads from. See Problems.md #34.

**Verification:**
- 16 new tests (12 pure-function in `test_order_gate.py`, 4 CLI reachability in `test_aq_cli.py`). Lean-side routing/callback methods not unit-tested in isolation (same `main.py` constraint) — not yet run against a real Lean backtest.

## Liquidate positions when an asset class gets disabled (+ 2 stale doc fixes)

**Summary:** `phase_v2.futures_risk.enabled`/`phase_v2.options_risk.enabled` flipping off correctly zeroed a position's sizing but never liquidated an already-open position from before the flag flipped, leaving a stale position forever.

**Shipped:**
- New pure `risk/asset_class_router.py::resolve_asset_class_enabled()`/`should_liquidate_disabled_asset_class_position()`.
- New `experience/simulated_portfolio.py::SimulatedPortfolioState.exit_using_last_known_price()`.
- New `main.py::_liquidate_positions_for_disabled_asset_classes()` per-bar sweep, anchored right after `_refresh_risk_state()`. Only ever applies to futures/options (equity/crypto/bond have no enable flag).
- Fixed two stale doc comments (`main.py`, `portfolio/README.md`) claiming options order placement was still a non-goal — false since the limit-order entry above.

**Verification:**
- 7 new tests (4 in `test_asset_class_router.py`, 3 in `test_simulated_portfolio.py`). Lean-side sweep method not unit-tested in isolation (same `main.py` constraint) — one real-backtest-only item, see Problems.md #35.

## Extended latency profiling beyond inference — found topology to be a much larger per-bar cost than inference itself

**Summary:** New per-subsystem profiling harness measured the per-bar cost of regime, topology, liquidity, gating, analyzer, and indicator primitives — subsystems the existing inference profiler never covered.

**Shipped:**
- New `scripts/profile_subsystems.py` (sibling to `scripts/profile_inference.py`, reuses its `percentile()`/`summarize_durations()`).
- New `aq profile --<subsystem>` flags, combinable, following the `aq test --cli --risk` convention.
- `main.py::_build_model_input()` itself stays unprofiled (documented partial-coverage choice); its pure indicator primitives are profiled instead.
- `profile_subsystems.py`'s `--iterations` default forced to 200 (not 10,000); `aq_cli.py`'s `--iterations` default changed to `None` so each script's own default applies independently.

**Verification:**
- Real finding: `build_market_topology()` costs ~500-600ms per call at the real ~30-symbol universe — comparable to or larger than the entire per-symbol inference total across the whole universe.
- 14 new tests (7 `test_profile_subsystems.py`, 7 `test_aq_cli.py`), 1 pre-existing test updated. No real-backtest-only risk — all profiled code is pure Python. See Problems.md #36.

## Investigated inference tail latency (p99 3-5x p50) — real GC-pause contribution confirmed

**Summary:** Diagnostic investigation into why inference p99 latency runs 3-5x p50, isolating GC pauses as a real contributor to worst-case tail latency.

**Shipped:**
- Resolved a discrepancy in `scripts/profile_inference_output.txt` (3 fresh paired runs, identical call counts, 2x wall-time variance) — confirmed machine load, not a regression.
- New `bucket_durations_by_iteration_index()` + `--bucket-report` ruled out a warmup effect (p50 flat across all 10 buckets).
- New `--no-gc` flag isolated GC pauses as a driver of worst-case (max) tail latency: -66% and -95% in two independent paired runs, p50 unaffected.
- `gc.freeze()` after model load documented as a candidate future tuning knob — not implemented this pass (needs real-backtest validation of interaction with Lean's .NET/Python GC boundary).

**Verification:**
- 10 new tests (6 `test_profile_inference.py`, 4 `test_aq_cli.py`). Full investigation writeup in Problems.md #37.

## 2-leg vertical spread selection for options (single-leg stays the default)

**Summary:** Added conservative, explicitly-scoped-in multi-leg options support (call/put verticals only) after entry #29 had left multi-leg as a non-goal; straddles/strangles/condors/butterflies remain out of scope.

**Shipped:**
- New `portfolio/options_strategy.py::OptionsSpreadLeg`/`OptionsSpreadPositionDecision` (additive; existing single-leg dataclass/functions untouched).
- `select_vertical_spread_legs()` (reuses `select_single_leg_contract()` for the long leg) and `build_vertical_spread_position_sizing()` (sizes by net vega, not the long leg's vega alone).
- `risk/asset_class_router.py` gained a `spread_strategy` dispatch (default `"single_leg"`).
- `main.py::_apply_option_order()` places spreads atomically via Lean's existing `OptionStrategies.bull_call_spread()`/`bear_put_spread()` + `self.Buy(strategy, quantity)` — a previously-unused API in this codebase, avoiding partial-fill/leg-slippage risk of hand-rolled sequential orders.
- Two real bugs caught pre-ship: unconditional `contract_symbol` extraction that would have rejected every spread order, and a new additive `option_contract_symbols_by_symbol` (plural) dict tracking spread legs without repurposing the existing singular dict.

**Verification:**
- 25 new tests (20 `test_options_strategy.py`, 5 `test_asset_class_router.py`, including a zero-behavior-change parity test). `main.py` placement/tracking-dict changes not unit-testable in isolation (same Lean-adapter constraint as every prior entry). Full writeup, including a documented scope trade-off on closing spreads, in Problems.md #38.

## 2026-07-16 — CI root cause found and fixed (#10), per-bar forward-pass latency measured (#21), per-asset-class book-slot caps (#29)

**Summary:** Closed three Problems.md entries chosen because none needed a rebuilt Docker image; all three needed real evidence (via `gh` CLI and `aq profile`) rather than guesswork.

**Shipped:**
- #10 — Installed/authenticated GitHub CLI, pulled the real failing CI log (`4 failed, ... 11 errors`). Three independent root causes fixed: `.gitignore`'s blanket `data/**` rule was excluding two hand-authored reference JSON files (added `!data/reference/*.json` exception, committed both files); `features/bond_features.py::empirical_duration_beta()`'s exact `variance_x == 0.0` check broke under Python 3.14's changed `sum()` float-summation algorithm (fixed with `variance_x < 1e-12` tolerance); `tests/test_lean_backtest_ml_coverage.py`'s self-skip guard only checked `lean` binary presence, not a usable Lean Data folder — new `_lean_data_folder_is_usable()` helper.
- #21 — No new tooling needed; `aq profile` already simulated the 11-forward-pass/5-call bundle. 10,000-iteration runs: batched mean=12.00ms/p50=7.03ms/p99=106.01ms/max=587.40ms; unbatched mean=8.72ms/p50=7.19ms/p99=41.02ms/max=212.67ms. `run_exported_sequence_multitask_model()` dominates (~48-58% of profiled time), flagged as future optimization target, not fixed. Verdict: negligible against the only real constraint (Lean's 90s `initialize()` isolator timeout).
- #29 — `portfolio/book_construction.py::build_rank_based_book()` gained optional `per_asset_class_slots` parameter (default `None`, byte-identical to prior pooled behavior; pooled/per-class paths now share `_select_book_group()`). Wired via `phase_v2.portfolio_book.per_asset_class_slots` + new `asset_class` field on `book_candidates` entries.

**Verification:**
- 19 new/extended tests (3 in `test_lean_backtest_ml_coverage.py`, 6 in `test_portfolio_book_construction.py`). 4 previously-failing tests now pass with no test changes (fixes were in reference files/`.gitignore`/production code). Full suite: `aq test` → 1304 passed, 0 failed, 11 deselected (`lean_backtest`), 1 pre-existing warning. Confirming CI itself goes green needed the next push's Actions run.

## 2026-07-16 (later) — #10 confirmed green on real CI, full implementations for #36 (topology embedding cache) and #37 (gc.freeze()) shipped, both config-gated off

**Summary:** Confirmed #10's CI fix went green on real GitHub Actions, then shipped real (not just documented) fixes for #36 and #37 — both config-gated off pending real-backtest validation.

**Shipped:**
- #36 — `build_market_topology()` gained `previous_correlations`/`correlation_stability_tolerance` parameters: when every pairwise correlation is stable within tolerance and the universe is unchanged, the SMACOF embedding call is skipped and the prior bar's positions reused. Wired via `phase_v2.topology.cache_enabled` (default `false`) and `.correlation_stability_tolerance` (default `0.02`).
- Finding: at the real ~30-symbol universe (435 pairs) with a 25-observation window, the skip essentially never fires at 0.02 tolerance — small-sample Pearson correlation noise means some pair almost always moves >2pp bar-to-bar, even under a stable synthetic factor model. Ships gated off pending real-data validation. New `aq profile --topology-cached` workload added for that future validation.
- #37 — `main.py::_ensure_ready()` now calls `gc.freeze()` once after model/weight load, before the `inference_parallelism` pool spawn, gated by `phase_v2.gc_tuning.freeze_after_load_enabled` (default `false`); still needs real-backtest validation of Lean's .NET/Python GC boundary interaction.

**Verification:**
- 21 new/extended tests (7 `test_market_topology.py`, 3 `test_profile_subsystems.py`, 7 `test_aq_cli.py`). `main.py` changes untestable outside Lean runtime, same constraint as every prior entry. Full suite: `aq test` → 1318 passed, 0 failed, 11 deselected, 1 pre-existing warning.

## 2026-07-16 (later still) — final pre-backtest bug sweep, 4 fixes, before this project's first real `lean backtest .` run

**Summary:** Dedicated sweep of the trading-critical path to de-risk the project's first-ever real `lean backtest .` run, since everything to that point had only been unit-tested against Lean's type stubs. Full writeup in Problems.md #39.

**Shipped:**
- `tests/test_lean_backtest_ml_coverage.py` — 3 of 11 assertions read the wrong state key (`config.model` instead of top-level `model`); would have silently passed a broken backtest. Fixed.
- `config.json`'s two liquidity participation thresholds had drifted to the same value (`0.01`), collapsing a two-tier system to one (side effect of entry #18). Fixed via `aq config set phase_v2.liquidity.thin_participation_threshold 0.005`.
- `main.py::_process_pending_limit_order_timeouts()` contradicted `classify_order_status()`'s documented contract (treated non-"pending" as cancel-eligible instead of only "unknown" being still-pending). Dormant today (`phase_v2.limit_orders.enabled: false`). Fixed.
- `portfolio/book_construction.py::build_rank_based_book()`'s `per_asset_class_slots` had no shape validation. New pure `normalize_per_asset_class_slots()` validates and reports skipped entries; `main.py` now calls it.

**Verification:**
- 6 new tests for `normalize_per_asset_class_slots()`. Fixes #1-#3 verifiable only via code review or a real `lean backtest .` (same `main.py`-untestable constraint). Full suite: `aq test` → 1324 passed, 0 failed, 11 deselected, 1 pre-existing warning.

## 2026-07-16 (yet later) — pinned the Lean engine Docker image, found live during the actual first backtest attempt

**Summary:** `aq backtest` appeared to hang on the first real attempt; it was actually silently re-pulling the ~42.5GB `quantconnect/lean` engine image because `lean backtest .` resolves the mutable `:latest` tag when no `--image` is given. Full writeup in Problems.md #40.

**Shipped:**
- `aq_cli.py::PINNED_LEAN_ENGINE_IMAGE = "quantconnect/lean:17900"` (real, numbered, immutable build tag, confirmed via Docker Hub API); `cmd_backtest()` now always passes `--image` explicitly.
- New `aq backtest --image <other>` escape hatch for trying a newer engine build deliberately.
- Root README updated (`aq backtest` CLI reference + Getting Started).

**Verification:**
- `tests/test_aq_cli.py`: updated the unpinned-invocation test, added a new `--image` override test. Full suite: `aq test` → 1326 passed, 0 failed, 11 deselected, 1 pre-existing warning.

## 2026-07-17 — Docker consolidation: one `aether-quant-engine` image for app + every worker, `aether-quant-` container rename, compose Lean image pinned

**Summary:** User-requested consolidation of Docker Desktop's separately-built per-service images and bare `aether-` container names (which collided with the user's other `aether-*` projects) into one fat image and a consistent `aether-quant-` naming scheme.

**Shipped:**
- Deleted `Dockerfile.workers` and `Dockerfile.retraining_worker`; the single remaining `Dockerfile` installs one `requirements/requirements.txt` (gained `aiofiles>=23.0`) and `COPY . .`s the whole source tree instead of per-service allow-lists. `requirements-runtime.txt`/`requirements-workers.txt`/`requirements-retraining-worker.txt` deleted.
- This structurally eliminates Problems.md #1, #2, #20, #30 — all the same root cause (per-worker COPY allow-list drift causing `ModuleNotFoundError` crash-loops).
- `docker-compose.yml`: app service renamed `aether-quant` → `engine` (`container_name: aether-quant-engine`); every worker references `image: ${AETHER_QUANT_IMAGE:-aether-quant-engine:latest}` with `container_name: aether-quant-<service>`. `redis`/`postgres` keep their DNS service names but get `aether-quant-redis`/`aether-quant-postgres` container names. Compose project name unchanged, so volumes are untouched.
- Compose `LEAN_IMAGE` default changed from `quantconnect/lean:latest` to `quantconnect/lean:17900`, matching the CLI pin (ties into #40).
- `aq_cli.py`'s `cmd_docker_up --all` and `cmd_docker_build` service names changed `"aether-quant"` → `"engine"`.
- Docs updated: `development/infrastructure.md`, root `README.md`, `requirements/README.md`, `notifications/README.md`, `webui/README.md`, `data_pipeline/README.md`.

**Verification:**
- `tests/test_aq_cli.py` tests updated for the `engine` service name. Full suite green. `docker compose config` validated the rewritten compose file resolves cleanly. Actual `docker compose build`/`up` and old-container/image cleanup left for the user to run themselves.

## 2026-07-17 — Pre-live security review: `lean.json` credential indirection, secrets out of the Docker image, localhost-only DB, secret-commit guard

**Summary:** Dedicated security pass before any live-capital/V3 multi-asset-class step. Nothing was ever actually leaked — all findings were prospective. Full findings in Problems.md #42.

**Shipped:**
- New `execution/lean_config_render.py` (pure render + `.env` parser) and `scripts/render_lean_credentials.py`/`aq render-lean-config` overlay `.env.live`'s `AETHER_*` values onto the empty tracked `lean.json` template, writing a gitignored `lean.live.json`; live/paper deploys use `--lean-config lean.live.json`. Only field names are ever printed. `aq backtest` deliberately untouched (uses plain `lean.json`).
- `.dockerignore` updated to exclude `lean.json`, `.env*`, `ib_config.py`, and `lean.live.json` (the last caught during verification of the fix itself — it was gitignored but not dockerignored). Pinned by new `tests/test_dockerignore_secrets.py`.
- Published DB/Redis ports rebound from `0.0.0.0` to `127.0.0.1` (host-only; internal container DNS unchanged). New fail-closed guard: `execution/live_credentials.py::postgres_dsn_is_live_safe()`/`load_postgres_dsn()`, threaded through `evaluate_live_broker_config()` and `main.py::_recompute_broker_config()` — live mode refuses to start on the default password (`aether_dev_password`).
- New `aq secrets-check` (`execution/secret_scan.py`) fails on a populated secret-looking `lean.json` field or a tracked real `.env`. Backed by an opt-in `.githooks/pre-commit` (never auto-installed).
- Checked and found clean: no deserialization-RCE surface, FastAPI monitoring server is read-only/localhost-CORS, Telegram creds already env-var-only, no secret in git history.
- Deferred: no dedicated audit logging of order placement/credential loads/live-mode transitions yet (tracked as the one open security item; closed in the next entry).

**Verification:**
- New `tests/test_lean_config_render.py`, `tests/test_secret_scan.py`, `tests/test_dockerignore_secrets.py`; extended `tests/test_live_credentials.py`, `tests/test_paper_readiness.py`, `tests/test_live_credentials_io.py`, `tests/test_aq_cli.py`. Docs updated: `development/infrastructure.md`'s V2-22 runbook, `README.md`, `.env.live.example`.

## 2026-07-17 — Full pre-live model overhaul: rank-driven trading, unblockable exits, and a training-pipeline rewrite that stops shipping the untrained model

**Summary:** Follow-up to a backtest showing bit-identical results (same 14 orders, same 20.364% net profit) to the pre-calibration run, proving the earlier threshold recalibration had zero effect. Root-caused to two independent bug classes: trading logic that could never exit, and a model whose output was nearly constant. Full detail in Problems.md #43.

**Shipped:**
- Trading logic could never exit: `_active_position_count()` counted only already-filled holdings (same-bar submissions overshot `max_active_positions`); the static sell threshold sat ~10 standard deviations from the model's real output range; the drawdown circuit breaker was neutered by config (`max_daily/total_drawdown_pct: 1.0`, `bypass_safety_gates: true`); risk-off/elevated-topology/trade-lock vetoes applied to `"sell"` exactly like `"buy"`, blocking exits during drawdowns.
- Model output was nearly constant: early stopping monitored validation BCE loss (lowest at epoch 1, worse every epoch after) — shipping near-random-init baseline/multitask/sequence models; threshold search had no degenerate-operating-point guard; MoE blend's unconditional 0.25 weight floor pulled the combined output toward 0.5; cross-sectional ranking heads (`rank_5d`/`rank_20d`) — the one statistically significant signal — were ignored by the trading path entirely.
- Trading-logic fixes (`main.py`, `analyzer/market_analyzer.py`, `portfolio/book_construction.py`): `portfolio_book` enabled, `rank_20d` now drives entries directly; `strategy_mode` now actually enforced (`"long_flat"` forces short side off); `build_rank_based_book()` gained deliberate long-only mode for `bottom_n==0`; book rotation forces a `"sell"` when a held symbol drops out of top/bottom-N; new Priority 0 in `build_market_analysis_decision()` — a `"sell"` for an already-invested symbol always executes, bypassing every protective veto; new non-model safety exits (`phase_v2.exits`, on by default: max holding age + direction-aware trailing stop); adaptive sell threshold (25th percentile of a symbol's own rolling probability_up history); same-bar position-cap overshoot fixed via per-bar pending-entries reservation; circuit breaker re-armed to real thresholds (0.03/0.12), `bypass_safety_gates: false`.
- Training-pipeline fixes (`train.py`, `train_multitask.py`, `train_sequence.py`, `train_gating.py`, `moe/gating.py`, `retraining/validation_gate.py`): new shared `is_new_best_epoch()` — single-head trainers now monitor balanced-accuracy with `min_best_epoch=3` floor; multi-head trainers kept monitoring combined loss (switching them to direction balanced-accuracy degraded rank_20d's non-overlapping t-stat, 2.90 → 2.21) but gained the epoch floor. `find_optimal_threshold()` gained a non-degenerate positive-rate band. New `select_model_context_columns()` collapses 30 per-ticker one-hots to 5 asset-class one-hots (model input dimensionality 85 → 52). `phase9.asset_quality.min_training_rows` 50 → 250 (excludes ETHUSD/XRPUSD/ADAUSD's ~52-row history). `moe/gating.py::_performance_score()` now floors at exactly 0.0 (was unconditional 0.25) for any zero-skill expert. `retraining/validation_gate.py` gained a skill-floor check (balanced-accuracy ≥ 0.50 OR MCC ≥ 0.0). Expert quality-gate defaults raised from below-coin-flip (0.48/0.48/−0.05) to 0.50/0.50/0.0.

**Verification:**
- Full stack retrained and promoted this session (baseline, 4 experts, multitask, sequence, learned gating — topology excluded, needs live Postgres telemetry that doesn't exist yet). Baseline best_epoch 16/34 (was 1/19), threshold search selects positive_rate 0.155 (was 0.91). All 4 experts clear the new skill floor. Sequence model best_epoch 3/13 (was 1); backtest rank_20d non-overlapping mean IC 0.2318, t-stat 2.955, clearing `promotion_gate.min_non_overlapping_t_stat: 2.0`.
- Caveats: no full walk-forward run (would take ~4 hours locally); rank_20d's internal promotion status still `not_promotable` by the strictest bar (one non-overlapping era out of ~9-40 has opposite-sign mean IC), though it doesn't block `portfolio_book` functionally.
- New `tests/test_train_threshold_and_early_stop.py`, `tests/test_train_select_model_context_columns.py`; extended `test_gating_network.py`, `test_market_analyzer.py`, `test_validation_gate.py`, `test_expert_models.py`, `test_portfolio_book_construction.py`. `test_model_input_dimensionality_is_59` → `_is_52`. Full suite: `pytest -m "not lean_backtest"` → 1392 passed, 0 failed, 11 deselected. `main.py`'s new logic has no direct unit tests (Lean-runtime-only, per established convention); the user's own `aq backtest` verification run was still outstanding as of this entry.

## 2026-07-18 — Operational maturity pass: tamper-evident audit logging, a real end-to-end retraining/rollback rehearsal, and every structural gap the rehearsal itself surfaced

**Summary:** Two exercises against real infrastructure (not mocks): shipped tamper-evident audit logging (closing the one deferred item from the security review, Problems.md #42), and ran a genuine end-to-end retraining/rollback rehearsal that surfaced and fixed real infrastructure bugs.

**Shipped:**
- New `audit/` package: Redis Stream → Postgres worker → JSON snapshot (same shape as `experience/`), hash-chained (git-commit-style, tamper detectable via `aq audit-log --verify`). Hooked into `main.py` (orders, credential loads, live-mode transitions) and `aq render-lean-config`. Queryable via `aq audit-log`, visible in webui (`AuditLogPanel.tsx`/`GET /api/audit-log`).
- Real end-to-end retraining rehearsal: seeded `experience_events` + a real `performance_triggers` row, let the `retraining-worker` container's own background poll loop auto-detect and run plan→train→train_topology→train_gating→train_multitask→train_sequence→validate against real Postgres/subprocesses, three times. All three candidates correctly rejected by the validation gate (consistent with #43's missing-edge finding, not a test failure).
- Rollback rehearsed directly against `retraining.orchestrator.rollback()`: happy path (hash-verified restore, Postgres status flip, new `retraining_events` row) and negative path (corrupted hash correctly refused, zero files touched).
- Rehearsal found and fixed 3 real structural bugs (Problems.md #44-#49): a read-only Docker volume mount blocking `train.py`; a Redis `xreadgroup(block=0)` bug causing perpetual socket timeouts in every Stream-consuming worker; an orphaned-`retraining_events`-row gap with no startup reconciliation.
- New reconciliation: `RetrainingWorker.__init__()` now calls `retraining.orchestrator.reconcile_stale_running_events()` on startup, marking any orphaned `planned`/`running` row as `failed` (staleness threshold 10800s / 3h, sum of every stage's own timeout). New config key `phase_v2.retraining.worker.stale_running_timeout_seconds`.
- A real-backtest verification pass for limit orders (#34), `gc.freeze()` (#37), and vertical spreads (#38) was attempted but blocked by this dev machine's 4GB RAM (module-import alone measured ~82s under memory pressure, hitting Lean's 90s isolator cap) — see Problems.md #50. One permanent fix shipped regardless: `main.py` now imports directly from `audit.redis_queue` instead of the whole `audit` package.
- Housekeeping: `ml/versions/` and `.av/` untracked from git and gitignored. `docker-compose.yml`'s `retraining-worker` gained `init: true` (tini) after a zombie-subprocess container-stop failure.

**Verification:**
- 8 new tests for reconciliation. Full `aq test` green (1465 passed, 0 failed, 11 deselected, 1 pre-existing warning) both before and after the reconciliation fix. `docker compose config` resolves cleanly.

## 2026-07-19 — The rank-pivot roadmap: trading path switched onto `rank_20d`, universe expanded 30→74 and rebalanced across asset classes, four Stage-4 regularization gaps closed

**Summary:** Direct follow-through on #43's finding that next-day direction is noise while `rank_20d` has genuine skill, but was being traded far faster than its ~20-day horizon supports (653 orders against a Sharpe -0.59 / Net -4.6% backtest). Five config-gated, independently-unit-tested changes; full detail in Problems.md #52.

**Shipped:**
- Trading path pivoted onto `rank_20d`: `strategy_mode` → `long_short`, `rank_sizing_enabled` → `true`, `gating_network.sequence_weight` 0.0 → 0.5, book `top_n`/`bottom_n` 5/5 → 8/8, `min_rank_confidence_spread` 0.1 → 0.15.
- New explicit 5-trading-day rebalance scheduler: pure `portfolio/book_construction.py::should_rebalance_this_bar()`, wired via `phase_v2.portfolio_book.rebalance_every_bars` (default 5; 1 reproduces prior every-bar behavior).
- Universe expanded 30 → 74 assets, rebalanced to 40 equities/22 bonds/12 crypto (54%/30%/16%), under the 75-name cap. All 44 new tickers backfilled via `yfinance_backfill.py` (a real MultiIndex-columns bug from a newer yfinance version found and fixed, 2 new regression tests). Dataset rebuilt: 113,804 rows (up from 46,242), 63 training-eligible + 11 observation-only. All 7 new crypto tickers landed observation-only (history starts 2017-11-09); tradeable crypto count stays at 2 (BTC, LTC).
- Four Stage-4 regularization gaps closed in `train_multitask.py`/`train_sequence.py`: rank-IC-based early stopping (config-gated, falls back to loss-based); dead 1-day direction head down-weighted via new `direction_loss_weight`; seed-ensembling (`average_ensemble_predictions()`, prediction-averaging not weight-averaging, plus new `--seed` CLI override); new horizon-consistency regularization penalizing 5d/20d heads landing on opposite sides of their shared midpoint.
- `phase1.target.ranking.purged_cv.enabled` was dead configuration (`purged_embargoed_folds()` had zero call sites). New `compute_purged_cv_rank_ic_diagnostic()` now actually invokes it, reported in both trainers' metrics JSON when the flag is on.

**Verification:**
- Every new function unit-tested (per-item breakdown in Problems.md #52). Full `aq test` green (1497 passed, 0 failed, 11 deselected, 1 pre-existing warning). Empirical retrain of the full ensemble and a real `aq backtest` confirming the t-stat/order-count/Sharpe improvements were still outstanding at the end of this entry — a `--multitask-only` retrain was started and deliberately stopped after ~4 hours of wall-clock for only ~800 CPU-seconds of progress (measured 350MB free of 3.9GB RAM), confirming #50's RAM finding and motivating a move to cloud compute.

## 2026-07-20 — GitHub Codespaces cloud-training offload, and the rank-pivot roadmap's actual empirical retrain

**Summary:** Moved the RAM-stuck retrain to GitHub Codespaces cloud compute and ran the full rank-pivot-roadmap retrain for real. Full detail (including an Alpine-devcontainer bug) in Problems.md #53; retrain numbers in #52's 2026-07-20 update.

**Shipped:**
- GitHub Codespaces set up as disposable training compute, reachable via `gh codespace ssh`, artifacts moved back via `gh codespace cp` (never through the public repo — `ml/` artifacts are gitignored).
- Found and fixed a real bug: the `docker-in-docker` devcontainer feature silently swaps the Codespace's base image to Alpine regardless of the `image` field (confirmed via 5 systematic A/B rebuild tests and a matching upstream issue). Also confirmed by direct failed experimentation that Docker cannot run inside a Codespace at all without that broken feature (unprivileged containers) — Lean/Docker backtests stay local-only; only training moved to the cloud.
- Final working config: base Debian image, only the `sshd` feature, CPU-only PyTorch (`--index-url https://download.pytorch.org/whl/cpu`). New "Cloud Training via GitHub Codespaces" section in `development/infrastructure.md`.
- All 8 model artifacts retrained end-to-end (baseline, 4 experts, multitask, sequence, gating) on the full 74-asset/113,804-row dataset — under 15 minutes total on the fixed Codespace vs. 4+ hours that never completed locally.
- A real git-hygiene bug found and fixed: 9 model artifact files (`ml/{multitask,sequence,gating}_{model,feature_schema,training_metrics}.json`) were still tracked in git, inconsistent with every other generated `ml/` artifact. Fixed via `.gitignore` addition + `git rm --cached`.

**Verification:**
- Rank-IC early stopping fired as designed (multitask best_epoch 24/42, sequence 8/18). Full-series rank_20d IC improved on the backtest split (multitask 0.172/t=7.55, sequence 0.127/t=5.70, up from pre-expansion 0.073/t=4.40). The project's non-overlapping significance gate (t-stat ≥ 2.0) was still not cleared — multitask 1.40, sequence 0.43 — an honest partial result. Infrastructure change verified by direct reproduction (5 A/B rebuild tests, a real failed dockerd-in-Codespace attempt), not a unit test. Retrain numbers taken directly from the 8 regenerated `ml/*_training_metrics.json` files. Git-untracking fix verified via `git check-ignore -v` and a clean `git status`. A fresh `aq backtest` against the retrained models was left as a manual next step for the user.

## 2026-07-20 — First real backtest against the rank-pivot-roadmap models: Sharpe -0.59 → +0.40, and a universe-selection bug found and fixed

**Summary:** The first actual `lean backtest .` run against the Codespaces-retrained rank-pivot models. Full detail in Problems.md #54.

**Shipped:**
- A real bug found via the backtest log: BNBUSD/TRXUSD (2 of the Stage-3 crypto additions) could never actually subscribe in Lean — Coinbase never listed those pairs (confirmed by grepping Lean's local symbol-properties database). Swapped for ETCUSD/ZECUSD, real Coinbase-listed pairs, backfilled with 1,239 real rows each via `aq fetch crypto --apply`. Universe count stays 74; tradeable crypto count unchanged at 2 (BTCUSD, LTCUSD).

**Verification:**
- Headline result: Sharpe Ratio -0.59 → 0.403, Net Profit -4.604% → +10.438%, Drawdown 11.1% → 4.0%, Expectancy -0.084 → +0.154, Win Rate 47% → 58%. Order count rose (653 → 2,082) but Portfolio Turnover barely moved (7.09% → 7.51%), confirming the 5-day rebalance scheduler works as designed; the raw order-count increase is explained by the bigger book (8/8 vs 5/5) and long/short trading both sides.
- Disclosed confound: `bypass_safety_gates` was also flipped on in this same session immediately before this run, so this result is not a clean isolation of the rank-pivot signal's standalone effect.
- Dry-run fetch previewed row counts/date ranges before `--apply`; `config.json` validated as parseable JSON after edits; `train.py --dataset-only` re-run to confirm the swapped tickers register as observation-only.

## V4 Webui — Overview/Operations split, Tracing reflow, genuinely 3D topology (V4-W1 / V4-W2 / V4-W3)

**Summary:** First V4 work item — split the overgrown Overview page, reflowed the Tracing page layout, and made the topology visualization genuinely 3D (previously z encoded volatility, now optionally a real embedding axis).

**Shipped:**
- Two roadmap corrections found while scoping: `_stress_majorize_2d()` actually lives in `topology/market_topology.py:150` (not `learned_topology.py`, which only applies bounded offsets); z previously encoded volatility, deliberately — going 3D replaces that meaning, acceptable only because `TopologyScene3D.tsx` already encodes volatility as node radius.
- V4-W1: seven operational/health panels (Performance Triggers, Retraining Status, Paper Readiness, Assets Status, Audit Log, Monitoring Feeds, Raw State) moved to new `webui/src/pages/OperationsPage.tsx` at `/operations`. Overview keeps the trading-side view. `AppShell.tsx`'s five duplicated `NavLink` blocks collapsed into a `NAV_ITEMS` map, adding a sixth.
- V4-W2: `TracingPage.tsx` restructured from `lg:grid-cols-2` row-major to two explicit flex columns at `lg:grid-cols-[1.6fr_1fr]` — three interactive charts left, Asset Performance alone right.
- V4-W3: new `phase_v2.topology.embedding_dimensions` (default 2). `_stress_majorize_2d` → `_stress_majorize` (dimension-agnostic, infers dimensionality from seed tuple width; 2-tuple seeds reproduce original behavior exactly); `_distance_2d` → `_distance`; `_rescale_positions_to_bounds` generalized, keeping its single isometric scale factor. At dimension 3: z becomes a correlation-distance axis on the same 0..100 scale as x/y, `dimensions.depth` reports 100 instead of 1.
- Two real breakages caught and fixed pre-ship: `main.py`'s `_previous_topology_positions` stored 2-tuples (would have silently disabled warm start in 3D mode); `_build_scene_payload()` copied raw z into a 0..1-scale payload (would have collapsed the scene onto a plane) — now divides by `dimensions.depth`.
- `TopologyScene3D.tsx`'s `toVec3()` fixed an anisotropic x/y-vs-z squash; z now maps with the same factor as x/y when `depth > 1`. In-scene legend switches text with the mode.
- Found and fixed during manual verification (Problems.md #55): every webui tab except `/` 404'd on direct load/hard refresh under FastAPI (`StaticFiles(html=True)` is not an SPA catch-all) — fixed with a new `SpaStaticFiles` subclass; pre-existing bug affecting all five prior tabs, hidden by vite's dev-server fallback.
- Logged, not fixed (Problems.md #56): `train_topology.py` learns z offsets on the old 0..1 scale, so the learned overlay wouldn't meaningfully move z in 3D mode. Latent, not active — no topology model has ever been trained.
- First frontend test infrastructure in the project: Vitest + Testing Library (`webui/src/test/setup.ts` stubs `@react-three/fiber`/`drei`), 10 tests across `pages.test.tsx` and `TopologyScene3D.test.tsx`.

**Verification:**
- 1497 → 1515 tests passing: +9 `test_market_topology.py`, +1 `test_learned_topology.py`, +8 `test_api_server.py`. The existing `test_stress_majorize_matches_pure_python_reference` parity guard passes unchanged, proving 2D mode moved zero coordinates. `aq test` (1515/1515), `npm run lint` clean, `npm run build` clean, a live `uvicorn` run sweeping all 15 API routes and 6 SPA routes. `/api/audit-log` 404s on a fresh checkout as documented (pre-existing, not a regression).

## V4.1 completion — normalized topology z offset, `aq train --topology-only` (Problems.md #56)

**Summary:** Closed the loose end V4-W3 left open — `train_topology.py` still emitted z offsets on the old 0..1 scale even though 3D mode put z on a real 0..100 correlation-distance scale.

**Shipped:**
- Naive fix (raising the multiplier to 4.0) was caught as wrong before shipping — it would regress 2D mode by saturating the `max_offset_z = 0.1` clamp for every win rate (verified: win_rate 0.45 gave old −0.0050 vs. naive −0.1000, a 20x distortion).
- Actual fix: `train_topology.py` now emits z normalized to [-1, 1]; `topology/learned_topology.py::_score_node()` multiplies it by the active `max_offset_z` before the same confidence-weighted clamp x/y already use — z's offset contract is deliberately asymmetric from x/y since z is the only axis whose scene scale changes between 2D/3D modes.
- Proven identity-preserving in 2D: `(win_rate − 0.5) × 2.0 × 0.1 ≡ (win_rate − 0.5) × 0.2` for every win rate/confidence, verified by a byte-identical-output test against the old formula. In 3D mode, the same normalized offset produces 60x more z travel under the raised cap (6.0/0.1).
- New `offset_schema` field on the model payload (format-identity detection hook), surfaced as `model_offset_schema` from `apply_learned_topology()`. No legacy-format branch added (no old-format model has ever existed).
- New `aq train --topology-only`, mirroring `--multitask-only`/`--gating-only`/`--sequence-only`: trains via `train_topology.py --version-id <uuid>` and installs into active `ml/`. Its skip message is more informative since skipping is the realistic outcome — `train_topology.py` needs `min_training_events` (default 500) realized-outcome events from Postgres, none of which exist on this machine.
- The learned overlay itself remains entirely dormant — this was a code fix, not a training run; `ml/topology_model.json` does not exist anywhere.

**Verification:**
- 1515 → 1521 tests passing (+6: 3 new `test_learned_topology.py` cases for the 2D identity/3D scaling/`model_offset_schema`; `test_train_topology.py`'s existing test gained value assertions; 3 new `test_aq_cli.py` cases for `--topology-only`). Docs updated: Problems.md #56 marked fixed, `topology/README.md`, `README.md`'s Webui roadmap and `aq train` CLI reference.

## V4.3.0 — Functionality: allow adding to an existing position, all 5 asset classes (Problems.md #57)

**Summary:** Closed the roadmap's Functionality item — scaling up an existing position instead of being blocked because one already exists. Exploration found three distinct problems instead of one gate.

**Shipped:**
- Equity/crypto/bond were genuinely blocked by a single `previous_signal != "buy" or not invested` gate in `main.py::_apply_signal()`.
- Futures/options had no gate at all — a live bug: each bar's absolute margin/vega-budgeted sizing target fired through incremental Lean primitives (`MarketOrder()`/`self.Buy(strategy, ...)`), silently stacking more contracts every bar the signal stayed the same (reachable only when `futures_risk`/`options_risk` enabled, both default off). Options additionally re-selected contract/spread legs every bar, orphaning old positions from `_is_invested()`'s tracking.
- Tier 1 (unconditional bug fix): new `risk_controls.py::compute_incremental_order_quantity()` computes the signed delta needed to converge toward an absolute target instead of overshooting every bar.
- Tier 2 (scale-up capability, behind `phase_v2.functionality.position_scaling.enabled`, default `false`): equity/crypto/bond gain `risk_controls.py::should_scale_position()` (weight-threshold churn guard); futures/options/spreads use "delta rounds to nonzero".
- Tier 3 (rotation capability, behind its own `rotate_on_drift` flag, default `false`, independent of `enabled`): a drifted option contract/spread is only liquidated-and-reentered same-bar when explicitly opted into.
- Two Lean sign conventions verified from existing codebase usage before writing delta logic (never assumed): `_futures_contract_count_for_weight()`'s signed contract count, and `HoldingsValue`'s signed-for-shorts convention.
- Default config confirmed byte-identical to prior behavior by grep — every new branch sits strictly behind the new flags, and futures/options bug-fix code is itself unreachable at true default. Vertical spreads only ever scale up, never down (no `Sell`-side combo-order primitive exists, same trade-off as #38's leg-by-leg close).
- Confirmed via call-graph tracing (not assumed) that `analyzer/market_analyzer.py`'s veto tiers, `active_position_limit_reached()`'s already-invested exemption, `cap_target_weight()`'s exposure-cap math, and `risk/futures_risk.py`/`portfolio/options_strategy.py`/`risk/asset_class_router.py` needed zero changes.

**Verification:**
- 1521 → 1558 tests passing. New coverage in `tests/test_risk_controls.py` (both new helpers) and `tests/test_order_gate.py` (every new execution-note string correctly classified real vs. no-op, exact-string denylist matching). Full writeup, including a deferred anti-thrashing-guard follow-up for `rotate_on_drift`, in Problems.md #57.

## V4.4 — architecturally-sound options: multi-position book, symmetric scale-down, held-contract sizing, spread combo orders (Problems.md #58)

**Summary:** Closes six architectural gaps in V4.3.0's options paths — single-leg-only scaling, no spread scale-down, drift freezes, single-slot tracking, un-netted rotation, no spread limit orders — by building a full multi-position options book plus the new spread combo API (Sell-combo scale-down, combo limit orders), both code-complete but IB-unverified.

**Shipped:**
- `portfolio/options_strategy.py`: new pure functions `build_options_position_sizing_for_contract()` and `build_vertical_spread_position_sizing_for_legs()` to size already-held positions on current greeks instead of re-selecting from the chain.
- `main.py` tracking changed to `self.option_positions_by_symbol: dict[str, list[dict]]`, capped by `phase_v2.options_risk.max_positions_per_underlying` (default `1`, byte-identical to pre-V4.4).
- New `_liquidate_option_record()` (close one position) separated from existing `_liquidate_position()` (full close).
- `pending_limit_orders` re-keyed from chain `symbol_key` to order-target Symbol so concurrent positions on one underlying don't collide; records normalized to `"tickets"`/`"target_symbols"` lists.
- Fixed a gap caught during verification: at-cap re-pricing branch placed real orders regardless of `position_scaling_enabled`; corrected to no-op when scaling is off.

**Verification:**
- 1558 → 1591 tests, all passing (10 new held-contract-sizer cases, 23 new execution-note classifications).
- Remains IB-unverified; see Problems.md #58 for deferred rotation-netting/anti-thrashing follow-ups.

## V4.5 — full `OptionStrategies` coverage: all 43 QuantConnect option structures, registry-driven (Problems.md #59)

**Summary:** Expands options coverage from 2 of 43 QuantConnect `OptionStrategies` factories to all 43, registry-driven, so the NN can drive any Lean-supported structure; the 6 arbitrage strategies are stubbed for a future mispricing detector.

**Shipped:**
- `portfolio/options_strategy.py`: new `MULTI_LEG_STRATEGY_REGISTRY` (one `StrategySpec` per strategy, transcribed from Lean's C# source) plus ~10 shared shape-family selectors dispatched via `select_strategy_legs()`.
- New `OptionsMultiLegPositionDecision`/`build_multi_leg_position_sizing()`, sizing by `abs(net_vega)`.
- New `portfolio/options_margin_sizing.py` (3 margin sub-models: Reg-T-style naked, uncovered-leg, bounded-max-loss).
- `risk/asset_class_router.py` gained `route_multi_leg_option_sizing()`, an ordered-priority selector, volatility-gated for straddle/strangle/iron-condor/butterfly.
- `main.py`'s 2-leg `"spread"` record kind replaced by general `"multi_leg"` (any leg count/ratio); liquidation now closes all SHORT legs before any long leg; new expiry-day auto-close sweep and covered/protective equity-lifecycle sweep.
- Fixed transcription bugs: 2 of 4 ladder strategies and 2 of 4 backspreads were mis-classified bounded/unbounded; fixed expiry-drift, debit/credit leg-role inversion, volatility-signal unit mismatch (annualize `× √252` at call site, not in classifier), missing margin family entries, and covered/protective bundled-order risk.
- New config under `phase_v2.options_risk`, gated by `multi_leg_strategies_enabled` (default `false`).

**Verification:**
- 1589 → 1656 tests, all passing (67 new).

## V4.6 — bounded options follow-ups, arbitrage mispricing detector, Forex/FX, analytic bond-ETF duration/convexity (Problems.md #60)

**Summary:** Closes bounded follow-ups from V4.5/#38/#57/#58, adds Forex as a fully first-class Lean asset class, and reframes individual-bond trading (confirmed infeasible in Lean) into deeper bond-ETF analytics. Learned strategy-selection model and full assignment/corporate-action modeling explicitly deferred.

**Shipped:**
- Fixed `_active_position_count()` counting every leg of a multi-leg position toward `max_active_positions` (via chain-level identity dedup), which also fixed the exclude filter never excluding option holdings.
- Rotation gained anti-thrashing cooldown (`rotation_cooldown_bars`) and same-bar netting.
- New optional per-asset `options_strategy_override`.
- New `portfolio/options_arbitrage_detector.py` (put-call-parity/box-spread/cost-of-carry fair value vs. market), gated behind off-by-default `arbitrage_detector.enabled`.
- New `risk/forex_risk.py` (leverage-utilization sizing, mirrors `futures_risk.py`) and `data/reference/forex_pair_specs.json`, wired via `asset_class_router.py`/`main.py::_add_asset()`; `on_data()` gained a midpoint-OHLC fallback for forex quote-bar data.
- `features/bond_features.py` gained `analytic_modified_duration()`/`analytic_convexity()`/`bond_dv01()`, informational-only via new `main.py::_bond_analytics_for_symbol()`.

**Verification:**
- 1656 → 1722 tests, all passing (66 new).
- Forex code-complete, IB-unverified, zero live tickers configured at this point.

## V4.7 — early-assignment/corporate-action modeling, a learned multi-leg strategy-selector model, and bond analytics wired into the trained model as real signals (Problems.md #61)

**Summary:** Brings the three items V4.6 scoped out into full scope: dividend-driven assignment risk modeling, a learned multi-leg strategy selector, and bond analytics as real trained-model features (code-complete, retrain deliberately not run).

**Shipped:**
- New `data_pipeline/dividend_backfill.py` (yfinance ex-dividend fetch, next-date projected from historical cadence).
- `features/options_greeks.py` gained a Barone-Adesi-Whaley American-exercise pricer `baw_american_price()`, verified against a CRR binomial tree.
- New `portfolio/options_assignment_risk.py` scores dividend-driven early-call-assignment risk (call-only), wired via `main.py::_apply_option_assignment_risk_sweep()`, off by default; same-bar stock splits logged into `corporate_action` field.
- New capture logic `main.py::_emit_option_strategy_outcome_if_pending()` / `simulated_option_strategy_entries_by_symbol_key` targets the observation-mode branch (real-order path never fires here); new `option_strategy_outcome` event type needs zero Postgres DDL changes.
- New `train_strategy_selector.py` (follows `train_topology.py`'s shape, dormant until real option positions trade) and `inference/strategy_selector_inference.py`; `route_multi_leg_option_sizing()` gained optional `strategy_selector_scores` kwarg (byte-identical when absent).
- `config.json` feature list gained the 3 analytic bond features; `main.py`/`train.py` now compute them, but the actual retrain was deliberately not run this pass.

**Verification:**
- 1722 → 1813 tests, all passing (91 new across 6 new + 5 modified test files).
- Explicitly flagged: deploying the config change without a matching retrain would `KeyError` on every bar — documented as the key sequencing risk.

## Phase 4.8 — closing the gaps a full-stack completeness audit found: `lean` CLI in the retraining-worker image, a new Options & Strategy webui page, a real `main.py` bug fix, and CLI/Docker discoverability fixes (Problems.md #62)

**Summary:** A 3-agent audit rated V4 7/10; this phase closes the concrete gap list the audit produced (topology-model training, IB integration, walk-forward, and a real Lean backtest explicitly deferred to the user).

**Shipped:**
- `lean` CLI installed in the production image; `retraining-worker` gained a `/var/run/docker.sock` mount (confirmed `lean backtest` launches its own container).
- `engine`'s docker-compose gained a scoped `data/reference/` mount (fixes `GET /api/assets-status` reporting zero Forex/futures/FRED specs).
- New `aq backfill <target>` command (`dividends`/`fred`/`yfinance`); fixed `aq_cli.py`'s stale test-group dict missing 4 recently-added test files.
- Fixed a real bug: `main.py`'s `corporate_action_payload` was set in Pass 1's per-symbol loop but read in Pass 2's separate loop, so every symbol's persisted event reused the last symbol's leftover value; fixed by threading through `pass1_state`.
- Wired previously-computed-but-never-persisted V4.7 fields (bond analytics, assignment-risk score/flag, dividend schedule, strategy-selector scores) into `signals[symbol_key]`.
- New webui "Options & Strategy" page (`/options-strategy`): held multi-leg positions, dividend schedule, strategy-selector scores, corporate actions, a 43-strategy catalog browser (new `GET /api/strategies`), and a real Forex pair-spec panel.

**Verification:**
- 1813 → 1818 tests, all passing; webui 13 tests across 2 files, `npm run build`/`lint`/`test` all clean.

## V4.9 — a major latency-optimization pass across every hot path, prepping the ground for a future HFT fork (Problems.md #63/#64)

**Summary:** A major latency-optimization pass across 9 priorities (mostly opt-in, byte-identical-default preserved), including one genuine live bug fix, ahead of a potential future HFT fork.

**Shipped:**
- P0 (bug fix): removed a still-live `_build_model_input()` profiling wrapper writing synchronously to `model_input_timing.log` on every symbol-bar call, despite Problems.md #50 claiming it was reverted; 45,187 untracked log lines found in the repo root.
- P1: new `run_exported_sequence_multitask_model_batched()` batches the sequence encoder across all pending symbols per bar, behind `phase_v2.sequence_model.batched_across_symbols_enabled` (default `false`).
- P2: new `correlation_stability_tolerance_percentile`/`correlation_change_history` params make topology cache tolerance a rolling percentile instead of a fixed value; `null` default reproduces old behavior byte-identically.
- P3: `select_calendar_legs()`/`select_arbitrage_jelly_roll_legs()` gained shared `grouped_chain_by_expiry`, computed once per `route_multi_leg_option_sizing()` call instead of per candidate.
- P4: options chain-payload gating considered and declined (documented, not re-investigable).
- P5: new non-blocking `ExperienceQueue.push()` via `async_enabled` (bounded background-thread queue, soft-drop-and-log on full), default `false`.
- P6: real `ProcessPoolExecutor` IPC-overhead benchmark added to `scripts/profile_inference.py --parallel`; confirmed the pool is dramatically slower on this dev machine's Windows `spawn` method.
- P7: `profile_subsystems.py` gained an `"options"` workload covering all 15 shape families; new `aq profile --options`/`--parallel`/`--pool-workers`/`--symbols-per-bar` flags.
- P8: new `development/architecture.md` section distinguishing genuine HFT-fork prep from same-loop optimizations.

**Verification:**
- 1818 → 1857 tests, all passing (39 new).

## V4.10 — pure-function extraction of main.py's exit logic, 4 webui quality fixes, and 15 new forex/FX assets fetched via `aq fetch` (Problems.md #66)

**Summary:** Extracts main.py's non-model exit logic into testable pure functions (a literal main.py unit test remains confirmed impossible), fixes 4 webui quality issues, and onboards 15 new forex assets.

**Shipped:**
- New `evaluate_non_model_exit()`/`compute_position_exit_tracking_update()` in `risk_controls.py`; `main.py`'s `_check_non_model_exit()`/`_update_position_exit_tracking()` became thin call sites, verified byte-identical via static call-graph trace.
- Fixed `DerivativesMacroPanel.tsx`'s `useMemo` calls silently defeated by inline `?? {}`/`?? []` allocating new objects every render; fixed with stable module-level constants.
- Route-level code-splitting via `React.lazy()`/`Suspense`, replacing a single 1.27MB/348KB-gzip bundle.
- Removed 2 dead Grafana-era API routes from `monitoring/api_server.py`; added 24 new tests for `format.ts` and shared chart primitives.
- New `"forex"` `ASSET_CLASS_CONFIG` entry in `data_pipeline/fetch.py`; new `synthesize_forex_bid_ask_row()`/`forex_rows_to_lean_csv()`/`write_lean_forex_zip()` to handle Lean's 10-column bid/ask forex CSV format (duplicating OHLC into bid/ask as a documented zero-spread approximation while preserving real historical spreads on merge).
- `forex_pair_specs.json` extended 7 → 15 pairs; all 15 actually fetched via `aq fetch forex ... --apply`; universe grew 74 → 89 assets. `phase_v2.forex_risk.enabled` stays off by default.
- Per user direction, `train.py --dataset-only` was NOT run this session.

**Verification:**
- 1857 → higher count pending full re-run; webui suite confirmed 37/37 passing, build/lint/test clean; zero real network access in any test.

## V4.10 follow-up — opt-in live (Lean/IB-calibrated) futures margin source (Problems.md #67)

**Summary:** Adds an opt-in live futures margin source (Lean's IB `BuyingPowerModel`) as an alternative to the static, drift-prone reference-file margin table.

**Shipped:**
- New `phase_v2.futures_risk.margin_source` toggle (`"static"` default or `"live"`), attached per-security via `SetBuyingPowerModel()` (not the global brokerage model, to avoid changing fees/slippage for other asset classes).
- New `risk/futures_risk.py::resolve_futures_margin_source()` (validates config, falls back to `"static"` on any unrecognized value) and `build_live_contract_spec()` (builds a live spec in the same shape as the static path).
- `main.py`'s 3 raw contract-spec lookups now route through new `_resolve_futures_contract_spec()`, falling back to static on live-query failure.
- Continuous-vs-mapped-contract distinction left as a known, documented gap.

**Verification:**
- 8 new tests in `tests/test_futures_risk.py` (26 total, up from 18); off by default, code-complete but Lean-API-unverified (no real Lean backtest with a futures position sized has been run).

## Backend/latency gap-closing pass — Docker-built C++ accelerator, main.py CI syntax-check, Windows inference_parallelism guard (Problems.md #68/#69)

**Summary:** Closes 3 findings that capped `backend/models/latency` at 8/10: the C++ accelerator never ran in a deployed image, main.py had zero CI coverage, and the Windows parallelism slowdown had no runtime guard.

**Shipped:**
- New soft-fail Docker `RUN` step builds `cpp_inference_ext` for the container's own Python 3.11 (the only prior compiled artifact was ABI-incompatible, built on this machine's Python 3.14), wrapped in `|| echo ...` so any failure degrades to the existing NumPy fallback; `.dockerignore` hardened to match `.gitignore`'s build-artifact excludes.
- New `python -m py_compile main.py` step added to `ci.yml`'s `test` job. A full mypy/pyright pass was considered and declined (QuantConnect stubs would produce overwhelming import noise).
- Added the missing `phase_v2.inference_parallelism` config key (found `aq config set` on it actually failed with `ConfigPathError`); new `windows_parallelism_slowdown_warning()` in `inference/parallel_inference.py`, surfaced via `self.Debug()` on Windows pool construction and via a matching `aq config set` CLI warning gated to `config.json` only.

**Verification:**
- 1857 → 1899 tests, all passing (cumulative across V4.10, the futures follow-up, and this pass).

## V4.11 — training + optimization phase: full Codespace retrain + walk-forward executed, three latent train.py bugs fixed, primary signal clears the ≥2.0 significance bar (Problems.md #70)

**Summary:** First real execution (on the GitHub Codespace) of a full model retrain and the Stage-6 walk-forward diagnostic, surfacing and fixing 3 latent `train.py` bugs and clearing the project's significance bar for the first time.

**Shipped:**
- 8 of 9 model families retrained (baseline + 4 experts + multitask + sequence + gating); topology overlay stayed dormant (no accumulated Postgres event store on a disposable Codespace).
- Fixed `load_lean_bars()` unable to parse forex's 11-field bid/ask quote bars (added a midpoint-collapse branch matching `main.py`'s runtime midpoint for train/serve parity).
- Fixed `add_regime_features()` duplicating every column on empty walk-forward sub-window frames (added an empty-frame guard).
- Fixed `build_dataset_manifest()` KeyError on walk-forward's empty `{}` inventory (`.get("coverage_checks", {})`).
- Caught a stale-data sync gap: 4 forex zips were an old 2007–2018 vintage, wrongly classifying EUR/USD, GBP/USD, NZD/USD, EUR/GBP observation-only; re-synced to 2014–2021 data, making all 15 forex pairs training-eligible (trainable universe 74 → 78).
- Toggled ON several Lean-backtest-gated, IB-independent features for the user's two upcoming manual Lean backtests: position-scaling + rotation, sequence symbol-batching, topology cache + percentile-tolerance, composite regime score, forex trading, inference parallelism.

**Verification:**
- Multitask `rank_20d` non-overlapping t-stat reached 2.028 (≥2.0 bar) with bootstrap CI lower +0.0065 (≥0) — both hard promotion gates pass for the first time (progression 1.20 → 1.40 → 2.028 as universe grew). Still `not_promotable`, blocked by `era_sign_instability` (2 of 9 eras invert sign). Sequence `rank_5d` t=1.996. Walk-forward cross-window MCC mean 0.0259, 95% CI [0.0128, 0.0409].

## Phase 4.12 — decomposing "era-sign instability" into 3 real causes, alt-data (options-implied vol + financial conditions), 104-asset universe, an RL sizing layer, and every remaining non-IB Problems.md item (Problems.md #71)

**Summary:** Decomposes V4.11's one remaining failing gate (`era_sign_instability`) into 3 distinct causes and fixes each targeted, plus adds alt-data, universe expansion, and an offline RL sizing layer.

**Shipped:**
- `min_universe_size` raised 10→20 to remove degenerate crypto-only weekend cross-sections (255 of 801 dates) causing spurious ±1.0 rank-ICs.
- New `era_sign_min_abs_ic`/`era_min_observations` added to `promotion_gate` to stop thin-sample era means from failing the gate like real inversions; verified in production (excluded sequence `rank_5d`'s negligible COVID-era mean_ic of -0.0007 while still counting `rank_20d`'s two real inversions).
- Fixed `average_correlation` hardcoded to `0.0` in both `train.py` and `train_gating.py` offline (silently disabling the risk_off correlated-crash rule); now sourced from the topology layer's real per-date correlation structure.
- Added alt-data (VIX level, VIX term structure, 4-week financial-conditions change) via the existing no-API-key FRED fetcher, lookahead-tested.
- Universe expanded 89 → 104 assets; `max_active_positions` 12→15; portfolio-book `top_n`/`bottom_n` 8→10.
- New offline contextual bandit RL sizing layer (`train_rl_sizing.py`, `risk/rl_sizing.py`) that scales (never replaces) the rule-based sizer, sits behind existing risk clamps, default off.
- Closed every remaining non-IB Problems.md item: `cpp_inference_ext` Docker-linkage check, real per-call inference timing data (#36), an experience-worker doc misnomer, a stale hardcoded-dimensionality test, and an `inference_parallelism` shutdown-hang fix (pool now explicitly `.shutdown()`-ed; feature defaulted back to `false`).

**Verification:**
- Primary `rank_20d` t-stat improved 2.028 → 2.8954, CI lower 0.0065 → 0.0585 (both significance gates pass with margin); still `not_promotable` — COVID inversion unchanged (mean_ic -0.1654) and cleanup exposed a second real inversion (Dec 2020–Mar 2021, mean_ic -0.0953).
- Sequence `rank_5d` became fully `promotable` for the first time (t=2.3158, CI lower 0.0084, zero opposite-sign eras); walk-forward MCC mean 0.0187, CI [0.0136, 0.0239].
- RL sizing: honest negative result — learned policy's expected reward (-8.542e-5) underperformed the constant-1.0 baseline (-8.264e-5); ships disabled per pre-committed abandon criterion.
- Docker Desktop/WSL2 was down the entire session; Docker-gated items left open with resume commands in Problems.md #71.

## V4.12.2 — close every webui/CLI integration gap Phase 4.12 left behind (Problems.md #71)

**Summary:** A follow-up audit found the backend/CLI genuinely complete but the webui was not — several already-computed and persisted fields were never rendered; this phase closes 4 gaps.

**Shipped:**
- `AssetSizingTable.tsx`/`DynamicSizing` type now expose `volatility_multiplier`/`confidence_multiplier`/`topology_multiplier`/`rank_multiplier`/`rl_multiplier` as chips, muted at neutral `1.0`.
- Extracted `RankingQualityGate` sub-component, now rendering `rank_20d`, `rank_5d`, and `sector_neutral_rank_20d` identically (previously only `rank_20d` shown), including a per-era `<details>` diagnostic table (window, n, mean IC, t-stat), flagging opposite-sign/thin eras.
- New `state["macro"]` key in `_write_state()` (`main.py` computed `latest_bond_payload`/`latest_alt_data_payload` every bar but never wrote them to state), new `MacroSnapshot` webui type and `MacroSnapshotPanel.tsx` on the Risk page, rendering `—` for missing values.
- CLI re-audited, no gaps found. Updated `regime/README.md`, `risk/README.md`, `features/README.md`, `data_pipeline/README.md`, `webui/README.md`, `ml/README.md`.

**Verification:**
- `python -m py_compile main.py` clean; full local `pytest -q` — 1989 passed, 11 errors (all pre-existing Docker-dependent fixture, not a regression); `npm run build` clean; `npx vitest run --no-file-parallelism` — 8 files/46 tests all green.

## Phase 4.12.3 — every remaining Docker-dependent item closed, Phase 4's arc complete (Problems.md #71)

**Summary:** Root-causes and fixes the Docker/WSL2 outage that had blocked Phase 4.12's deferred items, then closes every one of them, completing Phase 4's arc.

**Shipped:**
- Root cause: a stuck `wslinstaller.exe` process (since 2026-07-26) had wedged `WSLService` in `StopPending`; Windows Fast Startup made a normal shutdown/power-on resume the same broken session. Fixed via a genuine Start → Power → Restart.
- `#68` (cpp_inference_ext linkage): confirmed the compiled `.so` genuinely links/imports inside the built `engine` image.
- `#56` (topology overlay training): trained for real for the first time — 6 clusters from 4,937 samples; used the user's local `lean` CLI with `--extra-docker-config` to inject `AETHER_REDIS_URL` (the planned `docker compose run --rm lean` approach didn't work, that image has no Python `lean` CLI); observation backtest shrunk to 3 months to avoid repeated OOM crashes on the 4GB dev machine, still producing 52,129 real events (2 orders of magnitude past the 500-event minimum). Adopted a new standing rule: all model training goes through the Codespace CLI, never locally.
- RL sizing re-confirmed on freshly-rebuilt Codespace datasets — identical honest negative result, stays disabled.
- Lean isolator timing at 104 assets: `Initialize()` now ~105s (above the 90s budget), but backtest completed successfully regardless.

**Verification:**
- Backtest 1 (observation mode, 3-month window) generated the topology training data above.
- Backtest 2 (representative, full 2019-2021, drawdown enforcement genuinely active, no bypass): 3,606 orders, Sharpe -0.145 (improved from V4.11's -0.313, still negative), Net Profit +3.41% (up from 1.04%), Drawdown 6.6% (down from 8.9%), fees ($2,769) still consuming nearly all net profit. First backtest ever with the learned topology overlay actually active in sizing. `README.md`'s Backtest Results section updated. Nothing IB-independent remains open in the project.

## V5.1 — Cost-aware cross-sectional ranking (Problems.md #72, #77, #81, #83–86)

**Summary:** Rebuilds the model and execution path around V4's core gap (real gross edge, negative Sharpe from fees/uncalibrated book) by training for what's actually traded on and making cost explicit throughout the decision, sizing, and safety pipeline.

**Shipped:**
- Both trainers now optimize a differentiable cross-sectional soft-Spearman ranking loss (ListNet variant also available) over whole-date batches, confirmed better than MSE via same-seed comparison; AdamW + cosine decay + SWA; TCN trunk gained LayerNorm; rank targets available residualized against market beta/sector/size; per-asset macro sensitivity betas (rolling regression vs. ΔVIX/Δreal-rate/Δcredit/Δdollar) replaced broadcast macro features.
- New expected-net-edge gate compares model edge against `execution/cost_model.py`'s expected round-trip cost before every trade; positions can scale down (never up) on thin edge. Fixed a bug where rank heads were trained raw against `[0,1]` but exported with a leftover sigmoid, compressing live predictions to ~[0.475, 0.75] — invisible to rank-IC checks since rank-IC is monotone-invariant (#84).
- Book made dollar- and sector-neutral with hysteresis; sector mapping expanded 29 → 104 assets (#85). Fixed a truncation-by-symbol-order bug so strongest-ranked names survive when the position cap binds (#86). Fixed a severe bug where the sector-neutral step demeaned entire sector buckets to exact zero (erasing whole legs of the book, notably a one-sided Forex bucket) (#81) — offline net Sharpe roughly doubled once the short leg was sized again.
- Walk-forward evaluation now spans six expanding windows 2014–2021. New offline cost-aware rank-book simulator (`evaluation/`) reproducing the live decision path without a Lean run — net Sharpe, turnover, capacity, cost-stress, ablation harness; the promotion gate now actually consumes ranking-quality/net-performance verdicts.
- New automated kill switch (rolling Sharpe, drawdown velocity, live rank-IC decay, consecutive losses, slippage divergence, model age) tripping the same sticky trade lock as the drawdown breach. New position reconciliation (book intent vs. broker holdings). Opt-in, off-by-default auto-rollback with cooldown/minimum runway.
- Also fixed: `fetch_fred_series()` hang from FRED requiring HTTP/2 (#79); a feature-list mismatch crashing walk-forward net-performance evaluation (#82); a false-positive orphaned-feature report (#80); a ~17-minute-per-run test regression from an unmocked subprocess-spawning test (#78).

**Verification:**
- `rank_5d` non-overlapping t-stat reached 6.0–6.8 across every seed/objective tried, the strongest result in the project's history. `rank_20d` improved but still short of the promotion bar; residualized rank head not promotable yet. Offline simulator shows positive, balanced net Sharpe after costs across all six walk-forward windows. Validated only by the test suite and offline simulator — neither of the two reserved Lean backtests spent yet. IB end-to-end verification still open.

## V5.1.11 — Lean runtime portability and startup boundary

**Summary:** Fixes Lean runtime portability issues and a module-initialization ordering hazard ahead of spending the reserved V5.1 Lean backtests.

**Shipped:**
- `aq backtest` now defaults to a cached local `aether-quant-lean:17900` image (built from pinned `quantconnect/lean:17900`), installing Redis and `httpx[http2]` via `requirements/lean-runtime.txt`, removing a fragile generated-requirements bind mount on Windows.
- New Windows-only Lean CLI launcher adjusts temp-directory permissions before Lean starts (addresses Docker Desktop mount failures).
- Deferred `performance.evaluate_all_triggers` until the runtime dashboard view, preventing Lean's hard startup isolator from importing the trigger worker's PyTorch stack during module init.
- `httpx[http2]` (added in V5.1's FRED fix, #79) was missing from the local Lean image's dependency list despite `main.py` unconditionally importing it via `data_pipeline.fred_backfill` — added.

**Verification:**
- New unit/AST regression coverage for the local image path and deferred import; new Lean runtime test registered in `aq test --cli`.

## V5.1.12 — Six critical bugs found before the first V5.1 Lean backtest

**Summary:** A full review of every config value switched on this session and its consuming code (#88), catching six critical bugs before spending V5.1's first real Lean backtest.

**Shipped:**
- Net-edge gate no longer blocks every short — now measures edge in the trade's own direction.
- `--calibrate-edge` now regresses on the configured horizon's forward return, not always 1-day; `edge_bps_per_rank_unit` recalibrated 28.2194 → 396.2743.
- Kill switch no longer trips within the first few bars — rolling-Sharpe trigger requires a real minimum sample.
- Reconciliation now compares broker holdings against the FINAL post-sizing/liquidity/cost intent for every Pass-2 symbol, not pre-sizing book weight against all held securities; `trips_kill_switch` set to `false` pending a real backtest confirming the drift distribution is sane; dust positions no longer read as permanent orphans.
- Slippage-divergence tracking no longer treats overnight price gap as execution slippage; trigger disabled pending a reliable fill-time reference price, data collection continues.
- Fixed `corporate_action_payload` leaking the last Phase-1a symbol's value onto every other symbol's Phase-1c record.
- `sector_max_net_weight` raised 0.05 → 0.15 so `max_weight_per_name: 0.12` is reachable; a configured `0.0` can no longer silently zero the whole book (#81).

**Verification:**
- Full suite: 2392 passed. First of the arc's two reserved Lean backtest slots spent on this batch.

## V5.1.13 — First real V5.1 backtest: three critical fixes verified, book-spread bug found and calibrated

**Summary:** The first real V5.1 Lean backtest (2019-01-01→2021-03-31) confirmed V5.1.12's riskiest fixes work, but exposed the book trading for 3 weeks then placing zero new orders for the remaining 2.2 years (#89).

**Shipped:**
- Fixed the kill switch's rolling-Sharpe calculation being numerically unstable on near-zero-variance return windows (mostly-cash portfolio could swing to wildly extreme spurious Sharpe readings and get stuck tripped) — a different gap from #88's sample-count warmup fix.
- Found `min_rank_confidence_spread` (the book's conviction gate) was a never-validated guessed `0.2`; the offline simulator hardcodes this gate off entirely, so it was never validated at all. New `aq evaluate --calibrate-book-spread` CLI mirrors `--calibrate-edge`'s calibration discipline; applied real result 0.5014 (not 0.2).

**Verification:**
- A genuine short executed for the first time; kill switch never falsely tripped from a short sample; reconciliation reported zero false breaches.
- Honest open item: the calibrated spread came back far higher than expected — the guessed 0.2 threshold likely wasn't what actually stopped January 2019 entries; whether the dead-book symptom is actually fixed awaits the arc's second and final reserved backtest.
- Full suite: 2412 passed.

## V5.2.1 — Closing the offline-vs-live Sharpe gap

**Summary:** The follow-up backtest confirmed V5.1.13's fixes resumed trading, but Sharpe was strongly negative (-4.2 to -4.4) against offline's +0.26 to +2.18 for the same window — root-caused to three independent, compounding mechanisms (#90).

**Shipped:**
- Confirmed a ~1-bar execution lag the offline simulator never modeled (Daily market orders fill at the next bar's open, not same-day); ruled out a live-side fix (`MarketOnCloseOrder` lands even later) as structural. Offline simulator gained opt-in `entry_lag_bars` (default `0`); `aq evaluate --rank-book` now always shows both `0` and `1` side by side.
- Found orthogonal V4.3.0 position-scaling machinery re-firing every bar for book members independent of the book's 10-bar rebalance cadence, firing real resize orders far more often than offline assumed. Now gated to rebalance bars only for book-selected symbols; full exits untouched.
- Found the cost gate sized against the full target position value instead of the actual incremental resize, systematically under-costing frequent small resizes; now sized against the real trade delta, with direction flips costing more too.
- Offline simulator gained an approximate per-order minimum-commission floor.

**Verification:**
- Full suite: 2428 passed. Not yet confirmed whether these fixes close the offline-vs-live gap — full closure not promised since the execution-lag mechanism is structural.

## V5.2.2 — Book-history diagnostic + reconciliation CLI

**Summary:** The V5.2.1 confirming backtest (Sharpe -4.421) showed the three fixes did NOT close the gap; six more indirect hypotheses were tested and ruled out, so this round builds a reusable ground-truth diagnostic instead of another one-off test.

**Shipped:**
- New opt-in, backtest-only `visualization/book_history.jsonl` (`phase_v2.diagnostics.book_history.enabled`) logging the live book's actual selections per rebalance date via `portfolio/book_construction.py::build_book_history_record()`.
- New `aq evaluate --reconcile-book-history [--book-history-path PATH]`, reading that log back and reconciling against a fresh offline re-derivation (`evaluation/rank_signal_calibration.py::reconcile_book_history_date()`), reporting per-date symbol overlap/role mismatches/score-and-weight deltas, persisted to `ml/evaluation/book_history_reconciliation.json`.
- Fixed a real bug: `evaluation/model_predictions.py::build_sequence_windows()` builds trailing windows from ordinal row position not calendar dates, which would silently corrupt predictions if naively filtered to reconciliation dates; new `select_context_date_range()` computes the correct contiguous span.

**Verification:**
- No hysteresis replay in this round (documented limitation); no change to live selection/sizing logic — purely diagnostic. Full suite: 286 passed across touched test files.

## V5.2.3 — Full-universe snapshot, hysteresis replay, webui integration

**Summary:** V5.2.2's first real run (2026-08-07, 112 rebalance dates) surfaced two unexplained findings (#91): crypto/FX appear offline on 107/112 dates but in the live book on 0/112, and equities-only mean symbol overlap is only 54.8%.

**Shipped:**
- New opt-in `phase_v2.diagnostics.book_history.include_full_universe` — logs a `"universe"` snapshot of every symbol with a bar that date (selected or not), with `raw_rank_score`/`feature_ready`/`reason`/`trading_eligible`/`security_type`.
- New `--replay-hysteresis` CLI flag / `replay_book_history_reconciliation()` carries offline's held allocations forward across dates (mirroring live's `_last_book_allocations` and the walk-forward simulator), distinguishing real divergence from correct incumbent-holding behavior.
- New `summarize_universe_snapshot_by_security_type()` per-security-type aggregate.
- `book_history_reconciliation` and previously-unwired `book_spread_calibration` now served via `GET /api/evaluation` and shown in new webui panels (`BookHistoryReconciliationPanel`, `BookSpreadCalibrationPanel`).

**Verification:**
- Diagnostic-only round, no change to live logic. Update (2026-08-08 fresh backtest): byte-identical Sharpe/order-count/`OrderListHash` confirms the new logging is a true no-op. Crypto/FX never appear in `signals` on any of 112 dates at all — a bar-delivery problem, not a low-score problem. `self.bar_index` found running at ~2x the real trading-day rate, suggesting `on_data()` fires roughly twice per real day (leading hypothesis: separate Slices per asset-class Daily bar-close). Not yet fixed this round.

## V5.2.4 — Fixing bar_index inflation, the empty-book liquidation bug, and making crypto/FX book-eligible

**Summary:** Confirms and fixes V5.2.3's bar_index-inflation mechanism (equity-vs-crypto tick-splitting, not forex), fixes a second independent empty-book liquidation bug, and makes crypto/FX genuinely book-eligible.

**Shipped:**
- New `self.is_equity_session_bar`, computed fresh each tick from equity-bar data presence, gating `self.bar_index`'s single increment site — fixes every downstream bar_index-keyed consumer (rebalance cadence, cooldowns, max-holding exits, rotation cooldowns, limit-order timeouts) automatically, confirmed via full-repo grep.
- `should_rebalance_this_bar()` gained `is_trading_day_bar` parameter (default `True`) to prevent a frozen bar_index across off-session ticks from spuriously re-triggering rebalance.
- Kill switch's rolling-Sharpe/drawdown-velocity inputs now use dedicated equity-session-cadenced trackers separate from real-time `assess_drawdown_lock` inputs — `evaluation_bars: 60` becomes a real ~60-trading-day window (was effectively ~30).
- Fixed a second bug: `build_rank_based_book()` force-sold the entire book whenever `book_allocations` came back empty for ANY reason, not just genuine rotation-out; new `should_exit_non_selected_book_symbol()` fixes this.
- Made crypto/FX genuinely book-eligible: Phase 1a's per-symbol loop no longer skips symbols without a fresh bar on the equity-session tick if enough accumulated window history exists — uses last-known OHLCV snapshot instead; window/sequence-buffer appends still gated to genuinely-fresh bars only.

**Verification:**
- Full blast-radius audit (options, futures, corporate actions, audit-log, warm-up, Pass 2 ordering) confirmed clean. Full suite green, `py_compile` clean, extensive manual read-through.
- Update (2026-08-09 backtest): mean rebalance gap 10.29 business days (was 5.2), matching `rebalance_every_bars: 10`; 57 rebalances (was 112). Orders ~halved (392 vs. 768), fees ~halved ($372 vs. $664.70), turnover ~halved (0.27% vs. 0.49%). All 3 security_types now appear in the universe snapshot; 189 non-equity selections across 57 dates (BTCUSD/LTCUSD constantly long, several FX pairs short). Sharpe improved -4.103 vs. -4.421, but offline-vs-live gap not fully closed (V5.2.3's equity-only divergence and V5.2.1's execution-lag mechanism still open).

## V5.2.5 — Fixing the live-vs-offline `bond_empirical_duration_beta` mismatch

**Summary:** Continues the equity-only divergence investigation (54.8% overlap), ruling out price drift and scaler mismatch, and confirms `bond_empirical_duration_beta` as one real root cause; the fix produces a genuine Sharpe improvement but a mixed reconciliation-metric result.

**Shipped:**
- Ruled out: price data drift (NVDA/GE byte-identical between dataset and raw Lean zips), scaler mismatch (recomputed scaled columns matched to ~1e-15), and execution lag (re-confirmed already ruled out in V5.2.1 — this had been mis-stated as still-open).
- Root cause: offline `train.py::build_bond_features_by_date()` computes the OLS duration-beta slope once per ticker over full history and broadcasts it; live `main.py::_bond_empirical_duration_beta_for_symbol()` recomputed it every bar from a rolling 260-bar deque, a continuously-drifting out-of-distribution input. Corroborated by recurring bond ETFs in the mismatch lists (TLH, TLT, BIV, GOVT, VCIT, IEF live-only; SHY, VCSH, BWX offline-only).
- Fix: new `should_lock_in_duration_beta()` (`risk_controls.py`), true once both price and treasury-yield windows reach 260 bars; `_bond_empirical_duration_beta_for_symbol()` caches and locks the value permanently once both windows clear, via new `self._bond_empirical_duration_beta_cache`. Non-bond symbols unaffected.
- Secondary code-quality fix: `cs_momentum_rank_20` was independently reimplemented in `train.py`; confirmed bit-identical (diff ~1e-16) to the shared `features.cross_sectional_momentum_rank()`, so not an active bug — rewritten anyway to call the shared function and remove drift risk.

**Verification:**
- 5 new tests for `should_lock_in_duration_beta()`, 1 regression test for the `cs_momentum_rank_20` rewrite (byte-identical output vs. old formula). Full suite green; `py_compile` clean.
- Fix B (momentum rewrite) confirmed a true no-op: Codespace retrain + reconciliation produced 49.3059%/53.7895% overlap, matching the pre-fix baseline (0.5378951267984998) to every decimal place.
- Fix A (duration-beta lock) confirmed via fresh real Lean backtest: Sharpe improved -4.103 → -3.351 (~18% relative), but overlap did NOT confirm cleanly — independent-mode overlap dropped 49.31%→48.14%, hysteresis-replayed dropped 53.79%→49.96%; several bond ETFs (TLH, TLT, SHY, VCSH) flipped sides rather than disappearing; order count/fees/turnover rose slightly. Not reported as a clean root-cause closure. NVDA, GE, WFC, XOM, BA, and forex/crypto mismatches remain an open thread.

## V5.2.6 — Fixing the crypto/FX execution-path bug and closing the live-vs-offline risk-gate gap

**Summary:** An investigation-only deep-dive found two dominant, previously-undiscovered mechanisms behind the remaining NVDA/GE/WFC/XOM/BA/forex/crypto divergence: crypto/FX orders never actually execute, and live carries ~10 risk/execution gates with zero offline counterpart. This round fixes both.

**Shipped:**
- Finding 1: `main.py::_midpoint_bar_from_quote_bar()` hardcodes `volume=0.0` for forex; `liquidity/market_liquidity.py::build_liquidity_decision()`'s `if volume == 0.0` check unconditionally vetoes every forex order. A live BTCUSD bar with OHLC matching raw data also showed `volume=0.0` (likely a Lean/Coinbase data delivery quirk) — V5.2.4's crypto/FX book-eligibility was, in practice, phantom.
- Finding 2: `evaluation/rank_book_simulator.py`'s only execution-realism modeling is `entry_lag_bars` and the commission floor; two live gates duplicate signal the model's own active features already encode, and `min_confidence_to_trade` was never empirically calibrated.
- Fix 1: `build_liquidity_decision()` gains `zero_volume_fallback_ddv`, applied to forex always and to `quality_tier=="core"` crypto only (BTCUSD/LTCUSD); a new per-symbol bar counter in `state.json`'s `"diagnostics"` key.
- Fix 2: `build_market_analysis_decision()` gains `is_book_selected`/`min_confidence_to_trade_book_selected`, defaulting to today's single-threshold behavior.
- Fix 3: new `aq evaluate --calibrate-confidence-threshold` (`evaluation/confidence_threshold_calibration.py`); general threshold calibrated to 0.0968 (applied); book-selected threshold calibrated to 0.8925 but deliberately NOT applied (methodologically circular — book selection is already an extreme-rank filter).
- Fix 4: new `risk_off_override_min_severity` (analyzer) and `elevated_volatility_threshold` (topology, now threaded through `build_market_topology()`). Replaying `classify_risk_regime()` found 3 discrete severity tiers (-0.30/69%, -0.55/20%, -0.65/11%); applied `risk_off_override_min_severity=0.55` at the 25th-percentile boundary via a `None`-sentinel (the naive `0.0` default would NOT have been a safe no-op — drawdown-only risk_off can carry risk_score up to +0.10). `elevated_volatility_threshold` left at its 0.45 default.
- Fix 5: `build_book_history_record()` gains optional `book_member_decisions` (each book member's final action/reasons), requiring the book_history write to defer until after Pass 2 finishes; new `summarize_book_member_diversion()` wired into `aq evaluate --reconcile-book-history`.

**Verification:**
- `py_compile` clean; 33 new tests across 7 files; full suite 2530 passed (same 11 pre-existing Docker-only errors). Manual read-through confirmed all new config keys default to pre-V5.2.6 behavior.
- Update (2026-08-10): first backtest attempt crashed on `cannot access local variable 'spread_check_ranks'` (the deferred book_history write was gated on stale `book_allocations` truthiness); fixed with new `book_history_should_log_this_bar` flag. Full suite re-run clean (2505 passed).
- Update (2026-08-10, re-run succeeded, `backtests/2026-08-10_15-04-53`): Sharpe -2.984, up from -3.351, 437 orders, $407 fees. New diagnostic surfaced two further bugs fixed in V5.2.7: forex orders still never execute (a lot-sizing bug), and a 2020-02-27 kill-switch trip stayed stuck for the remaining 13+ months.

## V5.2.7 — Fixing the forex order-sizing bug and the sticky kill-switch lockout

**Summary:** Fixes two bugs surfaced by V5.2.6's `book_member_decisions` diagnostic: forex orders could never execute at portfolio scale, and a single kill-switch trip locked out the entire book for 13+ months.

**Shipped:**
- Bug 1: `main.py::_forex_lot_count_for_weight()` divided notional by a full 100,000-unit standard lot's dollar value; at realistic 4-12% book-member weights, notional ($4,000-$12,000) never reached one lot ($67,000-$130,000+), always rounding to 0. Confirmed 6 forex allocations reached `"trade"` then silently produced zero orders.
- Fix: new `risk_controls.py::compute_forex_order_units()` converts target weight directly to whole base-currency units (`round(notional / close_price)`), matching Lean's documented Forex `MarketOrder()` convention (raw units, not lots); deliberately does not round to a lot-size multiple (an earlier draft did and still produced 0). `_forex_lot_count_for_weight()` renamed `_forex_order_units_for_weight()`; dead `pair_spec` lookup removed. New opt-in `forex_order_sizing.jsonl` diagnostic logs `notional_ratio` per real forex order.
- Bug 2: kill switch tripped once on 2020-02-27 (`kill_switch_rolling_sharpe_below_floor`) and, by design, never auto-cleared — `kill_switch_*` sticky reasons are intentionally exempt from daily auto-clear. Measured: 40.4% of book-member decisions reached `"trade"` before the trip; 336/336 (100%) forced to `reduce_risk` for the remaining 13 months. Also found `is_backtest_safety_bypass_active()`'s docstring understated its actual effect — `bypass_safety_gates` cleared both the drawdown lock AND any kill_switch sticky reason together.
- Fix: new `is_sticky_trade_lock_bypass_active()` and `is_regime_drawdown_bypass_active()`, splitting the bundled behavior into independently configurable `phase_v2.backtest.bypass_sticky_trade_lock`/`bypass_regime_drawdown_gate` keys; legacy `bypass_safety_gates` still works (OR'd into both) with a one-time `Debug` nudge. This round turns on only `bypass_sticky_trade_lock`. `evaluate_kill_switch()` itself stays stateless/untouched.

**Verification:**
- `py_compile` clean; 18 new tests in `tests/test_risk_controls.py` (65 passed in that file); full suite 2523 passed, 14 deselected (2505 + 18 = 2523, same pre-existing Docker-only exclusion). Manual read-through confirmed dead code removed, diagnostic write gated backtest-only/real-orders-only, `Debug` nudge fires at most once, both new config keys default to prior behavior.
- Update (2026-08-11, `backtests/2026-08-11_09-56-24`): both fixes confirmed in production. Sharpe -2.984 → -2.17 (~27% relative), 644 orders (up from 437), $840 fees (up from $407). `notional_ratio` within 0.15% of 1.0 across all 193 diagnostic records — Lean's Forex `MarketOrder()` does take raw units. 220 real forex fills across 9 pairs appeared for the first time ever (crypto still doesn't trade — separate, unresolved). Kill switch now trips 26 separate times (was once, stuck forever) and clears at the next session each time; 120 `trade` decisions occur across the run, 109 after the first trip. Book-reconciliation overlap moved slightly against (independent 48.14%→47.37%, hysteresis 49.96%→48.59%), consistent with this metric's established unreliability as a Sharpe predictor. Both fixes ship as permanent; the 26-trip cadence flagged as a new open follow-up question (is the kill-switch's rolling-Sharpe floor too sensitive?).

## V5.2.8 — Closing unnecessarily-open Problems.md items and continuing the live-vs-offline gap investigation

**Summary:** Two-stage patch. Stage 1 closes every remaining non-IB, non-options/futures `Problems.md` item (3 entries, mostly stale-doc corrections). Stage 2 continues the live-vs-offline investigation from #91-#93: a real, working (if deliberately approximate) offline kill-switch replay, an optional gate-aware training-loss weight, a kill-switch sensitivity sweep, and a re-check of the still-unexplained NVDA/GE/WFC/XOM/BA divergence and the overlap metric's continued erosion.

**Shipped:**
- Stage 1: `execution/order_gate.py::classify_order_status()` now classifies `"CancelPending"` as `"pending"` (confirmed via 33 real `order-events.json` files, always paired 1:1 with a `"canceled"`; precision fix, zero behavior change). `Problems.md` #60/#61 corrected — Forex is fully live (not "zero live tickers"), and the bond-feature-schema retrain caveat was already closed by #70; both stale-doc only.
- Stage 2a: new `evaluation/kill_switch_replay.py` — a day-by-day offline replay of the kill-switch + sticky trade-lock state machine against the rank book's own return series, explicitly approximate (no bypass flags, no `net_edge`/book-selection modeling). New `aq evaluate --replay-kill-switch` flag, not in `--all`. Sensitivity sweep (`min_rolling_sharpe` × `evaluation_bars`, 20 combos) found lockout duration is close to binary under a non-bypassed replay — a trip either never happens, or locks out ~58-74% of the remaining ~2.2 years regardless of exact threshold. No config change applied.
- Stage 2b: new `train.py::compute_gate_friendliness_weight_by_date()` — an optional per-date training-loss weight from the same stateless topology/regime-severity gates the live analyzer uses (liquidity and the portfolio-level kill-switch excluded — no clean per-row training-dataset equivalent). Threaded as an optional `date_weights` parameter through the ranking-loss functions (`None` default, byte-identical to today); wired into both trainers behind `gate_aware_ranking_weights.enabled` (default `false`).
- Stage 2c/2d: re-ran book-history reconciliation against the real V5.2.7 log — NVDA/GE/WFC/XOM/BA all still recur prominently. Checked the one lead from #90's bond-duration-beta pattern against `cross_asset_sensitivity.py` — ruled out, both sides use the identical 252-day lookback. Both threads remain unexplained.

**Verification:**
- 33 new tests — full suite 2523 → 2556 passed, 0 failures. `py_compile` clean. `--replay-kill-switch` confirmed end-to-end against the real dataset.
- **Codespace smoke test (2026-08-12):** `gate_aware_ranking_weights.enabled: true`, 3 epochs — both trainers ran clean, no crash/NaN (rank_5d IC 0.10-0.11, t-stats ~6.3-6.4). Full `--walk-forward` pipeline (6 expanding windows, 2014-2021) also ran clean end to end: `rank_20d_ic` mean 0.1171, CI [0.0768, 0.1599], stable across all 6 windows; net Sharpe mean 0.78 (5/6 windows positive). Not a verdict on the flag — 3 epochs isn't comparable to production's 120/60 and no flag-off control ran alongside it — only confirms the mechanism is structurally sound. Active `ml/` artifacts untouched (backed up regardless, gitignored); new artifacts pulled into local `ml/versions/`; Codespace config reverted and stopped.

See `development/Problems.md` #94 for the full investigation, evidence, and honest scope notes.

## V5.2.9 — Full-scale production retrain with gate-aware ranking weights, promoted to active `ml/`

**Summary:** Follows up on #94's smoke test with a real, full-epoch (120/60) production training round: `gate_aware_ranking_weights` turned on for real, the candidate promoted to active `ml/`, RL sizing re-evaluated, and a full-epoch walk-forward pass. Topology excluded — needs a real Lean backtest's experience events through local Postgres/Redis, out of scope this round.

**Shipped:**
- `gate_aware_ranking_weights.enabled: true` for both trainers.
- Full Codespace candidate pipeline at production epoch counts (`train.py --candidate` → `train_gating.py` → `train_multitask.py` → `train_sequence.py` → `train_rl_sizing.py`), promoted to active `ml/` via `retraining.artifacts.copy_candidate_to_active()` after backing up prior artifacts to `ml/_backup_pre_v529_full_retrain/` (gitignored). `train_strategy_selector.py` failed as expected (no Postgres/option data). `train_topology.py` skipped.
- Full `--walk-forward` (6 expanding windows, 2014-2021) at the same settings, validation only.

**Verification:**
- New candidate vs. prior (2026-08-04) production model: rank_5d IC 0.097→0.109 (t 5.99→6.33), rank_20d IC 0.152→0.173 (t 9.24→10.28); direction-head MCC regressed (0.026→0.016). Dataset refresh and the flag both changed at once, so the gain isn't cleanly attributable to either alone — judged net positive since book selection is IC-driven.
- RL sizing: honest-negative result reproduced a third time (backtest policy expected reward -8.42e-5 vs. -7.74e-5 constant baseline) — stays disabled.
- Walk-forward: backtest MCC mean 0.0221 (95% CI [0.0082, 0.0342], stable); rank_20d_ic mean 0.0849 (CI [0.0404, 0.1173], 0% sign flips); net Sharpe mean ~0.65, 5/6 windows positive. One window's sequence stage timed out, absorbed cleanly by walk-forward's best-effort design.

See `development/Problems.md` #95 for full evidence and scope notes. A representative Lean backtest against this new candidate is left to the user (manual run); topology training remains a distinct, unscoped follow-up.

## V5.2.10 — README Backtest Results split into Lean/Offline Evaluation/Walk-Forward/Other Metrics/Disclaimer, all auto-updating

**Summary:** V5.2.9's real Lean backtest (Sharpe -1.72) plus a full offline cross-analysis (`--reconcile-book-history --replay-hysteresis`, `--replay-kill-switch`, both models' `--all`) surfaced a lot of numbers worth keeping visible, not just chat output. Restructures the README's Backtest Results section into five auto-regenerating subsections instead of one, and fixes a couple of real bugs the work surfaced along the way.

**Shipped:**
- README `## Backtest Results` split into `### Lean Backtest` (unchanged), `### Offline Evaluation`, `### Walk-Forward Training/Testing`, `### Other Metrics` (real vs. offline comparison), `### Disclaimer` — each with a compact table plus a foldable full-stats `<details>` block, matching Lean's existing pattern. Replaces a stale, Phase-4.12.3-era caveats block that had drifted out of date. Table of Contents and CLI Reference both updated to match (also added a previously-missing `aq paper-readiness` TOC entry).
- New `generate_evaluation_report.py`, wired into `cmd_evaluate` (3 exit points) and `cmd_backtest`, mirroring `generate_backtest_report.py`'s marker-replace/never-fail contract. Reads `ml/evaluation/*.json` and the newest `ml/versions/walk-forward-*/walk_forward_summary.json`; every section degrades to a placeholder, never a crash, when its source is missing.
- `cmd_evaluate` now additionally persists per-model-suffixed copies (`rank_book_simulation_{model}.json` etc.) alongside the existing unsuffixed files — fixes a real bug where evaluating `multitask` after `sequence` silently clobbered the first model's data with no way to compare both.
- `monitoring/evaluation_state.py` now also surfaces `kill_switch_replay.json` — an existing gap, never wired into the webui's evaluation state before.
- Other Metrics' kill-switch row now shows the *real* trip count (parsed from the Lean run's own log), not just the offline replay estimate — the comparison is the entire point of the section.

**Verification:**
- 15 new tests (`test_generate_evaluation_report.py` ×14, `test_evaluation_state.py` ×1); 16 existing `cmd_evaluate` tests updated with a mock for the new README-refresh call — caught during development that without it, running the test suite would have silently overwritten the real project README.md. Full suite: 2574 passed, 0 failures (excluding the real-Lean-backtest-dependent `test_lean_backtest_ml_coverage.py`, excluded by default per its own established convention).
- Real numbers now on the page: Lean -1.72 vs. offline sequence/multitask +1.52/+1.33 vs. walk-forward mean +0.65 (gaps of +3.24/+2.37); book-history reconciliation 24% mean overlap, 0/174 exact matches, 870/1464 book-member decisions diverted to `reduce_risk`; kill-switch 0 real trips vs. 78 offline-replay-estimated trips (73.5% locked) — a striking confirmation the replay tool is a deliberate over-estimate, not a bug.

## V5.3.1 — Limit-order docs/testing/tooling (#34) and book-history reconciliation bugs (#91), closed as completely as possible without a live Lean run

**Summary:** Deep research (5 parallel investigation passes) plus direct verification found `phase_v2.limit_orders` has actually been on by default all along (docs said otherwise), a second real bug beneath V5.2.5's bond-duration-beta fix, and a real hardcoded-assumption bug in the reconciliation tool itself — plus ruled out one suspected divergence source (FX/crypto) as a measurement artifact, and caught V5.2.10's own "0 real kill-switch trips" claim as never having been a real measurement. No live Lean backtest this round (out of scope) — every fix and check below is offline.

**Shipped:**
- Corrected 2 stale "limit orders are off by default" claims (`main.py`, `execution/README.md`); investigated the future/option fallback asymmetry and found it deliberate (no change made, correcting the original plan).
- Extracted `should_clear_pending_limit_order()`/`resolve_limit_order_timeout_action()` into `execution/order_gate.py` — `main.py` can't be imported outside a real Lean process, so this is the only way to unit-test the `PartiallyFilled` handling path end-to-end.
- New `evaluation/limit_fill_simulator.py` (`aq evaluate --simulate-limit-fills`) and standalone `scripts/order_events_audit.py` — two new offline diagnostics for limit-order behavior, neither needing a live backtest.
- `main.py:598`'s warm-up floor raised from `21` to `self.long_bar_history_size` (`260`) — closes a real cold-start gap in `bond_empirical_duration_beta` (and, for free, `cross_asset_sensitivity`) that V5.2.5's fix didn't reach.
- `reconcile_book_history_date()`/`replay_book_history_reconciliation()` (`evaluation/rank_signal_calibration.py`) now read real per-date `trading_eligible` from the logged `"universe"` payload instead of hardcoding `True`.
- New `summarize_universe_presence_by_symbol()`, run-segmented (not averaged across `book_history.jsonl`'s cumulative history) — the "FX/crypto absent 32% of the time" finding turned out to be 100%-absent-in-one-old-run diluted by 5 clean newer runs, not a live bug.
- `generate_evaluation_report.py::_count_real_kill_switch_trips()` now always returns `None` (the real trip-audit event is Redis-only and never reaches the text log it was counting) — README renders an honest caveat instead of a fake `0`.

**Verification:**
- 37 new tests across `test_order_gate.py` (9), `test_limit_fill_simulator.py` (8, new file), `test_order_events_audit.py` (9, new file), `test_rank_signal_calibration.py` (9), `test_generate_evaluation_report.py` (2). Full suite: 2574 → 2609 passed, 0 failures.
- `--simulate-limit-fills` and `order_events_audit.py` both sanity-checked against real data (82.95% fill rate; exact 23/23 cancel-pairing reproduced from 43 real backtest folders).
- Reconciliation eligibility fix re-verified against real V5.2.9 data: correctly applied, zero net effect on this dataset's overlap metric — later flagged (see below) as measured against a contaminated multi-run sample, so the specific 24.02% figure isn't a clean read; the code fix itself stays verified via unit tests either way.
- NVDA/GE/WFC/XOM/BA: sector-neutrality hypothesis ruled out by direct code proof, not just absence of a pattern — remains open.

**Update (2026-08-14):** a real Lean backtest (`backtests/2026-08-14_18-46-38`, Sharpe -1.034, up from -1.72) confirmed the bond warm-up fix live. Initial comparison against a believed-clean "prior run" snapshot suggested a severe new ~7-month book-disengagement regression — this was itself a data-contamination artifact (the "prior run" file was an undiscovered 7-run cumulative log); the true immediately-prior real backtest already showed the identical gap, so the fix is now verified with no evidence of any downside. Full story, including the self-caught investigation error, in `development/Problems.md` #98.

See `development/Problems.md` #96/#97/#98 for full evidence and scope notes.

## V5.3.2 — Root-causing #91/#97 (NVDA/GE/WFC/XOM/BA divergence) and #98 (confidence-spread disengagement gap)

**Summary:** An in-depth, no-stone-unturned research pass (3 parallel investigation agents plus direct data analysis, no live Lean backtest) closed #98 as genuine model behavior (not a bug) and found two real, fixable bugs in the reconciliation tooling for #91/#97 — but those two fixes turned out not to explain the NVDA/GE/WFC/XOM/BA divergence; the real, measured evidence now points somewhere new.

**Shipped:**
- #98 closed: `ml/sequence_training_metrics.json`/`ml/multitask_training_metrics.json`'s own per-era diagnostic shows all 4 model/head combinations (sequence/multitask × rank_5d/rank_20d) independently collapse to statistically-insignificant IC in the exact Apr-Sep 2019 window the real backtests disengage in — a genuine no-edge stretch, `min_rank_confidence_spread` working as documented. Regime/drawdown gate and sticky kill-switch lock both directly ruled out as alternate causes. No code change to the gate.
- New `evaluation/rank_signal_calibration.py::segment_logged_records_by_run()`, extracted from #97's `summarize_universe_presence_by_symbol()` (refactored to use it, behavior-preserving).
- `aq_cli.py`'s `--reconcile-book-history` now segments `book_history.jsonl` by run before reconciling and defaults to the most recent run only, never a silent cross-run merge (confirmed: 92% of real logged dates recur across multiple historical runs). New `--reconcile-run-index`/`--reconcile-all-runs` flags.
- Fixed a live-vs-offline tie-break order mismatch: the reconciliation tool now builds its raw-scores dict in `config.json`'s configured universe order (matching `main.py`'s live `self.symbols` order) instead of pandas groupby row order — zero changes to the live decision path itself.
- Reported (not applied): `min_rank_confidence_spread` recalibrated against the currently-active `rank_5d` head returns 0.2901 vs. the live 0.5014 — real drift, deliberately deferred to a future round with a real Lean backtest to verify.

**Verification:**
- 12 new tests across `test_rank_signal_calibration.py`, `test_aq_cli.py`, `test_portfolio_book_construction.py`. Full suite: 2609 → 2624 passed, 0 failures (11 pre-existing Docker-unavailable errors, unrelated).
- Re-run against real `visualization/book_history.jsonl`: default output reproduces the earlier hand-isolated 35.08% overlap exactly; `--reconcile-all-runs` shows 21-35% overlap across all 8 real runs individually.
- NVDA/GE/WFC/XOM/BA re-measured on the densest real run: both bugs fixed, neither explains the divergence. Matched-day raw-score deltas are large (0.11-0.21, not near-zero as a tie-break artifact would show) and strongly directional (live selects, offline doesn't, ~4-5:1) — points at a real feature/data-computation discrepancy for these 5 tickers specifically, not a selection-boundary artifact. Stays open with a sharper, evidenced next lead.

See `development/Problems.md` #98/#99 for full evidence and scope notes.

## V5.3.3 — Root cause found and fixed for the NVDA/GE/WFC/XOM/BA divergence (4 of 5 tickers); confidence-spread recalibration applied

**Summary:** V5.3.2's "sharper lead" (a real raw-score computation discrepancy, not a selection-boundary artifact) traced to a genuine, previously-undiscovered data gap: 63 of 77 equity tickers had no local Lean split/dividend factor file, so offline training silently used raw, unadjusted prices while live was always correctly adjusted automatically by Lean. Fixed for the whole universe, with real, measured improvement for 4 of the 5 tracked tickers. Also applied (not just reported, unlike V5.3.2) the confidence-spread recalibration, freshly re-measured against the corrected dataset. No live Lean backtest run this round — the user runs one real `aq backtest` next to verify the recalibration's live effect.

**Shipped:**
- New `data_pipeline/factor_file_backfill.py` — derives real Lean-format split/dividend factor files from yfinance's own corporate-action history (same dev-only-dependency convention as `dividend_backfill.py`), `--apply`/dry-run gated. Run for real: 63 new factor files written, zero fetch failures across the full universe.
- `aq train --dataset-only` regenerated `ml/datasets/*.csv` with the new files picked up automatically — zero changes needed to `train.py` itself.
- `min_rank_confidence_spread` recalibrated fresh against the corrected dataset (0.2831, close to V5.3.2's pre-fix 0.2901 — confirms the calibration is stable) and **applied** to all three `config.json` locations that hold it (the live key plus both preset copies, the latter requiring a direct JSON edit since they're stored as flat dotted-string keys `aq config set` can't reach).
- Fixed a real, separate bug found while refreshing the README's offline evaluation numbers: `aq evaluate --all`'s non-`--json` "lag tax" reporting line used a literal Greek Δ, which isn't in Windows' default `cp1252` console codec — every non-`--json` `--all` run on this machine had been crashing mid-command (after rank-book's own report, before capacity/stress/calibrate-edge and before the README refresh), silently leaving those sections stale since Aug 13 with no visible error. One-line ASCII fix (`development/Problems.md` #101).

**Verification:**
- 14 new tests (`tests/test_factor_file_backfill.py`). Full suite: 2624 → 2638 passed, 0 failures (11 pre-existing Docker-unavailable errors, unrelated). `tests/test_aq_cli.py` (216 tests) re-confirmed green after the Δ fix.
- Mechanical fix confirmed on real data: every real ex-dividend date for XOM/WFC/BA/GE shows the artificial return dip disappear, replaced by a correction matching the real event's own magnitude (GE's spinoff: +4.08% measured vs. 1.04 factor, matching to two decimal places).
- Divergence re-measured against the corrected dataset: XOM's mismatch rate 93%→65%, WFC 78%→71%, GE 52%→47%, NVDA 69%→59% (a real second-order effect from the other 62 tickers' scores shifting). BA stayed flat — plausibly swamped by genuine 2020 volatility, not yet confirmed. Reported honestly as mixed-but-net-positive, not a clean sweep.
- Confirmed via code reading: this fix does not change `main.py`'s live/backtest behavior at all (Lean was always correct) — only future retrains and the offline reconciliation tool's ground truth. The recalibration is the only part of this round that changes live behavior.
- README's offline evaluation numbers refreshed against the corrected dataset for both models (`aq evaluate --all --model sequence`/`--model multitask`, after the Δ fix): multitask net Sharpe **1.334→1.681** (up), sequence net Sharpe **1.517→0.997** (down) — a genuinely mixed, real result, not a uniform improvement; some of sequence's prior apparent edge was plausibly benefiting from the uncorrected dividend-dip artifact. Capacity, cost-stress, and the Sharpe-gap comparison table all refreshed consistently alongside it.

See `development/Problems.md` #100/#101 for full evidence and scope notes.

## V5.3.3 real backtest verification (2026-08-17) — factor-file fix confirmed strongly live; confidence-spread recalibration regressed Sharpe

**Summary:** The user's real `aq backtest` (2019-01-01–2021-04-02, ~6.8h) tested both V5.3.3 changes. Clean single-variable A/B against the prior real run (`backtests/2026-08-14_18-46-38`) since the factor-file fix never touches `main.py`'s live path — only the recalibration does.

**Result:**
- Orders 230→695, unique trading days 130→360 (the lower confidence-spread threshold re-engaging far more dates, as predicted).
- **Sharpe regressed: -1.034→-1.798.** Net Profit -1.60%→-5.51%. Root-caused via the equity curve and #98's own per-era IC diagnostic: the lower threshold now trades through 111 of ~124 days in the *known* no-skill era (Apr-Sep 2019) and through two more weak/negative-IC eras in 2020 that the old threshold correctly avoided. The calibration methodology (natural score-dispersion percentile) can't distinguish "the model differentiates symbols" from "that differentiation is actually correct."
- **Factor-file fix (#100) confirmed far more strongly live than the offline-only estimate suggested**: fresh reconciliation against this run's own `book_history.jsonl` (56 dates, the densest live sample yet) — GE mismatch 52%→15%, BA 48%→12%, NVDA 69%→25%, WFC 78%→55%, overall overlap fraction 56.9% (the best of the whole investigation). XOM showed 100% mismatch but on only 9 appearances — flagged, not concluded.

**Recommendation:** reconsider/partially revert the applied `min_rank_confidence_spread` value in a future round; the factor-file fix itself should stay as-is.

See `development/Problems.md` #102 for full evidence.
