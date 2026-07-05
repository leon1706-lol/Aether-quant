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
