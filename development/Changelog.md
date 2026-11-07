# Changelog

What each phase built and why, oldest first (the newest phase is <!--fact:changelog.latest-->V6.6.3<!--/fact-->, and `README.md` has the current status). The evidence lives in [`Problems.md`](Problems.md); entries describe what was true at the time. Full text of older phases: [`backups/`](backups/README.md).

## V1 — Finished

- First working pipeline over a small mixed universe (`AAPL`, `SPY`, `QQQ`, `BTCUSD`), 2014-12-01 to 2018-08-13 daily bars.
- Train/validation/backtest windows; next-day-direction label; 1d/5d/20d return/volatility/momentum, daily range, volume-change features.

## Phase 2 Result

- Loads Lean ZIPs, normalizes prices, computes features/targets, produces train/validation/backtest splits, fits and saves the scaler.

## Phase 3 Result

- PyTorch MLP with layer norm/dropout, asset context as model input, validation-loss early stopping, optimized decision threshold, saved metrics/checkpoint, JSON export for Lean inference.

## Phase 4 Result

- Loads exported artifacts (weights/schema/manifest/scaler), runs the forward pass directly in Lean; real buy/sell/hold signals written to `visualization/state.json`.

## Phase 5 Result

- Strategy returns vs buy-and-hold; Sharpe/volatility/max-drawdown export; equity curves; `backtests/strategy_report.json`.

## Phase 6 Result

- Separated Lean/dev dependencies; runs in the real local Lean Docker runtime; daily/total drawdown risk controls with trade-blocking + liquidation; minimum confidence + trade cooldown.

## Phase 8 Result

- `state.json` extended with dashboard/monitoring/scene data; Grafana-friendly CSV/JSON exports; scorecards, asset heatmap, risk band, positions, 3D-like dashboard scene.

## Phase 9 Result

- Universe expanded to equities, ETFs, and 3 crypto coins with a data-quality-aware pipeline.
- Derives ETHUSD/LTCUSD from Coinbase minute data; per-asset quality scoring; trains only on robust assets; thin series flagged `observation_only` (blocked from real trades, still shown); position/ exposure caps.

## Phase 10 Result

- Large artifacts kept out of git; documented core commands; structured runtime logs; first `pytest` tests (features, asset quality, scaler, risk controls); pre-flight artifact/config validation.

## Phase V2-1 Result

- Started the V2 fork on top of the stable V1/Phase 10 codebase.
- V2 module structure (MoE, experts, regime, topology, experience, risk, monitoring); documented planned architecture and tech stack (Docker, Lean, PyTorch, Postgres, Grafana, Telegram, HTML dashboard).

## Phase V2-2 Result

- `data_pipeline/` as a stable V2 layer over `train.py`; a V2 pipeline manifest (source, universe, features, windows, quality); tests locking in the Lean data contract.

## Phase V2-3 Result

- `risk/position_sizing.py`: volatility-classified (`low`/`normal`/`high`) dynamic sizing (`base_target_weight`, `target_weight`, `leverage_factor`) into runtime state, heatmap, Grafana CSV.

## Phase V2-4 Result

- `volatility_dashboard.html`: 5s-refresh live view reading `state.json` directly — portfolio/risk/drawdown plus per-asset signal/regime/vol/ sizing/confidence. Works without a broker key.

## Phase V2-6 Result

- `regime/market_regime.py`: trend (`bullish`/`bearish`/`sideways` from momentum) + volatility regime → `risk_on`/`risk_neutral`/`risk_off`.

## Phase V2-7 Result

- `experts/expert_datasets.py`: regime-sliced expert training datasets, filtered to `training_eligible`, with a manifest (row counts, splits, routing filters). Artifacts out of git.

## Phase V2-8 Result

- Separate PyTorch expert models per regime slice (MLP family); `train.py --experts-only`; per-expert weights/metrics under `ml/expert_models/`.

## Phase V2-8.5 Result

- Smaller experts with stronger regularization; a quality gate (validation/backtest/MCC/train-backtest gap) flagging each expert `stable`/`watchlist`/`disabled_for_gating` so gating never trusts a weak or overfit expert.

## Phase V2-9 Result

- `moe/gating.py`: weights experts by quality gate, regime fit, stability (ignores `disabled_for_gating`); combines baseline + experts into one final MoE probability; falls back to baseline if artifacts missing.

## Phase V2-10 Result

- A single pure decision layer replacing an ad-hoc if/elif chain in `main.py`.
- `analyzer/market_analyzer.py::build_market_analysis_decision()` returns exactly one of `observe`/`simulate`/`trade`/`reduce_risk`/ `retrain_candidate`, priority-ordered (risk containment > model health > profit action > paper tracking > observation). `_apply_signal` still only trades on `trade`.

## Phase V2-11 Result

- A pure cross-asset topology layer that starts influencing decisions.
- `topology/market_topology.py`: pairwise correlation, union-find clustering, 3D coordinates (correlated assets near each other, volatility on z); computed once per bar before the per-asset loop, no lookahead.
- Analyzer tiers: `topology_risk=="elevated"` forces `reduce_risk`; an isolated asset can't reach `trade` (falls back to `simulate`). New `/topology` tab + `/api/topology`.

## Phase V2-12 Result

- A pure per-asset liquidity/market-impact layer.
- `liquidity/market_liquidity.py`: dollar-volume/participation/slippage/ round-trip-cost from OHLCV alone; classifies orders `normal`/`thin`/`high_impact`/`blocked` recommending `allow`/`reduce_size`/`simulate_instead`/`block`. Two analyzer tiers force `simulate`.
- Real per-asset fees in Lean (`ConstantPercentageFeeModel` crypto, `ConstantFeeModel` equities); `LiquidityTable.tsx`; `Dockerfile` + extended compose.

## Phase V2-13 Result

- Fire-and-forget Redis experience-event stream.
- `experience/redis_queue.py`: `build_experience_event()` + `ExperienceQueue` (XADD after every asset decision, `maxlen=100000`); fails silently on Redis errors, never blocks the Lean loop; deferred `redis` import keeps Lean environments importable without it.

## Phase V2-14 Result

- Durable PostgreSQL persistence for the experience stream.
- `experience/postgres_worker.py`: standalone worker (`XREADGROUP` → `experience_events`, embedded DDL, no migrations); idempotent via `ON CONFLICT DO NOTHING`; dead-letter stream for malformed messages; exponential backoff/reconnect. New `experience-worker` service.

## Phase V2-15 Result

- Observation Mode — full decision pipeline, zero real orders, parallel simulated portfolio.
- `phase_v2.runtime.mode` (`backtest`/`observation`/`paper`/`live`, default `backtest` unchanged); `execution/order_gate.py:: resolve_order_permission()` — observation is **never** allowed real orders regardless of any other flag.
- `experience/simulated_portfolio.py::SimulatedPortfolioState` — fake cash/holdings/equity/drawdown/exposure entirely in memory; cooldown/ position-limit/exposure/drawdown checks made mode-aware; `observation_metrics.py`; dashboard exports + `ObservationPanel.tsx`.

## Phase V2-16 Result

- Performance Triggers — automated threshold-based health monitoring.
- `performance/triggers.py`: 8 pure trigger functions (drawdown, Sharpe degradation, win rate, confidence decay, regime shift, liquidity warning, risk-lock, observation count) + `evaluate_all_triggers()`; each event carries severity/scope/recommended_action/ `retrain_candidate`.

## Visualization Unification Result

- Two separate HTML dashboards replaced by a single React/Vite webui plus a FastAPI JSON backend.
- `monitoring/api_server.py` serves `state.json`/`scene.json`/Grafana exports; Overview + Risk pages map 1:1 onto the old dashboards; genuinely 3D rotatable market scene (`@react-three/fiber`) — foundation for V2-11's topology view.

## Phase V2-17 Result

- Controlled Retraining — full plan/train/validate/backtest/commit/promote/ rollback pipeline closing V2-16's open loop.
- New `retraining/` package (pure/IO/worker split): `planning.py`, `postgres_registry.py` (`model_versions`/`retraining_events` DDL, one-active-model DB constraint), `validation_gate.py`, `backtest_gate.py`/`lean_backtest.py`, `vault_commands.py`/ `vault_client.py` (external `av` subprocess wrapper, missing-binary-safe), `artifacts.py`, `status_export.py`, `orchestrator.py` (CLI), `worker.py`.
- `train.py --candidate --version-id` writes exclusively to `ml/versions/<id>/`, never active paths; promotion requires a successful Aether-Vault commit; rollback verifies SHA-256 hashes before activating; `RetrainingWorker.auto_promote` defaults `false`.

## Phase V2-17.5 Result

- Probabilistic topology overlay + richer triggers — strictly additive, never replacing the deterministic path.
- `topology/learned_topology.py`: per-node cluster probabilities/ confidence/uncertainty/stress/neighbor-drift; falls back to the deterministic position whenever the model is missing or unconfident.
- `train_topology.py`: fits KMeans prototypes from real experience-event outcomes → `ml/versions/<id>/` only; skips on insufficient data.

## Phase V2-18 Result

- Grafana removed in favor of a native React tracing dashboard (it had no computation path of its own — purely a new consumer of existing exports).
- Deleted the `grafana` service/volume; new `/tracing` page with 4 panels (metrics snapshot, asset performance, backtest equity, observation equity) + two dependency-free SVG chart primitives.

## Phase V2-19 Result

- Telegram Alerts for trigger events and end-of-session summaries.
- New `notifications/` package (pure/IO/worker split); trigger channel polls the existing `performance_triggers` table directly; session-summary channel adds a new experience event at session rollover in `main.py`.

## Phase V2-19.5 Result

- Manual, offline Yahoo Finance backfill script for thin local Lean data (mainly ETHUSD/LTCUSD) — never runs from training/runtime/Docker.
- `data_pipeline/yfinance_backfill.py`: dry-run by default (`--apply` writes); real Lean rows win on overlap; `yfinance` stays dev-only.

## Phase V2-23.1 Result

- Data-driven liquidity spread estimation (closed differently than planned: no real fill-slippage telemetry existed to calibrate from).
- `estimate_high_low_spread()`: Corwin & Schultz (2012) closed-form high- low estimator from already-collected bar data; replaces the static per-security-type spread lookup as primary (static stays fallback).

## Phase V2-23.2 Result

- Config audit: three `phase_v2` blocks `main.py` had read since V2-3/V2-6/V2-9 were never present in `config.json` (silently forcing hardcoded defaults); `average_correlation` unfed since V2-6.
- Added the three blocks (values = prior defaults, no behavior change); wired `average_correlation` from topology's `correlation_strength`.

## Phase V2-23.3 Result

- Topology's 3D layout was purely cosmetic angle-based placement.
- `_stress_majorize_2d()`: SMACOF stress-majorization over the full pairwise correlation-distance matrix, deterministically seeded, isometrically rescaled into display bounds; chosen over classical MDS to stay numpy-free.

## Test Suite

- 313 → 378 after the audit pass (14 new: 10 liquidity, 1 regime, 3 topology).

## Phase V2-20 Result

- Confirmed a normal `lean backtest .` already exercises the entire ML stack end-to-end (baseline, 4 experts, MoE gating, regime, topology) — proof of coverage, nothing rebuilt.
- `tests/test_lean_backtest_ml_coverage.py`: first real integration test (subprocess run asserting all subsystems populate `state.json`), closing `main.py`'s zero-test gap (#8/#66). Lean-vs-Lean4/`elan` binary-collision safeguard for the skip check.

## Phase V2-21 Result

- Paper Trading Preparation — real code-enforced gates targeting Lean's built-in PaperBrokerage (not a real IBKR paper account).
- `execution/paper_readiness.py`: `evaluate_paper_broker_config()` (3 required confirmations), `evaluate_observation_readiness()` (4 of 5 checklist items; the 5th deliberately left as human review). New `aq paper-readiness` gate, `PaperReadinessPanel.tsx`, opt-in `lean-live` compose profile.

## Phase V2-22 Result

- Live Deployment Structure — purely structural groundwork so paper→live becomes a config/credential change, not a rewrite. No real credentials or live trades configured or tested.
- `execution/live_credentials.py`/`live_credentials_io.py` (tries `ib_config.py`, falls back to env vars); `evaluate_live_broker_config()`/ `evaluate_live_risk_posture()`; auto-promote forces manual promotion when `mode=="live"`; new critical `live_order_permission_blocked_trigger` (not retrain-eligible — a broker misconfiguration isn't fixed by a new model).

## Latency Optimization + Docker Image Consolidation

- Static complexity analysis of `main.py`'s per-bar hot path found 3 real bugs + 2 CPU bottlenecks (pure-Python NN forward pass, pure-Python O(N²×100-iter) SMACOF); Docker images consolidated 5→3 as groundwork for a later latency-optimized variant (explicitly not an HFT conversion).
- Bugs (#11–#13): `_write_state()`'s useless throttle guard rewrote all 7 state files every bar; `mark_to_market()` called once per symbol instead of once per bar caused O((bars·symbols)²) CSV rebuild work — fixed via `close_prices_by_symbol` collection + new `_flush_observation_equity_csv()`; new `execution/config_cache.py:: read_cached()` mtime-cached config reads keyed `(config_path, loader)` after same-path readers overwrote each other's entries (found only via real `lean backtest .`).
- Left open then: skipping Redis push in backtest mode (#14).
- Docker: three worker images merged into one `Dockerfile.workers` (5→3 custom images).
- NN inference extracted to `inference/exported_model.py` free functions, vectorized with numpy (was pure Python, ×5/symbol/bar); `_stress_majorize_2d()` vectorized too (the pairwise-correlation loop and `learned_topology.py`'s smaller O(N²×5) portion deliberately left unvectorized).
- Behavior-changing: `build_market_topology()` accepts `previous_positions` for warm-started SMACOF (+ `convergence_tolerance` early exit); `phase_v2.topology.warm_start_enabled` (default `true`) / `convergence_tolerance` (0.01) break bit-reproducibility vs. old cold-seeded behavior; `warm_start_enabled: false` is an exact rollback.

## 20-Asset Universe Expansion + Genuine Held-Out Backtest Window

- Universe 10→20 on real data; backtest finally out-of-sample.
- 8 equities added at zero backfill cost from existing on-disk Lean data through 2021-03-31 (`AIG`, `BNO`, `FB`, `GOOG`, `GOOGL`, `USO`, `WM`, `AAA`); XRPUSD/ADAUSD backfilled via yfinance (real earliest history starts 2017-11-09, not the guessed dates); BTCUSD/ETHUSD/LTCUSD extended forward to 2021-03-31.
- Genuine held-out window: common-window end 2018-08-13 → 2021-03-31; training 2014-12-01→2017-12-31, validation 2018-01-01→2018-03-31, backtest 2018-04-01→2021-03-31 (~3 years; previously backtest == full window).
- Real bugs fixed: #15 — `ensure_derived_crypto_daily_series()` unconditionally clobbered ETH/LTC daily zips over yfinance-backfilled rows → merge by date instead; #16 — `initialize()` exceeded Lean's hardcoded 90s isolator timeout → split into minimal Lean-critical path + `_ensure_ready()` deferred to first `on_data()` (init now 1.85s, full window ~51s); #17 — intermittent timeouts from matplotlib font-cache rebuilds → persistent `MPLCONFIGDIR` pointed at `.matplotlib_cache/`.
- Manifest: 16/20 assets eligible; `AAA`/ETHUSD/XRPUSD/ADAUSD stayed observation-only for genuine sparsity. README "Universe Size" section + Mermaid diagram; lean-backtest timeout bumped 7200→14400s.

## `aq fetch` — ad-hoc Yahoo Finance ticker fetch

- New `aq fetch <crypto|stock> --ticker ... --start ... --end ... [--apply]`, replacing a multi-step manual ticker-onboarding process.
- `data_pipeline/fetch.py` reuses `yfinance_backfill.py`'s pure functions unchanged (`fetch_yahoo_ohlcv`, `scale_for_lean`, `write_lean_zip`); `ASSET_CLASS_CONFIG` drives the Lean path per class.
- `aq_cli.py`: new `cmd_fetch` (in-process) + `_iso_date` argparse validator; packaging fix: `pyproject.toml`'s `packages` gained `"data_pipeline"` (same ModuleNotFoundError bug class as a prior `execution` fix).

## Trade-frequency tuning — statistical/diagnostic backtest mode

- A real 3-year 20-asset backtest produced only 12 filled trades (compounding suppression across several gates plus two structural traps), so an opt-in bypass mode and threshold loosenings were added purely for statistical/diagnostic evaluation.
- Opt-in `phase_v2.backtest.bypass_safety_gates` (default `false`), standalone key separate from `aq trade-lock`; `is_backtest_safety_bypass_active()` true only when `runtime_mode=="backtest"` and explicitly true.
- Config-only loosening: `min_confidence_to_trade` 0.12→0.05; buy/sell_threshold_offset 0.08→0.04; `trade_cooldown_bars` 3→1; thin_participation_threshold 0.002→0.01; blocked 0.05→0.10; max_active_positions 5→10; max_crypto_exposure 0.25→0.35.
- Deliberately out of scope: real short-selling (`_apply_signal`'s sell branch only ever calls `Liquidate()`); hardcoded topology volatility threshold left unchanged.

## Real learned gating weights + learned topology wired into position sizing

- Closed two gaps flagged deferred by V3's completeness assessment: gating was still hand-tuned arithmetic, and the learned topology overlay never reached a trade decision.
- New pure `topology_sizing_multiplier()`: strict no-op (1.0) unless `topology_source=="learned"`; bounded shrink-only third factor in `build_dynamic_position_sizing()` — changes size only, never the decision. Keys: `phase_v2.dynamic_risk.topology_sizing_enabled` (default `true`), min/max multipliers 0.5/1.0.
- Additive learned gating: `GATING_MODEL_FEATURE_KEYS` (26-dim) + `build_gating_model_features()`; `build_gating_decision()` gains optional model/schema params → `decision_source: "learned_gating"`; any failure silently falls back to the hardcoded blend.
- New offline trainer `train_gating.py`: trains on the dataset's validation split (avoids stacking circularity), replayed through exported models, evaluated on backtest split; `AetherNet(26 → [16] → 1)`; smoke-tested against real data (1,304 validation / 16,184 backtest rows), valid model in ~90s.

## `aq config`/`aq lean` full read/write CLI + `analyzer/market_analyzer.py` real composite scoring

- Full CLI read/write access to `config.json`/`lean.json` (replacing hand-editing) plus a real config-gated composite signal-quality score.
- Both commands share one generic dispatcher (`_dispatch_json_config_command()`) — dotted-path walker/setter operating on whatever's on disk; bare command pretty-prints; `get`/`set <dotted.key> <value>`/`keys [prefix]`.
- `analyzer/market_analyzer.py::compute_signal_quality_score()`: bounded [0,1] weighted composite (confidence 0.45, regime confidence 0.20, topology peer-support 0.20, liquidity friction 0.15); `signal_quality_score`/`breakdown` always computed.

## Multi-task prediction (direction + magnitude + volatility) — Phase 1

- Root cause behind flat performance: every model sat at backtest MCC 0.02–0.07 (noise) with Sharpe -0.758, predicting only binary direction with no magnitude/volatility forecast for sizing.
- `export_multitask_architecture()` branching `{trunk, heads}` export alongside the unchanged original; `run_exported_multitask_model()` + `_softplus()` (guarantees volatility ≥ 0).
- `AetherNetMultiTask`: shared trunk + direction logit / magnitude regression / Softplus-volatility heads; new `target_volatility_next_day` column; `compute_regression_metrics()` (MAE/RMSE/bias).
- New `train_multitask.py`: loss = BCE(direction) + weight·MSE(magnitude) + weight·MSE(volatility) (both weights default 1.0); writes `ml/versions/<id>/multitask_*`; exits 0 on insufficient data.
- Runtime additive/informational: graceful artifact load gated by `phase_v2.multitask_model.enabled` (default `true`); predictions thread into signal_payload/analyzer/dashboard/CSV. Position sizing opt-in: `use_predicted_volatility` (default `false`) replaces backward-looking rolling vol when enabled.
- Retraining extended (`OPTIONAL_MULTITASK_FILES`, orchestrator stage, `--multitask-only`); `Dockerfile.retraining_worker` gained the COPY plus a found-missing `COPY risk/` fix (#20) — image needed rebuild.

## Phase 1 remainder + Phase 2: regime/liquidity/topology as inputs, per-expert multitask, sequence encoder

- Same-session continuation implementing both scoped-out pieces plus the causal-TCN sequence encoder, all verified against the real dataset.
- Regime/liquidity/topology as model inputs: `add_regime_features()` (9 one-hot + 3 continuous; renamed to fix a naming collision), `add_liquidity_features()` (deliberately excludes participation/slippage), `build_topology_features_by_date()` (per-date cross-asset call).
- Real off-by-one bug fixed: liquidity features originally ran after `engineer_features()`' dropna, silently missing each asset's first bars vs live windows; moved before it, on the raw frame (parity script: ETHUSD row 6 mismatch → exact match).
- Per-expert multitask exports under `ml/expert_models/<name>/`; gracefully skips datasets lacking the columns (found via a real pre-existing test failure).
- Sequence primitives in `inference/exported_model.py` (`_softmax`, `_layernorm_axis`, `_conv1d_causal` verified 9.1e-8 vs real `nn.Conv1d`, `_multihead_attention` verified 5.6e-8 — infrastructure only); `AetherNetSequenceMultiTask`: causal TCN trunk chosen over a Transformer for bit-for-bit verifiability; `train_sequence.py` smoke-tested (30,193 rows, ~3.5 min, MCC 0.0219 — same noisy range, proving the pipeline doesn't fix noise).
- Retraining extended for both pieces (`OPTIONAL_SEQUENCE_FILES`, stage, `--sequence-only`).

## Multitask/sequence pipeline integration — closing the 7 remaining gaps

- Follow-up closing open integration points between the new model layer and the rest of the stack.
- 4 new Lean-coverage tests exercising a real backtest against the 48-dim pipeline (baseline multitask, per-expert contribution, sequence).
- Experience events gain an optional `sequence_model` field (JSONB column, no Postgres migration).
- Neural-network webui extended to all 12 real networks (flat vs branching `{trunk, heads}` dispatch; recursive weight-stats flatten for conv1d 3D; per-head diagram columns; `NETWORK_ORDER` +6 — previously a silent filter, #19).
- Promotion-cycle tests confirm OPTIONAL files survive commit hashing; infrastructure.md documents the full stage order.
- Documented (#21, not benchmarked): forward passes went 5 → 11 per symbol per bar — both new families informational-only or off-by-default.

## Phase 2 sequence encoder wired into the gating decision (optional, off by default)

- Closes the scope boundary restated by every prior entry: the sequence encoder was informational-only; now wired into gating specifically (the one funnel all prediction sources pass through).
- `build_gating_decision()` gains `sequence_prediction` + `sequence_weight` (default `0.0`) applied last as the same anchor-blend shape `baseline_weight` uses; new `GatingDecision.sequence_blended` flag.
- Docs corrected everywhere the stale claim lived (`moe/README.md` design writeup; Follow-up notes in inference/analyzer/risk/architecture).

## Frontier-model edge investigation — target redesign, real bug fixes, cross-sectional ranking (model input 48 → 59)

- Every model (baseline, 4 experts, multitask, sequence) sat at backtest MCC 0.017–0.07 on next-day binary direction — noise.
- Bug fixes: `volume_change_1d` clamped [-1, 20]; winsorization + ±scaled_feature_clip_sigma (default 10.0) persisted to scaler stats (#23); real split/dividend adjustment via Lean factor files (train-only gap; Lean's feed was already correct) (#24); `assess_regression_quality()` gate wired into both trainers (#25); sequence window-size compat fix (#26); fixed 7 of 10 retraining-worker tests silently running real training subprocesses up to ~30 min each (#22).
- Windows widened: validation 2018-01-01→2018-12-31, backtest 2019-01-01→2021-03-31 (old 3-month validation gave too few non- overlapping observations; pre/post backtests deliberately not comparable).
- Targets: `target_return/direction_5d/20d`; horizon sibling model classes (experts/baseline/gating stay 1d-only); masked loss helpers + per-head thresholds avoiding silent always-positive collapse.
- Cross-sectional ranking: `build_cross_sectional_rank_targets()` (per-date percentile rank, min universe 10) → `target_rank_5d/20d`; `rank_5d`/ `rank_20d` heads; Spearman `compute_rank_ic()` with non-overlapping- stride variant; informational-only this pass.
- Peer returns: `TopologyNode.top_peers` + `rank_correlated_peers()` (`top_peers_n` default 3); offline/runtime emit `peer_rank1/2/3_return_1d` + `peer_mean_return_1d`. Dim 48 → 52.

## Follow-up — rank_20d wired into position sizing

- Wires the one statistically significant signal into sizing, off by default.
- `rank_sizing_multiplier()`: bounded, direction-preserving (defaults 0.75–1.25, median rank = no-op); `PositionSizingDecision.rank_multiplier`. `main.py` extracts predicted_rank_20d (sequence-preferred, multitask fallback) into dynamic sizing + signal_payload.
- `rank_sizing_enabled` ships `false` honestly: subsample t-stat only 1.20 vs 4.40 full-series — not yet independently significant.

## 5/10 → 9/10 frontier-readiness roadmap (Phases 1–7)

- Follow-up rated 5/10 since rank wasn't independently significant on the then-20-asset universe. Seven phases closed that gap plus other structural weaknesses.
- **P1 Bond sleeve**: universe 20→30 assets (SHY/IEF/TLT/AGG/LQD/HYG/TIP/ MBB/EMB/MUB registered as `security_type: "equity"`); `features/ macro_features.py` yield-curve slope (TLT-SHY spread momentum), credit spread (HYG-LQD), crypto risk appetite proxies. Dim 59 → 62.
- **P2 Validation rigor**: purged/embargoed folds, non-overlapping eras, bootstrap IC CI, `assess_ranking_quality()` code-enforcing promotable/watchlist/not_promotable (t < 2.0 fails; CI lower bound < 0 fails; any sign-flipping era fails).
- **P5 Sector neutrality**: `sector_mapping.json` + loader ("Unknown" fallback); sector-neutral rank targets/head — purely additive.
- **P3 Stage-2 long/short book** (the one deliberate direction-setting departure): `portfolio/book_construction.py::build_rank_based_book()` (top-N long / bottom-N short by predicted_rank_20d); `main.py::on_data()` restructured into two passes; provably byte-identical when off (`portfolio_book.enabled: false`).
- **P4 Walk-forward**: rolling/expanding window generation + `python train.py --walk-forward` CLI; config gated off; infra verified (6 expanding windows from the real window) but the full multi-window run (~45 min/window) was NOT executed.

## Follow-up — closing the roadmap's CLI/webui/backend wiring gaps

- Audit found backend logic for three phases unreachable from any user-facing surface; all fixed.
- `rank_ic_decay_trigger()` was backend-only → now fed by the worker every cycle (new config: rolling window 100, min mean IC 0.02, min t 2.0, horizon 20 days).
- Webui: `{head}_ranking_quality` promotion-gate badges (previously only rank_20d shown) and `portfolio_book_role` column; new badge tones.

## Multi-Asset-Class Support — Bonds, Futures, Options + Interactive Brokers Integration

- V3's headline scope item: futures/options trading alongside equity/crypto/ bonds with real Black-Scholes greeks and margin-based futures risk sizing (not a bolt-on to the equity sizer), plus bonds moving to real yield-curve/duration treatment.
- New modules: `data_pipeline/fred_backfill.py` (no-key FRED CSV), `features/bond_features.py` (curve level/slope/curvature, credit-spread, `empirical_duration_beta()`), `futures_contract_specs.json` + `risk/futures_risk.py` (contract-count sizing; `rollover_due()` diagnostic-only), `features/options_greeks.py` (BSM, Newton-Raphson+bisection IV), `portfolio/options_strategy.py` (single-leg, greeks-sized, vega-budget capped), `data_pipeline/ib_backfill.py` (dev-only, raises IBNotConfiguredError), `risk/asset_class_router.py::route_position_sizing()` (one dispatch point), `features/derivatives_macro_features.py` (neutral 0.0 default, #29).
- New `asset_class` universe field (distinct from Lean's security_type); context one-hot features; `input_set` 30→38 (breaking, retrain required). Exposure caps bonds 0.30/futures 0.20/options 0.10.

## Infrastructure/latency pass — `aq test` speed, inference-hot-path profiling, CI Docker cache

- Research-first pass (3 explore agents before any code change); writeup #31.
- `aq test` silently ran a REAL `lean backtest .` on every invocation (skipif checked binary availability, not intent) taking >1h — fixed via the `lean_backtest` marker (excluded by default, opt-in `--lean`) plus 11 combinable subsystem flags and opt-in `--parallel` xdist.
- New `scripts/profile_inference.py`: found and fixed `_conv1d_causal()`'s per-timestep Python loop (vectorized gather + batched einsum) and batched `main.py`'s 4-expert loop into one numpy call per layer (safe fallback on architecture mismatch).
- CI Docker builds gained `type=gha` caching; docs audits (README links, `scripts/README`, shared `AQ:TEST_COUNT` markers).

## Latency deep-dive follow-up — weight/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension

- Re-profiling found `numpy.asarray()` conversions as the largest remaining cost (#32).
- `convert_state_dict_arrays()` once at load; `BatchedLayerStackCache`/`build_models_batched_cache()` precompute stacks instead of `np.stack()` per call — zero API/behavior change.
- Profiling harness rebuilt (inputs pre-generated outside the profiled region; p50/p95/p99 tail reporting); new `aq profile` command.
- Opt-in per-symbol multiprocessing (`inference_parallelism`, default `false`): Pass 1 restructured so inference can run across a persistent `ProcessPoolExecutor`.
- New C++/pybind11 `cpp_inference_ext` accelerating `_linear_batched()`; optional path, deferred import, NumPy fallback. Two real bugs found: identically-named source folder shadowed the installed extension as an empty namespace package; first install went to system Python, not `.venv`, making an early comparison measure NumPy twice.

## Execution/risk realism — real `SlippageModel` wired to fills

- The liquidity layer's per-bar impact+spread estimate was computed purely for sizing/routing and discarded — no Lean security had a slippage model, and simulated fills used `slippage_bps=0.0` (systematically too-good fills).
- `order_gate`: `slippage_amount()` / `resolve_slippage_bps()` (clamped to 500bps) / `resolve_fill_slippage()`; `main._LiquidityAwareSlippageModel` adapter attached via `SetSlippageModel()`, per-symbol bps refreshed every bar; `enter_long(slippage_bps=...)` populated everywhere.
- Combined impact+spread used (Lean fill has no bid-ask awareness); follow-up made source + clamp configurable (`phase_v2.liquidity.fill_slippage.{source,max_bps}`).

## Real limit-order support — every tradable asset class, config-gated

- Closed the market-fill-only gap at all 5 order call sites (`phase_v2.limit_orders`, default off).
- Pure functions `resolve_limit_price()` / `classify_order_status()`; `main._try_submit_limit_order()` shared router; `on_order_event()` stamps cooldown at confirmed-fill time; per-bar stale-order sweep with per-class fallback-to-market policy (equity/crypto/bond on; future/option off).
- Two sign/keying bugs caught pre-ship: a naive buy-sign transform would have flipped correctly-signed futures quantities; option pending orders recorded the wrong symbol key.

## Liquidate positions when an asset class gets disabled (+ 2 stale doc fixes)

- Flipping `futures_risk`/`options_risk` off zeroed sizing but never liquidated pre-existing positions.
- `resolve_asset_class_enabled()` / `should_liquidate_disabled_asset_class_position()`; `exit_using_last_known_price()`; per-bar sweep anchored after `_refresh_risk_state()`. Applies to futures/options only.

## Extended latency profiling beyond inference — found topology to be a much larger per-bar cost than inference itself

- New `scripts/profile_subsystems.py` + combinable `aq profile --<subsystem>` flags measuring regime, topology, liquidity, gating, analyzer, and indicator primitives.
- Real finding: `build_market_topology()` costs ~500–600ms per call at the real ~30-symbol universe — comparable to or larger than the ENTIRE per-symbol inference total.

## Investigated inference tail latency (p99 3-5x p50) — real GC-pause contribution confirmed

- Profile-output discrepancy resolved (machine load, not regression); bucket-report ruled out warmup (p50 flat); `--no-gc` isolated GC pauses driving worst-case latency (−66%/−95% max tail across two paired runs, p50 unaffected).

## 2-leg vertical spread selection for options (single-leg stays the default)

- Conservative, explicitly-scoped multi-leg support (call/put verticals only); straddles/strangles/condors/butterflies remain out of scope.
- Additive dataclasses/functions; `select_vertical_spread_legs()` reuses the single-leg selector for the long leg; net-vega-based sizing; router `spread_strategy` dispatch (default `single_leg`); atomic placement via Lean's `OptionStrategies` + `Buy(strategy, quantity)` — avoiding hand-rolled sequential-order fill risk.
- Two bugs caught pre-ship: unconditional contract-symbol extraction would have rejected every spread; plural tracking dict added rather than repurposing the singular one.

## 2026-07-16 — CI root cause found and fixed (#10), per-bar forward-pass latency measured (#21), per-asset-class book-slot caps (#29)

- Closed three entries needing real evidence (`gh` CLI + `aq profile`), none needing a rebuilt image.
- #10 (three independent CI roots): `.gitignore`'s `data/**` excluded two hand-authored reference JSONs (exception added, files committed); `empirical_duration_beta()`'s exact `variance_x == 0.0` check broke under Python 3.14's float-summation change (< 1e-12 tolerance); the Lean integration self-skip checked binary presence, not a usable Data folder.
- #21: `aq profile` already simulated the 11-pass bundle — batched mean 12.00ms/p99 106ms vs unbatched 8.72/41; sequence encoder dominates (~48–58%), flagged not fixed; negligible vs the 90s `initialize()` budget.
- #29: `per_asset_class_slots` param (default `None` = pooled behavior byte-identical; pooled/per-class share `_select_book_group()`), wired via config + `asset_class` on book candidates.

## 2026-07-16 (later) — #10 confirmed green on real CI, full implementations for #36 (topology embedding cache) and #37 (gc.freeze()) shipped, both config-gated off

- Topology embedding cache: skip SMACOF when every pairwise correlation is stable within tolerance and the universe is unchanged (`cache_enabled: false`, tolerance 0.02).
- `gc.freeze()` once after model load, gated (`gc_tuning.freeze_after_load_enabled: false`); still needs real-backtest validation of Lean's .NET/Python GC boundary.

## 2026-07-16 (later still) — final pre-backtest bug sweep, 4 fixes, before this project's first real `lean backtest .` run

- 3 of 11 Lean-coverage assertions read the wrong state key (`config.model` vs top-level `model`) — would have silently passed a broken backtest.

## 2026-07-16 (yet later) — pinned the Lean engine Docker image, found live during the actual first backtest attempt

- `aq backtest` appeared to hang — it was silently re-pulling the ~42.5GB engine image because `lean backtest .` resolves mutable `:latest`.
- `PINNED_LEAN_ENGINE_IMAGE = "quantconnect/lean:17900"` (immutable tag confirmed via Docker Hub API); `cmd_backtest()` always passes `--image`; `aq backtest --image <other>` escape hatch.

## 2026-07-17 — Docker consolidation: one `aether-quant-engine` image for app + every worker, `aether-quant-` container rename, compose Lean image pinned

- Deleted `Dockerfile.workers`/`Dockerfile.retraining_worker`; one `Dockerfile` installing a single requirements file and COPY-ing the whole tree — structurally eliminates #1/#2/#20/#30 (all the same root cause: per-worker COPY allowlist drift causing ModuleNotFoundError crash-loops).
- Compose: app service renamed `engine` (`aether-quant-engine`); workers share the image with `aether-quant-<service>` names; `LEAN_IMAGE` default pinned to 17900 matching the CLI pin.

## 2026-07-17 — Pre-live security review: `lean.json` credential indirection, secrets out of the Docker image, localhost-only DB, secret-commit guard

- Nothing was ever leaked — all findings prospective (#42).
- `aq render-lean-config`: overlays `.env.live`'s `AETHER_*` values onto the empty tracked `lean.json` template into a gitignored `lean.live.json`; only field names ever printed.
- Published DB/Redis ports rebound to 127.0.0.1; fail-closed guard refuses live mode on the default dev password. New `aq secrets-check` (fail-on-populated-secret scan) + opt-in pre-commit hook.
- Checked clean: no deserialization-RCE surface; FastAPI read-only/ localhost-CORS; Telegram creds env-var-only; nothing in git history. Deferred: audit logging (closed in the next entry).

## 2026-07-17 — Full pre-live model overhaul: rank-driven trading, unblockable exits, and a training-pipeline rewrite that stops shipping the untrained model

- A backtest returned bit-identical results to pre-calibration (same 14 orders, same 20.364% net profit) proving the recalibration did nothing. Two independent bug classes (#43):
- Trading could never exit: position counting missed same-bar submissions; the static sell threshold sat ~10σ outside the model's real output range; the circuit breaker was neutered by config; protective vetoes blocked exits too.
- The model was nearly constant: early stopping monitored validation BCE (lowest at epoch 1) shipping near-random models; no degenerate-threshold guard; MoE's unconditional 0.25 expert floor pulled outputs to 0.5; ranking heads ignored by trading.

## 2026-07-18 — Operational maturity pass: tamper-evident audit logging, a real end-to-end retraining/rollback rehearsal, and every structural gap the rehearsal itself surfaced

- New `audit/` package: Redis Stream → Postgres → JSON snapshot, hash-chained (tamper-detectable via `aq audit-log --verify`); hooked into orders, credential loads, live-mode transitions; queryable + webui panel.
- Real rehearsal (not mocks): seeded events/triggers, let the retraining-worker poll loop auto-run plan→…→validate three times against real Postgres/subprocesses — all candidates correctly rejected by the validation gate.
- The rehearsal surfaced 3 real structural bugs (#44–#49): read-only volume blocking `train.py`; Redis `xreadgroup(block=0)` perpetual socket timeouts in every Stream worker; orphaned retraining-events rows → new startup reconciliation marks stale `planned`/`running` rows failed.
- A limit-orders/gc-freeze/spreads verification attempt was blocked by the 4GB machine (imports alone ~82s under pressure vs Lean's 90s cap, #50). One permanent fix regardless: direct import from `audit.redis_queue`.

## 2026-07-19 — The rank-pivot roadmap: trading path switched onto `rank_20d`, universe expanded 30→74 and rebalanced across asset classes, four Stage-4 regularization gaps closed

- Direct follow-through on #43: direction is noise while rank_20d has skill, but was being traded far faster than its horizon supports (653 orders, Sharpe −0.59 / Net −4.6%).
- Trading pivoted onto rank_20d: `long_short` mode, rank sizing on, sequence_weight 0.5, book 8/8, spread floor 0.15; explicit 5-day rebalance scheduler (`should_rebalance_this_bar()`).
- Universe 30→74 (40 equities/22 bonds/12 crypto); 44 tickers backfilled (a real MultiIndex-columns yfinance bug fixed + 2 regression tests); dataset 113,804 rows (was 46,242); 63 eligible + 11 observation-only.
- Four regularization gaps closed in both trainers: rank-IC early stopping; dead 1-day direction head down-weighted; seed ensembling (prediction-averaging + `--seed`); horizon-consistency regularization.

## 2026-07-20 — GitHub Codespaces cloud-training offload, and the rank-pivot roadmap's actual empirical retrain

- Codespaces set up as disposable training compute (`gh codespace ssh/cp`; artifacts never through the public repo).
- Working config: Debian base + sshd feature + CPU-only PyTorch. All 8 artifacts retrained end-to-end on the 113,804-row dataset in <15 minutes (vs 4+h local that never completed).
- Git-hygiene bug: 9 generated artifact files were still tracked — untracked + gitignored.

## 2026-07-20 — First real backtest against the rank-pivot-roadmap models: Sharpe -0.59 → +0.40, and a universe-selection bug found and fixed

- Real bug from the backtest log: BNBUSD/TRXUSD could never subscribe in Lean — Coinbase never listed those pairs. Swapped for ETCUSD/ZECUSD, backfilled with real rows; universe stays 74.
- **Headline result:** Sharpe −0.59 → **+0.403**, Net Profit −4.604% → **+10.438%**, Drawdown 11.1% → 4.0%, Win Rate 47% → 58%.

## V4 Webui — Overview/Operations split, Tracing reflow, genuinely 3D topology (V4-W1 / V4-W2 / V4-W3)

- W1: seven operational/health panels moved to `/operations`; duplicated nav blocks collapsed into a NAV_ITEMS map. W2: Tracing page reflowed into two explicit flex columns.
- Found+fixed (#55): every webui tab except `/` 404'd on hard refresh — FastAPI's StaticFiles isn't an SPA catch-all; new `SpaStaticFiles`.
- First frontend test infra: Vitest + Testing Library; 10 tests.

## V4.1 completion — normalized topology z offset, `aq train --topology-only`

- Naive fix (raising the z multiplier) caught as wrong BEFORE shipping (would saturate the clamp 20x for some win rates).

## V4.3.0 — Functionality: allow adding to an existing position, all 5 asset classes

- Exploration found THREE distinct problems, not one gate.
- Equity/crypto/bond were blocked by a stale-signal gate; futures/options had NO gate at all (live bug: absolute margin/vega targets fired through incremental primitives, silently stacking every bar — reachable only with those classes enabled, both default off; options also re-selected legs, orphaning tracked positions).
- Tier 1 (unconditional fix): `compute_incremental_order_quantity()` signs a delta toward the absolute target. Tier 2 (opt-in `position_scaling.enabled`): churn-guarded scale-ups.

## V4.4 — architecturally-sound options: multi-position book, symmetric scale-down, held-contract sizing, spread combo orders

- Closes six architectural gaps from V4.3.0 — code-complete, IB-unverified.
- Held-contract sizers size on current greeks instead of re-selecting from the chain; multi-position tracking dict capped per underlying (cap 1 = byte-identical pre-V4.4); dedicated single-position liquidation; pending-limit-orders re-keyed to order-target Symbols (concurrent positions don't collide); at-cap re-pricing bug caught during verification (placed orders regardless of the scaling flag).

## V4.5 — full `OptionStrategies` coverage: all 43 QuantConnect option structures, registry-driven

- From 2 of 43 factories to all 43; the 6 arbitrage structures stubbed for a future mispricing detector.
- Registry of per-strategy specs transcribed from Lean's C# source + ~10 shared shape-family selectors; net-vega multi-leg sizing; 3 margin sub-models; ordered-priority routing (volatility-gated for straddle/ strangle/condor/butterfly).
- Transcription bugs fixed: ladder/backspread bounded-unbounded misclassifications, expiry drift, debit/credit role inversion, √252 annualization at the wrong site, missing margin entries.

## V4.6 — bounded options follow-ups, arbitrage mispricing detector, Forex/FX, analytic bond-ETF duration/convexity

- Multi-leg positions no longer each count toward `max_active_positions`; rotation anti-thrashing cooldown + same-bar netting; optional per-asset strategy override; new put-call-parity/box/carry arbitrage detector (gated off); Forex fully first-class (`forex_risk.py` leverage-utilization sizing + pair specs + midpoint-OHLC quote-bar fallback); analytic duration/convexity/DV01 informational bond analytics.

## V4.7 — early-assignment/corporate-action modeling, a learned multi-leg strategy-selector model, and bond analytics wired into the trained model as real signals

- Code-complete; the matching retrain deliberately NOT run this pass.
- Dividend-driven early-call-assignment risk scoring (call-only, off by default) + Barone-Adesi-Whaley American pricer (verified vs a binomial tree); ex-dividend backfill pipeline; option-strategy outcome capture for observation mode (zero DDL changes); learned strategy-selector trainer + inference (dormant until real option positions exist); the 3 analytic bond features added to the model feature list.
- Sequencing risk documented: enabling the config without the matching retrain would KeyError every bar.

## Phase 4.8 — closing the gaps a full-stack completeness audit found: `lean` CLI in the retraining-worker image, a new Options & Strategy webui page, a real `main.py` bug fix, and CLI/Docker discoverability fixes

- A 3-agent audit rated V4 7/10; this closes its concrete gap list (topology training, IB integration, walk-forward, and the real backtest explicitly deferred to the user).
- `lean` CLI in the production image; retraining-worker got a docker.sock mount (Lean launches its own container); compose gained a scoped `data/reference/` mount (assets-status was reporting zero specs); new `aq backfill <dividends|fred|yfinance>`; stale subsystem-test dict missing 4 files fixed.
- Real bug: `corporate_action_payload` was set in Pass 1 but read in Pass 2 — every symbol reused the LAST symbol's leftover value; threaded through `pass1_state`.

## V4.9 — a major latency-optimization pass across every hot path, prepping the ground for a future HFT fork

- Nine priorities, mostly opt-in byte-identical-default, plus one genuine live bug fix:
- P0 (bug): a "removed" profiling wrapper was still live, synchronously writing `model_input_timing.log` every symbol-bar — 45,187 untracked log lines found in the repo root. P1 sequence batching across symbols (flag-gated).

## V4.10 — pure-function extraction of main.py's exit logic, 4 webui quality fixes, and 15 new forex/FX assets fetched via `aq fetch`

- Non-model exit logic extracted to pure `evaluate_non_model_exit()`/ `compute_position_exit_tracking_update()` — `main.py` keeps thin, byte-identical call sites (verified via static call-graph trace; a literal main.py unit test remains impossible).
- Forex onboarding: Lean's 10-column bid/ask CSV handled (documented zero-spread synthesis preserving real spreads on merge); pair specs 7→15, all fetched; universe 74→89. `forex_risk` stays off.

## V4.10 follow-up — opt-in live (Lean/IB-calibrated) futures margin source

- `phase_v2.futures_risk.margin_source` (`static` default | `live`) attached per-security via `SetBuyingPowerModel()` (not globally — avoids touching fees/slippage elsewhere); unrecognized values fall back to static; continuous-vs-mapped-contract documented as an open gap.

## Backend/latency gap-closing pass — Docker-built C++ accelerator, main.py CI syntax-check, Windows inference_parallelism guard

- Closes the 3 findings capping `backend/models/latency` at 8/10.
- Soft-fail Docker step builds `cpp_inference_ext` for the container's own Python (the prior local artifact was ABI-incompatible) — any failure degrades to the NumPy fallback.

## V4.11 — training + optimization phase: full Codespace retrain + walk-forward executed, three latent train.py bugs fixed, primary signal clears the ≥2.0 significance bar

- First real Codespace execution of a full retrain + the walk-forward diagnostic. 8 of 9 model families retrained (topology stayed dormant — disposable environment, no event store).
- Three latent `train.py` bugs fixed: forex 11-field quote bars couldn't parse (midpoint collapse added, matching runtime for parity); `add_regime_features()` duplicated every column on empty walk-forward frames; manifest KeyError on empty inventories.
- Several Lean-gated, IB-independent features switched ON ahead of the user's upcoming manual backtests (position-scaling, sequence batching, topology cache, composite regime score, forex trading, parallelism).

## Phase 4.12 — decomposing "era-sign instability" into 3 real causes, alt-data (options-implied vol + financial conditions), 104-asset universe, an RL sizing layer, and every remaining non-IB Problems.md item

- Cause 1: degenerate crypto-only weekend cross-sections (255/801 dates) forcing ±1.0 rank-ICs → `min_universe_size` 10→20.
- Alt-data added (VIX level + term structure, financial-conditions change) via the no-key FRED fetcher, lookahead-tested. Universe 89→104; `max_active_positions` 15; book 10/10.

## V4.12.2 — close every webui/CLI integration gap Phase 4.12 left behind

- Backend/CLI were complete; the webui rendered only part of what was now computed and persisted.
- Sizing-multiplier chips (volatility/confidence/topology/rank/rl); RankingQualityGate renders all three rank heads with a per-era diagnostic table flagging opposite-sign/thin eras; `state["macro"]` finally written (bond/alt-data payloads were computed every bar but never persisted) + MacroSnapshotPanel; CLI re-audited clean; 6 READMEs updated.

## Phase 4.12.3 — every remaining Docker-dependent item closed, Phase 4's arc complete

- Root-caused the Docker/WSL2 outage (a stuck installer process wedging WSLService in StopPending, preserved across power cycles by Windows Fast Startup) — fixed with a genuine restart.
- Topology overlay trained FOR REAL the first time: 6 clusters from 4,937 samples (observation-mode backtest shrunk to 3 months to survive the 4GB machine; still 52,129 real events — 100× past the 500-event minimum).
- RL sizing re-confirmed negative on freshly rebuilt datasets — stays disabled. Isolator note at 104 assets: `Initialize()` ~105s (over the 90s budget) though backtests completed regardless.

## V5.1 — Cost-aware cross-sectional ranking

- Rebuilds model + execution around V4's core gap (real gross edge, negative Sharpe from fees): train for what's actually traded on, make cost explicit throughout decision/sizing/safety.
- Both trainers optimize a differentiable soft-Spearman ranking loss (ListNet variant available) over whole-date batches; AdamW + cosine decay + SWA; LayerNorm TCN trunk; rank targets residualized vs market/sector/ size; per-asset macro-sensitivity betas replace broadcast macro features.
- Expected-net-edge gate vs expected round-trip cost before every trade; scale-down-only on thin edge. Fixed: rank heads trained raw [0,1] but exported with a leftover sigmoid compressing live predictions to ~[0.48, 0.75] — invisible to rank-IC (monotone-invariant) (#84).
- Book dollar+sector neutral with hysteresis; sector map 29→104 (#85); truncation-by-order fix keeps strongest names under the cap (#86).
- Walk-forward spans six expanding windows; new offline cost-aware rank-book simulator (`evaluation/`) mirrors the live path (net Sharpe/turnover/ capacity/stress/ablation); promotion gate consumes its verdicts.
- New kill switch (rolling Sharpe, drawdown velocity, live rank-IC decay, consecutive losses, slippage divergence, model age) tripping the same sticky lock as drawdown breaches; position reconciliation; opt-in auto-rollback.
- Also fixed: FRED HTTP/2 hang (#79), walk-forward feature-list crash (#82), false-positive orphaned-feature report (#80), ~17-min/run test regression from an unmocked subprocess test (#78).

## V5.1.11 — Lean runtime portability and startup boundary

- Ahead of spending the reserved V5.1 backtests:
- `aq backtest` defaults to a cached local `aether-quant-lean:17900` image (built from pinned `quantconnect/lean:17900`; installs Redis + `httpx[http2]`), removing the fragile generated-requirements mount on Windows; Windows launcher fixes temp-dir permissions before Lean starts.
- Deferred `performance.evaluate_all_triggers` to the dashboard view — prevents Lean's hard startup isolator importing the trigger worker's torch stack at module init.

## V5.1.12 — Six critical bugs found before the first V5.1 Lean backtest

- Full review of every config value switched on that session plus its consuming code (#88):
- Net-edge gate measured edge against trade direction (was blocking every short); `--calibrate-edge` regressed on the configured horizon, not always 1-day (`edge_bps_per_rank_unit` recalibrated 28.22→396.27); kill-switch rolling-Sharpe needs a minimum sample; reconciliation now compares broker holdings vs FINAL post-sizing intent per Pass-2 symbol; slippage-divergence no longer counts overnight gaps as slippage; `corporate_action_payload` leak onto other symbols fixed; `sector_max_net_weight` 0.05→0.15 so per-name caps are reachable.

## V5.1.13 — First real V5.1 backtest: three critical fixes verified, book-spread bug found and calibrated

- Confirmed the riskiest fixes live, but exposed the book trading 3 weeks then placing ZERO orders for 2.2 years (#89).
- Rolling-Sharpe numerically unstable on near-zero-variance windows (mostly-cash → spurious extreme readings stuck tripped) — distinct gap from #88's warmup fix.

## V5.2.1 — Closing the offline-vs-live Sharpe gap

- Confirming backtest resumed trading but Sharpe −4.2…−4.4 vs offline +0.26…+2.18 same window — three independent compounding mechanisms (#90).
- Confirmed ~1-bar execution lag never modeled offline (daily orders fill next bar's open; MarketOnClose lands later — structural). Simulator gains opt-in `entry_lag_bars`; `--rank-book` shows 0 and 1 side by side.
- Position-scaling machinery re-fired every bar for book members, independent of the rebalance cadence → gated to rebalance bars for book-selected symbols only (full exits untouched).
- Cost gate sized against full target value instead of the incremental resize delta (systematically under-costing small resizes) → sized against the real delta; flips cost more.

## V5.2.2 — Book-history diagnostic + reconciliation CLI

- The confirming backtest (−4.421) showed the fixes did NOT close the gap; six indirect hypotheses tested and ruled out → build reusable ground truth instead of another one-off.
- Opt-in backtest-only `visualization/book_history.jsonl` (`phase_v2.diagnostics.book_history.enabled`) logging actual selections per rebalance date via `build_book_history_record()`; new `aq evaluate --reconcile-book-history` re-derives scores offline and reports per-date overlap/role mismatches/score-weight deltas to `ml/evaluation/book_history_reconciliation.json`.
- Real bug: `build_sequence_windows()` windows by ordinal position not calendar dates → `select_context_date_range()` computes the correct span.

## V5.2.3 — Full-universe snapshot, hysteresis replay, webui integration

- First real run (2026-08-07, 112 rebalance dates) surfaced two unexplained findings (#91): crypto/FX appear OFFLINE on 107/112 dates but in the LIVE book on 0/112; equities-only mean overlap just 54.8%.
- Opt-in `include_full_universe`: logs EVERY symbol with a bar that date (score/readiness/reason/eligibility/type) — not just selected members.
- `--replay-hysteresis` carries held allocations forward like the live book, distinguishing real divergence from correct incumbent-holding. Per-security-type summary; evaluation JSONs served via `/api/evaluation` with webui panels.
- Update (2026-08-08 fresh backtest): byte-identical Sharpe/order-count/ OrderListHash — the logging is a true no-op. Crypto/FX absent from `signals` on all 112 dates = bar-delivery problem, not low scores.

## V5.2.4 — Fixing bar_index inflation, the empty-book liquidation bug, and making crypto/FX book-eligible

- `self.is_equity_session_bar` gates the single `bar_index` increment — fixes every downstream consumer automatically (cadence/cooldowns/ holding-age exits/rotation/limit timeouts).
- **Update (2026-08-09 backtest):** rebalance gap 10.29 business days matching config (was 5.2); orders ~halved (392), fees halved ($372); all three security types in the snapshot; 189 non-equity selections.

## V5.2.5 — Fixing the live-vs-offline `bond_empirical_duration_beta` mismatch

- Ruled out price drift (byte-identical data) and scaler mismatch (~1e-15); confirmed one root cause.
- Offline computes the OLS duration-beta once over full history and broadcasts it; live recomputed per bar from a rolling 260-bar deque — a continuously-drifting input.

## V5.2.6 — Fixing the crypto/FX execution-path bug and closing the live-vs-offline risk-gate gap

- Deep-dive found two dominant mechanisms: crypto/FX orders never actually execute, and live carries ~10 risk gates with zero offline counterpart.
- Finding 1: forex midpoint bars hardcode `volume=0.0` and the liquidity veto keys on exactly that — every forex order vetoed; a live BTCUSD bar also showed volume 0 (Lean/Coinbase delivery quirk), so V5.2.4's eligibility was phantom in practice.
- Book-selected confidence threshold split from the general one; new `--calibrate-confidence-threshold`: general threshold 0.0968 APPLIED; book-selected 0.8925 deliberately NOT (methodologically circular — book selection is already an extreme-rank filter).
- Risk-off override severity floor set from a real replay of severity tiers (applied 0.55 via a None-sentinel; a naive 0.0 default would NOT have been safe).
- **Updates:** first attempt crashed on stale gating (fixed with `book_history_should_log_this_bar`); successful run Sharpe **−2.984** (from −3.351), 437 orders. Diagnostics surfaced two more bugs → V5.2.7.

## V5.2.7 — Fixing the forex order-sizing bug and the sticky kill-switch lockout

- Both surfaced by V5.2.6's own diagnostic.
- Forex lots: notional at realistic 4-12% weights ($4k-$12k) never reached one 100k lot → always rounded to ZERO orders (6 allocations reached "trade", silently produced nothing).
- Sticky lockout: ONE trip (2020-02-27) locked the entire book for 13+ months — 40.4% of decisions reached "trade" before it, 100% forced `reduce_risk` after.
- **Update (2026-08-11 backtest):** both confirmed live — Sharpe −2.984→ **−2.17**, 220 real forex fills across 9 pairs for the FIRST TIME EVER, `notional_ratio` within 0.15% of 1.0 across 193 records; kill switch now trips 26 separate times, clearing each session (26-trip cadence flagged as a new open sensitivity question).

## V5.2.8 — Closing unnecessarily-open Problems.md items and continuing the live-vs-offline gap investigation

- Two-stage patch. Stage 1 closes stale non-IB items (doc corrections: Forex fully live; bond-schema caveat already closed by #70; CancelPending classified pending — precision, zero behavior change).
- `evaluation/kill_switch_replay.py` + `aq evaluate --replay-kill-switch`: day-by-day offline replay of the kill-switch state machine, explicitly approximate.
- Optional gate-aware training weight (`compute_gate_friendliness_weight_by_date()`) from the same stateless topology/regime-severity gates the analyzer uses; threaded as optional `date_weights` (None-default, byte-identical), behind `gate_aware_ranking_weights.enabled: false`.
- Reconciliation re-run vs the real log: the five-ticker divergence still recurs; the cross-asset-sensitivity lead ruled out (identical lookback).

## V5.2.9 — Full-scale production retrain with gate-aware ranking weights, promoted to active `ml/`

- Real full-epoch (120/60) round: flag ON, candidate promoted to active `ml/` after backup; RL sizing re-evaluated; full walk-forward. Topology excluded (needs real Lean events through local Postgres).

## V5.2.10 — README Backtest Results split into Lean/Offline Evaluation/Walk-Forward/Other Metrics/Disclaimer, all auto-updating

- V5.2.9's real Lean backtest (Sharpe −1.72) plus the offline cross-analysis surfaced numbers worth keeping visible, not chat-only.
- README Backtest Results split into five auto-regenerating subsections (compact tables + foldable detail blocks), replacing a stale Phase-4.12-era caveats block; TOC/CLI Reference updated.
- `generate_evaluation_report.py` wired into evaluate/backtest exit points (marker-replace, never-fail contract); per-model-suffixed artifact copies fix a real clobbering bug (evaluating multitask after sequence destroyed sequence's numbers); `kill_switch_replay.json` finally surfaced in the webui; Other-Metrics shows REAL kill-switch trips parsed from the Lean log next to the offline estimate.

## V5.3.1 — Limit-order docs/testing/tooling (#34) and book-history reconciliation bugs (#91), closed as completely as possible without a live Lean run

- Deep research (5 parallel passes) + direct verification. No live Lean run — everything below offline.
- `phase_v2.limit_orders` had actually been ON by default all along (docs said otherwise — corrected); future/option fallback asymmetry found deliberate (plan corrected, no change).
- Warm-up floor raised 21→260 bars closes a cold-start duration-beta gap V5.2.5 didn't reach. Reconciliation reads real per-date `trading_eligible` instead of hardcoding True.
- **Update (2026-08-14 real backtest, Sharpe −1.034 from −1.72):** the warm-up fix confirmed live. An apparent severe regression was itself a contamination artifact ("prior" file was an undiscovered 7-run cumulative log) — self-caught, documented in #98.

## V5.3.2 — Root-causing #91/#97 (NVDA/GE/WFC/XOM/BA divergence) and #98 (confidence-spread disengagement gap)

- In-depth pass (3 agents + direct analysis, no live run). Closed #98 as genuine model behavior; found two real reconciliation-tooling bugs — neither explains the divergence, but the evidence sharpens.
- #98 closed: the trainers' own per-era diagnostics show ALL FOUR model/head combinations collapse to insignificant IC in exactly Apr-Sep 2019 — a genuine no-edge stretch; the spread gate works as documented.
- Run segmentation extracted and wired into the reconcile CLI (defaults to most-recent run only; 92% of logged dates recur across runs — silent cross-run merging eliminated).
- **Re-measured:** matched-day raw-score deltas are large (0.11–0.21) and strongly directional (live selects, offline doesn't, ~4-5:1) — pointing at a real feature/data computation discrepancy for these 5 tickers specifically, not a boundary artifact.

## V5.3.3 — Root cause found and fixed for the NVDA/GE/WFC/XOM/BA divergence (4 of 5 tickers); confidence-spread recalibration applied

- V5.3.2's lead traced to a genuine, undiscovered data gap: 63 of 77 equity tickers had NO local Lean split/dividend factor file — offline trained on raw UNADJUSTED prices while live was always adjusted by Lean.
- New `data_pipeline/factor_file_backfill.py` derives real Lean-format factor files from yfinance corporate actions; run for real (63 files, zero failures); dataset regenerated automatically.
- Separate real bug (#101): `--all`'s non-JSON output used a literal Greek Δ outside cp1252 — every such run had been crashing mid-command since Aug 13, silently leaving sections stale.

## V5.3.3 real backtest verification (2026-08-17) — factor-file fix confirmed strongly live; confidence-spread recalibration regressed Sharpe

- User's real run (2019-01-01→2021-04-02, ~6.8h) tested both changes — clean single-variable A/B (the factor fix never touches the live path; only the recalibration does).
- Orders 230→695, unique trading days 130→360 (lower threshold re-engaging, as predicted). **Sharpe regressed: −1.034→−1.798**, Net Profit −1.60%→−5.51%.
- Factor-file fix confirmed STRONGLY live beyond offline estimates: GE 52→15%, BA 48→12%, NVDA 69→25%, WFC 78→55%, overall overlap 56.9% (best of the investigation).
- Recommendation: reconsider/partially revert the spread value; keep the factor fix. See #102.

## V5.3.5 — Rolling trailing-IC gate addressing #102's recommendation; wired into `main.py`, shipped disabled pending a real backtest

- Builds exactly what #102 asked for: an independent second book-engagement veto based on trailing REALIZED rank-IC, plus offline calibration/replay tooling deriving its threshold from real data before ever touching the live path.
- `evaluation/rank_ic_core.py`: torch-free extraction of the IC math (originals become re-exports, suites pass unmodified) avoiding the #16 isolator-import failure class.
- Additive `None`-default params (`rolling_ic_gate_result`, `veto_reason_out`) instead of a return-type change (6+ callers); new `gate_veto_reason` field; book-history now writes on EVERY genuine rebalance bar even when vetoed-empty (previously zero trace — true since V5.2.4 for the old gate too).
- Real bug found+fixed via the gate's own checkpoint: thin origin dates (2-3 resolved names) mathematically force ±1 IC dominating the low tail → `min_names_per_date` (tools/config use 10), which exposed a second bug: `min_resolved_dates_required=40` became structurally unreachable (plateau 22-24) → lowered to 20.

## V5.3.5.3 — Workstream B shipped (XOM feature-level diagnostics); rolling-IC gate's first live test written up; chronic shutdown hang investigated and probed

- Three threads, none touching trading behavior: (1) Workstream B from the V5.3.5 plan — XOM feature-level plumbing (#91/#100 lineage) — built and tested; (2) the previously undocumented 2026-08-19 real backtest (`backtests/2026-08-19_13-33-56`, the rolling-IC gate's first live test) written up (#103); (3) the "endless loop" from commit c2ed98c investigated and instrumented (#104).
- Workstream B shipped: adopted `evaluation/feature_reconciliation.py` (one real bug found by the new tests on adoption day itself: the summary aggregator counted whole delta dicts as feature names — fixed); additive allowlist-bounded `feature_snapshot` field on `build_book_history_record()` (defensive-copied); two flags under `phase_v2.diagnostics.book_history` (`include_feature_snapshot` / `feature_snapshot_symbols`) captured at main.py's write site via ticker-matched `base_features`; new CLI `aq evaluate --reconcile-features --symbol XOM` — pure log-vs-dataset diff (no models), run-segmented, not in `--all`.
- Tests: new `tests/test_feature_reconciliation.py` (14) + extensions to portfolio-construction and CLI tests (+6); registered in `_SUBSYSTEM_TEST_FILES`. Suite 2688→2708, badge refreshed. Manual dry-run vs the real cumulative log degrades cleanly (exit 0).
- Rolling-IC gate's first live test (backfilled from 2026-08-19, #103): Sharpe −1.832 vs the −1.798 baseline — NO recovery — while orders fell 695→462 and `rolling_ic_below_floor` out-vetoed the old gate 106:21.
- Shutdown hang (#104): chronic (72/78 teardown-reaching runs back to May 2026), post-results only, strictly tied to NORMAL completion (both clean exits were mid-run error terminations).

## V5.3.6 — Feature-parity audit: scaler artifact verified exact, NO live-path formula drift (XOM-class ruled out for OHLCV families); crypto zero-volume root cause narrowed to Lean quote-bar delivery

- **Summary:** Built the permanent train-vs-live feature-parity audit (#105): pure core + CLI driver + 15 tests.

## V5.3.6 completion — WS-B/D/E/C analyses banked; first fully-synced Codespace retrain pulled back (not promoted)

- **Added:** scripts/gate_sweep.py + promotion_gate_null_calibration.py + overlap_vs_sharpe_analysis.py with JSON results under ml/evaluation/; Problems.md #106 records the numbers: offline book net Sharpe +1.497; IC floor 0.05 doubles bad-era disengagement at zero era_0 cost offline; kill-switch zero offline trips at every grid point (live-only sensitivity); null calibration shows the t>=2 bar is genuine (2.75% FP) while era-flip blocking is not (66% of noise runs flip >=2 eras - real model flips only 1).

## V5.3.7 completion — era_rule flip_fraction shipped + full retrain promoted; promoted multitask offline net Sharpe 1.68; walk-forward infrastructure-blocked (documented)

- **Shipped:** era_rule gate selector + tests (6); extended null study under the gates own 90-day scheme (promotion_gate_null_gate_scheme.json: null flips ZERO, real 0.222 -> strict criterion validated, fraction knob calibrated context recorded).

## V5.3.8 — Monte Carlo simulation testing layer: aq evaluate --rank-book --monte-carlo with auto-refreshing README section (1000-run curves chart, red average line, foldable deep stats)

- **Shipped:** evaluation/monte_carlo.py (stationary block bootstrap / iid; seeded; pure numpy) + CLI flags (--mc-runs/--mc-block-size/--mc-seed/--mc-method) writing ml/evaluation/monte_carlo.json + monte_carlo_curves.npz + generate_evaluation_report.py rendering the new README subsection between Lean Backtest and Offline Evaluation: all-run equity chart (faint blue, red average line) auto-regenerated every evaluate run + foldable percentile/deep-stats block.

## V5.3.9 — Deep GitHub Actions testing suite: win+ubuntu pytest matrix with 80% coverage gate, ruff lint job, vitest in CI, CLI smoke battery, actionlint, workflow meta-tests; non-blocking tag-release visibility

- **Shipped:** ci.yml rewritten to five jobs (python-tests matrix with --cov-fail-under=80 calibrated from the measured 82% baseline + coverage.xml artifact; python-lint running the newly adopted ruff E/F ruleset - 604 pre-existing findings triaged to zero; webui-tests now executing the full vitest suite before build; cli-smoke editable-install battery incl. aq secrets-check; workflows-lint via actionlint). release.yml gained a deliberately NON-BLOCKING tag-tests job so tagged releases always proceed while gaps stay visible on the run. tests/test_ci_workflows.py pins the entire structure (7 meta-tests).

## V5.3.10 — CI regression fixes (requirements parse meta-test, pinned actionlint), aq test --ruff flag, main.py extraction batch #1

- **Shipped:** Fixed two CI regressions from V5.3.9's ci.yml rewrite (corrupted requirements-dev.txt line + fragile actionlint PATH-append pattern).

## V5.3.11 — CI python-lint fix (bare ruff, no editable-import chain) + pip-audit dependency-CVE scanning job

- **Fixed:** python-lint job reverted to bare `ruff check . (the `aq test --ruff` invocation required importing pandas via the aq_cli module chain, but the lint job intentionally runs in a minimal environment without full deps). Duplicate py_compile step removed. **Added:** dependency-audit job running pip-audit against both runtime and dev requirements files on every push/PR - catches known CVEs before release.

## V5.4.1 — RL sizing asymmetric reward fix (root-cause of 3× honest negative), regime conditioning, auto-rollback dry-run + degradation score, prediction provenance counters

- **RL sizing:** compute_action_reward() gained asymmetric_penalty_weight (>1.0 penalizes foregone profit on winners); RL_SIZING_STATE_KEYS gained regime_trend_bullish/bearish/sideways one-hots for regime-conditional policy learning. 6 tests. Codespace retrain ready but not yet executed.

## V5.4.2 — Critical missing-import fix (bar_synthesis), parity tests, pre-backtest audit, pip-audit job

- **Critical fix (#113):** V5.3.10's extraction of midpoint synthesis + sequence padding to data_pipeline/bar_synthesis.py never added the import to main.py → NameError crash on forex path + silent sequence-model death.

## V5.4.2 — Almgren impact model, residual demotion documented, pre-backtest audit clean

- **Shipped:** evaluation/impact_model.py (Almgren sqrt-impact formula); integrated into rank_book_simulator as optional cost layer (phase_v2.costs.impact_model, default off). Residual_rank_20d documented as non-promotable (#112) and explicitly demoted in config.json.

## V5.4.3 — Factor-neutralization check, HRP allocation, benchmark comparison baselines, README restructure; CI registration gap fixed

- **Shipped:** **Verification:** 2790 tests green (up from 2757); ruff clean; vitest 100/100; production build clean.
- `evaluation/factor_neutralization_check.py::compute_factor_exposure()` — OLS regression of book returns onto market/momentum factors reporting alpha Sharpe, R², loadings, and per-factor variance contribution. Pure numpy/pandas.
- `portfolio/hrp_allocation.py` — Hierarchical Risk Parity (López de Prado 2016): scipy Ward linkage on correlation distance → quasi-diagonal ordering → recursive bisection by inverse-variance → weights summing to 1.0.
- `evaluation/benchmark_comparison.py` — momentum top-N, mean-reversion bottom-N, and random-entry baselines on the same dataset/window for edge-vs-benchmark context.
- CI: `test_impact_model.py`, `test_v543_new_features.py`, `test_bar_synthesis_parity.py` registered in `_SUBSYSTEM_TEST_FILES` (subsystem-mapping guard caught the gap).
- README restructured: Continuous Integration section moved above Open Source Files and linked from main TOC; Monte Carlo visual description updated to explicitly mention light blue semi-transparent individual-run lines.

## Phase V5.4.4 — Public benchmarks, HRP in the live book sizing, CI lint and the Monte Carlo chart fixed

- **Public benchmarks:** `evaluation/public_benchmarks.py` adds buy-and-hold SPY and a daily-rebalanced 60/40 on the rank book's own window and Sharpe formula, surfaced by `aq evaluate --benchmarks` (in `--all`), a README section and a webui panel.
- **HRP sizing (opt-in):** `apply_hrp_weights` re-weights the already-selected book with HRP inverse-variance weights when `allocation_method: "hrp"`; selection is untouched and the default stays rank.
- **Mean-reversion baseline made real:** it accrued a placeholder and always scored 0.0; it now accrues next-day returns like the momentum baseline (#115).
- **CI and README hygiene (#114, #115):** two ruff findings removed, the test suite no longer overwrites the real Monte Carlo chart or test badge, and the installed `aq` script packages every module `aq evaluate` imports.

## Phase V5.4.5 — Documentation debt paid down and a pre-backtest live-execution audit

- **README restructure:** duplicate and stale sections removed (Quickstart, Current Status, Contributing, CI), the runbook moved into `RUNBOOK.md`, and the TOC rebuilt; the last two folders without a README got one.
- **Live-path audit (#116-#119):** the net-edge gate now charges both sides' commission, paper mode honours the risk locks, a NaN family is guarded at seven points, HRP's equal-weight fallback keeps dollar neutrality, and the RL asymmetric penalty is actually wired through config.

## Phase V5.4.7 — `aq` help refresh and a full-system bug hunt

- **NaN-safe persistence (#120):** `json_safety.py` sanitises and atomically writes every payload and status file, and the Postgres workers dead-letter a poison row instead of stranding a whole batch.
- **Model and gate correctness (#121, #122):** the gating blend renormalises over the experts that answered, NaN confidence no longer scores as perfect, and the retraining gates fail closed on missing or non-finite metrics.
- **Data pipeline and tooling (#123, #124):** Yahoo NaN rows dropped, inclusive backfill ends, merging FRED caches, atomic config writes, verified promotions and rollbacks, a watermark that always advances, and workers that survive a Redis outage at start.
- **CLI surface (#125):** `tests/test_cli_help_surface.py` keeps every parser flag and the README's CLI reference in sync in both directions.

## V5.4.8 / V5.4.9 - PyPI + GitHub Release pipeline unblocked; releases published

- **Summary:** V5.4.7 never reached PyPI because the repo's GitHub "Workflow permissions" was set to **Read repository contents only**, so the `on: push: tags: ["v*.*.*"]` release trigger fired but the publish job had no write tokens — silently no-op.

## Phase V5.4.10 — Missing crypto quote zips

- **Quote zips:** 34% of a backtest's data requests failed on missing crypto quote zips; `aq backfill yfinance --quotes` synthesises zero-spread quote zips from the trade zips, LTCUSD first.
- **Teardown evidence corrected:** the run's "clean exit" was read from the algorithm log; the engine log still shows the #104 timeout.

## Phase V5.5.0 — Offline/live execution parity and an open-problems sweep

- **Order-level audit (#127):** `aq evaluate --audit-backtest` decomposes a Lean run from its folder alone; it showed the 2026-08-27 run (Sharpe -2.51) was not trading the offline book.
- **As-live simulator (#128):** `aq evaluate --rank-book --as-live` (`evaluation/live_parity.py`) runs the book through `main.py`'s own decisions; offline as-live 1.68 against idealized 1.00, so the gap was execution.
- **Execution fixes (#128, #133, #134):** a budgeted legacy sleeve, forex sized from the book weight with its own short budget, one order per symbol, exit tracking that sees late fills and clears stale state, the formed book held through a veto, forced-exit-only cooldown exemptions and per-class spread caps; the 2026-10-07 re-run reached Lean Sharpe -1.05 (+0.17 without risk-free).
- **Data (#130):** 62 factor files that double-adjusted already-adjusted zips were removed (deleted, never stubbed: a stub makes Lean start the data in 2050).
- **First-bar crash (#132):** Lean's star import shadows the stdlib `time`; a private alias fixes it and `tests/test_main_ensure_ready_smoke.py` now runs the real first-bar setup.
- **CI and guardrails:** fast-guards, subsystem-matrix, wheel-smoke, python-compat, docker-checks, parity-smoke and advisory secret / test-count jobs, pinned in `tests/test_ci_workflows.py`; `main.py`'s order paths are tested against a minimal Lean stub (`tests/test_main_wiring.py`).

## Phase V5.6.0 — The dataset matches what live sees: tick alignment, forex fill-forward, missing FRED drivers, real crypto fees

- **Cross-asset timing (#137):** `features/cross_asset_timing.py` is the one window construction for `main.py` and the offline replay, ending a one-tick lead (and a crypto lookahead) in training.
- **Forex calendar and FRED drivers (#140, #141):** forex features follow Lean's fill-forward calendar and two FRED drivers that existed only on the Codespace are on both sides; NVDA topology agreement with live 32% -> 96%.
- **Real costs (#138):** crypto pays Lean's `CoinbaseFeeModel` and forex IB's $2 minimum, and the net-edge gate and simulator charge the same per-class rates.
- **Retrain and decisions:** the regenerated dataset's models were retrained with a resumable walk-forward (rank_20d IC 0.101, positive in all six windows); the spread floor moved to 0.1985 and forex trading was switched off after it lost money net of fees (#142).
- **Round 3 (#143):** book members are exempt from the elevated-topology veto, disabled classes take no book slots, the equity spread proxy is capped at 10 bps, the edge is recalibrated and the slippage trigger enabled at 80 bps, all by pre-registered rules.
- **CI (#136):** the V5.5.0 push was red on Python 3.11's eager annotations, gitignored README links and tensor names read as keys; each fixed with a guard.
- **Lean results:** Lean Sharpe -2.51 (08-27) -> -0.95 (BT2) -> -0.76 (BT3) -> -0.04 (BT4, #144), net +4.73%, drawdown 2.8%; the teardown hang was closed as environmental (#104).

## Phase V5.7.0 — A simulator that reproduces Lean, gates decided by rule on two splits, the ML pipeline re-measured

- **Simulator on `main.py`'s own functions (#145):** the kill switch, member sizing chain, liquidity and net-edge gates, HRP and per-name impact are modelled, and the rolling-IC state is computed once (~20 s a variant instead of ~12 min); backtest +0.66 / +4.2% against Lean BT4's +0.66 / +4.7%.
- **Gates by R-GATE on both splits (#146, #147):** IC gate window 80 / floor 0.0, spread floor 0.184 on the live pool and a legacy cap of 0.05 ship; the kill switch, hold-on-veto, HRP and impact stay as they were; fills pay the modelled ~5 bps with no price-source gap.
- **Slippage trigger fixed in two steps (#148, #153):** the divergence counts only adverse slippage and ignores limit fills, whose gap to the bar open is intraday drift; BT7 halved the kill-switch dates.
- **Retrain, forex, RL and crypto (#149-#152):** a label purge, forex one-hot, carry feature and separate forex rank group were tried; R-MODEL failed, so V5.6.0's models stay, forex has no within-pool edge, RL is negative a fifth time and crypto stays as is.
- **Lean results:** BT5 / BT6 / BT7 Lean Sharpe +0.07 / +0.13 / +0.47 (+1.15 without risk-free), net +8.64% and drawdown 2.8% on the shipped BT7 config.

## Phase V5.7.1 — CI green again: constant-window correlation independent of float summation

- **Topology correlation:** a window of identical values is zero variance by value, not by `sum()` rounding, so Python 3.11 (CI and Lean) and 3.14 rank peers the same; this was the only failing CI test.

## Phase V5.8.0 — Data to 2026, audit tools, class sleeves with loss guards, grouped ranks, full retrain

- **Audit tools:** `aq evaluate --ic-by-class`, `--audit-gates`, `--audit-data`, `--audit-heads`, `--audit-features` and `aq clean ml` judge every class, gate, head and feature against its own evidence before any decision.
- **Data to 2026-09 (#156):** all 104 zips rewritten from one Yahoo source, crypto quote zips and FRED refreshed, Coinbase listing dates recorded, and new splits train 2014-12..2021-12 / validation 2022-01..2023-06 / backtest 2023-07..2025-06 / holdout 2025-07..2026-09 (read once).
- **Sleeves by R-SLEEVE (#163-#166):** forex (carry, minimum cap), bonds (momentum ranked, cut to the minimum cap after BT1), crypto graduates (1% / 5% caps) and RL sizing ([0.9, 1.1] with a shadow guard) all trade under loss guards; bonds and forex rank among themselves (grouped ranks).
- **Retrain and the out-of-sample verdict (#160-#162, #169):** the full stack was retrained (walk-forward rank_20d IC +0.0525) and kept by the owner; the one-look holdout shows no demonstrated edge (head ICs +0.02..+0.04, as-live -2.4%).
- **Gates and parity (#161, #173):** R-GATE chose rolling-IC window 120 / floor 0.0 and spread 0.10, and the models' regime inputs are drawdown-free, as in the dataset (#173, confirmed in BT2).
- **Latency (#159, #167):** batched flat models (64 -> 2 ms a tick), vectorised topology and throttled backtest state writes.
- **Lean results (#172, #174):** BT1 (2023-07..2025-06) -5.03%, drawdown 8.2%; BT2 (2023-07..2026-09) -0.58%, drawdown 4.3%, Sharpe -0.03 without risk-free: capital preserved, costs ($2,195) above the gross result, no edge shown.

## Phase V6.0.0 — Close every open point of V5.8.0: benchmark, a simulator calibrated on Lean, rule-decided book / crypto / forex

- **Real benchmark (#175):** Lean's default hourly SPY feed ended 2021-03, so every run charted a constant; `runtime.benchmark_ticker` follows the daily SPY subscription.
- **Simulator against Lean (#176):** `aq evaluate --attribute-lean` rebuilds a run's daily P&L per component (within $2 of Lean) and `scripts/lean_calibration.py` compares the simulator rung by rung; correlation 0.38 -> 0.70, but R-CAL failed (branch B), so the gates stay frozen and alpha is judged ungated.
- **Rule-decided book, crypto and forex (#179-#181):** R-BOOK picked a 20-bar rebalance with 40-bar holds, R-CRYPTO limit exits, a route-aware fee and smaller graduate caps, and R-FX6 dropped the forex sleeve.
- **Parity (#177, #178):** live flattens Lean's fill-forward forex bar as the dataset does, and a late-bar symbol keeps its own tick's cross-asset payload.
- **Latency and housekeeping (#182-#184):** `_build_model_input` 2.75 -> 1.8 ms and expert inference 79 -> 16 ms a tick; the full four-split dataset rebuilt with the active scaler and 13.7 GB of backups deleted; the teardown hang reproduces on the newest Lean image (#104 environmental).
- **Lean results (#185, #186):** BT1 +6.72% (Sharpe +0.55 without risk-free), BT2 +5.28% (+0.44), drawdown 5.4-5.5% against a 5% limit; fees fell by more than half, but the gain sits in the seen holdout and the slower book lost on the backtest stretch, so no edge is demonstrated.

## Phase V6.1.0 — A simulator that models Lean, rule-decided book / legacy / models, every non-IB problem closed

- **Phase-0 defects (#187):** the holdout report selects the holdout window, the rank-signal fail-open is logged, attribution follows the component that opened a position and the run's own config, and a NumPy deprecation is gone.
- **Forex holiday calendar (#189):** the dataset, timeline and parity replica follow Lean's market-hours calendar, on which no forex bar is delivered on a holiday.
- **Simulator mechanisms (#190):** the daily member pass, a whole-portfolio kill switch, weekend crypto, the 12-position cap, the analyzer's verdicts and the legacy signal, each through the shared pure functions; R-CAL2 stays branch B but close (correlation 0.67-0.71, agreement 76-94%).
- **Gate reading closed (#196):** live counts a crypto pair's IC event twice per date; the offline gate now does too (agreement with live 73% -> 92%).
- **Rules on every rebalance phase (#194, #195):** no retrained model beats the installed ones by more than seed noise (R-MODEL9), the head blend, the 20/40 book and the cost model stay, and legacy L2 passes the margins but fails R-LEGACY's clause, so it went to the owner (declined in V6.2).
- **Latency and crypto venue (#191, #192):** the feature path did not regress (the host and container are the cost), and `aq render-lean-config` warns that IB cannot fill crypto.
- **Lean results (#196, #197):** BT1 reproduced V6 BT2 order for order (+5.28%, Lean is deterministic); BT2 with a 0.80 cap was worse (+3.80%, drawdown 7.80%), so the cap stays 1.0.

## Phase V6.2.0 — Lean's Sharpe measured right, idle cash in T-bills, CI green, three leads decided by rule

- **CI (#198):** the red run was one test reading the gitignored `ml/model_weights.json`; it brings its own artifacts, and `scripts/clean_checkout_test.ps1` runs CI's command on a checkout without gitignored files.
- **Lean's statistics (#199):** `evaluation/lean_statistics.py` reproduces Lean's Sharpe / Sortino / PSR exactly (`aq evaluate --lean-stats`); the risk-free file is refreshed from FRED (5.49% -> 4.69% average) and `runtime.trading_days_per_year` is 365 (owner decision).
- **T-bill cash sweep (#200):** `portfolio/cash_sweep.py` holds idle NAV in BIL outside the strategy and its risk controls, which read the strategy's own value; predicted +$10.1k, Lean +$10.7k.
- **Rules (#201-#203):** R-DEDUPE keeps the crypto double count (validation +0.58, backtest -0.09), R-STAGGER adopts no tranche book (S2 passes every margin but widens the phase range), R-MODEL10 installs nothing (no ensemble beats the 0.034 yardstick); legacy L2 declined by the owner.
- **Faster host (#204):** on a 4-core Docker-in-Docker Codespace `_build_model_input` costs 0.6 ms, a Lean run ~10 minutes, and every teardown is clean, so #104 is the PC.
- **Lean results (#205):** BT1 = BT3 = BT2: +16.85%, Lean Sharpe -1.673 -> +0.082 (-0.776 on the old basis), drawdown 4.30%; the strategy alone earned $6,148 (Sharpe +0.54 without risk-free), the rest is carry, not alpha.

## Phase V6.3.0 — The README's Backtest Statistics, the kill switch and the staggered book decided by rule, Codespaces on a budget

- **Backtest Statistics (#206):** `evaluation/backtest_statistics.py` computes López de Prado's ch. 14 measures for the portfolio and the strategy without its carry, rendered by `evaluation/readme_statistics.py` and refreshed by `aq backtest` / `aq evaluate --lean-report`; the README section is restructured with one TOC entry per point.
- **One run per report (#207, #208):** every Lean-reading flag resolves the run the same way (explicit, pin, newest), and the T-bill sweep is its own class in every per-class report.
- **Rules (#210-#212):** R-CAL3 branch B (the gates stay frozen), R-KILL branch C (a longer window locks too rarely, the release band loses -0.06), R-STAGGER2 keeps one book (S2's interquartile range widens 0.50 -> 0.67); nothing ships.
- **Codespaces and the Lean host (#209, #214):** AGENTS.md rule 13 (on only while a job runs), scripted Lean and engine checks on a temporary DinD Codespace, and the whole offline phase in one training-Codespace session.
- **Lean results (#213):** BT4 equals BT2 in all 1,596 order events (+16.85%, Sharpe +0.082), so BT5 was not run; the strategy holds 0.17x of NAV, hits 51.7% and has a deflated Sharpe of 46% over 22 trials.

## Phase V6.4.0 — Twelve leads closed by pre-registered rules, Lean book-call probabilities, a paper protocol, data to 2026-10-16

- **Data (#215):** 12 sessions appended to all 105 files in the stored Yahoo vintage (a splice factor puts the new rows on the old basis; FRED rows only after the cutoff): 144 files, 0 changed rows up to 2026-09-30, on the PC and on the Codespace; the dataset gained 1,296 rows and resolved labels, nothing else moved.
- **Rules (#216-#226), every rule written before its score:** the crypto double count stays (R-DEDUPE2 -0.10 on the pooled span); the gate hides weakness (engaged-day IC 0.088 against 0.129 on the vetoed backtest days, so the staggered book and the kill-switch design close by their precondition); the direction heads are uncalibrated noise (direction = diagnostic only); the legacy budget, the legacy-input retrain, within-class ranks, expert exclusion and the residual head change nothing.
- **Shipped by rule (#221, #225), Lean confirm open:** the book rebalances every 10 sessions and holds 20 (as-live Sharpe validation -0.45 -> +0.15, backtest +0.89 -> +1.06, turnover 7.5x -> 10.8x) and the crypto graduates leave the main book (`class_weight_caps.crypto.core_only`: they earned about -$70 net over 61 round trips in BT4 against the core's +$3.9k over 13).
- **Instrumentation (#227, #228):** book calls carry their head probabilities in the book history and `aq evaluate --classification-parity` scores them against the offline head (tolerance fixed in advance); `aq evaluate --paper-check` turns a paper or Lean run into the paper protocol's checklist and bands; the book history can be written in paper mode (bounded record).
- **Default-off knobs shipped and tested:** `risk.kill_switch.trip_confirm_bars`, `gating_network.disabled_experts`, `rank_signal.normalization: "sector_relative"`, `portfolio_book.tranche_adjust_fraction` and a direction overlay hook in the simulator; calibration, engaged-day, trade-bootstrap and trial-registry tooling.

## Phase V6.4.1 — The two Lean runs on the PC, the adopted book reverted, the engine image and the parity verified

- **BT5 (#229, #227):** the V6.3 book with the probability logging over 2023-07..2026-10-16 equals BT4 in all 1,596 order events through 2026-09-30 (+50 in October), makes +14.77% (strategy $3.9k, Sharpe +0.35 without risk-free; October cost it about $2.2k) and proves R-L11: all 444 book calls match an offline prediction (accuracy +0.0023, log-loss -0.0008 apart, inside the tolerance).
- **BT6 (#230, #221, #225):** the book the offline rules adopted (10-session rebalance, 20-session hold, crypto core only) lost $2.3k net in Lean (the strategy -$10.9k, Sharpe -1.12 against +0.35, drawdown 5.20% against 4.33%) and fails R-LEAN13 (`evaluation/lean_verdict.py`), so `config.json` keeps 20 / 40 with the graduates in.
- **Engine image (#214):** built on the PC (about 2 hours: the CUDA torch wheels) and answering `/api/assets-status` with HTTP 200 and the 2026-10-16 FRED cache; the image id is in `ml/evaluation/v640/engine_image.txt`.
- **Recompute and freeze:** every offline README block ran again locally on the shipped config (the feature permutation audit was stopped after an hour: it does not read the book config), the README is pinned to BT5, the paper bands are frozen from it in #228, and the clean-checkout view of the suite ran on the PC.

## Phase V6.4.2 — BT6 split in two on Lean, the holdout dataset refreshed on the PC, README dating fixed, audit gaps closed

- **BT6 attributed (#234, #237):** R-LEAN14 (superiority, written before the runs) judged each half against BT5: the 10 / 20 book alone (BT7) cost the strategy $8.8k (Sharpe -0.44), core-only crypto alone (BT8) earned $2.2k more (Sharpe +0.46) but deepened the drawdown to 6.0%; neither is adopted, `config.json` is unchanged.
- **Lean on the 4 GB PC (#235):** `lean.json` sets `algorithm-creation-timeout: 600` (the engine key behind the 90 s ceiling, #16; importing `main` took 4 m 15 s), the Lean CLI probe waits 120 s, and a WSL VM that will not boot is started by hand before Docker attaches.
- **README dating (#231-#233):** every Lean window label reads the run's configured end (Lean charts two days past it), the run history has a Status column (shipped / kept / rejected by rule) and a date, and the walk-forward blocks carry their run's date and are judged against the installed models (owner: no retrain while models and data are unchanged).
- **Holdout dataset on the PC (#238):** `scripts/splice_holdout_dataset.py` builds only the holdout window (~400 MB instead of ~8 GB) and splices it into `full_dataset.csv` behind an overlap guard on 32,179 rows; the holdout now runs to 2026-10-15 (as-live Sharpe +1.44 -> +0.92, the October weeks cost it as they cost BT5) and every offline README block was recomputed on it; the feature-permutation audit ran to the end for the first time on the PC (9 h, 68 inputs; the class one-hots and `dist_52w_high` carry the multitask model's validation IC).
- **#141 closed in a live run:** BT5's feature snapshots carry non-zero real-rate and dollar sensitivities in every one of 1,197 snapshots.
- **Smaller gaps (#236):** `lean_verdict` uses each run's frozen config, the retraining gate no longer points Lean at a model folder, a dropped README pin is announced, the DinD pull freezes run configs, and AGENTS.md, the portfolio / evaluation READMEs and the parity table match the code.

## Phase V6.4.3 — Lean 4 proofs of the shared functions, a pre-registered signal search, research and audit tools, the `aether_quant` library

- **Formal verification (#240):** `formal/` holds Lean 4 + Mathlib models of the functions `main.py` and the simulator share (book neutrality and construction, sizing, risk controls, kill switch, cost model, order gate, reconciliation, sleeve guard, hash chain, JSON safety): 143 theorems and lemmas over any ordered field, no `sorry`.
- **What the proofs found (#241-#244):** the sector cap does not survive the dollar-neutral step (5 of BT5's 38 rebalances, by up to 1.45 pp; new default-off `neutrality.reapply_sector_cap_after_dollar_neutral`, an owner call); a non-positive per-name cap erased or flipped the book; a NaN target became a full short, a NaN base a NaN weight, a negative multiplier product escaped the position cap on the wrong side, a zero lookback read the whole history (all fixed fail-safe, finite inputs bit-identical); hash-chain truncation is invisible (`verify_chain(expected_tail_hash=)`).
- **Signal search without a retrain (#248):** R-MODEL11 (17 trials written before any score, one dated amendment) found nothing: the grid's probability of backtest overfitting is 0.66, and every candidate that beats the installed book on one split loses on the other; the holdout stayed unread and R-LEAN15's Lean run never triggered. `config.json` is unchanged.
- **What the model knows (#246, #247):** the installed model's validation rank IC (0.004) is below an asset-identity prior (0.021) and an asset-class prior (0.066); the rank_20d heads keep none of their train IC, the sector-neutral heads 27-30%; the whole-history beta in the residual / beta-neutral labels inflated their backtest IC by 0.007 / 0.022 (as-of labels and `beta_estimation` for a retrain).
- **Simulator against Lean (#249):** R-CAL4 on BT5 / BT7 / BT8: daily correlation 0.61 / 0.44 / 0.58, branch B stands; the rebalance phase is the biggest gain and the live-gate replicas the biggest loss on every run; the candidate without them helps all three but misses the BT5 clause, so nothing is adopted.
- **Research and audit tools, and the library (#250):** `aq research`, `aq evaluate --pbo / --factor-spanning / --audit-leakage / --overfit-report / --calibrate-sim-lean`; `aether_quant` re-exports the shared pure functions, the tools and the Lean cases (pinned public surface, `lib` / `research` extras, a quickstart; the wheel passes the smoke test in a clean venv).
- **Housekeeping (#239, #245):** the stopped training Codespace was deleted (owner); `tests/test_aq_cli.py` no longer rewrites the README's render stamps; `scripts/clean_checkout_test.ps1` silently tested HEAD whenever the diff held a non-ASCII character (git now writes the patch, a failed apply stops the run); the editable install was refreshed through the repo venv's pip (the system Python's pip is broken).

## Phase V6.4.4 — A retrain on honest labels, a trend sleeve and the sector cap decided by rule, a proof of alpha, the priors corrected

- **Data to 2026-11-02 (#258):** 11 sessions appended to all 105 files in the stored vintage, 0 changed rows up to 2026-10-16 on the PC and on the training Codespace; `available_to` and the holdout end follow (a data-only change).
- **The retrain (#260, #261):** seven multitask recipes on as-of labels (the sector-neutral head as the target, within-class ranked inputs `features/cross_sectional_inputs.py`, regularisation, ListNet, append mode) judged by R-MODEL12, written before any score; no candidate reaches the identity / class priors, every backtest as-live Sharpe is below the installed book's, PBO 0.37, the holdout unread: `ml/` unchanged.
- **The priors were mostly an artifact (#259, #263):** percentile ranks in groups of different size have different means, so the "class prior" the installed model lost to in #247 rewards knowing a name's group; on group-centred labels the sector-neutral priors fall to ~0 and the installed head beats them.
- **A new alpha source (#262):** a directional time-series-momentum sleeve (`portfolio/trend_sleeve.py`, owner-approved) wins on 2014-2023 (net Sharpe +0.40) but loses in every variant on the 2023-07..2025-06 backtest, so R-TREND1 keeps it off; it was never wired into `main.py`.
- **Simulator trust (#264):** R-CAL5 re-derived the live-gate replicas from the engine's fills (`evaluation/gate_replica_audit.py`); the research default tracks BT5 at 0.73, the one candidate option lowered it, branch B stands.
- **Lean (#266, #267):** BT10 (the shipped book on the new data) repeats BT5 fill for fill through 2026-10-16; BT11 re-applies the sector cap after the dollar step and passes R-LEAN16 (strategy Sharpe +0.268 against +0.263, drawdown 4.98% both), so the key ships, the README is pinned to BT11 and the paper bands are re-frozen from it. #241 closed.
- **Proof of alpha (#265):** `aq evaluate --alpha-proof` reports per period the strategy's Sharpe with a bootstrap interval, its alpha against SPY / AGG / BTC with a Newey-West t, PSR and the deflated Sharpe; on BT11 R-ALPHA1 says not demonstrated (alpha t -0.07, DSR 3.8% over 78 trials; holdout and fresh-week alpha positive but not significant).
- **Fixes met on the way (#251-#257):** a CRLF shell script, a keepalive that let long jobs idle out, the training-Codespace docs, per-run model artifacts for DinD Lean runs, a stale as-live score cache for ranked inputs / ensembles, `pyarrow` missing on the Codespace, the DinD create on Windows PowerShell 5.1 and Docker 29's missing `/etc/docker`; the README run history now names the rule a verdict file records.

## Phase V6.5.0 — AetherVault for real, a Lean-grade instrument, and an honest search for an edge

- **Result (#279):** the target, Lean Sharpe >= 1 with a verified edge, was not reached. 46 pre-registered candidates ran; overfitting probability over the selection trials was 0.53, above the 0.5 limit, which ended verification.
- **AetherVault compatibility (#268-#271):** no candidate had ever reached the vault. `av` dropped `model.pt` and `scaler.pkl` from commits, the client could lose `av`'s output on Windows, rollback ran a repo-wide checkout, and a worker without `av` found out after a whole training run. All fixed; `.av` now holds real gate commits, and `tests/test_vault_contract.py` runs the real CLI.
- **`except Exception` in `main.py` never caught a Python error (#276):** Lean's star import exports .NET's `System.Exception` over the builtin, so about 40 fail-safe blocks did not do their job. Fixed with one import, and shown in a Lean run.
- **A trustworthy instrument (#272, #273):** `phase_v2.target_weights` executes a pinned weight file with no gates, and `evaluation/target_weights_engine.py` tracks it at a daily correlation of 0.992-0.9999999 and at most 65 bps a year, against 0.73 for the old simulator. The comparison found a $0 fee bug that flattered runs by about 250 bps a year.
- **Fair tests:** rules hashed and committed to the vault before any score (`rules.json` sha `ed4b1347…`), placebos that keep turnover and asset tilts, a truncation test of every sleeve for look-ahead, and a trial ledger that feeds the deflated Sharpe (now 124 trials). `data_pre2013/`, the one window nothing has read, is built and left unread.
- **What the search found:** only trend survives selection, and it is mostly exposure. Equity reversal, low volatility, FX momentum, carry and CFTC positioning failed, most with negative Sharpes. Every ML book, including a new set transformer and gradient-boosted rankers on honest walk-forward scores, was strong in 2019-2021 and negative in 2021-2023.
- **Errors in this phase's own work, caught before they shipped (#277, #278):** the alpha regression read BTC a day early, showing t 2.76 for what is t 0.83; and the plan's sticky velocity lock halted every run within months, so a first +0.655 was 8 months of rally then T-bills.
- **Open problems closed without IB (#38, #58-#61, #67):** all 43 option structures fill in Lean, live futures margin works against Lean's API, and `main.py` no longer crashes on an option asset. Real runs found a detector flagging fair prices as arbitrage (#274) and a short iron condor built wrong (#275). What is left needs IB data or an account.
- **Infrastructure:** `-Parallel N` runs many Lean backtests on one Codespace, proved order-for-order safe; a target-weights run takes about a minute per 2 years. AGENTS rule 12's "90-second limit" corrected to the 600 s in `lean.json`.
- **Owner decisions, 2026-11-05:** keep the crypto sleeve, spend the pre-2013 data, give SEC a contact at runtime only, Docker rebuild later. Amendments 2 and 3 recorded the new work before its scores; R-EDGE1 stays closed and the install is unchanged.
- **Pre-2013 read (`backtests/2026-11-05_07-05-37-1`):** crypto had no bars then, so the frozen rule tested multi-asset trend alone on 2004-06..2012-12. Sharpe 0.33 (Lean Sharpe -0.06, with idle cash and no T-bill sweep), alpha +1.8%/yr at t 0.83, drawdown 10.6%, and 6 of 20 time-shift placebos did as well: profitable before the data it was picked on, but not distinguishable from chance.
- **Earnings surprise (#280, #281):** with a contact SEC served 2,805 quarters for 47 tickers. The first two trials passed R-SLEEVE2 and every placebo (Sharpe 0.55 and 0.65), but the signal was defective: 53.6% of rows compared the wrong quarter, and splits read as large misses.
- **Docker on a new DinD Codespace (#282):** the runner now waits for the old daemon and clears its pid file, which had stopped the first start.

## Phase V6.6.0 — Alpha tested on evidence nothing had read: not verified, and the rest of the backlog closed

- **Verdict (#300):** zero of 28 pre-registered trials survived selection on never-read S&P 500 names and 701 Binance coins, so R-EDGE2's later clauses stayed unread and nothing was installed. The models show no skill (net alpha t -1.7 to -3.5); the best rule sleeve (accruals) reached 0.45 against 0.50.
- **The installed sleeve on coins it had never read (#301):** Sharpe -0.06, 2024 on -0.45, alpha t -1.94. On the same dates the 12 chosen coins score 0.33, so most of its 0.96 came before 2018. It stays installed under the owner's rule, and whether to keep trading it is the owner's call.
- **Earlier numbers corrected (#283-#288, #302):** Sharpes are now on excess returns and session annualisation, trial counts can't double (N 156, 164 after the addendum), alpha tools read the right data root and no longer book T-bill carry as alpha. `t3_trend_blend` and `t3_vix_scaled` lose their V6.5.0 passes.
- **New data, `data/` untouched:** `data_wide/` (653 tickers, EDGAR fundamentals, 694,447 insider trades, FINRA short volume, published factors, split by name and time in `evaluation/research_cells.py`) and `data_crypto_wide/` (701 coins, 190 stopped before the end). Downloads survive a dropped connection (#297).
- **Live path fail-safe (#289-#296):** a kill-switch trip liquidates in paper and live instead of freezing the book, a new weight row reaches a running algorithm, a rule sleeve no longer trips on a model's age, a non-sticky lock clears, a stopped name exits. `permitRiskExit` is proved in Lean 4 and differentially tested.
- **Lean found what stubs couldn't (#304-#307):** the CLI overwrote a root's symbol table through a hard link, token swaps sat inside pairs at up to 1,295x, a fill-forward copy hid a dead feed, and `main.py`'s combo limit order crashed on first use. All fixed; `main.py`'s own option order now fills, and BT24 still equals the pin on all 1,012 fills.
- **AetherVault 1.7.0 released (#268, #271, #298, #308):** 18 fixes (write-ahead queue, repo lock, corrupt state stops a commit, `av restore`, `av rm`; vault Probleme #195-#212), on PyPI and GHCR and pinned here. 16 queued commits drained to a real server, a candidate restored byte for byte from a fresh clone, and the Docker worker passes preflight.
- **A forward record that can't be backfilled (#299):** a scheduled Action appends one hash-chained row a session to branch `forward-ledger`; `aq evaluate --forward-ledger` verifies and judges it at 60 and 252 sessions. The first row is for session 2026-11-05, written about 5 hours after that close because the first dispatches found Yahoo leaves the newest bar's closes empty.
- **Decisions and evidence:** R-VEL1 keeps velocity off, recorded and enforced by paper readiness (#303). Venue evidence for #192 is in `venue_study.json`. The arbitrage detector nets dividends (#60). QuantConnect's terms were never accepted and no cash was spent; that step was not reached.
- **Addendum, 2026-11-06 (owner: keep the sleeve on paper, research more before committing):** a second search round of eight trials on cell S found nothing (best Sharpe 0.57, second half 0.21; #310), and N is now 164.
- **Hosts:** training Codespace about 2026-11-05 20:10-23:00 UTC and again 2026-11-06 09:08-10:54 UTC (round 2, code sync), stopped and kept. DinD Codespace 2026-11-05 23:01 UTC-2026-11-06 00:41 UTC, deleted. Everything else ran on the PC; the owner's clock read one hour later.

## Phase V6.6.1 — A third search found no verified alpha; generations that hand over, an automated research cycle, a library of the whole project

- **Verdict (#315):** zero of ten more pre-registered trials survived on cell S against the unchanged bar, so nothing was frozen, the holdouts stay unread and nothing was installed. Nearest: a slower pooled composite at Sharpe 0.58 (second half 0.29, needs 0.40) and pooled accruals at 0.47 (needs 0.50); quarterly accruals have the strongest signal (IC t 2.60) at 0.45.
- **Why the models looked like price models (#314):** fundamentals cover 1.4% of member rows in 2009 and 51% in 2010, so their early training windows held near-constant inputs. A new audit counts each of its 18 looks in N, and `--train-start` lets a model read only years holding its inputs; it did not rescue them.
- **New evidence:** quarterly trailing-twelve-month accruals, net operating assets and capex growth from a new EDGAR download (138,573 rows, in their own file, so the file earlier trials read is byte-identical; the contact was never stored).
- **Generations that hand over (#319):** weights blend upstream of the file the target-weights path reads, so `main.py` didn't change and Lean, the engine and the live path read one file. R-BLEND1 passes in Lean: daily correlation 0.99999 against the engine, 0.004 bps a year, and a blend at share 1.0 equals the pin on all 1,012 fills.
- **No schedule protects capital from a zero-alpha generation (#318):** R-GLIDE1 found no policy that qualifies, so a 252-session ladder stands by rule. Admission does the protecting, and the owner's tiered rule R-ADMIT1 is now code.
- **The forward ledger's timing (#313):** it credits a crypto decision one bar the book never earns, so its daily series correlates 0.04 with the engine. The chain stays as it is; a new file, `forward/generations.jsonl`, tracks the engine at 0.993.
- **An automated cycle (#321):** `aq cycle status`, `research`, `daily`, `decide`, `retrain`, `promote`, `schedule`; a generic round runner in place of hand-written phase scripts; a daily workflow on free runners; `GET /api/generations` and an Operations panel. Anyone can retrain with `aq cycle retrain --host local|codespace`, resumable, with a RAM preflight, and the Codespace host stops the machine however a run ends.
- **The library covers the project (#322):** 24 facade modules over every subsystem, six more packages in the wheel, and the trainers' split helpers moved to a module with no torch.
- **A dynamic glide (#323, owner, 2026-11-06):** up to four generations hold capital at once, each one's share computed from its record shrunk toward its claim, and shares move smoothly with no jump on entry. New stages `fading` and `winding_down` keep a generation short of its claim on the book while it still earns.
- **Verification moved to a Codespace (#324):** `scripts/codespace_verify.ps1` runs every CI job against the working tree before a commit, and `scripts/codespace_prove.sh` builds the proofs.
- **Fixes met on the way (#316, #317, #320, #325):** a second freeze could have reopened a held-out cell; the forward ledger's `decide` drops `top_k`; two Codespace pushes at once corrupted each other's archive; a test driver hung forever wherever `webui/dist` was built, and `-CodeOnly` dropped `tests/data`.
- **Verification:** every CI job on a Codespace (Python 3.11) against the final tree, in a clean checkout of `origin/main` plus its changes (`scripts/codespace_verify.ps1`): the suite 4,751 passed, 34 skipped, 0 failed, coverage 85.75% against the 80% gate; all 15 `aq test` buckets; ruff 0.16.4; the guard tests; actionlint 1.7.7 with 0 errors in 4 files, the new workflow included; the web UI's `tsc`, oxlint, vitest and build; the CLI smoke; the wheel outside the checkout, 0 failures across 27 subcommands; the Python 3.10 byte-compile; the parity job; gitleaks, no leaks; pip-audit, no known vulnerabilities; hadolint; the test count at 4,785.
- **Hosts:** training Codespace 2026-11-06 about 15:50-17:09 UTC, and again from about 18:20 UTC for the calibration, the proofs and the full verification, stopped and kept. DinD Codespace 16:26-17:09 UTC for BL1, BL2 and the engine check, deleted; another from about 19:25 UTC for BL3, BL2 again and the Docker checks, deleted. Everything else ran on the PC.
- **Freeze:** `config.json` sha256 `b58a67d521a48c129032ea692a58dc4e5b8eebe4a0c61a26b3bf518eb3d5d509`, `main.py`, `ml/target_weights.csv` (`57240be0…`) and `ml/forward/candidates.json` unchanged. README pin stays `backtests/2026-11-04_18-10-49`. Nothing is committed: the owner commits, and the new workflow starts with that push.

## Phase V6.6.2 — A documentation pass: leaner docs, facts that update themselves, statistics of the shipped book

- **Every doc rewritten (#327):** README, root docs, sub-readmes, `architecture.md` and `infrastructure.md` were cut to what is true today and turned into bullets and tables. Version tags and stale references went, and the README now leads with both jobs: the self-adapting thesis, and the toolkit for other algorithms.
- **Library section:** the README explains `aether_quant` with a worked example, and a test runs that example so it can't rot.
- **Facts that update themselves (#328):** `docs_facts.py` and `aq docs sync` keep counts, windows, versions and ticker lists true through `<!--fact:key-->` markers, and a full `aq test` syncs them. `tests/test_docs_facts.py` fails on a stale fact, and on a path, `phase_v2` key, `aq` command or problem number that no longer exists in a living doc.
- **Statistics recaptured for the shipped book (#329):** Backtest Statistics now reads only the pinned sleeve's run: new Benchmarks and Alpha by Period tables, a headline table under the intro, and Monte Carlo of the Lean run. The rank book's tables moved to a generated `development/research_results.md`. The pinned run itself is unchanged, and the current code reproduces it order for order.
- **Logs condensed:** `Problems.md` and `Changelog.md` were condensed by rule, keeping open entries nearly whole and older fixed ones as problem and fix. Numbers are unchanged, and full text is in `development/backups/`.
- **Hosts:** training Codespace `aq-Training-Ground-Fixed` for the full CI check, 2026-11-07 12:22-13:04 local, then stopped. No DinD Codespace and no Lean run: the pinned run is unchanged.
- **Verification:** `scripts/codespace_verify.ps1`, every CI job: 32 stages passed, 0 failed. Suite 4,779 passed in a clean checkout and 4,809 in the real tree, coverage 86%, `ruff check .` clean.

## Phase V6.6.3 — CI repair: the cycle example needed an installed package

- **Why CI was red since V6.6.1 (#331):** `tests/test_aether_quant_quickstart.py` runs each example in a child process. `examples/aether_quant_cycle.py` imported `aether_quant` without putting the repo root on `sys.path`, which only worked where `pip install -e .` had run (the dev PC, the Codespace), so both `python-tests` jobs failed on V6.6.1 and V6.6.2 while every other job passed. The example now adds the root itself, as the quickstart already did.
- **A guard for the class:** a test requires every example to insert the repo root before its first `aether_quant` import, since a child process doesn't inherit pytest's `pythonpath`.
- **Hosts:** none. No Codespace and no Lean run; `main.py`, `config.json` and the book are unchanged.
- **Verification:** the old example fails and the fixed one runs with the editable-install finder removed; the failing test, the docs and packaging guards, and `ruff check .` pass locally. The full CI run is on the push.
