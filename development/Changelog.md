# Changelog

Detailed phase results for Aether Quant (see `README.md` for current
status, project structure, and runbook). Newest entries at the bottom,
ordered chronologically by phase. Each entry: **Summary** (what/why) →
**Shipped** (concrete changes) → **Verification** (how confirmed; omitted
when none). Full pre-condensation snapshots live in `backups/`.

## V1 — Finished

First working pipeline over a small mixed universe (`AAPL`, `SPY`, `QQQ`,
`BTCUSD`), 2014-12-01 to 2018-08-13 daily bars.

- Train/validation/backtest windows; next-day-direction label; 1d/5d/20d
  return/volatility/momentum, daily range, volume-change features.

## Phase 2 Result

- Loads Lean ZIPs, normalizes prices, computes features/targets, produces
  train/validation/backtest splits, fits and saves the scaler.

## Phase 3 Result

- PyTorch MLP with layer norm/dropout, asset context as model input,
  validation-loss early stopping, optimized decision threshold, saved
  metrics/checkpoint, JSON export for Lean inference.

## Phase 4 Result

- Loads exported artifacts (weights/schema/manifest/scaler), runs the
  forward pass directly in Lean; real buy/sell/hold signals written to
  `visualization/state.json`.

## Phase 5 Result

- Strategy returns vs buy-and-hold; Sharpe/volatility/max-drawdown export;
  equity curves; `backtests/strategy_report.json`.

## Phase 6 Result

- Separated Lean/dev dependencies; runs in the real local Lean Docker
  runtime; daily/total drawdown risk controls with trade-blocking +
  liquidation; minimum confidence + trade cooldown.

## Phase 8 Result

- `state.json` extended with dashboard/monitoring/scene data;
  Grafana-friendly CSV/JSON exports; scorecards, asset heatmap, risk band,
  positions, 3D-like dashboard scene.

## Phase 9 Result

Universe expanded to equities, ETFs, and 3 crypto coins with a
data-quality-aware pipeline.

- Derives ETHUSD/LTCUSD from Coinbase minute data; per-asset quality
  scoring; trains only on robust assets; thin series flagged
  `observation_only` (blocked from real trades, still shown); position/
  exposure caps.
- **Verified:** successful Lean backtest over the expanded universe.

## Phase 10 Result

- Large artifacts kept out of git; documented core commands; structured
  runtime logs; first `pytest` tests (features, asset quality, scaler,
  risk controls); pre-flight artifact/config validation.

## Phase V2-1 Result

Started the V2 fork on top of the stable V1/Phase 10 codebase.

- V2 module structure (MoE, experts, regime, topology, experience, risk,
  monitoring); documented planned architecture and tech stack (Docker,
  Lean, PyTorch, Postgres, Grafana, Telegram, HTML dashboard).

## Phase V2-2 Result

- `data_pipeline/` as a stable V2 layer over `train.py`; a V2 pipeline
  manifest (source, universe, features, windows, quality); tests locking
  in the Lean data contract.

## Phase V2-3 Result

- `risk/position_sizing.py`: volatility-classified (`low`/`normal`/`high`)
  dynamic sizing (`base_target_weight`, `target_weight`,
  `leverage_factor`) into runtime state, heatmap, Grafana CSV.

## Phase V2-4 Result

- `volatility_dashboard.html`: 5s-refresh live view reading `state.json`
  directly — portfolio/risk/drawdown plus per-asset signal/regime/vol/
  sizing/confidence. Works without a broker key.

## Phase V2-6 Result

- `regime/market_regime.py`: trend (`bullish`/`bearish`/`sideways` from
  momentum) + volatility regime → `risk_on`/`risk_neutral`/`risk_off`.

## Phase V2-7 Result

- `experts/expert_datasets.py`: regime-sliced expert training datasets,
  filtered to `training_eligible`, with a manifest (row counts, splits,
  routing filters). Artifacts out of git.

## Phase V2-8 Result

- Separate PyTorch expert models per regime slice (MLP family);
  `train.py --experts-only`; per-expert weights/metrics under
  `ml/expert_models/`.

## Phase V2-8.5 Result

- Smaller experts with stronger regularization; a quality gate
  (validation/backtest/MCC/train-backtest gap) flagging each expert
  `stable`/`watchlist`/`disabled_for_gating` so gating never trusts a weak
  or overfit expert.

## Phase V2-9 Result

- `moe/gating.py`: weights experts by quality gate, regime fit, stability
  (ignores `disabled_for_gating`); combines baseline + experts into one
  final MoE probability; falls back to baseline if artifacts missing.

## Phase V2-10 Result

A single pure decision layer replacing an ad-hoc if/elif chain in
`main.py`.

- `analyzer/market_analyzer.py::build_market_analysis_decision()` returns
  exactly one of `observe`/`simulate`/`trade`/`reduce_risk`/
  `retrain_candidate`, priority-ordered (risk containment > model health >
  profit action > paper tracking > observation). `_apply_signal` still
  only trades on `trade`.
- **Verified:** 13 new tests in `tests/test_market_analyzer.py`.

## Phase V2-11 Result

A pure cross-asset topology layer that starts influencing decisions.

- `topology/market_topology.py`: pairwise correlation, union-find
  clustering, 3D coordinates (correlated assets near each other,
  volatility on z); computed once per bar before the per-asset loop, no
  lookahead.
- Analyzer tiers: `topology_risk=="elevated"` forces `reduce_risk`; an
  isolated asset can't reach `trade` (falls back to `simulate`). New
  `/topology` tab + `/api/topology`.
- **Verified:** new `tests/test_market_topology.py` + 4 analyzer cases.

## Phase V2-12 Result

A pure per-asset liquidity/market-impact layer.

- `liquidity/market_liquidity.py`: dollar-volume/participation/slippage/
  round-trip-cost from OHLCV alone; classifies orders
  `normal`/`thin`/`high_impact`/`blocked` recommending
  `allow`/`reduce_size`/`simulate_instead`/`block`. Two analyzer tiers
  force `simulate`.
- Real per-asset fees in Lean (`ConstantPercentageFeeModel` crypto,
  `ConstantFeeModel` equities); `LiquidityTable.tsx`; `Dockerfile` +
  extended compose.
- **Verified:** 9 liquidity tests + 4 analyzer cases; LTCUSD correctly
  hits `blocked`/`simulate` without disrupting the decision tree.

## Phase V2-13 Result

Fire-and-forget Redis experience-event stream.

- `experience/redis_queue.py`: `build_experience_event()` +
  `ExperienceQueue` (XADD after every asset decision, `maxlen=100000`);
  fails silently on Redis errors, never blocks the Lean loop; deferred
  `redis` import keeps Lean environments importable without it.
- **Verified:** 8 tests in `test_experience_queue.py`.

## Phase V2-14 Result

Durable PostgreSQL persistence for the experience stream.

- `experience/postgres_worker.py`: standalone worker (`XREADGROUP` →
  `experience_events`, embedded DDL, no migrations); idempotent via
  `ON CONFLICT DO NOTHING`; dead-letter stream for malformed messages;
  exponential backoff/reconnect. New `experience-worker` service.
- **Verified:** 7 tests in `test_postgres_worker.py`.

## Phase V2-15 Result

Observation Mode — full decision pipeline, zero real orders, parallel
simulated portfolio.

- `phase_v2.runtime.mode` (`backtest`/`observation`/`paper`/`live`,
  default `backtest` unchanged); `execution/order_gate.py::
  resolve_order_permission()` — observation is **never** allowed real
  orders regardless of any other flag.
- `experience/simulated_portfolio.py::SimulatedPortfolioState` — fake
  cash/holdings/equity/drawdown/exposure entirely in memory; cooldown/
  position-limit/exposure/drawdown checks made mode-aware;
  `observation_metrics.py`; dashboard exports + `ObservationPanel.tsx`.
- **Verified:** 33 new tests (80 → 113) incl. safety-critical
  never-allows-orders-even-if-flags-true; real Lean backtest with
  `mode="observation"` shows `"Total Orders": "0"`, unchanged end equity,
  while the panel showed simulated activity; two Docker bugs fixed
  post-hoc (`Dockerfile.worker` missing `execution/`;
  `requirements-worker.txt` missing `numpy`).

## Phase V2-16 Result

Performance Triggers — automated threshold-based health monitoring.

- `performance/triggers.py`: 8 pure trigger functions (drawdown, Sharpe
  degradation, win rate, confidence decay, regime shift, liquidity
  warning, risk-lock, observation count) + `evaluate_all_triggers()`;
  each event carries severity/scope/recommended_action/
  `retrain_candidate`. Dedicated Postgres table, standalone
  `performance/trigger_worker.py`, in-memory fast-path view in `main.py`,
  `PerformanceTriggersPanel.tsx`.
- **Verified:** 37 new tests (113 → 150).

## Visualization Unification Result

Two separate HTML dashboards replaced by a single React/Vite webui plus a
FastAPI JSON backend.

- `monitoring/api_server.py` serves `state.json`/`scene.json`/Grafana
  exports; Overview + Risk pages map 1:1 onto the old dashboards;
  genuinely 3D rotatable market scene (`@react-three/fiber`) — foundation
  for V2-11's topology view.

## Phase V2-17 Result

Controlled Retraining — full plan/train/validate/backtest/commit/promote/
rollback pipeline closing V2-16's open loop.

- New `retraining/` package (pure/IO/worker split): `planning.py`,
  `postgres_registry.py` (`model_versions`/`retraining_events` DDL,
  one-active-model DB constraint), `validation_gate.py`,
  `backtest_gate.py`/`lean_backtest.py`, `vault_commands.py`/
  `vault_client.py` (external `av` subprocess wrapper, missing-binary-safe),
  `artifacts.py`, `status_export.py`, `orchestrator.py` (CLI), `worker.py`.
- `train.py --candidate --version-id` writes exclusively to
  `ml/versions/<id>/`, never active paths; promotion requires a successful
  Aether-Vault commit; rollback verifies SHA-256 hashes before activating;
  `RetrainingWorker.auto_promote` defaults `false`.
- **Verified:** 90 new tests (150 → 244).

## Phase V2-17.5 Result

Probabilistic topology overlay + richer triggers — strictly additive, never
replacing the deterministic path.

- `topology/learned_topology.py`: per-node cluster probabilities/
  confidence/uncertainty/stress/neighbor-drift; falls back to the
  deterministic position whenever the model is missing or unconfident.
- `train_topology.py`: fits KMeans prototypes from real experience-event
  outcomes → `ml/versions/<id>/` only; skips on insufficient data. 5 new
  persistence-guarded triggers (topology uncertainty/mismatch/drift,
  model-disagreement, trigger-frequency-spike); `retraining/planning.py`
  picks candidates by priority score, not timestamp.
- **Verified:** 69 new tests (244 → 313).

## Phase V2-18 Result

Grafana removed in favor of a native React tracing dashboard (it had no
computation path of its own — purely a new consumer of existing exports).

- Deleted the `grafana` service/volume; new `/tracing` page with 4 panels
  (metrics snapshot, asset performance, backtest equity, observation
  equity) + two dependency-free SVG chart primitives.

## Phase V2-19 Result

Telegram Alerts for trigger events and end-of-session summaries.

- New `notifications/` package (pure/IO/worker split); trigger channel
  polls the existing `performance_triggers` table directly; session-summary
  channel adds a new experience event at session rollover in `main.py`.
  Fixed a real gap caught mid-implementation: `event_to_row()` KeyError'd
  on session-summary events, silently dead-lettering every one forever.
- **Verified:** 24 new tests + 7 extensions (313 → 364 with V2-19.5).

## Phase V2-19.5 Result

Manual, offline Yahoo Finance backfill script for thin local Lean data
(mainly ETHUSD/LTCUSD) — never runs from training/runtime/Docker.

- `data_pipeline/yfinance_backfill.py`: dry-run by default (`--apply`
  writes); real Lean rows win on overlap; `yfinance` stays dev-only.
- **Verified:** 20 tests using an injected fetch stub.

## Phase V2-23.1 Result

Data-driven liquidity spread estimation (closed differently than planned:
no real fill-slippage telemetry existed to calibrate from).

- `estimate_high_low_spread()`: Corwin & Schultz (2012) closed-form high-
  low estimator from already-collected bar data; replaces the static
  per-security-type spread lookup as primary (static stays fallback).
- **Verified:** 10 tests (independent reference calc, monotonicity,
  fallback behavior).

## Phase V2-23.2 Result

Config audit: three `phase_v2` blocks `main.py` had read since
V2-3/V2-6/V2-9 were never present in `config.json` (silently forcing
hardcoded defaults); `average_correlation` unfed since V2-6.

- Added the three blocks (values = prior defaults, no behavior change);
  wired `average_correlation` from topology's `correlation_strength`.
- **Verified:** 1 test confirming pass-through affects `risk_score`/
  `reasons`.

## Phase V2-23.3 Result

Topology's 3D layout was purely cosmetic angle-based placement.

- `_stress_majorize_2d()`: SMACOF stress-majorization over the full
  pairwise correlation-distance matrix, deterministically seeded,
  isometrically rescaled into display bounds; chosen over classical MDS to
  stay numpy-free.
- **Verified:** 3 tests.

## Test Suite

313 → 378 after the audit pass (14 new: 10 liquidity, 1 regime, 3
topology).

## Phase V2-20 Result

Confirmed a normal `lean backtest .` already exercises the entire ML stack
end-to-end (baseline, 4 experts, MoE gating, regime, topology) — proof of
coverage, nothing rebuilt.

- `tests/test_lean_backtest_ml_coverage.py`: first real integration test
  (subprocess run asserting all subsystems populate `state.json`),
  closing `main.py`'s zero-test gap (#8/#66). Lean-vs-Lean4/`elan`
  binary-collision safeguard for the skip check. New `/neural-network`
  page: interactive 3D view of all 5 trained networks + live stats.

## Phase V2-21 Result

Paper Trading Preparation — real code-enforced gates targeting Lean's
built-in PaperBrokerage (not a real IBKR paper account).

- `execution/paper_readiness.py`: `evaluate_paper_broker_config()` (3
  required confirmations), `evaluate_observation_readiness()` (4 of 5
  checklist items; the 5th deliberately left as human review). New
  `aq paper-readiness` gate, `PaperReadinessPanel.tsx`, opt-in
  `lean-live` compose profile.
- **Verified:** tests across `test_paper_readiness.py`/`_io.py`/`_report.py`.

## Phase V2-22 Result

Live Deployment Structure — purely structural groundwork so paper→live
becomes a config/credential change, not a rewrite. No real credentials or
live trades configured or tested.

- `execution/live_credentials.py`/`live_credentials_io.py` (tries
  `ib_config.py`, falls back to env vars); `evaluate_live_broker_config()`/
  `evaluate_live_risk_posture()`; auto-promote forces manual promotion when
  `mode=="live"`; new critical `live_order_permission_blocked_trigger`
  (not retrain-eligible — a broker misconfiguration isn't fixed by a new
  model).
- **Verified:** tests across `test_live_credentials.py`/`_io.py`/
  `test_runtime_config_io.py` + retraining/trigger extensions.

## Latency Optimization + Docker Image Consolidation

Static complexity analysis of `main.py`'s per-bar hot path found 3 real
bugs + 2 CPU bottlenecks (pure-Python NN forward pass, pure-Python
O(N²×100-iter) SMACOF); Docker images consolidated 5→3 as groundwork for a
later latency-optimized variant (explicitly not an HFT conversion).

- Bugs (#11–#13): `_write_state()`'s useless throttle guard rewrote all 7
  state files every bar; `mark_to_market()` called once per symbol instead
  of once per bar caused O((bars·symbols)²) CSV rebuild work — fixed via
  `close_prices_by_symbol` collection + new
  `_flush_observation_equity_csv()`; new `execution/config_cache.py::
  read_cached()` mtime-cached config reads keyed `(config_path, loader)`
  after same-path readers overwrote each other's entries (found only via
  real `lean backtest .`).
- Left open then: skipping Redis push in backtest mode (#14).
- Docker: three worker images merged into one `Dockerfile.workers` (5→3
  custom images).
- NN inference extracted to `inference/exported_model.py` free functions,
  vectorized with numpy (was pure Python, ×5/symbol/bar);
  `_stress_majorize_2d()` vectorized too (the pairwise-correlation loop and
  `learned_topology.py`'s smaller O(N²×5) portion deliberately left
  unvectorized).
- Behavior-changing: `build_market_topology()` accepts
  `previous_positions` for warm-started SMACOF (+ `convergence_tolerance`
  early exit); `phase_v2.topology.warm_start_enabled` (default `true`) /
  `convergence_tolerance` (0.01) break bit-reproducibility vs. old
  cold-seeded behavior; `warm_start_enabled: false` is an exact rollback.
- **Verified:** compose build/up clean; parity tests vs hand-computed/
  reference values (`test_config_cache.py`, `test_exported_model.py`,
  extensions).

## 20-Asset Universe Expansion + Genuine Held-Out Backtest Window

Universe 10→20 on real data; backtest finally out-of-sample.

- 8 equities added at zero backfill cost from existing on-disk Lean data
  through 2021-03-31 (`AIG`, `BNO`, `FB`, `GOOG`, `GOOGL`, `USO`, `WM`,
  `AAA`); XRPUSD/ADAUSD backfilled via yfinance (real earliest history
  starts 2017-11-09, not the guessed dates); BTCUSD/ETHUSD/LTCUSD extended
  forward to 2021-03-31.
- Genuine held-out window: common-window end 2018-08-13 → 2021-03-31;
  training 2014-12-01→2017-12-31, validation 2018-01-01→2018-03-31,
  backtest 2018-04-01→2021-03-31 (~3 years; previously backtest == full
  window).
- Real bugs fixed: #15 — `ensure_derived_crypto_daily_series()`
  unconditionally clobbered ETH/LTC daily zips over yfinance-backfilled
  rows → merge by date instead; #16 — `initialize()` exceeded Lean's
  hardcoded 90s isolator timeout → split into minimal Lean-critical path +
  `_ensure_ready()` deferred to first `on_data()` (init now 1.85s, full
  window ~51s); #17 — intermittent timeouts from matplotlib font-cache
  rebuilds → persistent `MPLCONFIGDIR` pointed at `.matplotlib_cache/`.
- Manifest: 16/20 assets eligible; `AAA`/ETHUSD/XRPUSD/ADAUSD stayed
  observation-only for genuine sparsity. README "Universe Size" section +
  Mermaid diagram; lean-backtest timeout bumped 7200→14400s.
- **Verified:** regression test for #15; diagnostic runs confirmed
  #16/#17; the full multi-hour 3-year backtest deliberately left manual.

## `aq fetch` — ad-hoc Yahoo Finance ticker fetch

New `aq fetch <crypto|stock> --ticker ... --start ... --end ... [--apply]`,
replacing a multi-step manual ticker-onboarding process.

- `data_pipeline/fetch.py` reuses `yfinance_backfill.py`'s pure functions
  unchanged (`fetch_yahoo_ohlcv`, `scale_for_lean`, `write_lean_zip`);
  `ASSET_CLASS_CONFIG` drives the Lean path per class. Policy difference:
  unlike the backfill script, `fetch.py` writes `config.json` on `--apply`
  (adding a ticker is its whole purpose); leaves an existing entry alone.
- `aq_cli.py`: new `cmd_fetch` (in-process) + `_iso_date` argparse
  validator; packaging fix: `pyproject.toml`'s `packages` gained
  `"data_pipeline"` (same ModuleNotFoundError bug class as a prior
  `execution` fix).
- **Verified:** end-to-end with real yfinance calls (`DOGEUSD`, `MSFT`):
  dry-run writes nothing, `--apply` writes correctly-scaled zip + config
  block, re-run reports `already_exists`; packaging fix verified via the
  installed `aq fetch --help`. Tests: 13 fetch + 7 wiring.

## Trade-frequency tuning — statistical/diagnostic backtest mode

A real 3-year 20-asset backtest produced only 12 filled trades
(compounding suppression across several gates plus two structural traps),
so an opt-in bypass mode and threshold loosenings were added purely for
statistical/diagnostic evaluation.

- Opt-in `phase_v2.backtest.bypass_safety_gates` (default `false`),
  standalone key separate from `aq trade-lock`;
  `is_backtest_safety_bypass_active()` true only when
  `runtime_mode=="backtest"` and explicitly true. Bypasses ONLY the sticky
  total-drawdown lock and the regime detector's `risk_off` drawdown
  branch; all other gates stay real in live/paper mode.
- Config-only loosening: `min_confidence_to_trade` 0.12→0.05;
  buy/sell_threshold_offset 0.08→0.04; `trade_cooldown_bars` 3→1;
  thin_participation_threshold 0.002→0.01; blocked 0.05→0.10;
  max_active_positions 5→10; max_crypto_exposure 0.25→0.35.
  `min_training_rows` 100→50 unlocked ETH/XRP/ADA (19/20 eligible, only
  `AAA` observation-only — its data starts after both windows).
- Deliberately out of scope: real short-selling (`_apply_signal`'s sell
  branch only ever calls `Liquidate()`); hardcoded topology volatility
  threshold left unchanged.
- **Verified:** +4 tests for the bypass helper; confirming backtest vs the
  ~200-trade target left manual.

## Real learned gating weights + learned topology wired into position sizing

Closed two gaps flagged deferred by V3's completeness assessment:
gating was still hand-tuned arithmetic, and the learned topology overlay
never reached a trade decision.

- New pure `topology_sizing_multiplier()`: strict no-op (1.0) unless
  `topology_source=="learned"`; bounded shrink-only third factor in
  `build_dynamic_position_sizing()` — changes size only, never the
  decision. Keys: `phase_v2.dynamic_risk.topology_sizing_enabled`
  (default `true`), min/max multipliers 0.5/1.0.
- Additive learned gating: `GATING_MODEL_FEATURE_KEYS` (26-dim) +
  `build_gating_model_features()`; `build_gating_decision()` gains optional
  model/schema params → `decision_source: "learned_gating"`; any failure
  silently falls back to the hardcoded blend. Wired via
  `_load_gating_model()`, gated by
  `phase_v2.gating_network.learned_model_enabled` (default `true`).
- New offline trainer `train_gating.py`: trains on the dataset's validation
  split (avoids stacking circularity), replayed through exported models,
  evaluated on backtest split; `AetherNet(26 → [16] → 1)`; smoke-tested
  against real data (1,304 validation / 16,184 backtest rows), valid model
  in ~90s. Retraining pipeline extended (`OPTIONAL_GATING_FILES`,
  orchestrator stage, worker step, `aq train --gating-only`); webui shows
  gating with a violet render entry.
- **Verified:** tests +7 sizing, +5 gating, 8 trainer, extensions across
  retraining/CLI/neural-network-state; suite at 581 passed. #14 resolved
  (user confirmed nothing reads backtest-mode experience events). Gating
  model NOT promoted — user runs real training/backtests themselves.

## `aq config`/`aq lean` full read/write CLI + `analyzer/market_analyzer.py` real composite scoring

Full CLI read/write access to `config.json`/`lean.json` (replacing
hand-editing) plus a real config-gated composite signal-quality score.

- Both commands share one generic dispatcher (`_dispatch_json_config_command()`)
  — dotted-path walker/setter operating on whatever's on disk; bare
  command pretty-prints; `get`/`set <dotted.key> <value>`/`keys [prefix]`.
  Deliberately unrestricted `set` (list/dict paths; JSON-parsed value with
  string fallback). Safety via transparency: every set backs up to
  `<file>.json.bak` and prints old→new; type changes warn but still write.
  Small fix: `aq retrain` stage choices gained the existing-but-missing
  `train_gating`.
- `analyzer/market_analyzer.py::compute_signal_quality_score()`: bounded
  [0,1] weighted composite (confidence 0.45, regime confidence 0.20,
  topology peer-support 0.20, liquidity friction 0.15);
  `signal_quality_score`/`breakdown` always computed. New flag
  `phase_v2.market_analyzer.use_composite_signal_score` (default `false`)
  — only when true does it replace raw confidence in the trade gate
  (priority 7) and simulate-vs-observe split (priority 8); hard safety
  tiers 1-6 never affected.
- **Verified:** +18 CLI tests (12 config, 6 lean); all 21 pre-existing
  analyzer tests pass unchanged (byte-identical default); +11 analyzer
  tests.

## Multi-task prediction (direction + magnitude + volatility) — Phase 1

Root cause behind flat performance: every model sat at backtest MCC
0.02–0.07 (noise) with Sharpe -0.758, predicting only binary direction
with no magnitude/volatility forecast for sizing. This phase adds
multi-task heads (sequence encoder explicitly scoped out — built later).

- `export_multitask_architecture()` branching `{trunk, heads}` export
  alongside the unchanged original; `run_exported_multitask_model()` +
  `_softplus()` (guarantees volatility ≥ 0).
- `AetherNetMultiTask`: shared trunk + direction logit / magnitude
  regression / Softplus-volatility heads; new `target_volatility_next_day`
  column; `compute_regression_metrics()` (MAE/RMSE/bias).
- New `train_multitask.py`: loss = BCE(direction) + weight·MSE(magnitude)
  + weight·MSE(volatility) (both weights default 1.0); writes
  `ml/versions/<id>/multitask_*`; exits 0 on insufficient data.
- Runtime additive/informational: graceful artifact load gated by
  `phase_v2.multitask_model.enabled` (default `true`); predictions thread
  into signal_payload/analyzer/dashboard/CSV. Position sizing opt-in:
  `use_predicted_volatility` (default `false`) replaces backward-looking
  rolling vol when enabled.
- Retraining extended (`OPTIONAL_MULTITASK_FILES`, orchestrator stage,
  `--multitask-only`); `Dockerfile.retraining_worker` gained the COPY plus
  a found-missing `COPY risk/` fix (#20) — image needed rebuild.
- Scope documented, not implemented this pass: regime/liquidity/topology
  as genuine inputs; per-expert magnitude/vol blending.
- **Verified:** smoke-tested end-to-end on real data (30,332 rows):
  direction MCC 0.0174, magnitude MAE 0.0259, volatility MAE 0.0236;
  interpreter parity ~1e-7 (float32) vs from-scratch PyTorch forward.
  Model NOT installed into active `ml/`; no Lean run.

## Phase 1 remainder + Phase 2: regime/liquidity/topology as inputs, per-expert multitask, sequence encoder

Same-session continuation implementing both scoped-out pieces plus the
causal-TCN sequence encoder, all verified against the real dataset.

- Regime/liquidity/topology as model inputs: `add_regime_features()`
  (9 one-hot + 3 continuous; renamed to fix a naming collision),
  `add_liquidity_features()` (deliberately excludes participation/slippage),
  `build_topology_features_by_date()` (per-date cross-asset call). **Input
  dimensionality 30 → 48** — baseline/experts/gating/multitask all
  retrained together.
- Real off-by-one bug fixed: liquidity features originally ran after
  `engineer_features()`' dropna, silently missing each asset's first bars
  vs live windows; moved before it, on the raw frame (parity script:
  ETHUSD row 6 mismatch → exact match).
- Per-expert multitask exports under `ml/expert_models/<name>/`;
  gracefully skips datasets lacking the columns (found via a real
  pre-existing test failure). Gating gains expert magnitudes/volatilities
  params → `final_magnitude`/`final_volatility` on `GatingDecision`;
  `_weighted_blend()` returns None (not 0.0) without data; main.py now
  takes mag/vol from the full blend.
- Sequence primitives in `inference/exported_model.py` (`_softmax`,
  `_layernorm_axis`, `_conv1d_causal` verified 9.1e-8 vs real `nn.Conv1d`,
  `_multihead_attention` verified 5.6e-8 — infrastructure only);
  `AetherNetSequenceMultiTask`: causal TCN trunk chosen over a Transformer
  for bit-for-bit verifiability; `train_sequence.py` smoke-tested (30,193
  rows, ~3.5 min, MCC 0.0219 — same noisy range, proving the pipeline
  doesn't fix noise). Runtime integration informational-only this pass
  (`symbol_feature_history` deque maxlen=30).
- Retraining extended for both pieces (`OPTIONAL_SEQUENCE_FILES`, stage,
  `--sequence-only`).
- **Verified:** suite green after every stage; one regression found+fixed
  (column-presence gap in `test_expert_models.py`); dataset rebuild
  ~1m47s; baseline/experts/gating/multitask/sequence installed into active
  `ml/` on the final 48-dim set; no Lean run.

## Multitask/sequence pipeline integration — closing the 7 remaining gaps

Follow-up closing open integration points between the new model layer and
the rest of the stack.

- 4 new Lean-coverage tests exercising a real backtest against the 48-dim
  pipeline (baseline multitask, per-expert contribution, sequence).
- Experience events gain an optional `sequence_model` field (JSONB column,
  no Postgres migration).
- Neural-network webui extended to all 12 real networks (flat vs branching
  `{trunk, heads}` dispatch; recursive weight-stats flatten for conv1d 3D;
  per-head diagram columns; `NETWORK_ORDER` +6 — previously a silent
  filter, #19). `architecture.md` updated (all 12 networks documented,
  48-dim note, Sequence Encoder Contract section, Redis schema).
- Promotion-cycle tests confirm OPTIONAL files survive commit hashing;
  infrastructure.md documents the full stage order.
- Documented (#21, not benchmarked): forward passes went 5 → 11 per symbol
  per bar — both new families informational-only or off-by-default.
- **Verified:** pytest green (Lean coverage self-skips without the CLI);
  `npx tsc -b --noEmit` clean.

## Phase 2 sequence encoder wired into the gating decision (optional, off by default)

Closes the scope boundary restated by every prior entry: the sequence
encoder was informational-only; now wired into gating specifically (the
one funnel all prediction sources pass through). The analyzer and position
sizing deliberately get no second direct sequence input.

- `build_gating_decision()` gains `sequence_prediction` +
  `sequence_weight` (default `0.0`) applied last as the same anchor-blend
  shape `baseline_weight` uses; new `GatingDecision.sequence_blended` flag.
  Byte-identical until `phase_v2.gating_network.sequence_weight > 0`
  (e.g. 0.2, same order as `baseline_weight`'s default 0.25). Runtime
  state's `informational_only` flag is now dynamic instead of hardcoded.
- Docs corrected everywhere the stale claim lived (`moe/README.md` design
  writeup; Follow-up notes in inference/analyzer/risk/architecture).
- **Verified:** new gating tests (zero-weight no-op, None prediction with
  positive weight, full blend arithmetic, blending atop learned gating);
  file-level 23 passed.

## Frontier-model edge investigation — target redesign, real bug fixes, cross-sectional ranking (model input 48 → 59)

Every model (baseline, 4 experts, multitask, sequence) sat at backtest MCC
0.017–0.07 on next-day binary direction — noise. Fixed confounding
bugs, redesigned targets (5d/20d horizons, cross-sectional percentile
rank), added peer-return + technical-indicator features, surfaced rank-IC
end-to-end. Details in Problems.md #22–#26.

- Bug fixes: `volume_change_1d` clamped [-1, 20]; winsorization +
  ±scaled_feature_clip_sigma (default 10.0) persisted to scaler stats
  (#23); real split/dividend adjustment via Lean factor files (train-only
  gap; Lean's feed was already correct) (#24); `assess_regression_quality()`
  gate wired into both trainers (#25); sequence window-size compat fix
  (#26); fixed 7 of 10 retraining-worker tests silently running real
  training subprocesses up to ~30 min each (#22).
- Windows widened: validation 2018-01-01→2018-12-31, backtest
  2019-01-01→2021-03-31 (old 3-month validation gave too few non-
  overlapping observations; pre/post backtests deliberately not
  comparable).
- Targets: `target_return/direction_5d/20d`; horizon sibling model
  classes (experts/baseline/gating stay 1d-only); masked loss helpers +
  per-head thresholds avoiding silent always-positive collapse.
- Cross-sectional ranking: `build_cross_sectional_rank_targets()` (per-date
  percentile rank, min universe 10) → `target_rank_5d/20d`; `rank_5d`/
  `rank_20d` heads; Spearman `compute_rank_ic()` with non-overlapping-
  stride variant; informational-only this pass. Promotion criterion
  documented: mean IC > 0.02, t-stat > 2.
- Peer returns: `TopologyNode.top_peers` + `rank_correlated_peers()`
  (`top_peers_n` default 3); offline/runtime emit
  `peer_rank1/2/3_return_1d` + `peer_mean_return_1d`. Dim 48 → 52.
- Technical indicators: shared `features/technical_indicators.py` (rsi_14,
  atr_pct_14, bollinger_pctb_20, volume_zscore_20, macd_histogram_norm,
  dist_52w_high via a 260-bar deque, cs_momentum_rank_20). Dim 52 → 59.
- Full R2 retrain on the final 59-dim set.
- **Verified:** sequence `rank_20d` mean IC 0.073 t=4.40; multitask 0.037
  t=2.10 — first statistically significant signal in project history;
  1d-direction MCC stayed noise throughout. Suite 817 passed (11
  pre-existing Docker-unavailable errors); `tsc` clean; no Lean run.

## Follow-up — rank_20d wired into position sizing

Wires the one statistically significant signal into sizing, off by default.

- `rank_sizing_multiplier()`: bounded, direction-preserving (defaults
  0.75–1.25, median rank = no-op); `PositionSizingDecision.rank_multiplier`.
  `main.py` extracts predicted_rank_20d (sequence-preferred, multitask
  fallback) into dynamic sizing + signal_payload.
- `rank_sizing_enabled` ships `false` honestly: subsample t-stat only 1.20
  vs 4.40 full-series — not yet independently significant.
- **Verified:** +9 tests (disabled/median/top/bottom, cap interaction,
  short-side sign preservation).

## 5/10 → 9/10 frontier-readiness roadmap (Phases 1–7)

Follow-up rated 5/10 since rank wasn't independently significant on the
then-20-asset universe. Seven phases closed that gap plus other
structural weaknesses.

- **P1 Bond sleeve**: universe 20→30 assets (SHY/IEF/TLT/AGG/LQD/HYG/TIP/
  MBB/EMB/MUB registered as `security_type: "equity"`); `features/
  macro_features.py` yield-curve slope (TLT-SHY spread momentum), credit
  spread (HYG-LQD), crypto risk appetite proxies. Dim 59 → 62.
- **P2 Validation rigor**: purged/embargoed folds, non-overlapping eras,
  bootstrap IC CI, `assess_ranking_quality()` code-enforcing
  promotable/watchlist/not_promotable (t < 2.0 fails; CI lower bound < 0
  fails; any sign-flipping era fails). Real bug fixed (#27): era/fold
  functions assumed datetime input but callers pass stringified dates.
- **P5 Sector neutrality**: `sector_mapping.json` + loader ("Unknown"
  fallback); sector-neutral rank targets/head — purely additive.
- **P3 Stage-2 long/short book** (the one deliberate direction-setting
  departure): `portfolio/book_construction.py::build_rank_based_book()`
  (top-N long / bottom-N short by predicted_rank_20d); `main.py::on_data()`
  restructured into two passes; provably byte-identical when off
  (`portfolio_book.enabled: false`). Real short-selling added;
  `max_short_exposure` 0.30. Gap found+fixed: analyzer's six safety tiers
  gated only `{"buy","sell"}`, missing `"short"` entirely.
- **P4 Walk-forward**: rolling/expanding window generation +
  `python train.py --walk-forward` CLI; config gated off; infra verified
  (6 expanding windows from the real window) but the full multi-window run
  (~45 min/window) was NOT executed.
- **P6 Production rank-IC decay monitoring**: experience events gain
  resolved-outcome fields; `performance/rank_ic_monitor.py`;
  `rank_ic_decay_trigger()` registered in planning weights.
- **P7 Live-loop closure groundwork**: paper-readiness scheduler service.
- **Verified:** real retrain (30 assets, 62 features, 46,242 rows):
  `rank_20d` clears its own promotion gate for the FIRST time —
  non-overlapping t-stat 2.52, bootstrap CI [0.035, 0.308], zero
  opposite-sign eras; full-series IC 0.173/t=10.40. rank_5d and
  sector-neutral variants not promotable (era flips). Sequence retrain
  OOM'd ((rows,30,72) tensor) — prior 59-input sequence model stayed
  active and degrades safely. Suite 928 passed; `tsc` clean.

## Follow-up — closing the roadmap's CLI/webui/backend wiring gaps

Audit found backend logic for three phases unreachable from any
user-facing surface; all fixed.

- `rank_ic_decay_trigger()` was backend-only → now fed by the worker every
  cycle (new config: rolling window 100, min mean IC 0.02, min t 2.0,
  horizon 20 days). `aq train --walk-forward` flags added as passthroughs.
- Webui: `{head}_ranking_quality` promotion-gate badges (previously only
  rank_20d shown) and `portfolio_book_role` column; new badge tones.
- **Verified:** +6 tests/extensions; suite 934 passed; `tsc` clean.
  Final rating after this pass: **9/10**.

## Multi-Asset-Class Support — Bonds, Futures, Options + Interactive Brokers Integration

V3's headline scope item: futures/options trading alongside equity/crypto/
bonds with real Black-Scholes greeks and margin-based futures risk sizing
(not a bolt-on to the equity sizer), plus bonds moving to real
yield-curve/duration treatment. IB toggled end-to-end via
`phase_v2.ib.enabled` (default off; system works exactly as before).

- New modules: `data_pipeline/fred_backfill.py` (no-key FRED CSV),
  `features/bond_features.py` (curve level/slope/curvature, credit-spread,
  `empirical_duration_beta()`), `futures_contract_specs.json` +
  `risk/futures_risk.py` (contract-count sizing; `rollover_due()`
  diagnostic-only), `features/options_greeks.py` (BSM,
  Newton-Raphson+bisection IV), `portfolio/options_strategy.py`
  (single-leg, greeks-sized, vega-budget capped),
  `data_pipeline/ib_backfill.py` (dev-only, raises IBNotConfiguredError),
  `risk/asset_class_router.py::route_position_sizing()` (one dispatch
  point), `features/derivatives_macro_features.py` (neutral 0.0 default,
  #29).
- New `asset_class` universe field (distinct from Lean's security_type);
  context one-hot features; `input_set` 30→38 (breaking, retrain required).
  Exposure caps bonds 0.30/futures 0.20/options 0.10. Bug fixed:
  exposure keyed raw security_type counted bond ETFs as equity.
  Futures execute via `MarketOrder(contract_count)`; options order
  placement out of scope (#29). CLI: `aq fetch futures/options`,
  `aq ib status`. Bug #28: book `"short"` signal was silently zeroed.
- **Verified:** new suites (greeks 22, fred 17, bonds 14, futures 19,
  options-strategy 16, ib 26 mocked, router 11, derivatives-macro 15);
  suite 1106 passed. TLT duration beta −0.181 ≈17× SHY's; BS matches Hull
  (call ≈ 4.76), parity exact to 1e-9, IV round-trip 0.35→1e-4. Retrain
  (85-input, 46,242 rows): multitask rank_20d t=3.17, sequence t=2.34;
  every head uniformly `not_promotable` on era sign instability
  (consistent small-sample noise). Sequence OOM'd once alongside Docker.

## Infrastructure/latency pass — `aq test` speed, inference-hot-path profiling, CI Docker cache

Research-first pass (3 explore agents before any code change); writeup #31.

- `aq test` silently ran a REAL `lean backtest .` on every invocation
  (skipif checked binary availability, not intent) taking >1h — fixed via
  the `lean_backtest` marker (excluded by default, opt-in `--lean`) plus
  11 combinable subsystem flags and opt-in `--parallel` xdist. Default
  now 1153 tests in under a minute.
- New `scripts/profile_inference.py`: found and fixed `_conv1d_causal()`'s
  per-timestep Python loop (vectorized gather + batched einsum) and
  batched `main.py`'s 4-expert loop into one numpy call per layer
  (safe fallback on architecture mismatch).
- CI Docker builds gained `type=gha` caching; docs audits (README links,
  `scripts/README`, shared `AQ:TEST_COUNT` markers).
- **Verified:** 448.4s → 290.6s (**−35.2%**) on the harness workload;
  conv1d bit-identical across 200 fuzz trials; 1153 passed. Numba
  evaluated and declined.

## Latency deep-dive follow-up — weight/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension

Re-profiling found `numpy.asarray()` conversions as the largest remaining
cost (#32).

- `convert_state_dict_arrays()` once at load;
  `BatchedLayerStackCache`/`build_models_batched_cache()` precompute
  stacks instead of `np.stack()` per call — zero API/behavior change.
- Profiling harness rebuilt (inputs pre-generated outside the profiled
  region; p50/p95/p99 tail reporting); new `aq profile` command.
- Opt-in per-symbol multiprocessing (`inference_parallelism`, default
  `false`): Pass 1 restructured so inference can run across a persistent
  `ProcessPoolExecutor`. Shipped default-off honestly (~4.8 ms/symbol means
  IPC may exceed any win; Windows spawn inside Lean untested).
- New C++/pybind11 `cpp_inference_ext` accelerating `_linear_batched()`;
  optional path, deferred import, NumPy fallback. Two real bugs found:
  identically-named source folder shadowed the installed extension as an
  empty namespace package; first install went to system Python, not
  `.venv`, making an early comparison measure NumPy twice.
- **Verified:** 448.4s → **48.4s (−89.2%)** from caching alone (mean
  ~44.8 → 4.83 ms/symbol-bar); C++ added −16.7%/−40.9% across two paired
  comparisons (real, modest, noisy).

## Execution/risk realism — real `SlippageModel` wired to fills

The liquidity layer's per-bar impact+spread estimate was computed purely
for sizing/routing and discarded — no Lean security had a slippage model,
and simulated fills used `slippage_bps=0.0` (systematically too-good
fills).

- `order_gate`: `slippage_amount()` / `resolve_slippage_bps()` (clamped to
  500bps) / `resolve_fill_slippage()`; `main._LiquidityAwareSlippageModel`
  adapter attached via `SetSlippageModel()`, per-symbol bps refreshed every
  bar; `enter_long(slippage_bps=...)` populated everywhere.
- Combined impact+spread used (Lean fill has no bid-ask awareness);
  follow-up made source + clamp configurable
  (`phase_v2.liquidity.fill_slippage.{source,max_bps}`).
- **Verified:** 12 new tests incl. byte-identical-vs-explicit-zero parity;
  follow-up +13. See #33.

## Real limit-order support — every tradable asset class, config-gated

Closed the market-fill-only gap at all 5 order call sites
(`phase_v2.limit_orders`, default off).

- Pure functions `resolve_limit_price()` / `classify_order_status()`;
  `main._try_submit_limit_order()` shared router; `on_order_event()` stamps
  cooldown at confirmed-fill time; per-bar stale-order sweep with
  per-class fallback-to-market policy (equity/crypto/bond on;
  future/option off).
- Two sign/keying bugs caught pre-ship: a naive buy-sign transform would
  have flipped correctly-signed futures quantities; option pending orders
  recorded the wrong symbol key.
- **Verified:** 16 new tests; not yet exercised by a real backtest (#34).

## Liquidate positions when an asset class gets disabled (+ 2 stale doc fixes)

Flipping `futures_risk`/`options_risk` off zeroed sizing but never
liquidated pre-existing positions.

- `resolve_asset_class_enabled()` /
  `should_liquidate_disabled_asset_class_position()`;
  `exit_using_last_known_price()`; per-bar sweep anchored after
  `_refresh_risk_state()`. Applies to futures/options only.
- **Verified:** 7 new tests; one real-backtest-only item (#35).

## Extended latency profiling beyond inference — found topology to be a much larger per-bar cost than inference itself

New `scripts/profile_subsystems.py` + combinable `aq profile --<subsystem>`
flags measuring regime, topology, liquidity, gating, analyzer, and
indicator primitives. `_build_model_input()` itself stays unprofiled
(documented choice — its pure indicator primitives are profiled instead).

- Real finding: `build_market_topology()` costs ~500–600ms per call at the
  real ~30-symbol universe — comparable to or larger than the ENTIRE
  per-symbol inference total.
- **Verified:** 14 new tests. See #36.

## Investigated inference tail latency (p99 3-5x p50) — real GC-pause contribution confirmed

- Profile-output discrepancy resolved (machine load, not regression);
  bucket-report ruled out warmup (p50 flat); `--no-gc` isolated GC pauses
  driving worst-case latency (−66%/−95% max tail across two paired runs,
  p50 unaffected). `gc.freeze()` after load documented as candidate knob —
  not implemented (needs real-backtest validation).
- **Verified:** 10 new tests. Writeup #37.

## 2-leg vertical spread selection for options (single-leg stays the default)

Conservative, explicitly-scoped multi-leg support (call/put verticals
only); straddles/strangles/condors/butterflies remain out of scope.

- Additive dataclasses/functions; `select_vertical_spread_legs()` reuses
  the single-leg selector for the long leg; net-vega-based sizing; router
  `spread_strategy` dispatch (default `single_leg`); atomic placement via
  Lean's `OptionStrategies` + `Buy(strategy, quantity)` — avoiding
  hand-rolled sequential-order fill risk.
- Two bugs caught pre-ship: unconditional contract-symbol extraction would
  have rejected every spread; plural tracking dict added rather than
  repurposing the singular one.
- **Verified:** 25 new tests incl. zero-behavior-change parity. Scope
  trade-offs in #38.

## 2026-07-16 — CI root cause found and fixed (#10), per-bar forward-pass latency measured (#21), per-asset-class book-slot caps (#29)

Closed three entries needing real evidence (`gh` CLI + `aq profile`), none
needing a rebuilt image.

- #10 (three independent CI roots): `.gitignore`'s `data/**` excluded two
  hand-authored reference JSONs (exception added, files committed);
  `empirical_duration_beta()`'s exact `variance_x == 0.0` check broke under
  Python 3.14's float-summation change (< 1e-12 tolerance); the Lean
  integration self-skip checked binary presence, not a usable Data folder.
- #21: `aq profile` already simulated the 11-pass bundle — batched
  mean 12.00ms/p99 106ms vs unbatched 8.72/41; sequence encoder dominates
  (~48–58%), flagged not fixed; negligible vs the 90s `initialize()`
  budget.
- #29: `per_asset_class_slots` param (default `None` = pooled behavior
  byte-identical; pooled/per-class share `_select_book_group()`), wired via
  config + `asset_class` on book candidates.
- **Verified:** 19 new/extended; 4 previously-failing tests pass with no
  test changes; suite 1304.

## 2026-07-16 (later) — #10 confirmed green on real CI, full implementations for #36 (topology embedding cache) and #37 (gc.freeze()) shipped, both config-gated off

- Topology embedding cache: skip SMACOF when every pairwise correlation is
  stable within tolerance and the universe is unchanged
  (`cache_enabled: false`, tolerance 0.02). Honest finding: at ~30 symbols
  /25-obs windows the skip essentially NEVER fires at 0.02 (Pearson noise)
  — ships gated off pending real-data validation; new
  `aq profile --topology-cached` workload added.
- `gc.freeze()` once after model load, gated
  (`gc_tuning.freeze_after_load_enabled: false`); still needs real-backtest
  validation of Lean's .NET/Python GC boundary.
- **Verified:** 21 new/extended; suite 1318.

## 2026-07-16 (later still) — final pre-backtest bug sweep, 4 fixes, before this project's first real `lean backtest .` run

- 3 of 11 Lean-coverage assertions read the wrong state key
  (`config.model` vs top-level `model`) — would have silently passed a
  broken backtest. Liquidity thresholds had drifted to the same value
  (0.01), collapsing two tiers to one → thin reset to 0.005.
  `_process_pending_limit_order_timeouts()` contradicted its documented
  status contract (dormant; fixed). `normalize_per_asset_class_slots()`
  added for shape validation.
- **Verified:** 6 new tests; suite 1324. See #39.

## 2026-07-16 (yet later) — pinned the Lean engine Docker image, found live during the actual first backtest attempt

`aq backtest` appeared to hang — it was silently re-pulling the ~42.5GB
engine image because `lean backtest .` resolves mutable `:latest`.

- `PINNED_LEAN_ENGINE_IMAGE = "quantconnect/lean:17900"` (immutable tag
  confirmed via Docker Hub API); `cmd_backtest()` always passes `--image`;
  `aq backtest --image <other>` escape hatch.
- **Verified:** parser tests updated; suite 1326. See #40.

## 2026-07-17 — Docker consolidation: one `aether-quant-engine` image for app + every worker, `aether-quant-` container rename, compose Lean image pinned

- Deleted `Dockerfile.workers`/`Dockerfile.retraining_worker`; one
  `Dockerfile` installing a single requirements file and COPY-ing the
  whole tree — structurally eliminates #1/#2/#20/#30 (all the same root
  cause: per-worker COPY allowlist drift causing ModuleNotFoundError
  crash-loops).
- Compose: app service renamed `engine` (`aether-quant-engine`); workers
  share the image with `aether-quant-<service>` names; `LEAN_IMAGE`
  default pinned to 17900 matching the CLI pin.
- **Verified:** tests updated for the rename; `docker compose config`
  validated; actual rebuild/cleanup left to the user.

## 2026-07-17 — Pre-live security review: `lean.json` credential indirection, secrets out of the Docker image, localhost-only DB, secret-commit guard

Nothing was ever leaked — all findings prospective (#42).

- `aq render-lean-config`: overlays `.env.live`'s `AETHER_*` values onto
  the empty tracked `lean.json` template into a gitignored
  `lean.live.json`; only field names ever printed. `.dockerignore` excludes
  credentials (the `lean.live.json` case caught during verification of the
  fix itself).
- Published DB/Redis ports rebound to 127.0.0.1; fail-closed guard refuses
  live mode on the default dev password. New `aq secrets-check`
  (fail-on-populated-secret scan) + opt-in pre-commit hook.
- Checked clean: no deserialization-RCE surface; FastAPI read-only/
  localhost-CORS; Telegram creds env-var-only; nothing in git history.
  Deferred: audit logging (closed in the next entry).
- **Verified:** 3 new test files + 4 extended.

## 2026-07-17 — Full pre-live model overhaul: rank-driven trading, unblockable exits, and a training-pipeline rewrite that stops shipping the untrained model

A backtest returned bit-identical results to pre-calibration (same 14
orders, same 20.364% net profit) proving the recalibration did nothing.
Two independent bug classes (#43):

- Trading could never exit: position counting missed same-bar submissions;
  the static sell threshold sat ~10σ outside the model's real output range;
  the circuit breaker was neutered by config; protective vetoes blocked
  exits too. Fixes: `portfolio_book` enabled with `rank_20d` driving
  entries; `strategy_mode` enforced (long_flat forces shorts off);
  deliberate long-only mode at `bottom_n==0`; rotation forces sells; new
  Priority 0 — a sell for an already-invested symbol bypasses every veto;
  non-model safety exits (holding-age + trailing stop, on by default);
  adaptive sell threshold (25th pct of rolling probability_up); same-bar
  cap overshoot reservation; breaker re-armed (0.03/0.12), bypass off.
- The model was nearly constant: early stopping monitored validation BCE
  (lowest at epoch 1) shipping near-random models; no degenerate-threshold
  guard; MoE's unconditional 0.25 expert floor pulled outputs to 0.5;
  ranking heads ignored by trading. Fixes: shared `is_new_best_epoch()`
  monitoring balanced accuracy with a 3-epoch floor; threshold search
  positive-rate band; `select_model_context_columns()` collapses 30 ticker
  one-hots to 5 asset-class one-hots (85 → 52 inputs); `min_training_rows`
  50→250; MoE score floors at exactly 0.0 for zero-skill experts;
  validation-gate skill floor; expert gate defaults raised to coin-flip+
  levels.
- **Verified:** full stack retrained and promoted (topology excluded — no
  telemetry): baseline best_epoch 16/34 (was 1/19), positive_rate 0.155
  (was 0.91), sequence rank_20d non-overlapping mean IC 0.2318/t=2.955
  clearing the 2.0 bar. Suite 1392. User's confirming backtest outstanding.

## 2026-07-18 — Operational maturity pass: tamper-evident audit logging, a real end-to-end retraining/rollback rehearsal, and every structural gap the rehearsal itself surfaced

- New `audit/` package: Redis Stream → Postgres → JSON snapshot,
  hash-chained (tamper-detectable via `aq audit-log --verify`); hooked into
  orders, credential loads, live-mode transitions; queryable + webui panel.
  Closes #42's deferred item.
- Real rehearsal (not mocks): seeded events/triggers, let the
  retraining-worker poll loop auto-run plan→…→validate three times against
  real Postgres/subprocesses — all candidates correctly rejected by the
  validation gate. Rollback rehearsed happy-path AND corrupted-hash-refused.
- The rehearsal surfaced 3 real structural bugs (#44–#49): read-only volume
  blocking `train.py`; Redis `xreadgroup(block=0)` perpetual socket
  timeouts in every Stream worker; orphaned retraining-events rows → new
  startup reconciliation marks stale `planned`/`running` rows failed.
- A limit-orders/gc-freeze/spreads verification attempt was blocked by the
  4GB machine (imports alone ~82s under pressure vs Lean's 90s cap, #50).
  One permanent fix regardless: direct import from `audit.redis_queue`.
  Housekeeping: `ml/versions/`/`.av` untracked; tini added to the
  retraining worker.
- **Verified:** 8 reconciliation tests; suite 1465 before+after.

## 2026-07-19 — The rank-pivot roadmap: trading path switched onto `rank_20d`, universe expanded 30→74 and rebalanced across asset classes, four Stage-4 regularization gaps closed

Direct follow-through on #43: direction is noise while rank_20d has skill,
but was being traded far faster than its horizon supports (653 orders,
Sharpe −0.59 / Net −4.6%).

- Trading pivoted onto rank_20d: `long_short` mode, rank sizing on,
  sequence_weight 0.5, book 8/8, spread floor 0.15; explicit 5-day
  rebalance scheduler (`should_rebalance_this_bar()`).
- Universe 30→74 (40 equities/22 bonds/12 crypto); 44 tickers backfilled
  (a real MultiIndex-columns yfinance bug fixed + 2 regression tests);
  dataset 113,804 rows (was 46,242); 63 eligible + 11 observation-only.
- Four regularization gaps closed in both trainers: rank-IC early stopping;
  dead 1-day direction head down-weighted; seed ensembling
  (prediction-averaging + `--seed`); horizon-consistency regularization.
  Also: `purged_cv.enabled` was dead configuration — now actually invoked
  as a diagnostic.
- **Verified:** per-item tests; suite 1497. The empirical retrain was
  still outstanding — a local `--multitask-only` attempt was stopped after
  ~4h wall for ~800 CPU-seconds (350MB free of 3.9GB RAM), confirming #50
  and motivating cloud compute. See #52.

## 2026-07-20 — GitHub Codespaces cloud-training offload, and the rank-pivot roadmap's actual empirical retrain

- Codespaces set up as disposable training compute (`gh codespace ssh/cp`;
  artifacts never through the public repo). Real bug found+fixed: the
  docker-in-docker devcontainer feature silently swaps the base image to
  Alpine regardless of the `image` field (5 systematic A/B rebuilds);
  Docker cannot run inside a Codespace at all — Lean backtests stay
  local-only, only training moved.
- Working config: Debian base + sshd feature + CPU-only PyTorch. All 8
  artifacts retrained end-to-end on the 113,804-row dataset in <15 minutes
  (vs 4+h local that never completed).
- Git-hygiene bug: 9 generated artifact files were still tracked —
  untracked + gitignored.
- **Verified:** early stopping fired as designed; full-series rank_20d
  improved (multitask 0.172/t=7.55, sequence 0.127/t=5.70); the
  non-overlapping significance gate was still NOT cleared (1.40 / 0.43 —
  honest partial). Infra change verified by reproduction, not unit tests.
  See #53; retrain numbers in #52's update.

## 2026-07-20 — First real backtest against the rank-pivot-roadmap models: Sharpe -0.59 → +0.40, and a universe-selection bug found and fixed

- Real bug from the backtest log: BNBUSD/TRXUSD could never subscribe in
  Lean — Coinbase never listed those pairs. Swapped for ETCUSD/ZECUSD,
  backfilled with real rows; universe stays 74.
- **Headline result:** Sharpe −0.59 → **+0.403**, Net Profit −4.604% →
  **+10.438%**, Drawdown 11.1% → 4.0%, Win Rate 47% → 58%. Orders rose
  (653→2,082) but turnover barely moved (7.09%→7.51%), confirming the
  rebalance scheduler works. Disclosed confound: `bypass_safety_gates`
  was flipped on the same session — not a clean isolation. See #54.

## V4 Webui — Overview/Operations split, Tracing reflow, genuinely 3D topology (V4-W1 / V4-W2 / V4-W3)

- W1: seven operational/health panels moved to `/operations`; duplicated
  nav blocks collapsed into a NAV_ITEMS map. W2: Tracing page reflowed
  into two explicit flex columns. W3: `embedding_dimensions` (default 2)
  makes topology genuinely 3D (z = correlation-distance axis); warm-start
  and scene-payload breakages caught and fixed pre-ship.
- Found+fixed (#55): every webui tab except `/` 404'd on hard refresh —
  FastAPI's StaticFiles isn't an SPA catch-all; new `SpaStaticFiles`.
  Logged not-fixed (#56): topology z-offset training still on the old
  scale (latent — no model trained yet).
- First frontend test infra: Vitest + Testing Library; 10 tests.
- **Verified:** 1515 passing; the 2D parity guard passes unchanged
  (zero coordinates moved); lint/build clean; live uvicorn route sweep.

## V4.1 completion — normalized topology z offset, `aq train --topology-only` (Problems.md #56)

- Naive fix (raising the z multiplier) caught as wrong BEFORE shipping
  (would saturate the clamp 20x for some win rates). Actual fix: z emitted
  normalized to [-1,1], multiplied by the active clamp downstream — proven
  identity-preserving in 2D by a byte-identical-output test, 60x more z
  travel in 3D. New `offset_schema` format-identity field; new
  `aq train --topology-only` (skips informatively — needs Postgres
  outcome events that don't exist locally). Overlay remains dormant.
- **Verified:** 1521 (+6); #56 marked fixed.

## V4.3.0 — Functionality: allow adding to an existing position, all 5 asset classes (Problems.md #57)

Exploration found THREE distinct problems, not one gate.

- Equity/crypto/bond were blocked by a stale-signal gate; futures/options
  had NO gate at all (live bug: absolute margin/vega targets fired through
  incremental primitives, silently stacking every bar — reachable only
  with those classes enabled, both default off; options also re-selected
  legs, orphaning tracked positions).
- Tier 1 (unconditional fix): `compute_incremental_order_quantity()` signs
  a delta toward the absolute target. Tier 2 (opt-in
  `position_scaling.enabled`): churn-guarded scale-ups. Tier 3 (own
  `rotate_on_drift` flag): drifted option contracts rotate only if opted
  in. Two Lean sign conventions verified from existing usage before
  writing delta logic.
- **Verified:** 1558 (+37). Defaults byte-identical by construction.

## V4.4 — architecturally-sound options: multi-position book, symmetric scale-down, held-contract sizing, spread combo orders (Problems.md #58)

Closes six architectural gaps from V4.3.0 — code-complete, IB-unverified.

- Held-contract sizers size on current greeks instead of re-selecting from
  the chain; multi-position tracking dict capped per underlying (cap 1 =
  byte-identical pre-V4.4); dedicated single-position liquidation;
  pending-limit-orders re-keyed to order-target Symbols (concurrent
  positions don't collide); at-cap re-pricing bug caught during
  verification (placed orders regardless of the scaling flag).
- **Verified:** 1591 (+33).

## V4.5 — full `OptionStrategies` coverage: all 43 QuantConnect option structures, registry-driven (Problems.md #59)

From 2 of 43 factories to all 43; the 6 arbitrage structures stubbed for a
future mispricing detector.

- Registry of per-strategy specs transcribed from Lean's C# source +
  ~10 shared shape-family selectors; net-vega multi-leg sizing; 3 margin
  sub-models; ordered-priority routing (volatility-gated for straddle/
  strangle/condor/butterfly). Liquidation closes SHORT legs before LONG;
  expiry-day auto-close + covered/protective lifecycle sweeps.
- Transcription bugs fixed: ladder/backspread bounded-unbounded
  misclassifications, expiry drift, debit/credit role inversion,
  √252 annualization at the wrong site, missing margin entries.
- **Verified:** 1656 (+67).

## V4.6 — bounded options follow-ups, arbitrage mispricing detector, Forex/FX, analytic bond-ETF duration/convexity (Problems.md #60)

- Multi-leg positions no longer each count toward `max_active_positions`;
  rotation anti-thrashing cooldown + same-bar netting; optional per-asset
  strategy override; new put-call-parity/box/carry arbitrage detector
  (gated off); Forex fully first-class (`forex_risk.py` leverage-utilization
  sizing + pair specs + midpoint-OHLC quote-bar fallback); analytic
  duration/convexity/DV01 informational bond analytics.
- **Verified:** 1722 (+66). Forex code-complete, IB-unverified, zero live
  tickers configured.

## V4.7 — early-assignment/corporate-action modeling, a learned multi-leg strategy-selector model, and bond analytics wired into the trained model as real signals (Problems.md #61)

Code-complete; the matching retrain deliberately NOT run this pass.

- Dividend-driven early-call-assignment risk scoring (call-only, off by
  default) + Barone-Adesi-Whaley American pricer (verified vs a binomial
  tree); ex-dividend backfill pipeline; option-strategy outcome capture for
  observation mode (zero DDL changes); learned strategy-selector trainer +
  inference (dormant until real option positions exist); the 3 analytic
  bond features added to the model feature list.
- Sequencing risk documented: enabling the config without the matching
  retrain would KeyError every bar.
- **Verified:** 1813 (+91).

## Phase 4.8 — closing the gaps a full-stack completeness audit found: `lean` CLI in the retraining-worker image, a new Options & Strategy webui page, a real `main.py` bug fix, and CLI/Docker discoverability fixes (Problems.md #62)

A 3-agent audit rated V4 7/10; this closes its concrete gap list
(topology training, IB integration, walk-forward, and the real backtest
explicitly deferred to the user).

- `lean` CLI in the production image; retraining-worker got a docker.sock
  mount (Lean launches its own container); compose gained a scoped
  `data/reference/` mount (assets-status was reporting zero specs); new
  `aq backfill <dividends|fred|yfinance>`; stale subsystem-test dict
  missing 4 files fixed.
- Real bug: `corporate_action_payload` was set in Pass 1 but read in
  Pass 2 — every symbol reused the LAST symbol's leftover value; threaded
  through `pass1_state`. Previously-computed-but-never-persisted V4.7
  fields wired into signals. New webui "Options & Strategy" page
  (positions, dividends, selector scores, corporate actions,
  43-strategy catalog, Forex specs).
- **Verified:** 1818; webui 13 tests; build/lint/test clean.

## V4.9 — a major latency-optimization pass across every hot path, prepping the ground for a future HFT fork (Problems.md #63/#64)

Nine priorities, mostly opt-in byte-identical-default, plus one genuine
live bug fix:

- P0 (bug): a "removed" profiling wrapper was still live, synchronously
  writing `model_input_timing.log` every symbol-bar — 45,187 untracked log
  lines found in the repo root. P1 sequence batching across symbols
  (flag-gated). P2 topology-cache tolerance as rolling percentile (null =
  old behavior). P3 per-call chain grouping. P5 non-blocking
  ExperienceQueue push (background thread, soft-drop). P6 real
  ProcessPoolExecutor IPC benchmark (confirms spawn dramatically slower).
  P7 options profiling workload + new `aq profile` flags. P8 architecture
  section separating HFT-fork prep from same-loop wins.
- **Verified:** 1857 (+39).

## V4.10 — pure-function extraction of main.py's exit logic, 4 webui quality fixes, and 15 new forex/FX assets fetched via `aq fetch` (Problems.md #66)

- Non-model exit logic extracted to pure `evaluate_non_model_exit()`/
  `compute_position_exit_tracking_update()` — `main.py` keeps thin,
  byte-identical call sites (verified via static call-graph trace; a
  literal main.py unit test remains impossible). Webui: memoization bugs
  from inline `?? {}` allocations, route-level code-splitting (1.27MB
  bundle split), 2 dead Grafana-era routes removed, 24 new utility tests.
- Forex onboarding: Lean's 10-column bid/ask CSV handled (documented
  zero-spread synthesis preserving real spreads on merge); pair specs
  7→15, all fetched; universe 74→89. `forex_risk` stays off.
- **Verified:** webui 37/37, build/lint clean, zero network in tests.

## V4.10 follow-up — opt-in live (Lean/IB-calibrated) futures margin source (Problems.md #67)

- `phase_v2.futures_risk.margin_source` (`static` default | `live`)
  attached per-security via `SetBuyingPowerModel()` (not globally — avoids
  touching fees/slippage elsewhere); unrecognized values fall back to
  static; continuous-vs-mapped-contract documented as an open gap.
- **Verified:** futures_risk 26 tests (+8); never yet run with a futures
  position sized.

## Backend/latency gap-closing pass — Docker-built C++ accelerator, main.py CI syntax-check, Windows inference_parallelism guard (Problems.md #68/#69)

Closes the 3 findings capping `backend/models/latency` at 8/10.

- Soft-fail Docker step builds `cpp_inference_ext` for the container's own
  Python (the prior local artifact was ABI-incompatible) — any failure
  degrades to the NumPy fallback. `python -m py_compile main.py` added to
  CI (mypy/pyright declined as too noisy against QuantConnect stubs).
  Missing `inference_parallelism` config key added (found `aq config set`
  failing outright); new Windows slowdown warning at pool construction +
  matching CLI warning.
- **Verified:** suite 1899 (cumulative).

## V4.11 — training + optimization phase: full Codespace retrain + walk-forward executed, three latent train.py bugs fixed, primary signal clears the ≥2.0 significance bar (Problems.md #70)

First real Codespace execution of a full retrain + the walk-forward
diagnostic. 8 of 9 model families retrained (topology stayed dormant —
disposable environment, no event store).

- Three latent `train.py` bugs fixed: forex 11-field quote bars couldn't
  parse (midpoint collapse added, matching runtime for parity);
  `add_regime_features()` duplicated every column on empty walk-forward
  frames; manifest KeyError on empty inventories. Plus a stale-data sync
  gap: 4 forex zips were a 2007–2018 vintage wrongly marking EUR/GBP/NZD
  pairs observation-only — re-synced, trainable universe 74→78.
- Several Lean-gated, IB-independent features switched ON ahead of the
  user's upcoming manual backtests (position-scaling, sequence batching,
  topology cache, composite regime score, forex trading, parallelism).
- **Verified:** multitask `rank_20d` non-overlapping t-stat reached 2.028
  (≥2.0 for the FIRST time; progression 1.20→1.40→2.03 as the universe
  grew), bootstrap CI lower bound +0.0065 — both hard gates pass; still
  `not_promotable` overall on era sign instability (2/9 invert). Walk-
  forward MCC mean 0.0259, CI [0.0128, 0.0409].

## Phase 4.12 — decomposing "era-sign instability" into 3 real causes, alt-data (options-implied vol + financial conditions), 104-asset universe, an RL sizing layer, and every remaining non-IB Problems.md item (Problems.md #71)

- Cause 1: degenerate crypto-only weekend cross-sections (255/801 dates)
  forcing ±1.0 rank-ICs → `min_universe_size` 10→20. Cause 2: thin-sample
  era means failing the gate like real inversions → new
  `era_sign_min_abs_ic`/`era_min_observations` knobs (validated: excludes a
  negligible −0.0007 COVID reading while still catching rank_20d's two
  real inversions). Cause 3: `average_correlation` hardcoded 0.0 offline
  (silently disabling the correlated-crash rule) → now sourced from the
  topology layer's real structure.
- Alt-data added (VIX level + term structure, financial-conditions change)
  via the no-key FRED fetcher, lookahead-tested. Universe 89→104;
  `max_active_positions` 15; book 10/10. New offline contextual-bandit RL
  SIZING layer (scales, never replaces; default off). Closed every
  remaining non-IB Problems item — including #70's shutdown hang (pool now
  explicitly shut down; parallelism defaulted back off).
- **Verified:** rank_20d t-stat 2.03→**2.90**, CI lower +0.06 (both gates
  pass with margin); still `not_promotable` (COVID inversion unchanged, a
  second real inversion exposed). Sequence `rank_5d` became fully
  `promotable` for the first time (t=2.32). RL sizing: honest negative
  result (learned reward worse than constant baseline) — ships disabled
  per pre-committed criterion. Docker Desktop was down all session;
  Docker-gated items carried to the next entry.

## V4.12.2 — close every webui/CLI integration gap Phase 4.12 left behind (Problems.md #71)

Backend/CLI were complete; the webui rendered only part of what was now
computed and persisted.

- Sizing-multiplier chips (volatility/confidence/topology/rank/rl);
  RankingQualityGate renders all three rank heads with a per-era
  diagnostic table flagging opposite-sign/thin eras; `state["macro"]`
  finally written (bond/alt-data payloads were computed every bar but
  never persisted) + MacroSnapshotPanel; CLI re-audited clean; 6 READMEs
  updated.
- **Verified:** `py_compile` clean; pytest 1989 (11 pre-existing Docker
  errors); npm build + vitest 46 green.

## Phase 4.12.3 — every remaining Docker-dependent item closed, Phase 4's arc complete (Problems.md #71)

- Root-caused the Docker/WSL2 outage (a stuck installer process wedging
  WSLService in StopPending, preserved across power cycles by Windows Fast
  Startup) — fixed with a genuine restart. Confirmed the compiled C++
  accelerator genuinely links inside the built image (#68).
- Topology overlay trained FOR REAL the first time: 6 clusters from 4,937
  samples (observation-mode backtest shrunk to 3 months to survive the 4GB
  machine; still 52,129 real events — 100× past the 500-event minimum).
  Standing rule adopted: all model training goes through Codespaces,
  never locally.
- RL sizing re-confirmed negative on freshly rebuilt datasets — stays
  disabled. Isolator note at 104 assets: `Initialize()` ~105s (over the
  90s budget) though backtests completed regardless.
- **Verified backtests:** (1) observation run generating the topology
  data; (2) representative full 2019–2021, drawdown enforcement genuinely
  active, no bypass: 3,606 orders, **Sharpe −0.145** (up from −0.313), Net
  Profit +3.41%, fees ($2,769) still consuming nearly all profit. First
  backtest ever with the learned topology overlay active in sizing.
  Nothing IB-independent remained open.

## V5.1 — Cost-aware cross-sectional ranking (Problems.md #72, #77, #81, #83–86)

Rebuilds model + execution around V4's core gap (real gross edge, negative
Sharpe from fees): train for what's actually traded on, make cost explicit
throughout decision/sizing/safety.

- Both trainers optimize a differentiable soft-Spearman ranking loss
  (ListNet variant available) over whole-date batches; AdamW + cosine decay
  + SWA; LayerNorm TCN trunk; rank targets residualized vs market/sector/
  size; per-asset macro-sensitivity betas replace broadcast macro features.
- Expected-net-edge gate vs expected round-trip cost before every trade;
  scale-down-only on thin edge. Fixed: rank heads trained raw [0,1] but
  exported with a leftover sigmoid compressing live predictions to ~[0.48,
  0.75] — invisible to rank-IC (monotone-invariant) (#84).
- Book dollar+sector neutral with hysteresis; sector map 29→104 (#85);
  truncation-by-order fix keeps strongest names under the cap (#86).
  Severe bug fixed: sector-neutralization demeaned whole sector buckets to
  exactly zero, erasing legs (notably one-sided Forex) — offline net Sharpe
  roughly doubled once the short leg was sized again (#81).
- Walk-forward spans six expanding windows; new offline cost-aware rank-book
  simulator (`evaluation/`) mirrors the live path (net Sharpe/turnover/
  capacity/stress/ablation); promotion gate consumes its verdicts.
- New kill switch (rolling Sharpe, drawdown velocity, live rank-IC decay,
  consecutive losses, slippage divergence, model age) tripping the same
  sticky lock as drawdown breaches; position reconciliation; opt-in
  auto-rollback.
- Also fixed: FRED HTTP/2 hang (#79), walk-forward feature-list crash
  (#82), false-positive orphaned-feature report (#80), ~17-min/run test
  regression from an unmocked subprocess test (#78).
- **Verified:** `rank_5d` non-overlapping t-stat **6.0–6.8** across every
  seed/objective — strongest result in project history; rank_20d improved
  but short of the bar; offline net Sharpe positive across all six
  windows. Neither reserved Lean backtest spent yet.

## V5.1.11 — Lean runtime portability and startup boundary

Ahead of spending the reserved V5.1 backtests:

- `aq backtest` defaults to a cached local `aether-quant-lean:17900` image
  (built from pinned `quantconnect/lean:17900`; installs Redis +
  `httpx[http2]`), removing the fragile generated-requirements mount on
  Windows; Windows launcher fixes temp-dir permissions before Lean starts.
- Deferred `performance.evaluate_all_triggers` to the dashboard view —
  prevents Lean's hard startup isolator importing the trigger worker's
  torch stack at module init. Added missing `httpx[http2]` to the image's
  deps despite an unconditional import via `fred_backfill`.
- **Verified:** unit/AST regression coverage for the image path and
  deferred import.

## V5.1.12 — Six critical bugs found before the first V5.1 Lean backtest

Full review of every config value switched on that session plus its
consuming code (#88):

- Net-edge gate measured edge against trade direction (was blocking every
  short); `--calibrate-edge` regressed on the configured horizon, not
  always 1-day (`edge_bps_per_rank_unit` recalibrated 28.22→396.27);
  kill-switch rolling-Sharpe needs a minimum sample; reconciliation now
  compares broker holdings vs FINAL post-sizing intent per Pass-2 symbol;
  slippage-divergence no longer counts overnight gaps as slippage;
  `corporate_action_payload` leak onto other symbols fixed;
  `sector_max_net_weight` 0.05→0.15 so per-name caps are reachable.
- **Verified:** suite 2392. First reserved backtest slot spent here.

## V5.1.13 — First real V5.1 backtest: three critical fixes verified, book-spread bug found and calibrated

Confirmed the riskiest fixes live, but exposed the book trading 3 weeks
then placing ZERO orders for 2.2 years (#89).

- Rolling-Sharpe numerically unstable on near-zero-variance windows
  (mostly-cash → spurious extreme readings stuck tripped) — distinct gap
  from #88's warmup fix. Found `min_rank_confidence_spread` was a never-
  validated guessed 0.2 (offline simulator hardcodes the gate off, so it
  was never exercised); new `aq evaluate --calibrate-book-spread`;
  applied calibrated 0.5014.
- **Verified:** first genuine short executed; zero false kill-switch
  trips; zero false reconciliation breaches. Suite 2412. Honest open item:
  whether the dead-book symptom is actually fixed awaited the second
  reserved backtest.

## V5.2.1 — Closing the offline-vs-live Sharpe gap

Confirming backtest resumed trading but Sharpe −4.2…−4.4 vs offline
+0.26…+2.18 same window — three independent compounding mechanisms (#90).

- Confirmed ~1-bar execution lag never modeled offline (daily orders fill
  next bar's open; MarketOnClose lands later — structural). Simulator gains
  opt-in `entry_lag_bars`; `--rank-book` shows 0 and 1 side by side.
- Position-scaling machinery re-fired every bar for book members,
  independent of the rebalance cadence → gated to rebalance bars for
  book-selected symbols only (full exits untouched).
- Cost gate sized against full target value instead of the incremental
  resize delta (systematically under-costing small resizes) → sized against
  the real delta; flips cost more. Commission floor added to simulator.
- **Verified:** suite 2428. Gap closure not promised — lag is structural.

## V5.2.2 — Book-history diagnostic + reconciliation CLI

The confirming backtest (−4.421) showed the fixes did NOT close the gap;
six indirect hypotheses tested and ruled out → build reusable ground truth
instead of another one-off.

- Opt-in backtest-only `visualization/book_history.jsonl`
  (`phase_v2.diagnostics.book_history.enabled`) logging actual selections
  per rebalance date via `build_book_history_record()`; new
  `aq evaluate --reconcile-book-history` re-derives scores offline and
  reports per-date overlap/role mismatches/score-weight deltas to
  `ml/evaluation/book_history_reconciliation.json`.
- Real bug: `build_sequence_windows()` windows by ordinal position not
  calendar dates → `select_context_date_range()` computes the correct span.
- **Verified:** 286 passed across touched files. Purely diagnostic round.

## V5.2.3 — Full-universe snapshot, hysteresis replay, webui integration

First real run (2026-08-07, 112 rebalance dates) surfaced two unexplained
findings (#91): crypto/FX appear OFFLINE on 107/112 dates but in the LIVE
book on 0/112; equities-only mean overlap just 54.8%.

- Opt-in `include_full_universe`: logs EVERY symbol with a bar that date
  (score/readiness/reason/eligibility/type) — not just selected members.
- `--replay-hysteresis` carries held allocations forward like the live
  book, distinguishing real divergence from correct incumbent-holding.
  Per-security-type summary; evaluation JSONs served via `/api/evaluation`
  with webui panels.
- Update (2026-08-08 fresh backtest): byte-identical Sharpe/order-count/
  OrderListHash — the logging is a true no-op. Crypto/FX absent from
  `signals` on all 112 dates = bar-delivery problem, not low scores.
  `bar_index` running ~2× the trading-day rate (suspected per-asset-class
  Slices) — not fixed this round.

## V5.2.4 — Fixing bar_index inflation, the empty-book liquidation bug, and making crypto/FX book-eligible

- `self.is_equity_session_bar` gates the single `bar_index` increment —
  fixes every downstream consumer automatically (cadence/cooldowns/
  holding-age exits/rotation/limit timeouts). Kill-switch trackers move to
  equity-session cadence (`evaluation_bars: 60` becomes a real ~60 days,
  was effectively ~30). Second bug: empty book force-sold everything for
  ANY reason → `should_exit_non_selected_book_symbol()`. Phase 1a stops
  skipping symbols lacking a fresh equity-session bar when accumulated
  window history exists (last-known OHLCV snapshot); buffer appends stay
  fresh-gated.
- **Update (2026-08-09 backtest):** rebalance gap 10.29 business days
  matching config (was 5.2); orders ~halved (392), fees halved ($372);
  all three security types in the snapshot; 189 non-equity selections.
  Sharpe −4.103 (from −4.421) — improved, gap not closed.

## V5.2.5 — Fixing the live-vs-offline `bond_empirical_duration_beta` mismatch

Ruled out price drift (byte-identical data) and scaler mismatch (~1e-15);
confirmed one root cause.

- Offline computes the OLS duration-beta once over full history and
  broadcasts it; live recomputed per bar from a rolling 260-bar deque — a
  continuously-drifting input. Corroborated by recurring bond ETFs in the
  mismatch lists. Fix: `should_lock_in_duration_beta()` caches/locks the
  value permanently once both windows clear 260 bars. Also: `cs_momentum_
  rank_20` reimplemented locally in train.py confirmed bit-identical, then
  rewritten to call the shared function anyway.
- **Verified:** fresh real backtest Sharpe −4.103→**−3.351** (~18%) — but
  overlap did NOT confirm cleanly (independent 49.3→48.1%, hysteresis
  53.8→50.0%; bonds flipped sides rather than disappearing). Reported as
  mixed, not clean closure. The five-ticker divergence thread stays open.

## V5.2.6 — Fixing the crypto/FX execution-path bug and closing the live-vs-offline risk-gate gap

Deep-dive found two dominant mechanisms: crypto/FX orders never actually
execute, and live carries ~10 risk gates with zero offline counterpart.

- Finding 1: forex midpoint bars hardcode `volume=0.0` and the liquidity
  veto keys on exactly that — every forex order vetoed; a live BTCUSD bar
  also showed volume 0 (Lean/Coinbase delivery quirk), so V5.2.4's
  eligibility was phantom in practice. Fix: `zero_volume_fallback_ddv`
  (forex always; core-tier crypto BTC/LTC only) + per-symbol bar counter.
- Book-selected confidence threshold split from the general one; new
  `--calibrate-confidence-threshold`: general threshold 0.0968 APPLIED;
  book-selected 0.8925 deliberately NOT (methodologically circular — book
  selection is already an extreme-rank filter).
- Risk-off override severity floor set from a real replay of severity
  tiers (applied 0.55 via a None-sentinel; a naive 0.0 default would NOT
  have been safe). `book_member_decisions` logged per member, write
  deferred until after Pass 2 (+ diversion summary in the reconcile CLI).
- **Updates:** first attempt crashed on stale gating (fixed with
  `book_history_should_log_this_bar`); successful run Sharpe **−2.984**
  (from −3.351), 437 orders. Diagnostics surfaced two more bugs → V5.2.7.

## V5.2.7 — Fixing the forex order-sizing bug and the sticky kill-switch lockout

Both surfaced by V5.2.6's own diagnostic.

- Forex lots: notional at realistic 4-12% weights ($4k-$12k) never reached
  one 100k lot → always rounded to ZERO orders (6 allocations reached
  "trade", silently produced nothing). Fix: `compute_forex_order_units()`
  converts weight straight to whole base-currency units (Lean takes raw
  units, not lots) + opt-in sizing diagnostic log.
- Sticky lockout: ONE trip (2020-02-27) locked the entire book for 13+
  months — 40.4% of decisions reached "trade" before it, 100% forced
  `reduce_risk` after. Split the bundled bypass into independently
  configurable `bypass_sticky_trade_lock` / `bypass_regime_drawdown_gate`
  (legacy key still ORs into both with a one-time nudge); only the sticky
  bypass enabled this round. `evaluate_kill_switch()` untouched.
- **Update (2026-08-11 backtest):** both confirmed live — Sharpe −2.984→
  **−2.17**, 220 real forex fills across 9 pairs for the FIRST TIME EVER,
  `notional_ratio` within 0.15% of 1.0 across 193 records; kill switch now
  trips 26 separate times, clearing each session (26-trip cadence flagged
  as a new open sensitivity question). Reconciliation overlap moved
  slightly against — consistent with its established unreliability.

## V5.2.8 — Closing unnecessarily-open Problems.md items and continuing the live-vs-offline gap investigation

Two-stage patch. Stage 1 closes stale non-IB items (doc corrections:
Forex fully live; bond-schema caveat already closed by #70;
CancelPending classified pending — precision, zero behavior change).

Stage 2 continues #91–#93:

- `evaluation/kill_switch_replay.py` + `aq evaluate --replay-kill-switch`:
  day-by-day offline replay of the kill-switch state machine, explicitly
  approximate. Sensitivity sweep (20 combos): lockout is near-binary —
  either never happens or locks ~58-74% of the remaining 2.2 years
  regardless of exact threshold. No config change applied.
- Optional gate-aware training weight
  (`compute_gate_friendliness_weight_by_date()`) from the same stateless
  topology/regime-severity gates the analyzer uses; threaded as optional
  `date_weights` (None-default, byte-identical), behind
  `gate_aware_ranking_weights.enabled: false`.
- Reconciliation re-run vs the real log: the five-ticker divergence still
  recurs; the cross-asset-sensitivity lead ruled out (identical lookback).
- **Verified:** 33 new tests (2523→2556). Codespaces smoke (flag on,
  3 epochs): trainers ran clean; full walk-forward pipeline ran end-to-end
  (net Sharpe mean 0.78, 5/6 positive) — mechanism sound, NOT a verdict
  (no production epochs, no control arm). See #94.

## V5.2.9 — Full-scale production retrain with gate-aware ranking weights, promoted to active `ml/`

Real full-epoch (120/60) round: flag ON, candidate promoted to active
`ml/` after backup; RL sizing re-evaluated; full walk-forward. Topology
excluded (needs real Lean events through local Postgres).

- **Verified:** vs prior (2026-08-04) production model — rank_5d IC
  0.097→0.109 (t 5.99→6.33), rank_20d 0.152→0.173 (t 9.24→10.28);
  direction MCC regressed (0.026→0.016). Dataset refresh and flag changed
  together — gain judged net positive (book selection is IC-driven). RL
  negative reproduced a third time (stays disabled). Walk-forward: MCC
  mean 0.0221 stable; rank_20d_ic mean 0.0849, 0% sign flips; net Sharpe
  ~0.65, 5/6 windows positive. See #95. Representative Lean backtest left
  to the user.

## V5.2.10 — README Backtest Results split into Lean/Offline Evaluation/Walk-Forward/Other Metrics/Disclaimer, all auto-updating

V5.2.9's real Lean backtest (Sharpe −1.72) plus the offline cross-analysis
surfaced numbers worth keeping visible, not chat-only.

- README Backtest Results split into five auto-regenerating subsections
  (compact tables + foldable detail blocks), replacing a stale
  Phase-4.12-era caveats block; TOC/CLI Reference updated.
- `generate_evaluation_report.py` wired into evaluate/backtest exit points
  (marker-replace, never-fail contract); per-model-suffixed artifact copies
  fix a real clobbering bug (evaluating multitask after sequence destroyed
  sequence's numbers); `kill_switch_replay.json` finally surfaced in the
  webui; Other-Metrics shows REAL kill-switch trips parsed from the Lean
  log next to the offline estimate.
- **Verified:** 15 new tests + 16 updated (the README-refresh mock caught
  during development would otherwise let the SUITE overwrite the real
  README). Suite 2574. Numbers on the page: Lean −1.72 vs offline
  +1.52/+1.33 vs walk-forward +0.65; reconciliation 24% mean overlap,
  0/174 exact matches, 870/1464 diverted; kill-switch 0 real vs 78
  estimated trips — replay is a deliberate over-estimate, not a bug.

## V5.3.1 — Limit-order docs/testing/tooling (#34) and book-history reconciliation bugs (#91), closed as completely as possible without a live Lean run

Deep research (5 parallel passes) + direct verification. No live Lean run
— everything below offline.

- `phase_v2.limit_orders` had actually been ON by default all along (docs
  said otherwise — corrected); future/option fallback asymmetry found
  deliberate (plan corrected, no change). Timeout logic extracted pure so
  the PartialFilled path is unit-testable. New offline diagnostics:
  `--simulate-limit-fills` + `scripts/order_events_audit.py`.
- Warm-up floor raised 21→260 bars closes a cold-start duration-beta gap
  V5.2.5 didn't reach. Reconciliation reads real per-date
  `trading_eligible` instead of hardcoding True.
  `summarize_universe_presence_by_symbol()` made run-segmented — the
  "FX/crypto absent 32%" finding was one old contaminated run diluted by
  newer ones, not a live bug. Real-trip counter returns honest None (the
  audit event is Redis-only; it was counting a text log that can't contain
  it).
- **Verified:** 37 new tests (2574→2609); fill-rate sanity-checked against
  real order events (82.95%; exact 23/23 cancel pairing across 43 folders).
  Sector-neutrality hypothesis for the five tickers ruled out by direct
  code proof.
- **Update (2026-08-14 real backtest, Sharpe −1.034 from −1.72):** the
  warm-up fix confirmed live. An apparent severe regression was itself a
  contamination artifact ("prior" file was an undiscovered 7-run cumulative
  log) — self-caught, documented in #98. See #96/#97/#98.

## V5.3.2 — Root-causing #91/#97 (NVDA/GE/WFC/XOM/BA divergence) and #98 (confidence-spread disengagement gap)

In-depth pass (3 agents + direct analysis, no live run). Closed #98 as
genuine model behavior; found two real reconciliation-tooling bugs —
neither explains the divergence, but the evidence sharpens.

- #98 closed: the trainers' own per-era diagnostics show ALL FOUR
  model/head combinations collapse to insignificant IC in exactly Apr-Sep
  2019 — a genuine no-edge stretch; the spread gate works as documented.
  Regime/drawdown and sticky-lock alternates directly ruled out.
- Run segmentation extracted and wired into the reconcile CLI (defaults to
  most-recent run only; 92% of logged dates recur across runs — silent
  cross-run merging eliminated). Tie-break order now matches live's
  configured universe order, not pandas row order. Reported-not-applied:
  spread recalibrated against the current head = 0.2901 vs live 0.5014.
- **Re-measured:** matched-day raw-score deltas are large (0.11–0.21) and
  strongly directional (live selects, offline doesn't, ~4-5:1) — pointing
  at a real feature/data computation discrepancy for these 5 tickers
  specifically, not a boundary artifact. Suite 2624. See #98/#99.

## V5.3.3 — Root cause found and fixed for the NVDA/GE/WFC/XOM/BA divergence (4 of 5 tickers); confidence-spread recalibration applied

V5.3.2's lead traced to a genuine, undiscovered data gap: 63 of 77 equity
tickers had NO local Lean split/dividend factor file — offline trained on
raw UNADJUSTED prices while live was always adjusted by Lean.

- New `data_pipeline/factor_file_backfill.py` derives real Lean-format
  factor files from yfinance corporate actions; run for real (63 files,
  zero failures); dataset regenerated automatically. Spread recalibrated
  against the CORRECTED dataset (0.2831, close to pre-fix 0.2901 —
  calibration stable) and APPLIED to all three config locations this time.
- Separate real bug (#101): `--all`'s non-JSON output used a literal Greek
  Δ outside cp1252 — every such run had been crashing mid-command since
  Aug 13, silently leaving sections stale. ASCII one-liner.
- **Verified:** mechanical fix proven on real data (GE spinoff correction
  matches its 1.04 factor to two decimals). Divergence re-measured: XOM
  93→65%, WFC 78→71%, GE 52→47%, NVDA 69→59% (second-order shift from the
  other 62 tickers' corrected scores); BA flat (plausibly swamped by 2020
  vol). Live behavior changes ONLY via the recalibration — the factor fix
  touches retrains/offline ground truth only. Offline numbers refreshed:
  multitask net Sharpe UP 1.33→1.68, sequence DOWN 1.52→1.00 (some prior
  edge plausibly rode the dividend-dip artifact). Suite 2638. See
  #100/#101.

## V5.3.3 real backtest verification (2026-08-17) — factor-file fix confirmed strongly live; confidence-spread recalibration regressed Sharpe

User's real run (2019-01-01→2021-04-02, ~6.8h) tested both changes — clean
single-variable A/B (the factor fix never touches the live path; only the
recalibration does).

- Orders 230→695, unique trading days 130→360 (lower threshold
  re-engaging, as predicted). **Sharpe regressed: −1.034→−1.798**, Net
  Profit −1.60%→−5.51%. Root-caused: it traded through 111/~124 days of
  the KNOWN no-skill era (Apr-Sep 2019) plus two weak/negative-IC 2020
  eras. Dispersion-percentile calibration cannot distinguish
  "differentiation exists" from "differentiation is correct."
- Factor-file fix confirmed STRONGLY live beyond offline estimates: GE
  52→15%, BA 48→12%, NVDA 69→25%, WFC 78→55%, overall overlap 56.9%
  (best of the investigation). XOM: 100% mismatch but only 9 appearances
  — flagged, not concluded.
- Recommendation: reconsider/partially revert the spread value; keep the
  factor fix. See #102.

## V5.3.5 — Rolling trailing-IC gate addressing #102's recommendation; wired into `main.py`, shipped disabled pending a real backtest

Builds exactly what #102 asked for: an independent second book-engagement
veto based on trailing REALIZED rank-IC, plus offline calibration/replay
tooling deriving its threshold from real data before ever touching the
live path. Ships `phase_v2.rolling_ic_gate.enabled: false`.

- `evaluation/rank_ic_core.py`: torch-free extraction of the IC math
  (originals become re-exports, suites pass unmodified) avoiding the #16
  isolator-import failure class. `portfolio/rolling_ic_gate.py`: pure
  `compute_rolling_ic_state()`/`evaluate_rolling_ic_gate()` — deliberately
  separate from the dispersion check and from kill_switch's dormant
  differently-scoped condition.
- Additive `None`-default params (`rolling_ic_gate_result`,
  `veto_reason_out`) instead of a return-type change (6+ callers); new
  `gate_veto_reason` field; book-history now writes on EVERY genuine
  rebalance bar even when vetoed-empty (previously zero trace — true since
  V5.2.4 for the old gate too). Live event buffer + gate wired in
  `main.py`; calibration + replay CLIs mirror existing discipline.
- Real bug found+fixed via the gate's own checkpoint: thin origin dates
  (2-3 resolved names) mathematically force ±1 IC dominating the low tail
  → `min_names_per_date` (tools/config use 10), which exposed a second
  bug: `min_resolved_dates_required=40` became structurally unreachable
  (plateau 22-24) → lowered to 20. After both: era_0 0% disengaged, bad
  eras 22-37.5% — concentrated correctly.
- **Verified:** 60 new tests; suite 2638→2688; calibration + replay run
  against real data (see #103); all-runs reconciliation unchanged. No
  Lean run this round — user's manual run is next.

## V5.3.5.3 — Workstream B shipped (XOM feature-level diagnostics); rolling-IC gate's first live test written up; chronic shutdown hang investigated and probed

Three threads, none touching trading behavior: (1) Workstream B from the
V5.3.5 plan — XOM feature-level plumbing (#91/#100 lineage) — built and
tested; (2) the previously undocumented 2026-08-19 real backtest
(`backtests/2026-08-19_13-33-56`, the rolling-IC gate's first live test)
written up (#103); (3) the "endless loop" from commit c2ed98c investigated
and instrumented (#104).

- Workstream B shipped: adopted `evaluation/feature_reconciliation.py`
  (one real bug found by the new tests on adoption day itself: the summary
  aggregator counted whole delta dicts as feature names — fixed);
  additive allowlist-bounded `feature_snapshot` field on
  `build_book_history_record()` (defensive-copied); two flags under
  `phase_v2.diagnostics.book_history` (`include_feature_snapshot` /
  `feature_snapshot_symbols`) captured at main.py's write site via
  ticker-matched `base_features`; new CLI
  `aq evaluate --reconcile-features --symbol XOM` — pure log-vs-dataset
  diff (no models), run-segmented, not in `--all`.
- Tests: new `tests/test_feature_reconciliation.py` (14) + extensions to
  portfolio-construction and CLI tests (+6); registered in
  `_SUBSYSTEM_TEST_FILES`. Suite 2688→2708, badge refreshed. Manual dry-run
  vs the real cumulative log degrades cleanly (exit 0).
- Rolling-IC gate's first live test (backfilled from 2026-08-19, #103):
  Sharpe −1.832 vs the −1.798 baseline — NO recovery — while orders fell
  695→462 and `rolling_ic_below_floor` out-vetoed the old gate 106:21. The
  gate works; what it lets through isn't profitable either. Config left
  unchanged per user decision.
- Shutdown hang (#104): chronic (72/78 teardown-reaching runs back to May
  2026), post-results only, strictly tied to NORMAL completion (both clean
  exits were mid-run error terminations). Inference pool exonerated; no
  other thread creators in the live path. Shipped a `shutdown-probe:`
  Debug dump of alive threads in `on_end_of_algorithm()` — next backtest
  names the culprit.

## V5.3.6 — Feature-parity audit: scaler artifact verified exact, NO live-path formula drift (XOM-class ruled out for OHLCV families); crypto zero-volume root cause narrowed to Lean quote-bar delivery

**Summary:** Built the permanent train-vs-live feature-parity audit (#105): pure core + CLI driver + 15 tests. On real data (163,227 rows x 104 assets) the shipped scaler artifact reproduces every stored scaled column exactly wherever replicas see the same bar sequences; all residual deltas positionally attributed to warmup/hole artifacts of auditing against a post-processed dataset. Cross-cutting findings: per-ticker OWN-calendar momentum is mandatory (union pivots provably wrong, TLT 78% rows), cross_sectional_momentum_rank's NaN-in-denominator semantics pinned, most families flow through shared features/*.py functions. Side results: crypto zero-volume narrowed to Lean quote-bar delivery for BTCUSD (source zips clean); Initialize() static audit shows no heavy ML imports at module scope; #104 thread-site enumeration finds no unaccounted non-daemon creator in our code.

**Shipped:** evaluation/feature_parity.py; scripts/feature_parity_audit.py (+ ml/evaluation/feature_parity_report.json); tests/test_feature_parity.py (15, registered in _SUBSYSTEM_TEST_FILES under evaluation).

**Verification:** suite green for new files; driver OVERALL report committed with positional classifications and analysis notes.


## V5.3.6 completion — WS-B/D/E/C analyses banked; first fully-synced Codespace retrain pulled back (not promoted)

**Added:** scripts/gate_sweep.py + promotion_gate_null_calibration.py + overlap_vs_sharpe_analysis.py with JSON results under ml/evaluation/; Problems.md #106 records the numbers: offline book net Sharpe +1.497; IC floor 0.05 doubles bad-era disengagement at zero era_0 cost offline; kill-switch zero offline trips at every grid point (live-only sensitivity); null calibration shows the t>=2 bar is genuine (2.75% FP) while era-flip blocking is not (66% of noise runs flip >=2 eras - real model flips only 1). Codespace round-trip executed end-to-end via scp -F route (gh cs cp broken): full pipeline trained on synced tree, artifacts parked in ml/versions/codespace_v536_20260823/ pending user promotion decision.


## V5.3.7 completion — era_rule flip_fraction shipped + full retrain promoted; promoted multitask offline net Sharpe 1.68; walk-forward infrastructure-blocked (documented)

**Shipped:** era_rule gate selector + tests (6); extended null study under the gates own 90-day scheme (promotion_gate_null_gate_scheme.json: null flips ZERO, real 0.222 -> strict criterion validated, fraction knob calibrated context recorded). Full Codespace retrain with rule active (baseline+experts exit0; gating/multitask/sequence via --version-id v537cs20260823 after fixing bare-invocation exit-2). Promoted unconditionally per user: backup ml/_backup_pre_v537/, 12 artifacts + expert_models promoted. Offline eval of promoted multitask rank book: net Sharpe 1.6805/1.6933(lag1), +10.61% return, -2.63% maxDD. Sequence: 0.997/0.955.

**Blocked:** walk-forward died at window 5 in three consecutive configs due to Codespace VM reboots (uptime evidence per attempt; swapon prohibited) - partials preserved under ml/versions/v537cs20260823/ml/versions/walk-forward-*; relaunch ready when infra allows.


## V5.3.8 — Monte Carlo simulation testing layer: aq evaluate --rank-book --monte-carlo with auto-refreshing README section (1000-run curves chart, red average line, foldable deep stats)

**Shipped:** evaluation/monte_carlo.py (stationary block bootstrap / iid; seeded; pure numpy) + CLI flags (--mc-runs/--mc-block-size/--mc-seed/--mc-method) writing ml/evaluation/monte_carlo.json + monte_carlo_curves.npz + generate_evaluation_report.py rendering the new README subsection between Lean Backtest and Offline Evaluation: all-run equity chart (faint blue, red average line) auto-regenerated every evaluate run + foldable percentile/deep-stats block. 9 dedicated tests; suite green.

**First real run:** promoted multitask book resampled 1000x -> final return p5/p50/p95 -2.00/+9.38/+21.45%, P(neg)=9.5%, maxDD p95 9.11%.


**V5.3.8 webui addendum:** MonteCarloPanel on the Evaluation page (SVG avg curve + p5/p95 band, percentile table, loss probability), monte_carlo served via /api/evaluation, TS types added; vitest 100/100 (23 files) incl. 4 new panel tests, tsc + production build clean.


## V5.3.9 — Deep GitHub Actions testing suite: win+ubuntu pytest matrix with 80% coverage gate, ruff lint job, vitest in CI, CLI smoke battery, actionlint, workflow meta-tests; non-blocking tag-release visibility

**Shipped:** ci.yml rewritten to five jobs (python-tests matrix with --cov-fail-under=80 calibrated from the measured 82% baseline + coverage.xml artifact; python-lint running the newly adopted ruff E/F ruleset - 604 pre-existing findings triaged to zero; webui-tests now executing the full vitest suite before build; cli-smoke editable-install battery incl. aq secrets-check; workflows-lint via actionlint). release.yml gained a deliberately NON-BLOCKING tag-tests job so tagged releases always proceed while gaps stay visible on the run. tests/test_ci_workflows.py pins the entire structure (7 meta-tests). Coverage config standardized in pyproject.toml.

**Verification:** ruff clean; full suite 2751 passed / 11 deselected including all new meta/edge tests.


## V5.3.10 — CI regression fixes (requirements parse meta-test, pinned actionlint), aq test --ruff flag, main.py extraction batch #1

**Shipped:** Fixed two CI regressions from V5.3.9's ci.yml rewrite (corrupted requirements-dev.txt line + fragile actionlint PATH-append pattern). Added aq test --ruff flag (lint gate before pytest). main.py extraction batch #1: midpoint_bar_from_quote_bar + pad_sequence_history extracted to data_pipeline/bar_synthesis.py with thin main.py delegations.


## V5.3.11 — CI python-lint fix (bare ruff, no editable-import chain) + pip-audit dependency-CVE scanning job

**Fixed:** python-lint job reverted to bare `ruff check .` (the `aq test --ruff` invocation required importing pandas via the aq_cli module chain, but the lint job intentionally runs in a minimal environment without full deps). Duplicate py_compile step removed.
**Added:** dependency-audit job running pip-audit against both runtime and dev requirements files on every push/PR - catches known CVEs before release.


## V5.4.1 — RL sizing asymmetric reward fix (root-cause of 3× honest negative), regime conditioning, auto-rollback dry-run + degradation score, prediction provenance counters

**RL sizing:** compute_action_reward() gained asymmetric_penalty_weight (>1.0 penalizes foregone profit on winners); RL_SIZING_STATE_KEYS gained regime_trend_bullish/bearish/sideways one-hots for regime-conditional policy learning. 6 tests. Codespace retrain ready but not yet executed.
**Auto-rollback:** rollback_hardening.py with compute_degradation_score() (continuous 0-1) and select_rollback_target_dry_run(). 6 tests.
**Prediction provenance:** per-session sequence-vs-multitask counters logged at shutdown. Tests pending Lean runtime.


## V5.4.2 — Critical missing-import fix (bar_synthesis), parity tests, pre-backtest audit, pip-audit job

**Critical fix (#113):** V5.3.10's extraction of midpoint synthesis + sequence padding to data_pipeline/bar_synthesis.py never added the import to main.py → NameError crash on forex path + silent sequence-model death. Fixed + 5 parity tests added.
**CI fixes:** python-lint reverted to bare ruff (aq test --ruff requires full deps); duplicate py_compile removed; pip-audit dependency-CVE scanning job added.
**Verification:** 2769 tests green; config validated for backtest readiness.


## V5.4.2 — Almgren impact model, residual demotion documented, pre-backtest audit clean

**Shipped:** evaluation/impact_model.py (Almgren sqrt-impact formula); integrated into rank_book_simulator as optional cost layer (phase_v2.costs.impact_model, default off). Residual_rank_20d documented as non-promotable (#112) and explicitly demoted in config.json.
**CI fixes:** python-lint reverted to bare ruff (aq test --ruff required pandas import chain); pip-audit dependency-CVE job added; duplicate py_compile removed.


## V5.4.3 — Factor-neutralization check, HRP allocation, benchmark comparison baselines, README restructure; CI registration gap fixed

**Shipped:**
- `evaluation/factor_neutralization_check.py::compute_factor_exposure()` — OLS regression of book returns onto market/momentum factors reporting alpha Sharpe, R², loadings, and per-factor variance contribution. Pure numpy/pandas.
- `portfolio/hrp_allocation.py` — Hierarchical Risk Parity (López de Prado 2016): scipy Ward linkage on correlation distance → quasi-diagonal ordering → recursive bisection by inverse-variance → weights summing to 1.0.
- `evaluation/benchmark_comparison.py` — momentum top-N, mean-reversion bottom-N, and random-entry baselines on the same dataset/window for edge-vs-benchmark context.
- CI: `test_impact_model.py`, `test_v543_new_features.py`, `test_bar_synthesis_parity.py` registered in `_SUBSYSTEM_TEST_FILES` (subsystem-mapping guard caught the gap).
- README restructured: Continuous Integration section moved above Open Source Files and linked from main TOC; Monte Carlo visual description updated to explicitly mention light blue semi-transparent individual-run lines.

**Verification:** 2790 tests green (up from 2757); ruff clean; vitest 100/100; production build clean.

## V5.4.4 — Public benchmark baselines (SP500/60-40), HRP integration into the live book-sizing path; CI python-lint fix; Monte Carlo README visual fixed

**Shipped:**
- `evaluation/public_benchmarks.py` — public benchmark baselines from the universe's own proxy columns (zero new data dependencies): `compute_sp500_baseline()` (buy-and-hold SPY, close-to-close) and `compute_60_40_baseline()` (60% SPY / 40% TLT, daily rebalanced). Same `close_pivot` input and Sharpe formula as `benchmark_comparison.py`'s baselines; output shape matches (`strategy`/`net_sharpe`/`total_return_pct`) plus an additive `status` field — a universe without SPY/TLT degrades to `SKIPPED: <reason>` (None metrics), never a crash. `pct_change(fill_method=None)` so NaN closes can't fabricate flat 0% days.
- HRP into the live path (Phase 2 of the plan): new pure `portfolio/book_construction.py::apply_hrp_weights(book_allocations, returns_by_symbol, gross_exposure)` (+ `pct_returns_from_closes()` helper) — re-weights the ALREADY-SELECTED book symbols with HRP inverse-variance weights; selection untouched, sizing only. Config: `phase_v2.portfolio_book.allocation_method: "rank"` (default, byte-identical) | `"hrp"`. `main.py` wiring on rebalance bars only: return history from each selected symbol's rolling 25-bar `self.symbol_windows` deque (user-accepted); HRP weights feed `apply_book_neutrality()` as raw input when neutrality is on, or populate `self._book_target_weights` directly when off (Pass 2's `.get()` consumes either). Unrecognized `allocation_method` values degrade to `"rank"` with a Debug line. scipy import kept lazy inside `apply_hrp_weights()` so the default path never pays it (Problems.md #16 isolator-timeout class).
- `portfolio/hrp_allocation.py::build_hrp_allocation()` single-sided fix: the unconditional gross/2-per-leg split silently halved a long-only book's exposure (`long_flat` is the shipped default strategy_mode). Two-sided books unchanged (±gross/2); single-sided books now give the present leg the full gross.
- CI python-lint fix (Problems.md #114): removed the two ruff findings V5.4.3 shipped — unused `next_date` (`benchmark_comparison.py`, F841) and unused `fcluster` import (`hrp_allocation.py`, F401, hoisted `leaves_list` to module scope).
- Monte Carlo README visual fixed (Problems.md #114) — root cause was NOT staleness: `update_readme_evaluation_sections()` rendered `MONTECARLO_CHART_PATH` (the real repo PNG) from whatever `EVALUATION_DIR` contained, and a test suite fixture (`runs_curves=np.ones((10,2))`, degenerate 2-point/flat-runs render) monkeypatched `EVALUATION_DIR` without the chart path — **every full test-suite run silently overwrote the real chart with the fixture render**. Fix: chart now renders only when refreshing the real `README_PATH` (resolve-guard); offending test spy-asserts no render on tmp readmes; new hermetic test covers the real-README render path; chart regenerated — all 1000 individual runs now visible as light blue lines under the red average; `Axes.plot`-intercepting regression tests pin the behavior.
- Same-bug-class fix (#114 Problem 2b): `test_aq_test_ruff_flag.py`'s clean-passthrough test didn't mock `_update_readme_test_badge` and fed `cmd_test` a hardcoded `"2751 passed"` fixture — every full-suite run reset the REAL README badge to the stale 2751. Badge writer now mocked like every sibling; badge refreshed to the real count.
- New tests: `tests/test_public_benchmarks.py` (16 — known-Sharpe synthetic series, daily-rebalance-vs-buy-and-hold pin, SPY-only universe, zero-close degradation, shape parity, `run_all_baselines`/`close_pivot_from_frame` aggregator), `tests/test_hrp_book_sizing.py` (14 — per-leg sums, sign preservation, equal-weight fallback <2 names, single-sided full-gross fix, selection-untouched invariant, `pct_returns_from_closes` edge cases), `tests/test_generate_evaluation_report.py` (+2 chart-render guards, +3 benchmark-markdown), `tests/test_aq_cli.py` (+2 benchmarks end-to-end/degrade), `tests/test_evaluation_state.py` (+2 benchmarks section), `tests/test_v543_new_features.py` (+2 un-placeholdered mean-reversion). All registered in `_SUBSYSTEM_TEST_FILES`.

**Benchmarks surfaced end-to-end (user follow-up ask):**
- CLI: `aq evaluate --benchmarks` (included in `--all`) — runs all five baselines over the SAME split-filtered dataset window as the rank book, writes `ml/evaluation/benchmark_comparison.json`, prints a per-baseline table.
- README: new "Benchmark Comparison" auto-section (`AQ:BENCHMARK` markers) — rank book's own net Sharpe rows first (per model), then every baseline; refreshed by `generate_evaluation_report.py` on every evaluate run, honest not-run-yet fallback before the first run.
- Webui: `BenchmarkPanel` on the Evaluation tab (types in `evaluation.ts`, `benchmarks` key served by `monitoring/evaluation_state.py::build_evaluation_state()` with the standard `not_evaluated` degrade); vitest-covered.
- `mean_reversion_baseline` un-placeholdered (V5.4.3 debt): previously accrued `weight_sum * 0.001` — structurally 0.0 Sharpe/return regardless of data; now accrues next-day close-to-close returns exactly like `momentum_baseline` (real backtest split numbers: 0.0 → −0.119 Sharpe / −20.96%).
- Packaging (Problems.md #115): installed `aq` console script raised `ModuleNotFoundError: No module named 'evaluation'` on `aq evaluate` — `evaluation`/`portfolio`/`features`/`audit`/`inference`/`analyzer` added to `[tool.setuptools] packages` and `generate_evaluation_report` to `py-modules` per the list's own transitive-import rule (aq_cli has imported them function-level for many versions; pytest/Lean masked it).

**Verification:** 2834 tests green; vitest 103/103; ruff clean; real `aq evaluate --benchmarks` run verified end-to-end (820 dates × 93 tickers, README section populated: rank book multitask 1.681 vs momentum 0.476 / SP500 1.214 / 60-40 1.624 / mean-reversion −0.119 / random −0.217).

## V5.4.5 — Documentation debt paydown: main README restructure, sub-README coverage, dev-doc index completion

**Shipped:**
- Main README restructured for readability (no content loss — everything removed here lives on elsewhere):
  - "Quickstart" section deleted (exact duplicate of Download); "Current Status" section deleted entirely (stale V5.1-era prose, superseded by Backtest Results + Known Limitations + Changelog).
  - "Contributing" bottom section deleted (CONTRIBUTING.md in Open Source Files is the single source); "Continuous Integration" bottom section deleted (CI expectations live in CONTRIBUTING.md, workflow details in `.github/workflows/`).
  - The README's "Runbook" section moved into `RUNBOOK.md` as "Everyday commands" + "Train in the cloud (GitHub Codespaces)" sections; the incident procedures stay RUNBOOK's core.
  - "Open Source Files" table relocated from below the footer to its TOC position (after Development Documentation), so the author footer is now literally the end of the file.
  - TOC rebuilt to match the new body order; intro paragraph and CLI Reference intro tightened without dropping any factual claim.
  - All six auto-generated result sections (Lean/Monte Carlo/Offline/Benchmarks/Walk-forward/Other Metrics) verified marker-complete and CLI-refreshable (`aq backtest`, `aq evaluate`); public benchmarks confirmed end-to-end since V5.4.4, nothing to implement.
- Sub-README coverage completed: `.devcontainer/README.md` and `.githooks/README.md` added (the last two tracked folders without one; `.github/` deliberately excluded). Every other tracked folder already had a current README.
- `development/README.md` index completed: `asset_universe.md` and `project_structure.md` were missing from it; `architecture.md`'s entry updated from "V2 system architecture" to the full-subsystem description.
- `development/project_structure.md`: tree extended with `.devcontainer/` and `.githooks/`.
- `SECURITY.md`: stale "README → Current Status / Known Limitations" reference fixed to point at Known Limitations only (Current Status no longer exists).
- `REPRODUCIBILITY.md`: two broken claimed-numbers table rows (Monte Carlo p5/p95, walk-forward mean) had their columns realigned.

**Environment note:** local venv had drifted from `requirements/requirements.txt` (+`requirements-dev.txt`) — `httpx` (declared since the FRED backfill work) and the whole dev extra set (ruff, pytest-cov, ...) were simply not installed, breaking test collection at import. Reinstalled both files; no repo change needed or made.

**Verification:** 2834/2834 tests green (`aq test`, badge refreshed); `ruff check .` clean after dev-extras install; README local links + heading anchors all resolve (scripted check); no inbound references to any deleted section remained (grepped).

**V5.4.5 round 2 - pre-backtest live-execution safety audit (structural review):** with the last verified Lean backtest predating V5.4.1-V5.4.4, the whole live decision/order path (main.py two-pass flow, portfolio/book_construction + hrp_allocation + book_neutrality, risk/position_sizing + rl_sizing + kill_switch, execution/order_gate + cost_model + reconciliation, data_pipeline/bar_synthesis parity) was reviewed end-to-end before the next real backtest. Findings and fixes (details in Problems.md #116-#119):

- Net-edge cost gate charged only ONE side's commission against a round-trip contract - live was more permissive than the offline simulator here. Both sides now counted (config is enabled+calibrated, so this actively affects decisions).
- Paper mode ignored `risk_locks_healthy` entirely - a tripped kill switch could not stop real broker orders in paper. Now enforced like live.
- NaN-propagation family fixed at seven points (kill-switch triggers, fill-slippage clamp, reconciliation false-clean, net-edge gate reason, book rank eligibility/spread veto, HRP covariance inputs, gross-cap erasure) plus a position-sizing floor-above-cap misconfiguration guard.
- HRP equal-weight fallback normalized across BOTH legs combined -> asymmetric two-sided books lost dollar-neutrality; now shares the main path's per-leg totals.
- V5.4.1's RL asymmetric-penalty reward was dead code at its production call site (nothing loaded/forwarded the weight); wired through config (`asymmetric_penalty_weight`, default 1.0 byte-identical) with provenance recorded.
- Verified-clean areas explicitly audited: bar_synthesis train/runtime parity (module-level import everywhere, third padding copy noted in off-default parallel path), RL state-vector order/count parity trainer-vs-runtime, RL multiplier clamps/direction preservation, kill-switch Sharpe window math and trip stickiness, override precedence layering, neutrality step ordering, sign conventions on every sizing path.

**Verification (round 2):** 2858/2858 tests green (24 new tests pinning every fix), ruff clean; badge auto-refreshed.
