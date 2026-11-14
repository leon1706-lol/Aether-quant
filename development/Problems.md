# Problems

Every bug and infrastructure issue found in this codebase, oldest first, with how it was fixed or why it stayed open. Numbers never change, because code and docs cite them; #73-76 don't exist, and #88 and #112 appear twice.

**Entries:** <!--fact:problems.total-->358<!--/fact--> up to #<!--fact:problems.last-->360<!--/fact-->: <!--fact:problems.fixed-->325<!--/fact--> 🟢 `fixed` (changed and verified), <!--fact:problems.partial-->12<!--/fact--> 🟡 `partial` (shipped, verification pending), <!--fact:problems.closed-->18<!--/fact--> 🔴 `closed` (no code fix: declined, moot or superseded). Severity runs from 1 (cosmetic) to 10 (data loss or safety). Full text of older entries: [`backups/`](backups/README.md).

**Open now** (each needs a broker key, a forward record or the laptop):

- **#192** Live crypto cannot fill through Interactive Brokers
- **#228** L12: the paper-period protocol and its band check
- **#299** A forward record nothing could backfill didn't exist
- **#301** The installed crypto rule failed on coins it had never read
- **#313** The forward ledger credits a crypto decision one bar the book never earns
- **#319** Generations that share a book and hand over
- **#321** Anyone can retrain, on any machine with the RAM
- **#323** A dynamic glide: three or more generations, smooth, with shares from each one's record
- **#338** IB field test: what the Lean samples cannot show about options and futures

---

### 88a. Lean CLI's generated Windows dependency mount was unreliable, and startup imported the training stack
🟢 `fixed` (V5.1.11) · 6/10

**Problem:** On some Windows Docker Desktop hosts Lean CLI's generated temp `requirements.txt` mount was rejected even though project files were readable; separately, `main.py` importing `performance` at module scope pulled the training/PyTorch graph into Lean's 90-second startup isolator window. **Fix:** `aq backtest` builds a cached local image with Redis pre-installed (no generated requirements mount), the Windows wrapper grants Docker read access to Lean-created temp dirs, and `main.py` defers `evaluate_all_triggers` to dashboard view; the missing `httpx` runtime dep was added to `requirements/lean-runtime.txt`.

### 1. `experience-worker` crash loop — missing `numpy` dependency
🟢 `fixed` · 6/10

**Problem:** `experience/observation_metrics.py` imports `numpy`; `requirements-worker.txt` (backing `experience-worker`) never listed it — container crash-looped with `ModuleNotFoundError`. **Fix:** Added `numpy>=1.24.0`; same proactively applied to trigger-worker requirements.

### 2. `Dockerfile.worker` missing `execution/` copy
🟢 `fixed` · 6/10

**Problem:** `experience/simulated_portfolio.py` imports `execution.order_gate`; `Dockerfile.worker` never copied `execution/` — rebuild would fail with `ModuleNotFoundError`. **Fix:** Added `COPY execution/ ./execution/`; same pattern applied to `Dockerfile.trigger_worker`.

### 3. Simulated portfolio/positions snapshot not mode-aware
🟢 `fixed` · 5/10

**Problem:** Webui Positions panel/summary always read real (flat, uninvested) `self.Portfolio` even in `observation` mode, contradicting mode-aware drawdown beside it. **Fix:** Added `_snapshot_portfolio_summary()`; `_snapshot_positions()` mode-aware via `SimulatedPortfolioState` when real orders blocked.

### 4. Webui: empty space above Market Scene panel
🟢 `fixed` · 2/10

**Problem:** CSS Grid default `align-items: stretch` padded shorter left column to match taller right column. **Fix:** `items-start` on outer grid; wrappers → `flex flex-col gap-4`.

### 5. Webui: Signal Distribution / Rejected By Reason tables overflow the panel
🟢 `fixed` · 2/10

**Problem:** Long reason strings forced `<table>` wider than its Grid track; default `min-width: auto` blocked shrinking. **Fix:** Flexbox rows replace `<table>`; added `min-w-0`, `break-words`.

### 6. `aether-grafana` container name collision blocks the real Grafana service
🟢 `fixed` (moot, no code change needed) · 3/10

**Problem:** Orphaned unmanaged `aether-grafana` container (port 3000, non-compose volume) would have blocked `docker compose up -d grafana` (same name). **Fix:** No action — Grafana removed from stack in V2-18 (replaced by React tracing dashboard); collision moot.

### 7. ~85GB of orphaned duplicate Lean engine images + stale containers/volumes
🟢 `fixed` · 2/10

**Problem:** Two untagged 42.5GB `quantconnect/lean` images, stale one-off containers, unused pip-cache volumes, stray/unpinned tags accumulating disk. **Fix:** Removed confirmed orphans (`docker rmi`/`docker volume rm`) after two passes — first missed image `650dd8d4063a` plus unrelated Grafana volume/image, corrected on follow-up.

### 8. Bare `pytest` (no path) fails from repo root
🟢 `fixed` · 3/10

**Problem:** Bare `pytest` also crawled `backtests/*/code/tests/` (each backtest copies full algorithm code incl. tests) — ~76 duplicate-module-name collection errors. **Fix:** `pyproject.toml` `[tool.pytest.ini_options]` sets `testpaths = ["tests"]`.

### 9. Total-drawdown trade lock never auto-clears within a run
🟢 `addressed` (manual override, not a default-behavior change) · 4/10

**Problem:** Total-drawdown lock never clears within a run (unlike daily lock) — real run showed it blocking ~79% of events after one early breach. Treated as intentional capital-preservation behavior, not silently patched. **Fix:** Added `phase_v2.risk.manual_trade_lock_override` (read once per session rollover), `aq trade-lock --on/--off/--auto` CLI, auto-clear-on-successful-promotion hook in `retraining/orchestrator.py::promote()`. Default sticky behavior unchanged.

### 10. `ci.yml`'s `test` job fails on GitHub's Linux runner — root cause found and fixed
🟢 `fixed` · 3/10

**Problem:** The first clean-install bare-`pytest` CI run surfaced four masked problems: a nonexistent PyPI package name, pytest not adding the repo root to `sys.path`, two reference files swallowed by a blanket `.gitignore` rule, a Python 3.11-vs-3.14 float-summation difference in `empirical_duration_beta()`, and a Lean-backtest skip-guard checking binary presence rather than a usable Lean Data folder. **Fix:** Corrected the package (`lean>=1.0.225`), set `pythonpath = ["."]`, committed both reference files via a `.gitignore` exception, replaced the exact-zero variance check with a `<1e-12` tolerance, and required a real Lean Data file in the skip guard.

### 11. `_write_state()`'s per-bar throttle was unreachable
🟢 `fixed` · 6/10

**Problem:** Dead guard clause meant 7 output files fully rewritten every bar instead of once per timestamp. **Fix:** Removed impossible clause (`if ... and signals is None`).

### 12. `observation_equity_curve.csv` quadratic rewrite (N-per-bar entries + full-file rewrite every bar)
🟢 `fixed` · 7/10

**Problem:** `mark_to_market()` ran once per symbol per bar, producing `N·B` equity-curve entries instead of `B`, and #11's every-bar flush plus full-file CSV rebuild made write cost `O((bars·symbols)²)`. **Fix:** `on_data()` now accumulates closes and calls `mark_to_market()` once per bar, with an append-only flush (`_flush_observation_equity_csv()`) tracked by a written-count offset.

### 13. Per-bar/per-poll `config.json` reads on every session rollover, uncached
🟢 `fixed` · 5/10

**Problem:** At Daily resolution the once-per-session rollover check fires every bar, each firing doing uncached `open()`+`json.load()` of `config.json` in several places (`main.py`, `retraining/worker.py` poll loop). **Fix:** New `execution/config_cache.py::read_cached()`, an mtime-gated cache keyed on both path and loader (a path-only key collided across readers and crashed `_recompute_broker_config()` on bar 1 of a real backtest).

### 14. Redis push in backtest mode — deliberately left unoptimized
🟢 `resolved` (confirmed no-op, no code change needed) · n/a

**Problem:** `experience/redis_queue.py::push()` does blocking Redis write every bar even in backtest mode — skippable for perf, but unconfirmed downstream dependency made skipping risky. **Fix:** No code change — owner confirmed nothing reads backtest-mode experience events downstream from Postgres.

### 15. `ensure_derived_crypto_daily_series()` silently discarded yfinance-backfilled crypto history on every `train.py` run
🟢 `fixed` · 7/10

**Problem:** Function rebuilt derived crypto daily zips (ETHUSD/LTCUSD) via full-overwrite `ZipFile` write from sparse raw minute data, wiping 1000+ days of yfinance-backfilled history to 3-4 rows every `train.py` run. **Fix:** Reads existing zip, merges by date — fresh minute-derived rows win only where real minute data exists; other dates survive.

### 16. `main.py::initialize()` exceeded Lean's hard 90-second isolator timeout at 20 assets
🟢 `fixed` · 8/10

**Problem:** Loading all model/expert/topology artifacts plus deriving ~40 config values inside `initialize()` pushed isolator-timed cost past Lean's non-configurable 90s cap at 20 assets, so every `lean backtest .` failed. **Fix:** Split into a minimal Lean-critical path (dates/cash/subscriptions/warm-up) plus `_ensure_ready()` carrying artifact/config loading, deferred to the first `on_data()` (no isolator limit there).

### 17. Matplotlib font cache rebuilt from scratch on every single `lean backtest .` run
🟢 `fixed` · 6/10

**Problem:** Lean's `AlgorithmImports` bridge imports matplotlib, so ephemeral per-run containers rebuilt the font cache (20-40s) every run, occasionally breaching the 90s isolator cap even after #16. **Fix:** `main.py` sets `MPLCONFIGDIR` to a host-mounted `.matplotlib_cache/` before any other import, so the cache survives containers.

### 18. Two structural "never recovers" traps suppressed real backtest trade count to 12 over 3 years
🟢 `addressed` (opt-in statistical bypass, default behavior unchanged) · 5/10

**Problem:** A one-time mass liquidation crossing the 12% total-drawdown limit froze trading for the remaining 374 days of a 3-year backtest — the sticky lock plus a `peak_equity` running-max that never fell meant it could never self-clear; an earlier-firing 8% twin sat in the regime `risk_off` drawdown branch. **Fix:** Opt-in `phase_v2.backtest.bypass_safety_gates` (default `false`, backtest-only) bypasses only these two mechanisms, with other gates fully active and live/paper unaffected.

### 19. Neural-network webui tab's gating exclusion went stale the moment gating became learnable
🟢 `fixed` · 2/10

**Problem:** Gating hardcoded excluded from `/neural-network` list ("no learned weight matrix"); 3D scene render order hardcoded to exactly 5 names — both stale once gating gained optional learned model. **Fix:** Removed gating from exclusion list; wired through generic network-summary path; added to render-order array.

### 20. `Dockerfile.retraining_worker` never copied `risk/`, so `retraining.worker` could not have started
🟢 `fixed` (superseded by the consolidated engine image, #30) · 7/10

**Problem:** `retraining/orchestrator.py` imports `risk.manual_override` at module level, but the worker image's COPY list lacked `risk/`, so every start crashed with `ModuleNotFoundError`. **Fix:** added `COPY risk/` (and `train_multitask.py`); V5.5.0's single engine image later removed per-worker COPY lists altogether.

### 21. Per-bar model forward-pass count doubled (5 → 11) — measured, not currently a problem
🟢 `measured, not currently a problem` · 2/10

**Problem:** Multitask/sequence models roughly doubled per-symbol-per-bar forward passes (5 → 11; batching keeps top-level calls at 5), never measured against any budget. **Fix:** No code change — measured via `aq profile --batched`: ~12ms mean/symbol/bar, negligible vs only enforced constraint (Lean's 90s `initialize()` isolator cap, unrelated to per-bar cost).

### 22. `tests/test_retraining_worker.py` silently ran real training (subprocess-level hang, up to ~30 minutes per test)
🟢 `fixed` · 6/10

**Problem:** 7 of 10 tests never updated to mock newer `train_multitask`/`train_sequence` stages — with real artifacts present they fell through to genuine subprocess training, up-to-30-minute timeouts (looks like hang). **Fix:** Added `patch("retraining.worker.train_multitask")`/`train_sequence` to all 7, matching existing mock pattern.

### 23. BTCUSD volume-feed unit discontinuity blew up the sequence model's RMSE 31x
🟢 `fixed` · 7/10

**Problem:** BTCUSD raw volume jumped ~520,000x on one date (a real Coinbase feed unit-convention change), producing a 5.2-million-percent single-day "return" through an unclipped `StandardScaler` that poisoned 30 rows of the sequence window — 66%+ of the backtest's squared error. **Fix:** Three layers: clamp `volume_change_1d` to `[-1.0, 20.0]`, winsorize scaler-fit columns pre-fit, and clip scaled values to `±10σ` (persisted to `scaler_stats.json` so `main.py` applies the same bound at runtime), plus an automated regression-quality gate.

### 24. `train.py` never applied Lean's own split/dividend factor files — offline dataset had fake ±74%/+745% "returns"
🟢 `fixed` · 8/10

**Problem:** `train.py`'s independent raw-zip reader bypassed Lean's split/dividend adjustment, so real corporate actions (AAPL's 2020 4-for-1, USO's reverse split) produced fake ±74%/+745% "returns" in every label/feature spanning the boundary — an offline train/runtime parity gap (Lean's own engine was unaffected). **Fix:** New `train.py::apply_split_adjustments()` reads each equity's real Lean factor file and rescales OHLCV exactly as Lean does; `yfinance_backfill.py` switched to `auto_adjust=True`, with a per-security-type label-outlier guard as defense-in-depth.

### 25. No quality gate ever existed for regression heads (magnitude/volatility/rank) — only direction MCC was gated
🟢 `fixed` · 5/10

**Problem:** Only direction models quality-gated; regression heads had none — how #23's 31x blowup shipped silently a whole session. **Fix:** New `train.py::assess_regression_quality()` gates on RMSE/MAE and backtest/train RMSE ratios; wired into `train_multitask.py`/`train_sequence.py`; surfaced on `/neural-network`.

### 26. `main.py`'s sequence-model runtime buffer size never read the trained model's own `window_size`
🟢 `fixed` · 4/10

**Problem:** Runtime buffer size came only from `config.json`, never model schema — retrained model with different window silently disabled sequence signal via shape-mismatch exception, unsurfaced. **Fix:** New `resolve_sequence_window_size()` — schema value wins when loaded; config fallback otherwise.

### 27. Phase 2's new era/fold-splitting functions crashed on real training runs — assumed datetime input, but the real dataset's `date` column is plain strings
🟢 `fixed` · 6/10

**Problem:** `split_into_non_overlapping_eras()`/`purged_embargoed_folds()` did Timestamp arithmetic on `np.asarray(dates)`, correct only for datetime input — real callers pass stringified date columns, so the first real run crashed despite all unit tests passing on synthetic datetime fixtures. **Fix:** Both functions (and an identically-bugged caller) coerce via `pd.to_datetime(np.asarray(dates))`, robust to string/Timestamp/datetime64.

### 28. Portfolio book's `"short"` signal silently zeroed to no position
🟢 `fixed` · 4/10

**Problem:** `_build_dynamic_sizing_payload()` guard recognized only `{"buy", "sell"}` — never updated when `"short"` became valid, so book-selected shorts sized to exactly zero. Never observed in practice (book feature defaults off). **Fix:** Guard recognizes `{"buy", "sell", "short"}`.

### 29. Multi-asset-class support (bonds/futures/options + IB) — explicit non-goals
🟢 `fixed` (core multi-asset-class trading is fully implemented; remaining items are permanent non-goals) · n/a (scope note)

**Problem:** Tracked multi-asset-class gaps after the initial architecture pass — options order placement against a resolved contract, real derivatives-macro data, per-asset-class book slot caps — were originally deferred. **Fix:** All three resolved later: real option-contract order placement, real futures/options derivatives-macro features (offline and live), and an optional `per_asset_class_slots` book parameter (default `None`, byte-identical to the prior pooled ranking).

### 30. `Dockerfile.retraining_worker` missing `data_pipeline/` (and pre-existing: `liquidity/`) copy
🟢 `fixed` · 7/10

**Problem:** A top-level `data_pipeline.fred_backfill` import was never copied into `Dockerfile.retraining_worker`, which also pre-existing missed `liquidity/` — either would crash the first retrain. **Fix:** Both COPYs were added, then the whole class was structurally eliminated by the July 17 consolidation (the Dockerfile is gone; compose builds a consolidated `aether-quant-engine:latest` via `COPY . .`).

### 31. Infrastructure/latency pass — `aq test` silently ran a real Lean backtest, per-bar inference hot path never profiled, CI Docker builds never cached
🟢 `fixed` · 8/10 (aq test) / 6/10 (inference latency) / 4/10 (CI cache)

**Problem:** `aq test`'s Lean-backtest file checked binary presence only, so routine runs paid a real (over-an-hour) backtest cost; the inference hot path was unprofiled and CI Docker release builds were uncached. **Fix:** Opt-in `lean_backtest` pytest marker (excluded by default; `--lean`/`--full` opt-in) plus per-subsystem `aq test` flags, a new `scripts/profile_inference.py` harness, hot-path fixes (causal-conv Python loop → batched `einsum`; four per-expert dispatch calls → one batched), and `cache-from`/`cache-to: type=gha` on the release Docker step.

### 32. Latency deep-dive follow-up — weight-array/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension attempt
🟢 `fixed` · n/a (optimization pass)

**Problem:** Re-profiling after #31 showed repeated `numpy.asarray()` conversions of the same static JSON-loaded weights every bar were the largest remaining cost. **Fix:** `convert_state_dict_arrays()` converts once at load (no downstream API change), batched-stack caching precomputes expert weights in `_ensure_ready()`, and it added `aq profile`, opt-in per-symbol multiprocessing (default off, sequential fallback), and a C++/pybind11 extension (`cpp_inference_ext`) accelerating the batched linear layer.

### 33. Execution/risk realism pass — real `SlippageModel` wired to fills
🟢 `fixed` · 7/10

**Problem:** `build_liquidity_decision()` computed a real spread+impact estimate every bar that nothing consumed — no security had a `SlippageModel`, simulated fills hardcoded zero slippage, and historical backtests had systematically too-good fills. **Fix:** Pure `slippage_amount()`/`resolve_slippage_bps()`/`resolve_fill_slippage()` in `execution/order_gate.py`, threaded into both the Lean fill path (a new `_LiquidityAwareSlippageModel` adapter) and the simulated-fill path; the cost source and safety clamp were later made config-configurable.

### 34. Real limit-order support — every tradable asset class, config-gated
🟢 `fixed` (`PartiallyFilled` never appears at daily resolution: a standing caveat) · 6/10

**Problem:** every order was an all-or-nothing `MarketOrder()` / `SetHoldings()` across all five asset classes. **Fix:** `phase_v2.limit_orders` real `LimitOrder()` support for every class: one submit path, an `on_order_event()` fill callback, per-class timeout with market fallback, and the futures/option bookkeeping bugs found on the way.

### 35. Disabling an asset class never liquidated already-open positions
🟢 `fixed` · 6/10

**Problem:** Flipping `phase_v2.futures_risk.enabled`/`options_risk.enabled` false mid-run zeroed new sizing but left already-open positions (signal derivation unaware of flags) — sat untouched, silently failing every bar. **Fix:** Pure `resolve_asset_class_enabled()`/`should_liquidate_disabled_asset_class_position()` + per-bar sweep `_liquidate_positions_for_disabled_asset_classes()` liquidating newly-disabled classes' real/simulated positions; equity/crypto/bond have no such flag.

### 36. Latency profiling extended beyond inference — `build_market_topology()` found to be a much larger per-bar cost than the entire inference step
🟢 `fixed` · 6/10

**Problem:** per-bar subsystems besides inference were never profiled; `build_market_topology()` cost ~500-600 ms per bar, more than whole-universe inference. **Fix:** `scripts/profile_subsystems.py` / `aq profile --<subsystem>`, and a correlation-stability cache that skips the embedding when pairwise correlations moved less than a (percentile) tolerance; enabled since V5.5.0 (`topology.cache_enabled`, percentile 75).

### 37. Inference tail latency (p99 3-5x p50) — investigated and fixed
🟢 `fixed` · 4/10

**Problem:** p99 inference ran 3-5x p50 and a stale profiling file suggested a regression. **Fix:** the stale file was unrelated; paired runs isolated GC pauses as the tail, and `gc.freeze()` after model load ships on (`gc_tuning.freeze_after_load_enabled: true`, unfrozen before shutdown for #104).

### 38. 2-leg vertical spread selection for options — explicit scope-in of a previously-non-goal feature
🟢 `fixed` (verified in Lean through main.py, V6.6.4; real combo routing needs an IB key and is #338) · n/a (feature scope-in)

**Problem:** Multi-leg spread selection was explicit non-goal (#29); this pass closes minimal 2-leg vertical-spread slice. **Fix:** New `select_vertical_spread_legs()`/`build_vertical_spread_position_sizing()` (net-vega sized), wired through `risk/asset_class_router.py` + new `_apply_option_spread_order()` using Lean's own `OptionStrategies` atomic combo-order primitive (previously completely unused here); two real bugs (field-existence check ordering; early draft breaking option orders entirely for spread case) caught/fixed during implementation. **Verification:** 20 new tests (leg selection/sizing/degrade paths) + critical zero-behavior-change parity for single-leg path. **V6.5.0:** verticals fill through `OptionStrategies` on Lean's sample chain (`scripts/lean_smoke/option_structures.py`), and `main.py` with an option asset now initializes and runs a month of the sample (it crashed at initialization, #276). **V6.6.4:** `scripts/lean_smoke/main_option_scenarios.py` drives `main.py`'s own order path in Lean on the sample AAPL chain (June 2014, `ml/evaluation/v664/lean_smoke_option_*.jsonl`, run on a DinD Codespace). A bull call spread enters through `OptionStrategies` combo orders (2 orders) and a second position opens beside it.

### 39. Final pre-backtest bug sweep — 4 fixes found and fixed before this project's first real `lean backtest .` run
🟢 `fixed` · 6/10 (test-harness bug) / 5/10 (liquidity threshold collision) / 3/10 (limit-order timeout) / 2/10 (book-slot crash risk)

**Problem:** A final pre-backtest sweep found four defects: a wrong dict-key path silently failing three Lean coverage assertions, two liquidity thresholds collapsed to one value (merging a two-tier gate), a limit-order timeout handler contradicting the dependency's "unknown status = still pending" contract, and no shape validation on optional per-asset-class book-slot config. **Fix:** Fixed the key path, restored the `thin < high_impact` ordering, made the handler pop-without-cancel only on genuinely terminal statuses, and added a `normalize_per_asset_class_slots()` pure validator degrading gracefully on malformed entries.

### 40. `aq backtest` silently re-pulled the ~42.5GB Lean engine image on every run
🟢 `fixed` · 5/10

**Problem:** `lean backtest .` resolved the mutable `quantconnect/lean:latest` unpinned, so whenever QC moved the tag even machines with the full 42.5GB image cached re-pulled — indefinitely, every clone and run. **Fix:** Pinned the immutable `quantconnect/lean:17900` by default (always passed explicitly), with `aq backtest --image <other>` for deliberate newer-build opt-in.

### 41. First real backtest: only 14 trades, none ever closed
🟢 `fixed` (superseded by #43) · 6/10 (blocks a statistically meaningful backtest)

**Problem:** First real backtest produced 14 orders, all openings, zero closes — model's `probability_up` clustered 0.46-0.49 vs buy/sell thresholds 0.50/0.42, almost nothing crossing either line. **Fix:** None here — proposed threshold-tightening lever diagnosed but never shipped. #43 found real causes structural (position-cap overshoot, risk vetoes blocking exits, neutered circuit breaker, no exit mechanism) plus a training-pipeline defect, pivoting trading entirely to `rank_20d`/`portfolio_book`.

### 42. Pre-live security review — broker/API credentials could be published; DB exposed to the LAN behind a repo-published password
🟢 `fixed` · 7/10

**Problem:** A pre-live review found the runbook instructed hand-editing real IB credentials into git-tracked `lean.json`, `.dockerignore` didn't exclude secret files from published images, Postgres/Redis were published to `0.0.0.0` behind a password published in this public repo, and nothing structurally prevented future secret commits. **Fix:** A credential render step (`aq render-lean-config`) overlays secrets from a gitignored `.env.live` onto a gitignored `lean.live.json` (tracked `lean.json` stays empty), the secret list is mirrored into `.dockerignore`, DB/Redis are bound to `127.0.0.1` with a fail-closed live-mode guard, and `aq secrets-check` plus an opt-in pre-commit hook were added.

### 43. Full pre-live model overhaul: trading-logic bugs + training-pipeline bugs, pivot to the one significant signal
🟢 `fixed` (see #52/#54) · 9/10

**Problem:** A second backtest after #41's recalibration produced bit-identical results (same 14 trades/profit), showing calibration had zero effect on actual trades — causes spanned trading logic (soft position-cap overshoot, sell-vetoing risk logic, a sell threshold ~10σ from live output, a neutered drawdown breaker, no stop-loss/trailing/max-holding-age exits) and training (untrained epoch-1 checkpoints, degenerate threshold search, an MoE blend diluting skill to 0.5, no skill-floor gates, 35/85 static one-hot inputs, ~52-row crypto training, and trading that ignored `rank_20d`/`rank_5d`, the only statistically significant signal). **Fix:** Rewrote early stopping with a `min_best_epoch` floor, fixed the threshold-search bounds, unified asset-context columns, removed dead features, raised the `min_training_rows`/skill-floor gates, zeroed no-skill experts, wired `portfolio_book` to trade `rank_20d` directly, bypassed the exit veto, added safety exits (max holding age + trailing stop) and an adaptive sell band, fixed the same-bar position cap, re-armed the drawdown breaker, and fixed the crypto/`InteractiveBrokersFeeModel` crash.

### 44. Lean CLI couldn't feed the retraining loop — undocumented second `requirements.txt` convention
🟢 `fixed` · 6/10

**Problem:** `main.py`'s `ExperienceQueue` silently no-oped during every real `lean backtest .` run because `redis` was missing: Lean CLI auto-installs deps from a project-root `requirements.txt`, separate from the repo's `requirements/requirements.txt` convention Lean never reads, and everything else happened to exist in the image. **Fix:** A repo-root `requirements.txt` containing `redis>=5.0.0`, cross-referenced from `requirements/README.md`; later superseded by #88a's Lean CLI Windows dependency-mount workaround.

### 45. `av` (Aether-Vault CLI) was broken on this machine — never actually run once in this repo
🟢 `fixed` · 4/10

**Problem:** `retraining/vault_client.py`'s commit stage shells out to `av`, which failed every call (`ModuleNotFoundError: questionary`) and had never been initialized (`.av/` absent) — invisible because `commit_candidate_to_vault()` degrades gracefully by design. **Fix:** Installed `questionary` into the correct environment (`av.exe` resolves via a separate user-scoped Python 3.14 install, not the repo `.venv`) and ran `av init --mode local -y --no-repl` in the repo root.

### 46. `xreadgroup(block=0)` meant "block forever," not "don't block" — idle Redis-stream workers timed out every cycle
🟢 `fixed` · 6/10

**Problem:** `experience/postgres_worker.py`/`audit/postgres_worker.py` called `xreadgroup(..., block=0)` believing it non-blocking, but Redis `BLOCK 0` blocks forever — with a client `socket_timeout=5`, every idle poll raised a timeout exception (invisible to `fakeredis`, which doesn't reproduce blocking-socket behavior). **Fix:** Removed `block=0` from both call sites; the default `None` omits `BLOCK`, letting the existing correct `sleep(1)` idle loops work.

### 47. `retraining-worker`'s `./data` volume mount was read-only — `train.py` could never complete inside the real container
🟢 `fixed` · 7/10

**Problem:** Compose mounted `./data:/app/data:ro`, but crypto daily-series derivation (#15) must read-then-write `data/crypto/coinbase/daily/*.zip` every invocation, so the container crashed with `OSError: Read-only file system` — never caught before because rehearsals ran `train.py` on the (writable) host. **Fix:** Changed the mount to writable (`./data:/app/data`).

### 48. Force-recreating `retraining-worker` mid-cycle orphaned a stuck `retraining_events`/`model_versions` row — no startup reconciliation existed
🟢 `fixed` · 6/10

**Problem:** Recreating `retraining-worker` mid-cycle killed the in-flight `train.py` before it reported back, leaving `retraining_events`/`model_versions` rows stuck `"running"`/`"candidate"` so the cooldown check blocked all future retraining; the container also ran `python -m retraining.worker` as PID 1 without an init process, so a subprocess killed on orchestrator timeout could become an unreapable zombie that blocked even `docker compose stop`. **Fix:** Startup reconciliation `fetch_stale_active_events()`/`reconcile_stale_running_events()` marks stale `running`/`planned` rows `failed` (rejecting still-`candidate` `model_versions` rows) after a configurable `stale_running_timeout_seconds` (default 10800s), and `init: true` gives the Compose service Docker's tini so killed subprocesses are reaped.

### 49. Full end-to-end retraining-loop rehearsal against the real Compose stack — three real cycles ran, all correctly rejected; rollback rehearsed both ways
🟢 `verified` · n/a (operational-maturity verification, not a bug)

**Problem:** N/A — a rehearsal to prove a genuine closed loop rather than mocked-unit-test logic; one follow-up (the `lean` CLI absent from the worker image, so `backtest_gate` silently no-ops rather than crashing) was a known deliberate infrastructure gap, later settled by #62. **Fix:** None (verification exercise).

### 50. This dev machine's 4GB RAM couldn't reliably run a real `lean backtest .` — blocked verifying #34/#36/#37/#38
🟢 `fixed` (superseded — see #54) · n/a (hardware constraint)

**Problem:** Four consecutive real `aq backtest` attempts failed at Lean's hardcoded 90-second `initialize()` isolator cap, root-caused to plain top-level imports (torch/pandas/sklearn) taking ~82 seconds under memory pressure (~300MB free on this 4GB host) — not a code regression; it blocked verification of #34/#36/#37/#38. **Fix:** Narrowed `main.py`'s `from audit import ... (which transitively pulled unused Postgres/status-export code) to `from audit.redis_queue import ...`, trimming in-window import cost; also documented that failed `lean backtest` containers aren't reliably cleaned up, leaving orphaned `lean_cli_*` containers holding memory.

### 51. `GET /api/assets-status` 500'd in Docker — `lean.json` (entry #42's exclusion) was never mounted back in, and the reader didn't degrade gracefully
🟢 `fixed` · 5/10

**Problem:** `GET /api/assets-status` 500'd in real deployment: #42 excludes `lean.json` from the published image but nothing volume-mounted it back at deploy time, so `build_assets_status_from_disk()` hit an uncaught `FileNotFoundError`. **Fix:** Added a read-only runtime mount (`./lean.json:/app/lean.json:ro`) on the `engine` service (never baked into the image, preserving #42); the reader now catches `FileNotFoundError` and degrades to an empty `lean_config` so `ib_readiness_status()` reports gracefully instead of 500ing.

### 52. The rank-pivot roadmap: trading path switched to `rank_20d`, universe expanded 30→74 assets, four Stage-4 regularization gaps closed
🟢 `fixed` (retrained and backtest-verified — see #54; one caveat still open, below) · 9/10

**Problem:** Trading path traded the noise-objective direction head (backtest MCC ~0.02-0.04) instead of `rank_20d` — the one genuinely skillful signal — and even that far faster than its ~20-day horizon supports. **Fix:** Five config-gated changes: (1) `strategy_mode`→`long_short`, rank-based sizing enabled, sequence `rank_20d` blended into traded probability, book widened top/bottom 8; (2) 5-bar rebalance scheduler `should_rebalance_this_bar()` matching horizon; (3) universe 30→74 (54% equity/30% bond/16% crypto), dataset rebuilt to 113,804 rows; (4) rank-IC early stopping, dead direction-head loss down-weighted (not removed), seed-ensembling + horizon-consistency regularization in `train_multitask.py`/`train_sequence.py`; (5) previously dead `purged_embargoed_folds()` wired into real diagnostic (`purged_cv_rank_20d`).

### 53. GitHub Codespaces set up as cloud training offload; a real Alpine-base devcontainer bug found and fixed
🟢 `fixed` · 5/10

**Problem:** The 4GB machine spent hours wall-clock on ~800 CPU-seconds of training (#50/#52), and Codespaces setup hit a real bug — the `docker-in-docker` feature silently swapped the pinned Debian image to Alpine, breaking `pip install` against musl libc (matching upstream `devcontainers/images#1114`); deeper, Codespaces containers run unprivileged so Lean/Docker backtests cannot run there at all (a platform limitation). **Fix:** Dropped `docker-in-docker` (training needs none) and kept only `sshd`, prepended a CPU-only `pip install torch --index-url .../cpu` to `postCreateCommand` (a bare install resolved a GPU-failing CUDA build), and `.gitignore`d 9 inconsistently-tracked generated `ml/` artifacts.

### 54. First real `aq backtest` against rank-pivot models: Sharpe -0.59 → +0.40, plus a universe-selection bug (BNBUSD/TRXUSD never listed on Coinbase)
🟢 `verified` / `fixed` · n/a (verification milestone) / 3/10 (ticker bug)

**Problem:** Rank-pivot roadmap (#52/#53) needed real `lean backtest .` confirmation. Separately, two Stage-3 crypto tickers from #52's expansion (BNBUSD, TRXUSD) could never subscribe — Coinbase never listed Binance Coin or TRON pairs, though Yahoo Finance returned price history masking the mis-selection. **Fix:** Swapped for ETCUSD (Ethereum Classic) and ZECUSD (Zcash), both confirmed present in Lean's local Coinbase symbol-properties database, backfilled via `aq fetch crypto --apply`.

### 55. Every webui tab except `/` 404'd on a direct load when served by FastAPI
🟢 `fixed` · 6/10

**Problem:** The webui bundle mounted as `StaticFiles(directory=WEBUI_DIST, html=True)`, and `html=True` maps only directory paths, so a direct load/hard refresh of `/risk`, `/topology`, `/neural-network`, `/tracing`, or `/operations` returned a raw 404 (client-side nav worked, masked in dev by vite's SPA fallback). **Fix:** A `SpaStaticFiles(StaticFiles)` subclass overrides `get_response()` to fall back to `index.html` on 404, limited to extensionless paths so genuinely missing assets (`/assets/*.js`) still 404 (careful to catch Starlette's own `HTTPException(404)`, not FastAPI's subclass).

### 56. `train_topology.py` learned prototype z offsets on the pre-V4 `0..1` scale
🟢 `fixed` · 1/10 (latent; unreachable until a model exists)

**Problem:** V4-W3 made z a real `0..100` correlation-distance axis in 3D embedding mode, but prototype z offsets were still emitted on the old `0..1` formula, so the overlay effectively moved nodes in x/y rather than z. **Fix:** Z is normalized to `[-1, 1]`, with `topology/learned_topology.py::_score_node()` scaling by the active `max_offset_z` before the same clamp as x/y (provably identity-preserving in 2D, proportionally larger in 3D) and an `offset_schema` detection field since no old-format model ever existed.

### 57. Futures/options had a live incremental-vs-absolute order-sizing bug — fixed, plus position scale-up for all 5 asset classes
🟢 `fixed` · 5/10 (dormant, reachable only via `futures_risk.enabled`/`options_risk.enabled`, both default off)

**Problem:** Equity/crypto/bond add-to-position was blocked by a simple `main.py::_apply_signal()` gate, but futures/options had none — worse, correctly-recomputed **absolute** per-bar targets fired through **incremental** primitives (`MarketOrder`/`Buy`) every bar the signal held, stacking contracts unbounded, and options could orphan a position by re-selecting strike/expiry each bar without closing the old one. **Fix:** New `risk_controls.py::compute_incremental_order_quantity()` makes futures/options submit only the signed delta toward the absolute target, unconditionally (a genuine bug fix, no flag), with two opt-in tiers: `position_scaling.enabled` scale-up/down with a churn guard and `rotate_on_drift` liquidate-then-reenter.

### 58. Architecturally-sound options: multi-position book, symmetric scale-down, held-contract sizing, spread combo orders (V4.4)
🟢 `fixed` (verified through main.py in Lean on the sample chain, V6.6.4; the IB part is #338) · n/a (architecture pass, no defect)

**Problem:** Review of #57's options paths found six gaps: single-leg options scaled up only, never down; spreads couldn't scale down at all (no `Sell`-side combo primitive); drifted position with `rotate_on_drift` off frozen rather than re-managed; single-slot tracking capped book at one position per underlying; rotation's same-bar liquidate+reenter had no netting; spreads had no limit-order path. **Fix:** Full multi-position book (`option_positions_by_symbol` as `dict[str, list[dict]]`, capped by `max_positions_per_underlying`, default 1 = byte-identical), pure sizing functions for already-held contracts/legs, Sell-side combo scale-down, combo limit orders; real gap caught during verification and fixed pre-landing (at-cap re-pricing firing even with `position_scaling` disabled). **Verification:** Default path unreachable — `options_risk.enabled=false` forces vega budget to 0; tests 1558→1591 (`tests/test_options_strategy.py`, `tests/test_order_gate.py`); `main.py` exhaustive call-graph trace only (untestable in isolation); real fill/margin behavior remains IB-unverified. **V6.6.4:** through `main.py` in Lean: a bull call spread enters, scales down on the Sell side (2 orders, `reduced_option_multi_leg_bull_call_spread`), a scale-up at the cap keeps it (`options_multi_leg_kept`), a second position opens under `max_positions_per_underlying=2` (a straddle) and a third at the cap gets no decision. 6 orders, 2 positions held at the end.

### 59. Full `OptionStrategies` coverage: all 43 QuantConnect option structures, registry-driven (V4.5)
🟢 `fixed` (all 43 fill in Lean's engine, 8 of them also through main.py's own order path, V6.6.4; the IB part is #338) · n/a (architecture pass, no defect)

**Problem:** Only 2 of QuantConnect's 43 `OptionStrategies` factory structures implemented (#57/#58); user wanted full coverage so the model drives any structure gap-free. **Fix:** Near-duplicate per-strategy functions replaced by `MULTI_LEG_STRATEGY_REGISTRY` data table (all 43, transcribed from real Lean C# source, correcting 2 mistranscribed leg-direction assumptions found en route) dispatched through ~10 shared shape-family leg selectors; `options_margin_sizing.py` for naked/uncovered/bounded-max-loss tiers; `main.py` generalized to `"multi_leg"` record kind; gated behind `multi_leg_strategies_enabled` (default false, byte-identical). **Verification:** Tests 1589→1656 (registry completeness, all 43 strategies vs synthetic chains, margin tiers, router gating); rewrite verified via trace plus full pre-existing suite unchanged (proves legacy vertical path identical through generalized code); combo surface remains IB-unverified. **V6.6.4:** through `main.py`'s path on the sample chain 8 of the 43 structures found legs and filled (bull_call_ladder, call_backspread, naked_call, naked_put, put_calendar_spread, short_call_backspread, short_put_calendar_spread, short_straddle); the sample chain is thin on the few bars the window reaches, so the other 35 found no legs there and are not claimed (the V6.5.0 smoke builds all 43 by hand and Lean fills each). Our own margin tiers sat beside Lean's margin change per structure: margin_naked 1007 (naked call) to 7183 (short straddle) against Lean's own charge, and `vega_budget` structures cost Lean nothing.

### 60. V4.6 — bounded options follow-ups, arbitrage mispricing detector, Forex/FX, analytic bond-ETF duration/convexity
🟢 `fixed` (forex live-verified; the detector runs inside main.py's router on the sample chain, V6.6.4; IB quotes are #338) · n/a (architecture pass)

**Problem:** multi-leg positions were double-counted against the position cap, rotation could thrash, there was no forex asset class or mispricing detector, and this Lean version has no bond security type. **Fix:** distinct-position counting, a rotation cooldown and same-bar netting, per-asset strategy overrides, `options_arbitrage_detector.py` (off), `risk/forex_risk.py` with pair specs, and analytic bond duration / convexity / DV01 (informational). **Verification:** tests 1656 -> 1722; forex traded live in two Lean runs (220 fills, notional within 0.15%). **V6.5.0:** on a real chain the detector flagged everything (#274, fixed). **V6.6.4:** with the detector on, `main.py`'s router returns a `conversion` decision on the sample chain (dividend-netted) and returns none with it off; no order followed, as the gates did not pass it.

### 61. V4.7 — early-assignment/corporate-action modeling, a learned strategy-selector model, and bond analytics wired into the trained model
🟢 `fixed` (the assignment sweep runs in Lean and the selector trains, scores and reranks end to end on synthetic outcomes, V6.6.4; both stay default-off, and real outcomes need IB, #338) · n/a (follow-up/architecture pass, no defect)

**Problem:** Deferred from V4.6: full early-assignment/corporate-action modeling; learned model picking multi-leg strategies; bond analytics as real trained features (previously informational-only specifically to avoid forcing a retrain). **Fix:** `dividend_backfill.py` (yfinance ex-dividend history + cadence-based next-date projection); Barone-Adesi-Whaley American-exercise pricer; `options_assignment_risk.py` scoring; default-off auto-close sweep; capture path in observation-mode order branch (real-order path never fires without IB); `train_strategy_selector.py`, `inference/strategy_selector_inference.py`, router reranking (active only once model trained/enabled); 3 new bond features (`bond_analytic_modified_duration`, `bond_analytic_convexity`, `bond_dv01`) into `input_set`, computed in both `main.py` and `train.py` offline pipeline. **Verification:** Tests 1722→1813 (91 new, incl. American≥European price invariant and put-always-zero-assignment-risk invariant); `main.py` trace only. **V6.6.4:** the assignment sweep ran on a held bull call spread (latest score 0.0, no flag) but the June 2014 window holds no in-the-money contract through expiry (the spread expires 2014-07-25), so Lean's own exercise model was not exercised and is not claimed. `tests/test_train_strategy_selector.py` runs 400 synthetic `option_strategy_outcome` events through `main()`, the written model, `score_strategies` and the router's reranking: the calm regime prefers the condor, the stressed one the straddle, an unscored name sinks, nothing under 300 events or with one outcome class is written, and nothing lands under `ml/`.

### 62. Phase 4.8 — closing operational/surfacing gaps: `lean` CLI in retraining-worker, a `main.py` scoping bug fix, new Options & Strategy webui page
🟢 `fixed` · n/a (surfacing pass), plus one real bug rated 4/10 (silently wrong data persisted, never a crash)

**Problem:** A 3-agent audit found `lean` missing from the production image used by `retraining-worker`, the compose `data/reference` mount missing (silently zeroing Forex/futures/FRED specs), `aq` lacking a bulk-backfill dispatcher, stale `aq test` subsystem file lists, and a real bug where `corporate_action_payload` was computed in Pass 1's per-symbol loop but read in Pass 2's separate loop (no block scoping, so every symbol reused the last one's value); several V4.7 fields (bond analytics, assignment risk, dividend schedule, strategy-selector scores) were computed but never reached `state.json`. **Fix:** Added `lean` to production requirements plus a Docker socket mount, fixed the compose mount/comment, added `aq backfill <target>`, fixed the stale dict and threaded the payload through `pass1_state` per-symbol, wired all 5 fields into `signals[symbol_key]` in `_write_state()`, and added a `/options-strategy` page.

### 63. V4.9 Priority 0 — the #36/#50 profiling wrapper was never reverted: a live per-bar disk write on the hottest path
🟢 `fixed` · 6/10 (real continuous synchronous disk I/O on every symbol-bar call in any live/paper/backtest run)

**Problem:** #36's claim that the `_build_model_input()` wrapper "was fully reverted" (per #50) was false — `main.py` unconditionally opened `model_input_timing.log` and wrote a line every symbol-bar call, ungated, with 45,187 accumulated lines (~983KB) untracked in repo root. **Fix:** Impl renamed back to `_build_model_input`, wrapper deleted; dead `perf_counter` import removed; log file deleted. Real per-call timing collection remains an open task — `scripts/profile_inference.py`'s in-process harness (no disk I/O) intended path forward.

### 64. V4.9 Priority 4 — `_build_options_chains_payload()`'s gating, considered and declined
🟢 `fixed` (declined by design, no code change) · n/a (no code change — a documented decision)

**Problem:** A candidate optimization to gate `_build_options_chains_payload()` (runs once per bar per configured option asset) behind `self.options_risk_enabled`. **Fix:** Declined — configuring an option asset is already the deliberate visibility trigger (it feeds `state.json`/webui regardless of multi-leg trading), matching the "compute for visibility even when trading is off" pattern bond analytics/assignment risk follow, and it never appeared as a meaningful profiling cost.

### 65. V4.9 Priorities 1-3, 5-8 — sequence batching, topology percentile-tolerance caching, options chain-grouping hoist, non-blocking experience delivery, IPC benchmark, HFT documentation
🟢 `fixed` · n/a (feature/optimization pass, all off by default)

**Problem:** A profiling-roadmap continuation: the sequence encoder cost was paid once per symbol, the fixed topology cache tolerance was poorly calibrated, per-bar options cost was hoistable, live/paper experience-event delivery was blocking, the `ProcessPoolExecutor` IPC assumption was unmeasured, options profiling coverage was missing, and the framing of which latency work is genuine HFT-fork prep was unclear. **Fix:** Added batched sequence inference (`run_exported_sequence_multitask_model_batched()`, default off, falling back on <2 sequences or any failure), a percentile-based rolling-window tolerance, a hoisted `group_chain_by_expiry()` per routing call, non-blocking `ExperienceQueue.push()` (`async_enabled`, default off), an IPC benchmark confirming `ProcessPoolExecutor` is dramatically slower than sequential on this Windows/spawn machine, an `"options"` workload in `profile_subsystems.py`, and an architecture doc section separating genuine HFT-transfer work from daily-bar-loop speedups.

### 66. V4.10 — pure-function extraction of `main.py`'s exit logic, 4 webui quality fixes, and 15 new forex/FX assets fetched
🟢 `fixed` · n/a (feature/extraction/data pass)

**Problem:** Exit-decision logic (max-holding-age + trailing-stop) never extracted into a testable pure module unlike comparable decisions elsewhere. **Fix:** Extracted `evaluate_non_model_exit()`/`compute_position_exit_tracking_update()` into `risk_controls.py`; webui stable empty constants + `React.lazy()`/`Suspense` 3D-bundle split + removed dead routes + chart/format primitive tests; `"forex"` entry in `fetch.py` asset-class config plus bid/ask-synthesizing Lean CSV writer; `forex_pair_specs.json` 7→15 pairs, all fetched full-window (universe 74→89); `forex_risk.enabled` stays off by default.

### 67. V4.10 follow-up — opt-in live (Lean/IB-calibrated) futures margin source, toggleable via `aq config`
🟢 `fixed` (V6.5.0: the calls main.py makes ran against Lean's API on sample ES data: initial margin $4,180, multiplier 50, order filled, `scripts/lean_smoke/futures_margin.py`) · n/a (feature, off by default)

**Problem:** `futures_contract_specs.json` carried since V4.6 an explicit "documented future enhancement, not implemented" note asking to prefer IB's live margin over static reference numbers. **Fix:** Added `phase_v2.futures_risk.margin_source` (default `"static"`), settable via generic `aq config set`. `"live"` mode attaches Lean's local IB-calibrated `BuyingPowerModel` per futures security individually (never global `SetBrokerageModel`), queried via new `_resolve_futures_contract_spec()`; `build_live_contract_spec()`/`resolve_futures_margin_source()` in `risk/futures_risk.py` produce spec interchangeable with the static path; every live-margin call site wrapped in try/except falling back to static/default on any failure.

### 68. `cpp_inference_ext` was never built for the actual deployed image — closed via a soft-fail Docker build step
🟢 `fixed` · low (silent perf-only gap, not correctness)

**Problem:** The only compiled extension was hand-built for dev-machine Python 3.14 (ABI-incompatible with the deployed `python:3.11-slim`), and the Dockerfile lacked a compiler/pybind11/extension entirely, so C++ acceleration never ran deployed — a 100% silent gap. **Fix:** Added a soft-fail `RUN` step installing `build-essential`+`pybind11`, pip-installing `cpp_inference_ext`, and purging `build-essential` in the same layer, wrapped in `(...) || echo ...` so a toolchain/ABI failure degrades to the NumPy fallback rather than breaking the build; a `.dockerignore` block keeps locally-built incompatible binaries out of the published image.

### 69. Audit follow-up — `main.py` CI syntax-check gate, and a Windows-specific inference-parallelism slowdown guard
🟢 `fixed` · low

**Problem:** `main.py` had zero CI coverage, not even a syntax check (`AlgorithmImports` is undefined outside a real Lean process), and `phase_v2.inference_parallelism.enabled` was unguarded despite #65 measuring it dramatically slower than sequential on Windows/spawn — with the key also absent from `config.json`, so `aq config set` on it failed rather than silently succeeding. **Fix:** Added a `python -m py_compile main.py` CI step (parse only; mypy/pyright via `quantconnect-stubs` was declined as too noisy), a `windows_parallelism_slowdown_warning()` that fires `Debug()` only on win32 after real pool construction, a key-specific stderr warning citing the #65 measurement, and an explicit `phase_v2.inference_parallelism: {"enabled": false}` block in `config.json`.

### 70. V4.11 — full Codespace retrain + walk-forward executed, three latent `train.py` bugs fixed
🟢 `fixed` (the era-sign question moved to #71) · n/a (milestone)

**Problem:** the first real retrain surfaced forex quote bars dropped by the trade-bar parser, duplicate regime columns on an empty frame, a manifest `KeyError`, and stale forex zips on the Codespace. **Fix:** quote bars collapsed to midpoints, an empty-frame guard, a `.get()` fallback, and fresh zips re-synced.

### 71. Phase 4.12 — kill era-sign instability, close remaining non-IB items, expand breadth, alt-data + RL sizing
🟢 `fixed` · n/a (milestone)

**Problem:** 4 Docker-outage-blocked items: #68 linkage check, B1 topology training (#56), two user-run backtests, isolator timing at new 104-asset universe. **Fix:** Root-caused outage to stuck `wslinstaller.exe` wedging `WSLService` — required genuine cold restart (not "shut down then power on," which resumes the same broken session under Windows Fast Startup).

### 72. V5.1 Phase 1's net-edge cost gate blocked 100% of trades — Lean Backtest 1 produced 0 orders end to end
🟢 `fixed` · 9/10

**Problem:** The Priority 6.5 net-edge gate re-derived its own pass/fail from raw `net_edge_bps` instead of trusting `build_net_edge_decision()`'s `passes` field, and the "disabled" state still carried `net_edge_bps=0.0`, so with the `aggressive` preset's `min_net_edge_bps: 2.0`, `0.0 < 2.0` evaluated True every symbol/bar and routed every directional signal away from trading — 100% blocked, 0 orders for the whole backtest. **Fix:** Removed the re-derived comparison and `min_net_edge_bps` parameter from `build_market_analysis_decision()`, which now trusts `net_edge.get("passes", True)`, the single verdict already computed by `build_net_edge_decision()`.

### 77. V5.1 Phase 1's `min_rank_confidence_spread` gate defeated by its own cross-sectional normalization fix — real Lean Backtest 1 traded but lost money
🟢 `fixed` · 8/10

**Problem:** `_select_book_group()`'s conviction gate read the cross-sectionally-normalized `predicted_rank_20d` (introduced by the F1 fix, #73) instead of the raw score, and a fixed top-6/bottom-6 selection percentile-ranks to a ~0.90+ spread regardless of dispersion, so the `aggressive` preset's `min_rank_confidence_spread: 0.20` never disengaged the book across the whole 2019-2021 run — Sharpe −0.145→−2.526 and net profit +3.41%→−3.11%. **Fix:** Added an optional `spread_check_ranks` parameter to `_select_book_group()`/`build_rank_based_book()` that `main.py` builds from each symbol's pre-normalization `raw_rank_score` alongside the normalized `book_candidates`, changing only the engagement gate's input while sizing/confidence still read the normalized value.

### 78. `tests/test_retraining_worker.py` — 7 of 11 tests spawned a real, unmocked subprocess, adding ~17 minutes to every full suite run
🟢 `fixed` · 3/10 (dev-velocity/CI-cost only, no correctness impact)

**Problem:** 7 tests in `test_retraining_worker.py` patched the first four of `run_once()`'s five best-effort trainer stages but never `train_strategy_selector`, so each spawned a real `subprocess.run()` shelling `train_strategy_selector.py` (~140-168s apiece) — collectively ~1,050-1,200s of a ~28-minute suite. **Fix:** Added `patch("retraining.worker.train_strategy_selector")` alongside the other stage patches in all 7, matching the file's per-stage mocking convention.

### 79. `data_pipeline/fred_backfill.py::fetch_fred_series()` hung/reset on every request — FRED's graph-export endpoint requires HTTP/2, which stdlib `urllib` cannot speak
🟢 `fixed` · 7/10 (blocked V5.1 Phase 2's CODESPACE RUN 1 entirely — 0 of 12 FRED series fetchable)

**Problem:** stdlib `urllib.request` (HTTP/1.1-only) could no longer reliably reach FRED's `fredgraph.csv` endpoint — an external FRED-side change, not a regression — so all 12 series failed with read timeouts; a secondary finding was that the prior browser-spoofing `User-Agent` caused an immediate `RST_STREAM` even over HTTP/2, plausibly FRED's WAF cross-checking UA against the TLS fingerprint. **Fix:** Swapped to `httpx.Client(http2=True)` (adding `httpx[http2]>=0.27.0`) and removed the browser-spoofing `User-Agent` entirely.

### 80. `train.py::build_dataset_manifest()`'s new `computed_but_unused_features` (V5.1 Phase 2) flagged ~70 legitimate columns as orphaned on the first real dataset build
🟢 `fixed` · 6/10 (would have buried the 3 genuine orphans under ~70 false positives)

**Problem:** `train.py::build_dataset_manifest()`'s new `computed_but_unused_features` (V5.1 Phase 2) built on the post-scaling dataset but `_computed_but_unused_feature_columns()` excluded only `base_feature_names`/`context_feature_names` — never `scaled_feature_names`, `categorical_feature_names`, or raw OHLCV/bookkeeping columns — so it flagged ~70 legitimate columns as orphaned; tiny synthetic fixtures never included those column classes. **Fix:** Threaded `scaled_feature_names`/`categorical_feature_names` into the exclusion set and expanded `_NON_FEATURE_DATASET_COLUMNS` with `RAW_COLUMNS` plus `security_type`/`market`/`quality_tier`/`trading_eligible`/`training_eligible`.

### 81. `portfolio/book_neutrality.py::apply_book_neutrality()`'s sector-neutral step silently erased entire legs of the live/simulated book
🟢 `fixed` · 9/10

**Problem:** sector demeaning drove every member of a zero-dispersion bucket to zero, which is the normal case for equal-weighted roles; the all-forex bucket erased the short leg whenever forex was in it (`mean_names_short=0.00` with `bottom_n=6`). **Fix:** a bucket within `sector_max_net_weight` is left alone; above it the whole bucket is shrunk proportionally (sign kept) until its net equals the cap.

### 82. V5.1 Phase 4's walk-forward net-performance step crashed on window 1 — fed the exported model the wrong feature list (49 raw names instead of the 66 it was actually trained on)
🟢 `fixed` · 7/10 (crashed the entire walk-forward run on window 1)

**Problem:** V5.1 Phase 4's walk-forward net-performance call site passed the outer `feature_names` (49 raw pre-scaling names) instead of the 66-column `model_input_names` the models were actually trained against, crashing window 1 with `ValueError: _conv1d_causal: in_channels mismatch (49 vs weight's 66)`. **Fix:** Both call sites now use `dataset_manifest["model_input_names"]`.

### 83. V5.1 Phase 4's walk-forward sequence training hits a hard memory ceiling on the project's Codespace machine type for larger training windows
🟢 `fixed` (root cause found and fixed at start of Phase 5) · 6/10 (no corruption — degraded cleanly to multitask fallback — but weakened statistical power of 3 of 6 windows)

**Problem:** Walk-forward sequence training was SIGTERM-killed on windows >~130-147k rows (3 of 6 in CODESPACE RUN 3) while constructing the dense `(rows, 30, 66)` tensor; a partial fix (freeing the parent's held dataset) recovered one window but not the ceiling, root-caused to building the full `sequences` array once and extracting the backtest split ~250 lines later — ~1.08GB resident through the whole training loop on a 7.8GB machine. **Fix:** Moved the split extraction next to the train/validation splits, added `del sequences; gc.collect()` before training, and switched `evaluation/model_predictions.py::build_sequence_windows()` from float64 to float32 to match `train.py`.

### 84. Rank heads were sigmoid-squashed at inference but trained raw against an MSE target
🟢 `fixed` (V5.1) · 8/10

**Problem:** Rank heads (`rank_5d`/`rank_20d`/`sector_neutral_rank_20d`) trained raw linear output against a `[0,1]` percentile target, but export wrapped every head in a leftover `"sigmoid"` — compressing live `predicted_rank_20d` into ~[0.475, 0.75], silently tightening `min_rank_confidence_spread` ~4x, capping confidence near 0.5, and zero-sizing bottom-ranked shorts, all invisible to rank-quality gates since rank-IC is invariant under monotone transforms. **Fix:** Set the export activation to `None` for every rank head and added per-bar cross-sectional percentile normalization at inference (`portfolio/rank_signal.py::cross_sectional_rank_scores()`), since a pure ranking loss makes absolute output scale meaningless by construction.

### 85. `sector_mapping.json` covered 29 of the universe's 104 assets
🟢 `fixed` (V5.1) · 6/10

**Problem:** `sector_mapping.json` covered only 29 of the universe's 104 assets — 75 tickers (all 15 forex pairs, most crypto/equities) defaulted `"Unknown"`, making `target_sector_neutral_rank_20d` (a live head with `loss_weight: 0.3`) nearly duplicate plain `rank_20d` for 72% of the universe, while genuinely small sectors NaN'd under `min_sector_size: 3`. **Fix:** Added a full 104-ticker mapping (GICS-like buckets for equities; `Forex`/`Crypto`/`Fixed Income`/`Broad Market ETF` for the rest), leaving `AAA` deliberately unmapped as a documented ambiguous legacy ticker.

### 86. The constructed book was silently truncated by `max_active_positions`, not by rank
🟢 `fixed` (V5.1) · 5/10

**Problem:** `top_n=10 + bottom_n=10` requested 20 names but `max_active_positions=15`, so excess names were rejected in `self.symbols` iteration order — an accident of universe ordering, not conviction. **Fix:** Presets now set `max_active_positions >= top_n + bottom_n`, and when the cap binds, Pass 2 sorts candidates by rank-confidence so the strongest convictions survive.

### 87. `capacity_curve()`'s binding-ticker search let a forex pair's fake zero dollar volume dictate the whole book's capacity
🟢 `fixed` · 5/10

**Problem:** `capacity_curve()`'s binding-ticker search picked the lowest-average-dollar-volume held name, and forex pairs always report `liquidity_log_dollar_volume == 0.0` (Yahoo reports no FX volume), so any forex pair won automatically and produced a sub-$1 `capacity_usd` failing every promotion gate regardless of the rest of the book's real liquidity; a secondary bug was using `np.exp()` where `log1p()`'s inverse is `np.expm1()`. **Fix:** Excluded exact-zero tickers from the binding search (a true zero is no liquidity signal, not "most illiquid") and fixed `np.exp`→`np.expm1`.

### 88. A pre-backtest review found six critical bugs in code/config that had never executed a Lean bar
🟢 `fixed` · 9/10

**Problem:** the newly enabled net-edge gate, cost model, kill switch and reconciliation had six defects that together locked a half-dead book: long-only edge (every short vetoed), edge calibrated on the 1-day not the 20-day return (~14x too low), no minimum sample for the kill switch's Sharpe, reconciliation against pre-sizing weights, slippage measured as the overnight gap, and a corporate-action payload leaking across symbols; plus a sector cap tighter than the per-name cap. **Fix:** direction-aware edge, calibration on `target_return_{horizon}d` (28 -> 396 bps per rank unit), `min_bars_for_sharpe`, reconciliation on post-sizing weights within the universe, the slippage trigger parked until a fill-time reference exists, the payload carried per symbol, `sector_max_net_weight` 0.15.

### 89. The book went dead after 3 weeks in the first real V5.1 Lean backtest — two more bugs found and fixed, one root cause still open
🟢 `fixed` · 8/10

**Problem:** First real V5.1 backtest (2019-01-01→2021-03-31) opened 4 positions January 2019, closed them ~2 weeks later, then zero orders for remaining 2.2 years (Sharpe −61.3, 8 total orders). **Fix:** Added `min_return_std_for_sharpe` floor (default 0.0005), composable with existing bar-count guard; added `aq evaluate --calibrate-book-spread`, deriving threshold from real per-date raw-score dispersion via shared `compute_confidence_spread()` — calibrated 0.5014 (vs guessed 0.2/0.18), applied to base config and both presets; also fixed `cmd_evaluate()` bug where `--calibrate-book-spread` alone incorrectly triggered a full `--rank-book` run.

### 90. A real Lean backtest, once it finally traded continuously, showed Sharpe -4.2 to -4.4 against a +2.18 offline number — three compounding mechanisms found and fixed (V5.2.1)
🟢 `fixed` (V5.2.1; the investigation this entry's own open caveat seeded was continued and closed through #91-#93) · 9/10

**Problem:** Book traded continuously but Sharpe was −4.42 (gated)/−4.18 (bypassed) vs +0.26 to +2.18 offline. **Fix:** `simulate_rank_book()` gained opt-in `entry_lag_bars`; new `is_position_resize_permitted()` gates resizing to rebalance bars only; cost gate's `order_value` reflects actual incremental trade delta.

### 91. Book-history reconciliation (V5.2.2/V5.2.3) finds two unexplained live-vs-offline selection divergences
🟢 `fixed` (crypto/FX a log artifact, #97; NVDA/GE/WFC/BA the missing factor files, #100/#102; XOM's residual closed in V6.1.0, #187) · 9/10 -> 2/10

**Problem:** the new `--reconcile-book-history` found crypto/FX in offline's book on 107 of 112 dates and in live's on none, and only 35-55% equity overlap. **Fix:** `bar_index` counted every asset-class tick (now equity sessions only), an empty book force-sold everything, crypto/FX were not book-eligible, and the bond duration beta was recomputed every bar instead of locked once.

### 92. Deep-dive into the remaining NVDA/GE/WFC/XOM/BA/forex/crypto divergence finds crypto/FX never actually trade, and a systemic live-vs-offline risk-gate gap (V5.2.6)
🟢 `fixed` (V5.2.6) · 10/10

**Problem:** Crypto/FX were regularly selected but never placed a single real order — forex's synthetic quote-bar conversion hardcodes `volume=0.0`, tripping the liquidity gate's zero-volume block — and live carries ~10 risk/execution gates that offline's Sharpe engine never models, two of them duplicating a signal already an active input feature. **Fix:** Added `zero_volume_fallback_ddv` (always for forex; for crypto only when `quality_tier=="core"`) to substitute a realistic daily-dollar-volume estimate without bypassing participation/cost gates, added book-selection-aware confidence thresholds, narrowed the `risk_off`/`topology_elevated` overrides using real-data-derived thresholds, and added `aq evaluate --calibrate-confidence-threshold` plus a `book_member_decisions` diagnostic.

### 93. Forex order sizing rounds to zero at realistic book scale, and a sticky kill-switch trip locks out the book for 13+ months (V5.2.7)
🟢 `fixed` (V5.2.7) · 9/10

**Problem:** `_forex_lot_count_for_weight()` divided notional by full 100,000-unit lot value — at realistic 4-12% weights notional never reached one lot, so every forex order silently rounded to zero. **Fix:** New `compute_forex_order_units()` sizes orders in raw base-currency units, not lots (earlier lot-rounding design caught in review — would have reproduced bug under a new name).

### 94. Kill-switch sensitivity sweep, an offline gate-aware replay, a training-side gate-aware ranking weight (V5.2.8)
🟢 `fixed` · n/a (investigation and opt-in tooling)

**Problem:** was the kill switch's 26 trips in 2.2 years mistuned, and could training see the live gates? **Fix:** `evaluation/kill_switch_replay.py` (`--replay-kill-switch`, approximate by design) and an opt-in per-date gate-friendliness loss weight (`gate_aware_ranking_weights`); a 20-combination sweep showed the lockout is near-binary, so no config change.

### 95. Full-scale production retrain with gate-aware ranking weights promoted to active `ml/` (V5.2.9)
🟢 `fixed` · n/a (training round)

**Problem:** #94's weights had only a 3-epoch smoke test and no flag-off control. **Fix:** full Codespace retrain with the flag on, promoted to `ml/` (backup kept), plus a 6-window walk-forward; RL sizing stayed disabled (negative a third time).

### 96. Real limit-order support: stale docs corrected, `PartiallyFilled` made testable, two new offline diagnostic tools (V5.3.1, closes #34)
🟢 `fixed and verified` · 6/10

**Problem:** `phase_v2.limit_orders.enabled` was actually default-on all along, but `Problems.md`/`Changelog.md`/`execution/README.md`/a `main.py` comment claimed "default off. `PartiallyFilled` had never fired in 45 real backtests; partial-fill logic wasn't unit-testable (not importable outside Lean process). **Fix:** Docs corrected. Investigated future/option `fallback_to_market_on_timeout=false` asymmetry — deliberate rationale already exists in `main.py` (margin/expiry risk), left unchanged. Extracted `should_clear_pending_limit_order()`/`resolve_limit_order_timeout_action()` into `execution/order_gate.py`, wired behavior-preserving — partial-fill contract unit-testable for first time.

### 97. Book-history reconciliation: bond duration-beta cold start, reconciliation eligibility, FX/crypto absence a log artifact, kill-switch count corrected (V5.3.1)
🟢 `fixed` · 9/10 -> 2/10

**Problem:** the bond duration beta locked at 0.0 for ~230 bars because its warm-up floor was 21 instead of the 260-bar history; reconciliation assumed every name eligible; the README's "0 real kill-switch trips" was never measured. **Fix:** warm-up floor = `long_bar_history_size` (also fixes `cross_asset_sensitivity`'s cold start), eligibility read from the logged universe, a run-segmented presence summary (FX/crypto absence existed only in one old run), and the trip count reported as unmeasurable instead of 0.

### 98. Real V5.3.1 backtest (2026-08-14): Sharpe improves again; a suspected "7-month disengagement regression" is pre-existing
🟢 `fixed` (closed in V5.3.2 as a genuine low-IC era; its modern form is the rolling-IC gate, #161 / #176) · 4/10

**Problem:** the run (Sharpe -1.03, 230 orders) seemed to disengage for seven months from 2019-01, but it had been compared against a contaminated multi-run log. **Fix:** against the true previous run the gap shrank 202 -> 169 days; all four model/head pairs show near-zero IC in 2019-04..09, so the spread gate correctly refuses to trade then (no code change).

### 99. Reconciliation tool's own cross-run contamination and live-vs-offline tie-break order fixed (V5.3.2)
🟢 `fixed` (the ticker divergence it pointed at: #100 / #102) · 6/10

**Problem:** reconciliation deduplicated dates across the cumulative `book_history.jsonl` (160 of 174 dates recur across runs, one in eight) and carried hysteresis across run boundaries; ties resolved in a different order live (universe order) and offline (dataset order). **Fix:** `segment_logged_records_by_run()` with the latest run by default (`--reconcile-run-index`, `--reconcile-all-runs`), and offline raw scores rebuilt in universe order.

### 100. Missing Lean split/dividend factor files for 63 of 77 equity tickers — offline trained on unadjusted prices (V5.3.3)
🟢 `fixed` (confirmed live, #102; the generated files were later found to double-adjust and were repaired, #130) · 7/10 -> 2/10

**Problem:** without a factor file `apply_split_adjustments()` silently kept raw prices, so dividends and the GE spinoff made artificial return dips that live (adjusted by Lean) never saw. **Fix:** `data_pipeline/factor_file_backfill.py` derives Lean-format factor files from yfinance history (63 written), datasets regenerated, `min_rank_confidence_spread` recalibrated.

### 101. `aq evaluate --all`'s non-JSON reporting crashed on Windows — a Greek Δ character isn't in the cp1252 console codec
🟢 `fixed` · 3/10

**Problem:** Refreshing README evaluation numbers post-#100 (`aq evaluate --all`, non-`--json`) crashed on Windows with `UnicodeEncodeError: 'charmap' codec can't encode character 'Δ'` — `aq_cli.py`'s delta-print line used a literal Δ, absent from the cp1252 console codec. **Fix:** Replaced Δ with an ASCII `delta_net_sharpe` label.

### 102. Real V5.3.3 backtest (2026-08-17): factor-file fix strongly confirmed live — but the confidence-spread recalibration made real Sharpe worse
🟢 `fixed` (the factor files confirmed; the spread floor re-decided later: 0.1985 in V5.6.0, 0.184 on the live pool, #146) · 6/10

**Problem:** the run changed one thing on the live path, `min_rank_confidence_spread` 0.5014 -> 0.2831: orders 230 -> 695, Sharpe -1.03 -> -1.80, mostly from trading through the known no-skill eras (2019-04..09, 2019-12..2020-03). **Fix:** none in code: dispersion measures whether the model differentiates names, not whether it is right, so the spread floor alone cannot gate skill; that became the rolling-IC gate (#103).

### 103. A rolling trailing-IC gate, addressing #102 — built, offline-verified, wired into `main.py`
🟢 `fixed` (on since V5.5.0; window and floor re-decided by R-GATE, #146) · 6/10

**Problem:** the spread floor traded through no-skill eras because dispersion looked normal when skill was absent. **Fix:** `portfolio/rolling_ic_gate.py` vetoes engagement on the trailing realised 20-day rank IC from a live buffer of past predictions (torch-free `evaluation/rank_ic_core.py`), with `--calibrate-rolling-ic-floor` and `--replay-rolling-ic-gate`; `min_names_per_date` drops dates with 2-3 names (forced to IC ±1) and `min_resolved_dates_required` is 20 (40 was unreachable).

### 104. Chronic Lean embedded-Python teardown hang ("endless loop") — fires only after normal completion, never affects results
🔴 `closed` (environmental: the pinned Lean image hangs on a 15-line algorithm; clean on the Codespace host, #204) · 3/10

**Problem:** after every normally completed run the engine log shows `PythonInitializer.Shutdown()` timing out after 10 s (`Failed to shutdown python`), always after the results were written. **Fix:** none possible in this code: a shutdown probe found no live Python thread, and the strongest cleanup (slippage models detached, GC unfrozen, containers cleared) still hung; the experiment stays behind `diagnostics.teardown_cleanup` (off).

### 105. Train-vs-live feature-parity audit (V5.3.6) — scaler exact, no live-path formula drift in the OHLCV-recomputable families
🟢 `fixed` (verified clean; re-opened and closed by #137 / #140 / #141) · n/a (verification pass)

**Problem:** the XOM-class divergence needed a per-feature cause or a systematic rule-out. **Fix:** `evaluation/feature_parity.py` and `scripts/feature_parity_audit.py`: scaler-mapping checks and row-faithful replicas of the base technicals, indicators, momentum, macro proxies and liquidity features, with residual mismatches classified by position (warm-up, date gaps).

### 106. Gate sweep, kill-switch offline finding, promotion-gate null calibration, first Codespace retrain on a synced tree (V5.3.6)
🟢 `fixed` (every pending decision taken in V5.6.0 / V5.7.0, #142-#146) · n/a (calibration round)

**Problem:** which floors and promotion criteria were calibrated, and could the Codespace retrain the full tree? **Fix:** `scripts/gate_sweep.py` (offline net Sharpe +1.50; a rolling-IC floor of 0.05 doubles bad-era coverage at no good-era cost; dispersion floors bite the good era; the kill switch never trips offline), `promotion_gate_null_calibration.py` (t >= 2 has a 2.75% null rate), `overlap_vs_sharpe_analysis.py`, and a full Codespace retrain over scp (`gh cs cp` upload is broken).

### 107. Null-calibrated era promotion rule (V5.3.7): `era_rule` selector shipped
🟢 `fixed` · n/a (promotion methodology)

**Problem:** #106's "66% of noise runs flip two eras" used coarse buckets; the question was whether the strict era-sign gate is calibrated. **Fix:** on the gate's own criterion (90-day eras, |IC| >= 0.05) 400 permutations produce no opposite-sign era, so the strict rule is calibrated; `promotion_gate.era_rule` adds `"flip_fraction"` (blocks only above `max_era_sign_flip_fraction` 0.34) next to `"legacy"`, and the V5.3.7 candidate was promoted (owner decision).

### 108. Monte Carlo simulation testing layer — `aq evaluate --rank-book --monte-carlo` with an auto-refreshing README section
🟢 `fixed` · n/a (feature)

**Problem:** risk was shown as one equity path. **Fix:** `evaluation/monte_carlo.py` (seeded stationary block bootstrap of the book's daily net returns, 1,000 runs), `aq evaluate --monte-carlo`, a README chart with the average run in red and percentile tables, and a webui panel via `/api/evaluation`.

### 109. Deep GitHub Actions testing suite — windows+ubuntu matrix with calibrated coverage gate, ruff lint, vitest in CI, CLI smoke battery, actionlint, workflow meta-tests; non-blocking release visibility (V5.3.9)
🟢 `shipped` · n/a (verification-infrastructure round)

**Problem:** Auditing `ci.yml` found the 100 vitest frontend tests never ran in CI, no Python lint or coverage measurement/gate existed, runners were Linux-only despite Windows being the dev platform (the class of past bugs like #10's float-summation variance), and `release.yml` published to PyPI/Docker/GitHub-Release on tag push with zero test visibility. **Fix:** Rewrote `ci.yml` into five jobs — `python-tests` (ubuntu+windows matrix, full offline suite with `--cov-fail-under=80` calibrated from the measured 82% total minus two points of slack, coverage artifact from ubuntu), a new `python-lint` ruff job (E/F ruleset calibrated to existing style; 604 pre-existing findings triaged to zero), `webui-tests` now also running `npx vitest run --pool=threads`, a `cli-smoke` packaging-drift battery, and `workflows-lint` actionlint validation.

### 110. V5.3.10 - CI regression fixes (requirements parse meta-test, pinned actionlint single-step) + aq test --ruff flag + main.py extraction batch #1
🟢 `shipped` · n/a

**Problem:** V5.3.10 addressed three items: two CI regressions (a PowerShell-backtick-mangled `requirements-dev.txt` line failing the ubuntu install at 9s, and a two-step actionlint PATH pattern losing the binary between steps), the lack of a fast lint gate, and further `main.py` extraction. **Fix:** Fixed both CI regressions and pinned them with meta-tests, added the `aq test --ruff` flag (runs ruff before pytest so lint failures fail fast, used by the ci.yml lint job), and extracted `_midpoint_bar_from_quote_bar()`/`_pad_sequence_history()` verbatim into `data_pipeline/bar_synthesis.py` as thin main.py delegations.

### 111. V5.3.11 - CI python-lint job fixed (bare ruff, no editable-install import chain); duplicate py_compile step removed; pip-audit dependency-CVE scanning job added
🟢 `shipped` · n/a (CI infrastructure)

**Problem:** The `python-lint` job (V5.3.10) used `aq test --ruff`, which imports `aq_cli`→`data_pipeline.fetch`→pandas, but the lint job intentionally runs in a minimal ruff-only environment, so it failed with `ModuleNotFoundError` at ~9s; the same job also held a duplicated "Syntax-check main.py" step. **Fix:** Reverted to bare `ruff check . (the minimal lint env is by design; local devs use `aq test --ruff` with full deps), removed the duplicate py_compile step, and added a new `dependency-audit` job running `pip-audit --requirement requirements/*.txt` against runtime and dev deps on every push/PR to catch CVEs before a release tag.

### 112. V5.4.1 - RL sizing reward asymmetry fix, regime conditioning, auto-rollback hardening, prediction provenance counters
🔴 `closed` (RL retrained with the fixes, still no edge over a constant 1.0) · n/a (model improvement)

**Problem:** the RL sizing reward was symmetric, so "do nothing" (constant 1.0) was always optimal and the policy learned exactly that three times. **Fix:** `asymmetric_penalty_weight`, regime trend one-hots in the state, `retraining/rollback_hardening.py` (degradation score, dry-run target selection) and per-session prediction-provenance counters at shutdown.

### 113. V5.4.2 pre-backtest audit — critical missing-import bug found and fixed; parity tests added; config validated
🟢 `fixed and verified` · 8/10 (would have crashed forex path + silently killed sequence model on every bar)

**Problem:** The V5.3.10 extraction of `_midpoint_bar_from_quote_bar()` and `_pad_sequence_history()` into `data_pipeline/bar_synthesis.py` never added the corresponding import to main.py, so the thin delegation bodies referenced unbound names — a runtime `NameError` that `py_compile` and CI both missed since no test imports main.py. **Fix:** Added the module-scope import in main.py, 5 parity tests in `test_bar_synthesis_parity.py` registered in `_SUBSYSTEM_TEST_FILES`, and removed a duplicate "Syntax-check main.py" CI step (a V5.3.11 rebase regression).

### 112. V5.4.2 - residual_rank_20d head documented as non-promotable
🔴 `closed` (the head is noise; it stays demoted) · n/a (signal quality)

**Problem:** `residual_rank_20d` never cleared its promotion gate (IC ~0.01, t < 1). **Fix:** listed as demoted in `config.json`; the retrain validation gate no longer judges it (#139).

### 114. V5.4.4 - CI python-lint red since V5.4.3; Monte Carlo README PNG showed only the average; HRP single-sided books silently halved
🟢 `fixed` · 5/10

**Problem:** two ruff findings had kept `python-lint` red; the test suite overwrote the real Monte Carlo PNG (and the test badge) with fixture output; `build_hrp_allocation()` gave a single-sided book only half its gross; a zero close made a -100% return in HRP's covariance. **Fix:** ruff findings removed; the chart renders only for the real README and the badge writer is mocked in that test; single-sided books get the full gross on their one leg; any pair touching a non-positive close is skipped.

### 115. V5.4.4 - installed `aq` console script broken for `evaluate`/`audit`; mean-reversion baseline was a placeholder
🟢 `fixed` · 6/10

**Problem:** `pyproject.toml` packaged only `risk`/`execution`/`data_pipeline`, so the installed `aq evaluate` raised `ModuleNotFoundError` (masked by the repo root on `sys.path`); `mean_reversion_baseline()` accrued a hardcoded placeholder, so its Sharpe was always 0. **Fix:** the missing packages and `generate_evaluation_report` added to the packaging lists; the baseline accrues real next-day returns.

### 116. V5.4.5 - pre-backtest audit: round-trip commission undercounted 2x in the net-edge gate; paper mode ignored every risk lock
🟢 `fixed` (the IB paper part is deferred with the IB items) · 6/10

**Problem:** `estimate_round_trip_cost_bps()` charged one side's commission for a round trip, so live let through trades the simulator would not; `resolve_order_permission()` checked the risk locks only in live mode, so a tripped kill switch could not stop paper orders. **Fix:** each side pays `max(rate, dollar floor)`, twice; paper mode requires healthy risk locks (`paper_orders_blocked_risk_lock`).

### 117. V5.4.5 - NaN propagation family: NaN skipped safety triggers, poisoned fill prices, reconciliation reported false-clean, NaN ranks bypassed the spread veto
🟢 `fixed` · 7/10 latent

**Problem:** every guard in the family was a one-sided float comparison or an `is not None` check, all pass-through for NaN. **Fix:** finite-or-None normalisation of the kill switch's inputs and its rolling Sharpe, non-finite prices degrade to zero slippage, reconciliation fails closed on non-finite weights, an explicit `non_finite_cost_estimate` reason, a finite-rank eligibility guard in book construction, a skipped non-positive gross cap and a re-clamped minimum position weight.

### 118. V5.4.5 - HRP equal-weight fallback broke dollar-neutrality on asymmetric two-sided books
 · 

**Problem:** Both fallback paths in `build_hrp_allocation()` (<2 names with usable history; scipy exception) divided gross across both legs combined (`gross / len(longs + shorts)`), so a two-sided book with unequal legs (e.g. 6 longs / 2 shorts) came out +0.75·gross / −0.25·gross instead of dollar-neutral, contradicting the function's own docstring; the main HRP path normalized per leg correctly and existing tests only pinned symmetric cases. **Fix:** One shared `_equal_weight_fallback()` using the same leg-total convention as the HRP path (computed once at the top, shared by all three paths), with new tests for asymmetric thin-history, linkage-exception, and single-sided books.

### 119. V5.4.5 - V5.4.1's RL asymmetric-penalty reward fix was dead code at its only production call site
 · 

**Problem:** `compute_action_reward()`'s `asymmetric_penalty_weight` (V5.4.1) was dead code at its only production call site — `build_bandit_rows()` never accepted or forwarded it and `main()` never loaded it from config, so real training used the exact symmetric reward whose failure mode motivated the fix; only `test_rl_sizing_v541.py` exercised it via explicit kwargs. **Fix:** Added `phase_v2.rl_sizing.training.asymmetric_penalty_weight` (default 1.0, byte-identical until set), loaded in `main()`, threaded through `build_bandit_rows()` into `compute_action_reward()`, and recorded in `training_metrics_payload` for provenance.

### 120. V5.4.7 - one NaN event could permanently wedge the Redis->Postgres pipeline; torn JSON writes 500'd the API
🟢 `fixed` · 7/10

**Problem:** a bare `NaN` passed Redis and then failed PostgreSQL's JSONB insert, rolling back and stranding every batch that held it; status files were truncated-then-written, so a racing reader got HTTP 500s. **Fix:** `json_safety.py` (finite sanitising serialiser, atomic writes, lenient reads) for both producers and every status writer; the Postgres workers persist the clean prefix and dead-letter a poison row (the audit chain stops at the first one so it cannot fork), while an outage still leaves everything pending.

### 121. V5.4.7 - gating blend deflated magnitude/volatility by missing-head weight mass; NaN confidence scored as perfect
🟢 `fixed` · 6/10

**Problem:** `_weighted_blend()` did not renormalise when an expert lacked a multitask head (volatility ~25% too low, positions oversized); `_clamp01()` turned NaN into 1.0, clearing the trade gate. **Fix:** the blend divides by the contributing weights; non-finite clamps to 0.0; `_performance_score()` keeps a real 0.0; the interpreter's layernorm has an eps floor.

### 122. V5.4.7 - retraining gates compared against fake zeros: missing files deadlocked promotion, NaN passed every gate
🟢 `fixed` · 6/10

**Problem:** `validation_gate.py` defaulted missing metrics to 0.0, which deadlocked promotion when the active side's file was missing and passed vacuously when the candidate's was; NaN failed no one-sided comparison. **Fix:** required candidate metrics are finite-or-None and fail closed with an explicit reason; a missing active baseline fails `active_baseline_metrics_missing`; `backtest_gate` treats non-finite returns as no edge.

### 123. V5.4.7 - data-pipeline corruption class: Yahoo NaN frames written as bars, FRED cache destroyed by a narrow refetch, config.json truncation
🟢 `fixed` · 5/10

**Problem:** rate-limited Yahoo responses wrote NaN rows as bars, yfinance's exclusive end never fetched the last day, a narrow FRED refetch replaced the whole cache, `aq fetch --apply` could truncate `config.json`, and two liquidity guards divided by zero or lowered cost below the ceiling. **Fix:** NaN frames dropped, `end + 1 day`, merged FRED caches, atomic config and cache writes (`json_safety`), conservative liquidity blocks and an explicit error for an empty sequence history.

### 124. V5.4.7 - auto-rollback/promote artifact verification gaps; Telegram watermark freeze; worker startup crash-loop
🟢 `fixed` · 4/10

**Problem:** promote copied artifacts without verifying them, a rollback to an empty version "succeeded", a null JSONB field froze the Telegram watermark forever, and a Redis-down ping crash-looped both Postgres workers. **Fix:** `verify_version_artifacts()` before any promote, `no_artifacts_found` and a version-id charset check on rollback, junk-tolerant alert formatting that advances the watermark, and a startup that warns and reconnects.

### 125. V5.4.7 - `aq` help surfaces drifted: stale `--all` text since V5.4.4; README missing five flags; CI covered 2 of ~23 help screens
 · 

**Problem:** `aq evaluate --all`'s help text was stale since V5.4.4 (benchmarks had joined the bundle), the README's `aq train`/`aq evaluate` synopses were missing six shipped flags, CI's cli-smoke job exercised only two help screens, and ci.yml's `ruff` install was unpinned (new ruff releases could change CI independently of repo changes). **Fix:** Updated the `--all` help and code comment and documented all missing flags with per-flag bullets; added `tests/test_cli_help_surface.py` (parametrized exit-0 `--help` across every parser leaf plus a two-directional README↔`build_parser()` flag-sync guard) and pinned `ruff==0.16.4`; reinstalled the editable `aq` per the #115 packaging rule.

### 126. V5.4.10 - 34% of backtest data requests failed on missing crypto quote zips
🟢 `fixed` · 2/10

**Problem:** Lean's `AddCrypto` requests a quote feed too and the pipeline wrote only trade zips; only the traded LTCUSD mattered (`main.py` never reads crypto quote bars). **Fix:** `aq backfill yfinance --quotes` synthesises zero-spread Lean crypto quote zips from the trade zip (real bid/ask rows kept); LTCUSD first, the observation-only pairs in V5.6.0.

### 127. 2026-08-27 backtest written up: Sharpe -2.51 against an offline +1 — what the run actually traded (V5.5.0)
🟢 `fixed` (decomposed and fixed by #128-#134) · 9/10

**Problem:** the run (Sharpe -2.51, -4.25%) did not trade the offline book: equity long ~2.5% of NAV, forex short 13% and -$3.0k, 135 of 171 equity entries outside the book, 16 bps equity fees and 115 overlapping orders. **Fix:** `evaluation/backtest_audit.py` (`aq evaluate --audit-backtest`), which made the decomposition repeatable; Lean's Sharpe also subtracts a risk-free rate the offline tools do not (-1.16 without).

### 128. Offline/live execution parity: ten divergences between `aq evaluate` and `main.py`, fixed (V5.5.0)
🟢 `fixed` · 9/10

**Problem:** live traded the legacy probability signal outside the book without a budget, shrank book weights ~8x through the multiplier chain, sized forex by margin (several x NAV), stacked duplicate limit orders, lost hysteresis memory on a veto, never saw its own fills in exit tracking, overcharged fill slippage and decided forex/crypto on the previous bar; the offline simulator used another head, cap, gate set and weighting. **Fix:** a legacy sleeve budget (`portfolio/legacy_sleeve.py`), a book-weight floor, forex capped to its book weight with its own short budget, one order per symbol, the formed book remembered through a veto, exit tracking that adopts held positions, per-side fill slippage, and `aq evaluate --as-live` (`evaluation/live_parity.py`) mirroring the live decisions.

### 129. Crypto never traded: one global 0.45 volatility cutoff made BTC/LTC permanently "elevated"; teardown and timing probes added (V5.5.0)
🟢 `fixed` — crypto trades (16 trades) and the probes were read once (cleanup changed nothing for the teardown hang, which stays open as #104) · 6/10

**Problem:** `ELEVATED_VOLATILITY_THRESHOLD = 0.45` (annualized) sits below crypto's own distribution — **77% of crypto samples in the backtest window exceed it** (85% over all history; p80 0.87 / 1.11) — so the analyzer's Priority 3 cancelled 13 of the 26 BTC/LTC book selections (the 08-27 run); zero-volume blocked only one.

### 130. 62 equity factor files were applied on top of already-adjusted data: prices x0.05 (AMZN), dividends counted twice (V5.5.0)
🟢 `fixed` (dataset and models rebuilt from single-adjusted zips, #156 / #162) · 7/10

**Problem:** #100 wrote factor files for zips the yfinance backfill had already split- and dividend-adjusted, so prices were adjusted twice (AMZN $84 -> $4) and per-share fees cost 16-49 bps a side. **Fix:** `factor_file_backfill.py --audit` / `--repair-adjusted-zips --apply` remove the files (backup kept) and generation skips backfill-written zips; a sentinel-only file must never replace one (Lean then serves no data until 2050).

### 131. Four latent defects found by the new guards (V5.5.0)
🟢 `fixed` · 5/10

**Problem:** (1) the wheel omitted `monitoring`, `topology`, `liquidity`, `experience` and `risk_controls`, so `aq assets`, `--replay-kill-switch`, feature-parity and the paper-readiness report raised `ModuleNotFoundError` on any non-editable install; (2) `scripts/feature_parity_audit.py`'s synthetic check was **silently dead** — a swallowed `SKIPPED` still printed PASS; (3) `compute_factor_exposure()` averaged residuals only (~0 by construction), so its alpha metrics were always 0.0; (4) `--reconcile-book-history` read a vetoed live rebalance as 0% overlap and its hysteresis replay ignored the veto. **Fix:** The five `pyproject.toml` entries plus `tests/test_packaging_modules.py` and a real-wheel `scripts/wheel_smoke.py`; the audit's date alignment, a real replica call and `--synthetic-only` (fails when the check did not run); alpha = intercept + residuals; vetoed dates flagged and excluded, with `--hysteresis-survives-veto`.

### 132. V5.5.0's first backtest attempt crashed on bar 1: Lean's star import shadows `time` (and a second trap hid behind it)
🟢 `fixed` (verified: the re-run, `backtests/2026-10-07_15-39-04`, completed in 2840 s) · 7/10

**Problem:** `backtests/2026-10-07_15-19-36` stopped after 11 seconds with `type object 'datetime.time' has no attribute 'perf_counter'` at `_ensure_ready`: `from AlgorithmImports import *` exports Lean's `time` (`datetime.time`), shadowing the stdlib module `main.py` imported for the timing probe. **Fix:** `main.py` uses `from time import perf_counter as _perf_counter` after the star import; the wiring stub exports `time = datetime.time`; `tests/test_main_ensure_ready_smoke.py` runs the real `initialize()`/`_ensure_ready()` (skipped on a fresh checkout), a structural test forbids `time.<attr>` in `main.py`, and #130's repair now removes the files.

### 133. 2026-10-07 backtest (V5.5.0 first full run): Sharpe -4.55, 230 of 355 trades closed within 2 days, crypto and most forex blocked
🟢 `fixed` (verified in the re-runs, #134) · 9/10

**Problem:** every sell was exempt from the cooldown so the legacy signal flipped positions within a day, book positions fell to the legacy signal during a veto, market and limit orders stacked in one bar, and the liquidity gate read crypto/forex volatility as spread (no crypto trades, most forex simulated). **Fix:** only forced exits skip the cooldown, book-owned positions are held through a veto (`hold_owned_positions_on_veto`), a second entry waits for an in-flight order, and the spread proxy is capped per class.

### 134. Re-entries were force-sold the next day: the closing fill never cleared the exit-tracking state (V5.5.0)
🟢 `fixed` · 9/10

**Problem:** a close fills a bar late, so exit tracking never saw the position go flat and the next entry inherited the old entry bar and peak, then was force-sold by the age exit or trailing stop the next day (154 of 196 re-entries). **Fix:** `compute_position_exit_tracking_update(..., clear_stale_state=True)` clears a flat symbol's stale state.

### 135. Feature reconciliation of the 2026-10-07 run: live features diverged from `full_dataset.csv` (V5.5.0)
🟢 `fixed` (#137, #140, #141) · 7/10

**Problem:** `--reconcile-features` on XOM and NVDA differed on 16-20 of ~52 features almost every day: price-level features from the double-adjusted dataset (#130), cross-asset features from a timing difference. **Fix:** the tick order (#137), Lean's forex fill-forward calendar (#140) and two missing FRED drivers (#141); dataset regenerated and models retrained.

### 136. CI on `main` red since the V5.5.0 push: 29 `NameError: Slice` errors, README links into gitignored READMEs, 43 gitleaks findings (V5.6.0)
🟢 `fixed` · 5/10

**Problem:** Python 3.11 evaluates `main.py`'s `Slice` annotation at import (3.14 does not), the README linked gitignored READMEs, and gitleaks read exported-model `*_key` tensor names as credentials. **Fix:** the stubs export `Slice` and an AST guard catches new import-time Lean names, the three READMEs are un-ignored and the link test fails on ignored targets, and `.gitleaks.toml` allowlists exactly the tensor-name lines.

### 137. Feature divergence #135 solved: live built cross-asset features one tick behind the dataset (V5.6.0)
🟢 `fixed` · 8/10

**Problem:** `main.py` builds the topology, peer, macro and momentum-rank payloads before the tick's bars join the windows, so live(D) equalled the dataset's D-1, and training also saw crypto's same-day bar (a lookahead). **Fix:** `features/cross_asset_timing.py`: one window-to-inputs construction for `main.py` and a `CrossAssetTimeline` that replays the live visibility rule offline from raw per-ticker history (equity visible at the close, crypto/forex at the next midnight).

### 138. Crypto fills paid $0 fees: Lean's default crypto fee model charges nothing (V5.6.0)
🟢 `fixed` · 6/10

**Problem:** `add_crypto(..., Market.COINBASE)` does not bring a fee model, so every crypto fill carried $0 fees and the net-edge gate assumed IB's equity commission. **Fix:** `costs.fee_by_type.crypto` assigns Lean's `CoinbaseFeeModel()`, the net-edge gate charges each class its own fee, and the simulator gets the same per-ticker rate.

### 139. Training-pipeline and tooling defects fixed before the V5.6.0 retrain
🟢 `fixed` — unit-tested; the retrain itself is recorded in the entries that follow · 6/10

**Problem:** Six defects blocked the V5.6.0 retrain: `validation_gate` judged the never-promotable `residual_rank_20d` head (rejecting every candidate); `train_rl_sizing.py` compared its penalised policy against an unpenalised constant with no way to pick the penalty; a VM reboot at walk-forward window 5 lost the run three times; `--reconcile-book-history` loaded all 251 dataset columns and re-ran the model per head (~1.3 GB, killed on this PC); `overlap_vs_sharpe_analysis.py` collapsed runs sharing a sim window; and topology cost 332 ms/call, 87% of it pure-Python Pearson loops. **Fix:** The ranking gate now reads `ranking.heads` (`rank_5d`/`rank_20d`, passes if any clears); `policy_beats_constant_unpenalized` + `--penalty-sweep` on a chronological holdout; per-window `window_result.json` + `train.py --resume-run-id`; `predict_heads()` + `row_mask` + chunked column-pruned reads (~0.5 GB); per-run points; numpy correlation matrix with a scalar fallback (1.16 s → 0.16 s for 104 symbols, exact to 1e-12).

### 140. Lean fills forward forex bars: live windows hold flat Sunday bars the dataset never had (V5.6.0)
🟢 `fixed` · 7/10

**Problem:** Lean emits a flat forex bar for every open day without data (Sundays, a missing weekday), so live forex windows carried zero-return days and topology strength matched live on only 32% of NVDA dates. **Fix:** `fill_forward_open_forex_days()` builds the same calendar in `CrossAssetTimeline`, and `train.engineer_forex_features_on_lean_calendar()` computes forex features on it while labels stay on real bars.

### 141. Two FRED sensitivity drivers existed only on the Codespace: 4 model features were 0 live and real in training (V5.6.0)
🟢 `fixed` — files pulled local; confirmed live in V6.4.2: BT5's feature snapshots (`visualization/book_history/20261022T090307Z.jsonl`, 7 symbols, 431 book records) carry non-zero `sens_real_rate_beta` and `sens_dollar_beta` in 1,197 of 1,197 snapshots (the interactions are zero only on days the driver did not move) · 8/10

**Problem:** `sens_real_rate_beta/interaction` and `sens_dollar_beta/interaction` are regressions on the FRED series `treasury_10yr_real` and `dollar_index`, which `data/reference/fred_series/` on this PC never had (nor `breakeven_inflation_10y`); only the Codespace copy did.

### 142. Backtests of the V5.6.0 models: BT1 (diagnostic, 2020-H1), BT2 and BT3 (full 2019-21) (V5.6.0)
🟢 `fixed` · 6/10

**Problem:** did the retrained models and the data fixes improve Lean, and what does forex earn? **Fix:** forex trading switched off (`forex_risk.enabled` false; forex still feeds features): it lost money after fees in both runs because IB's $2 minimum is ~8 bps a fill on 2.6%-of-NAV positions.

### 143. What costs the as-live book its Sharpe: lever attribution, a forex-slot defect and four rule-driven changes (V5.6.0)
🟢 `fixed` (confirmed in Lean, #144) · 7/10

**Problem:** `scripts/as_live_levers.py` changed one live mechanism at a time: the elevated-topology veto on book members cost 0.70 Sharpe; disabled forex still won book slots; the equity spread proxy exceeded its own 25 bps cap on 62% of days (118 BT3 decisions liquidity-blocked). **Fix:** by rule: no topology veto for book members, disabled classes kept out of the book (`book_candidate_trading_eligible`), edge 396 -> 574 bps per rank unit, the slippage trigger at 80 bps (p99 x 1.5), an equity spread cap of 0.001.

### 144. BT4: the round-3 changes in Lean (V5.6.0 final run, `backtests/2026-10-09_22-13-03`)
🟢 `fixed` (the kill-switch throttle and the spread-floor recalibration followed in #146) · 5/10

**Problem:** did #143's changes hold in Lean? **Fix:** none needed: decisions reaching `trade` 71 -> 321, liquidity and topology blocks 0, net-edge blocks 1.

### 145. The offline simulator modelled almost none of Pass 2 and its gate took 15 minutes: rebuilt on main.py's own functions (V5.7.0)
🟢 `fixed` · 7/10

**Problem:** the as-live simulator skipped the kill switch, sizing chain, liquidity and net-edge gates, HRP and per-name impact, charged impact on a $1M book, and each rolling-IC gate took ~12 minutes. **Fix:** `evaluation/rolling_ic_series.py` (one state per date, shared by every floor) and `simulate_rank_book` driven by `live_parity`'s builders of the live pure functions, impact at the real NAV, the spread calibration on the live pool, `--audit-fills`.

### 146. Gate research on the rebuilt simulator, both splits: one rule-driven flip, five rejected, the kill switch kept (V5.7.0)
🟢 `fixed` (confirmed in Lean by BT5, #148) · 6/10

**Problem:** the kill switch was the main throttle, the spread floor had been calibrated with forex in the pool, and the rolling-IC gate vetoed 157 of 281 rebalances. **Fix:** by R-GATE on both splits: IC gate window 80 / floor 0.0, spread floor 0.184 on the live pool, legacy cap 0.10 -> 0.05; the kill switch, hold-on-veto, HRP, own-tick and impact kept or rejected by measurement.

### 147. Execution-cost leads closed with measurements: no data-source gap, market fills pay the modelled 5 bps, no limit order was stale (V5.7.0)
🟢 `fixed` (IB paper fills stay deferred with #116's IB part) · 4/10

**Problem:** a median 5 bps fill-vs-open gap was blamed on a data-source gap, and 11 limit orders were flagged open > 5 days. **Fix:** `evaluation/fill_price_audit.py` (`aq evaluate --audit-fills`) and limit-order ages in weekday sessions (`--max-open-sessions`).

### 148. BT5: the V5.7.0 gate bundle in Lean, and a kill-switch trigger that counted price improvement as slippage (V5.7.0)
🟢 `fixed` (the trigger needed a second fix, #153) · 5/10

**Problem:** 24 member decisions were locked by `kill_switch_slippage_divergence_above_cap`, because `abs(fill - open)` counted a limit fill below the open on a buy as slippage. **Fix:** the divergence counts only adverse slippage given the fill's direction.

### 149. Crypto: no observation-only name graduates, and BTC/LTC stay (V5.7.0)
🟢 `fixed` (a decision; the machinery ships default-off) · 4/10

**Problem:** the crypto pool was two names and BT5's 13 crypto book trades earned $64 gross for $257 of fees. **Fix:** none in behaviour: no name passes R-GATE alone, all ten together collapse the book and removing BTC/LTC loses too; `trading_eligibility_basis: "history"` ships off for a later look.

### 150. V5.7.0 retrain: leakage fixed, honest numbers are lower, R-MODEL fails, V5.6.0 stays (V5.7.0)
🔴 `closed` as a promotion (the purge, diagnostics and holdout machinery ship) · 6/10

**Problem:** a large train/validation IC gap, no purge at split boundaries, forex invisible to the model. **Fix:** a 20-day label purge, a forex one-hot, `fx_carry_3m` and a separate forex rank group; seven variants inside the seed spread, so the control was the candidate.

### 151. Forex sleeve: no within-pool rank edge, R-FX fails, forex stays off (V5.7.0)
🔴 `closed` (superseded by #163, then R-FX6 turned forex off, #181) · 4/10

**Problem:** forex was off because IB's $2 minimum ate a ~$0 gross edge; a fee-aware within-pool sleeve was the plan. **Fix:** none shipped: the 15-pair rank IC is negative on both splits for the shipped and the retrained models (-0.03..-0.07), every sleeve configuration is net-negative, and the carry feature created no signal.

### 152. Gating, label timing and the shipped checks that need no change (V5.7.0)
🟢 `fixed` (verified, no code change) · 2/10

**Problem:** did the weak learned gating model (MCC 0.0097) or close-to-close labels distort the book? **Fix:** none needed: gating feeds only the capped legacy sleeve, and the live score's IC against open-to-open returns is within 1-6% of close-to-close.

### 153. BT6: the direction-aware slippage fix did nothing; the trigger was crypto limit-fill drift (V5.7.0)
🟢 `fixed` (verified in BT7) · 4/10

**Problem:** BT6 had the same slippage-locked dates as BT5: the tracker compared a limit fill with the bar's open although the order went in hours later, so its gap is intraday drift, not cost. **Fix:** `_track_slippage_divergence` ignores fills of tracked limit orders; market fills are unchanged. After any Codespace pull diff all of `ml/` (a stale `expert_models/` cost one invalid run).

### 154. Closing the minor leads against BT7 (V5.7.0)
🟢 `fixed` (accepted residuals, no code change) · 2/10

**Problem:** the topology cache tolerance, the XOM/NVDA selection residuals, AAA's late Lean start and the live-only `fx_carry_3m` were still open. **Fix:** each measured and accepted: topology strength differs on 4-5% of dates from run state, not the cache; selections 6% per symbol with every other feature exact; AAA is observation-only; the carry feature is kept for the next retrain.

### 155. CI-only failure: a constant return window correlated as noise on Python <= 3.11 (V5.7.1)
🟢 `fixed and verified` (reproduced on Python 3.10, fixed, 54/54 topology tests pass there and on 3.14) · 3/10

**Problem:** `test_vectorised_correlations_match_the_scalar_pearson_for_every_pair` failed on every CI job since V5.6.0 (CI runs 3.11, the dev PC 3.14): `_pearson_correlation` relied on an exact zero variance for a constant window, but Python <= 3.11 sums naively so `mean([0.001] * 24) != 0.001` and the variance came out ~1e-35, giving a ~1e-17 correlation instead of 0.0 and breaking the alphabetical top-peer tie. **Fix:** A window whose values are all equal now returns 0.0 in the scalar path and zeroes that row and column in the vectorised matrix (decided on the values, independent of `sum()` rounding).

### 156. All Lean data stopped at 2021-03-31; the holdout was a separate root (V5.8.0)
🟢 `fixed` · 8/10

**Problem:** every zip ended 2021-03-31, so ten crypto pairs never reached 250 train rows, forex mixed two sources, 15 obsolete factor files remained and the shipped models had no rank edge on a new validation split (pooled IC -0.003). **Fix:** all 104 zips rewritten 2013-01..2026-09 from one Yahoo source (a bad EURGBP print overridden), crypto quote zips and 19 FRED series refreshed, Coinbase listing dates recorded, and new splits train 2014-12..2021-12 / validation 2022-01..2023-06 / backtest 2023-07..2025-06 / holdout 2025-07..2026-09 (read once).

### 157. Eight audit tools, so each question below is answered by a measurement (V5.8.0)
🟢 `fixed` · n/a (tooling)

**Problem:** the backtest audit counted bonds as "equity" (it groups by Lean securityType), the rolling-IC gate had never been compared with the IC it estimates, there was no check that a data rewrite is sound, no single view of which heads are promotable, and nobody could say whether a feature was a ticker ID. **Fix:** `--ic-by-class` (within vs between class IC), `--audit-gates` (gate reading vs fully resolved IC, false-veto share; a constant true IC of +0.05 must be vetoed on well under half of the rebalances, pinned by a test), `--audit-data`, `--audit-heads` (R-HEAD), `--audit-features` (ticker-ID suspects, class-constant features, per-split IC sign, permutation drop), `aq clean ml`, per-order slippage trace in the book-history record, and `scripts/codespace_status.sh`.

### 158. Bond duration beta leaked later data into every training row and was a per-ticker constant (V5.8.0)
🟢 `fixed` (point-in-time on both sides; the retrained model is judged in the entries that follow) · 7/10

**Problem:** `bond_empirical_duration_beta` was one OLS slope over a bond ETF's WHOLE 2014-2021 history broadcast to every row (so validation and backtest returns shaped the training feature, and it identified the ticker); live froze its own estimate after 260 bars and never saw that value. **Fix:** `features/bond_features.py::rolling_duration_beta` / `rolling_duration_beta_series` (trailing 252 bars; the vectorised series equals the scalar at every row to 4e-16, holes included), used by `train.build_bond_features_by_date` and `main.py::_bond_empirical_duration_beta_for_symbol` behind `phase1.features.bond_duration_beta.mode` (default `full_history` = unchanged).

### 159. Latency and memory: the biggest per-tick costs measured and cut (V5.8.0)
🟢 `fixed` · 5/10

**Problem:** per tick, inference took 166-494 ms (57 separate model calls), topology 332-542 ms and `write_state` rewrote ~1.2 MB of JSON; the sequence trainer held a 1.3 GB tensor. **Fix:** flat models for all symbols in one matmul per layer (64 -> 2 ms), vectorised topology lookups and peer ranking, trimmed scaler and sensitivity work, per-split sequence tensors, and throttleable dashboard writes in backtests (`diagnostics.state_write`).

### 160. The Codespace retrain was killed five times: a memory spike, a push that overwrote the retrain's artifacts, VM restarts (V5.8.0)
🟢 `fixed` · 6/10

**Problem:** the sequence trainer's full-split forward pass spiked past the 8 GB Codespace, a mid-retrain push overlaid the new scaler and models with the old ones while reporting "verified", and VM restarts killed nohup jobs. **Fix:** `forward_in_batches` for full-split passes, float32 chunked reads, `codespace_sync.ps1 -CodeOnly` / `-NoDatasets`, detached launchers with pid files (`codespace_start_bg.sh`) and status / memory helpers.

### 161. The rolling-IC gate vetoes the better periods: decided by R-GATE (V5.8.0)
🟢 `fixed` (decided by rule; the offline benefit did not transfer to Lean, #172, so the gates are safety controls) · 7/10

**Problem:** the gate's vetoes are anti-informative: 82% of backtest vetoes are false and the forward IC on vetoed dates (+0.156) beats the overall (+0.095), because trailing IC mean-reverts. **Fix:** R-GATE on both splits chose window 120 / floor 0.0 and a spread floor of 0.10; the kill switch stays, hold-on-veto, HRP and impact stay rejected.

### 162. V5.8.0 retrain, R-MODEL8 and the walk-forward (V5.8.0)
🟢 `fixed` (the owner kept the candidate on 2026-10-13; read in Lean by BT1 / BT2, #172 / #174) · 7/10

**Problem:** the shipped V5.6.0 models had no rank edge on the new splits and their as-live book vetoed 97% of rebalances. **Fix:** a retrain on 2014-12..2021-12 (20-day purge, bond and forex rank groups, point-in-time bond beta) where no variant beat the control by more than the seed spread; R-MODEL8 failed one clause numerically and the owner kept the candidate; the learned gating network was switched off by R-HEAD.

### 163. Forex: a carry-ranked sleeve at the minimum cap (V5.8.0, R-SLEEVE)
🟢 `fixed` (dropped later by R-FX6, #181) · 4/10

**Problem:** no signal gave forex a net-positive sleeve on both splits; carry had the best within-pool IC (+0.07, t 0.7). **Fix:** by the owner's every-area-trades decision and R-SLEEVE the carry sleeve shipped at the minimum cap (gross 0.10, 2 per side, its own loss guard; `features/fx_signals.py`).

### 164. Bonds: they lost money in the book; a momentum-ranked sleeve passes R-SLEEVE (V5.8.0)
🟢 `fixed` (shipped at the minimum cap after BT1) · 6/10

**Problem:** every bond ETF the V5.7 book traded lost money (hidden because the audit filed bonds under equity), and the model has no stable within-bond edge. **Fix:** `phase_v2.bond_sleeve`: the 22 ETFs ranked among themselves by vol-scaled momentum (positive on both splits offline) outside the main pool; after BT1's -$540 in Lean, R-SLEEVE's minimum-cap branch cut the gross 0.30 -> 0.10.

### 165. Crypto: all twelve pairs trade, the ten extra ones capped (V5.8.0, R-SLEEVE)
🟢 `fixed` (the per-name cap was cut further by R-CRYPTO, #180) · 4/10

**Problem:** with data to 2026 every pair is trading-eligible, none with a proven edge, at 49-56 bps a fill. **Fix:** graduates capped at 1% per name / 5% class gross with BTC/LTC exempt (`apply_class_weight_caps`, shared live and offline), a loss guard and the venue listing guard (no order before listing, during XRP's suspension or after EOS's delisting).

### 166. RL sizing, a sixth time: no edge, so it ships at the minimum range with a shadow guard (V5.8.0, R-SLEEVE)
🟢 `fixed` · 3/10

**Problem:** the book-level policy again does not beat a constant 1.0, and no multiplier range gains +0.05 Sharpe on both splits. **Fix:** RL runs at `[0.9, 1.1]` with `dynamic_risk.rl_shadow_guard` (back to 1.0 while its trailing excess return is below -0.2% of NAV); the forex sleeve does not use it.

### 167. Latency and resources: what shipped, what R-LAT rejected (V5.8.0)
🟢 `fixed` · 4/10

**Problem:** a 2.25-year Lean run took 6,900-8,800 s, dominated by inference, topology, state writes and `build_model_input`. **Fix:** the #159 cuts plus batched offline head scoring (an as-live pass 10 min -> 83 s); R-LAT rejected re-parsing `config.json` at rollover (0.2-0.6% of a run) and pruning Lean's code snapshot (~1 MB a run).

### 168. Feature audit verdict: the flagged features are class descriptors, not leaks (V5.8.0)
🟢 `fixed` (no input-set change) · 3/10

**Problem:** `--audit-features` flagged 13 per-ticker-constant features, 26 constant for forex and 18 that flip IC sign between splits. **Fix:** none: they are instrument descriptors by design or not applicable to FX; the only real look-ahead (the bond beta) was already point-in-time, and the backtest split keeps a pooled IC of +0.060 (t 2.34), mostly within classes.

### 169. Holdout, one look (2025-07-01..2026-09-29): no out-of-sample rank edge, the gated book loses 2.4% (V5.8.0)
🟢 `fixed` (reported as measured, nothing tuned on it) · 8/10

**Problem:** did the in-window edge persist after 2025-05? **Fix:** none: every head's IC is at most +0.037 with t < 1.5; the idealized book makes -0.81 Sharpe and the as-live book -0.59 (-2.4%), vetoed on 153 of 172 rebalances at 13% mean gross.

### 170. Learned topology sizing, measured offline for the first time (rule R-TOPO): stays on (V5.8.0)
🟢 `fixed` (no change) · 2/10

**Problem:** the live topology sizing multiplier (0.5..1.0) was invisible to every offline run. **Fix:** dataset rows scored with the live prototype distances through the same `topology_sizing_multiplier`; on vs off differs in sign by split and clears no margin, so it stays on (it acts as a uniform shrink).

### 171. README results are refreshed by the commands that produce them; Monte Carlo is part of `--all` (V5.8.0)
🟢 `fixed` · 3/10

**Problem:** the README's Monte Carlo section claimed to refresh with every `aq evaluate` but only re-rendered a stale result (`--monte-carlo` was not in `--all`), `--monte-carlo` crashed with a KeyError on fewer than 30 daily returns, the as-live book and all V5.8.0 research were not on the page, and a second Lean run overwrote the first one's row. **Fix:** `aq evaluate --all` includes Monte Carlo (a short dataset reports SKIPPED), `evaluation/readme_research.py` renders the as-live book per split and the research/audit block, `generate_backtest_report.build_history_markdown` lists every finished Lean run, and the audit flags and research scripts refresh the README on exit.

### 172. BT1 (Lean, 2023-07-01..2025-06-30): the retrained candidate loses 5.0% in the engine; the offline +0.62 does not reproduce (V5.8.0)
🟢 `fixed` (measured and attributed; the regime skew it exposed is #173) · 9/10

**Problem:** BT1 (`backtests/2026-10-13_17-54-47`): Lean Sharpe -2.98 (-0.75 without risk-free), net -5.03%, drawdown 8.2%, with the loss in the main equity book; the offline as-live book (+0.62) and Lean correlate at 0.02 daily. **Fix:** none in the book: the gates that made the offline number did not dodge the same days in Lean; `--audit-backtest` now splits P&L by config class (bonds -$540), `--reconcile-features` applies crypto/forex's late-bar row, and the backtest state-write throttle goes on (34% of the run).

### 173. The models read a regime vector the dataset never produced: live fed the account drawdown into the `regime_*` inputs (V5.8.0)
🟢 `fixed` (confirmed in BT2) · 7/10

**Problem:** the dataset builds `regime_*` at zero drawdown while `main.py` passed the real one, so the regime inputs differed on 64 of 94 BT1 dates and a losing book changed its own inputs (top/bottom-6 overlap 0.66 at -8%). **Fix:** `regime.build_model_input_regime_vector` (drawdown pinned to 0) feeds both training and live model inputs; risk decisions keep the real-drawdown vector.

### 174. BT2 (Lean, 2023-07-01..2026-09-30): capital preserved, no edge demonstrated, the regime fix confirmed (V5.8.0)
🟢 `fixed` (measured and written up; the verdict is no demonstrated edge) · 6/10

**Problem:** BT2 (`backtests/2026-10-14_07-27-32`): net -0.58%, drawdown 4.3%, Lean Sharpe -2.03 (-0.03 without risk-free); costs ($2,195) exceeded the gross result ($1,614), crypto alone $1,131 at 70 bps a fill. **Fix:** none: R-LEAN8's engine and drawdown clauses hold, its Sharpe bar is missed (+0.14 on the backtest stretch), and the gain over BT1 comes from a changed config, one path, so it is evidence for the fix, not an edge.

### 175. Lean's benchmark was a constant since 2021: the default hourly SPY feed had no data in the window (V6.0.0)
🟢 `fixed` · 4/10

**Problem:** without `set_benchmark` Lean used its sample hourly SPY zip ending 2021-03-31, so every V5.8 run charted SPY as a constant and its Alpha, Beta and Information Ratio were meaningless. **Fix:** `runtime.benchmark_ticker` -> `set_benchmark(lambda time: <the daily SPY price>)` (a Symbol argument makes Lean add the hourly feed again); the report redraws a flat benchmark from the daily zip.

### 176. The offline simulator is not a model of Lean yet: R-CAL says branch B, and the gap is attributed (V6.0.0)
🟢 `fixed` (the tools and the verdict) · 7/10

**Problem:** V5.8's as-live Sharpe overstated BT1 by +1.4 and no tool compared the two day by day. **Fix:** `aq evaluate --attribute-lean` rebuilds a Lean run's daily P&L per ticker and component (reconciles within $2), and `scripts/lean_calibration.py` compares it with the simulator rung by rung; the cadence phase, next-open fills, the per-order floor, live's resize / cooldown / stop and topology sizing were added to the simulator.

### 177. Forex features: Lean's fill-forward bar repeats the previous range, the dataset's was flat, and the betas counted filled days (V6.0.0)
🟢 `fixed` · 5/10

**Problem:** Lean's fill-forward forex bar clones the previous bar's high and low while the dataset's is flat at the previous close, and live regressed the sensitivity betas over the filled window. **Fix:** `forex_fill_forward_bars: "flat"`: live flattens a fill-forward bar (`flatten_fill_forward_bar`, the dataset's definition) before it joins the windows, and forex keeps real-bar-only histories for the betas.

### 178. Crypto and forex cross-asset features read a correlation window one bar longer than the dataset's; the TLT date is not the topology cache (V6.0.0)
🟢 `fixed` (BT1 reconciliation: ETHUSD 1 of 170 dates, BTCUSD, XOM, NVDA, TLT 0, against 58% for ETHUSD's momentum rank in BT2) · 5/10

**Problem:** BT2 reconciliation: ETHUSD `cs_momentum_rank_20` diverged on 58% of dates, `topology_correlation_strength` on 51%, the regime scores on 14%. **Fix:** `phase1.features.late_bar_cross_asset: "own_tick"`: `features.cross_asset_timing.LateBarCrossAssetCache` keeps the topology node and momentum map a crypto/forex symbol had at its own tick and the equity-tick re-score uses them; `--reconcile-features` then compares those payload features with the previous dataset row.

### 179. Main book: one change beats its costs, a slower book (R-BOOK) (V6.0.0)
🟢 `fixed` (decided by rule; kept by V6.1's every-phase re-score, #195) · 7/10

**Problem:** a rank IC of +0.05 does not pay a top-6/bottom-6 book's costs. **Fix:** of ~12 single changes on the ungated calibrated book, only B1 passes R-BOOK: `rebalance_every_bars` 10 -> 20 and `exits.max_holding_bars` 20 -> 40 (+0.42 / +0.42 Sharpe validation / backtest).

### 180. Crypto fees: limit exits, the passive-but-filled offset, a route-aware fee and smaller graduates (R-CRYPTO winner C5) (V6.0.0)
🟢 `fixed` (corrected by BT1's fee evidence) · 4/10

**Problem:** BT2 paid $1,131 of crypto fees on $775 of gross P&L; every exit was a market order at 80 bps. **Fix:** crypto exits rest as limit orders (risk exits still go to market), a 5-bar crypto timeout, a route-aware net-edge fee (maker 60 / taker 80) and graduates capped at 0.5% per name / 2.5% class; the research's offset 0.0 was reverted to 1.0 after BT1 (a limit at the last close is charged as taker).

### 181. Forex sleeve dropped by rule R-FX6 (V6.0.0)
🟢 `fixed` (decided by rule) · 3/10

**Problem:** the minimum-cap carry sleeve lost $544 net in BT2 (IB's minimum is ~11 bps a fill on its tickets). **Fix:** none of 48 variants is positive on the backtest split, so R-FX6 drops it: `forex_risk.enabled` false (also takes the pairs out of the book and liquidates held ones); forex still feeds the cross-asset features.

### 182. Latency: three measured cuts, two rejected by estimate (V6.0.0)
🟢 `fixed` · 4/10

**Problem:** `_build_model_input` took 2.75 ms a call and the regime experts ran per symbol. **Fix:** the sensitivity betas from cached float64 arrays, one sorted FRED index, and the experts for every symbol in one pass (`batch_experts_across_symbols`, 79 -> 16 ms a tick, bit-identical); R-LAT rejected re-using own-tick predictions and caching the indicator block.

### 183. Datasets and the backups: `full_dataset.csv` is the V5.8.0 window again, and the ETH/LTC vintage rows differ only in dead rows (V6.0.0)
🟢 `fixed` · 4/10

**Problem:** the local `full_dataset.csv` and split files were the pre-V5.8.0 window, and the Codespace-built datasets had ETH/LTC rows differing from local. **Fix:** `scripts/build_holdout_dataset.py --full-splits --write-split-files` rebuilds all four splits with the active scaler (never refit); old backups and `data_holdout/` deleted (`aq clean ml --apply`, 13.7 GB); `available_to` refreshed from the zips.

### 184. #104 teardown: the trivial algorithm hangs on the newest Lean image too (V6.0.0)
🔴 `closed` (environmental) · 3/10

**Problem:** was the teardown hang specific to the pinned `lean:17900` image? **Fix:** none: the 15-line `scripts/lean_teardown_smoke` also times out on `lean:latest` (2026-10-12), after the results; the pin stays.

### 185. BT1 (Lean, 2023-07-01..2026-09-30, the V6 config): +6.72% net, Sharpe +0.55 without the risk-free rate, drawdown 5.40% (V6.0.0)
🟢 `fixed` (written up; the drawdown clause is #196's) · 6/10

**Problem:** BT1 (`backtests/2026-10-15_14-55-24`): Lean Sharpe -1.55, net +6.72%, drawdown 5.40% (limit 5%), with the main book -$3.0k on the backtest stretch and +$5.9k on the seen holdout; crypto limit fills paid 70.9 bps against a 70 bps bound. **Fix:** the crypto limit offset back to 1.0 (a maker fill); R-POSTURE kept the gross cap at 1.0 (main-book P&L +$4.7k, Sharpe +0.55).

### 186. BT2 (Lean, same span, the corrected crypto config): +5.28% net, crypto fees halved, one small change moves a Lean path (V6.0.0)
🟢 `fixed` (written up; the consistency and drawdown clauses fail, reported) · 6/10

**Problem:** BT2 (`backtests/2026-10-15_17-29-50`): net +5.28%, Lean Sharpe -1.67 (+0.44 without), drawdown 5.50%; crypto paid 63.9 bps a fill ($546), but the main book earned $0.9k against BT1's $2.9k with identical selections. **Fix:** none: a different crypto P&L moves the whole-portfolio return the kill switch reads, which froze the equity book on different days, so one Lean path cannot rank configs at this precision; the whole-span gain over V5.8 sits in the seen holdout.

### 187. Phase-0 defects: the holdout report scored the backtest split, a silent rank-head fail-open, attribution by ticker and today's config, a preset trap, a NumPy deprecation (V6.1.0)
🟢 `fixed` · 5/10

**Problem:** `holdout_report.py` would have reported the backtest split as the holdout; the fail-open rank-head policy was recorded only as a reason string; `--attribute-lean` labelled positions by the day's book and read today's config; `presets.moderate` kept the pre-R-GATE spread; `pd.Timedelta(days=n)` raised a NumPy deprecation. **Fix:** holdout rows by `phase1.windows.holdout`, a logged `demotion_fallback`, attribution by the component that opened a position and the run's frozen config, the preset spread 0.10, `pd.Timedelta(n, unit="D")`.

### 188. The calibration tool simulated every Lean run with today's config and threw away why the simulator vetoed (V6.1.0)
🟢 `fixed` · 5/10

**Problem:** `scripts/lean_calibration.py` built the simulator from the current `config.json` for every window, so once V6 moved the book to 20/40 a re-run of a V5.8.0 window would have simulated the wrong book; it kept only engaged / vetoed per offline rebalance (the reason was dropped), counted a date the simulator never reached as a plain disagreement, compared only main book + crypto, and live's book history logged the rolling-IC gate's veto but not its reading. **Fix:** each window runs on its run's frozen config (`ml/evaluation/run_configs/<run folder>.json` through `lean_attribution.run_config_path`); `disagreement_table` lists every live-vs-offline disagreement with the offline reason and counts `missing_offline` dates apart; `--components` / `--rcal2` add the legacy signal and the three R-CAL2 windows (V6 BT2 backtest and holdout stretches, V5.8.0 BT2 backtest stretch) with a per-component correlation; `build_book_history_record` stores `rolling_ic` (mean, resolved dates, non-finite -> null) on every rebalance record.

### 189. Forex: Lean's market holidays dropped bars live never receives, the dataset kept them (V6.1.0)
🟢 `fixed` (dataset rebuilt on the Codespace; BT1's reconciliation confirms) · 4/10

**Problem:** EURUSD / GBPJPY diverged on 15 of 170 dates (`sens_*` betas for 6 dates, momentum / topology on 2024-01-23, MACD for 6 months, and 44 artefact cells on 2025-12-26 / 2026-01-02). **Fix:** `features.cross_asset_timing.lean_market_holidays` reads the database; `phase1.features.forex_lean_holidays` (on) drops holiday zip bars and stops filling them in `fill_forward_open_forex_days`, the timeline, the dataset's forex features and the parity replica; the reconciler compares any tick that holds a fill-forward bar (Sunday, or a weekday the zip lacks) on its payload features only (`forex_tick_holds_fill_forward_bar`); the bar probe takes `date_ranges` so BT1 logs Lean's bars on the holiday dates.

### 190. The simulator lacked the mechanisms that decided the V6 Lean runs, and charged no exit cost on a rebalance date (V6.1.0)
🟢 `fixed` (R-CAL2 stays branch B by the rule) · 8/10

**Problem:** live re-runs every member each session, watches the kill switch on the whole portfolio, trades crypto on weekends, caps 12 positions, passes members through the analyzer and runs the legacy signal; the simulator did none of this, charged no cost on age/stop exits on a rebalance date and read a non-existent regime key. **Fix:** `simulate_rank_book` options for each mechanism (defaults reproduce V6 exactly), the shared `derive_signal` in `main.py`, `scripts/build_legacy_probability.py`, a warm rolling-IC gate and `lean_calibration.py --rcal2`.

### 191. Latency: the feature path did not regress; Lean's per-tick cost is the host and the container (V6.1.0)
🟢 `fixed` (environmental) · 4/10

**Problem:** V6 BT2 took 111 minutes against V5.8.0's 48 on the same span, already in the warm-up year. **Fix:** none in the code: `_build_model_input` is 1.9 ms native (2.9 ms in V5.8.0), 5.3 ms in the Lean image and 8.9 ms in the engine on the 2011 4 GB PC; `TimingProbe` now records CPU time and a whole-tick section, and the profiler runs inside the Lean image.

### 192. Live crypto cannot fill through Interactive Brokers (V6.1.0)
🟡 `partial` (checked and flagged, routes studied in V6.6.0; the choice is the owner's) · 5/10

**Problem:** the book prices Coinbase fees (`CoinbaseFeeModel`, a cash account) and the backtests fill on Lean's Coinbase market, while the live credentials this project renders are Interactive Brokers'. QuantConnect's staff answer in the IB-crypto thread is "Interactive Brokers does not support crypto" (the LEAN pull request #8446 for it is still open), and Lean's Coinbase brokerage supports crypto on cash accounts only, with market, limit and stop orders. **Fix:** `execution.lean_config_render.validate_live_crypto_route` (advisory, never changes trading) is printed by `aq render-lean-config`; RUNBOOK's deploy checklist names it. Choosing the live crypto brokerage (Coinbase) or switching the crypto classes off before a live deploy stays with the deferred IB items. **Verification (V6.6.0 addendum: IB and TradeStation checked in #312, EOS delisted in #311):** `tests/test_lean_config_render.py`; sources: quantconnect.com/forum/discussion/18507, quantconnect.com/docs/v2/writing-algorithms/reality-modeling/brokerages/supported-models/coinbase. **V6.6.0 (`ml/evaluation/v660/venue_study.json`):** Coinbase direct is the only route for all 12 coins.

### 193. The README performance section mixed V5.8.0 text with V6 results (V6.1.0)
🟢 `fixed` (V6.3.0: every block regenerated on the shipped config and BT4; `scripts/readme_freshness.py` finds none stale, #206) · 4/10

**Problem:** every offline block (Monte Carlo, evaluation, benchmarks, as-live, research, kill-switch replay) dated from V5.8.0 and two contradicted the shipped config (the forex sleeve "shipped at gross 0.10", crypto caps 0.01 / 0.05); `_updated_at()` stamped render time, so a re-render made old data look fresh; `--audit-backtest`, `--attribute-lean`, `--audit-fills` and `--reconcile-features` did not refresh the README; Monte Carlo bootstrapped only the offline idealized book and said nothing about its source; `README.md` / `REPRODUCIBILITY.md` said `--all` excludes Monte Carlo. **Fix:** the research builder reads `v600/{forex,crypto}_research.json` and the shipped `config.json` (no typed settings), plus the R-CAL2 and rule-chain results; stamps show the source artifact's time and the render time; the four audit flags refresh the README; `aq evaluate --lean-monte-carlo` adds the Lean run's own bootstrap to the block with its source named; the run history keeps ten runs; docs corrected.

### 194. Retrained candidates and head blends: nothing beats the installed stack by more than seed noise (R-MODEL9, R-HEAD2; V6.1.0)
🟢 `fixed` (decided by rule; the installed models and blend stay) · 6/10

**Problem:** the installed multitask is the weakest of three control seeds, the trainers overfit (train IC 0.37, validation ~0), and the live blend serves the weaker sequence model first. **Fix:** none installed: 29 candidates; the best (`v9_reg`, swapped priority) gains +0.019 validation IC against a seed spread of 0.071, so R-MODEL9 fails; R-HEAD2's head blends lose on backtest. The tools ship (`model_candidate_research.py`, `prepare_v610_candidates.py`, a swapped-priority decision score).

### 195. Book cadence, net-edge holding period, legacy budget, gates, gross cap: decided on every rebalance phase (R-BOOK2, R-LEGACY, R-GATE; V6.1.0)
🟢 `fixed` (decided by rule; legacy L2 declined by the owner in V6.2.0) · 7/10

**Problem:** V6.0.0 picked the 20-bar book on one rebalance phase, but the shipped book's ungated validation Sharpe spans -1.02..+0.57 across its 10 phases. **Fix:** none adopted on all-phase medians: the 10/20 book is a near miss (+0.099 against +0.10), the holding-period change fails, legacy L2 (gross 0.15) passes the margins but not R-LEGACY's positive-on-both-splits clause, the gates are skipped (branch B); the RL guard state no longer leaks between runs.

### 196. BT1 (Lean, the V6.1 config = V6 BT2's): identical to V6 BT2, which confirms determinism (V6.1.0)
🟢 `fixed` (written up; the drawdown clause fails, #197) · 6/10

**Problem:** did V6.1's `main.py` changes alter behaviour, and why did the live rolling-IC gate read lower than offline? **Fix:** none in behaviour: all 1,268 order events equal V6 BT2's (+5.28%, drawdown 5.50%); live counts a crypto pair's IC event twice per date (its own tick and the next equity tick), which the offline gate now replicates (`with_live_event_duplicates`); R-POSTURE2 set a cap of 0.80 for BT2.

### 197. BT2 (Lean, gross cap 0.80 by R-POSTURE2): lower exposure, worse path; the shipped cap stays 1.0 (V6.1.0)
🟢 `fixed` (written up) · 6/10

**Problem:** BT2 (`backtests/2026-10-16_21-27-47`): net +3.80%, drawdown 7.80% against BT1's +5.28% / 5.50%; the main book fell from $1.5k to $0.4k. **Fix:** the cap is not confirmed (R-LEAN10's BT2 clause fails), so it stays 1.0: a smaller book changes which sessions the kill switch locks, so one path moves by more than the scaling.

### 198. CI red on the V6.1.0 commit: a test read the gitignored `ml/model_weights.json`; ubuntu-latest moves to 26.04 (V6.2.0)
🟢 `fixed` (GitHub CI green on the V6.2.0 commit `5d5ae86`, 2026-10-18) · 5/10

**Problem:** run 39036302436 failed python-tests (ubuntu, windows) and subsystem-matrix (ml) on one test: `test_v610_harness_warms_the_gate_on_earlier_rows_and_models_the_legacy_signal` reached `AsLiveHarness.v610_mechanisms()`, which reads `ml/model_weights.json`, present locally and on the Codespace but gitignored. CI also warned that `ubuntu-latest` moves to Ubuntu 26.04 from 2026-10-19 and that the Node 20 actions are forced onto Node 24. **Fix:** the test brings its own `ml_dir` (a stub `model_weights.json`) and score cache in `tmp_path`; `scripts/clean_checkout_test.ps1` runs CI's pytest command in a detached worktree of HEAD plus the working-tree changes, with no gitignored file (an AGENTS.md wrap-up step, `tests/README.md`); the Linux jobs pin `ubuntu-24.04` and the actions move to checkout / setup-python / setup-node / upload-artifact v7 (release notes read: nothing this repo uses changed); `codespace_stop_jobs.sh` matches the V6.1+ job names.

### 199. Lean's Sharpe charged a stale 5.5% risk-free rate and annualised a 7-day equity curve at 252 days (V6.2.0)
🟢 `fixed` · 6/10

**Problem:** Lean's sample risk-free file ended 2023-07 at 5.5% and was filled forward through 2026, and a weekend-trading equity curve (~365 returns a year) was annualised at 252. **Fix:** `evaluation/lean_statistics.py` reproduces Lean's Sharpe / Sortino / PSR exactly (`aq evaluate --lean-stats`), `scripts/refresh_lean_interest_rate.py` appends FRED DPCREDIT's change points (average 5.49% -> 4.69%), and `runtime.trading_days_per_year` is 365 (owner decision).

### 200. Idle cash earned nothing in Lean: a T-bill sweep (BIL), outside the strategy and its risk controls (V6.2.0)
🔴 `closed` (the sweep shipped and is confirmed; the lock-path sensitivity is a documented design limit, R-KILL branch C, #211) · 7/10

**Problem:** the mostly vetoed book left 70-95% of NAV in cash that earned nothing while Lean's Sharpe subtracts the full risk-free rate. **Fix:** `portfolio/cash_sweep.py` holds idle NAV in BIL (outside the universe and every strategy control) under a no-borrow and a Lean-margin limit; the risk controls read the strategy's own value (`advance_strategy_value`); the simulator, attribution and harness model it.

### 201. Crypto counted twice in the rolling-IC gate: decided by R-DEDUPE - not adopted (V6.2.0)
🟢 `fixed` (decided by rule; the double count stays) · 4/10

**Problem:** live records a late-bar symbol's IC event on its own tick and the next equity tick (#196). **Fix:** `rolling_ic_gate.late_bar_event_count` ("per_tick" default, "once") through one predicate, `should_record_ic_event`, live and offline; "once" lifts validation -0.45 -> +0.13 but costs -0.09 on backtest against a +0.10 bar, so not adopted (worth revisiting with more data).

### 202. Phase luck: a staggered tranche book, decided by R-STAGGER - not adopted (V6.2.0)
🟢 `fixed` (one tranche stays; V6.3.0's second look also adopted nothing, #212) · 5/10

**Problem:** the book's Sharpe depends on its rebalance phase (-1.02..+0.57 on validation); tranches at offsets should average that out. **Fix:** tranche helpers in `portfolio.book_construction` and `evaluation/tranche_book.py` (K phase-shifted runs, each tranche's kill switch fed the others' returns); S2 passed every `rule_verdict` margin (+0.26 / +0.52) but widened the validation phase range, the clause the lead exists for; the live path is built only on adoption.

### 203. Regularised retrain (more seeds, label noise, a train-chosen feature subset): R-MODEL10 installs nothing (V6.2.0)
🟢 `fixed` (decided by rule; the installed models stay) · 5/10

**Problem:** could stronger regularisation, judged as an ensemble against ensemble noise, beat the installed models? **Fix:** `label_noise_std`, per-model input features (so a subset model could ship), `select_feature_subset.py` (17 of 68 inputs on the train split) and a resampled-ensemble yardstick (0.034); every candidate fails clause 1 and no decision head passes R-HEAD.

### 204. Latency and the #104 teardown measured on a faster host: both are the dev PC (V6.2.0)
🟢 `fixed` (measured; no code change) · 4/10

**Problem:** was the 8.9 ms per `_build_model_input` call in Lean, and the teardown timeout, the code or the 2011 4 GB PC? **Fix:** none: on a 4-core DinD Codespace the call costs 0.6 ms in and out of the Lean image, a 3.25-year run takes ~10 minutes and all three runs shut down cleanly.

### 205. BT2 (Lean, the shipped V6.2.0 code and config): identical to BT3; run tooling defects found on the way (V6.2.0)
🟢 `fixed` · 5/10

**Problem:** confirm the shipped code in Lean (`backtests/2026-10-17_21-39-55`). **Fix:** BT2 equals BT3: +16.85%, Lean Sharpe +0.082 (-0.776 on the old basis), drawdown 4.30%, sweep +$10,699, strategy ex sweep $6,148 (Sharpe +0.54); the sweep and the 365 basis ship.

### 206. The README's backtest section had Lean's raw statistics dump and no bet, concentration or cost measures: rebuilt as "Backtest Statistics" (V6.3.0)
🟢 `fixed` · 4/10

**Problem:** Lean's 27 statistics were one unsorted dump without AUM, leverage, bets, HHI, drawdown percentiles, cost per turnover, deflated Sharpe, classification scores or per-class risk, and the T-bill carry was mixed into every number. **Fix:** `evaluation/backtest_statistics.py` (López de Prado ch. 14, portfolio and strategy-ex-sweep columns, a reason instead of a fabricated number), `evaluation/readme_statistics.py`, `aq evaluate --backtest-stats` / `--lean-report` (run by `aq backtest`) / `--classification`, and `scripts/build_trial_registry.py` for the deflated Sharpe's N.

### 207. Each Lean-run `aq evaluate` flag picked "the latest run" its own way and none honoured the README pin (V6.3.0)
🟢 `fixed` · 3/10

**Problem:** five flags chose the newest run by name, with or without an engine log, while the README used the pin, so two blocks could describe two runs. **Fix:** one resolver, `generate_backtest_report.resolve_lean_run_dir` (explicit, pin, newest finished run), for every Lean-reading flag.

### 208. The T-bill sweep was counted as equity in the order audit's per-class P&L (V6.3.0)
🟢 `fixed` · 4/10

**Problem:** BIL is a Lean equity outside the universe, so `--audit-backtest` filed $10.7k of carry under "equity" and made the book look equity-long. **Fix:** `backtest_audit.class_by_ticker_from_config` gives the sweep ticker its own class `cash_sweep` and falls back to `security_type`.

### 209. Codespaces billed while idle and the Lean host was undecided (lead 5) (V6.3.0)
🟢 `fixed` · 5/10

**Problem:** the monthly Codespace budget was ~90% used, the DinD Lean recipe was typed by hand and the docs still said Lean cannot run on a Codespace. **Fix:** AGENTS.md rule 13 (on only while a job runs, bundled work, DinD deleted after its pull), `scripts/codespace_lean_run.ps1` + `codespace_lean_dind.sh`, and `codespace_session_v630.sh` for the whole offline phase in one lifetime; Lean runs on a temporary DinD Codespace from now on.

### 210. R-CAL3: the offline simulator against V6.2.0's BT2 - branch B, the gates stay frozen (V6.3.0)
🟢 `fixed` (decided by rule) · 4/10

**Problem:** is the simulator calibrated on the shipped config, so the gates could be tuned? **Fix:** none allowed: correlation 0.79 / 0.70, gap +1.3 / -3.0 pp, agreement 78% / 94% on BT2's two stretches fail R-CAL2's clauses, so R-GATE3 is skipped.

### 211. R-KILL: the kill switch's window and a release band against its lock-path fragility - branch C, nothing adopted (V6.3.0)
🟢 `fixed` (decided by rule; #200 closes as a design limit) · 5/10

**Problem:** at the -1.0 floor a few dollars flipped Lean's lock path (46 against 14 lock dates on identical decisions). **Fix:** `risk.kill_switch.release_rolling_sharpe` (default `null`) through one function live and offline; the 120-bar window gains +0.24 Sharpe but locks on less than half of KS0's dates (safety clause fails), the release band is stable (0.99) but -0.06, so KS0 stays.

### 212. R-STAGGER2: S2's second look with phase measures that ignore one lucky phase - not adopted (V6.3.0)
🟢 `fixed` (decided by rule; the live tranche path stays unbuilt) · 4/10

**Problem:** S2 passed every margin in V6.2 but widened the phase range; the re-look replaced the range with robust measures. **Fix:** none adopted: +0.26 / +0.52 and the worst-phase clause pass, but the validation interquartile range widens 0.50 -> 0.67 (limit 0.62); both looks count in the trial registry.

### 213. BT4 (Lean, the V6.3.0 code, BT2's config plus the null release band): identical to BT2 order for order (V6.3.0)
🟢 `fixed` (the final run of the phase) · 3/10

**Problem:** confirm the new code is a no-op on the shipped path (`backtests/2026-10-18_12-55-00`, DinD Codespace). **Fix:** none needed: all 1,596 order events and 27 statistics equal BT2's, clean teardown; no rule shipped a change, so BT5 was not run. The statistics show the strategy at 0.17x of NAV, a 51.7% hit ratio and a 46% deflated Sharpe.

### 214. Engine image checked on the DinD host; run tooling fixed on the way (V6.3.0)
🟢 `fixed` (the local image was rebuilt on the PC in V6.4.1) · 4/10

**Problem:** the live path changed in V6.2, so the engine image needed rebuilding, and Docker Desktop cannot start on the PC. **Fix:** `scripts/codespace_engine_check.sh` builds it on DinD and checks `/api/assets-status` (the engine alone: alpine redis/postgres cannot start there), which now reports the sweep; the DinD runner puts the Lean CLI on PATH and each Codespace gets its own ssh config.

### 215. Data refresh to 2026-10-16: rows are appended in the stored vintage, never rewritten (V6.4.0)
🟢 `fixed` (decided; nothing pending) · 4/10

**Problem:** the data ended 2026-09-30; a full Yahoo rewrite would move every adjusted row (each new dividend rescales history), and with it the dataset, the models' inputs and the BT5 = BT4 check. **Fix:** `scripts/data_append_refresh.py` fetches from 14 days before the last stored date, puts today's vintage back on the stored basis (old / new close at the latest common date, 1.0 unless a dividend or split intervened), appends only the new rows and merges the FRED caches the same way; `scripts/data_append_guard.py` hashes every row up to 2026-09-30 before and after.

### 216. R-DEDUPE2: crypto counted twice in the rolling-IC gate, second look on the longer span (V6.4.0)
🟢 `fixed` (decided by rule; #201 closes: the double count stays) · 4/10

**Problem:** #201's rule did not adopt `late_bar_event_count: "once"` (validation +0.13, backtest -0.09 against a +0.10 bar) and said to revisit it with more data. **Fix:** the same variant, as-live, scored on validation and the pooled post-validation span (backtest + holdout, the holdout read logged); adopted iff `verdict_as_live` passes (backtest gain >= +0.10, validation >= -0.02, >= 60% of phases beat the base median on both splits, drawdown within 1 pp).

### 217. L1: engaged-day rank skill - does the gate protect capital or hide weakness? (V6.4.0)
🟢 `fixed` (decided by rule: the gate hides weakness, it does not protect capital) · 5/10

**Problem:** the gate vetoes most rebalances (mean exposure 0.17x) while the pooled IC (~0.05) cannot pay for a full book; is the IC higher when the gate lets the book trade? **Fix:** report, no config change. On validation and backtest (holdout report only) the gate's per-date verdict splits the dates; rank IC (daily mean, non-overlapping, HAC t), the top-6/bottom-6 spread and the as-live Sharpe over the days whose latest rebalance was engaged are compared with all days.

### 218. L2: direction heads - calibrated signal or diagnostic only? (V6.4.0)
🟢 `fixed` (decided by rule: direction = diagnostic only) · 4/10

**Problem:** the direction heads reach ~57-58% accuracy with a weak log-loss, and the Lean book's side accuracy is ~51%; they are not in the book. **Fix:** temperature scaling or isotonic regression fitted on validation only (the method chosen by cross-fitted log-loss), per-class thresholds, and three overlays on the percentile ranks (`portfolio/direction_overlay.py`): blend w=0.25, blend w=0.5, agree-filter margin 0.05. Shipped iff `verdict_as_live` passes AND the median turnover rises <= 20%; otherwise "direction = diagnostic only".

### 219. L3: the legacy signal against the main MoE book (V6.4.0)
🟢 `fixed` (decided by rule: the legacy sleeve and the models stay) · 5/10

**Problem:** legacy made ~+$1.45k against the main book's ~+$1.04k on the same Lean run; is it a better primary signal, a feature, or a permanent parallel sleeve? **Fix:** (a) legacy budget off / half (0.025 / 0.01) / double (0.10 / 0.04, with the legacy-positive clause), as-live: shipped iff `verdict_as_live` passes and validation improves.

### 220. L4: within-class equity ranking against the global pool (V6.4.0)
🟢 `fixed` (decided by rule: pooled equity + crypto ranks stay) · 5/10

**Problem:** equity carries ~88% of the risk share at a Sharpe of ~0.23; does ranking inside equities (or inside sectors) beat the pooled equity + crypto rank? **Fix:** W1 crypto leaves the main rank group, W2 `rank_signal.normalization: "sector_relative"`, W3 both. Shipped (best backtest median) iff the whole book stays non-inferior (>= -0.02 on both splits), the engaged equity IC and the equity sleeve's gross Sharpe rise on both splits, and the holdout Sharpe falls by <= 0.10 (one logged read).

### 221. L5: turnover against IC - the rebalance / max-hold grid (V6.4.0)
🔴 `closed` (adopted offline, reverted by R-LEAN13 on BT6; the book stays 20 / 40) · 4/10

**Problem:** with IC ~0.05 which (rebalance, hold) maximises the net Sharpe? V6's slower 20/40 book helped, yet the walk-forward net Sharpe is negative in 8 of 12 windows. **Fix:** rebalance {10, 20, 40} x hold {20, 40, 60} against 20/40, as-live, across rebalance phases: shipped iff `verdict_as_live` passes and the median AND p25 phase Sharpe are >= the base's on both splits (at most one Lean confirm).

### 222. L6: a staggered book judged on phase spread (V6.4.0)
🟢 `fixed` (decided by rule: closed by its precondition, no variant scored) · 4/10

**Problem:** S2 passed the level margins twice but widened the phase interquartile range (0.50 -> 0.67). **Fix:** T2, T2h (half-way adjustment), T3, T3h, ungated: shipped iff the median >= base on both splits, the validation IQR <= base, p10 >= base on both splits, the cost drag rises <= 30%, and L1 showed the gate protects capital. The live tranche path is built only on adoption.

### 223. L7: kill-switch design - the lock that one borderline order flips (V6.4.0)
🟢 `fixed` (decided by rule: closed by its precondition, no variant scored) · 5/10

**Problem:** at the -1.0 floor a few dollars moved the lock from 14 to 46 dates (#200); R-KILL rejected "lock less often". **Fix:** `risk.kill_switch.trip_confirm_bars` (default 1 = today) through the same function live and offline; KD1 confirm 3, KD2 120 bars + confirm 3, KD3 release -0.5 + confirm 3, KD4 floor -1.5.

### 224. L8: which experts earn their place in the legacy signal? (V6.4.0)
🟢 `fixed` (decided by rule: every expert stays) · 3/10

**Problem:** the four regime experts and the gating blend feed only the legacy signal (the main book ranks on the rank heads); attribution is by class, not by expert. **Fix:** contribution(e) = IC(legacy score) - IC(legacy score without e) on the engaged equity dates, both splits; experts at <= 0 on both splits are disabled together (`gating_network.disabled_experts`) iff the book is non-inferior as-live (>= -0.02 on both splits).

### 225. L9: crypto core against graduates - a repeatable rank effect or a few fills? (V6.4.0)
🔴 `closed` (adopted offline, reverted by R-LEAN13 on BT6; crypto graduates stay in the book) · 3/10

**Problem:** crypto_core made ~+$3.9k on 13 fills; the graduates +$85 on $141 of fees. **Fix:** bootstrap by trade on BT4's closed trades, leave-one-name-out (as-live), crypto IC; graduates on against off (only BTC / LTC selectable): graduates stay iff they beat core-only on the median Sharpe of BOTH splits.

### 226. L10: the residual rank head as a blend component (V6.4.0)
🟢 `fixed` (decided by rule: the residual head stays demoted) · 3/10

**Problem:** `residual_rank_20d` was demoted yet shows a positive walk-forward IC (~0.024). **Fix:** blends R1 (0.4 / 0.4 / 0.2), R2 (0.35 / 0.35 / 0.3), R3 (0.5 / 0 / 0.5) over rank_20d / rank_5d / residual_rank_20d, as-live: shipped iff `verdict_as_live` passes and neither the market nor the momentum loading of the book moves by more than 0.10.

### 227. L11: book-call probabilities in Lean, and the Lean-vs-offline parity rule R-L11 (V6.4.0)
🟢 `fixed` (R-L11 verified on BT5) · 3/10

**Problem:** the Backtest Statistics' classification table showed n/a log-loss for the Lean book calls: the book history dropped the head probabilities `main.py` already held. **Fix:** `diagnostics.book_history.include_probabilities` (a diagnostic, never an order input) logs `probability_up` and the two models' `direction_20d` per allocated and decided symbol; `evaluation/classification_parity.py` scores Lean and the offline head on the identical calls. R-L11 tolerance: |accuracy delta| <= 0.01, |neg log-loss delta| <= 0.01, median |probability gap| <= 0.005.

### 228. L12: the paper-period protocol and its band check (V6.4.0)
🟡 `partial` (protocol, tool and frozen bands shipped; the paper run itself needs the IB paper account) · 4/10

**Problem:** every recent rule names paper trading as the honest test, with no pre-registered success criterion. **Fix:** frozen config; at least 6 rebalances and 120 trading days; success = every checklist metric inside the 5-95% band of the contiguous 6-rebalance windows of the pinned final Lean run (veto rate, kill-switch lock share, strategy exposure, fills per rebalance, slippage, fee bps, strategy and sweep P&L per day, hit ratio, turnover); no live capital. `diagnostics.book_history.paper_enabled` writes the bounded book history in paper mode; `aq evaluate --paper-check` compares. **Verification:** `evaluation/paper_protocol.py`, `tests/test_paper_protocol.py`; a tool dry run on BT5's tail after 2026-09-30, labelled as such. **V6.6.4 (no broker needed):** `scripts/lean_smoke/live_plumbing.sh` ran `main.py` in Lean's `live-paper` environment on `PaperBrokerage` with a fake data queue and real Redis and Postgres (no login, key or terms). All four scenarios passed: it starts live and warms up from history, it stayed up for 51 s while Redis and then Postgres were stopped under it and came back, a second start on the same project directory came up, and the audit chain verified on the real database across the 2 entries `main.py` emitted (`ml/evaluation/v664/live_plumbing.json`). Not proved, and stated in that file: an order reaching a broker (no rebalance fell in the window), the kill switch under a forced drawdown (`main.py` is unchanged and fake prices are random), and reconciliation against a real broker's positions.

### 229. BT5 (Lean, V6.3's book plus the probability logging, 2023-07-01..2026-10-16) equals BT4 order for order (V6.4.1)
🟢 `fixed` (the baseline of the phase) · 3/10

**Problem:** prove the V6.4.0 instrumentation is a no-op on the trading path, extend the span to the appended data, and give R-L11 its Lean run (the Codespace budget was spent, so this ran on the PC's own Docker). **Fix:** none needed: 1,596 of 1,596 order events through 2026-09-30 are identical to BT4's (`ml/evaluation/run_configs/v640_bt5.json`), plus 50 events in October; the engine log reaches the teardown (the PC's usual timeout).

### 230. BT6 (Lean, the adopted 10 / 20 book + core-only crypto) fails R-LEAN13 and is reverted (V6.4.1)
🟢 `fixed` (decided by rule; `config.json` unchanged from BT5's book) · 6/10

**Problem:** #221 and #225 were adopted by the offline rules; the pre-registered confirm is one Lean run judged by R-LEAN13 (strategy Sharpe not below the baseline's by more than 0.10, drawdown within +1 pp, a complete run). **Fix:** `evaluation/lean_verdict.py` (`python -m evaluation.lean_verdict --baseline <BT5> --candidate <BT6>`): BT6 (`backtests/2026-10-22_12-41-40`, `v640_bt6.json`) made -$2,329 net, the strategy -$10,937 (Sharpe -1.12 against +0.35), drawdown 5.20% against 4.33%, fees $1,736 against $1,237, 1,873 order events against 1,646, hit ratio 44% against 52%: the Sharpe clause fails, so the three keys are back at 20 / 40 / graduates in.

### 231. Every Lean window label named a date two days after the run's end (V6.4.2)
🟢 `fixed` · 3/10

**Problem:** the README Overview, every run-history row, Backtest Statistics' "Time range" and the Lean Monte Carlo line took the window's end from the last Strategy Equity point, which Lean writes about two days past the end (BT5: "to 2026-10-18" for a run ending 2026-10-16). **Fix:** `evaluation/backtest_audit.configured_run_window` reads `algorithmConfiguration.startDate/endDate`; `generate_backtest_report.load_backtest_summary`, `backtest_statistics` and `aq evaluate --lean-monte-carlo` label with it and fall back to the chart only when it is missing. The statistics keep using the chart series on purpose (V6.6.0): it is Lean's own daily marking, and only the label needed the configured window.

### 232. The README's run history had no date and no status: the rejected BT6 read like any run (V6.4.2)
🟢 `fixed` · 2/10

**Problem:** `AQ:BACKTEST_HISTORY` listed the ten newest runs without saying which one is shipped or which one a rule rejected, and carried no date, so the freshness check skipped it. **Fix:** a Status column from `run_status` (the README pin = "shipped (README pin)", each `ml/evaluation/*/r_lean*.json` verdict = "kept / rejected (R-LEANnn)") and a `computed YYYY-MM-DD` line; `readme_freshness.py` now dates the block like any other.

### 233. The walk-forward blocks always read "undated", and the freshness check missed the research sources (V6.4.2)
🟢 `fixed` · 2/10

**Problem:** the walk-forward block printed only its re-render time as "Last updated ... (no `|`), so `readme_freshness.py` never matched a date and every phase had to `--allow` it; the `RESEARCH` block's source list missed `holdout_report.json` and the V6.4 files. **Fix:** the blocks print the run id and the summary file's write time ("computed 2026-10-13 ... (rendered ...)"); the walk-forward blocks are model-bound (stale only when older than the installed models, `MODEL_FILES`), since only a retrain can refresh them; `RESEARCH` lists `holdout_report.json`, the V6.4 research and the R-LEAN13 / R-LEAN14 verdicts.

### 234. R-LEAN14: the two halves of BT6 judged one at a time, rule written before the runs (V6.4.2)
🟢 `fixed` (rule registered 2026-10-23, `ml/evaluation/v642/r_lean14_rule.json`) · 4/10

**Problem:** R-LEAN13 judged the 10 / 20 book and core-only crypto together (#230), so neither half is known; a change adopted on Lean evidence needs superiority, not R-LEAN13's non-inferiority. **Fix:** BT7 = BT5 + the book keys only (`v642_bt7.json`, sha256 107ab4f6...), BT8 = BT5 + `core_only` only (`v642_bt8.json`, ab2bb581...), checked to differ from BT5 by exactly those keys and to add up to BT6.

### 235. Lean on the 4 GB PC: the 90 s ceiling is `algorithm-creation-timeout`, a slow CLI probe read as "not found", a VM that would not boot (V6.4.2)
🟢 `fixed` · 6/10

**Problem:** with ~300 MB free, (a) WSL's `CreateVm` timed out, so Docker Desktop never started its engine (it also misread a slow `wsl --version` as "WSL update required"); (b) `aq backtest` reported "Lean CLI not found" because the venv CLI's `--version` took longer than the 30 s probe; (c) two BT7 starts died at Lean's 90 s limit while Python imported `main` (#16). **Fix:** (a) boot the `docker-desktop` VM by hand and keep it alive, then start Docker (recipe in `development/infrastructure.md`); (b) the probe waits 120 s (`aq_cli._find_quantconnect_lean_binary`); (c) `lean.json` sets `algorithm-creation-timeout: 600`, the engine key behind the 90 s (found in `QuantConnect.Lean.Engine.dll`), a host-speed setting that changes no trade.

### 236. Smaller gaps found by the V6.4.2 audit (V6.4.2)
🟢 `fixed` · 3/10

**Problem:** `lean_verdict` scored both runs with the root `config.json`; `retraining/lean_backtest.py` launched `lean backtest` on a candidate's model folder, which can only fail; `aq backtest` dropped the README pin silently; the DinD runner froze no `run_configs/<folder>.json`; AGENTS.md's rule 5 and CI job list, `portfolio/README.md` (`core_only`, the offline-only `tranche_adjust_fraction`), the parity table (`core_only`) and `evaluation/README.md` (11 flags) had drifted; #214 still read `partial`. **Fix:** per-run frozen configs in `lean_verdict.run_config`; the retraining gate returns `not_a_lean_project` without a `main.py`; the unpin prints the dropped run and the re-pin command; `codespace_lean_run.ps1 -Pull` copies each named config to its folder name and checks the hash; the docs are updated and #214 is `fixed` (the image was rebuilt on the PC in V6.4.1).

### 237. BT7 and BT8 (Lean, each half of BT6 alone): R-LEAN14 adopts neither, the book cadence carries the loss (V6.4.2)
🟢 `fixed` (decided by the pre-registered rule #234; `config.json` unchanged) · 5/10

**Problem:** split BT6's -$14.8k strategy loss against BT5 between its two changes, and adopt a half only on Lean superiority. **Fix:** none needed, both runs complete on the PC's Docker (0 inference failures, the PC's usual teardown timeout). BT7 (`backtests/2026-10-24_05-28-07`, 10 / 20 book): +5.24% net, strategy -$4,895 (Sharpe -0.44 against +0.35), drawdown 3.48%, fees $1,910, 1,246 orders, so it fails the Sharpe clause.

### 238. The holdout rows refreshed on the 4 GB PC by a guarded splice, not the 8 GB rebuild (V6.4.2)
🟢 `fixed` · 4/10

**Problem:** the PC's `ml/datasets/full_dataset.csv` ended 2026-09-29 (pre-refresh build); the 2026-10-16 build existed only on the training Codespace, and a full rebuild needs ~8 GB. **Fix:** `scripts/splice_holdout_dataset.py`: `--build` runs `build_holdout_dataset.py` with one-month train / validation windows from a start a sensitivity lookback before the holdout (2024-05-31; a 2025-03 start left the trailing 252-row `sens_*` betas at 0.0, which the guard caught), at ~400 MB; `--splice` streams the old rows before 2025-07-01 and the new holdout rows into the file after an overlap guard (every feature and label of 32,179 rows dated 2025-07-01..2026-08-28 equal within 1e-9).

### 239. The stopped training Codespace deleted (V6.4.3)
🟢 `fixed` (owner decision 2026-11-02) · 2/10

**Problem:** `aq-sshd-only-test-7v49pjgx6jg43r7g6` (stopped since V6.4.0) billed storage while holding only the rejected `v640_mt_leg_s1..5` / `v640_cand_*` candidates (L3, #217) and an old dataset. **Fix:** deleted with `gh codespace delete --force` on the owner's answer; the candidates are gone (they were never installable).

### 240. Lean 4 proofs of the shared pure functions (V6.4.3)
🟢 `fixed` · 5/10

**Problem:** the safety invariants of the functions `main.py` and the simulator share (order gate, hash chain, book neutrality and construction, risk controls, kill switch, sizing, cost model, reconciliation, sleeve guard, JSON safety) lived only in docstrings and example-based tests. **Fix:** `formal/` (Lean 4 v4.35.0 + Mathlib v4.35.0 from its cache): 11 specs generic over an ordered field (one proof for ℚ and ℝ, `Real.lean` restates the headline theorems at ℝ), 143 theorems and lemmas, no `sorry`; `GenCases.lean` (run interpreted: `lake env lean --run`, no Mathlib C build) runs the models at ℚ on seeded inputs and edge cases (3,134 cases) into `aether_quant/_formal_cases/`, which `tests/test_formal_differential_*.py` run the Python against (CI needs no Lean); `aq prove [--module] [--regen-cases] [--check-sorry]`; new test bucket `formal` (CI matrix).

### 241. The sector cap does not survive the dollar-neutral step (V6.4.3)
🟢 `fixed` (V6.4.4: BT11 passed R-LEAN16, the key ships, #267) · 4/10

**Problem:** `apply_book_neutrality` shrinks one leg only in step 3, so a sector holding a long and a short can end above `sector_max_net_weight`; the docstring only claimed the cap after step 2. **Fix:** `phase_v2.portfolio_book.neutrality.reapply_sector_cap_after_dollar_neutral` (default `false`, the shipped book): the sector shrink runs again after step 3, proved to hold every sector within the cap at the end (`sector_cap_with_reapply`) at the cost of a net exposure of at most 1.45% on BT5's books (mean L1 change 0.3%).

### 242. A non-positive per-name cap erased or flipped the book (V6.4.3)
🟢 `fixed` · 3/10

**Problem:** step 1 of `apply_book_neutrality` always clipped to `[-cap, cap]`: `max_weight_per_name = 0` zeroed every weight, a negative value turned every weight, shorts included, into a long of |cap| (`old_clip_flips_shorts`). The sector and gross steps already skipped a non-positive cap. **Fix:** step 1 is skipped for a cap <= 0 (`per_name_cap_skipped_nonpositive_cap`), like the other caps. Shipped value 0.12, so no shipped behaviour changes.

### 243. Non-finite and misconfigured inputs in the sizing path (V6.4.3)
🟢 `fixed` · 5/10

**Problem:** the non-finite audit of the verified functions found: `cap_target_weight(nan, ...)` returned a full short of the remaining capacity (`nan >= 0.0` is False); `build_dynamic_position_sizing` turned a NaN base target into a NaN weight, and a negative multiplier product (a misconfigured `min_*_multiplier < 0`) flipped the trade and escaped `max_position_weight` (`old_negative_product_escapes_cap`: 50x the cap, wrong side); `trailing_drawdown(..., lookback_bars=0)` read the whole history (`xs[-0:]`). **Fix:** a non-finite target is blocked `(0.0, True)`; a non-finite base sizes to 0 and the sized magnitude is clamped at 0; a non-positive lookback reads no window. Finite, configured inputs are bit-identical; the guards cost 0.1-1.2 µs a call (idle PC, `scripts/v643_microbench.py`, ~0.1 ms a bar over 74 symbols).

### 244. Hash-chain truncation is invisible (V6.4.3)
🟢 `fixed` · 3/10

**Problem:** every prefix of a valid audit chain is valid (`truncation_undetected`), so deleting the newest rows passes `verify_chain`; the module docstring claimed any deletion breaks the chain. Deleting a row with a successor is detected (`delete_detected`), as are altered fields (`payload_tamper_detected`). **Fix:** `verify_chain(rows, expected_tail_hash=None)`: with the latest hash recorded elsewhere, a truncated chain reports index `len(rows)`. Default unchanged.

### 245. Two verification tools lied quietly: README stamps under test, a clean checkout of HEAD (V6.4.3)
🟢 `fixed` · 4/10

**Problem:** four tests (`aq backtest` wiring, `aq evaluate --reconcile-features`) ran the real `_refresh_readme_evaluation_sections`, so every `aq test --cli` changed five "rendered" stamps in the repository's README. **Fix:** an autouse fixture in `tests/test_aq_cli.py` patches the refresh (tests that check it patch it themselves); the script lets git write the patch (`--output`) and stops when it does not apply.

### 246. The beta-neutral and residual labels' lookahead, measured (V6.4.3)
🟢 `fixed` (default unchanged; a retrain can switch) · 3/10

**Problem:** #238: both labels residualise against one whole-history beta per asset, fitted on forward returns that include the label's own future. **Fix:** `features/asof_beta_labels.py` (a trailing 252-day beta of realised daily returns, as of each date; train.py's definitions otherwise unchanged) and `phase1.target.ranking.beta_estimation` (`"full_history"` default, `"asof"` for a retrain); `cross_sectional_residualize` moved there and shared with train.py.

### 247. The installed model ranks worse than "who the asset is" (V6.4.3)
🔴 `closed` (a measurement; it feeds the next retrain, no code fix) · 6/10

**Problem:** `aq evaluate --audit-leakage` (new) on the validation split: no feature is flagged (no forward-looking window, no IC left after shuffling the target, no single feature above |0.15|), but the installed live score's mean daily rank-20d IC is 0.004, below a pure asset-identity prior (each ticker's mean train target, 0.021) and far below an asset-class prior (0.066). **Fix:** none in this phase (no retrain, owner decision 2026-11-02). A retrain should start from what V6.4.3 measured: per-date cross-sectional inputs, the as-of labels (#246), and a model that has to beat the identity and class priors before it beats nothing.

### 248. R-MODEL11: no factor, probe, blend or head switch qualifies; the grid overfits (V6.4.3)
🟢 `fixed` (decided by the pre-registered rule; `config.json` unchanged) · 6/10

**Problem:** find a better signal than the installed V5.8.0 stack without retraining it: 17 trials written down before any score (`ml/evaluation/v643/r_model11_rule.json`, one dated amendment adding S1 before scoring): five factors and their composite, ridge and gradient-boosting probes on per-date ranked features (one on the as-of residual label), three blends of the installed score with the factor composite, a regime-weighted factor mix and the sector-neutral head as the live signal. **Fix:** none qualifies. The grid's probability of backtest overfitting is 0.66 (CSCV, 16 blocks, 12,870 splits; out-of-sample Sharpe falls by 0.64 per unit of in-sample Sharpe), which by clause 4 blocks every candidate, and no candidate passes `verdict_as_live` on its own either: each one that beats the installed book on one split loses on the other (S1: backtest as-live Sharpe +1.07 against +0.90, validation -0.76 against -0.51; B1: validation +0.84, backtest -0.00).

### 249. R-CAL4: the simulator tracks the last three Lean runs at 0.44-0.61; no option adopted (V6.4.3)
🟢 `fixed` (decided by the pre-registered rule; branch B stands) · 5/10

**Problem:** an offline win only means something if the simulator tracks Lean (R-CAL2 left it at ~0.7 on older runs; BT6 / BT7 lost in Lean what the simulator had adopted). **Fix:** `scripts/lean_calibration.py`'s ladder on BT5 / BT7 / BT8 (2023-07-01..2026-10-16): the calibrated rung's daily correlation is 0.614 / 0.439 / 0.578 (decision agreement 87% / 83% / 87%; replaying live's own gate decisions lifts it to 0.74 / 0.73 / 0.71), so branch B stands.

### 250. Research and audit tools, and the `aether_quant` library (V6.4.3)
🟢 `fixed` · 3/10

**Problem:** each research phase rebuilt its scoring in a one-off script, there was no overfitting statistic across a grid of variants, no factor baseline to beat, no leakage or identity check, and nothing of the system was importable as a library. **Fix:** `evaluation/research_harness.py` (`aq research --signal CSV`), `pbo.py` (`--pbo`), `factor_spanning.py` (`--factor-spanning`), `leakage_audit.py` (`--audit-leakage`), `overfit_diagnostics.py` (`--overfit-report`), `sim_lean_calibration.py` (`--calibrate-sim-lean`), `research_probes.py`, `trial_registry.py` (moved from the script), `features/cross_sectional_norm.py`; `aether_quant/`: a facade re-exporting the shared pure functions (the same objects `main.py` uses), the research tools and the Lean cases, with `lib` / `research` extras, `py.typed`, a pinned public surface (`tests/data/aether_quant_api.json`) and `examples/aether_quant_quickstart.py`.

### 251. A shell script with CRLF endings would break on the Codespace (V6.4.4)
🟢 `fixed` · 2/10

**Problem:** `scripts/codespace_retrain_v580.sh` had CRLF in the working tree despite `*.sh text eol=lf`; a tar push carries the working tree, so bash on the Codespace would fail on it. **Fix:** rewritten with LF (the index content is unchanged).

### 252. The Codespace keepalive returned while long jobs still ran (V6.4.4)
🟢 `fixed` · 3/10

**Problem:** `scripts/codespace_keepalive.sh` matched only the session, research, test and multitask / sequence trainer processes, so a `train.py` walk-forward, a retrain script, `v644_research.py` or a dataset build could lose its ssh hold and idle out with the Codespace. **Fix:** the pattern also matches `codespace_retrain_`, `train.py`, `v644_research.py` and `build_holdout_dataset.py`.

### 253. Training-Codespace docs: an ambiguous create command and a wrong repo path (V6.4.4)
🟢 `fixed` · 2/10

**Problem:** `development/infrastructure.md` created the training Codespace without `--devcontainer-path` (the repo has two devcontainers) on a 2-core machine, and told users to `cd Aether-quant` (the repo is `/workspaces/<repo>`). **Fix:** the documented command names the devcontainer, the 4-core / 16 GB machine (owner choice), `--idle-timeout 30m` and the display name the sync script expects; the paths point at `/workspaces/*/`; `.devcontainer/README.md` says the 2-core requirement is a minimum.

### 254. A Lean run on the DinD Codespace could not use other models (V6.4.4)
🟢 `fixed` · 4/10

**Problem:** `main.py` reads its models from fixed `ml/` paths and the DinD runner swapped only `config.json`, so a retrained candidate could not be backtested there without installing it first. **Fix:** `scripts/codespace_lean_dind.sh` copies `ml/evaluation/run_artifacts/<run>/` over `ml/` for that run only, restores and byte-verifies the originals afterwards (a failed restore stops the batch), and writes `run_artifacts_manifest.json` into the run folder; `codespace_lean_run.ps1 -Pull` refuses a run that used an overlay but has no manifest.

### 255. The as-live harness returned stale cached scores for ranked inputs or a seed ensemble (V6.4.4)
🟢 `fixed` · 5/10

**Problem:** `scripts/as_live_levers._fingerprint` keyed the cached live score on the model files, the dataset and `phase_v2.rank_signal` only; scoring the same models with `phase1.features.cross_sectional_inputs` or `phase_v2.model_ensemble` turned on (or with new ensemble members) read the old cache. **Fix:** both settings and the ensemble members' files enter the key when either is on; a default config keeps its old key, so existing caches stay valid.

### 256. The training Codespace had no parquet reader for the research chains (V6.4.4)
🟢 `fixed` · 3/10

**Problem:** the research chains cache scores and trial returns as parquet, but `pyarrow` was only in `pyproject.toml`'s `research` extra, which the devcontainer never installs; the V6.4.4 session stopped at its first parquet write. **Fix:** `pyarrow>=14.0` in `requirements/requirements-dev.txt` (the devcontainer's install list); the running session was unblocked with a one-off `pip install`.

### 257. Two DinD runner failures: the create on Windows PowerShell 5.1 and the Docker config folder (V6.4.4)
🟢 `fixed` · 4/10

**Problem:** `codespace_lean_run.ps1 -Create` ran gh under `$ErrorActionPreference = 'Stop'`, so gh's stderr notice ("usage ... is paid for by ...") became a terminating error and no Codespace was created; on the new Codespace the docker-in-docker feature (Docker 29) no longer creates `/etc/docker`, so writing `daemon.json` failed and dockerd never moved to `/tmp`. **Fix:** the create runs with `Continue` and stderr discarded, then checks gh's exit code; the runner creates `/etc/docker` before writing `daemon.json`.

### 258. Data to 2026-11-02 (V6.4.4)
🟢 `fixed` · 3/10

**Problem:** the data ended 2026-10-16. **Fix:** `scripts/data_append_refresh.py --end 2026-11-03 --cutoff 2026-10-16 --apply`: 11 sessions appended to all 105 files in the stored vintage (splice factors 1.000-1.006), FRED appended after the cutoff; `config.json` `available_to` and the holdout end move to 2026-11-02 (a data-only change); the local holdout rows were rebuilt with `splice_holdout_dataset.py` (to 2026-11-01).

### 259. The identity / class priors mostly measure a percentile-rank artifact (V6.4.4)
🟢 `fixed` (the audit reports both; the labels themselves are unchanged) · 6/10

**Problem:** a percentile rank in a group of n names averages (n+1)/2n. With separate rank groups (bond 22 names, forex 15, the main pool) and small sectors the per-group label means are constants (bond 0.5227, forex 0.5333, sector-neutral equity 0.5833, identical in train and validation), so a pooled per-date IC rewards knowing a name's group size: the "class prior" of #247 (0.066 on rank_20d, 0.090 on the sector-neutral target) and part of every model's pooled IC are that artifact, which a book ranking within groups cannot trade. **Fix:** `evaluation/leakage_audit.identity_check(..., group_column=)` and `centre_by_group` also report every figure on the group-centred target (`aq evaluate --audit-leakage` passes the label's rank groups); `scripts/v644_research.py --centred` scores on centred labels (rule R-MODEL13, #263).

### 260. Ranked model inputs, built and judged offline (V6.4.4)
🟢 `fixed` (default off; not wired into `main.py`, no candidate qualified) · 4/10

**Problem:** #247 asked for per-date cross-sectional inputs; nothing in the trainer or the scorer supported them. **Fix:** `features/cross_sectional_inputs.py` ranks each `*_scaled` input within (bar, asset class) ("replace", or "append" as `<name>_csr`), one definition in list and pandas form; `train_multitask.py` (and so the walk-forward) and `aq_cli._blend_raw_scores_for_dataset` apply it behind `phase1.features.cross_sectional_inputs` (default off), and the trainer stamps the setting into its schema.

### 261. R-MODEL12: no retrained candidate beats the priors (V6.4.4)
🟢 `fixed` (decided by the pre-registered rule; `ml/` unchanged) · 6/10

**Problem:** the retrain #247 asked for, judged by a rule written before any score (`ml/evaluation/v644/rules.json`, sha `42dcaf43…`): seven multitask recipes on as-of labels (today's, the sector-neutral head as the target, ranked inputs, both, plus regularisation, ListNet, append mode), seed 1 first, seeds 2-3 for at most three survivors, then as-live, PBO, a walk-forward and one holdout read. **Fix:** none qualifies: every seed-1 candidate fails C1 (validation IC at or above the identity / class priors and the installed model + 0.034); the best validation non-overlapping IC is M4's 0.079 (ranked inputs, sector-neutral target, regularised) against priors of 0.079 / 0.090. No stage 2, no walk-forward, no holdout read.

### 262. R-TREND1: the trend sleeve loses on the backtest (V6.4.4)
🟢 `fixed` (decided by the pre-registered rule; the sleeve stays off) · 5/10

**Problem:** time-series momentum is the one classic alpha source the system lacked: a small directional sleeve on SPY, QQQ, IWM, EEM, TLT, IEF and USO (`portfolio/trend_sleeve.py`: the sign of the trailing return, inverse-volatility weights aimed at 3% of NAV a year, caps, a 2% loss guard; the owner approved researching and shipping it by rule). **Fix:** K1 picks T2 (126-session sign; train+validation net Sharpe +0.40, phase median), K2 passes, K4 passes (correlation with the main book 0.10), but K3 fails (backtest net Sharpe -0.34; all four trials lose on 2023-07..2025-06: T1 -0.48, T3 -0.61, T4 -0.33) and K5 fails (the combined book's backtest Sharpe -0.02 against the main book's -0.04 + 0.10).

### 263. R-MODEL13: the same grid on group-centred labels, nothing qualifies (V6.4.4)
🟢 `fixed` (a follow-up rule written before any centred score; `ml/` unchanged) · 5/10

**Problem:** #259 showed R-MODEL12's C1 bar was mostly an artifact, so its verdict says little about skill. **Fix:** R-MODEL13 (`ml/evaluation/v644/r_model13_rule.json`, written after R-MODEL12's stage 1 and before any centred number; the raw validation ICs already seen are listed in it) repeats R-MODEL12 with C1 / C3 on group-centred labels.

### 264. R-CAL5: the live-gate replicas re-derived from the engine's trades; no option adopted (V6.4.4)
🟢 `fixed` (decided by the pre-registered rule; moot since #272 retired the gated simulator from selection, and `target_weights_engine` is the instrument) · 4/10

**Problem:** the #249 lead: re-derive the simulator's resize / cooldown / trailing-stop replicas from Lean's own trades (the order events carry no reason tags). **Fix:** `evaluation/gate_replica_audit.py` classifies Lean's fills and the simulator's weights into entries, exits, flips and resizes on and off live's rebalance dates (Lean fills a close decision at the next open, one session later).

### 265. A proof-of-alpha report for any Lean run (V6.4.4)
🟢 `fixed` · 3/10

**Problem:** the README reported the strategy's Sharpe and deflated Sharpe, but nothing asked whether its return is alpha (not explained by market exposures), per period, including data no model or rule has seen. **Fix:** `evaluation/alpha_proof.py` / `aq evaluate --alpha-proof`: per period (the run, backtest, holdout, the fresh weeks after 2026-10-16) the strategy's Sharpe with a stationary-bootstrap 95% interval, its alpha against SPY / AGG / BTC on the session calendar with a Newey-West t (the factor-spanning estimator), PSR and the deflated Sharpe over the trial registry, and the descriptive R-ALPHA1 verdict (written in `rules.json`).

### 266. BT10: the shipped book on the new data, the V6.4.4 Lean baseline (V6.4.4)
🟢 `fixed` · 3/10

**Problem:** every V6.4.4 Lean candidate needs a baseline over the same window, which now ends 2026-11-02. **Fix:** BT10 = CFG0 (`ml/evaluation/run_configs/v644_bt10.json`, sha `13f89088…`) over 2023-07-01..2026-11-02 on a DinD Codespace (`backtests/2026-11-03_16-16-07`, 614 s): it repeats BT5 fill for fill through 2026-10-16 (762 of 762) and adds 7 fills in the fresh weeks.

### 267. BT11: the sector cap re-applied after the dollar step passes R-LEAN16 and ships (V6.4.4)
🟢 `fixed` (adopted by the pre-registered rule; README pinned to BT11) · 4/10

**Problem:** #241's owner call: `phase_v2.portfolio_book.neutrality.reapply_sector_cap_after_dollar_neutral` keeps every sector within its cap (proved) at the cost of up to ~1.5% net exposure; it needed a Lean run. **Fix:** BT11 = CFG0 + the key (`v644_bt11.json`, sha `b16aa933…`, `backtests/2026-11-03_16-26-39`): strategy Sharpe +0.268 against BT10's +0.263, max drawdown 4.98% against 4.98%, a complete run; R-LEAN16 (non-inferiority, written in `rules.json` before the run) keeps it, so `config.json` gets the key (CFG1 sha `c9c8732d…`, = BT11's frozen config without its window override).

### 268. A candidate's vault commit silently dropped its model and scaler, so no commit could ever restore one (V6.5.0)
🟢 `fixed` (released in aether-vault 1.7.0, V6.6.0) · 8/10

**Problem:** `av` matched this repo's `ml/*.pkl` and `ml/*.pt` with a `*` that crosses `/`, so `av add ml/versions/<id>` dropped `scaler.pkl` and `model.pt` with no message. `.av` had never held a commit, so nobody had seen it. **Fix:** Aether-Vault Probleme.md #189: `.gitignore` patterns match per path segment, like git. `tests/test_vault_contract.py` runs the real `av` against a copy of this `.gitignore`. **Verification:** the contract test asserts every `REQUIRED_CANDIDATE_FILES` entry is in the commit's tree; `av log` in this repo now holds real gate commits (`e390a72`, `bd88f8d`, ...).

### 269. The vault client could lose `av`'s output on Windows and stored only a short hash (V6.5.0)
🟢 `fixed` · 6/10

**Problem:** `run_av_command` decoded output with the system codepage; `av`'s UTF-8 banner killed the reader thread and left `stdout` as `None` on Windows. The hash was scraped from human text with a regex capped at 40 characters, and a push queued because the server was unreachable looked the same as a delivered one. **Fix:** explicit UTF-8; commit, push and restore read `av --output json`; the full 64-character hash is stored; `push_state` is `drained`, `queued`, `failed` or `skipped`, and `vault.require_push` (default off, today's behaviour) can make a queued push block. **Verification:** `tests/test_vault_client.py`, `tests/test_vault_commands.py`, and `tests/test_vault_contract.py` against the real CLI, including an unreachable remote.

### 270. Rollback ran a repo-wide `av checkout` that could overwrite and delete source files (V6.5.0)
🟢 `fixed` · 8/10

**Problem:** when a candidate's files failed their hash check, `orchestrator.rollback` ran `av checkout <hash>`, which overwrites every tracked file (`main.py`, `train.py`, `config.json`) and deletes whatever the old commit did not track. A dirty tree made it refuse and still exit 0, so the failure was invisible. **Fix:** new `av restore --source <hash> PATH... (Aether-Vault #193), restoring only `ml/versions/<id>/`; `av checkout` failures now exit non-zero (Aether-Vault #190). Rollback never calls `checkout`. **Verification:** `test_rollback_restores_only_the_candidate_from_the_vault_and_never_runs_a_checkout`, and the real-CLI contract test where a dirty sibling survives a restore.

### 271. A worker without `av` found out only after a whole training run (V6.5.0)
🟢 `fixed` (aether-vault pinned in `requirements/requirements.txt`, 1.7.1 since 2026-11-06; verified in the image on 1.7.0, #308) · 5/10

**Problem:** the retraining worker image has no `av`, so every cycle would train fully and then fail at the commit. `vault.repo_path` was read by nothing and rollback ignored the timeout. **Fix:** `vault_preflight` runs before training and fails the event with the reason. New `vault.enabled` (default on), `vault.min_version`, `vault.extra_add_paths` (the other trainers, `features/`, schema and dataset manifest, so a commit can reproduce a candidate); `repo_path` is now the working directory; `.av/` is in `.dockerignore`. **Verification:** `test_run_once_stops_before_training_when_the_vault_preflight_fails` and the preflight tests. **V6.6.0:** released and pinned; CI now runs `tests/test_vault_contract.py` against it, and 16 queued commits drained to a real 1.7.0 server, with a candidate's `model.pt` and `scaler.pkl` restored byte for byte from a fresh clone.

### 272. The offline simulator could not be trusted to select anything (V6.5.0)
🟢 `fixed` for a new path; the gated path's simulator is retired from selection, and no candidate has been chosen on it since · 9/10

**Problem:** the rank-book simulator tracks the gated live path at a daily correlation of about 0.73 and has got the sign wrong (BT6: +1.06 offline, -1.12 in Lean), because the path has too many gates to replicate. Offline selection on it was not selection. **Fix:** `phase_v2.target_weights` (default off): `main.py` executes a hash-pinned file of target weights with no gates between a weight and its order, and `evaluation/target_weights_engine.py` calls the same pure functions (`rebalance_deltas`, `daily_financing_usd`, `cash_sweep_target_weight`). **Verification:** R-INSTR1: daily correlation 0.9999993 (equities), 0.99999994 (crypto), 0.992 (mixed), 0.99999995 (oracle, drawdown lock on the same day); annual gaps 0.14, 1.27, 65 and 3.6 bps. BT16 in a parallel batch equals BT13 alone, order for order, and BT12 (flag off) equals BT11 (`ml/evaluation/v650/instrument_result.json`).

### 273. Comparing the engine with Lean found four defects on the first run (V6.5.0)
🟢 `fixed` · 7/10

**Problem:** assigning a Python fee model to Lean's `FeeModel` property charged $0 in every fill, flattering a run by about 250 bps a year. The engine assumed a 50 bps Coinbase tier Lean does not have, marked crypto and forex a day ahead of Lean's daily sample, and wrote to a pandas 3 read-only array. **Fix:** `SetFeeModel`, which wraps the Python object; the schedule read from Lean's own fills (30, 25, then 80 bps from 2019-10-08); crypto and forex marks follow the bar that ended as the label began. **Verification:** BT13 fees $5,347.47 in Lean against $5,347.65 in the engine, 5,306 fills each; `tests/test_target_weights_engine.py`.

### 274. The arbitrage detector called fair prices arbitrage, in either direction (V6.5.0)
🟢 `fixed` · 6/10 (default off, nothing traded on it)

**Problem:** on its first real chain it flagged all six structures. It compared `abs(cost - fair)`, so a short box's credit always read as a mispricing of twice its notional; it used mids, not the prices one could trade; and its docstring had the conversion's direction reversed. **Fix:** `detect_executable_edge`: a one-sided edge at bid and ask, per structure, with the conversion's sign corrected. **Verification:** parity-priced chains fire nothing, rich calls fire only the conversion, cheap calls only the reverse, a wider spread than the mispricing fires neither (`tests/test_options_arbitrage_detector.py`). On the AAPL sample all six are now silent, the last once dividends were netted in V6.6.0 (#60).

### 275. A short iron condor was built as an ordinary iron condor (V6.5.0)
🟢 `fixed` · 6/10 (default off)

**Problem:** the shared selector always placed the role named `short_*` on the inner strikes. A short iron condor has its shorts on the outside, so it passed strikes out of order; Lean's factory raised, on the first time it was ever called. **Fix:** the inner legs are the registry's anchors, and the short iron condor's anchors are now its long legs. **Verification:** `test_both_iron_condors_pass_lean_ascending_strikes` asserts ascending strikes for both; the smoke run reports the structure.

### 276. `except Exception` in `main.py` never caught a Python error (V6.5.0)
🟢 `fixed` · 9/10 (every fail-safe block of the live path)

**Problem:** Lean's `from AlgorithmImports import *` exports .NET's `System.Exception` over the builtin. `System.Exception` is a subclass of Python's `Exception`, so about 40 `except Exception` blocks caught .NET errors only, and any Python error crashed the algorithm instead of degrading (rule 3). Pinned runs raised none, which hid it; `main.py` with an option asset crashed at initialization through a `try` written to survive exactly that. **Fix:** `from builtins import Exception` after the star import, beside rule 10's `time` workaround. The builtin catches both kinds. **Verification:** `scripts/lean_smoke/exception_scope.py` in real Lean: `Exception` is `<class 'System.Exception'>`, an `AttributeError` escapes it, and the builtin catches a Python error, a .NET binding error and a raised `System.ArgumentException`. `test_except_exception_in_main_catches_python_errors` pins it; BT12 reruns on the fixed code.

### 277. The alpha test compared crypto a day ahead of the strategy, booking its beta as alpha (V6.5.0)
🟢 `fixed` · 8/10

**Problem:** `benchmark_daily_returns` dated BTC on its bar's own date, but a bar dated D ends after the equity close of D, so a run's sample of D holds the bar before it. The regression saw BTC a day early and found almost no beta: a long-only crypto sleeve showed beta 0.012, alpha 5.7%/yr, t 2.76. **Fix:** crypto and forex benchmarks follow the sample's timeline. The same sleeve is now beta 0.075, alpha 1.3%/yr, t 0.83; weekly returns, which no one-day shift can affect, agree. BT11's verdict does not change (t -0.14 against -0.07). **Verification:** `test_crypto_benchmark_is_on_the_timeline_of_a_runs_daily_sample`.

### 278. A velocity lock pre-registered by the plan halted every run within months (V6.5.0)
🟢 `fixed` by a recorded amendment · 8/10 (it would have shipped a result that was mostly T-bills)

**Problem:** the plan set a sticky drawdown-velocity lock of 3 x 7% / sqrt(252) = 1.32% per bar. One ordinary bad crypto day trips it. The first R-LEAN19 pool stopped trading by 2024-03-06 at the latest, and its winner's +0.655 Lean Sharpe was 8 months of a crypto rally followed by T-bills. **Fix:** `ml/evaluation/v650/rules_amendment_1.json`, recorded in the vault before any rerun: the velocity trigger is off on this path, as it was in selection; the owner's 15% drawdown stays the sticky stop. No acceptance bar changed. **Verification:** 18 of 18 weight files hash the same in the rerun, so nothing was reselected, and the winner now trades to the end of its file. The first pool is kept as `r_lean19_locked.json`, so its windows are disclosed as seen.

### 279. V6.5.0's verdict: no verified edge; a crypto trend sleeve ships as improved, not verified
🔴 `closed` for R-EDGE1; the shipped sleeve is 🟡 until the forward check and a venue (#192), and it failed on never-read coins (#301) · n/a (phase result)

**Problem:** the owner's target: Lean Sharpe >= 1 and a verified edge. 46 pre-registered candidates: 20 rule sleeves, 2 positioning sleeves, 12 walk-forward model books, 4 new-architecture rankers (set transformer, gradient boosting), 2 combinations, 6 gate ablations. **Fix:** only two sleeves passed selection (`t3_crypto_trend_blend`, `t3_trend_blend`). PBO over the 38 selection trials is 0.53, above the 0.5 limit, which ended verification: R-EDGE1 cannot be awarded, and E4 and E5 were not read, so `data_pre2013/` stays unread for the owner to spend. By R-LEAN19, `t3_crypto_trend_blend` installs (`config.json` sha `38a24ffd…`; pin `backtests/2026-11-04_18-10-49`, the median of 5 phases). **Verification:** Lean Sharpe 0.63 (0.51-0.77) against -0.20; strategy Sharpe 0.72 against 0.27; vol 7.3%, drawdown 7.8%.

### 280. SEC EDGAR refuses a client that names no contact (V6.5.0)
🟢 `fixed` · 2/10

**Problem:** the two earnings-surprise trials need `companyfacts`, and SEC returned HTTP 403 to a generic client name; it asks for a contact address. No personal address is sent without the owner's say. **Fix:** with the owner's approval (2026-11-05), `AQ_SEC_CONTACT` supplies the address for one run, so it never enters the repository. `TICKER_ALIASES` maps the universe's `FB` to SEC's `META`. **Verification:** 2,805 quarters for 47 tickers in `data/reference/edgar_eps.csv` (no `@` in the file); `tests/test_alt_data_v650.py`.

### 281. Earnings-surprise signal: wrong comparison quarter, and splits read as misses (V6.5.0)
🟢 `fixed` · 6/10

**Problem:** the signal compared "four rows back", but most companies report no standalone Q4, so 53.6% of rows compared a quarter 15-18 months earlier. EPS was also unadjusted, so a split read as a large miss (AAPL -5.64 after 2020). Those trials still passed R-SLEEVE2 and both placebos at Sharpe 0.55 and 0.65. **Fix:** match the quarter ending 350-380 days earlier, divide each first filing by the splits after its filing date (`split_adjusted_eps`, `data/reference/equity_splits.csv`), and use only rows filed by that date. Amendment 3 closed the old trials before the new score; a missing Q4 gives no signal rather than a derived one. **Verification:** corrected Sharpe 0.18 and 0.17 against the 0.50 needed, so nothing reached Lean; a placebo pass did not protect against a defective signal. `ml/evaluation/v650/amendment3_eps.json`, `tests/test_alt_data_v650.py`.

### 282. A new DinD Codespace's Docker daemon failed to restart on its data-root move (V6.5.0)
🟢 `fixed` · 3/10

**Problem:** `dockerd` refused to start because `/var/run/docker.pid` named a live process after the old daemon was killed, so a whole batch failed in setup. **Fix:** `scripts/codespace_lean_dind.sh` waits up to 30 s for the old daemon to exit and removes the stale pid file before starting the new one. **Verification:** the same Codespace then ran all 21 pre-2013 runs; `tests/test_codespace_lean_scripts.py`.

### 283. The alpha tools read only `data/`, and on any other root booked T-bill carry as alpha (V6.6.0)
🟢 `fixed` · 8/10

**Problem:** `closes_for_universe` and `--alpha-proof` read `data/` alone, so a run on another root got empty closes, and `v650_lean.strategy_series` fell back to NAV with the sweep in it. BTC's NaNs before its first bar dropped every earlier row from the regression, so a 15.8-year window couldn't be reached, and a benchmark missing from a config vanished silently. **Fix:** `data_dir` on those functions and `aq evaluate --data-dir`; BTC's return is 0 before its first bar; `benchmark_daily_returns(required=True)` raises on a missing benchmark. **Verification:** `tests/test_v660_fixes.py`, on a fixture root.

### 284. A long book's Sharpe was raw, not excess, and session rows were annualised at sqrt(365) (V6.6.0)
🟢 `fixed` · 8/10

**Problem:** Ex-sweep returns pay nothing for the cash a long book ties up, so selection and placebos scored raw returns. Before crypto's first bar a panel has no weekend rows, and a fixed sqrt(365) inflated those Sharpes about 1.2 times. **Fix:** The engine adds `strategy_excess` (strategy less net capital x rf), which `score_sleeve` and `placebo_sharpes` use; `strategy` stays for comparison with Lean. `annual_sharpe(sessions=)` compounds to sessions at 252; crypto-only stays calendar. V6.5.0's sleeves rescored in `ml/evaluation/v660/v650_rescore.json`. **Verification:** `test_strategy_excess_*`, `test_session_sharpe_is_the_same_with_or_without_weekend_rows`.

### 285. The fresh period counted calendar rows, and a week of it could fail a clause (V6.6.0)
🟢 `fixed` · 5/10

**Problem:** `forward_judgeable` counted calendar points, so "60 sessions" came at about 41, and any n of 5-10 could read as "fresh-period alpha <= 0". **Fix:** One bar for both checks, `FORWARD_MIN_SESSIONS = 60`, counted in equity sessions. An all-session series annualises at 252 (`measured_annualization`). **Verification:** `test_fresh_sessions_ignore_weekend_rows`, `test_a_short_fresh_period_fails_no_clause`.

### 286. The deflated Sharpe could count 50 trials twice, and read a variance from no window (V6.6.0)
🟢 `fixed` · 7/10

**Problem:** Passing today's registry to `deflation_inputs` gave N = 178, since the registry already holds V6.5.0's ledger; `--alpha-proof` also read a variance mixing windows and annualisations, against its docstring. **Fix:** `legacy_trials` drops ledger phases; each phase labels its own window (`v660_selection`); `period_report` takes the inputs. **Verification:** `test_deflation_inputs_on_todays_files_count_128_trials`: N is 128.

### 287. Precomputed score tables and the research carry read a bar too new (V6.6.0)
🟢 `fixed` · 4/10 (no trial it touched survived)

**Problem:** A crypto or forex score dated D reads a bar closing after D's decision, which `test_no_lookahead` can't see inside a table; USD carry in a signal read the same-day rate. **Fix:** `align_score_table` shifts late classes a row; `build_context`'s signal table reads the previous session's rate. The model's feature is unchanged: it would break the schema. **Verification:** `test_align_score_table_*`.

### 288. Training eligibility read the future, and a pooled rank outran its purge (V6.6.0)
🟢 `fixed` · 5/10

**Problem:** `training_eligible` required backtest rows, dropping a name that later died from earlier training. 20 crypto bars are 20 days against about 28 for equities, so a kept crypto row could rank on equity returns past the boundary. **Fix:** New default-off keys: `asset_quality.eligibility_ignores_backtest_rows`, `windows.purge_label_calendar_days`. The wide trainer uses neither clause. No retrain on this path. **Verification:** `test_calendar_purge_catches_a_crypto_row_the_row_count_keeps`.

### 289. A held name whose bars stopped never exited (V6.6.0)
🟢 `fixed` · 8/10

**Problem:** The engine discarded an open with no price, crypto stayed pending forever, and the position held at zero return: a delisted name read as a flat one, in a universe full of them. **Fix:** `target_weights.no_bar_exit` (default off, on in V6.6.0's runs): after 2 missed bars the name closes at its last close less a haircut (5% equity, 20% crypto), in the engine and `main.py`, reading only bars already missing. Research panels also blank a name after 5 rows with no bar. **Verification:** `test_engine_closes_a_dead_name_*`, `test_main_closes_a_name_whose_bars_stopped_*`; proved in Lean by BT25 and BT27.

### 290. On the target path a kill-switch trip froze the book open in paper and live (V6.6.0)
🟢 `fixed` · 9/10

**Problem:** A lock turns order permission off, and `_target_weights_tick` returned on that before its liquidation: a backtest closed the book, and paper or live would have held it through the very event the lock was for. **Fix:** `resolve_risk_exit_permission` (the lock isn't consulted, observation still places nothing), modelled in `formal/` with `permit_implies_risk_exit`; the tick liquidates first. **Verification:** `test_a_tripped_target_book_closes_in_every_mode_that_can_place_orders`; `tests/test_formal_differential_order_gate.py`.

### 291. A live run could never read a new row (V6.6.0)
🟢 `fixed` · 8/10

**Problem:** The file loaded once at startup, and row D is written after D's close while the tick for D had already looked it up, so every row was missed and the book silently held. **Fix:** `target_weights.live_reload` (default off): a pre-open event re-reads the file against its `.sha256` sidecar, which `append_row` writes, and applies the newest unapplied row. Backtests keep the exact-date lookup. Live-only by necessity: `architecture.md` parity table. **Verification:** `test_premarket_tick_*`, `test_next_unapplied_row_*`. Real scheduling needs IB, so this stays unproved in a live feed.

### 292. A rule sleeve would have tripped the kill switch on a model's age (V6.6.0)
🟢 `fixed` · 6/10

**Problem:** `max_model_age_days` applied on the target path, so a sleeve using no model would hit a sticky lock around 2027-04-10. **Fix:** Model age is None unless `target_weights.uses_model`. **Verification:** `test_model_age_is_skipped_on_a_target_run_with_no_model`.

### 293. A non-sticky lock re-locked itself every session in paper and live (V6.6.0)
🟢 `fixed` · 6/10

**Problem:** While locked, risk value read the simulated portfolio, which this path never updates: it stayed at the starting cash, and the rollover set the session start there, so any value below it re-tripped daily. **Fix:** The target path reads the real portfolio wherever orders could exist. **Verification:** `test_risk_value_reads_the_real_book_while_locked_on_the_target_path`.

### 294. A lock let pending crypto buys go out, and exited crypto at a 16-hour-old price (V6.6.0)
🟢 `fixed` · 5/10

**Problem:** After a lock at midnight the pending buys were still sent, and lock exits on the equity tick filled crypto at its stale price, unlike the engine. **Fix:** `_liquidate_target_positions` replaces the pending set with exits only, which wait for each coin's own next bar. **Verification:** `test_a_lock_drops_a_pending_crypto_buy`, `test_a_lock_sends_crypto_exits_on_its_next_bar_not_the_equity_tick`; BT26.

### 295. The daily weights script hid a broken feed behind "not a rebalance day" (V6.6.0)
🟢 `fixed` · 6/10

**Problem:** A date with no data printed that and exited 0, and stale crypto was forward-filled silently, so a broken feed produced a quiet wrong decision. **Fix:** `data_problems` exits non-zero on a missing date or a class too old (equity 5 days, crypto 2). **Verification:** `test_a_missing_date_is_a_problem_not_a_quiet_no_op`, `test_stale_crypto_is_a_problem_fresh_data_is_not`.

### 296. The forward check measured frozen weights, not the signal on new prices (V6.6.0)
🟢 `fixed` · 6/10

**Problem:** RUNBOOK's rerun used the pinned file, which ends 2026-10-28, so its fresh period held old decisions. **Fix:** `scripts/extend_frozen_weights.py` writes a copy with new rows by the frozen rule, never rewriting a frozen row, and RUNBOOK uses it. The forward ledger (#299) is the better record. **Verification:** `test_extended_rows_never_rewrite_a_frozen_row`.

### 297. A dropped connection read as "no data", and was cached (V6.6.0)
🟢 `fixed` · 8/10

**Problem:** A WLAN drop during the first insider download made every later quarter return nothing and be cached as empty, so a rerun would have kept 2016-2026 blank; FINRA's whole series came back with 0 days and would have left its trial with an empty book. **Fix:** `data_pipeline/net_retry.py`: only a status the server chose means absent; anything else waits out the outage (up to an hour), then stops the run to resume later. Empty quarters and months are never cached; the crypto builder uses it too and asks the archive which months exist. **Verification:** `tests/test_net_retry.py`; the rerun read 41 more insider quarters (694,447 trades) and 2,075 short-volume days.

### 298. The vault client failed a retry of an unchanged candidate, and could sweep a failed gate's files into a commit (V6.6.0)
🟢 `fixed` · 6/10

**Problem:** Exit 11 (`nothing_to_commit`) read as failure, so a retry after a killed run could never succeed; `av commit` takes all that is staged, so a failed gate's leftovers could land under the next label; a `repo_path` outside the candidate raised `ValueError`. **Fix:** Exit 11 is success with the existing hash; `staged_leftovers` refuses first; `_path_in_vault` fails the event cleanly. **Verification:** `tests/test_vault_client.py`, `tests/test_vault_record.py`, `test_a_candidate_outside_the_vault_repo_fails_the_event_cleanly`.

### 299. A forward record nothing could backfill didn't exist (V6.6.0)
🟡 `partial` · n/a (new)

**Problem:** Every result so far could be rerun until it looked good, so none could show a decision came before its return, and the 60-session forward check depends on someone rerunning it. **Fix:** `.github/workflows/forward-ledger.yml` appends one hash-chained row a session to the orphan branch `forward-ledger` by the frozen rule in `ml/forward/candidates.json`; missing data is a `no_data` row, never a gap. `aq evaluate --forward-ledger` verifies the chain and judges at 60 and 252 sessions, which is why this stays partial. **Verification:** `tests/test_forward_ledger.py`, including tampered rows. The first real dispatch wrote nothing and found why: Yahoo leaves the newest bar's closes empty for hours, which would have silently skipped every evening run, so its quote's last price of that same day now stands in.

### 300. V6.6.0's verdict: not verified, stopped at the first gate on evidence nothing had read
🔴 `closed` for R-EDGE2; the equity holdouts stay unread for a later phase · n/a (phase result)

**Problem:** The owner's objective: prove or refute alpha on names no rule had read. 28 pre-registered trials on S&P 500 point-in-time members and 701 Binance coins, with information new to this project (fundamentals, insider trades, short volume, funding rates), rules hashed before any score (`rules.json` `8e6aecba…`, vault `2852edb9`). **Fix:** Zero survived R-SLEEVE3, so E1-E6b were not read, nothing was frozen and nothing was installed. Closest: w04 (accruals) 0.45 net against 0.50, IC t 1.97 against 2.0, second half 0.33 against 0.40, one near miss of 28 and not rerun; e3 (volatility-managed SPY) failed its placebos (p 0.17 and 0.18); PBO 0.38 did not end it. **Verification:** `ml/evaluation/v660/r_edge2.json`, `verdict_table.json`, `selection_gate.json`, `trial_ledger.jsonl` (N 156 after round 1, 164 after round 2, #310). The wide path can see an edge: an oracle scores Sharpe 19.2, its reversal -8.3, random ranks -0.88 from costs alone (`sanity_wide_path.json`). `rules` precedes `selection` in the vault's commit order.

### 301. The installed crypto rule failed on coins it had never read (V6.6.0)
🟡 `partial` (reported by rule R-CRYPTO1; the sleeve stays installed by the binding fail rule, and whether to keep trading it is the owner's call) · 8/10

**Problem:** `t3_crypto_trend_blend` was picked on 12 surviving coins and had never met a delisted one. On 2018-01..2026-11 side-B liquid coins, delisted included, it scores Sharpe -0.06 (2018-2020 0.25, 2021-2023 -0.03, 2024 on -0.45), alpha -3.4%/yr at t -1.94, drawdown 21.6%. **Fix:** None by design: a frozen rule isn't refit on its test. On 2018-2022 the same rule scores 0.33 on the 12 chosen coins (raw basis), 0.13 on side-A liquid coins and -0.05 on side B, so V6.5.0's 0.96 was earned mostly before 2018 and coin choice added a smaller part. Delisted coins aren't the reason: survivors alone score -0.01. **Verification:** `ml/evaluation/v660/r_crypto1.json`; the README's limitations state it beside the sleeve's label.

### 302. Two of V6.5.0's selection passes didn't survive corrected Sharpes (V6.6.0)
🟢 `fixed` (report only: R-EDGE1 stays closed, the install doesn't change) · 4/10

**Problem:** Rescored on excess returns and session annualisation (#284), `t3_trend_blend`'s first half falls from 0.428 to 0.357 and `t3_vix_scaled`'s pooled from 0.587 to 0.484, both under their bars. **Fix:** Recorded beside the frozen numbers; the installed sleeve moves only from 0.96 to 0.94. **Verification:** `ml/evaluation/v660/v650_rescore.json`: 38 rescored, 2 changed a clause.

### 303. R-VEL1: velocity stays off, as a decision (V6.6.0, closes #278)
🟢 `fixed` · 5/10

**Problem:** #278 left "a live deployment needs its own velocity decision" open, and nothing stopped paper trading without one. **Fix:** By rule on the installed sleeve: k=5 locks on 2020-03-13 and leaves 44% of sessions trading; k=8 never fires, so it cuts nothing. Neither qualifies, so `target_weights.velocity_decision` records "off"; `aq paper-readiness` prints it and fails if a target-weights config has none. **Verification:** `ml/evaluation/v660/r_vel1.json`; `evaluate_velocity_decision` tests in `tests/test_v660_fixes.py`.

### 304. Lean's CLI silently replaced a data root's symbol table, through a hard link (V6.6.0)
🟢 `fixed` · 7/10

**Problem:** The CLI refreshes `symbol-properties-database.csv` from GitHub about daily, writing in place. On a parallel run that wrote through the hard link into the shared master, so the rows a wide root adds were gone and BT27 skipped 6 coins with only a debug line: correlation 0.80 to the engine, half its fees. **Fix:** `scripts/codespace_lean_parallel.sh` stamps `file-database-last-update` in a run's own `lean.json` whenever its root isn't `data/`. **Verification:** `tests/test_codespace_lean_scripts.py`; the rerun skipped none.

### 305. A token swap read as a 1,295x return inside one pair (V6.6.0)
🟢 `fixed` (found after selection and R-CRYPTO1 were read, so it rescues nothing) · 8/10

**Problem:** 8 of 701 Binance pairs carry a break of at least 10x across a gap: COCOS 1,295x and DREP 108x upward, LUNA's relaunch upward, and BNX, QUICK, SUN, VEN and VIDT downward. Lean rode COCOS to +$13.5M in BT27; the engine exits at the gap, but momentum and volatility signals still read across it. **Fix:** `truncate_at_swap` ends a pair at such a gap, in the builder and by `--cut-swaps` on the existing root. A collapse without a gap (LUNA on 2022-05-11) is a real loss and stays. **Verification:** `tests/test_binance_archive.py`. With those coins out, every c trial's first half is unchanged (each still under 0.40) and pooled moves at most 0.07; R-CRYPTO1 goes from -0.06 to -0.07, so no clause changes (`crypto_breaks_effect.json`). BT27 then passes R-INSTR2.

### 306. On Lean the no-bar exit never saw a crypto feed stop, and would have charged again every day (V6.6.0)
🟢 `fixed` · 8/10

**Problem:** Lean fills a stopped crypto feed forward, so the copy in the slice read as a bar and the exit never fired, unlike the engine (BT25's equity case had passed). Once it fired, Lean holds a market order open until a later bar, which a dead name never has, so the position stayed and each tick charged the haircut again. **Fix:** `_has_real_bar` ignores `IsFillForward`; `_target_exited_without_bars` makes the exit once-only until a real bar returns. **Verification:** `test_a_fill_forward_copy_is_not_a_bar_for_the_no_bar_exit`; BT27 with a dead coin held across its last bar: correlation 0.99946, gap 0.54 bps, fees within 0.02%, one exit in each. BT24 equals the pin, 1,012 of 1,012 fills.

### 307. `main.py`'s multi-leg limit order had never run, and crashed on its first use (V6.6.0, closes #38 for Lean)
🟢 `fixed` · 8/10 (options are off, no option asset is configured)

**Problem:** Forcing the signal showed `ComboLimitOrder(strategy, ...)` has no such overload, an unhandled error in `on_data`. Its limit was also the underlying's price rather than the combo's net, and a vega budget could buy $120k of premium on a $100k account, which Lean rejected whole. **Fix:** `_combo_legs_at_net_mid` sends legs at their net mid (no two-sided quote falls back to the market order); `resolve_combo_limit_price` offsets on either side of zero; `_affordable_contracts` caps premium at 90% of equity in all three vega sizers. **Verification:** `backtests/smoke_main_option_order`: the limit order is accepted and later times out, the market branch fills +1 at $5.05 and -1 at $3.10; `tests/test_main_wiring.py`, `test_order_gate.py`, `test_options_strategy.py`.

### 308. The Docker worker could never pass its own vault preflight (V6.6.0, closes #271)
🟢 `fixed` · 7/10

**Problem:** `.av` is dockerignored, so in the container `vault_preflight` returned `not_an_av_repo` and every retraining cycle would stop. Separately, on a DinD Codespace `/tmp`'s default ACL gave containers a `/` no non-root user could enter, so Postgres couldn't start. **Fix:** The worker keeps its repo on volume `retraining-vault` and inits it once; `codespace_lean_dind.sh` strips the default ACL from Docker's data root. **Verification:** Image `0268ededb204` built from the final tree, never pushed: `/api/assets-status` 200, `av 1.7.0`, preflight `ready`, repo survives a restart (`ml/evaluation/v660/engine_image.txt`); `test_the_docker_worker_has_a_vault_repo_that_outlives_its_container`.

### 309. The engine's turnover divided by the starting NAV (V6.6.0)
🟢 `fixed` · 2/10

**Problem:** A compounding path read as high turnover (an oracle showed 12,124x a year), and a shrinking one as low. It's a reported number that no gate reads. **Fix:** Traded dollars over mean NAV. Selection's recorded turnovers predate this; those paths' NAV stays near flat. **Verification:** `test_turnover_is_a_share_of_the_nav_the_book_actually_had`.

### 310. Round 2 of the search: eight more trials on cell S, none survived (V6.6.0 addendum)
🔴 `closed` (R-SLEEVE3 unchanged; nothing installed or frozen) · n/a (research)

**Problem:** The owner asked for research to improve the model before committing. Round 1 left eight sleeves with a positive no-cost Sharpe that costs removed, so `rules_r2.json` (hash `197048b7…`, in the vault before any score) fixed eight trials: a wider book (r01), two fixed composites of the low-turnover signals (r02, r03) and a no-trade band on five (r04-r08). All read only cell S on side-A names; the holdouts V1-V3, P and CV stayed closed. **Fix:** Nothing qualified. r03 came closest (Sharpe 0.57; 0.76 and 0.21 by half; IC t 1.97), then r02 (0.45; 0.57, 0.33; IC t 1.69) and r01 (0.38). The bands didn't rescue reversal: w14 stays at -1.89 (r04) and -0.89 (r05), and the band sleeves on w11, w09 and w10 net 0.30, 0.17 and 0.25. PBO over round 1's 22 columns plus these 8 is 0.31. The deflated Sharpe's N is now 164 (`trial_ledger.jsonl`). **Verification:** `ml/evaluation/v660/selection_scores_r2.json`, `selection_gate_r2.json`, `selection_pbo_r2.json`; `tests/test_v660_round2.py`. Report only, never gating (`report_only_r2.json`): accruals (w04) has a positive rank IC in all 8 years (mean +0.015, strongest in the most liquid third, +0.028) and is the only signal that keeps a positive Sharpe at twice the costs (0.46 to 0.29) or on a $25k account (0.39); the models' IC is negative in 7 of 8 years for m2 and 5 of 8 for m4.

### 311. The installed sleeve's universe holds a coin Coinbase has delisted (V6.6.0)
🟢 `fixed` (the owner decided on 2026-11-07; V6.6.4) · 6/10

**Problem:** Checking venues for #192, Coinbase's product API returns EOS-USD with status `delisted` and trading disabled, and its public candles for it end 2025-12-10; Kraken has no EOS pair. `config.json` and `ml/forward/candidates.json` still list EOSUSD, with prices to 2026-11-02 from a feed that is not Coinbase's. A Coinbase deployment could never fill an EOS order, and the forward ledger marks it on Coinbase candles that stopped. **Fix:** None applied. Without EOS the installed rule scores 0.99 against 0.95 over 2014-12..2026-11, and 0.66 against 0.65 on the Lean window (`ib_subset.json`, report only), so the sleeve doesn't lean on it. The frozen weight file last holds EOS on 2025-09-03. **Verification:** `ml/evaluation/v660/ib_subset.json`, `venue_data_coverage.json`. **V6.6.4:** the forward definition is `t3_crypto_trend_blend_x_eos` (a new `definition_sha256`, so the old row is never pooled; g0001 took it with a lifecycle row), and `config.json` lists 103 assets. Today's code first rebuilt the installed weight file byte for byte (sha `57240be0…`), so the only difference in the new pin is the coin. The rule was re-run over the same windows on a DinD Codespace, five rebalance phases and the long window, and R-LEAN19's median phase installed: pin `2026-11-07_17-54-01`, Lean Sharpe 0.651 (0.633 with EOS), strategy Sharpe median 0.737 (0.720), drawdown 7.8% in both; the long run `2026-11-07_17-56-48` has Sharpe 0.862 and drawdown 14.0%. `ml/evaluation/v664/eos_repin.json`, `eos_reproduce.json`; `scripts/v664_eos_repin.py`. V6.5.0's code-digest freeze guard fails by design now (five files changed since), so the re-pin uses the byte-for-byte reproduction instead. **V6.6.4 audits of the re-pin (`2026-11-07_17-54-01`):** 987 fills with crypto filling a median 10.0 bps from the open (p99 15.3 bps) and equity 1.0 bp, the dataset open equal to Lean's zip open on every traded date, no overlapping same-symbol orders and no limit order open past 4 sessions, a clean engine teardown, and 0 of 171 dates with a divergent feature for BTCUSD (`--audit-fills`, `--audit-backtest`, `--reconcile-features`). A paper-check of a phase run against the pin sits inside all bands (167 rebalances).

### 312. What Interactive Brokers, TradeStation and public sources can give the crypto sleeve (V6.6.0, adds to #192)
🟢 `fixed` (the question was answered; testing an account belongs to #192) · 5/10

**Problem:** The owner asked whether IB or TradeStation can supply the sleeve's crypto data and trading. **Fix:** IB can, with limits: its API serves crypto (`CRYPTO` / `PAXOS`) with historical bars and no data subscription, but Lean's IB brokerage can't route it, 8 of the 12 coins are on its reported lists, and the 2026 additions are reported as not available to IB Ireland clients. TradeStation's API documents no crypto at all, and its crypto is a separate US product. Without an account the sleeve's history comes from public sources: Binance's archive (everything since listing), Coinbase (300 daily bars a call) and Kraken (the newest 720). **Verification:** `ml/evaluation/v660/venue_study.json` (`research_2026_11_06`), `venue_data_coverage.json`, `scripts/v660_venue_coverage.py`. Installed sleeve, report only: on the 8 IB coins and IB's fee schedule Sharpe is 1.08 over 2014-12..2026-11 and 0.72 over 2023-07..2026-11, against 0.95 and 0.65 on all 12 at Coinbase's; from 2025-07 on every variant is at or below zero, so the decline in #301 does not depend on the venue. **V6.6.4:** closed as answered. `ml/evaluation/v660/venue_study.json` now carries a note that Coinbase stands as the assumed venue (the file's earlier "Kraken chosen" was superseded by the owner's confirmation of 2026-11-07).

### 313. The forward ledger credits a crypto decision one bar the book never earns (V6.6.1)
🟡 `partial` (the older chain is kept as it is; the new file is right, and runs from the owner's first push) · 7/10

**Problem:** A decision at session D's close reads the mark from D's midnight, and its order fills at bar D's close. `scripts/forward_ledger.py` lets those weights earn from that same midnight, one bar too early. Replayed over 2023-07..2026-11, a series at that timing has a daily correlation of 0.04 with the offline engine, so `forward/ledger.jsonl` does not track the book it records, and its 60-session judgement would not read the book's returns. **Fix:** `forward/generations.jsonl` (`evaluation/generation_ledger.py`) lags each class to its real fill. The old chain is untouched, since a change there would start a new record. Compare generations only inside the new file. **Verification:** `ml/evaluation/v661/replay_check.json`: daily correlation 0.993 with the engine over 838 sessions, 5.1% a year against 5.5%; `tests/test_generation_ledger.py`. The new workflow has not run on GitHub: it starts with the owner's push.

### 314. Why the models behaved like price models: their fundamentals were nearly empty when training began (V6.6.1)
🔴 `closed` (no model track survives; see #315) · n/a (research)

**Problem:** V6.6.0's m2-m4 trained from 2004 with `rank_inputs` filling missing values with the middle of their group. Fundamental coverage of member rows is 1.4% in 2009, 51% in 2010 and 77% in 2011, so in their early windows those inputs were near-constant, and the models were close to price models whatever their feature list said. **Fix:** `--train-start` and `--feature-set fundamental` let a model read only years holding its inputs. This was the audit's one actionable finding, and it did not rescue the models. **Verification:** `ml/evaluation/v661/model_audit.json`: 18 fixed group x horizon looks on cell S, each counted in N. No group's IC is meaningful at the 21-session horizon the book trades (best |non-overlap t| 1.13).

### 315. Round 3: breadth, residuals, walk-forward models and quarterly accruals, none survived (V6.6.1)
🔴 `closed`; the equity holdouts stay unread · n/a (phase result)

**Problem:** The owner's first objective: more, verified alpha. `round3.json` (hash `34a4c3ac…`, vault `96c6171e`, before any score) fixed ten trials on cell S under the unchanged R-SLEEVE3 and PBO: pooled books that give a sector gross by its breadth, a composite less known exposures, a slower book, Fama-MacBeth slopes held to published signs, a monotone tree, the installed network on the fundamentals era, and quarterly accruals from a new EDGAR download. **Fix:** Zero survived, so nothing was frozen, the holdouts stayed unread and nothing was installed. Sharpe (first half, second half), IC t: k04 0.58 (0.84, 0.29), 1.97; k02 0.55 (0.76, 0.32), 1.97; k03 0.55 (0.91, 0.13), 2.36; k01 0.47 (0.40, 0.61), 1.98; k09 0.45 (0.49, 0.36), 2.60; k10 0.14; k06 -0.46; k08 -0.57; k05 -0.58. k05's mean IC of -0.003 closed the model track on evidence, so k07 didn't run, and it still counts. Best alpha t 1.93 (k03). PBO 0.36 did not end it. N is 192. **Verification:** `ml/evaluation/v661/r_round3.json`, `selection_gate_round3.json`, `selection_pbo_round3.json`, `sanity_pooled.json`: the pooled path can see an edge (oracle 20.5, reversed -8.6, random -1.5 from costs alone). `tests/test_research_round.py` recomputes round 2's stored gate and PBO exactly.

### 316. A second freeze could have reopened a held-out cell (V6.6.1)
🟢 `fixed` · 6/10

**Problem:** `write_freeze` refuses only its own path, so a second freeze under another name would have opened V1-V3 again, and nothing recorded a read. **Fix:** `record_holdout_read` writes a once-only ledger, before the read, at `ml/generations/holdout_ledger.jsonl` (tracked, since `ml/evaluation/` is not), and `stage_freeze` refuses once any holdout is spent. Later candidates reach shadow through 252 forward sessions instead. **Verification:** `tests/test_research_round.py`.

### 317. `forward_ledger.decide` drops `top_k` and any score table (V6.6.1)
🟢 `fixed` for new records (no installed rule uses either) · 5/10

**Problem:** It passes empty extras and no `top_k`, so a cross-sectional or model rule would fail, or silently become a different rule, on the forward record. **Fix:** `generation_ledger.decide_generation` passes both. For the installed rule it returns the same weights, so `forward_ledger.decide` stays as it is. **Verification:** `tests/test_generation_ledger.py`.

### 318. R-GLIDE1: no handover schedule keeps capital off a generation with no alpha (V6.6.1)
🔴 `closed` (fixed 252 by rule) · n/a (research)

**Problem:** Which policy should move capital between generations? R-GLIDE1 (`rules_glide1.json`, hashed first) ran the live allocator over 2,000 fixed-seed worlds where a new generation arrives yearly and has no alpha 50-80% of the time, and required at most 20% of time mostly on such a generation. **Fix:** None qualified, so the rule's fallback stands: a 252-session ladder. Equal weight came closest (regret 0.130, 36% of time on a zero-alpha generation); the ladders spend 51-55%, and instant switching 57%. Evidence helped little: holding a ramp on a watch signal made regret worse (0.18 against 0.15). So the schedule can't protect capital, and admission (R-ADMIT1) is what does. **Verification:** `ml/generations/glide_policy.json`; `tests/test_glide_calibration.py`. Replay on real vintages was not possible (`ml/versions` holds none), as the rule says.

### 319. Generations that share a book and hand over (V6.6.1)
🟡 `partial` (proved in Lean and on the ledger; a paper period waits for the broker keys) · n/a (new capability)

**Problem:** The owner wants several model generations live at once, sharing capital as an old one's alpha decays (70/30, 60/40, ... 0/100). The system had one active slot: `promote` copies a model over `ml/`. **Fix:** Weights blend upstream of the file the target-weights path already reads (`portfolio/generation_blend.py`), so `main.py` is untouched and Lean, the engine and the live path read one file. `evaluation/generation_registry.py` holds the owner's admission rule R-ADMIT1, `evaluation/alpha_decay.py` a CUSUM, `aq cycle` the verbs, `research-cycle.yml` the daily record. The first threshold of 8 alarmed on healthy returns; a test caught it, and 26 gives a median false alarm of about 1,040 sessions, at the price of about 380 to see a fall from Sharpe 1 to 0. **Verification:** R-BLEND1 passes (`ml/evaluation/v661/r_blend1.json`). BL1, a two-generation handover in Lean over 2015-01-02..2018-12-31 (`backtests/2026-11-06_16-52-44-1`), against the engine: daily correlation 0.99999, annual gap 0.004 bps, fees $2,656 against $2,656; it traded crypto in 2015-16, equities from 2016, and handed over fully by early 2017. **V6.6.4:** the live-mode plumbing (a start, outages and a restart under Lean's paper mode, the audit chain on a real Postgres) is proved without a broker; the paper period itself still needs the broker keys and 120 days.

### 320. Two Codespace pushes at once corrupted each other's archive (V6.6.1)
🟢 `fixed` · 5/10

**Problem:** `codespace_sync.ps1` built `push.tgz` in one shared folder, so a push to the training Codespace overwrote the archive a DinD upload was still reading: tar reported trailing garbage. **Fix:** One archive per Codespace. **Verification:** Re-run with both Codespaces up: both pushes verified.

### 321. Anyone can retrain, on any machine with the RAM (V6.6.1)
🟡 `partial` (every stage proved on a synthetic panel on this PC and on the Codespace; a real local retrain waits for a machine with the RAM) · n/a (new capability)

**Problem:** Training was documented as Codespace-only, and each phase hand-drove its session scripts. The owner gets a powerful laptop soon, and wants anyone able to retrain locally and automatically. **Fix:** `aq cycle retrain --host local|codespace`: the same resumable stages on both, a RAM preflight that refuses under 14 GB with the numbers, a `bootstrap_data` stage for a fresh checkout, `--smoke` to prove the plumbing anywhere, and `aq cycle schedule install` for a weekly retrain-if-due job, which refuses a smaller machine and was not installed on this PC. The Codespace host stops the Codespace however the run ends. **Verification:** `aq cycle retrain --host local` refuses this PC with its 3.9 GB; `--smoke` passes on it. `--host codespace --smoke` ran every stage on the real Codespace and stopped it. **V6.6.4:** `register` now writes the vintages it promises, the scores come back with `state.json`, the shell is looked up (`pwsh` or `powershell`) and its absence is said plainly, and the bootstrap refuses with a reason when `data_wide` and the SEC contact are both missing. The real `--procedure k06` run on the Codespace was attempted on 2026-11-08 at the owner's request and could not start: GitHub refused to start the Codespace (HTTP 402, a billing and usage limit), and a paid top-up is not something the agent does. It is unavailable until the monthly quota resets or the laptop arrives; k06 already failed (#315), so it would show plumbing only. (A first attempt also hung for minutes because `/workspaces/...` was rewritten into a Windows path when launched from Git Bash; run `aq cycle retrain` from PowerShell.)

### 322. The library covers the whole project (V6.6.1)
🟢 `fixed` · n/a (new capability)

**Problem:** `aether_quant` covered 11 modules. `moe`, `regime`, `retraining`, `notifications`, `experts` and `performance` weren't even in the wheel, and the trainers' split helpers could only be reached with torch loaded. **Fix:** 24 facade modules over every subsystem, with the helpers moved unchanged to `features/training_splits.py` and re-imported by the trainers. `main.py`, workers, `api_server` and fetchers stay out, on purpose (`aether_quant/README.md`). **Verification:** `scripts/wheel_smoke.py` from a built wheel outside the checkout: 0 import and 0 help failures across 27 subcommands, a real call into each module, every shipped package imported. Importing all 24 modules loads none of torch, sklearn, Redis, Postgres, fastapi or Lean.

### 323. A dynamic glide: three or more generations, smooth, with shares from each one's record (V6.6.1 addendum)
🟡 `partial` (proved in Lean; a paper period waits for the broker keys, and `policy.enabled` stays false) · n/a (new capability)

**Problem:** The owner asked for a smoother handover, for three or more generations at once while an old one is still somewhat profitable, for more stages in between, and for a dynamic calculation of each one's share. The ladder held one gainer and jumped 30% on entry. **Fix:** `dynamic_generation_shares`: a generation's score is its exponentially weighted Sharpe shrunk toward its claim at admission, its target is proportional to its score above a floor, up to four hold capital, and shares move a fixed fraction of the way to their targets each session, so nothing jumps. New stages `fading` and `winding_down` replace `decaying`: falling short of its claim isn't the end while a generation still earns. **Verification:** R-BLEND2 in Lean (`ml/evaluation/v661/r_blend2.json`): three generations under the adopted policy over 2015-01-02..2018-12-31, 94 blended rows with three holding capital. Against the engine: daily correlation 1.00000, annual gap 0.082 bps, fees $2,807 against $2,791. **V6.6.4:** the same live-mode plumbing result applies (see #228); the glide still waits for a paper period, and `policy.enabled` stays false.

### 324. The Lean proofs and the full verification now run on a Codespace (V6.6.1 addendum)
🟢 `fixed` · 3/10

**Problem:** The PC's low-memory guard stopped both the full `aq test` and the proof-case regeneration, so V6.6.1's first hand-over left the full suite unverified. **Fix:** `scripts/codespace_prove.sh` builds the proofs and regenerates their cases from Mathlib's cache. `scripts/codespace_verify.ps1` and `.sh` run every CI job on a Codespace against the working tree in a clean checkout, before a commit. **Verification:** The 11 older case files regenerated on Linux are identical in content to the committed ones. every CI job on a Codespace (Python 3.11) against the final tree, in a clean checkout of `origin/main` plus its changes (`scripts/codespace_verify.ps1`): the suite 4,751 passed, 34 skipped, 0 failed, coverage 85.75% against the 80% gate; all 15 `aq test` buckets; ruff 0.16.4; the guard tests; actionlint 1.7.7 with 0 errors in 4 files, the new workflow included; the web UI's `tsc`, oxlint, vitest and build; the CLI smoke; the wheel outside the checkout, 0 failures across 27 subcommands; the Python 3.10 byte-compile; the parity job; gitleaks, no leaks; pip-audit, no known vulnerabilities; hadolint; the test count at 4,785.

### 325. What only a run against the real tree could find: a hanging test driver and a push that dropped `tests/data` (V6.6.1 addendum)
🟢 `fixed` · 4/10

**Problem:** With a built `webui/dist` present, `tests/test_api_server.py`'s SPA tests hung forever on Python 3.11: the test's fake ASGI client answered `receive` at once every time, so Starlette's disconnect listener never yielded. CI has no `dist`, so they had only ever skipped there. Separately, `codespace_sync.ps1 -CodeOnly` excluded every folder named `data`, `tests/data` included, so the Codespace's API snapshot stayed stale. A first version of the verification's vault stage also passed with `av` off PATH, its real-CLI tests skipped. **Fix:** The client now delivers the request once and then stays connected. Windows tar's excludes are anchored with `^`. The vault stage fails if `av` is absent or a contract test skips. **Verification:** The suite in the tree holding the data, which stalled at 93% for 55 minutes, now finishes in about a minute with 0 failures.

### 326. `evaluation/lean_statistics.py` can't import on Python 3.10, which the package claims to support (V6.6.1 addendum)
🟢 `fixed` (V6.6.4) · 2/10

**Problem:** `from datetime import UTC` needs Python 3.11, while `requires-python` says `>=3.10`. CI's 3.10 job only byte-compiles, which can't see it. A stricter check found it during this phase's verification. **Fix:** None applied. Either `timezone.utc` there, or `requires-python >=3.11`, is the owner's call. **Verification:** `vermin -t=3.10-` names the one file among the first-party sources it read. **V6.6.4:** `evaluation/lean_statistics.py` reads `timezone.utc`, and CI's `python-compat` job now runs `vermin -t=3.10-` over the first-party sources as well as byte-compiling them (compiling cannot see a name that is new in 3.11). The old file fails that check and the new tree passes it; `tests/test_ci_workflows.py` pins the step, and `requires-python` stays `>=3.10`.

### 327. The docs had drifted from the code (V6.6.2)
🟢 `fixed` · 3/10

**Problem:** README claims and sub-readmes described the retired model book as the shipped system, named deleted scripts and config keys, and quoted counts that disagreed (a badge of 4,476 beside a count of 4,785). **Fix:** every living doc was rewritten against the code and condensed. **Verification:** `tests/test_docs_facts.py`, `tests/test_docs_links.py`.

### 328. Nothing stopped a quoted number or a reference going stale (V6.6.2)
🟢 `fixed` · 4/10

**Problem:** counts, windows and versions were hand-typed in many docs, and renamed paths and config keys rotted silently. **Fix:** `docs_facts.py` with `aq docs sync`, refreshed by a full `aq test`; `tests/test_docs_facts.py` fails on a stale fact and on a path, `phase_v2` key, `aq` command or problem number that no longer exists in a living doc. **Verification:** the same test found `phase_v2.crypto_graduates`, `scripts/forex_signal_research.py` and a dead `#75` on its first run.

### 329. The README's statistics mixed the shipped book with the retired one, and four numbers were wrong (V6.6.2)
🟢 `fixed` · 6/10

**Problem:** the Monte Carlo chart, walk-forward, offline and classification tables described a rank book that stopped trading at V6.5.0. The run history listed plumbing runs (one showing Sharpe 5.5). `backtest_audit.json` described a different run. The Lean Monte Carlo annualized a 365-day series at 252 (median Sharpe 0.98 for 1.18), and the deflated Sharpe's trial count was stale (124 for 173 in the registry, 192 in the ledgers). **Fix:** the README shows only the pinned run, with benchmarks and per-period alpha; the rest moved to `development/research_results.md`; the history lists only runs a rule judged; Monte Carlo reads the series' own calendar; `--lean-report` includes the alpha proof. **Verification:** `aq evaluate --lean-report --backtest-dir backtests/2026-11-04_18-10-49`, `scripts/readme_freshness.py`, and four repeat runs with identical orders.

### 330. The alpha regression compares a crypto book with SPY a session out of line (V6.6.2)
🟢 `fixed` (V6.6.4: reported beside the pre-registered figure, which is unchanged) · 2/10

**Problem:** `benchmark_daily_returns` aligns BTC to a run's daily samples but not SPY or AGG, so the strategy's correlation to SPY reads 0.05 as-is against 0.30 lagged one session (Lean's own figure is 0.29). **Fix:** none. Lagging the equity columns moves the pinned run's alpha t from 0.13 to 0.08, and R-ALPHA1 stays "not demonstrated". The README's benchmark table leaves correlation out for this reason. Changing it is the owner's call, because it alters a pre-registered measure. **Verification:** computed on the pinned run during this phase. **V6.6.4:** `benchmark_daily_returns(..., lag_equity=True)` reads SPY and AGG a session late, as the crypto column is, and each period of `alpha_proof_report` carries it as `alpha_session_aligned`, a key `r_alpha1` never reads (a test pins that). On the re-pinned run the full-window alpha t is 0.150 as pre-registered and 0.116 aligned; on the long run 0.954 and 0.779. R-ALPHA1 stays "not demonstrated" either way, and the README states the aligned figure under its table.

### 331. CI failed on V6.6.1 and V6.6.2: an example only ran where the package was installed (V6.6.3)
🟢 `fixed` · 4/10

**Problem:** both `python-tests` jobs failed on one test, `test_the_cycle_example_hands_over_and_takes_risk_off`, with `ModuleNotFoundError: No module named 'aether_quant'`. The test runs `examples/aether_quant_cycle.py` in a child process, which doesn't see pytest's `pythonpath`, and CI doesn't install the package. It passed on the dev PC and the Codespace because both have an editable install, so neither the local suite nor `codespace_verify.ps1` could catch it. **Fix:** the example inserts the repo root on `sys.path` like the quickstart, and a test requires that of every example. **Verification:** with the editable finder removed the old example fails with CI's exact error and the fixed one runs; the CI logs show this was the only failing test (1 failed, 4,781 passed on ubuntu).

### 332. A forward-ledger run that fired after midnight UTC recorded nothing, and the record lost a session (V6.6.4)
🟢 `fixed` · 7/10

**Problem:** the scheduled run of Friday 2026-11-06 fired 3 h 41 min late, at 02:11 UTC Saturday. Both ledger scripts took "today" from the clock, found 2026-11-07 was no session, logged "not a session yet" and exited green, so session 2026-11-06 has no row, against the "never a gap" promise (#299). Any delay past midnight repeats it, and the 22:30 run has only 90 minutes of margin. **Fix:** `evaluation.forward_ledger.resolve_session` records the newest session on or before today (an override must be a real session), `session_for_outage` dates a no-calendar outage row by the last closed weekday, and a run with no session to write raises `NoSessionToRecord`, which exits non-zero. It records only the newest session and never fills an older gap. **Verification:** `tests/test_v664_late_session.py`, `tests/test_forward_ledger.py` (a weekend run records Friday once), `tests/test_cycle_daily.py`. The definition hash covers the rule, not the script, so no new record starts.

### 333. One coin whose Coinbase fetch failed turned every coin's session into `no_data` (V6.6.4)
🟢 `fixed` · 5/10

**Problem:** both ledger scripts fetched all coins in one expression, so one failing product (EOS-USD was delisted, #311) raised for the whole candidate. **Fix:** `crypto_closes_guarded` fetches coin by coin and gives a failed coin an empty series; the row stays `ok` unless a held name has no mark, and a decision day with a failed coin holds the weights and says which coin, so a decision never silently leaves a coin out. The generations' path leaves a NaN column, which its 98% coverage rule turns into `no_data`, and raises only when every coin failed. **Verification:** `tests/test_v664_late_session.py`, `tests/test_forward_ledger.py::test_coinbase_blocked_keeps_the_weights_held`.

### 334. A record that stopped or never started raised no alarm (V6.6.4)
🟢 `fixed` · 5/10

**Problem:** `aq evaluate --forward-ledger` never passed a calendar, so its stale-ledger warning could not fire. `aq cycle status` read the local branch without fetching it. A ledger with no rows read as "0 sessions behind". Nothing re-enabled a schedule GitHub disables after 60 days. **Fix:** the evaluate flag builds the weekday calendar since the last row, `aq cycle status` fetches `origin/forward-ledger` first (a failed fetch warns), an empty ledger reports `record not started` with an action to dispatch `research-cycle.yml`, and `.github/workflows/keepalive.yml` re-enables both ledger workflows monthly with one permission and no secret. **Verification:** `tests/test_v664_late_session.py`, `tests/test_ci_workflows.py` (the new workflow is pinned). GitHub doesn't document that enabling an enabled workflow resets the timer, so the warning stays.

### 335. A generation with no selection pass could still ramp and hold capital (V6.6.4)
🟢 `fixed` · 7/10

**Problem:** `next_stage` moved a shadow generation to ramping on a 60-session forward pass alone, and `share_cap` gave a lifted cap to any tier, so a hand-entered `tier: none` record with a good-looking forward alpha could reach 100% of the paper book, against the rule that no selection pass means no share (R-ADMIT1). **Fix:** a tier-`none` generation is observed only: `next_stage` leaves it where it is (a guard trip still rejects it) and `share_cap` returns 0 for any stage and evidence; a shadow generation ramps on a forward pass only with `selection_pass`; a lifted cap is a tier-2 privilege. **Verification:** `formal/AetherFormal/Admission.lean` proves `tier_none_never_capital`, `tier_none_never_ramps`, `no_selection_no_ramp`, `retired_absorbing`, `dying_leaves_the_book` and `lifted_cap_only_for_tier2`, and 800 Lean-computed cases match Python (`tests/test_formal_differential_admission.py`); a property test runs the same claims over random evidence (`tests/test_v664_properties.py`); regression tests in `tests/test_generation_registry.py`.

### 336. Round 4: crypto risk and liquidity, EDGAR filings, ETF trend and macro timing, none survived (V6.6.4)
🔴 `closed`; the equity and crypto holdouts stay unread · n/a (phase result)

**Problem:** the owner's main task: find alpha. Three rounds fixed their rules before any score (vault commits, `ml/evaluation/v664/`): `round4c` (14 crypto trials on cell CS: low volatility, lottery, Amihud, volume trend, proximity to the high, reversal, beta, idiosyncratic volatility, a funding-filtered trend, breadth timing, a constant core, a regime-gated pair and a gradient-boosted model), `round4e` (nine on cell S: filing similarity, announcement proximity and reaction, same-month seasonality, opportunistic insider buying, cash profitability, filing similarity with accruals, ETF trend, term and credit timing) and `round4f` (the last two again, below). The EDGAR download behind three of them covers 255-294 side-A names a year, with nothing filed after 2018. **Fix:** zero survived the unchanged R-SLEEVE3 and PBO, so nothing was frozen and no holdout was read. Round 4C: PBO 0.58, x08 idiosyncratic volatility Sharpe 0.62 (first half 0.39, second 0.69, IC t 4.45), x01 low volatility 0.57, x10 breadth timing reached the placebo and failed it (sign_block p 0.18, time_shift p 0.04), the gradient-boosted x13 0.40. Round 4E: PBO 0.31, q05 cash profitability 0.39, q07 filing similarity with accruals 0.12 (IC t 3.01), q01-q04 and q06 negative. **A defect, found before any return was read:** e4 and e5 scored exactly 0.0 with no live names, because the runner masked every table to the cell's index members and ETFs and SPY are not members. Under the rule they are void and stay counted in N; the runner now masks a time-series or direct trial to the assets it names (`tradable_mask`), and the same two hypotheses were re-registered as e4b and e5b in `round4f` (vault commit `5683571b`, before any score). Round 4F: PBO 0.26, e4b Sharpe 0.75 but 1.28 then 0.09 across the halves, e5b (SPY on term and credit, one name) 0.75 and failed the placebo (time_shift p 0.04). The deflated-Sharpe N is now 217. **Verification:** `ml/evaluation/v664/r_round4.json`; `tests/test_research_round.py::test_a_time_series_trial_that_names_etfs_is_not_masked_to_index_members`, `tests/test_v664_write_rounds.py`; the paths were checked first with an oracle (Sharpe 2.57), its reversal (-2.23) and random ranks (0.23) on the crypto cell (`sanity_crypto.json`).

### 337. The forward alpha regression has the same one-session offset on SPY and AGG, and it is small (V6.6.4)
🔴 `closed` (measured; no change to the pre-registered measure) · 2/10

**Problem:** #330's check on the forward judge. A crypto book's daily return holds the bar dated before the session, while the SPY and AGG columns in each forward row are the session's own close-to-close, so they sit a session ahead of it. **Fix:** none. The judge regresses on SPY, AGG and BTCUSD, and BTCUSD is built from the same marks as the book, so it is aligned. On the re-pinned run, which uses the same three columns, the full-window alpha t moves from 0.150 (as pre-registered) to 0.116 with SPY and AGG read a session late; on the long run from 0.954 to 0.779. No verdict moves, and no forward alpha has been read yet. **Verification:** `ml/evaluation/alpha_proof.json` (`alpha_session_aligned`), `tests/test_alpha_proof.py`.

### 338. IB field test: what the Lean samples cannot show about options and futures (V6.6.4, residue of #38 and #58-#61)
🟡 `partial` (needs an Interactive Brokers account and key) · 6/10

**Problem:** options (all 43 structures, combo orders, margin, early assignment, the arbitrage detector, the strategy selector) and futures margin are verified on Lean's sample chains and on stubs, never against a real broker. **Fix:** none possible without a key. V6.6.4 narrowed what remains: the same structures now run through `main.py`'s own order path in Lean (below), and the pure functions are covered by property tests. **Left for a key:** real combo routing and fills, IB's margin against `options_margin_sizing`, assignment notices, IB chain quotes for the detector, and the selector trained on real `option_strategy_outcome` events (`aq ib status`, RUNBOOK "When the keys arrive"). **Verification:** see #38 and #58-#61.

### 339. `aq audit-log --verify` could not verify a chain read from a real Postgres (V6.6.4)
🟢 `fixed` · 8/10

**Problem:** the audit worker hashes `created_at` as the producer's string, stores it in a `TIMESTAMPTZ` column, and `fetch_all_events_ordered` returns the driver's `datetime`. `verify_chain` joins that into the hash input, so on any real database it raised `TypeError`, and even a string made from the datetime would not have matched the original text. The unit tests used strings, so nothing caught it; the hash chain existed to be checked before real capital. **Fix:** `audit.hash_chain.canonical_timestamp` writes a datetime, or an ISO string that parses, as UTC `YYYY-MM-DDTHH:MM:SSZ`; the worker hashes that form and the reader returns it, so a row hashed before this reads back unchanged (`build_audit_event` already wrote it). `compute_entry_hash` is untouched, so the Lean model and its 13 existing case files are unchanged. **Verification:** `tests/test_audit_postgres_worker.py` (a chain built through the worker verifies after a datetime round trip, an edit is found), `scripts/field_test_services.py` against a real Postgres (below).

### 340. Audit events read while Postgres was down were never written (V6.6.4)
🟢 `fixed` · 8/10

**Problem:** found by stopping a real Postgres under a running audit worker (`ml/evaluation/v664/field_test_services.json`). A message read with `xreadgroup(">")` and not acknowledged stays in the consumer's pending list and is never delivered again, so a batch that failed during an outage, or a worker that died holding messages, left those events out of the hash-chained log for good. **Fix:** `run_once` first reads its own pending entries (id `0`) until none remain, then carries on; the insert is idempotent and the chain tail is taken from the database each batch, so a replay cannot fork it. A batch that fails five times for a reason that is not the connection is dead-lettered instead of wedging the worker, and a long outage never dead-letters anything. The same real database also showed `aq paper-readiness` and `aq audit-log` crashing on a table no worker had created yet (#339 family); both now read that as no events. **Verification:** four replay tests in `tests/test_audit_postgres_worker.py`, `tests/test_paper_readiness_io.py` and `tests/test_postgres_audit.py`; on the real services all four field scenarios pass (50 events flow with an intact chain, a tampered row is found at entry 49 and the chain verifies again once restored, 20 events pushed while Postgres was down are all written after the restart, Redis stopped refuses pushes and the same publisher reconnects by itself).

### 341. A new public function could leave `aether_quant` out of date, and several safety claims had no check behind them (V6.6.4)
🟢 `fixed` · 5/10

**Problem:** nothing failed when a public function or module stayed out of the library; `aq prove` and `--check-sorry` ran in no CI job although `infrastructure.md` said they did; there was no property, mutation or axiom check; `on_data()` had only run with an empty slice; and the verification surfaces were listed nowhere. **Fix:** `scripts/library_gate.py` (pre-commit hook via `scripts/install_hooks.py`, CI's fast-guards, `codespace_verify`) fails a public name that no facade exports and that `tests/data/aether_quant_unexported.json` does not explain, and its legacy backlog can only shrink (655 unexported names became 288, and every new V6.6.4 module is exported); `tests/test_module_has_test.py` makes "one test file per module" a check; `tests/test_v664_properties.py` (hypothesis, derandomized); `scripts/mutation_check.py`; three new Lean specs, `scripts/check_axioms.py`, `tests/test_formal_no_sorry.py` and `.github/workflows/formal.yml`; `tests/test_main_on_data_target_weights.py` drives `on_data()` for a week of sessions; `aq verify` and `development/verification.md` list every surface. **Verification:** each has its tests; `ml/evaluation/v664/verification.json` holds the full run. **Mutation check (V6.6.4):** the first run changed one comparison, operator or constant at a time in seven safety and ledger modules and caught 186 of 272 mutants (68%; 53% to 85% per file), so every threshold now has a boundary test (`tests/test_v664_mutation_safety.py`, `tests/test_v664_mutation_ledgers.py`). A second run with a fresh seed, which the tests had not been written against, caught 246 of 272 (90%), and 262 of 272 (96%, every file at least 90%) after its own survivors were tested; what is left is equivalent (a price or bps of exactly zero gives zero slippage either way, tolerance edges of 1e-9, a date equal to its anchor selects no sessions). **Proofs (V6.6.4):** the Lean specs build on a Codespace, the regenerated differential cases equal the committed ones, there is no `sorry`, and all 186 theorems rest on the standard axioms (one `native_decide` finding in BookNeutrality is named and listed). Evidence: `ml/evaluation/v664/mutation_summary.json`, `proofs/`.

### 342. `pip install aether-quant` could not import its own library (V6.6.5)
🟢 `fixed` · 7/10

**Problem:** `pyproject.toml` had no `dependencies`, so a bare install had no numpy. Four facades (`cycle`, `evaluation`, `features`, `research`) failed even on the `[research]` extra, because `data_pipeline/fred_backfill.py` imported httpx at module level and no extra listed it. No test or CI job ever installed the package without the full requirements. **Fix:** the base dependencies are numpy and pandas. The extras are `research`, `notebooks`, `dashboard`, `live`, `train`, `docs` and `full`, and httpx is imported where it is used. `aq_cli.main(argv)` takes arguments so the light paths run in process. **Verification:** `tests/test_lite_install.py` blocks 24 optional packages, then imports every facade and runs `aq --help` and `aq hello --offline`. A real clean venv on the PC holds only numpy, pandas, python-dateutil and tzdata (145 MB) and runs `aq hello --offline` in 35 s (`ml/evaluation/v665/lite_install.json`). CI's new `lite-install` job repeats it on the built wheel.

### 343. No five-minute start: no demo command, no sample data, no notebook (V6.6.5)
🟢 `fixed` · 6/10

**Problem:** every first step needed the 40 GB Lean image, the trained models or a dataset the repo does not ship. The only examples ran on synthetic numbers. **Fix:** `aq hello` downloads the 11 coins' daily bars from Coinbase's public candles (`data_pipeline/public_candles.py`: keyless, paged, cached, only closed bars, a failed coin named), runs the shipped rule `t3_crypto_trend_blend_x_eos` through `evaluation/backtest_api.backtest` with Coinbase costs, and prints benchmarks and overfitting checks: PSR, PBO over 8 variants, the deflated Sharpe, the 217-trial haircut and the minimum track record. A 185 KB sample in the wheel is the offline fallback. Four notebooks (`notebooks/`, built from percent-format sources by `scripts/build_notebooks.py`) open in Colab. Building it found a pandas difference: pandas 2's `DataFrame.from_dict` drops a date whose weights dict is empty, so an empty decision held the book, where pandas 3 closed it. `rule_weights` now builds rows explicitly and both agree. **Verification:** `tests/test_hello_world.py` (rule equals the tracked candidate, no lookahead, golden Sharpe 0.43, the empty-decision regression) and `tests/test_public_candles.py`. On the PC, `aq hello` takes 26 s offline and 49 s online, and all four notebooks run clean (`tests/test_notebooks.py`, CI's `notebooks` job).

### 344. The dashboard was empty without a running system and only came in the 10 GB engine image (V6.6.5)
🟢 `fixed` · 5/10

**Problem:** the API read only runtime files that a fresh checkout lacks. The only image was the engine, with CUDA torch, and the engine port was published to the LAN. **Fix:** `AQ_DASHBOARD_ROOT` and `AQ_DASHBOARD_DEMO` point the API at another tree. `scripts/build_dashboard_demo.py` writes deterministic demo data (13 files, 71 KB) from `aq hello`. The Dockerfile gains a `wheel-builder` and a `dashboard` target that installs only the wheel, plus the UI and the demo, runs as a non-root user and has a healthcheck. The engine installs CPU torch, and compose binds the engine to 127.0.0.1. `aq webui --docker` runs it. The web UI gains a demo banner, an onboarding empty state, sign-in, an account selector, a Readiness page, a Trade Lock panel and jsx-a11y lint. The jest-dom matchers are now registered explicitly: the `/vitest` side-effect entry left them unregistered on this PC and failed every UI test. **Verification:** `tests/test_dashboard_demo.py` (a rebuild is byte-identical, and every GET route answers from the demo), 113 of 113 vitest, tsc, oxlint and the build. On the PC's Docker, `docker build --target dashboard` succeeds, and the image runs as `aq`. Its healthcheck reports healthy, `/` serves the UI, and all 20 GET routes answer 200 with `/api/health` reporting `demo: true` (`ml/evaluation/v665/dashboard.json`). The first build sent a ~600 MB context, because `.dockerignore` patterns are anchored at the root and missed `formal/.lake`, the backups and nested caches; they now match at any depth. Removing the pandas and numpy test suites and pip took the image from 461 MB to 373 MB (253 MB unpacked).

### 345. The library lacked basic research tools, and nothing grouped it by job (V6.6.5)
🟢 `fixed` · 5/10

**Problem:** the library had no Kelly sizing, no whole-book volatility targeting, no beta or factor neutrality, no composable cost model, no general backtest of arbitrary weights, no minimum track record, no haircut Sharpe, and no signal tools from prices. Its 24 facades were organised by subsystem, not by task. **Fix:** new pure modules, each with its own tests:

- `risk/kelly.py`, `risk/vol_target.py`
- `portfolio/neutrality.py`
- `execution/cost_models.py`
- `evaluation/backtest_api.py`
- `evaluation/overfitting.py`
- `evaluation/signal_tools.py`

Eight facades group them by job: `sizing`, `neutrality`, `costs`, `overfitting`, `backtest`, `signals`, `samples` and `hello`, for 32 facades. With the accounts, secrets, field-test, readiness and auth rules from #348-#352 it exports 928 names. **Verification:** `backtest()` agrees with `simulate_target_weights` to 5e-9 a day on a synthetic equity panel. Hypothesis properties check that net beta is zero after neutralising, gross never exceeds the cap, and a cost is never negative or NaN. That property found a $1 minimum fee on a subnormal trade costing infinite bps; the minimum is now charged up to the notional. The API pin is regenerated and `scripts/library_gate.py` is green.

### 346. The public API had no reference docs and a third of it was not fully typed (V6.6.5)
🟢 `fixed` · 4/10

**Problem:** 312 of the 844 exported functions and classes had a missing or bare annotation (`dict`, `Mapping`), 150 had no docstring, and there was no documentation site. **Fix:** two codemods parametrised the bare containers and annotated every parameter from its real use: `ArrayLike`, `WideCell`, `date`, and `TYPE_CHECKING` imports. Every export now has a docstring. `scripts/type_completeness.py` is the gate, with a floor that can only rise. The MkDocs site (`mkdocs.yml`, `docs/`) has getting started, the four tutorials, a guide whose examples run in tests, the live pages, an API reference generated per facade (`scripts/build_docs.py`) and the about pages. `pyright --verifytypes` found no package on this Windows editable install, so it runs as an advisory step in CI on the built wheel. **Verification:** 887 of 887 exported callables fully annotated, with the Part C exports included (`ml/evaluation/v665/type_completeness.json`). `tests/test_public_docstrings.py` and `tests/test_docs_site.py` pass, and `mkdocs build --strict` gives 0 warnings.

### 347. The license kept institutions from using any part of the project (V6.6.5)
🟢 `fixed` · 4/10

**Problem:** the whole repository, library included, was under PolyForm Noncommercial. **Fix (owner decision 2026-11-08):** everything the wheel and the dashboard image ship moves to Apache-2.0 (`LICENSES/Apache-2.0.txt`, `NOTICE`), and so do the web UI, the notebooks, the docs, the examples and the Lean proofs. The trading system stays PolyForm Noncommercial. The map is in the root `LICENSE` and in `REUSE.toml`. The wheel metadata reads `License-Expression: Apache-2.0`, and releases up to 6.6.4 keep their old license. An audit found no third-party license header in the Apache paths. **Verification:** `tests/test_licensing.py` checks every file the wheel ships against `REUSE.toml`, and the built wheel's `.dist-info/licenses/` holds the Apache text and NOTICE. This is not legal advice: commercial terms for the PolyForm parts are the owner's to set.

### 348. Secrets came only from plain environment variables, and Coinbase keys could not be rendered (V6.6.5)
🟢 `fixed` · 6/10

**Problem:** every credential was an `AETHER_*` variable, so there was no Docker secret, file or keyring option. `SECRET_ENV_MAP` had no Coinbase fields, though the crypto sleeve needs Coinbase (#192). RUNBOOK said to put keys in the tracked `lean.json`, which `aq secrets-check` forbids. `aq cycle status` looked for keys only in `lean.json`, and compose's `lean-live` never passed `--lean-config`. **Fix:** `execution/secrets.py` and `secrets_io.py` resolve each named secret from a `*_FILE` file, a Docker secret, the environment or the OS keyring. Values travel as a `SecretValue` that never shows itself, and named accounts are prefixed. Seventeen call sites read through `secret_env`, which equals the old `os.environ.get` when only the variable is set. The renderer takes the Coinbase pair and `--account`. Also new: `aq secrets status|set|delete`, `docker-compose.secrets.yml`, corrected key detection and hint, `lean-live --lean-config`, and ignore entries for `accounts.json`, `state/` and `secrets/`. **Verification:** `tests/test_secrets.py`, plus a hypothesis property that no status line, redaction or text form contains a secret.

### 349. One account only (V6.6.5)
🟢 `fixed` · 5/10

**Problem:** the system had one credential set, one portfolio, one set of state files and one override file, and no account dimension in the audit log or the API. **Fix:** `execution/accounts.py` and `accounts_io.py` add a registry, `accounts.json`, whose overrides may only tighten the base config (proved in `formal/AetherFormal/AccountOverrides.lean`, with 320 differential cases). `main.py` resolves `AQ_ACCOUNT` or the Lean parameter `aq-account`. A named account writes under `state/accounts/<id>/`, reads its own overrides and secrets, and tags its audit events. The default account changes nothing. New commands: `aq accounts`, `aq live up|down --account`, `aq render-lean-config --account`, `aq trade-lock|kill-switch --account` and `aq evaluate --account`. The API gains `/api/accounts` and `?account=`. **Verification:** `tests/test_main_accounts.py` shows on the real config that the default account keeps the same config, paths and audit queue, and that a named one tightens and namespaces. `tests/test_accounts_parity.py` shows main.py and the offline loader derive the same effective config (rule 6). Unit and hypothesis tests cover the rest. In Lean, run `2026-11-12_11-22-15` (today's code, the pin's weights and window) reproduces pin `2026-11-07_17-54-01` order for order: 1974 of 1974 order events and all 27 statistics. In the field test, `paper-a` (paper) and `paper-b` (observation, tighter limits) ran at once, as `state/accounts/paper-a/` and `state/accounts/paper-b/`. Their audit events carry their own ids (`ml/evaluation/field_test/2026-11-11/report.json`).

### 350. The API had no users, no auth and no write path, and was published to the LAN (V6.6.5)
🟢 `fixed` · 6/10

**Problem:** every route, the audit log included, was readable by anyone who could reach the port, and compose published that port on all interfaces. An operator could lock trading only from a shell. **Fix:** `monitoring/auth.py` and `auth_io.py` add viewer, operator and admin roles, random tokens stored as salted PBKDF2-SHA256 hashes, and per-account scope. `authorize` is proved never to grant above a role or outside a scope (`formal/AetherFormal/Authorize.lean`, 400 cases). With a users file, a middleware requires a bearer token on every `/api` route but `/api/health`. `POST /api/accounts/<id>/trade-lock` locks for an operator and unlocks for an admin; it writes the override main.py reads and a hash-chained `state/api_actions.jsonl` record. Also new: `aq users add|list|remove`, the engine bound to 127.0.0.1, and sign-in in the UI. With no users file, reads stay open and nothing can write, as before. **Verification:** `tests/test_api_auth.py` (401, 403, scope, lock and unlock, chain verified, an invalid users file refuses to serve), `tests/test_auth.py` with a hypothesis property, and the differential test.

### 351. The safety paths had never run against orders, a trip, a breach or a restart (V6.6.5)
🟡 `partial` · 7/10

**Problem:** V6.6.4's live plumbing started main.py in `live-paper` and survived outages, but placed no order, tripped nothing and reconciled nothing (#228). **Fix:** `execution/field_test.py` adds injectors. They run only when the run's config and `AQ_FIELD_TEST=1` agree, and only in observation or in paper on Lean's own paper brokerage, never live; a property test checks this. One target row goes through the real `_apply_target_row`, injected drift hits the holdings reconciliation reads, and an injected drawdown velocity hits the kill switch. `FIELD_TEST` engine-log lines record what happened, and `judge_field_test` grades nine checks. A reconciliation breach is now an audit event of its own. `scripts/lean_smoke/field_test.py` runs three scenarios against real Redis and Postgres:

1. orders, drift, the shock and both outages
2. a restart on the same project
3. two accounts at once

**Verification:** 9 of 9 checks pass on the PC's Docker (`ml/evaluation/field_test/2026-11-11/report.json`, engine logs beside it, no traceback):

- 14 orders submitted and filled.
- The drift breached reconciliation at bar 8, with an audit event.
- The shock tripped the kill switch on its own bar 14. The strategy's exposure was 0.0 from the next bar.
- Redis and then Postgres were stopped under the running engine, which stayed up.
- The restart's first reconciliation was clean.
- `paper-a` and `paper-b` ran at once in separate state directories.
- The 43-entry audit chain verifies and carries both account tags.

Two findings came from running it, both fixed:

- **The gate.** Paper orders need `allow_live_orders`, yet the first gate required it off, so no order could be placed. The gate now names Lean's paper brokerage instead.
- **The flatness measure.** Flatness was first measured with the T-bill sweep included; the lock keeps the sweep on purpose (attempt 1, 8 of 9). It is now measured as the lock's own liquidation defines it.

Lean's paper brokerage starts empty on each run, so the restart proves the state files and a clean first reconciliation, not broker-held positions. **Open:** a real broker (IB and Coinbase: #338, #192) and a paper period (#228).

### 352. No measured checklist stood between paper and live (V6.6.5)
🟢 `fixed` · 5/10

**Problem:** the paper-to-live conditions were prose in RUNBOOK. The live broker gate ran only inside main.py, and `aq paper-readiness` never showed it. **Fix:** `execution/live_readiness.py` and `_io.py` build a scorecard of 21 metrics in six groups (edge, paper, safety, operations, code, accounts) from what the project already writes. Unknown counts as fail, and stale evidence fails. Thresholds live in `phase_v2.live_readiness`, which is report-only; `enforce_before_live`, off by default, makes main.py hold a live run in observation unless the last scorecard is ready. Also new: `aq live-readiness [--docs]`, `/api/readiness`, the Readiness page, `docs/live/paper-to-live.md` with the generated table, `scripts/backup_postgres.py`, and `aq paper-readiness` now reports the live gate. **Verification:** `tests/test_live_readiness.py` (a property: missing evidence is never ready), `tests/test_live_readiness_io.py` and `tests/test_backup_postgres.py`. At the phase end the real repo scores NOT READY: 7 pass, 6 fail, 8 unknown, with the field test, verification and mutation rows passing.

### 353. CI scanned little and blocked less, with no coverage report or badges (V6.6.5)
🟢 `fixed` · 4/10

**Problem:** the gitleaks and npm audit jobs were advisory. There was no CodeQL, SAST, image scan, SBOM or provenance, coverage was a bare XML artifact, and the README had no CI, coverage or security badge. **Fix:**

- **Blocking now:** gitleaks on the working tree (it passed on every run since V5.5.0); the history scan is advisory until reviewed. npm audit of runtime dependencies blocks too, after `npm audit fix` moved react-router to 7.18.5 and fflate to 0.8.3 with no breaking change.
- **New CI jobs:** `lite-install`, `typecheck`, `docs`, `notebooks` and `bandit` (0 high findings in 49k lines).
- **Image scans:** docker-checks builds and smoke-tests the dashboard image and scans the tree and the image with trivy.
- **Coverage:** Python coverage gains JSON and HTML reports plus a run summary; vitest coverage is uploaded too.
- **New workflows:** `codeql.yml`, `scorecard.yml`, and `pages.yml`, which publishes the docs, the coverage reports and a shields endpoint badge.
- **Release:** both images go out, with SBOMs and build provenance.

**Verification:** `tests/test_ci_workflows.py` pins every job, permission and version (30 tests), and actionlint 1.7.7 passes all nine workflows. The first CI run of the new jobs is the owner's push.


### 354. The first CI run of V6.6.5 failed on what the PC could not show (V6.6.5)
🟡 `partial` · 4/10

**Problem:** the push of `1edb206` failed Scorecard and eight CI jobs, for causes the PC could not show:

- **Scorecard:** `ossf/scorecard-action@v2.4.0` pulls its image from gcr.io, which now refuses the pull.
- **docker-checks:** the tag `aquasecurity/trivy-action@0.28.0` no longer exists.
- **docs:** `mkdocs-jupyter==0.27.0` needs Python 3.12, and CI builds on 3.11.
- **workflows-lint:** shellcheck flagged an unused loop variable.
- **Doc guards:** they found links to the gitignored `docs/tutorials/` copies and a placeholder path. The clean-checkout script had missed both, because it copies new files without adding them to its worktree's index.
- **pandas 2:** `DataFrame.stack()` treats the sample's leading NaNs differently, which broke a sample test.
- **Windows:** the checkout turned the demo files into CRLF, and text-mode `git check-ignore --stdin` handed git a trailing `\r` on every path but the last.

**Fix:**

- Scorecard v2.4.3 (pulls from ghcr.io), and trivy-action pinned to v0.35.0's commit.
- `mkdocs-jupyter==0.26.1` (Python 3.9+), resolved for 3.11 with `uv pip compile` and built `--strict` with the pinned set.
- The loop variable renamed to `_`.
- The link checker reads a docs tutorial from its `notebooks/` source.
- The sample test checks finite values with numpy.
- `monitoring/demo/** text eol=lf`, and both `check-ignore` helpers send bytes.

**Verification:** every fix passes locally, with the docs tests run without the generated tutorials and actionlint clean. The next push (`32c282c`) ran CI, Scorecard, CodeQL and Pages green.

**Release `v6.6.5`:** the tag's run failed in two places and published nothing to PyPI:

- The wheel's SBOM step used `--output-file`, which `cyclonedx-py` 4.6.1 does not have; the flag is `--outfile`.
- `anchore/sbom-action` tried to attach each image's SBOM to the release, which needs `contents: write`. Both images were already pushed and attested by then.

**Release fix:** the flag is corrected (checked against 4.6.1's own help and run end to end), the image SBOMs stay workflow artifacts (`upload-release-assets: false`), and `github-release` skips a release that already exists, so the moved tag can run again. It stays 🟡 until that run publishes to PyPI.

### 355. CodeQL's first analysis: a Telegram token and Redis passwords could reach the logs (V6.6.5)
🟢 `fixed` · 6/10

**Problem:** the first CodeQL run (`1edb206`) raised 15 high and 20 medium alerts.

- **Real:** a `requests` error quotes the Telegram URL, which holds the bot token, and four Redis clients logged their URL, which may hold a password.
- **Real:** `pages.yml` ran CI's checked-out code with Pages write rights whenever `head_branch` was `main`, which a fork's pull request can also claim.
- **Medium:** `ci.yml` and `release.yml` gave every job the default token.
- **False positives (7):** prints of secret *names* in `aq_cli.py` and `scripts/render_lean_credentials.py`, and a test's URL assertion.

**Fix:**

- `execution.secrets.redact_url` masks a URL's password, and every Redis log line goes through it.
- The Telegram client redacts its token from every error it logs.
- Pages deploys only a push to this repository's `main`.
- Both workflows default to `contents: read`; the publishing jobs keep their own scopes.

**Verification:** tests prove a failed Telegram send, a non-2xx body and an unreachable Redis URL never log the secret, and they pin the URL masking and both workflow guards. actionlint is clean. The false positives are for the owner to dismiss in the code-scanning view.


### 356. The OpenSSF Scorecard never saw a release (V6.6.6)
🟡 `partial` · 5/10

**Problem:** the Scorecard scored the newest commit, but Signed-Releases read "no releases found". Scorecard skips a release with no assets, and `release.yml` created notes-only releases: the wheel, the SBOMs and the attestations went to PyPI, GHCR and the attestation store, never to the release.

**Fix:** each tag now attaches the wheel, the sdist, the SBOM, a Sigstore `.sigstore.json` per file and an SLSA `.intoto.jsonl` (the generic SLSA 3 generator), then dispatches the Scorecard on `main`. A `backfill_tag` dispatch attaches PyPI's own files, checked against PyPI's digests and signed, to an older release (RUNBOOK "Releases").

**Verification:** `tests/test_ci_workflows.py` pins the assets, the provenance job, the re-run path, the backfill and the Scorecard dispatch; actionlint is clean. It stays 🟡 until a tag shows Signed-Releases above zero.

### 357. Scorecard hygiene: unpinned actions, top-level write tokens, a risky checkout, low dependency floors (V6.6.6)
🟢 `fixed` · 4/10

**Problem:** the Scorecard read 4.2. Every action used a tag and every base image a tag, three scheduled workflows held write tokens at the top level, and `pages.yml` checked out a `workflow_run`'s commit. OSV counted 38 advisories, almost all against the `>=` floors in `requirements/` rather than what CI installs.

**Fix:**

- Actions are pinned by commit with a version comment, and base images by digest. The SLSA reusable workflow keeps its tag, because it refuses a SHA.
- Dependabot gains the Docker ecosystem, with digest refreshes only.
- Writes moved onto the one job that needs them.
- Pages checks out `main` and uses CI's coverage only when it ran on that same commit.
- Floors rose to the first fixed versions: black, pyarrow, pytest, flask, python-dotenv, requests, scikit-learn, torch 2.9.1 (what the PC runs), and vitest 4.1.12.
- Still open: five torch advisories with no fixed version, three fixed only in torch 2.10 to 2.13, held per `todo.md` because a torch bump can move the model files. Hash-pinned pip installs are out of scope.

**Verification:** tests pin the SHA pins, the digests, the job-level writes and the checkout. Branch protection, code review, the CII badge and fuzzing stay owner and process items.

### 358. Public pages quoted numbers by hand, and the test badge lagged (V6.6.6)
🟢 `fixed` · 3/10

**Problem:** the trial N appeared as 217 on the site and as "71 trials" in the README. The hello-world figures, the sample window and the Lean pin's run ID were copied in by hand.

- A README sentence still said the light install "arrives with release 6.6.5".
- The release section claimed tag tests block a release.
- The test badge changed only when someone ran `aq test` locally.
- The GitHub About still described a long/short multi-asset book.

**Fix:**

- New facts: `research.trials` (Problems.md), `sample.*` (the bundled sample), `hello.*` (a summary `tests/test_hello_world.py` checks against a real run) and `lean.pin_run` (the README's generated header).
- A generated `CHANGELOG_LATEST` block, and the stale text fixed.
- The test badge comes from CI's JUnit report (`scripts/test_badge.py` on Pages). The local badge writer and the `test-count-drift` job are gone.
- What can't be generated is listed in AGENTS.md "After every phase".

**Verification:** `tests/test_docs_facts.py`, `tests/test_test_badge.py`, `tests/test_hello_world.py` and `aq docs sync --check` are clean.

### 359. Coverage measured about two thirds of the code, and the gate sat at 80% (V6.6.6)
🟢 `fixed` · 4/10

**Problem:** CI measured 86% over a hand-listed set of packages. Whole-repo coverage, counting `main.py`, `train*.py`, `scripts/` and the other top-level modules, was **67.6%** (47,482 statements, 15,369 missed). Eight lines were hidden with `pragma: no cover`, and some were dead code behind an `ImportError` that cannot happen. Many one-off scripts had no test, and `aq test` on the 4 GB PC could not produce a whole-repo number.

**Fix:**

- The measured scope is every directory with tracked code (`source_dirs`), `if TYPE_CHECKING:` is the one exclusion, and `fail_under` and CI's gate are 100. `tests/test_coverage_scope.py` pins all of it.
- `aq test --coverage` runs the registered groups one process at a time and reports the combined figure.
- Every pragma is gone: dead fallbacks in `risk/asset_class_router.py` and `topology/market_topology.py` were removed, and the rest got tests.
- New tests use `tests/script_loader.py` (a loader, a runner for `__main__`, a write blocker and a stand-in for the gitignored stored rules). `tests/test_script_entry_points.py` runs the `--help` of every script that has a command line.
- Round files `tests/test_v666_coverage_*.py` hold the small branch tests per package.

- Runtime tests run whole programs on small synthetic worlds: a fake QuantConnect `QCAlgorithm` for `main.py` (`tests/lean_world.py`, `lean_fakes.py`), generated Lean zips for `train.py` and the trainers (`train_world.py`, `trainer_fakes.py`) and a wide equity and crypto root (`wide_world.py`).
- Real defects the tests found are in #360. Branches that cannot run were removed with a comment (a fold that cannot be empty, an event that is always in its own date list, a group with no rows, a purchase that is never routine).

**Verification:** `aq test --coverage` on the PC: 47,438 statements, 0 missed, **100%**, `fail_under=100` met, 8,000+ tests passing across all 16 groups, `ruff check .` clean. A real Lean engine run stays the owner's (`aq backtest`); `main.py` is covered against the fake Lean, not the engine.

### 360. The offline legacy sleeve's exits never fired as configured (V6.6.6)
🟢 `fixed` · 3/10

**Problem:** writing the missing tests for `evaluation/rank_book_simulator.py` showed two defects in the legacy sleeve's backstop exits. The age exit compared the exit function's reason to `max_holding_bars_reached`, a string `risk_controls.evaluate_non_model_exit` never returns (it returns `max_holding_age_exceeded`), so a position never aged out. The call also passed `exits_enabled = max_holding is not None`, so a trailing stop alone was switched off, and a missing stop was passed as 0.0, which fires on any position that has a peak. Live was correct; only the offline simulation of the legacy sleeve was off, and the shipped book sets neither exit on it.

**Fix:** the sleeve checks the real reason string, enables the exit function whenever either rule is configured, and passes an infinite stop when none is.

**Verification:** `tests/test_rank_book_legacy_step.py` covers an age exit, a trailing-stop exit, and no exit when none is configured. Dead guards the same round found (a fold that cannot be empty, an event that is always in its own date list, a group that cannot have zero rows, a purchase that is never routine) were removed with a one-line comment each.
