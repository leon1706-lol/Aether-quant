# Changelog

Detailed phase results for Aether Quant, moved out of `README.md` (see there
for the current status, project structure, and runbook). Newest entries at
the bottom, ordered chronologically by phase.

## Phase 2 Result

The current pipeline does the following:

- Loads Lean ZIP files for `AAPL`, `SPY`, `QQQ`, and `BTCUSD`
- Normalizes prices
- Loads assets per data window without reducing them to the smallest common intersection
- Computes features and the target variable
- Produces train, validation, and backtest splits
- Fits the scaler on the training split and saves it

## Phase 3 Result

The current training stage additionally does the following:

- Trains a more robust MLP classification model in PyTorch
- Uses layer normalization and dropout for more stable behavior
- Uses asset context as an additional model input
- Uses validation loss for early stopping
- Optimizes the decision threshold on the validation split
- Saves train, validation, and backtest metrics
- Saves a binary checkpoint to `ml/model.pt`
- Prepares a JSON export for later Lean inference

## Phase 4 Result

The current runtime stage additionally does the following:

- Loads `model_weights.json`, `feature_schema.json`, `dataset_manifest.json`, and `scaler_stats.json`
- Computes the same features as training directly in Lean
- Runs the exported MLP forward pass locally
- Produces real `buy`, `sell`, and `hold` signals from the model probability
- Writes model status, thresholds, and signal probabilities to `visualization/state.json`

## Phase 5 Result

The current validation stage additionally does the following:

- Computes strategy returns from the model probabilities
- Compares the strategy against buy-and-hold
- Exports return, annualized volatility, Sharpe, and max drawdown
- Writes equity curves for validation and backtest to `backtests/equity_curves.csv`
- Saves an overall report to `backtests/strategy_report.json`

## Phase 6 Result

The current paper trading preparation additionally does the following:

- Separates Lean runtime dependencies from local dev dependencies
- Successfully runs the algorithm in the real local Lean Docker runtime
- Uses risk controls for daily and total drawdown
- Blocks new trades on a risk breach and optionally liquidates open positions
- Uses minimum confidence and a cooldown between trades for more conservative signal execution

## Phase 8 Result

The current visualization stage additionally does the following:

- Extends `visualization/state.json` with dashboard, monitoring, and scene data
- Produces `visualization/scene.json` as the basis for the market/portfolio stage
- Exports Grafana-friendly snapshots and CSV files under `visualization/grafana/`
- Shows scorecards, an asset heatmap, a risk band, positions, and a 3D-like asset scene in the dashboard

## Phase 9 Result

The current multi-asset stage additionally does the following:

- Expands the universe to equities, ETFs, and three spot crypto coins
- Derives `ETHUSD` and `LTCUSD` daily series from existing Coinbase minute data
- Uses a more flexible training pipeline that no longer reduces assets to the smallest common intersection
- Scores each asset by data quality, training rows, and backtest rows
- Trains the model and scaler only on sufficiently robust assets
- Automatically flags series that are too short, like `ETHUSD` and `LTCUSD`, as `observation_only`
- Prevents trades on observation-only assets in Lean, while still showing them in state, dashboard, and scene
- Caps portfolio expansion with a maximum number of active positions plus equity and crypto exposure caps
- Runs a successful Lean backtest over the expanded daily universe

## Phase 10 Result

The current stabilization stage additionally does the following:

- Keeps large local artifacts such as `data/`, `backtests/`, `ml/datasets/`, and `.venv/` out of the public Git repo
- Documents the most important local commands for training, tests, Lean backtests, Lean reports, and the dashboard
- Uses structured runtime logs in `train.py` for dataset build, asset quality, and training progress
- Adds first `pytest` tests for feature engineering, asset quality decisions, and scaler fitting
- Adds risk control tests for drawdown locks, position limits, and exposure caps
- Validates data paths, asset configuration, and time windows before training with clear error messages
- Checks before Lean inference whether model, feature, and scaler artifacts are present

## Phase V2-1 Result

The new V2 fork additionally does the following:

- Uses the prior V1/Phase 10 code as a stable foundation
- Sets up the V2 module structure for MoE, experts, regime, topology, experience, risk, and monitoring
- Documents the planned V2 process flow in `development/v2_architecture.md`
- Documents the planned tech stack for Docker, Lean, PyTorch, PostgreSQL, Grafana, Telegram, and the HTML dashboard
- Keeps training and backtesting on the local Lean `data/` folder as the primary data source

## Phase V2-2 Result

The V2 Lean data pipeline additionally does the following:

- Sets up `data_pipeline/` as a stable V2 layer on top of the existing `train.py` pipeline
- Defines a V2 pipeline manifest for data source, universe, features, time windows, and asset quality
- Explicitly documents that training and backtesting continue to run over the local Lean `data/` folder
- Prepares clean integration points for MoE experts, regime detection, topology, dynamic risk, and the volatility dashboard
- Adds tests that lock in this Lean data contract

## Phase V2-3 Result

The V2 dynamic risk and position sizing stage additionally does the following:

- Adds `risk/position_sizing.py` as testable V2 risk logic
- Classifies volatility into `low_volatility`, `normal_volatility`, and `high_volatility`
- Adjusts target position sizes to the current rolling volatility
- Reduces position sizes in high volatility and allows controlled expansion in calm market phases
- Computes `base_target_weight`, dynamic `target_weight`, annualized volatility, and `leverage_factor`
- Writes these values into runtime state, the dashboard heatmap, and `visualization/grafana/runtime_asset_metrics.csv`
- Prepares the ground for the HTML live volatility dashboard

## Phase V2-4 Result

The HTML live volatility dashboard additionally does the following:

- Adds `volatility_dashboard.html` as its own V2 live view
- Automatically reads `visualization/state.json`
- Refreshes every 5 seconds
- Shows portfolio, risk lock, drawdown, target volatility, and maximum leverage factor
- Shows, per asset, signal, volatility regime, annualized volatility, base weight, dynamic target weight, leverage factor, confidence, and sizing reason
- Works in backtest/observation mode without a broker API key

## Phase V2-6 Result

V2 regime detection additionally does the following:

- Adds `regime/market_regime.py` as a testable quantitative regime layer
- Detects `bullish`, `bearish`, and `sideways` from 5d/20d momentum
- Detects `low_volatility`, `normal_volatility`, and `high_volatility` from rolling volatility
- Combines trend, volatility, drawdown, and optional correlation into `risk_on`, `risk_neutral`, or `risk_off`
- Writes a `regime` block per asset into the Lean runtime state
- Exports regime fields into the runtime monitoring CSV for Grafana

## Phase V2-7 Result

The V2 expert dataset stage additionally does the following:

- Adds `experts/expert_datasets.py` as a slicing layer for later expert models
- Uses quantitative regime detection for bullish, bearish, sideways, and volatility slices
- Filters expert training data to `training_eligible` assets
- Produces local expert CSV files under `ml/expert_datasets/` during the dataset build
- Writes `ml/expert_dataset_manifest.json` with row counts, split counts, tickers, target balance, and routing filters
- Keeps the generated expert artifacts out of Git

## Phase V2-8 Result

The V2 expert model stage additionally does the following:

- Trains separate PyTorch models for `bullish`, `bearish`, `sideways`, and `volatility`
- Uses the same MLP family as the baseline model, but with regime-specific training data
- Adds `python train.py --experts-only` for training experts only
- Also refreshes the expert models on a normal `python train.py` run
- Writes local expert weights and metrics under `ml/expert_models/<expert>/`
- Writes an overall summary to `ml/expert_training_metrics.json`
- Keeps all generated expert model artifacts out of Git

## Phase V2-8.5 Result

V2 expert stabilization additionally does the following:

- Uses smaller default networks for experts, with stronger dropout and higher weight decay
- Reduces expert training by default to fewer epochs and stricter early-stopping patience
- Scores each expert with a quality gate against validation, backtest, MCC, and the train/backtest gap
- Flags experts as `stable`, `watchlist`, or `disabled_for_gating`
- Writes `gating_eligible_experts` and `disabled_for_gating_experts` into `ml/expert_training_metrics.json`
- This prevents the later gating network from blindly using weak or overfit experts

## Phase V2-9 Result

The V2 gating network additionally does the following:

- Adds `moe/gating.py` as an explainable manager for the expert models
- Weights experts by quality gate, regime fit, and backtest/validation stability
- Uses `stable` and `watchlist` experts, but ignores `disabled_for_gating`
- Loads local expert JSON exports from `ml/expert_models/<expert>/model_weights.json` in `main.py`
- Combines baseline model probability and expert probability into a final MoE probability
- Writes `moe_gating`, expert probabilities, active experts, and decision type into runtime state and the Grafana CSV
- Automatically falls back to the baseline model if expert artifacts are missing

## Phase V2-10 Result

The central market analyzer additionally does the following:

- Adds `analyzer/market_analyzer.py` as a pure, deterministic decision layer that combines expert (`moe_gating`), regime, topology (optional, until V2-11), and risk output (risk lock, position sizing) into one final category
- Replaces the previous ad-hoc if/elif chain in `main.py.on_data()` with a call to `build_market_analysis_decision(...)`, without changing the actual order-placement behavior: `_apply_signal` still only runs for the `trade` category
- Classifies each asset per bar into exactly one of five categories: `observe`, `simulate`, `trade`, `reduce_risk`, `retrain_candidate`
- Prioritizes risk containment over model health over profit action over paper tracking over pure observation (a portfolio-wide trade lock and an asset risk-off regime always beat `retrain_candidate` and `trade`)
- Detects `retrain_candidate` via a stateless heuristic (no active experts plus low regime confidence), since the window-based performance triggers only arrive in V2-16
- Writes the full decision, including a `reasons` list, as a `market_analysis` block into every asset signal in `visualization/state.json`, automatically visible in the webui via the existing FastAPI pipeline
- Adds `tests/test_market_analyzer.py` with 13 tests (all five categories, topology absence, two priority tiebreaks)

## Phase V2-11 Result

3D topology market modeling additionally does the following:

- Adds `topology/market_topology.py` as a pure, deterministic cross-asset layer: pairwise Pearson correlation from returns, union-find clustering over a correlation threshold, 3D coordinates (similar assets sit close together, high volatility separates on the z-axis)
- Computes topology once per bar in `main.py` from `self.symbol_windows` (as of the previous bar, no lookahead) before the per-asset loop, without restructuring it
- Writes `visualization/topology_state.json` and a `state["topology"]` block, plus a per-asset `topology` context (`cluster_id`, `correlation_strength`, `market_distance`, `topology_risk`) into `visualization/state.json`
- Replaces the previous orbit placement in `_build_scene_payload` with real topology coordinates and adds correlation links between assets to the existing overview scene
- **Changes real trading decisions**: `analyzer/market_analyzer.py` gets two new, deterministic priority tiers — an asset with `topology_risk == "elevated"` is forced to `reduce_risk`, and an isolated asset (`topology_risk == "isolated"`, no sufficiently correlated peers) can no longer reach `trade` and falls back to `simulate`
- Adds a new webui tab `/topology` (its own 3D scene colored by action/regime/risk, plus a readable cluster list) and a `/api/topology` endpoint in `monitoring/api_server.py`
- Adds `tests/test_market_topology.py` (stable coordinates, stronger links for correlated assets, robust with missing/thin data, regime label aggregation) plus four new cases in `tests/test_market_analyzer.py`
- Documents in `V2-17.5` (see phase plan in the README) that these deterministic rules are meant to later be replaced by data-driven/learned versions once the experience pipeline (V2-13/14) and controlled retraining (V2-16/17) are in place

## Phase V2-12 Result

The market impact & liquidity engine additionally does the following:

- Adds `liquidity/market_liquidity.py` as a pure, deterministic per-asset liquidity layer: estimates daily dollar volume (`DDV = close × volume`), order value, participation rate, slippage, and round-trip cost without external data
- Classifies every asset order attempt as `normal`, `thin`, `high_impact`, or `blocked`, and recommends `allow`, `reduce_size`, `simulate_instead`, or `block`
- Automatically applies a configurable size reduction (`high_impact_size_factor=0.5`) on `high_impact`, before the market analyzer decides
- Adds two new deterministic priority tiers to `analyzer/market_analyzer.py`: `liquidity_blocked` forces `simulate`, `liquidity_thin` also forces `simulate` (below the existing risk-off and topology priorities, but above the `trade` path)
- Writes all liquidity fields (`daily_dollar_volume`, `participation_rate`, `estimated_slippage`, `spread_proxy`, `estimated_round_trip_cost`, `liquidity_risk`, `recommended_action`, `adjusted_target_weight`) as a `liquidity` block into every asset signal in `visualization/state.json`
- Adds static bid-ask spread proxies per security type (equity: 5 bps, crypto: 20 bps), since real bid-ask data can't be derived from daily OHLCV
- Bills real per-asset transaction costs in Lean: `ConstantPercentageFeeModel(0.0025)` for crypto (25 bps taker proxy) and `ConstantFeeModel(1.0)` for equities ($1/trade IB proxy)
- Adds `webui/src/components/risk/LiquidityTable.tsx` as a new liquidity panel on the risk page: shows per asset DDV, order value, participation rate, slippage, spread, round-trip cost, risk level, and recommended action with colored badges
- Adds `Dockerfile` (multi-stage: Node.js webui build → Python runtime) and an extended `docker-compose.yml` (new `aether-quant` service on port 8000, Grafana on port 3001 instead of 3000) so the overall infrastructure can be started consistently
- Adds 9 new unit tests in `tests/test_market_liquidity.py` and 4 new cases in `tests/test_market_analyzer.py`
- LTCUSD (only 2 days of data in the universe → DDV below the $100k floor) correctly hits `blocked` and is forced to `simulate` without disrupting the rest of the decision tree

## Phase V2-13 Result

The Redis experience queue additionally does the following:

- Adds `experience/redis_queue.py` as a new module with `build_experience_event()` (pure function) and `ExperienceQueue` (fire-and-forget Redis stream publisher)
- Immediately writes a JSON event via `XADD` into the Redis stream `aether:experience` after every complete asset decision (after `signal_payload.update`), capped at `maxlen=100000` entries (approximate)
- Every event contains: `event_id` (UUID), `event_type`, `created_at` (ISO UTC), `mode` (`backtest`/`observation`/`paper`/`live`), `symbol`, `ticker`, `signal`, `action`, `execution_note`, `probability_up`, `confidence`, `target_weight`, `regime`, `moe_gating`, `topology`, `liquidity`, `market_analysis`, `portfolio` (with `total_value`, `cash`, `current_drawdown`)
- Fails silently on Redis errors: `ExperienceQueue.push()` returns `False` and logs a WARNING; the Lean loop is never blocked or interrupted
- Loads `redis_url` from the `AETHER_REDIS_URL` environment variable (set in `docker-compose.yml` to `redis://redis:6379/0`), falling back to `redis://localhost:6379/0` for local development
- Configurable via `config.json phase_v2.experience` with `enabled`, `redis_stream`, and `maxlen`
- The Redis import is deferred (inside `ExperienceQueue.__init__`), so the code stays importable in Lean environments without the `redis` package
- Adds `redis>=5.0.0` to `requirements.txt` and `fakeredis>=2.20.0` to `requirements-dev.txt`
- Adds `tests/test_experience_queue.py` with 8 tests (required schema fields, disabled = safe no-op, Redis unreachable = no crash, JSON serialization, configurable stream name, all 4 modes, push writes to the stream, event ID uniqueness)
- Stopping point for Redis: no PostgreSQL yet in V2-13; V2-14 builds the persistence worker (`XREAD → INSERT INTO experience_events`)

## Phase V2-14 Result

The PostgreSQL persistence worker additionally does the following:

- Adds `experience/postgres_worker.py` as a standalone, synchronous worker that reads `aether:experience` via `XREADGROUP` and durably stores events in PostgreSQL
- Creates the `experience_events` table with embedded DDL: `event_id` (UUID, UNIQUE), `created_at`, `ingested_at`, `mode`, `ticker`, `symbol`, `signal`, `action`, `confidence`, `target_weight`, `payload` (JSONB) plus 5 indexes — no Alembic, no migration files
- Uses `ON CONFLICT (event_id) DO NOTHING` for safe, idempotent retry on Redis redelivery after a worker crash
- Routes malformed JSON messages into the dead-letter stream `aether:experience:deadletter` and immediately acknowledges them via `XACK`, without interrupting operation
- Leaves messages unacknowledged on a PG error — they stay pending and are redelivered after the Redis visibility timeout
- Implements exponential backoff (1→2→4→...→60s) and automatic PG reconnect in the `run()` loop
- Exports `event_to_row` (pure function, no I/O) and `PostgresWorker` from `experience/__init__.py`
- Adds `psycopg[binary]>=3.1` to `requirements.txt` and `requirements-dev.txt`
- Creates `requirements-worker.txt` as a minimal dependency list for the worker container
- Builds `Dockerfile.worker` as a minimal `python:3.11-slim` image with only `redis` and `psycopg[binary]`
- Adds the `experience-worker` service to `docker-compose.yml` (`depends_on: redis:healthy, postgres:healthy`, `restart: unless-stopped`)
- Extends `config.json phase_v2.experience` with a `worker` sub-block for group, consumer, batch size, dead-letter stream, and backoff max
- Adds 7 tests in `tests/test_postgres_worker.py`: scalar fields extracted correctly, full payload, batch persistence, duplicate idempotency, dead-letter routing, a PG error leaves messages pending, an empty stream returns 0
- Stopping point for PostgreSQL: V2-15 builds Observation Mode on top of the now-existing experience trail

## Phase V2-15 Result

Observation Mode additionally does the following:

- Adds `phase_v2.runtime` to `config.json` with `mode` (`backtest`/`observation`/`paper`/`live`, committed default `"backtest"` — unchanged behavior for `lean backtest .`) and `allow_live_orders` (default `false`)
- Adds the new, Lean-free package `execution/order_gate.py`: `resolve_runtime_mode` (falls back to `"observation"` on a missing/unknown value), `resolve_order_permission` (truth table: `backtest` always allowed, `observation` **never** allowed — regardless of any other flag, `paper`/`live` only with `allow_live_orders` + broker configuration + for `live` additionally a healthy risk lock), and `simulate_fill` (pure fill-price/quantity math)
- Adds a single gate method `_apply_signal`/`_refresh_risk_state` in `main.py` (`_order_permission()`) that decides, at all three real order sites (`SetHoldings`, per-symbol `Liquidate`, portfolio-wide `Liquidate` on a drawdown breach): a real order or a simulation
- Adds `experience/simulated_portfolio.py` (`SimulatedPortfolioState`): manages fake cash/holdings/equity curve/drawdown/exposure/turnover entirely in memory, never touching `self.Portfolio` or any broker call; `snapshot()` is a superset of the previous `portfolio={...}` dict, so **no signature change** is needed for `build_experience_event`, `event_to_row`, or the Postgres DDL (`mode VARCHAR(20)` already supported `observation`/`paper`/`live`)
- Makes `self._experience_mode` (previously hardcoded to `"backtest"`) depend on the new `runtime_mode`
- Makes cooldown, max-position, and exposure-cap checks, as well as the drawdown/risk-lock computation, mode-aware: when real orders are blocked, these checks run against the simulated instead of the real portfolio (which stays permanently empty in blocked modes) — otherwise risk rules would be ineffective in Observation Mode
- Adds `experience/observation_metrics.py`: pure functions (`count_observations`, `signal_distribution`, `action_distribution`, `rejected_by_reason`, `simulated_win_loss`, `simulated_sharpe`, `simulated_max_drawdown`, `compute_observation_summary`) operating on a single `list[dict]` shape, usable identically for in-memory logs and Postgres JSONB rows; `rejected_by_reason` reads the already-existing `reasons` list from `analyzer/market_analyzer.py` — no new schema field needed
- Writes new dashboard exports `visualization/grafana/observation_summary.json` and `visualization/grafana/observation_equity_curve.csv`, also embedded as `state["observation"]` in `visualization/state.json`; clearly marked "SIMULATED - NOT REAL TRADES"
- Extends `monitoring/api_server.py` with `/api/grafana/observation-summary` and `/api/grafana/observation-equity-curve`
- Adds the webui panel `webui/src/components/monitoring/ObservationPanel.tsx` (data-table style, no new chart package), wired into `webui/src/pages/Overview.tsx`
- Adds 33 new tests (80 → 113 total): `tests/test_order_gate.py` (10, including the safety-critical `test_observation_mode_never_allows_orders_even_if_flags_true`), `tests/test_simulated_portfolio.py` (9), `tests/test_observation_metrics.py` (14) — `main.py` deliberately still has no unit tests of its own (importing it requires `AlgorithmImports`/Lean, which none of the 13 existing test files do); the safety guarantee is fully proven at the `order_gate`/`simulated_portfolio` level
- Manually verified via a real `lean backtest .` run with `mode="observation"` (2014-2018, BTCUSD/ETHUSD/LTCUSD): Lean's own statistics show `"Total Orders": "0"` and `"End Equity": "100000"` (unchanged) across the whole run — the real portfolio was never touched — while the observation panel in the webui showed real simulated activity (drawdown, turnover, a simulated risk-lock breach at -12%)
- Stopping point: `phase_v2.runtime.mode` is only read at startup, no hot-reload during a running run
- After completion, two bugs were found and fixed during a Docker review — see `development/Problems.md`: `Dockerfile.worker` didn't copy `execution/` (ModuleNotFoundError), `requirements-worker.txt` was missing `numpy` (ModuleNotFoundError, crash loop in the running container)

## Phase V2-16 Result

Performance Triggers additionally does the following:

- Adds the new, Lean-free package `performance/triggers.py`: 8 trigger functions (`observation_count_trigger`, `drawdown_trigger`, `sharpe_degradation_trigger`, `win_rate_trigger`, `confidence_decay_trigger`, `regime_shift_trigger`, `liquidity_warning_trigger`, `risk_lock_trigger`) plus `evaluate_all_triggers()` as an aggregator — pure functions on the same `list[dict]` shape as `experience/observation_metrics.py` (V2-15), including reuse of `simulated_sharpe`/`simulated_max_drawdown` instead of reimplementing them
- Every trigger returns a structured event: `trigger_id`, `created_at`, `trigger_type`, `severity` (`info`/`warning`/`critical` by a breach-ratio rule), `mode`, `scope` (`portfolio` or ticker), `metric_value`, `threshold`, `message`, `recommended_action`, `retrain_candidate`
- `liquidity_warning_trigger` deliberately only counts `block`/`reduce_size` as a rejection — `simulate_instead` (Observation Mode routing) is explicitly excluded, so Observation Mode doesn't falsely look like a liquidity crisis
- `risk_lock_trigger` fires both on the activation transition (`warning`) and on a sustained lock past `max_consecutive_locked_events` (`critical`, always `retrain_candidate=True`) — for this, the `portfolio` block in `main.py` additionally gets `trade_lock_active`/`trade_lock_reason` (purely additive, no schema/DDL change needed)
- Extends `config.json phase_v2.performance_triggers` with the 7 user-specified thresholds plus 5 more (confidence decay/instability, risk-lock duration, rolling window, suppression minutes)
- Adds `performance/postgres_triggers.py`: embedded DDL for a **dedicated** `performance_triggers` table (not `experience_events` with a new `event_type`, so Grafana/Phase 17 can query it cleanly) plus `performance_trigger_watermark` for progress, `ON CONFLICT (trigger_id) DO NOTHING` plus an explicit suppression-window check against duplicate spam on sustained breaches
- Adds `performance/trigger_worker.py` as a standalone worker (`python -m performance.trigger_worker`, `--once` flag like `postgres_worker.py`) that advances through `experience_events` by watermark and durably persists triggers — deliberately **not** synchronous inside `main.py`/Lean, because the async Redis→worker path might not have caught up yet at the moment of a mid-backtest query (same decoupling principle as V2-13/14)
- `main.py` additionally gets a fast, purely in-memory view (`_build_performance_triggers_view()`, over `_observation_event_log`) for `state["performance_triggers"]` and `visualization/grafana/performance_triggers.json` — explicitly marked as non-durable (`source: "in_memory_current_run"`); the Postgres table remains the only source for Phase 17
- New service `performance-trigger-worker` in `docker-compose.yml` (depends only on `postgres`, no Redis; mounts `config.json` read-only, since the thresholds are strategy, not infra, configuration) plus `Dockerfile.trigger_worker` and `requirements-trigger-worker.txt`
- Extends `monitoring/api_server.py` with `/api/grafana/performance-triggers`
- Adds the webui panel `PerformanceTriggersPanel.tsx` (retrain-candidate banner, severity distribution, last trigger, trigger-type breakdown) and places it together with `ObservationPanel` at the very top of the right column, so it isn't pushed down by a growing signal board when there are many assets
- Adds 37 new tests (113 → 150 total): `tests/test_triggers.py` (24), `tests/test_postgres_triggers.py` (11), `tests/test_trigger_worker.py` (2)
- Along the way: documentation reorganized — `docs/v2_architecture.md` and `infrastructure/README.md` moved to `development/` (as `v2_architecture.md`/`infrastructure.md`), new `development/Changelog.md` (this file) and `development/Problems.md` created; the webui gets a consistent black/orange/white theme with an orange hover glow on every panel
- Stopping point: Phase 16 doesn't retrain anything — `retrain_candidate` is only a flag for V2-17, no automatic model-weight changes

## Visualization Unification Result

The visualization unification additionally does the following:

- Replaces `dashboard.html` and `volatility_dashboard.html` with a single React/Vite webui under `webui/` on `http://localhost:3000`
- Adds `monitoring/api_server.py` as a FastAPI JSON API that serves `visualization/state.json`, `visualization/scene.json`, and the Grafana exports on `localhost:8000`, instead of the frontend reading files directly from the filesystem
- Maps the Overview page (scorecards, asset heatmap, signal board, positions, strategy/risk cards, monitoring feeds) and the Risk page (risk core, asset volatility/sizing table) 1:1 onto the previous HTML dashboards
- Renders the market scene as genuinely three-dimensional and rotatable for the first time, using `@react-three/fiber`/`@react-three/drei` instead of the previous 2D-div approximation, as the foundation for the later V2-11 3D topology market modeling
- Keeps the existing polling pattern (React Query, 5s interval) and changes nothing about the Python writers of `state.json`/`scene.json`

## Phase V2-17 Result

Controlled Retraining closes the loop left open by Phase 16, and now does the following:

- Adds the new `retraining/` package, using the same pure/IO/worker split as `performance/` (V2-16): `planning.py` (pure, trigger selection/cooldown/minimum observations), `postgres_registry.py` (embedded DDL for `model_versions` and `retraining_events`), `validation_gate.py` (pure, candidate-vs-active comparison instead of `assess_expert_quality`'s fixed thresholds), `backtest_gate.py`/`lean_backtest.py` (backtest comparison plus an optional, best-effort real Lean run), `vault_commands.py`/`vault_client.py` (pure `av` command builder plus a subprocess wrapper, always catches a missing `av` binary), `artifacts.py` (hashing/copying/restoring candidate artifacts), `status_export.py` (writes `visualization/grafana/retraining_status.json`), `orchestrator.py` (CLI subcommands `plan`/`train`/`validate`/`backtest`/`commit`/`promote`/`rollback`/`status`), `worker.py` (`RetrainingWorker`, continuous, toggled via `phase_v2.retraining.enabled`)
- `train.py` gets a fourth mode, `--candidate --version-id <uuid>`: `train_model()`/`write_model_export()`/the scaler-writing logic (newly extracted as `write_scaler_artifacts()`) now take optional path kwargs, defaulting to the previous active `ml/`/`backtests/` constants, so no existing caller changes behavior; the candidate branch writes exclusively to `ml/versions/<version_id>/` and never touches the active paths
- `model_versions` tracks `status` (`active`/`candidate`/`rejected`/`promoted`/`rolled_back`/`archived`), `git_commit`, `aether_vault_commit`, artifact paths/hashes, training/validation/backtest windows, and metrics; a partial unique index enforces exactly one `active` model at the DB level
- `retraining_events` tracks `retraining_id`, `source_trigger_id`, `status` (`planned`/`running`/`validated`/`rejected`/`promoted`/`failed`), `reason`, `candidate_version_id`, metrics, and notes — the full audit trail per retraining attempt
- Promotion deliberately copies more files than named in the original spec (`model_weights.json`, `scaler.pkl`, `training_metrics.json`): also `feature_schema.json` and `scaler_stats.json`, because `main.py`'s `_validate_runtime_artifacts()` strictly needs exactly these two as well — without them a promotion would silently break the Lean loader
- Promotion hard-requires an existing `aether_vault_commit` (`phase_v2.retraining.promotion.require_vault_commit`) — without a successful Aether-Vault commit, there is no promotion
- Rollback verifies SHA-256 hashes against `model_versions.artifact_hashes` before activating any file; if local `ml/versions/<id>/` files are missing, it falls back to `av checkout <commit>` before retrying the restore
- Aether-Vault (`C:\Users\Blackhead\Desktop\aether-vault`, a separate sibling project) is invoked exclusively as an external `av` subprocess — its source is never read or imported anywhere; `run_av_command()` always catches a missing `av` binary/timeout and marks the `retraining_event` as `failed`, without crashing the pipeline
- `RetrainingWorker` is deliberately **not** an unconditionally auto-promoting daemon: `phase_v2.retraining.worker.auto_promote` defaults to `false`, so the worker stops after a successful vault commit (`status=validated`), and the actual model takeover remains a manual `python -m retraining.orchestrator promote --version-id <id>` — "no uncontrolled live learning" is thus preserved even with the worker running
- New service `retraining-worker` in `docker-compose.yml`; unlike `experience-worker`/`performance-trigger-worker`'s minimal images, this worker needs the full training stack (`torch`, `pandas`, `scikit-learn`, `joblib`), because `orchestrator.py`'s `train()` step invokes `train.py` via subprocess — `Dockerfile.retraining_worker` accordingly also copies `experts/`, `regime/`, and `train.py`
- Extends `config.json phase_v2.retraining` (cooldown, minimum observations, daily limit, validation/backtest gate thresholds, vault/promotion/worker configuration)
- Extends `monitoring/api_server.py` with `/api/grafana/retraining-status`; `/api/state` merges `retraining_status.json` in server-side, because `main.py` (unlike with `performance_triggers`) can't provide an in-memory approximation — it never holds its own Postgres connection
- Adds the webui panel `RetrainingStatusPanel.tsx` (active/candidate version, validation status, vault commit short hash, last trigger, rollback availability), placed directly below `PerformanceTriggersPanel`
- Adds 90 new tests (150 → 244 total), one test file per source file per the existing convention

## Phase V2-17.5 Result

The non-deterministic topology & retrain-trigger upgrade additionally does the following:

- Safety rule first: "non-deterministic" means probabilistic scoring (confidence/uncertainty), not random trades — every order still passes unchanged through the risk engine, liquidity engine, order gate, Observation Mode, and the V2-17 gates; `analyzer/market_analyzer.py` is **not** touched and continues to read only `topology_risk`/`state` from the deterministic layer
- Adds `topology/learned_topology.py`: pure Python (no numpy/sklearn at runtime, like `market_topology.py`/`regime/`/`liquidity/`); `apply_learned_topology(...)` overlays a probabilistic layer on top of the existing deterministic topology — never a replacement. Per node: `cluster_probs` (softmax over distances to trained prototypes), `topology_confidence`, `topology_uncertainty` (normalized entropy), `stress_score` (novelty signal), `neighbor_shift_score` (Jaccard drift of the learned neighbor set), `topology_disagreement`, bounded x/y/z offsets (never a full replacement embedding), and `topology_source` (`deterministic`/`learned`/`hybrid`/`fallback`). Falls back to the deterministic position per node (and, in the worst case, entirely) whenever the model is missing or not confident enough — never a crash
- New root script `train_topology.py` (numpy/scikit-learn allowed, never runs inside the Lean container): reads `experience_events` via the reused `performance.postgres_triggers.fetch_recent_events()`, derives a `win`/`loss`/`neutral` outcome label per ticker from `portfolio.last_realized_pnl` (backfilling the open-trade span retroactively), builds feature vectors, and fits `sklearn.cluster.KMeans` prototypes over z-scored features. Writes `topology_model.json`/`topology_training_metrics.json`/`topology_feature_schema.json` exclusively to `ml/versions/<version_id>/`; exits 0 (skipped, not an error) when there isn't enough training data
- `retraining/orchestrator.py` gets `train_topology()`: a second, independently-failable subprocess between `train` and `validate` — a failure is logged as a note on `retraining_events` and **never** rejects the candidate. `retraining/artifacts.py` gets `OPTIONAL_TOPOLOGY_FILES` (deliberately **not** in `REQUIRED_CANDIDATE_FILES`, so `validate()` never rejects for missing topology artifacts), but included in `ACTIVE_ARTIFACT_FILES`/`ALL_TRACKED_FILES` — the whole `ml/versions/<id>/` folder is already committed via `av add`, so topology artifacts are picked up automatically. `RetrainingWorker` calls `train_topology()` at the same spot; `auto_promote` remains `false` by default
- `performance/triggers.py` gets 5 new triggers: `topology_uncertainty_trigger`, `topology_regime_mismatch_trigger`, `cluster_drift_trigger`, `model_topology_disagreement_trigger` (all persistence-guarded: a window average **and** a minimum fraction of individually-breaching bars, so a single outlier never fires) plus `trigger_frequency_spike` (a meta-trigger over trigger *rows*, not events — a rate increase against its own baseline). `evaluate_all_triggers()` gets an optional `recent_triggers` argument, backward-compatible
- Fixes the V2-16 limitation: `performance/trigger_worker.py`'s `run_once()` still only advances the watermark over the incremental batch (cheap idle polls), but now evaluates triggers over a real rolling window from `fetch_recent_events()` — the last `rolling_window_events` observations, bounded to `rolling_window_days` days or since the last retraining (`fetch_last_retraining_at()`), whichever is more recent
- `retraining/planning.py::select_candidate_trigger()` now picks by priority score instead of just timestamp: severity + trigger-type weight + a bonus when a regime shift and a topology trigger co-occur (only for these types, not for unrelated candidates) + a capped repetition bonus. A single weak topology event doesn't even reach this selection stage — the persistence guards in `performance/triggers.py` already handle that
- Extends `config.json` with `phase_v2.topology_learning` (model thresholds plus a `training` sub-block), new thresholds/window sizes in `phase_v2.performance_triggers`, `phase_v2.retraining.topology_training`, and the three new filenames in `phase_v2.retraining.promotion.active_artifact_files`
- `main.py` loads `ml/topology_model.json`/`ml/topology_feature_schema.json` optionally (missing file ⇒ `None`, no hard failure, like the MoE expert exports) and calls `apply_learned_topology()` after the existing `build_market_topology()` call; liquidity/regime-risk-score inputs are necessarily one bar lagged (the same existing limitation as `latest_regime_by_symbol`)
- Webui: `state.ts` gets the new topology fields, `TopologyScene3D.tsx` shows `topology_source`/`topology_confidence` in the tooltip and slightly dims fallback nodes, a new panel `TopologyLearningPanel.tsx` (deterministic/learned/hybrid/fallback badge, aggregated confidence/uncertainty/stress/mismatch statistics) on the topology page
- `Dockerfile.retraining_worker` additionally copies `topology/` and `train_topology.py` — `requirements-retraining-worker.txt` already had numpy/scikit-learn/psycopg since V2-17, no new dependencies needed
- Adds 69 new tests (244 → 313 total): `tests/test_learned_topology.py` (18), extensions to `tests/test_triggers.py`/`test_trigger_worker.py`/`test_postgres_triggers.py`, `tests/test_retraining_planning.py`, `tests/test_train_topology.py` (10, new), `tests/test_retraining_artifacts.py`, `tests/test_retraining_orchestrator.py`, `tests/test_retraining_worker.py`
- Along the way: Docker host ports remapped so a local Aether Quant stack never collides with the separate Aether-Vault compose stack (which independently binds host 8000/3000/5432/6379) — `aether-quant` 8000→8001, Redis 6379→6380, PostgreSQL 5432→5433, the local Vite dev server 3000→3002, Grafana stays at 3001; the local, non-containerized `uvicorn` also moves to 8001

## Phase V2-18 Result

Grafana removed, native React tracing dashboard:

- Grafana's only job was displaying exports already served as JSON/CSV via `monitoring/api_server.py`'s `/api/grafana/*` routes (`equity_curves.csv`, `asset_performance.csv`, `observation_equity_curve.csv`, `runtime_metrics_snapshot.json`) — no computation path of its own, so no backend change was needed, just a new consumer
- `docker-compose.yml`: the `grafana` service, `grafana-data` volume, and `AETHER_GRAFANA_URL` env on the `lean` service removed; the stack now consists of Redis, PostgreSQL, `aether-quant`, and the three workers
- New webui page `TracingPage.tsx` under `/tracing` (nav entry in `AppShell.tsx`) with four panels under `src/components/tracing/`: `MetricsSnapshotPanel.tsx` (stat tiles from the runtime metrics snapshot), `AssetPerformancePanel.tsx` (diverging Sharpe bars per ticker, blue/red by sign, plus a table view), `BacktestEquityPanel.tsx` (ticker dropdown, strategy vs. buy-and-hold cumulative return line chart), and `ObservationEquityPanel.tsx` (simulated equity/cash line chart plus a drawdown chart, downsampled client-side to ~400 points against the several thousand bars of the Observation Mode export)
- Two new, dependency-free SVG chart primitives instead of a charting library: `LineChart.tsx` (crosshair+tooltip, a legend from two series on, subtle gridlines, never two Y axes) and `DivergingBarChart.tsx`, both reused by several panels
- `src/api/client.ts`/`hooks.ts` get `fetchMetricsSnapshot`/`fetchEquityCurves`/`fetchAssetPerformance`/`fetchObservationEquityCurve` and matching `useX()` hooks (15s refresh, called only from the tracing page itself, not globally like `useRuntimeState()`); new types in `src/types/tracing.ts`
- Deliberately NOT renamed: the `visualization/grafana/` folder, `retraining/status_export.py`, `performance/postgres_triggers.py`, and the `/api/grafana/*` route names — only the consumer changed; a rename would have been pure renaming risk with no user value
- Docs updated: `README.md`, `development/v2_architecture.md` (including a new "Remove Grafana, React Tracing Dashboard (V2-18)" section and an updated port table without the Grafana row), `webui/README.md`

## Phase V2-19 Result

Telegram Alerts additionally does the following:

- Adds the new, Lean-free package `notifications/`, using the same pure/IO/worker split as `performance/` (V2-16) and `retraining/` (V2-17): `telegram_alerts.py` (pure — `should_alert_trigger()`, `format_trigger_alert()`, `format_session_summary_alert()`, only renders already-computed fields, computes nothing new), `postgres_telegram.py` (embedded DDL for `telegram_alert_watermark`, one row per channel `"triggers"`/`"session_summary"`, plus `fetch_session_summaries_since()` as a defensive, never-raising read on `experience_events`), `telegram_client.py` (injectable Telegram Bot API wrapper, `send_message()` never raises, deferred `import requests`), `telegram_worker.py` (`TelegramWorker`, `python -m notifications.telegram_worker [--once]`)
- **Trigger channel**: polls the already continuously running `performance_triggers` table (V2-16) directly via `performance.postgres_triggers.fetch_triggers_since()` — no trigger detection of its own. Since every trigger type (not just `drawdown_trigger`) is reported from `phase_v2.telegram.min_severity_for_trigger_alert` up, risk-lock activation, regime shifts, liquidity rejections, Sharpe/win-rate/confidence degradation, and all five topology triggers come along with no extra instrumentation
- **Session summary channel**: `main.py` gets three additive changes — `self._session_events: list[dict]` collects the running session's events (alongside `self._observation_event_log`); in the existing session-rollover branch of `_refresh_risk_state()` (the date-change check that already resets `session_start_equity`), a new `experience.redis_queue.build_session_summary_event()` event (`event_type="session_summary"`) is now pushed **before** the reset, guarded against the very first bar, via the existing `ExperienceQueue` — the same Redis→`experience-worker`→Postgres pipeline as every other event, no new transport needed
- `build_session_summary_event()` (`experience/redis_queue.py`, exported from `experience/__init__.py`) itself only computes `session_return`; every other statistic comes unchanged from the already-existing `experience.observation_metrics.compute_observation_summary()`
- **Necessary, non-additive fix**: `experience/postgres_worker.py::event_to_row()` previously indexed `event["ticker"]`/`["symbol"]`/`["signal"]`/`["action"]` directly. A `session_summary` event has none of these fields (portfolio-level, not asset-level) — without the fix, a `KeyError` would have been raised, the event silently routed to the dead-letter stream, and `fetch_session_summaries_since()` would have returned `[]` forever, with no visible error anywhere. Fix: `.get(key, "")` defaults (backward-compatible, since `experience_events` columns are `VARCHAR NOT NULL` with no unique constraint), `action` falls back to `event_type`
- `Dockerfile.telegram_worker` copies `execution/`, `experience/`, `performance/`, `notifications/` — `execution/` is needed because importing `performance.postgres_triggers` transitively initializes `performance/__init__.py` → `.triggers` → `experience.observation_metrics` → (via `experience/__init__.py`) `.simulated_portfolio` → `execution.order_gate`; the same lesson as `development/Problems.md` #1/#2, applied proactively here instead of discovered after a broken build. `requirements-telegram-worker.txt` includes `numpy` for the same reason
- New service `telegram-worker` in `docker-compose.yml`, depends only on `postgres` (no Redis — the worker never touches the experience stream); new `.env.compose.example` (the `.gitignore` exception for it already existed, the file itself did not) documents `AETHER_TELEGRAM_BOT_TOKEN`/`AETHER_TELEGRAM_CHAT_ID`
- Extends `config.json phase_v2.telegram` (`enabled`, `min_severity_for_trigger_alert`, `session_summary_enabled`, `worker.{poll_interval_seconds,batch_size,backoff_max}`)
- Adds 24 new tests (Telegram part) plus 7 extensions to existing test files: `tests/test_telegram_alerts.py` (4), `tests/test_postgres_telegram.py` (7), `tests/test_telegram_client.py` (7), `tests/test_telegram_worker.py` (6), extending `tests/test_experience_queue.py` (5, `build_session_summary_event`) and `tests/test_postgres_worker.py` (2, `event_to_row` with `session_summary` events) — together with V2-19.5's 20 new tests: 313 → 364 total
- `tests/README.md`'s test count had already been stale since V2-17.5/V2-18 ("244 tests as of V2-17", actually 313) — corrected in this pass
- Stopping point: no more retry/backoff than necessary for the actual Telegram API call, no webui panel for alert history — both deliberately out of scope for V2-19

## Phase V2-19.5 Result

Yahoo Finance Historical Data Backfill (a supplementary request alongside V2-19, not an item in the original numbered plan) now does the following:

- Adds `data_pipeline/yfinance_backfill.py` as a **manual offline script** — never runs from `train.py`/`main.py`/a Docker worker, no network access during training or a backtest (same status as `train_topology.py`: "never runs inside the Lean container")
- Fills gaps in thin local Lean zips, most notably `ETHUSD`/`LTCUSD` (only a few scattered days of real Coinbase minute data, see `train.py::ensure_derived_crypto_daily_series()` and the Phase 9 entry above) — hence `observation_only` so far under `train.py::build_asset_quality()`'s row thresholds
- New, optional `"backfill"` sub-block per asset in `config.json phase1.universe.assets[]` (`source`, `symbol`, `backfill_from`, `backfill_to`) — deliberately a new key instead of reusing `aggregation: "daily_from_minute_trade"`, since that value already triggers `train.py`'s own Coinbase aggregation on every run, and this path must stay manual
- Pure functions (`yahoo_symbol_for`, `detect_gap`, `scale_for_lean`, `rows_to_lean_csv`, `write_lean_zip`) mirror `train.py::ensure_derived_crypto_daily_series()`'s exact Lean zip write pattern (`ZipFile(path, "w")`, member name `f"{ticker.lower()}.csv"`, row format `f"{date:%Y%m%d} 00:00,{o},{h},{l},{c},{v}"`), with one addition: `scale_for_lean()` applies the x10000 integer convention for equities (Yahoo returns real dollar floats), crypto stays unscaled
- `fetch_yahoo_ohlcv()` is the only function that imports `yfinance`, deferred inside the function (mirroring `experience/redis_queue.py`'s deferred `import redis`) — importing `data_pipeline` never requires `yfinance`
- Two independent safety limits, both with an explicit manual step: (1) writing/merging zip files only with `--apply` (default: dry run, report only); (2) `config.json`'s `available_from`/`available_to` are **never** changed automatically, even with `--apply` — `train.py::build_asset_quality()` only counts rows inside the configured windows, so the script only prints the suggested new values to the console
- `write_lean_zip()`'s merge always lets existing real Lean rows win on overlapping dates; Yahoo data only fills genuine gaps
- `yfinance` is a pure dev dependency (`requirements/requirements-dev.txt`), never in `requirements.txt`/`requirements-runtime.txt`
- Adds `tests/test_yfinance_backfill.py` with 20 tests (all using an injected `fetch_fn` stub — `yfinance` is never imported anywhere in the test file)
- Stopping point: no automatic follow-up of `available_from`/`available_to`, no Docker worker — deliberately a manual offline script, same status as `train_topology.py`

## Phase V2-23.1 Result

Data-Driven Liquidity Threshold Calibration — closed, but differently than originally planned:

- The original plan was to calibrate `spread_proxy` from real historical fill/slippage data once the experience pipeline (V2-13/14) had accumulated enough history. A deeper look during this session found that this premise had no data to stand on — Lean backtests never set a `SlippageModel` (only an `InteractiveBrokersFeeModel`, which is a transaction fee, not price-impact slippage), and `experience/simulated_portfolio.py`'s `enter_long()` always calls `execution.order_gate.simulate_fill(...)` with the default `slippage_bps=0.0` — so no realized spread/slippage observation had ever been logged anywhere to calibrate from
- Instead of building new fill-telemetry infrastructure as a prerequisite, the **Corwin & Schultz (2012) high-low spread estimator** was implemented instead: a published, closed-form formula that estimates the bid-ask spread purely from consecutive daily high/low ranges — data already collected every bar in `main.py::self.symbol_windows`
- `liquidity/market_liquidity.py::estimate_high_low_spread(highs, lows)` (pure, no I/O): computes an estimate per consecutive 2-bar window using the Corwin-Schultz formula (`beta`, `gamma`, `alpha`, then `spread = 2*(e^alpha-1)/(1+e^alpha)`), clips negative single-window estimates to `0.0` (a known, documented artifact of the method at low volatility, not a bug), and averages across all windows; returns `None` with fewer than 2 valid bars
- `build_liquidity_decision(...)` gets a new optional `dynamic_spread` parameter — replaces `TYPICAL_SPREAD_BY_TYPE.get(security_type, ...)` as the primary path; the static lookup table remains only as a fallback for the first bars of a run (`phase_v2.liquidity.spread_estimation.min_bars`, default 2) or if the estimator can't produce a valid value
- `main.py` reads `highs`/`lows` from `self.symbol_windows[symbol]` at the liquidity call site (already populated every bar, no new state management needed) and passes the result as `dynamic_spread`
- Extends `config.json phase_v2.liquidity.spread_estimation` (`enabled`, `min_bars`)
- Adds 10 new tests to `tests/test_market_liquidity.py`: an independently recomputed reference calculation, zero spread on flat prices, monotonicity (narrower range → smaller spread), averaging across multiple windows, `None` with too few/inconsistent bars, skipping invalid windows, and `dynamic_spread` override/fallback behavior in `build_liquidity_decision`
- Stopping point: no fallback to real fill-data calibration — that would first require introducing a `SlippageModel`/real fill telemetry, which is deliberately out of scope for this phase

## Phase V2-23.2 Result

Static config wiring + a dead `average_correlation` feature (supplementary, found during a static-vs-dynamic architecture audit this session):

- `config.json` gets three previously missing `phase_v2` blocks (`dynamic_risk`, `regime_detection`, `gating_network`) that `main.py` has already been reading since V2-3/V2-6/V2-9 (`self.phase_v2.get("dynamic_risk", {})` etc.) — without these blocks, every single value (target volatility, regime thresholds, gating baseline weight) silently and permanently fell back to the Python-hardcoded default, without ever actually being configurable. Purely additive: the new values match the previous defaults exactly, no behavior change
- `regime/market_regime.py::build_market_regime_vector()`'s `average_correlation` parameter has existed since V2-6, but was never fed a real value — `main.py` always called `_build_regime_payload()` without this parameter, so the correlation-driven risk_off branch in `classify_risk_regime()` was practically unreachable. Fix: `main.py::_build_regime_payload()` gets a new `average_correlation` parameter, filled at the call site with `topology_payload["correlation_strength"]` — the mean peer correlation within its own cluster, already computed per asset by `topology/market_topology.py`, available because `_build_topology_payload()` already runs once per bar before the per-asset loop. No change needed in `regime/market_regime.py` or `topology/market_topology.py` themselves — purely `main.py` wiring of an already-real value into an already-real parameter
- Adds 1 new test to `tests/test_market_regime.py`: confirms `average_correlation` is passed through and actually affects `risk_score`/`reasons`
- Stopping point: `main.py` deliberately still has no unit tests of its own (importing it requires `AlgorithmImports`/Lean) — the wiring is tested up to the `main.py` boundary, not end-to-end in Lean

## Phase V2-23.3 Result

Real topology embedding (supplementary, same audit):

- `topology/market_topology.py`'s previous 3D coordinate placement was purely cosmetic: cluster centroids were placed via `index -> angle` on a fixed ellipse, and members within a cluster likewise via `member_index -> angle` — only the radius was data-driven (market distance), never the direction. Two strongly correlated clusters could end up on opposite sides of the scene
- Replaced with `_stress_majorize_2d(...)`: SMACOF (Scaling by MAjorizing a COmplicated Function), an iterative stress-majorization algorithm (the classical Guttman transform) that runs over the full pairwise correlation-distance matrix of all eligible symbols (not just within a cluster) — spatial position now actually reflects correlation distance, not just cluster membership
- SMACOF was deliberately chosen over classical MDS: no eigendecomposition needed (just a weighted position average per iteration), so it stays pure Python with no numpy/scipy — the same reasoning that already keeps `topology/learned_topology.py` numpy-free
- Deterministically seeded from the previous cosmetic layout (not randomly) — `test_stable_coordinates_are_deterministic` keeps passing unchanged
- `_rescale_positions_to_bounds(...)` scales the result isometrically (a single scale factor, not independent per-axis stretching, which would distort the very distances being preserved) back into the existing `NEUTRAL_DIMENSIONS` `[0,100]x[0,100]` bounds — `webui/src/components/topology/TopologyScene3D.tsx` needed no change, since it already normalizes via `topology.dimensions`
- The z-axis (volatility encoding) stays unchanged — deliberately a separate, meaningful encoding, not part of the spatial embedding
- `build_market_topology(...)` gets a new `embedding_iterations` parameter (default 100), `config.json phase_v2.topology.embedding_iterations` added, `main.py` passes it through
- Adds 3 new tests to `tests/test_market_topology.py`: correlated assets are now spatially closer than uncorrelated ones (a stronger claim than the previous pure cluster-ID comparison), coordinates stay within bounds, `embedding_iterations` actually affects the layout (not an ignored config value)
- Stopping point: no 3D embedding (z stays a volatility encoding, not part of distance preservation) — deliberate, since z already carries an established, separate meaning

## Test Suite

313 → 378 tests total after this audit-driven pass (14 new: 10 liquidity, 1 regime, 3 topology). `tests/README.md` updated.

## Phase V2-20 Result

Lean Backtesting Integration additionally does the following:

- Answers the open question of whether a normal `lean backtest .` run already
  exercises the entire ML system (baseline model, all 4 experts, MoE gating,
  regime, topology) with **yes** — by tracing `main.py::on_data`:
  `_run_model` (baseline model), `_run_expert_models` (all 4 experts through
  the same `_run_exported_model` interpreter), `build_gating_decision`
  (MoE gating), `_build_topology_payload` (deterministic + learned
  topology, once per bar before the symbol loop), and
  `build_market_regime_vector` (regime) all run unchanged since
  V2-9/V2-11/V2-12 per bar and per symbol — V2-20 therefore didn't rebuild
  any runtime logic, it proved the existing coverage
- Adds `tests/test_lean_backtest_ml_coverage.py`: a real
  integration test that runs `lean backtest .` via subprocess and then
  checks `visualization/state.json` to confirm that at least one fully
  evaluated signal shows all 4 expert names in `expert_probabilities`, 4
  weighted entries in `moe_gating.weights`, a populated
  `regime.trend_regime`, and a populated `liquidity.liquidity_risk`,
  and that `state["topology"]["nodes"]` isn't empty — closing the
  gap documented in `development/Problems.md` #8, that `main.py` had no
  tests of its own until now
- The new test adopts `retraining/lean_backtest.py`'s convention
  (optional dependency, skip instead of fail if the Lean CLI is missing), but
  adds a safeguard: on machines with `elan` installed (Lean 4, the
  theorem prover), a bare `lean` on `PATH` points to the **wrong**
  program (a name collision); `_find_quantconnect_lean_binary()` checks the
  `--version` output and prefers the project's own `.venv/Scripts/lean.exe`,
  so the test is cleanly skipped instead of failing with a confusing error
  message
- Adds the new webui page `/neural-network` (nav entry between
  Topology and Tracing): an interactive 3D view of all 5 actually trained
  neural networks (baseline model + 4 experts) side by side in a
  shared camera/orbit scene, plus a live-updated statistics box
  (layer/node/edge count per network, quality status, last change) — see
  the Neural Network Visualization Contract (V2-20) in `v2_architecture.md` for
  the full data schema and the deliberately excluded non-networks
  (MoE gating, learned topology prototypes)
- New backend module `monitoring/neural_network_state.py`
  (`build_neural_network_state()`, pure function) and a new route
  `GET /api/neural-network`, both following the same read-only reshape pattern
  as `/api/topology`

## Phase V2-21 Result

Paper Trading Preparation — closes the gap where `broker_config_present`
was previously a no-op (`bool(self.paper_brokerage)`, a string that is
never empty by default), without setting up a real IBKR paper account:

- New, pure module `execution/paper_readiness.py`: `evaluate_paper_broker_config()`
  requires three confirmations (`brokerage` set, `live_data_provider_configured`,
  `manual_review_confirmed` — the latter replaces the old dead
  `phase6.paper_trading.ready_for_live_paper` stub), and
  `evaluate_observation_readiness()` translates 4 of the 5 items from
  `development/infrastructure.md`'s "Ready for Paper Trading?" checklist into
  code (minimum observation count, `simulated_sharpe` floor,
  `simulated_max_drawdown` floor, no dominant `rejected_by_reason`)
  — the 5th item (manual review of trade history) deliberately remains a
  human decision
- The target architecture is Lean's built-in `PaperBrokerage` (`lean.json`'s already
  existing `live-paper` environment, no real broker credentials
  needed) instead of a real IBKR paper account — a user decision for this
  phase
- `execution/paper_readiness_io.py` (IO): `read_paper_trading_config()` reads
  `phase_v2.paper_trading` fresh from disk (same pattern as
  `risk/manual_override.py`); `fetch_observation_mode_events()` is the first
  `mode='observation'`-filtered experience-events query (the existing
  `fetch_recent_events()`/`fetch_events_since()` don't filter by `mode`)
- New offline report module `execution/paper_readiness_report.py`
  (`build_paper_readiness_view()`, the same pattern as
  `retraining/status_export.py`): writes
  `visualization/grafana/paper_readiness_report.json`; new CLI command
  `aq paper-readiness` (`aq_cli.py`) as a human-triggered gate before
  switching `phase_v2.runtime.mode` to `"paper"`
- `main.py`: `phase6.paper_trading` removed entirely (`self.paper_brokerage`/
  `self.ready_for_live_paper` were only a no-op); new
  `self.phase_v2_paper_trading`, a new `_recompute_broker_config()` method
  (called once in `initialize()` and once per session rollover in
  `_refresh_risk_state()`, the same "fresh from disk, no restart
  needed" principle as the manual trade-lock override), `_order_permission()`
  now reads `self._broker_config_present` instead of the old no-op check
- `monitoring/api_server.py`: `paper_readiness_report.json` is served both in
  `/api/state` (under `state["paper_readiness"]`, same pattern as
  `retraining_status`) and as its own route,
  `GET /api/grafana/paper-readiness`
- New webui panel `PaperReadinessPanel.tsx` (same structure as
  `RetrainingStatusPanel.tsx`), placed next to the Retraining Status
  panel in `Overview.tsx`; new `PaperReadiness` type in `types/state.ts`
- New Docker Compose service `lean-live` (profile `lean-live`, never part of
  `--all`/`--lean`): keeps `lean live deploy . --environment
  ${LEAN_LIVE_ENVIRONMENT:-live-paper}` running continuously (`restart:
  unless-stopped`), unlike the existing `lean` service, which only
  provides `sleep infinity` for ad-hoc `lean backtest .` runs
- `config.json` gets `phase_v2.paper_trading` (default: everything blocking,
  `live_data_provider_configured`/`manual_review_confirmed` both `false`)
- New tests: `tests/test_paper_readiness.py`, `tests/test_paper_readiness_io.py`,
  `tests/test_paper_readiness_report.py`, plus `test_paper_readiness_wraps_the_report_module`
  in `tests/test_aq_cli.py`
- Stopping point: no real broker/real live market data configured or tested
  in this session — `lean live deploy`'s exact CLI flags aren't
  verified against an installed Lean CLI; the runbook in
  `development/infrastructure.md` explicitly points out to check
  `lean live deploy --help` before production use

## Phase V2-22 Result

Live Deployment Structure — purely structural: turns the later switch from
paper to real live trading into a config/credential change, not a code
rewrite. No real broker credentials or live trades configured or tested
in this phase.

- New credential handling: `.env.live.example` (new `.gitignore` exception
  `!.env.live.example`, analogous to `.env.compose.example`), pure
  `execution/live_credentials.py` (`credentials_present()`,
  `describe_missing_fields()`), and IO module
  `execution/live_credentials_io.py::load_live_credentials()` — tries
  `ib_config.py` first (repo root, gitignored, previously only planned), then
  falls back to `AETHER_IB_*` environment variables. Pure preflight
  validation — doesn't wire up Lean itself; Lean still reads `ib-account`/
  `ib-user-name`/`ib-password` directly from `lean.json`, which remains
  a manual step (see the new runbook below)
- `execution/paper_readiness.py` gets `evaluate_live_broker_config()`
  (requires real credentials in addition to a passed paper check) and
  `evaluate_live_risk_posture()` (a safety ceiling: `max_daily_drawdown_pct`/
  `max_total_drawdown_pct` must not exceed `phase_v2.live.max_allowed_*_drawdown_pct`,
  `liquidate_on_risk_breach` must be `true`) — the same decision table as
  for `paper`, just with additional conditions, thus evidence that the
  paper→live switch is genuinely just a configuration question
- `main.py`: `self._live_credentials` is loaded once in `initialize()`
  (environment variables/`ib_config.py` don't change during a run, unlike
  `config.json`); `_recompute_broker_config()` passes
  `credentials_present(...)` and the current risk/live config state through to
  `evaluate_broker_config()`
- `config.json` gets `phase_v2.live` (`max_allowed_daily_drawdown_pct: 0.05`,
  `max_allowed_total_drawdown_pct: 0.15`)
- Auto-promote safety net: new, tiny IO module
  `execution/runtime_config_io.py::read_runtime_mode()` (same pattern as
  `risk/manual_override.py`); `retraining/worker.py::run_once()` forces
  manual promotion (`auto_promote` set to `False` for this cycle, with a
  warning log) whenever `phase_v2.runtime.mode == "live"` AND
  `phase_v2.retraining.worker.auto_promote_blocked_in_live_mode` (default
  `true`) — full autonomy is fine as long as no real live trading exists yet,
  but a model change should never go live unsupervised once real orders are
  possible
- New trigger `live_order_permission_blocked_trigger` in
  `performance/triggers.py`: fires `critical` when `mode == "live"` but
  recent `execution_note`s are still `simulated_*` (the order gate is
  silently blocking what should be a real order — a sign of
  misconfigured credentials/flag/risk lock). Deliberately **not**
  retrain-eligible (`_NON_RETRAIN_TRIGGERS`) — a new model doesn't fix a
  broker misconfiguration; `notifications/telegram_alerts.py` needed no
  change, since it already formats triggers generically
- New tests: `tests/test_live_credentials.py`, `tests/test_live_credentials_io.py`,
  `tests/test_runtime_config_io.py`, plus extensions to
  `tests/test_retraining_worker.py` and `tests/test_triggers.py`
- Stopping point: no new generic "watch-a-directory-and-auto-commit"
  feature built — the existing `retraining/worker.py` loop plus the
  Aether-Vault commit (`retraining/vault_client.py`) already covers that;
  here only `phase_v2.retraining.worker.auto_promote` was set to `true`
  (see the separate section in `development/v2_architecture.md`'s Controlled
  Retraining Contract)

## Latency Optimization + Docker Image Consolidation

Starting point: a static complexity analysis of `main.py`'s per-bar hot path
found three real bugs (not just slow code, but behavior that scales worse
than linearly with the backtest timespan) plus two real CPU bottlenecks (a
pure-Python neural-net forward pass, run 5x per symbol per bar, and a
pure-Python O(N²×100-iteration) topology embedding, run once per bar). In
parallel: consolidating Docker images from 5 to 3 as groundwork for a
later, latency-optimized system variant — **this does not make this
system HFT** (that would require a completely different data/execution
architecture), it only makes the existing daily-bar system faster and the
Docker layout cleaner.

**Three bug fixes (Problems.md #11-#13):**

- `main.py::_write_state()`'s throttle guard was effectively useless due to
  an unreachable comparison (`signals is None`, but `on_data()` always
  passes `signals` as a dict) — all 7 state files were fully rewritten
  every single bar instead of once per timestamp
- `experience/simulated_portfolio.py::mark_to_market()` was called once
  per symbol per bar instead of once per bar with all symbol prices —
  `equity_curve` therefore had `N·bars` instead of `bars` entries; combined
  with a full CSV rebuild on every write, that added up to
  `O((bars·symbols)²)` work for `observation_equity_curve.csv`. Fix:
  `on_data()` now collects `close_prices_by_symbol` during the
  symbol loop and calls `mark_to_market(...)` once afterward; the new
  `main.py::_flush_observation_equity_csv()` only appends the rows new
  since the last flush (writing the header once, on the first flush)
- New `execution/config_cache.py::read_cached()`: mtime-cached reads
  for `risk/manual_override.py`, `execution/paper_readiness_io.py`,
  `execution/runtime_config_io.py` (all three read `config.json` far more
  often than the file actually changes). **A real bug was found here only
  through the real `lean backtest .` integration test, not through
  unit tests:** the first version cached only by file path, not by
  path+loader — since several readers (`manual_trade_lock_override`,
  `paper_trading_config`, ...) read the same `config.json` within the same
  bar, the second reader's call incorrectly overwrote the first one's
  cache entry, causing `main.py::_recompute_broker_config()` to crash with
  `None` instead of a dict. Fixed via the cache key `(config_path, loader)`.

**Deliberately left open:** skipping `experience/redis_queue.py::push()`
in backtest mode would be trivial, but would contradict
`development/v2_architecture.md`'s documented Redis experience queue
behavior, without a suspected downstream dependency being either
confirmed or ruled out (see Problems.md #14, `open`).

**Docker consolidation (5 → 3 custom images):** `experience-worker`,
`performance-trigger-worker`, and `telegram-worker` now share one
image (`Dockerfile.workers` + `requirements/requirements-workers.txt`,
a union of the previous three requirements files) instead of each having
its own Dockerfile/requirements pair. Verified via `docker compose build`/`up`
and a clean startup of all three containers. The `aether-quant` and
`retraining-worker` images are unchanged.

**NN inference extracted and vectorized:** `_run_exported_model`/
`_linear`/`_layernorm`/`_sigmoid` were private `main.py` methods, pure
Python, called 5x per symbol per bar (baseline + 4 experts) — despite
`numpy` having long been a declared dependency that nothing in `main.py`'s
import chain had ever actually imported. First extracted behavior-
identically into `inference/exported_model.py` (free functions, the
same pattern as `risk/position_sizing.py`), then vectorized there with
`numpy`. Safety net: `tests/test_exported_model.py` (hand-computed
values plus a reference forward pass).

**Topology vectorized + warm start (Problems.md style, `v2_architecture.md`
has the details):** `topology/market_topology.py::_stress_majorize_2d()`
(the SMACOF embedding, the dominant cost factor of the topology layer) is
now vectorized with `numpy`, with the same inputs/outputs/iteration
count/seeding as the pure-Python version (parity test in
`tests/test_market_topology.py`). The pairwise correlation loop deliberately
stays pure Python (symbols don't share a uniform window length in
practice — staggered onboarding, thin markets like ETHUSD/LTCUSD);
`topology/learned_topology.py`'s smaller `O(N²×5)` portion stays
unvectorized for the same reason, and is negligible next to SMACOF anyway
at only 10 assets in the universe.

**Behavior-changing, not just speed:** `build_market_topology()` now
accepts `previous_positions` — for known symbols, SMACOF starts from the
prior bar's result instead of the cosmetic angle seed, combined with a
new `convergence_tolerance` parameter for early iteration exit once
points barely move anymore (this is what actually saves time — a
warm start alone gains nothing if all 100 iterations still always run).
New config keys `phase_v2.topology.warm_start_enabled` (default
`true`) and `phase_v2.topology.convergence_tolerance` (default `0.01`).
**This changes the topology coordinate values bar by bar** — historical
backtest results and already-promoted models trained/validated against the
old, always-freshly-seeded behavior no longer reproduce bit-for-bit
afterward. `warm_start_enabled: false` reproduces the old (vectorized, but
cold-seeded) behavior exactly — a genuine, redeploy-free rollback switch,
not just a default.

New tests: `tests/test_config_cache.py`,
`tests/test_exported_model.py`, plus extensions to
`tests/test_simulated_portfolio.py`, `tests/test_manual_override.py`,
`tests/test_paper_readiness_io.py`, `tests/test_runtime_config_io.py`,
`tests/test_market_topology.py`.

## 20-Asset Universe Expansion + Genuine Held-Out Backtest Window

V2's second-to-last phase: growing the trading universe from 10 to 20
assets, backed entirely by real (not synthetic) historical data, and
restructuring the train/validation/backtest split so the backtest is
finally a genuine, out-of-sample period instead of re-running over the
full training history. Purely a `config.json` change plus one real bug
fix surfaced along the way — confirmed no source file anywhere hardcodes
the 10-asset universe (`train.py`, `data_pipeline/`, `moe/`, `topology/`
all iterate `config["phase1"]["universe"]["assets"]` generically).

- **8 new equities at zero backfill cost:** `AIG`, `BNO`, `FB`, `GOOG`,
  `GOOGL`, `USO`, `WM`, `AAA` — all already had real Lean daily data on
  disk through `2021-03-31` (QuantConnect's free sample data), completely
  unused by the previous config. `available_from` set per-ticker from each
  zip's actual first row, not assumed uniform.
- **2 new crypto assets from scratch:** `XRPUSD`, `ADAUSD`, added via
  `data_pipeline/yfinance_backfill.py --apply` with no existing zip —
  confirmed the script's `write_lean_zip()` already supports this (creates
  a fresh zip when the target path doesn't exist). A dry run first
  (`--tickers ... `, no `--apply`) revealed Yahoo's real earliest daily
  history for both starts `2017-11-09`, not the originally guessed
  `2017-08-01`/`2017-10-01` — `available_from`/`backfill_from` set from
  the dry run's actual report, per the script's own safety contract.
- **`BTCUSD`/`ETHUSD`/`LTCUSD` extended forward to `2021-03-31`:** `BTCUSD`
  gained a new `backfill` block (`backfill_from: 2018-08-14`, its real
  local data's last day); `ETHUSD`/`LTCUSD`'s existing `backfill_to` bumped
  forward from their old, narrower ranges. yfinance's `end` parameter is
  exclusive, so `backfill_to` was set to `2021-04-01` (not `2021-03-31`)
  to actually capture the `2021-03-31` trading day — confirmed by
  inspecting the written zips' last row before/after.
- **Genuine held-out backtest window:** `common_window` end moved
  `2018-08-13` → `2021-03-31`. `phase1.windows` restructured — training
  `2014-12-01`→`2017-12-31`, validation `2018-01-01`→`2018-03-31`,
  backtest `2018-04-01`→`2021-03-31` (~3 years). Previously `backtest`
  was identical to the full `common_window` — the Lean backtest re-ran
  over the entire training history, not a held-out period at all. This is
  the same universe of assets and same feature/target definitions, just a
  split that now actually tests generalization.
- **Real bug found and fixed (Problems.md #15):**
  `train.py::ensure_derived_crypto_daily_series()` unconditionally
  overwrote `ETHUSD`/`LTCUSD`'s daily zip from minute-trade data alone on
  every `train.py` run, silently discarding any yfinance-backfilled rows
  sitting in the same zip — the backfill script's own write survived on
  disk only until the next training run. Fixed to merge by date instead of
  clobber (minute-derived rows win on their dates, backfilled rows for
  every other date survive). New regression test:
  `tests/test_train_pipeline.py::test_ensure_derived_crypto_daily_series_merges_with_existing_backfill`.
- **Dataset manifest result:** 16/20 assets landed
  `training_eligible`/`trading_eligible`; `AAA`, `ETHUSD`, `XRPUSD`,
  `ADAUSD` stayed `observation_only` (Phase 9's `asset_quality` gate,
  unchanged thresholds) — all four for genuine reasons, not a bug:
  `ETHUSD`/`XRPUSD`/`ADAUSD`'s real history barely overlaps the
  `2014-2017` training window (~52-54 post-feature-engineering training
  rows, under `min_training_rows: 100`); `AAA`'s own real Lean data is
  sparse before `2020-09-09`. `LTCUSD` (real data back to `2016-01-01`)
  did land `training_eligible` once the merge-clobber bug above was fixed.
- Trained the baseline model + all 4 experts over the new 20-asset,
  2018-2021-held-out dataset with zero further code changes —
  `experts/expert_datasets.py`'s regime-slicing scaled with the asset
  count as expected.
- `tests/test_lean_backtest_ml_coverage.py::LEAN_BACKTEST_TIMEOUT_SECONDS`
  bumped `7200` → `14400`: the new backtest window roughly doubles the
  asset count against a similar-length window, so this integration test's
  real Lean CLI runtime is expected to roughly double too.
- README: new "Universe Size" section listing all 20 tickers with role
  (trading vs. observation-only) and a Mermaid hub-and-spoke diagram (the
  baseline DNN + MoE experts as the central node, all 20 tickers as
  spokes, color-coded by trading eligibility).
- **`development/logo.png` fixed:** stripped a ~4px stray opaque border
  artifact around the full perimeter (an export leftover; the rest of the
  canvas was already transparent) and re-composited the mark onto a
  rounded dark card (`#1A1A1A`, matching the README badges' `labelColor`)
  instead of a hard-edged square, so it reads correctly in both GitHub
  light and dark themes instead of looking like a black box in light mode.
- **Real bug found and fixed (Problems.md #16), discovered only by
  actually running `lean backtest .` against the new universe — no unit
  test could catch this, `main.py` has none:** `main.py::initialize()`
  now exceeded Lean's hardcoded 90-second isolator timeout on algorithm
  creation (`AlgorithmFactory.Loader.TryCreateAlgorithmInstanceWithIsolator`,
  not configurable via `lean.json`). The `add_equity`/`add_crypto`
  subscription loop — confirmed via direct disk-log instrumentation to be
  fast (20 assets in 1.8s) — wasn't the problem; loading every
  model/expert/topology artifact and deriving ~40 config values inside
  `initialize()` was. Fixed by splitting `initialize()` into the minimal
  Lean-critical path (config load, dates/cash, the subscription loop,
  warm-up) plus a new `_ensure_ready()` carrying everything else, deferred
  to run once on the first `on_data()` call (no isolator limit there).
  Confirmed fixed against real 20-asset data: `initialize()` alone now
  takes 1.85s, and the full isolator-timed window (import + instantiate +
  `initialize()`) totals ~51s, safely under the 90s cap.
- Stopping point: the real, full `lean backtest .` run over the new
  universe/window (the multi-hour, 3-year, 20-asset run) was deliberately
  left for manual, out-of-band execution rather than run to completion by
  an agent — see the Runbook for the exact commands. Diagnostic Lean runs
  (stopped early, right after confirming `initialize()` no longer times
  out) were used to find and fix Problems.md #16 above. This phase does
  not touch Docker images or the controlled retraining loop.
- **Follow-up fix (Problems.md #17):** those same diagnostic Lean runs kept
  hitting the 90-second isolator cap intermittently even after `initialize()`
  was fixed — root cause was Lean's own `AlgorithmImports` bridge pulling in
  `matplotlib`, whose font cache never survives Lean CLI's ephemeral
  per-backtest Docker container, so it rebuilt from scratch (20-40+ seconds)
  on every single run. Fixed by pointing `MPLCONFIGDIR` at a `.matplotlib_cache/`
  directory inside the mounted project folder (persists across containers);
  confirmed via two consecutive runs that the second no longer rebuilds it.

## `aq fetch` — ad-hoc Yahoo Finance ticker fetch

A new `aq fetch <crypto|stock> --ticker <TICKER> --start <YYYY-MM-DD> --end
<YYYY-MM-DD> [--apply]` command, requested directly by the user to remove
the multi-step manual process the 20-asset expansion above required for
onboarding a new crypto ticker (run `yfinance_backfill.py`, inspect its
output, hand-edit `config.json`). One command now fetches from Yahoo
Finance, formats into Lean's zip/CSV convention, writes it to the correct
`data/` path, and — on `--apply` — appends a new asset block straight into
`config.json`'s `phase1.universe.assets[]`. Deliberately does **not** run
`train.py` itself; training stays a separate, deliberate step.

- New `data_pipeline/fetch.py`: reuses `yfinance_backfill.py`'s
  config.json-independent pure functions (`fetch_yahoo_ohlcv`,
  `scale_for_lean`, `write_lean_zip`) unchanged — no duplicated logic.
  `ASSET_CLASS_CONFIG` dict drives the Lean path/market convention per
  asset class (`crypto` → `data/crypto/coinbase/daily/<ticker>_trade.zip`;
  `stock` → `data/equity/usa/daily/<ticker>.zip`) — adding a `derivative`
  class in V3 is one new dict entry, not a redesign.
- **Deliberate policy difference from `yfinance_backfill.py`:** that script
  never touches `config.json` (its rule exists to stop it from silently
  widening an *existing* asset's date range without a human decision).
  `fetch.py` *does* write `config.json` on `--apply`, because adding a
  brand-new ticker to the universe on purpose is its entire reason to
  exist, not an accidental side effect. If the ticker already has a
  `config.json` entry, `fetch.py` leaves it alone and points at
  `yfinance_backfill.py` instead — scope stays "add a new ticker," not
  "extend an existing one." See `data_pipeline/README.md`'s new section
  for the full comparison table.
- `aq_cli.py`: new `cmd_fetch`, wired as the second in-process exception
  alongside `trade-lock` (no subprocess) — calls `data_pipeline.fetch`
  directly. New `_iso_date` argparse validator rejects non-ISO dates (e.g.
  `02.02.2017`) with a clear error instead of a confusing downstream
  yfinance failure.
- **Required packaging fix:** `pyproject.toml`'s `packages` list gained
  `"data_pipeline"` (→ `["risk", "execution", "data_pipeline"]`) — the same
  class of `ModuleNotFoundError` bug this list's own comment already
  documents from `execution` being added previously. Verified via the
  *installed* `aq fetch --help` (not `python aq_cli.py`), which is the only
  way this specific regression class is actually caught.
- New tests: `tests/test_fetch.py` (13 tests, mirrors
  `tests/test_yfinance_backfill.py`'s style — `fetch_fn` injected via
  keyword default, never real yfinance) plus 7 wiring tests in
  `tests/test_aq_cli.py`.
- Manually verified end-to-end with real yfinance calls (`DOGEUSD`,
  `MSFT`): dry run writes nothing; `--apply` writes a correctly-scaled zip
  and adds a config.json block; re-running `--apply` on the same ticker
  reports `already_exists` without duplicating the entry; `derivative` is
  rejected by argparse (V3 not implemented yet). Test artifacts removed
  from `config.json`/`data/` after verification — not part of the real
  20-asset universe.

## Trade-frequency tuning — statistical/diagnostic backtest mode

A real 3-year, 20-asset backtest this session produced only 12 filled
trades: 5 entries, 1 opportunistic exit, then a 5-symbol mass liquidation
on 2020-03-23 that froze the algorithm for the remaining 374 days of the
window. Two parallel research passes tracing the full per-bar decision
pipeline found the suppression compounds across several independent gates,
plus two structural traps where a gate that fires once effectively never
clears for the rest of a run — the portfolio sits flat in cash and its own
drawdown-from-peak calculation can never recover without trading.

- **New opt-in flag, `phase_v2.backtest.bypass_safety_gates`** (default
  `false`) — deliberately a standalone key, not a repurposing of
  `aq trade-lock`'s existing `--on`/`--off`/`--auto` override (which keeps
  its separately-documented meaning completely unchanged in every runtime
  mode). New pure helper
  `risk_controls.py::is_backtest_safety_bypass_active(runtime_mode, bypass_flag)`
  returns `True` only when `runtime_mode == "backtest"` **and** the flag is
  explicitly `true` — any non-backtest mode always returns `False`
  regardless of the flag, so live/paper safety behavior is completely
  untouched by this change.
- **Bypasses the sticky total-drawdown lock** (`main.py::_refresh_risk_state()`,
  the `trade_lock_reason != "total_drawdown_limit_breached"` exclusion) and
  **the regime detector's `risk_off` drawdown branch**
  (`main.py::_build_regime_payload()`, passes `float("inf")` instead of
  `regime_risk_off_drawdown_threshold` when the bypass is active) — the
  regime override was found to be an equally significant, earlier-firing
  (8% vs. the lock's 12%) version of the same structural trap, independent
  of the lock. Only these two specific mechanisms are affected; the
  bearish-trend+high-vol and composite risk-score branches of regime
  classification, and every liquidity/topology/cooldown/exposure gate,
  stay fully active either way.
- **Explicitly scoped to statistical/model-quality evaluation, not a
  live-representative equity curve** — in live/paper mode both gates are
  real, designed behavior that would have actually frozen trading on
  2020-03-23. This is a deliberate, accepted tradeoff for generating enough
  trade volume to get meaningful backtest metrics and exercise
  performance-trigger thresholds (`trade_count_interval=100`,
  `validation_gate.min_trade_count=30`) that never fire at ~12 trades —
  not a claim about deployable behavior.
- **Config-only threshold loosening** (confirmed test-safe: no existing
  test loads the real `config.json` for any of these keys):
  `phase6.risk.min_confidence_to_trade` 0.12→0.05,
  `phase5.backtest.buy_threshold_offset`/`sell_threshold_offset` 0.08→0.04
  each, `phase6.risk.trade_cooldown_bars` 3→1,
  `phase_v2.liquidity.thin_participation_threshold` 0.002→0.01,
  `phase_v2.liquidity.blocked_participation_threshold` 0.05→0.10,
  `phase9.portfolio.max_active_positions` 5→10,
  `phase9.portfolio.max_crypto_exposure` 0.25→0.35.
- **`phase9.asset_quality.min_training_rows` 100→50**: unlocked ETHUSD,
  XRPUSD, and ADAUSD as `training_eligible`/`trading_eligible` (they failed
  only this one threshold — 52-54 actual training rows, since these coins
  weren't listed on Yahoo until deep into the 2014-2017 training window;
  they already comfortably cleared `min_total_feature_rows` and
  `min_backtest_rows`) — confirmed via `train.py --dataset-only`: 19 of 20
  assets now `training_eligible`, only `AAA` remains observation-only.
  `AAA` was deliberately excluded from this fix — its usable data starts
  2020-09-09, entirely after both the training and validation windows end,
  so no threshold value can fix it; it would need real pre-2018 backfilled
  history that doesn't exist for whatever instrument `AAA` actually is.
- **Deliberately out of scope:** real short-selling (confirmed
  `phase5.backtest.strategy_mode` is read in exactly one place in the whole
  repo, `train.py`'s report-metadata code, and is never branched on —
  `main.py::_apply_signal`'s `sell` branch only ever calls `self.Liquidate()`,
  there is no code path anywhere that opens a short position; enabling real
  shorting would be a materially bigger, riskier change than everything
  above and isn't needed to raise trade count via long/flat cycling alone).
  Also left alone: the topology "elevated" volatility threshold
  (`topology/market_topology.py`'s `ELEVATED_VOLATILITY_THRESHOLD = 0.45`,
  hardcoded, not in `config.json`) — a smaller contributor than the two
  structural traps, left as a secondary lever for later if needed.
- New tests: `tests/test_risk_controls.py` (4 new cases for
  `is_backtest_safety_bypass_active`).
- Stopping point: the real Lean backtest with `bypass_safety_gates: true`
  to confirm the actual resulting trade count against the ~200 target was
  left for the user to run manually, per this session's established
  preference — the exact starting-point threshold values above may need
  one iteration based on that real count.

## Real learned gating weights + learned topology wired into position sizing

Closes two gaps this project's own V3 completeness assessment had flagged
as deferred, not rejected: `moe/gating.py`'s gating network was still
hand-tuned arithmetic dressed as a decision layer, and the learned
probabilistic topology overlay (V2-17.5) computed real per-symbol
confidence/uncertainty every bar but never reached an actual trade
decision — only the dashboard and the offline retrain-trigger pipeline.

**Learned topology → position sizing** (`risk/position_sizing.py`): new
pure function `topology_sizing_multiplier(topology_source,
topology_confidence, topology_disagreement, min_topology_multiplier=0.5,
max_topology_multiplier=1.0)` — a strict no-op (`1.0`) unless
`topology_source == "learned"`, otherwise a bounded, continuous,
**shrink-only** multiplier (`min + (max-min) * confidence * (1-disagreement)`,
never above `1.0`). Composes into the existing `volatility_multiplier ×
confidence_multiplier` chain in `build_dynamic_position_sizing()` as a
third factor — this changes only *how large* an already-approved trade is,
never *whether* it happens, so it never touches the analyzer's
`trade`/`simulate`/`observe`/`reduce_risk` decision itself (see
`analyzer/README.md`'s documented reason that path stays deterministic).
Wired through `main.py::_build_dynamic_sizing_payload()`. New config keys:
`phase_v2.dynamic_risk.topology_sizing_enabled` (default `true`),
`min_topology_multiplier` (`0.5`), `max_topology_multiplier` (`1.0`).

**Real learned gating weights** (`moe/gating.py`): additive, optional,
always-falls-back — the existing hand-written
quality-multiplier×performance-score×regime-alignment blend is still
computed first and unchanged; a trained model, if present, only
*overrides* the final probability. New `GATING_MODEL_FEATURE_KEYS`
(26-dim: each expert's probability/quality/performance/regime-alignment ×4,
baseline probability, one-hot trend/volatility/risk regime — already
bounded `[0,1]`/one-hot, so no scaler needed) and
`build_gating_model_features()`. `build_gating_decision()` gains optional
`gating_model`/`gating_feature_schema` params; on success `decision_source`
becomes `"learned_gating"` (new value, confirmed inert everywhere else in
the repo); any failure/missing model silently falls back to the hardcoded
blend, mirroring `topology/learned_topology.py`'s per-node fallback
isolation. Wired via new `main.py::_load_gating_model()`, gated by
`phase_v2.gating_network.learned_model_enabled` (default `true`).

**New offline trainer, `train_gating.py`** (sibling of `train_topology.py`,
same never-runs-in-Lean, exits-0-not-1-on-insufficient-data contract).
Trains the blend on the dataset's `validation` split (avoids
stacking-circularity: `train` already fit baseline+experts, `validation`
is the right held-out-from-fitting size to become this model's *own*
training data) replayed through the exported baseline+expert models via
the existing `inference/exported_model.py::run_exported_model()`
interpreter — zero new inference code. Evaluates once, at the end, on the
`backtest` split (never touched by any fitting anywhere in the pipeline).
Model is a small `AetherNet(26 → [16] → 1)`, deliberately restricted to
`relu`/`layernorm` (never `gelu`/`silu`/`batchnorm1d`, which
`run_exported_model()` cannot interpret). Regime reconstruction uses
`portfolio_drawdown=0.0`/`average_correlation=0.0` (runtime-only state not
recoverable offline — an honest, documented simplification; the two most-
used regime keys, `trend_regime`/`volatility_regime`, are unaffected).
Smoke-tested end-to-end against the real dataset (1,304 validation rows,
16,184 backtest rows) — writes a valid, runtime-interpretable model in
~90s. New config block `phase_v2.retraining.gating_training`.

**Retraining pipeline wiring**: `retraining/artifacts.py` gained
`OPTIONAL_GATING_FILES` (3 files, same best-effort contract as
`OPTIONAL_TOPOLOGY_FILES` — never required, never blocks candidate
promotion) plus `check_gating_artifacts()`; `retraining/orchestrator.py`
gained `train_gating()` (mirrors `train_topology()` line-for-line) plus a
`train_gating` CLI subparser; `retraining/worker.py` calls it right after
`train_topology()` in `run_once()`. `config.json`'s
`promotion.active_artifact_files` extended with the 3 new files.

**New `aq train --gating-only` flag**: since `train_gating.py` always
writes to `ml/versions/<id>/` (the versioned-candidate convention every
trainer here uses), this generates a throwaway version-id, runs the
trainer, then copies the 3 resulting artifacts straight into active `ml/`
— the same manual promotion-simulation step already used to verify this
trainer, mirroring how `train.py --experts-only` already writes directly
to active paths without a promotion gate.

**Neural-network webui tab now shows the gating network too**
(`monitoring/neural_network_state.py`): it was previously in the page's
hardcoded `excluded` list with a "deterministic, no weight matrix" reason
that this change makes stale. Now reads `ml/gating_model.json` exactly
like the baseline/experts (same optional, degrades-to-`not_trained`
contract) and reports a `"learned"` quality-status badge once a model
exists. `webui/src/components/neuralnet/NeuralNetworkScene3D.tsx`'s
previously-hardcoded 5-network render order gained `'gating'` (violet),
since the 3D scene only ever drew networks named in that list regardless
of what the backend returned.

- New tests: `tests/test_position_sizing.py` (+7), `tests/test_gating_network.py`
  (+5), `tests/test_train_gating.py` (8, pure-function style mirroring
  `tests/test_train_topology.py`), `tests/test_retraining_artifacts.py`/
  `test_retraining_orchestrator.py`/`test_retraining_worker.py` (extended
  for the new gating stage), `tests/test_aq_cli.py` (+3 for
  `--gating-only`), `tests/test_neural_network_state.py` (+2 new, 2
  rewritten to match gating no longer being excluded). Full suite: 581
  passed.
- Docs: `development/Problems.md` #14 (Redis push in backtest mode) marked
  resolved — the project owner confirmed no downstream process reads
  backtest-mode experience events from Postgres, so the open question this
  entry tracked is answered; `experience/redis_queue.py::push()` itself is
  deliberately left unchanged, since performance was never the blocker.
- Stopping point: `python train_gating.py` / `aq train --gating-only` was
  smoke-tested against the real dataset but its resulting model was **not**
  installed into active `ml/` or promoted through the retraining pipeline —
  per this session's established preference, the user runs the real
  training/backtest themselves.

## `aq config`/`aq lean` full read/write CLI + `analyzer/market_analyzer.py` real composite scoring

**`aq config`/`aq lean` — full read/write access to `config.json`/`lean.json`
from the CLI**, replacing hand-editing either file. Both share one
generic dispatcher, `aq_cli.py::_dispatch_json_config_command()`, pointed
at `CONFIG_PATH`/`LEAN_JSON_PATH` respectively — genuinely universal, no
hardcoded key list: any key either file already has, or gains later, is
immediately reachable with zero code changes, since the dotted-path
walker/setter (`_get_config_value`/`_set_config_value`/`_iter_leaf_paths`)
operates on whatever JSON structure is actually on disk at call time.

- `aq config` (bare) pretty-prints the whole file; `aq config get
  <dotted.key>` prints one value (scalar, or a nested section as JSON);
  `aq config set <dotted.key> <value>` writes it; `aq config keys
  [<dotted.prefix>]` lists every leaf key path for discoverability in a
  file this deeply nested. `aq lean` is the identical tool for `lean.json`.
- **Deliberately unrestricted** — `set` can target list/dict paths too
  (e.g. `phase_v2.retraining.eligible_severities`), not just scalars; the
  value is parsed as JSON first (`true`/`123`/`0.5`/`["a","b"]`/`{...}`
  become their real types automatically), falling back to a plain string
  only when it isn't valid JSON on its own.
- **Safety via transparency, not restriction:** every `set` backs up the
  pre-write file to `<file>.json.bak` first (`config.json.bak`/
  `lean.json.bak`, both added to `.gitignore`) and always prints old → new
  so a mistake is immediately visible; a type change (e.g. bool → string)
  prints a warning to stderr but still writes the value — full access was
  the explicit requirement, not a safe subset with guardrails.
- Small fix found while wiring this in: `aq retrain`'s stage `choices`
  list had `train_topology` but not `train_gating`, even though
  `retraining/orchestrator.py`'s own CLI subparser for it already existed
  from the previous session's work — `aq retrain train_gating ...` was
  unreachable. Added.
- New tests: `tests/test_aq_cli.py` (+18: 12 for `aq config`'s full
  behavior matrix, 6 for `aq lean`'s wiring — the shared dispatch logic's
  edge cases are already covered by the `config` tests, so `lean`'s tests
  only confirm it's pointed at the right file/attribute).

**`analyzer/market_analyzer.py` gains real composite scoring (additive,
config-gated).** Previously pure if/elif routing — every priority tier
checked exactly one raw field in isolation against a fixed threshold, no
aggregation anywhere. New `compute_signal_quality_score(confidence,
regime_confidence, topology, liquidity)` computes a real bounded `[0,1]`
weighted composite (confidence 0.45, regime confidence 0.20, topology
peer-support 0.20 — penalized when `topology_risk` is
`isolated`/`elevated` — liquidity friction 0.15 — penalized by
`participation_rate`), mirroring `moe/gating.py`'s
`_quality_multiplier`/`_performance_score` style: real math over
already-available fields, not a trained model.

- `MarketAnalysisDecision` gains `signal_quality_score`/
  `signal_quality_breakdown` fields, **always** computed and populated on
  every decision regardless of any flag — visible in
  `visualization/state.json` immediately.
- Only changes routing when the new
  `phase_v2.market_analyzer.use_composite_signal_score` flag is explicitly
  `true` (default `false`) — in that case the composite score replaces raw
  `confidence` in the `trade` gate (priority 7) and the
  `simulate`-vs-`observe` split (priority 8) only. The hard safety-override
  tiers (trade-lock, `risk_off` regime, elevated topology, liquidity
  blocked — priorities 1-6) are **never** affected, regardless of the
  flag — same reasoning as the pre-existing topology-elevated/isolated
  rules staying deterministic.
- Default `false` means output is byte-identical to pre-this-change
  behavior everywhere the flag isn't explicitly turned on — confirmed by
  every one of the 21 pre-existing tests in `tests/test_market_analyzer.py`
  passing completely unchanged, with zero edits to any of them.
- New tests: `tests/test_market_analyzer.py` (+11: 7 pure-function tests
  for `compute_signal_quality_score()`, 1 confirming the score is always
  populated even with the flag off, 3 confirming the flag can both
  downgrade a `trade` to `simulate` and upgrade a `simulate` to `trade` —
  only when explicitly enabled, never by default).
- Docs: `analyzer/README.md` new section explaining the composite score
  and its config gate; `moe/gating.py`'s `_quality_multiplier`/
  `_performance_score` style is the explicit precedent cited, not a novel
  approach.

## Multi-task prediction (direction + magnitude + volatility) — Phase 1

**Context.** A root-cause investigation this session found every model in
the system — baseline and all 4 experts — sits at backtest MCC 0.02-0.07
(essentially noise) and Sharpe -0.758 on a real backtest, and that
`AetherNet` predicts only direction (`target_direction`, binary): no
magnitude, no volatility, so position sizing had no actual forecast to
work with and fell back to a backward-looking `rolling_volatility_20d`
average. This entry closes the "no magnitude/volatility prediction" half
of that gap. The other structural fact the investigation found —
`AetherNet` is a plain feedforward MLP with zero temporal structure — is
explicitly **not** addressed here; it is scoped as Phase 2 (a real
sequence encoder over `main.py`'s existing `self.symbol_windows`), not
implemented in this pass.

**New export schema + interpreter (foundation).** `train.py` gains
`export_multitask_architecture(model) -> dict`, a branching
`{"trunk": [...], "heads": {"direction": [...], "magnitude": [...],
"volatility": [...]}}` export alongside the existing flat
`export_architecture()` (refactored internally to share a new
`_export_sequential_layers()` helper — a behavior-preserving extraction,
`export_architecture()`'s own output is unchanged). `export_state_dict()`
needed no changes (already architecture-agnostic).
`inference/exported_model.py` gains `run_exported_multitask_model(model_export,
inputs) -> dict[str, float]` (runs the shared trunk once, then each head
independently) and a new `_softplus(x)` helper (numerically stable
`log1p(exp(-|x|)) + max(x, 0)`) guaranteeing the volatility head is always
`>= 0`. `run_exported_model()` itself is completely untouched — new
function alongside it, zero regression risk to its 5 existing call sites.

**New model + training loop.** `train.py` gains `AetherNetMultiTask`: a
shared trunk (identical shape to `AetherNet`'s hidden-layer stack) feeding
three small heads — `head_direction` (raw logit), `head_magnitude` (raw
regression) and `head_volatility` (`Softplus`). New engineered column
`target_volatility_next_day` in `engineer_features()` — next day's own
`high_low_range_pct` shifted back one row, a genuine one-day-ahead
realized-range label; NaN only on the same last-per-asset row
`target_return_1d` already is, so it never drops additional rows.
`compute_regression_metrics()` (MAE/RMSE/bias) is the magnitude/volatility
equivalent of `compute_binary_metrics()` — MCC/F1/precision-recall are
meaningless for a continuous target.

**`train_multitask.py`** (repo root, sibling of `train_gating.py`/
`train_topology.py`): reads the already-built active dataset
(`ml/datasets/full_dataset.csv`) and `feature_schema.json`'s
`model_input_names` directly — same input feature set as the baseline
model (scaled features + asset context); this pass does not change *what*
the input feature set is, only what the model predicts from it (regime/
liquidity/topology as genuine new input features, per the original plan,
is scoped out of this pass — see "Scope decisions" below). Loss is
`BCEWithLogitsLoss(direction) + magnitude_loss_weight * MSE(magnitude) +
volatility_loss_weight * MSE(volatility)` (both weights default `1.0`,
`phase_v2.retraining.multitask_training`); early stopping and
`find_optimal_threshold()` both operate on direction only. Writes
`ml/versions/<id>/multitask_model.json`/`multitask_feature_schema.json`/
`multitask_training_metrics.json`; exits 0 (not an error) when there isn't
enough train/validation/backtest data yet, matching every other trainer's
"skipped must never look like failed" contract.

**Smoke-tested end-to-end against the real dataset** (30,332 rows, 20
assets, `ml/datasets/full_dataset.csv` rebuilt via `python train.py
--dataset-only` to pick up the new `target_volatility_next_day` column
first): `python train_multitask.py --version-id <id>` completed and wrote
real artifacts (backtest direction MCC 0.0174 — in the same noisy range as
today's baseline/experts, magnitude MAE 0.0259, volatility MAE 0.0236).
**Interpreter parity independently verified**: `run_exported_multitask_model()`
against a from-scratch PyTorch forward pass loaded from the same exported
`state_dict` matched to ~1e-7 (float32 precision) on all three heads.

**Runtime integration (main.py, additive).** New optional artifact pair
`ml/multitask_model.json`/`ml/multitask_feature_schema.json`, loaded by
`_load_multitask_model()` (identical graceful-fallback contract to
`_load_gating_model()`/`_load_learned_topology_model()`: missing/malformed
→ `None`, never a hard failure), gated by
`phase_v2.multitask_model.enabled` (default `true`). `_run_multitask_model()`
calls it alongside (never replacing) `_run_model()`/`_run_expert_models()`.
`predicted_return_magnitude`/`predicted_volatility` are threaded into
`signal_payload`, `MarketAnalysisDecision` (2 new fields, always populated,
`None` when unavailable — informational only, never changes the analyzer's
`trade`/`simulate`/`observe`/`reduce_risk` categorization), the dashboard
asset heatmap, and the runtime asset CSV export (2 new columns).

**Position sizing can now use a real forecast (opt-in).**
`risk/position_sizing.py::build_dynamic_position_sizing()` gains
`predicted_volatility`/`use_predicted_volatility` params and a new
`_resolve_effective_volatility()` helper; when
`phase_v2.dynamic_risk.use_predicted_volatility` is `true` (default
`false`) and a prediction is available, it replaces the backward-looking
`rolling_volatility_20d` average everywhere volatility drives sizing
(`volatility_regime` classification, `annualized_volatility`, the
`volatility_multiplier` itself). New `volatility_source` field
(`"rolling"`/`"predicted"`, default `"rolling"`) reports which one
actually drove a given bar. Default `false` means byte-identical output
everywhere the flag isn't explicitly enabled — same pattern as this
session's `use_composite_signal_score`.

**Retraining pipeline.** `retraining/artifacts.py` gains
`OPTIONAL_MULTITASK_FILES` (3 filenames, same optional/best-effort
contract as `OPTIONAL_TOPOLOGY_FILES`/`OPTIONAL_GATING_FILES`) plus
`check_multitask_artifacts()`. `retraining/orchestrator.py` gains
`train_multitask()` (mirrors `train_gating()` line-for-line) plus a CLI
subparser; `retraining/worker.py` calls it right after `train_gating()` in
`run_once()`. New `aq train --multitask-only` flag (mirrors
`--gating-only` exactly). `config.json`'s `promotion.active_artifact_files`
extended with the 3 new files. `Dockerfile.retraining_worker` gains `COPY
train_multitask.py .` (needed for the new stage's subprocess call) and,
found during that same audit, `COPY risk/ ./risk/` — a pre-existing gap
that should have broken `retraining.worker`'s container startup entirely
(see `development/Problems.md` #20); **the `retraining-worker` Docker
image needs a rebuild** for either fix to take effect.

**Scope decisions (this pass vs. the original plan).** Two pieces of the
original plan were deliberately not implemented this session, documented
rather than silently dropped:
- **Regime/liquidity/topology as genuine model *input* features** (not
  just downstream consumers) — the plan's own text flagged topology as
  the highest-effort piece requiring a new per-historical-date
  cross-asset loop, and extending `feature_schema.json`'s
  `model_input_names` would force retraining the baseline/experts/gating
  together with a new input dimensionality (correct per the plan, but a
  materially larger blast radius than fit this pass). Not started.
- **Gating does not blend per-expert magnitude/volatility** — the
  multi-task model is trained once, at baseline scale, not once per
  expert, so there is no per-expert magnitude/volatility for
  `moe/gating.py` to weighted-average the way `expert_probability_up`
  already is. `main.py` calls the multitask model directly instead of
  routing it through `build_gating_decision()`. See `moe/README.md`.

Phase 2 (a real sequence encoder replacing the flat-MLP trunk) remains
unimplemented, exactly as scoped in the original plan — it depends on this
phase's branching export/interpreter pattern existing and being validated
first, which it now is.

- New tests: `tests/test_exported_model.py` (+7: `_softplus` hand-computed
  values, a full-stack `run_exported_multitask_model()` parity test
  against an independently hand-transcribed reference, a nonnegative-
  volatility check, an unsupported-layer-type check),
  `tests/test_train_multitask_architecture.py` (new, 8 tests: the
  `target_volatility_next_day` column against an independent hand
  computation, `AetherNetMultiTask` forward shapes and the volatility
  head's nonnegativity, `export_multitask_architecture()`'s shape and
  disjoint weight keys, `compute_regression_metrics()`),
  `tests/test_train_multitask.py` (new, 8 tests, pure-function style
  mirroring `tests/test_train_gating.py`), `tests/test_position_sizing.py`
  (existing 11 unchanged, confirming the new params are additive),
  `tests/test_market_analyzer.py` (existing 32 unchanged, confirming the 2
  new fields are additive), `tests/test_retraining_artifacts.py`/
  `test_retraining_orchestrator.py` (+13 for the new multitask stage,
  mirroring the existing topology/gating stage tests), `tests/test_aq_cli.py`
  (+3 for `--multitask-only`).
- Stopping point: `python train_multitask.py` was smoke-tested against the
  real dataset (see above) but its resulting model was **not** installed
  into active `ml/`, and no real Lean backtest with
  `use_predicted_volatility: true` was run — per this session's
  established preference, the user runs the real training/backtest
  themselves.

**Update, same session:** the two scope decisions above (regime/liquidity/
topology as genuine input features, and per-expert multitask blending) and
Phase 2 (the sequence encoder) were all subsequently implemented later in
this same session, after this entry was originally written — see "Phase 1
remainder + Phase 2: regime/liquidity/topology as inputs, per-expert
multitask, sequence encoder" below. This entry is left as-written (not
rewritten in place) so the plan-vs-actual scoping history stays visible.

## Phase 1 remainder + Phase 2: regime/liquidity/topology as inputs, per-expert multitask, sequence encoder

Continuation of the multi-task prediction entry above, same session: the
two pieces explicitly scoped out there, plus Phase 2 (the sequence
encoder), all implemented and verified against the real dataset.

### Regime/liquidity/topology as genuine model input features

`train.py::build_feature_dataset()` gains three new per-row/per-date
feature builders, all reusing the exact runtime functions each subsystem
already ships (no parallel reimplementation):

- **`add_regime_features()`** — row-wise, calls `regime.build_market_regime_vector()`
  on each row's own already-engineered momentum/volatility columns
  (`portfolio_drawdown=0.0`/`average_correlation=0.0`, the same honest
  offline simplification `train_gating.py` already established). Adds 9
  one-hot columns (`regime_trend_bullish/bearish/sideways`,
  `regime_volatility_low/normal/high`, `regime_risk_on/off/neutral`) plus
  3 continuous columns, renamed `regime_signal_confidence`/
  `regime_signal_trend_score`/`regime_signal_risk_score` (see "naming
  collision" below).
- **`add_liquidity_features()`** — asset-intrinsic only:
  `liquidity_log_dollar_volume` (log1p of close×volume) and
  `liquidity_spread_proxy` (`liquidity.estimate_high_low_spread()` over a
  trailing `CROSS_SECTIONAL_WINDOW_BARS`-bar window, static fallback for
  the first bar). Deliberately excludes `participation_rate`/
  `estimated_slippage` — those need an assumed order size
  (`target_weight × portfolio_value`), which has no principled value
  before any sizing decision exists; a documented adaptation of the
  original plan text, not an oversight.
- **`build_topology_features_by_date()`** — genuinely new code (confirmed
  during planning: no prior function computed a cross-asset relationship
  at dataset-build time). For each unique historical date across the
  whole universe, gathers every asset's trailing `CROSS_SECTIONAL_RETURNS_WINDOW`-return
  window ending at that date and calls the real
  `topology.build_market_topology()` — `embedding_iterations=1`
  deliberately, since `correlation_strength`/`topology_risk` (the only two
  fields consumed) don't depend on the SMACOF x/y embedding at all, so the
  expensive iterative step is skipped for speed with zero effect on either
  output value. Adds `topology_correlation_strength` plus 3 one-hot
  `topology_risk_normal/elevated/isolated` columns. Missing/insufficient
  data defaults to the same "isolated, zero correlation" signal
  `build_market_topology()`'s own fallback already produces — never a
  NaN needing an extra dropna pass.

New `_categorical_feature_names()` treats the 12 one-hot columns above
like `add_asset_context_features()`'s existing asset one-hots: appended
directly to `model_input_names` unscaled (already-bounded `[0,1]` flags),
never run through `StandardScaler`. `config.json`'s
`phase1.features.input_set` gains the 6 new *continuous* names only (the
one-hots stay out of it, by design). `feature_schema.json` gains a new
`categorical_feature_names` field. **Model input dimensionality grows from
30 to 48** (10 original + 6 new continuous, scaled, + 12 new categorical +
20 asset one-hot) — this is a real, coordinated breaking change to the
shared input schema: baseline, all 4 experts, gating, and the multitask
model all needed retraining together (done — see below).

**Runtime integration (main.py) required reordering, not just extending.**
Topology was already computed once per bar before the symbol loop, so no
reordering was needed there. Regime, however, used to be computed *after*
the baseline model ran (purely for downstream gating/analyzer
consumption) — now that it's a genuine model *input*, `_build_model_input()`
computes `regime_payload` itself, before assembling `model_inputs`, and
`on_data()` reuses that same value later (`feature_payload["regime_payload"]`)
instead of recomputing it — one regime computation per bar, not two, and
gating/analyzer/dashboard now see exactly what the model saw. Liquidity's
`spread_proxy` is computed once in `_build_model_input()` too and reused
verbatim by the later `build_liquidity_decision()` call (previously
recomputed a second time).

**A real off-by-one bug was found and fixed via train/runtime parity
checking**, the same rigor applied to the multitask export in the entry
above: `add_liquidity_features()`, originally called *after*
`engineer_features()`, was operating on the post-dropna frame — since
`engineer_features()` always drops each asset's first raw row (its
`close_to_close_return_1d` etc. are undefined, no previous close), that
frame's own row 0 already corresponds to the asset's *second* raw bar, so
`spread_proxy`'s trailing window was silently missing the true first bar
for roughly each asset's first `CROSS_SECTIONAL_WINDOW_BARS` rows — a real
discrepancy from `main.py`'s live `self.symbol_windows`, which does
include that first bar. High/low pairs (unlike returns) are legitimately
usable from the very first raw bar, so this wasn't a fundamental
limitation, just a call-order bug. **Fix:** `add_liquidity_features()` now
runs on the *raw* per-asset frame, before `engineer_features()` — its
output columns ride along through the dropna step unaffected (they're
never in `required_columns`) with correct values. Verified via a
standalone parity script comparing `ml/datasets/full_dataset.csv`'s
offline values against an independent re-simulation of `main.py`'s
windowing logic, across several (ticker, date) pairs including this exact
early-history edge case (`ETHUSD`, its 6th ever row) both before (mismatch
confirmed) and after (exact match) the fix.

**Naming collision found and fixed.** `regime_confidence`/`regime_trend_score`/
`regime_risk_score` (the names `add_regime_features()` originally used)
collide with columns `experts/expert_datasets.py::annotate_dataset_with_regimes()`
already writes under those exact names (a separate, pre-existing
regime-annotation pass used only for expert dataset *filtering*, called
later in the pipeline inside `train_expert_models()`). The collision was
functionally harmless to already-trained models (expert training reads
the `_scaled` columns, computed and frozen *before* the collision, and the
two computations happen to produce numerically identical values under
default thresholds) but a real landmine for anyone changing
`phase_v2.regime_detection.*` thresholds later, since only one of the two
computations reads them from config. **Fix:** renamed to
`regime_signal_confidence`/`regime_signal_trend_score`/`regime_signal_risk_score`
throughout (`train.py`, `config.json`, `main.py`, tests) - the one-hot
names had no collision and are unchanged.

### Per-expert multitask heads + gating blend

`train.py` gains `_train_expert_multitask()`/`_write_expert_multitask_export()`,
mirroring `_train_expert_classifier()`'s exact shape but training
`AetherNetMultiTask` (not the direction-only classifier) per expert, over
the same regime-filtered dataset slice, with the same combined
BCE+MSE+MSE loss `train_multitask.py` uses. Wired into `train_expert_models()`'s
existing per-expert loop as a best-effort second step, right after the
classifier — writes `ml/expert_models/<name>/multitask_model.json` as a
sibling file. Gracefully skips (never crashes) when a dataset lacks the
multitask target columns (e.g. older synthetic test fixtures) — found via
a real pre-existing unit test failure (`tests/test_expert_models.py`)
during the full-suite run, fixed with an explicit column-presence guard.

`moe/gating.py::build_gating_decision()` gains `expert_magnitudes`/
`expert_volatilities`/`baseline_magnitude`/`baseline_volatility` params
and `final_magnitude`/`final_volatility` on `GatingDecision` (plus
`magnitude`/`volatility` on `ExpertGateWeight`). New `_weighted_blend()`
helper generalizes the exact weighted-average pattern `expert_probability`
already uses, with one deliberate difference: it returns `None` (not
`0.0`) when no expert has a value at all, since a spurious `0.0` would
misrepresent "no data" as "predicted zero magnitude/volatility". The
`baseline_fallback` branch (no experts eligible) uses `baseline_magnitude`/
`baseline_volatility` directly, matching how it already uses
`baseline_probability_up` directly in that branch. The learned-gating
override (when present) stays direction-only, as before —
`final_magnitude`/`final_volatility` are unaffected by `decision_source`
switching to `"learned_gating"`.

`main.py` gains `_load_expert_multitask_exports()`/`_run_expert_multitask_models()`
(same optional, per-expert graceful-degradation contract as the direction
experts), and `predicted_return_magnitude`/`predicted_volatility` (already
threaded through signal_payload/analyzer/position-sizing in the entry
above) now come from `gating_payload["final_magnitude"/"final_volatility"]`
— the full baseline-anchor-plus-per-expert-weighted-average blend — instead
of directly from the single baseline-scale multitask model. Same treatment
`probability_up` itself already got from gating, now extended to
magnitude/volatility too.

### Phase 2: causal-TCN sequence encoder

The root-cause investigation's other structural finding — "AetherNet is a
plain feedforward MLP with zero temporal structure" — addressed via a new
sequence-encoder trunk, additive and informational-only this pass (not
wired into any trading decision yet).

**`inference/exported_model.py` gains 4 new primitives**, each
independently cross-checked against real PyTorch modules during
development (not merely hand-computed) to well under float32 tolerance:
`_softmax` (numerically stable, arbitrary axis), `_layernorm_axis`
(generalizes `_layernorm` to normalize along a chosen axis of a
multi-dimensional array — needed for per-timestep normalization over a
`(window, features)` sequence, where the original `_layernorm` normalizes
a flat vector as one whole), `_conv1d_causal` (causal dilated 1D
convolution matching `torch.nn.Conv1d` under left-zero-padding — verified
to `9.1e-8` max abs diff against a real `nn.Conv1d`), and
`_multihead_attention` (scaled dot-product multi-head self-attention with
an optional causal mask — verified to `5.6e-8` against real
`nn.MultiheadAttention`). New `run_exported_sequence_multitask_model()`
walks a `{"trunk": [...], "heads": {...}}` export whose trunk is
`conv1d_causal`/`relu`/`dropout` layers instead of `linear`, pools to the
trunk's most-recent (causal) timestep, then the same 3-head shape
`run_exported_multitask_model()` already uses. `run_exported_model()`/
`run_exported_multitask_model()` are completely untouched — new functions
alongside them, zero regression risk.

**`train.py` gains `AetherNetSequenceMultiTask`** — a causal TCN trunk
(dilation doubling per layer: 1, 2, 4, ..., the standard WaveNet/TCN
receptive-field-growth idiom; each conv left-padded by
`(kernel_size-1)×dilation` timesteps so `output[t]` never depends on
`input[>t]`) over a rolling window of already-computed flat
`model_inputs` vectors, pooled to the most-recent timestep, then the same
3 heads `AetherNetMultiTask` uses. **Chosen over a Transformer encoder
block for this first real Phase 2 model specifically because a causal
conv stack is simpler to verify bit-for-bit end-to-end** —
`_multihead_attention()` above is implemented and independently tested as
interpreter infrastructure for a future attention-based model, not wired
to a trained export in this pass. `export_sequence_multitask_architecture()`
is the matching exporter. New `build_sequence_tensor_dataset()` needs no
new feature engineering — it only windows over each ticker's own trailing
history of the *same* 48-dim `model_input_names` columns Phase 1 already
computes per row, zero-padding rows with less than a full window of
history (mirrors `main.py`'s runtime buffer starting empty and filling up
bar by bar).

**`train_sequence.py`** (new, mirrors `train_multitask.py`'s structure):
builds `(rows, window=30, features=48)` tensors from the active dataset,
trains with the same combined BCE+MSE+MSE loss, writes
`ml/versions/<id>/sequence_model.json`/`sequence_feature_schema.json`/
`sequence_training_metrics.json`. Smoke-tested end-to-end against the real
dataset (30,193 eligible rows) — training completed in ~3.5 minutes
(building the sequence tensor: seconds; training: the rest), backtest
direction MCC 0.0219 (same noisy range as every other model in this
system — Phase 2's goal this pass was proving the temporal-structure
pipeline works end-to-end, not fixing the underlying noise, which the
original root-cause investigation never claimed a single architecture
change would do). **Interpreter parity independently verified** against
the real trained export, and separately against a synthetic model with a
hand-computed reference in `tests/test_exported_model.py`.

**`main.py` runtime integration is additive and informational-only, by
deliberate design.** A new per-symbol rolling buffer,
`self.symbol_feature_history` (`deque(maxlen=phase_v2.sequence_model.window_size)`,
default 30) — **deliberately a separate buffer from `self.symbol_windows`**
(raw OHLCV, sized to match `train.py`'s `CROSS_SECTIONAL_WINDOW_BARS` for
the Stage-1-3 feature parity established above), not a resize of it;
changing `symbol_windows`' length would have silently broken that
already-verified parity. Each bar, right after `_build_model_input()`
computes the flat 48-dim vector, it's appended to the buffer (before
running the sequence model, so the most-recent timestep is always the
current bar) — reusing the already-computed vector directly, never
recomputing regime/liquidity/topology per historical bar. `_run_sequence_model()`
left-pads with zero vectors when less than a full window of history
exists yet, matching `build_sequence_tensor_dataset()`'s exact offline
convention. Output threads into `signal_payload["sequence_model"]` and
`state["model"]["sequence"]` for dashboard/diagnostic visibility only —
**it does not feed gating, the analyzer, or position sizing this pass**.
Wiring it into an actual trading decision is a deliberate follow-up, not
an oversight: it needs its own validation pass (real backtest comparison
against the flat multitask model) before it should influence money,
mirroring how the flat multitask model itself was smoke-tested
extensively before Phase 1 wired it into sizing.

### Retraining pipeline (both pieces)

`retraining/artifacts.py` gains `OPTIONAL_SEQUENCE_FILES` (3 filenames,
same optional/best-effort contract as the other `OPTIONAL_*_FILES`
tuples) plus `check_sequence_artifacts()`. `retraining/orchestrator.py`
gains `train_sequence()` (mirrors `train_multitask()` line-for-line) plus
a CLI subparser, run right after `train_multitask()` in
`retraining/worker.py`'s `run_once()`. New `aq train --sequence-only`
flag (mirrors `--multitask-only`/`--gating-only` exactly).
`config.json`'s `promotion.active_artifact_files` extended with the 3 new
files. `Dockerfile.retraining_worker` gains `COPY train_sequence.py .`.

### Verification

Full suite green after every stage, with one real regression found and
fixed along the way (the `tests/test_expert_models.py` failure above —
not a stale test, a genuine gap in the new per-expert multitask call's
column-presence assumption). Real end-to-end runs, not just unit tests:
full dataset rebuild (~1m47s, up from ~28s pre-session — the topology
per-date cross-sectional loop is the added cost, acceptable for an
occasional offline build step), baseline+expert retraining, gating/
multitask/sequence retraining, and a full interpreter smoke test chaining
every model (baseline → experts → gating blend, including per-expert
magnitude/volatility) end-to-end against the real retrained artifacts.

- New tests: `tests/test_train_cross_sectional_features.py` (new, 13
  tests: `add_regime_features()` against an independent
  `build_market_regime_vector()` call, `add_liquidity_features()`
  including the fixed windowing behavior, `build_topology_features_by_date()`
  including the highly-correlated/single-asset/early-history edge cases,
  `_categorical_feature_names()`), `tests/test_gating_network.py` (+7 for
  the magnitude/volatility blend: default-None, full blend arithmetic,
  baseline-only fallback, expert-only fallback, `baseline_fallback`
  ignoring expert values, `ExpertGateWeight` carrying magnitude/volatility
  through), `tests/test_exported_model.py` (+11 for the 4 Phase 2
  primitives plus `run_exported_sequence_multitask_model()`'s full-stack
  parity/causality/error-handling), `tests/test_train_sequence_architecture.py`
  (new, 13 tests: `AetherNetSequenceMultiTask` shapes/dilation/determinism,
  `export_sequence_multitask_architecture()`'s structure, and
  `build_sequence_tensor_dataset()`'s row-alignment/zero-padding/
  ticker-boundary/full-window behavior), `tests/test_retraining_artifacts.py`/
  `test_retraining_orchestrator.py`/`test_aq_cli.py` (+~20 for the
  `train_sequence` stage, mirroring the existing multitask stage tests).
- Docker: `Dockerfile.retraining_worker` needs a rebuild
  (`docker compose build retraining-worker`) to pick up `train_sequence.py`
  in addition to the `risk/`/`train_multitask.py` fix from the entry
  above.
- Stopping point: no real Lean backtest was run (per this session's
  established preference, the user runs it). The baseline, all 4 experts,
  gating, multitask, and sequence models were all retrained on the final
  48-dim feature set and installed into active `ml/` so the artifacts on
  disk are internally consistent (no stale narrower-dimension exports
  left behind); the sequence model's runtime integration remains
  informational-only regardless (see above) — it does not need a
  validated backtest before it can ship, since it cannot influence any
  trading decision yet.

## Multitask/sequence pipeline integration — closing the 7 remaining gaps

Follow-up pass to the two entries above: the multitask/sequence models
themselves were fully built and verified, but 7 integration points between
that new model layer and the rest of the stack were still open. All 7 are
closed now (one, `requirements-retraining-worker.txt` already covering
`train_sequence.py`'s deps, needed no action — confirmed, not fixed).

- **Real-backtest coverage.** `tests/test_lean_backtest_ml_coverage.py`
  gains 4 tests exercising a real `lean backtest .` run against the 48-dim
  input pipeline, the baseline multitask model, the per-expert multitask
  heads' contribution to `moe_gating.final_magnitude`, and the sequence
  model — the established mechanism this repo uses for real-backtest
  proof, rather than a manual one-off run.
- **`sequence_model` now reaches the experience/Postgres pipeline.**
  `experience/redis_queue.py::build_experience_event()` gains an optional
  `sequence_model` field (defaults `None`); `main.py`'s call site now
  passes the already-computed `sequence_prediction` through. No Postgres
  migration — the whole event dict already serializes into the catch-all
  `payload JSONB` column.
- **Neural-network webui page extended to all 11 real networks.**
  `monitoring/neural_network_state.py::_parse_network_export()` now
  dispatches between the original flat `architecture` shape and the new
  branching `{"trunk", "heads"}` shape (`_parse_branching_network_export()`),
  tagging every layer with its owning head; `_weight_stats()`'s flatten
  was made recursive (`_flatten()`) to handle `conv1d_causal`'s 3D weight
  matrix. `build_neural_network_state()` now also reads
  `ml/multitask_model.json`, each expert's `multitask_model.json`, and
  `ml/sequence_model.json`. On the webui side, `NeuralNetworkScene3D.tsx`'s
  new `headColumnsFor()` expands each multitask/sequence network into one
  diagram column per head (direction/magnitude/volatility), reusing the
  existing `NetworkDiagram` primitives unchanged rather than building a
  new 3D branching-tree renderer; `NETWORK_ORDER` extended with the 6 new
  names (previously a silent filter — see Problems.md #19 on why this
  matters). Also fixed a stale claim in `v2_architecture.md`'s Neural
  Network Visualization Contract: the "gating has no learned weight
  matrix, excluded" paragraph predated the learned-gating model and no
  longer matched the code (gating has been rendered as a real network,
  not excluded, since that work shipped).
- **`development/v2_architecture.md` updated**: the Neural Network
  Visualization Contract section now documents all 11 networks and the
  branching export shape; a new "Model input dimensionality is 48, not
  30" sub-block on the Expert Model Contract; a new Follow-up paragraph on
  the Gating Network Contract for the magnitude/volatility blend; a new
  "Phase 2 Sequence Encoder Contract" section; and the Redis Experience
  Queue section's schema/Follow-up now include `sequence_model`.
- **Retraining promotion-cycle test coverage + runbook doc.** New tests
  confirm `OPTIONAL_MULTITASK_FILES`/`OPTIONAL_SEQUENCE_FILES` stay
  present in `ALL_TRACKED_FILES`/`ACTIVE_ARTIFACT_FILES`, and that a
  candidate's `multitask_model.json`/`sequence_model.json` survive
  `commit()`'s hashing step (mocked subprocess/vault, no live Postgres
  needed — matching this file's own established test-coverage
  convention). `development/infrastructure.md`'s retraining runbook now
  lists the full `train_topology`/`train_gating`/`train_multitask`/
  `train_sequence` stage order (a pre-existing gap in that doc, unrelated
  to this session, fixed while already touching the exact list it lives
  in) and notes per-expert multitask artifacts are **not** tracked by
  `retraining/artifacts.py` — they follow a separate promotion path.
- **Per-bar inference cost documented, not benchmarked.** Problems.md
  #21: the forward-pass count went from 5 to 11 per symbol per bar.
  Explicitly not measured this pass — both new model families are either
  informational-only or gated behind an off-by-default config flag, so
  nothing trades on them yet, and this repo's only enforced latency
  constraint (Lean's 90s `initialize()` isolator timeout) is unrelated to
  per-bar cost. If it ever becomes a real problem, entries #16/#17
  already establish the diagnose-via-real-backtest-run method to use.
- **README architecture diagrams updated** to visually match the prose
  already added in the entry above — see the "System Flow"/"Tech Stack"
  Mermaid diagrams.

### Verification

`pytest tests/` — full suite green (see the test badge at the top of this
repo's README, refreshed via `aq test`).
`tests/test_lean_backtest_ml_coverage.py`'s new assertions are exercised
only when the Lean CLI is available locally (self-skips otherwise, same
as the rest of that file). `npx tsc -b --noEmit` in `webui/` — clean, no
type errors from the `NeuralNetworkModel`/`NeuralNetworkLayer` type
extensions or `NeuralNetworkScene3D.tsx`'s head-column expansion.
