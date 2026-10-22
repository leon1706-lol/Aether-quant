# Problems

<p align="center">
  <img src="https://img.shields.io/pypi/v/aether-quant?style=flat-square&labelColor=1A1A1A&color=FF8C00&logo=pypi&logoColor=white" alt="PyPI version">
  <img src="https://img.shields.io/badge/tests-3796%2F3796%20passing-brightgreen?style=flat-square&labelColor=1A1A1A" alt="3796 of 3796 tests passing">
  <img src="https://img.shields.io/badge/python-3.10%2B-FF8C00?style=flat-square&labelColor=1A1A1A&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/%F0%9F%93%84%20license-PolyForm%20Noncommercial%201.0.0-8B5CF6?style=flat-square&labelColor=1A1A1A" alt="License: PolyForm Noncommercial 1.0.0">
  <img src="https://img.shields.io/badge/problems-230%20entries-0097E8?style=flat-square&labelColor=1A1A1A" alt="230 problem entries">
</p>

Bugs and infrastructure issues found in this codebase, how they were fixed
(or why still open), with severity rating (1 = cosmetic, 10 = critical
data-loss/safety issue) and status. Ordered by entry number (oldest first);
entries #73-76 don't exist (skipped in original numbering), and #88 appears
twice (`88a` and `88`) from an earlier numbering mistake — both kept
unrenumbered to avoid breaking cross-references elsewhere in this repo
(Changelog.md, memory files, etc.).

**Status legend:**
- 🟢 `fixed` — code changed (or final decision made) and verified or self-evidently complete; nothing meaningfully pending.
- 🟡 `partial` — fix shipped but verification incomplete/pending (e.g. needs a real Lean backtest or IB connection), or a real known caveat/open sub-issue remains.
- 🔴 `closed` — no code fix applied: declined/won't-fix, non-goal, moot, or superseded without ever being fixed on its own terms.

Every entry follows **Problem** → **Fix** → **Verification** (~1-2 sentences each; real Lean backtest, unit tests, or manual review; standing convention: `main.py` itself has zero direct unit test coverage, so many Lean-adapter fixes are verified only by manual review or a real backtest). 🟢 entries with nothing pending are condensed; 🟡/🔴 entries and 🟢 entries that still carry an explicit open caveat keep their full detail.

---

### 88a. Lean CLI's generated Windows dependency mount was unreliable, and startup imported the training stack

**Severity:** 6/10 · **Status:** 🟢 `fixed` (V5.1.11)

**Problem:** On some Windows Docker Desktop hosts Lean CLI's generated temp `requirements.txt` mount was rejected even though project files were readable; separately, `main.py` importing `performance` at module scope pulled the training/PyTorch graph into Lean's 90-second startup isolator window.

**Fix:** `aq backtest` builds a cached local image with Redis pre-installed (no generated requirements mount), the Windows wrapper grants Docker read access to Lean-created temp dirs, and `main.py` defers `evaluate_all_triggers` to dashboard view; the missing `httpx` runtime dep was added to `requirements/lean-runtime.txt`.

**Verification:** Regression tests cover both boundaries; four real backtests (V5.2.4-V5.2.7) later confirmed the `httpx`/`fred_backfill` chain.

### 1. `experience-worker` crash loop — missing `numpy` dependency

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/observation_metrics.py` imports `numpy`; `requirements-worker.txt` (backing `experience-worker`) never listed it — container crash-looped with `ModuleNotFoundError`.

**Fix:** Added `numpy>=1.24.0`; same proactively applied to trigger-worker requirements.

**Verification:** Rebuilt/restarted; clean startup via `docker compose logs`.

### 2. `Dockerfile.worker` missing `execution/` copy

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/simulated_portfolio.py` imports `execution.order_gate`; `Dockerfile.worker` never copied `execution/` — rebuild would fail with `ModuleNotFoundError`.

**Fix:** Added `COPY execution/ ./execution/`; same pattern applied to `Dockerfile.trigger_worker`.

**Verification:** Caught via import-graph tracing pre-rebuild; standing lesson documented in `development/architecture.md`.

### 3. Simulated portfolio/positions snapshot not mode-aware

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Webui Positions panel/summary always read real (flat, uninvested) `self.Portfolio` even in `observation` mode, contradicting mode-aware drawdown beside it.

**Fix:** Added `_snapshot_portfolio_summary()`; `_snapshot_positions()` mode-aware via `SimulatedPortfolioState` when real orders blocked.

**Verification:** Live screenshot review with user.

### 4. Webui: empty space above Market Scene panel

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** CSS Grid default `align-items: stretch` padded shorter left column to match taller right column.

**Fix:** `items-start` on outer grid; wrappers → `flex flex-col gap-4`.

**Verification:** Live Playwright screenshot review.

### 5. Webui: Signal Distribution / Rejected By Reason tables overflow the panel

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Long reason strings forced `<table>` wider than its Grid track; default `min-width: auto` blocked shrinking.

**Fix:** Flexbox rows replace `<table>`; added `min-w-0`, `break-words`.

**Verification:** Same screenshot review as #4.

### 6. `aether-grafana` container name collision blocks the real Grafana service

**Severity:** 3/10 · **Status:** 🟢 `fixed` (moot, no code change needed)

**Problem:** Orphaned unmanaged `aether-grafana` container (port 3000, non-compose volume) would have blocked `docker compose up -d grafana` (same name).

**Fix:** No action — Grafana removed from stack in V2-18 (replaced by React tracing dashboard); collision moot.

**Verification:** Re-checked 2026-07-04: no such container; no `grafana` service exists anymore.

### 7. ~85GB of orphaned duplicate Lean engine images + stale containers/volumes

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Two untagged 42.5GB `quantconnect/lean` images, stale one-off containers, unused pip-cache volumes, stray/unpinned tags accumulating disk.

**Fix:** Removed confirmed orphans (`docker rmi`/`docker volume rm`) after two passes — first missed image `650dd8d4063a` plus unrelated Grafana volume/image, corrected on follow-up.

**Verification:** Re-verified via `docker images -a`/`docker volume ls`; Aether-Vault items untouched.

### 8. Bare `pytest` (no path) fails from repo root

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** Bare `pytest` also crawled `backtests/*/code/tests/` (each backtest copies full algorithm code incl. tests) — ~76 duplicate-module-name collection errors.

**Fix:** `pyproject.toml` `[tool.pytest.ini_options]` sets `testpaths = ["tests"]`.

**Verification:** README's `pytest tests/` form still works; bare `pytest` works too.

### 9. Total-drawdown trade lock never auto-clears within a run

**Severity:** 4/10 · **Status:** 🟢 `addressed` (manual override, not a default-behavior change)

**Problem:** Total-drawdown lock never clears within a run (unlike daily lock) — real run showed it blocking ~79% of events after one early breach. Treated as intentional capital-preservation behavior, not silently patched.

**Fix:** Added `phase_v2.risk.manual_trade_lock_override` (read once per session rollover), `aq trade-lock --on/--off/--auto` CLI, auto-clear-on-successful-promotion hook in `retraining/orchestrator.py::promote()`. Default sticky behavior unchanged.

**Verification:** Documented in Manual Trade-Lock Override Contract (`development/architecture.md`).

### 10. `ci.yml`'s `test` job fails on GitHub's Linux runner — root cause found and fixed

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** The first clean-install bare-`pytest` CI run surfaced four masked problems: a nonexistent PyPI package name, pytest not adding the repo root to `sys.path`, two reference files swallowed by a blanket `.gitignore` rule, a Python 3.11-vs-3.14 float-summation difference in `empirical_duration_beta()`, and a Lean-backtest skip-guard checking binary presence rather than a usable Lean Data folder.

**Fix:** Corrected the package (`lean>=1.0.225`), set `pythonpath = ["."]`, committed both reference files via a `.gitignore` exception, replaced the exact-zero variance check with a `<1e-12` tolerance, and required a real Lean Data file in the skip guard.

**Verification:** The four previously-failed tests plus three new regression tests pass locally, and a real GitHub Actions run passed post-fix (user-confirmed).

### 11. `_write_state()`'s per-bar throttle was unreachable

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Dead guard clause meant 7 output files fully rewritten every bar instead of once per timestamp.

**Fix:** Removed impossible clause (`if ... and signals is None`).

**Verification:** Found during latency audit of `main.py` hot path.

### 12. `observation_equity_curve.csv` quadratic rewrite (N-per-bar entries + full-file rewrite every bar)

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `mark_to_market()` ran once per symbol per bar, producing `N·B` equity-curve entries instead of `B`, and #11's every-bar flush plus full-file CSV rebuild made write cost `O((bars·symbols)²)`.

**Fix:** `on_data()` now accumulates closes and calls `mark_to_market()` once per bar, with an append-only flush (`_flush_observation_equity_csv()`) tracked by a written-count offset.

**Verification:** A unit test asserts one entry per multi-symbol call; row-count-equals-bar-count was confirmed via real Lean backtest output.

### 13. Per-bar/per-poll `config.json` reads on every session rollover, uncached

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** At Daily resolution the once-per-session rollover check fires every bar, each firing doing uncached `open()`+`json.load()` of `config.json` in several places (`main.py`, `retraining/worker.py` poll loop).

**Fix:** New `execution/config_cache.py::read_cached()`, an mtime-gated cache keyed on both path and loader (a path-only key collided across readers and crashed `_recompute_broker_config()` on bar 1 of a real backtest).

**Verification:** New `tests/test_config_cache.py` (with a collision regression), re-confirmed via a real Lean backtest re-run.

### 14. Redis push in backtest mode — deliberately left unoptimized

**Severity:** n/a · **Status:** 🟢 `resolved` (confirmed no-op, no code change needed)

**Problem:** `experience/redis_queue.py::push()` does blocking Redis write every bar even in backtest mode — skippable for perf, but unconfirmed downstream dependency made skipping risky.

**Fix:** No code change — owner confirmed nothing reads backtest-mode experience events downstream from Postgres.

**Verification:** Direct owner confirmation, not testing.

### 15. `ensure_derived_crypto_daily_series()` silently discarded yfinance-backfilled crypto history on every `train.py` run

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** Function rebuilt derived crypto daily zips (ETHUSD/LTCUSD) via full-overwrite `ZipFile` write from sparse raw minute data, wiping 1000+ days of yfinance-backfilled history to 3-4 rows every `train.py` run.

**Fix:** Reads existing zip, merges by date — fresh minute-derived rows win only where real minute data exists; other dates survive.

**Verification:** Regression test `test_ensure_derived_crypto_daily_series_merges_with_existing_backfill`.

### 16. `main.py::initialize()` exceeded Lean's hard 90-second isolator timeout at 20 assets

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** Loading all model/expert/topology artifacts plus deriving ~40 config values inside `initialize()` pushed isolator-timed cost past Lean's non-configurable 90s cap at 20 assets, so every `lean backtest .` failed.

**Fix:** Split into a minimal Lean-critical path (dates/cash/subscriptions/warm-up) plus `_ensure_ready()` carrying artifact/config loading, deferred to the first `on_data()` (no isolator limit there).

**Verification:** Disk-log instrumentation (a timed-out `initialize()`'s `self.Debug()` is silently lost) confirmed `initialize()` completes in 1.85s with a ~51s full window; the 525-test non-Lean suite stayed green.

### 17. Matplotlib font cache rebuilt from scratch on every single `lean backtest .` run

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Lean's `AlgorithmImports` bridge imports matplotlib, so ephemeral per-run containers rebuilt the font cache (20-40s) every run, occasionally breaching the 90s isolator cap even after #16.

**Fix:** `main.py` sets `MPLCONFIGDIR` to a host-mounted `.matplotlib_cache/` before any other import, so the cache survives containers.

**Verification:** Two consecutive real runs: ~82s import cold vs ~58s warm, zero timeout.

### 18. Two structural "never recovers" traps suppressed real backtest trade count to 12 over 3 years

**Severity:** 5/10 · **Status:** 🟢 `addressed` (opt-in statistical bypass, default behavior unchanged)

**Problem:** A one-time mass liquidation crossing the 12% total-drawdown limit froze trading for the remaining 374 days of a 3-year backtest — the sticky lock plus a `peak_equity` running-max that never fell meant it could never self-clear; an earlier-firing 8% twin sat in the regime `risk_off` drawdown branch.

**Fix:** Opt-in `phase_v2.backtest.bypass_safety_gates` (default `false`, backtest-only) bypasses only these two mechanisms, with other gates fully active and live/paper unaffected.

**Verification:** Scoped to statistical/model-quality backtesting only (never representative of live behavior) and deliberately not wired into `aq trade-lock`.

### 19. Neural-network webui tab's gating exclusion went stale the moment gating became learnable

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Gating hardcoded excluded from `/neural-network` list ("no learned weight matrix"); 3D scene render order hardcoded to exactly 5 names — both stale once gating gained optional learned model.

**Fix:** Removed gating from exclusion list; wired through generic network-summary path; added to render-order array.

**Verification:** Standing gotcha noted: render-order array is silent filter needing manual updates for anything new to appear in 3D scene.

### 20. `Dockerfile.retraining_worker` never copied `risk/`, so `retraining.worker` could not have started

**Severity:** 7/10 · **Status:** 🟢 `fixed` (superseded by the consolidated engine image, #30)

**Problem:** `retraining/orchestrator.py` imports `risk.manual_override` at module level, but the worker image's COPY list lacked `risk/`, so every start crashed with `ModuleNotFoundError`.

**Fix:** added `COPY risk/` (and `train_multitask.py`); V5.5.0's single engine image later removed per-worker COPY lists altogether.

**Verification:** found by static import-graph tracing; the consolidated image runs the worker.

### 21. Per-bar model forward-pass count doubled (5 → 11) — measured, not currently a problem

**Severity:** 2/10 · **Status:** 🟢 `measured, not currently a problem`

**Problem:** Multitask/sequence models roughly doubled per-symbol-per-bar forward passes (5 → 11; batching keeps top-level calls at 5), never measured against any budget.

**Fix:** No code change — measured via `aq profile --batched`: ~12ms mean/symbol/bar, negligible vs only enforced constraint (Lean's 90s `initialize()` isolator cap, unrelated to per-bar cost).

**Verification:** 10,000-iteration profiling runs (batched/unbatched) with real exported weights; sequence encoder causal conv flagged largest remaining cost / future optimization candidate.

### 22. `tests/test_retraining_worker.py` silently ran real training (subprocess-level hang, up to ~30 minutes per test)

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** 7 of 10 tests never updated to mock newer `train_multitask`/`train_sequence` stages — with real artifacts present they fell through to genuine subprocess training, up-to-30-minute timeouts (looks like hang).

**Fix:** Added `patch("retraining.worker.train_multitask")`/`train_sequence` to all 7, matching existing mock pattern.

**Verification:** Previously-hanging test ~1.2s; full 10-test file ~1.2s total.

### 23. BTCUSD volume-feed unit discontinuity blew up the sequence model's RMSE 31x

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** BTCUSD raw volume jumped ~520,000x on one date (a real Coinbase feed unit-convention change), producing a 5.2-million-percent single-day "return" through an unclipped `StandardScaler` that poisoned 30 rows of the sequence window — 66%+ of the backtest's squared error.

**Fix:** Three layers: clamp `volume_change_1d` to `[-1.0, 20.0]`, winsorize scaler-fit columns pre-fit, and clip scaled values to `±10σ` (persisted to `scaler_stats.json` so `main.py` applies the same bound at runtime), plus an automated regression-quality gate.

**Verification:** Post-fix the max absolute scaled value is exactly 10.0 (clip firing) and the retrained RMSE/MAE ratio fell 31x → 1.59x.

### 24. `train.py` never applied Lean's own split/dividend factor files — offline dataset had fake ±74%/+745% "returns"

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `train.py`'s independent raw-zip reader bypassed Lean's split/dividend adjustment, so real corporate actions (AAPL's 2020 4-for-1, USO's reverse split) produced fake ±74%/+745% "returns" in every label/feature spanning the boundary — an offline train/runtime parity gap (Lean's own engine was unaffected).

**Fix:** New `train.py::apply_split_adjustments()` reads each equity's real Lean factor file and rescales OHLCV exactly as Lean does; `yfinance_backfill.py` switched to `auto_adjust=True`, with a per-security-type label-outlier guard as defense-in-depth.

**Verification:** On real data the AAPL split-boundary "return" fell from -74% to ~3.4% and USO's from +745% to ~5.6%.

### 25. No quality gate ever existed for regression heads (magnitude/volatility/rank) — only direction MCC was gated

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Only direction models quality-gated; regression heads had none — how #23's 31x blowup shipped silently a whole session.

**Fix:** New `train.py::assess_regression_quality()` gates on RMSE/MAE and backtest/train RMSE ratios; wired into `train_multitask.py`/`train_sequence.py`; surfaced on `/neural-network`.

**Verification:** Mirrors `assess_expert_quality()` shape/convention.

### 26. `main.py`'s sequence-model runtime buffer size never read the trained model's own `window_size`

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** Runtime buffer size came only from `config.json`, never model schema — retrained model with different window silently disabled sequence signal via shape-mismatch exception, unsurfaced.

**Fix:** New `resolve_sequence_window_size()` — schema value wins when loaded; config fallback otherwise.

**Verification:** Extracted as pure function for unit-testability outside Lean runtime.

### 27. Phase 2's new era/fold-splitting functions crashed on real training runs — assumed datetime input, but the real dataset's `date` column is plain strings

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `split_into_non_overlapping_eras()`/`purged_embargoed_folds()` did Timestamp arithmetic on `np.asarray(dates)`, correct only for datetime input — real callers pass stringified date columns, so the first real run crashed despite all unit tests passing on synthetic datetime fixtures.

**Fix:** Both functions (and an identically-bugged caller) coerce via `pd.to_datetime(np.asarray(dates))`, robust to string/Timestamp/datetime64.

**Verification:** New regression tests use plain string dates with real object-array shapes, closing the "passes unit tests, fails first real run" gap.

### 28. Portfolio book's `"short"` signal silently zeroed to no position

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `_build_dynamic_sizing_payload()` guard recognized only `{"buy", "sell"}` — never updated when `"short"` became valid, so book-selected shorts sized to exactly zero. Never observed in practice (book feature defaults off).

**Fix:** Guard recognizes `{"buy", "sell", "short"}`.

**Verification:** Covered implicitly by portfolio-book suite plus future end-to-end backtests with book enabled.

### 29. Multi-asset-class support (bonds/futures/options + IB) — explicit non-goals

**Severity:** n/a (scope note) · **Status:** 🟢 `fixed` (core multi-asset-class trading is fully implemented; remaining items are permanent non-goals)

**Problem:** Tracked multi-asset-class gaps after the initial architecture pass — options order placement against a resolved contract, real derivatives-macro data, per-asset-class book slot caps — were originally deferred.

**Fix:** All three resolved later: real option-contract order placement, real futures/options derivatives-macro features (offline and live), and an optional `per_asset_class_slots` book parameter (default `None`, byte-identical to the prior pooled ranking).

**Verification:** Seven new tests for per-class slotting (ranking, exclusion, thin-class isolation, confidence-spread gating, backward compat); the remaining items (ML-driven multi-leg spread selection, IBC headless TWS login, live IB margin, bulk historical derivatives fetch) are permanent non-goals tracked in README Known Limitations.

### 30. `Dockerfile.retraining_worker` missing `data_pipeline/` (and pre-existing: `liquidity/`) copy

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** A top-level `data_pipeline.fred_backfill` import was never copied into `Dockerfile.retraining_worker`, which also pre-existing missed `liquidity/` — either would crash the first retrain.

**Fix:** Both COPYs were added, then the whole class was structurally eliminated by the July 17 consolidation (the Dockerfile is gone; compose builds a consolidated `aether-quant-engine:latest` via `COPY . .`).

**Verification:** Import-graph tracing (#2/#20 method) confirmed directly — the bug class is now impossible.

### 31. Infrastructure/latency pass — `aq test` silently ran a real Lean backtest, per-bar inference hot path never profiled, CI Docker builds never cached

**Severity:** 8/10 (aq test) / 6/10 (inference latency) / 4/10 (CI cache) · **Status:** 🟢 `fixed`

**Problem:** `aq test`'s Lean-backtest file checked binary presence only, so routine runs paid a real (over-an-hour) backtest cost; the inference hot path was unprofiled and CI Docker release builds were uncached.

**Fix:** Opt-in `lean_backtest` pytest marker (excluded by default; `--lean`/`--full` opt-in) plus per-subsystem `aq test` flags, a new `scripts/profile_inference.py` harness, hot-path fixes (causal-conv Python loop → batched `einsum`; four per-expert dispatch calls → one batched), and `cache-from`/`cache-to: type=gha` on the release Docker step.

**Verification:** Collect-only 1132/1143 (11 deselected), non-Lean run >1h → ~73s-4min; a 10k-iteration real-weight workload measured 448.4s→290.6s (-35.2%), with a 200-trial fuzz parity check between the old loop and batched conv1d.

### 32. Latency deep-dive follow-up — weight-array/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension attempt

**Severity:** n/a (optimization pass) · **Status:** 🟢 `fixed`

**Problem:** Re-profiling after #31 showed repeated `numpy.asarray()` conversions of the same static JSON-loaded weights every bar were the largest remaining cost.

**Fix:** `convert_state_dict_arrays()` converts once at load (no downstream API change), batched-stack caching precomputes expert weights in `_ensure_ready()`, and it added `aq profile`, opt-in per-symbol multiprocessing (default off, sequential fallback), and a C++/pybind11 extension (`cpp_inference_ext`) accelerating the batched linear layer.

**Verification:** Measured 448.4s→48.4s (-89.2%; mean 44.8ms→4.83ms per symbol/bar); 14 parity tests prove the cached path bit-identical. A naming-collision bug and a wrong-Python-env install were caught during verification; the multiprocessing win/loss was left to a real backtest and not enabled this pass.

### 33. Execution/risk realism pass — real `SlippageModel` wired to fills

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `build_liquidity_decision()` computed a real spread+impact estimate every bar that nothing consumed — no security had a `SlippageModel`, simulated fills hardcoded zero slippage, and historical backtests had systematically too-good fills.

**Fix:** Pure `slippage_amount()`/`resolve_slippage_bps()`/`resolve_fill_slippage()` in `execution/order_gate.py`, threaded into both the Lean fill path (a new `_LiquidityAwareSlippageModel` adapter) and the simulated-fill path; the cost source and safety clamp were later made config-configurable.

**Verification:** 12+13 new tests (`test_order_gate.py`/`test_simulated_portfolio.py`) including default-vs-explicit-zero parity; the adapter itself is not unit-testable in isolation (the usual `main.py`-outside-Lean constraint), so the logic lives in tested pure functions.

### 34. Real limit-order support — every tradable asset class, config-gated

**Severity:** 6/10 · **Status:** 🟢 `fixed` (`PartiallyFilled` never appears at daily resolution: a standing caveat)

**Problem:** every order was an all-or-nothing `MarketOrder()` / `SetHoldings()` across all five asset classes.

**Fix:** `phase_v2.limit_orders` real `LimitOrder()` support for every class: one submit path, an `on_order_event()` fill callback, per-class timeout with market fallback, and the futures/option bookkeeping bugs found on the way.

**Verification:** pure and CLI tests; 45 real order-event files show submitted / filled / cancelled pairs 1:1 and the extracted pending/timeout functions run live (#98).

### 35. Disabling an asset class never liquidated already-open positions

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Flipping `phase_v2.futures_risk.enabled`/`options_risk.enabled` false mid-run zeroed new sizing but left already-open positions (signal derivation unaware of flags) — sat untouched, silently failing every bar.

**Fix:** Pure `resolve_asset_class_enabled()`/`should_liquidate_disabled_asset_class_position()` + per-bar sweep `_liquidate_positions_for_disabled_asset_classes()` liquidating newly-disabled classes' real/simulated positions; equity/crypto/bond have no such flag.

**Verification:** Truth-table tests for both; parity test: simulated exit matches calling `exit()` directly. One item unverified until a real backtest: reading `Portfolio[...].Invested` at new, earlier point in bar execution order.

### 36. Latency profiling extended beyond inference — `build_market_topology()` found to be a much larger per-bar cost than the entire inference step

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** per-bar subsystems besides inference were never profiled; `build_market_topology()` cost ~500-600 ms per bar, more than whole-universe inference.

**Fix:** `scripts/profile_subsystems.py` / `aq profile --<subsystem>`, and a correlation-stability cache that skips the embedding when pairwise correlations moved less than a (percentile) tolerance; enabled since V5.5.0 (`topology.cache_enabled`, percentile 75).

**Verification:** tests prove no embedding call on unchanged correlations plus every fallback; clean in full Lean runs, reuse counts reported by the timing probe (#129).

### 37. Inference tail latency (p99 3-5x p50) — investigated and fixed

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** p99 inference ran 3-5x p50 and a stale profiling file suggested a regression.

**Fix:** the stale file was unrelated; paired runs isolated GC pauses as the tail, and `gc.freeze()` after model load ships on (`gc_tuning.freeze_after_load_enabled: true`, unfrozen before shutdown for #104).

**Verification:** GC off cuts max latency 66-95% with p50 unchanged; clean across full Lean runs.

### 38. 2-leg vertical spread selection for options — explicit scope-in of a previously-non-goal feature

**Severity:** n/a (feature scope-in) · **Status:** 🟡 `partial`

**Problem:** Multi-leg spread selection was explicit non-goal (#29); this pass closes minimal 2-leg vertical-spread slice.

**Fix:** New `select_vertical_spread_legs()`/`build_vertical_spread_position_sizing()` (net-vega sized), wired through `risk/asset_class_router.py` + new `_apply_option_spread_order()` using Lean's own `OptionStrategies` atomic combo-order primitive (previously completely unused here); two real bugs (field-existence check ordering; early draft breaking option orders entirely for spread case) caught/fixed during implementation.

**Verification:** 20 new tests (leg selection/sizing/degrade paths) + critical zero-behavior-change parity for single-leg path. **Real-backtest verification still genuinely open** — no option/future asset configured in universe yet, so never exercised against real Lean order placement, margin, or partial-fill behavior.

### 39. Final pre-backtest bug sweep — 4 fixes found and fixed before this project's first real `lean backtest .` run

**Severity:** 6/10 (test-harness bug) / 5/10 (liquidity threshold collision) / 3/10 (limit-order timeout) / 2/10 (book-slot crash risk) · **Status:** 🟢 `fixed`

**Problem:** A final pre-backtest sweep found four defects: a wrong dict-key path silently failing three Lean coverage assertions, two liquidity thresholds collapsed to one value (merging a two-tier gate), a limit-order timeout handler contradicting the dependency's "unknown status = still pending" contract, and no shape validation on optional per-asset-class book-slot config.

**Fix:** Fixed the key path, restored the `thin < high_impact` ordering, made the handler pop-without-cancel only on genuinely terminal statuses, and added a `normalize_per_asset_class_slots()` pure validator degrading gracefully on malformed entries.

**Verification:** Six new validator tests; the other three fixes were verified by direct inspection/config check (pre-real-backtest by design), with the suite green after all four.

### 40. `aq backtest` silently re-pulled the ~42.5GB Lean engine image on every run

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `lean backtest .` resolved the mutable `quantconnect/lean:latest` unpinned, so whenever QC moved the tag even machines with the full 42.5GB image cached re-pulled — indefinitely, every clone and run.

**Fix:** Pinned the immutable `quantconnect/lean:17900` by default (always passed explicitly), with `aq backtest --image <other>` for deliberate newer-build opt-in.

**Verification:** Tests confirm pin-by-default plus the working override flag; documented in README Getting Started.

### 41. First real backtest: only 14 trades, none ever closed

**Severity:** 6/10 (blocks a statistically meaningful backtest) · **Status:** 🟢 `fixed` (superseded by #43)

**Problem:** First real backtest produced 14 orders, all openings, zero closes — model's `probability_up` clustered 0.46-0.49 vs buy/sell thresholds 0.50/0.42, almost nothing crossing either line. Secondary finding: soft `max_active_positions` cap (same-bar overshoot counting only already-filled positions).

**Fix:** None here — proposed threshold-tightening lever diagnosed but never shipped. #43 found real causes structural (position-cap overshoot, risk vetoes blocking exits, neutered circuit breaker, no exit mechanism) plus a training-pipeline defect, pivoting trading entirely to `rank_20d`/`portfolio_book`.

**Verification:** Diagnosis only, confirmed against real output files (`state.json`, order-events, logs).

### 42. Pre-live security review — broker/API credentials could be published; DB exposed to the LAN behind a repo-published password

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** A pre-live review found the runbook instructed hand-editing real IB credentials into git-tracked `lean.json`, `.dockerignore` didn't exclude secret files from published images, Postgres/Redis were published to `0.0.0.0` behind a password published in this public repo, and nothing structurally prevented future secret commits.

**Fix:** A credential render step (`aq render-lean-config`) overlays secrets from a gitignored `.env.live` onto a gitignored `lean.live.json` (tracked `lean.json` stays empty), the secret list is mirrored into `.dockerignore`, DB/Redis are bound to `127.0.0.1` with a fail-closed live-mode guard, and `aq secrets-check` plus an opt-in pre-commit hook were added.

**Verification:** New `tests/test_dockerignore_secrets.py` evaluates real Docker pattern semantics (not a literal line-grep); no secret exists anywhere in git history and there is no deserialization-RCE surface.

### 43. Full pre-live model overhaul: trading-logic bugs + training-pipeline bugs, pivot to the one significant signal

**Severity:** 9/10 · **Status:** 🟢 `fixed` (see #52/#54)

**Problem:** A second backtest after #41's recalibration produced bit-identical results (same 14 trades/profit), showing calibration had zero effect on actual trades — causes spanned trading logic (soft position-cap overshoot, sell-vetoing risk logic, a sell threshold ~10σ from live output, a neutered drawdown breaker, no stop-loss/trailing/max-holding-age exits) and training (untrained epoch-1 checkpoints, degenerate threshold search, an MoE blend diluting skill to 0.5, no skill-floor gates, 35/85 static one-hot inputs, ~52-row crypto training, and trading that ignored `rank_20d`/`rank_5d`, the only statistically significant signal).

**Fix:** Rewrote early stopping with a `min_best_epoch` floor, fixed the threshold-search bounds, unified asset-context columns, removed dead features, raised the `min_training_rows`/skill-floor gates, zeroed no-skill experts, wired `portfolio_book` to trade `rank_20d` directly, bypassed the exit veto, added safety exits (max holding age + trailing stop) and an adaptive sell band, fixed the same-bar position cap, re-armed the drawdown breaker, and fixed the crypto/`InteractiveBrokersFeeModel` crash.

**Verification:** Real backtest (2026-07-17) went from stuck-at-14 to 653 orders at 11.1% drawdown (mechanical fixes confirmed; still -4.6%/Sharpe -0.59), with tests extended across `train.py`, gating, `market_analyzer`, `validation_gate`, experts, and `portfolio_book_construction`; superseded by #52/#54's profitable rank-pivot backtest (Sharpe 0.403, Net +10.4%).

### 44. Lean CLI couldn't feed the retraining loop — undocumented second `requirements.txt` convention

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `main.py`'s `ExperienceQueue` silently no-oped during every real `lean backtest .` run because `redis` was missing: Lean CLI auto-installs deps from a project-root `requirements.txt`, separate from the repo's `requirements/requirements.txt` convention Lean never reads, and everything else happened to exist in the image.

**Fix:** A repo-root `requirements.txt` containing `redis>=5.0.0`, cross-referenced from `requirements/README.md`; later superseded by #88a's Lean CLI Windows dependency-mount workaround.

**Verification:** Confirmed by reading Lean CLI's source (`lean_runner.py`), with the real-run re-verification left to the user.

### 45. `av` (Aether-Vault CLI) was broken on this machine — never actually run once in this repo

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `retraining/vault_client.py`'s commit stage shells out to `av`, which failed every call (`ModuleNotFoundError: questionary`) and had never been initialized (`.av/` absent) — invisible because `commit_candidate_to_vault()` degrades gracefully by design.

**Fix:** Installed `questionary` into the correct environment (`av.exe` resolves via a separate user-scoped Python 3.14 install, not the repo `.venv`) and ran `av init --mode local -y --no-repl` in the repo root.

**Verification:** Confirmed via `av status`; local-only is accepted (no remote registry, degrading to a local pending-push queue).

### 46. `xreadgroup(block=0)` meant "block forever," not "don't block" — idle Redis-stream workers timed out every cycle

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/postgres_worker.py`/`audit/postgres_worker.py` called `xreadgroup(..., block=0)` believing it non-blocking, but Redis `BLOCK 0` blocks forever — with a client `socket_timeout=5`, every idle poll raised a timeout exception (invisible to `fakeredis`, which doesn't reproduce blocking-socket behavior).

**Fix:** Removed `block=0` from both call sites; the default `None` omits `BLOCK`, letting the existing correct `sleep(1)` idle loops work.

**Verification:** Real Compose Redis showed both workers at 0% CPU with zero errors; the 18 tests in `test_postgres_worker.py`/`test_audit_postgres_worker.py` pass unchanged (they never asserted on `block`).

### 47. `retraining-worker`'s `./data` volume mount was read-only — `train.py` could never complete inside the real container

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** Compose mounted `./data:/app/data:ro`, but crypto daily-series derivation (#15) must read-then-write `data/crypto/coinbase/daily/*.zip` every invocation, so the container crashed with `OSError: Read-only file system` — never caught before because rehearsals ran `train.py` on the (writable) host.

**Fix:** Changed the mount to writable (`./data:/app/data`).

**Verification:** A rehearsal re-run after `docker compose up -d --force-recreate` completes past this point.

### 48. Force-recreating `retraining-worker` mid-cycle orphaned a stuck `retraining_events`/`model_versions` row — no startup reconciliation existed

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Recreating `retraining-worker` mid-cycle killed the in-flight `train.py` before it reported back, leaving `retraining_events`/`model_versions` rows stuck `"running"`/`"candidate"` so the cooldown check blocked all future retraining; the container also ran `python -m retraining.worker` as PID 1 without an init process, so a subprocess killed on orchestrator timeout could become an unreapable zombie that blocked even `docker compose stop`.

**Fix:** Startup reconciliation `fetch_stale_active_events()`/`reconcile_stale_running_events()` marks stale `running`/`planned` rows `failed` (rejecting still-`candidate` `model_versions` rows) after a configurable `stale_running_timeout_seconds` (default 10800s), and `init: true` gives the Compose service Docker's tini so killed subprocesses are reaped.

**Verification:** Eight new tests across `postgres_registry`, `orchestrator`, and `retraining_worker`, suite green (1465 passed) before/after; the zombie scenario was hit live and manually recovered (`docker rm -f`) before `init: true`, and `docker compose config --quiet` is clean.

### 49. Full end-to-end retraining-loop rehearsal against the real Compose stack — three real cycles ran, all correctly rejected; rollback rehearsed both ways

**Severity:** n/a (operational-maturity verification, not a bug) · **Status:** 🟢 `verified`

**Problem:** N/A — a rehearsal to prove a genuine closed loop rather than mocked-unit-test logic; one follow-up (the `lean` CLI absent from the worker image, so `backtest_gate` silently no-ops rather than crashing) was a known deliberate infrastructure gap, later settled by #62.

**Fix:** None (verification exercise).

**Verification:** Three real cycles ran through the worker poll loop (`plan→train→train_topology→train_gating→train_multitask→train_sequence→validate`), with `train_sequence` timing out once at its 1800s cap (a real resource-constrained-host finding, not a crash); all three candidates were rejected on legitimate quality grounds (consistent with #43), and rollback was tested against real Postgres/files both ways (happy path flips `active`; a corrupted-hash tamper path is refused with nothing copied); `backtest_gate` was never organically exercised (nothing cleared `validate`).

### 50. This dev machine's 4GB RAM couldn't reliably run a real `lean backtest .` — blocked verifying #34/#36/#37/#38

**Severity:** n/a (hardware constraint) · **Status:** 🟢 `fixed` (superseded — see #54)

**Problem:** Four consecutive real `aq backtest` attempts failed at Lean's hardcoded 90-second `initialize()` isolator cap, root-caused to plain top-level imports (torch/pandas/sklearn) taking ~82 seconds under memory pressure (~300MB free on this 4GB host) — not a code regression; it blocked verification of #34/#36/#37/#38.

**Fix:** Narrowed `main.py`'s `from audit import ...` (which transitively pulled unused Postgres/status-export code) to `from audit.redis_queue import ...`, trimming in-window import cost; also documented that failed `lean backtest` containers aren't reliably cleaned up, leaving orphaned `lean_cli_*` containers holding memory.

**Verification:** `python -m py_compile main.py` and the suite were green; superseded 2026-07-20 (#54) when a real backtest completed on the same machine, verifying #34/#36/#37 (~40 min run needing manual zombie cleanup), with #38 still open for an unrelated reason (no option asset registered).

### 51. `GET /api/assets-status` 500'd in Docker — `lean.json` (entry #42's exclusion) was never mounted back in, and the reader didn't degrade gracefully

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `GET /api/assets-status` 500'd in real deployment: #42 excludes `lean.json` from the published image but nothing volume-mounted it back at deploy time, so `build_assets_status_from_disk()` hit an uncaught `FileNotFoundError`.

**Fix:** Added a read-only runtime mount (`./lean.json:/app/lean.json:ro`) on the `engine` service (never baked into the image, preserving #42); the reader now catches `FileNotFoundError` and degrades to an empty `lean_config` so `ib_readiness_status()` reports gracefully instead of 500ing.

**Verification:** New `test_build_assets_status_from_disk_degrades_gracefully_when_lean_json_missing`; all 8 tests in the file pass and the rebuilt container returns 200 with correct content where it previously 500'd.

### 52. The rank-pivot roadmap: trading path switched to `rank_20d`, universe expanded 30→74 assets, four Stage-4 regularization gaps closed

**Severity:** 9/10 · **Status:** 🟢 `fixed` (retrained and backtest-verified — see #54; one caveat still open, below)

**Problem:** Trading path traded the noise-objective direction head (backtest MCC ~0.02-0.04) instead of `rank_20d` — the one genuinely skillful signal — and even that far faster than its ~20-day horizon supports. Gaps: purged-CV configured but never called; no rank-IC early stopping; dead 1-day direction head fully weighted in loss; no seed-ensembling or cross-head consistency regularization.

**Fix:** Five config-gated changes: (1) `strategy_mode`→`long_short`, rank-based sizing enabled, sequence `rank_20d` blended into traded probability, book widened top/bottom 8; (2) 5-bar rebalance scheduler `should_rebalance_this_bar()` matching horizon; (3) universe 30→74 (54% equity/30% bond/16% crypto), dataset rebuilt to 113,804 rows; (4) rank-IC early stopping, dead direction-head loss down-weighted (not removed), seed-ensembling + horizon-consistency regularization in `train_multitask.py`/`train_sequence.py`; (5) previously dead `purged_embargoed_folds()` wired into real diagnostic (`purged_cv_rank_20d`). Also fixed `yfinance_backfill.py` `float()`-on-MultiIndex deprecated pandas fallback.

**Verification:** New functions unit-tested; suite green 1465→1497. Update 2026-07-20 (Codespaces retrain, #53): early stopping fired (best_epoch far off old floor); full-series IC improved — multitask 0.172/t=7.55 (vs 0.073/t=4.40), sequence 0.127/t=5.70. Open caveat: promotion bar (non-overlapping t-stat ≥ 2.0) unmet (multitask 1.40, sequence 0.43). Real backtest (2026-07-20, #54) profitable (Sharpe 0.403, Net +10.4%), confounded by concurrent `bypass_safety_gates` change.

### 53. GitHub Codespaces set up as cloud training offload; a real Alpine-base devcontainer bug found and fixed

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** The 4GB machine spent hours wall-clock on ~800 CPU-seconds of training (#50/#52), and Codespaces setup hit a real bug — the `docker-in-docker` feature silently swapped the pinned Debian image to Alpine, breaking `pip install` against musl libc (matching upstream `devcontainers/images#1114`); deeper, Codespaces containers run unprivileged so Lean/Docker backtests cannot run there at all (a platform limitation).

**Fix:** Dropped `docker-in-docker` (training needs none) and kept only `sshd`, prepended a CPU-only `pip install torch --index-url .../cpu` to `postCreateCommand` (a bare install resolved a GPU-failing CUDA build), and `.gitignore`d 9 inconsistently-tracked generated `ml/` artifacts.

**Verification:** Five systematic A/B Codespace rebuilds confirmed the fix; a full 8-artifact retrain ran <15 min on the fixed Codespace vs 4+ hours unfinished locally, with `git check-ignore -v`/`git status` clean.

### 54. First real `aq backtest` against rank-pivot models: Sharpe -0.59 → +0.40, plus a universe-selection bug (BNBUSD/TRXUSD never listed on Coinbase)

**Severity:** n/a (verification milestone) / 3/10 (ticker bug) · **Status:** 🟢 `verified` / `fixed`

**Problem:** Rank-pivot roadmap (#52/#53) needed real `lean backtest .` confirmation. Separately, two Stage-3 crypto tickers from #52's expansion (BNBUSD, TRXUSD) could never subscribe — Coinbase never listed Binance Coin or TRON pairs, though Yahoo Finance returned price history masking the mis-selection.

**Fix:** Swapped for ETCUSD (Ethereum Classic) and ZECUSD (Zcash), both confirmed present in Lean's local Coinbase symbol-properties database, backfilled via `aq fetch crypto --apply`.

**Verification:** Sharpe -0.59→0.403; Net Profit -4.604%→+10.438%; Drawdown 11.1%→4.0%; Win Rate 47%→58%; rebalance scheduler confirmed working (turnover barely moved despite order count rising — bigger book, long_short trading both sides). Disclosed confound: `bypass_safety_gates` flipped `true` same run, improvement not cleanly attributable to rank-pivot alone — clean-comparison backtest reverted left as manual follow-up. Swap dry-run row-count/date-range checked pre-`--apply`; `config.json` JSON-validated; rebuild confirmed registration with same observation-only classification as other Stage-3 crypto; log confirmed #34's limit orders fire (rounded limit-price log line).

### 55. Every webui tab except `/` 404'd on a direct load when served by FastAPI

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** The webui bundle mounted as `StaticFiles(directory=WEBUI_DIST, html=True)`, and `html=True` maps only directory paths, so a direct load/hard refresh of `/risk`, `/topology`, `/neural-network`, `/tracing`, or `/operations` returned a raw 404 (client-side nav worked, masked in dev by vite's SPA fallback).

**Fix:** A `SpaStaticFiles(StaticFiles)` subclass overrides `get_response()` to fall back to `index.html` on 404, limited to extensionless paths so genuinely missing assets (`/assets/*.js`) still 404 (careful to catch Starlette's own `HTTPException(404)`, not FastAPI's subclass).

**Verification:** Parametrized tests cover all six client routes, the missing-asset-still-404 case, and `/api/*` not being shadowed.

### 56. `train_topology.py` learned prototype z offsets on the pre-V4 `0..1` scale

**Severity:** 1/10 (latent; unreachable until a model exists) · **Status:** 🟢 `fixed`

**Problem:** V4-W3 made z a real `0..100` correlation-distance axis in 3D embedding mode, but prototype z offsets were still emitted on the old `0..1` formula, so the overlay effectively moved nodes in x/y rather than z.

**Fix:** Z is normalized to `[-1, 1]`, with `topology/learned_topology.py::_score_node()` scaling by the active `max_offset_z` before the same clamp as x/y (provably identity-preserving in 2D, proportionally larger in 3D) and an `offset_schema` detection field since no old-format model ever existed.

**Verification:** Byte-identical output vs the old raw formula in 2D, and 60x more z travel under the raised 3D cap. A schema-2 `ml/topology_model.json` (6 prototypes, trained 2026-07-29 from live experience events) later exercised the fix in the first-bar smoke test; retraining the overlay was declined because it fits logged live win/loss events and a dataset proxy would be a different distribution.

### 57. Futures/options had a live incremental-vs-absolute order-sizing bug — fixed, plus position scale-up for all 5 asset classes

**Severity:** 5/10 (dormant, reachable only via `futures_risk.enabled`/`options_risk.enabled`, both default off) · **Status:** 🟢 `fixed`

**Problem:** Equity/crypto/bond add-to-position was blocked by a simple `main.py::_apply_signal()` gate, but futures/options had none — worse, correctly-recomputed **absolute** per-bar targets fired through **incremental** primitives (`MarketOrder`/`Buy`) every bar the signal held, stacking contracts unbounded, and options could orphan a position by re-selecting strike/expiry each bar without closing the old one.

**Fix:** New `risk_controls.py::compute_incremental_order_quantity()` makes futures/options submit only the signed delta toward the absolute target, unconditionally (a genuine bug fix, no flag), with two opt-in tiers: `position_scaling.enabled` scale-up/down with a churn guard and `rotate_on_drift` liquidate-then-reenter.

**Verification:** The default path is unreachable via grep/call-graph trace; tests rose 1521→1558 passing (`test_risk_controls.py`, `test_order_gate.py`), with `main.py` verified by call-graph trace only (it subclasses `QCAlgorithm` and has no direct unit tests).

### 58. Architecturally-sound options: multi-position book, symmetric scale-down, held-contract sizing, spread combo orders (V4.4)

**Severity:** n/a (architecture pass, no defect) · **Status:** 🟡 `partial` (code-complete, ⚪ IB-unverified — no option assets in the universe, no IB key connected)

**Problem:** Review of #57's options paths found six gaps: single-leg options scaled up only, never down; spreads couldn't scale down at all (no `Sell`-side combo primitive); drifted position with `rotate_on_drift` off frozen rather than re-managed; single-slot tracking capped book at one position per underlying; rotation's same-bar liquidate+reenter had no netting; spreads had no limit-order path.

**Fix:** Full multi-position book (`option_positions_by_symbol` as `dict[str, list[dict]]`, capped by `max_positions_per_underlying`, default 1 = byte-identical), pure sizing functions for already-held contracts/legs, Sell-side combo scale-down, combo limit orders; real gap caught during verification and fixed pre-landing (at-cap re-pricing firing even with `position_scaling` disabled).

**Verification:** Default path unreachable — `options_risk.enabled=false` forces vega budget to 0; tests 1558→1591 (`tests/test_options_strategy.py`, `tests/test_order_gate.py`); `main.py` exhaustive call-graph trace only (untestable in isolation); real fill/margin behavior remains IB-unverified.

### 59. Full `OptionStrategies` coverage: all 43 QuantConnect option structures, registry-driven (V4.5)

**Severity:** n/a (architecture pass, no defect) · **Status:** 🟡 `partial` (code-complete, ⚪ IB-unverified)

**Problem:** Only 2 of QuantConnect's 43 `OptionStrategies` factory structures implemented (#57/#58); user wanted full coverage so the model drives any structure gap-free.

**Fix:** Near-duplicate per-strategy functions replaced by `MULTI_LEG_STRATEGY_REGISTRY` data table (all 43, transcribed from real Lean C# source, correcting 2 mistranscribed leg-direction assumptions found en route) dispatched through ~10 shared shape-family leg selectors; `options_margin_sizing.py` for naked/uncovered/bounded-max-loss tiers; `main.py` generalized to `"multi_leg"` record kind; gated behind `multi_leg_strategies_enabled` (default false, byte-identical).

**Verification:** Tests 1589→1656 (registry completeness, all 43 strategies vs synthetic chains, margin tiers, router gating); rewrite verified via trace plus full pre-existing suite unchanged (proves legacy vertical path identical through generalized code); combo surface remains IB-unverified.

### 60. V4.6 — bounded options follow-ups, arbitrage mispricing detector, Forex/FX, analytic bond-ETF duration/convexity

**Severity:** n/a (architecture pass) · **Status:** 🟡 `partial` (forex 🟢 live-verified; the arbitrage detector needs option data and IB)

**Problem:** multi-leg positions were double-counted against the position cap, rotation could thrash, there was no forex asset class or mispricing detector, and this Lean version has no bond security type.

**Fix:** distinct-position counting, a rotation cooldown and same-bar netting, per-asset strategy overrides, `options_arbitrage_detector.py` (off), `risk/forex_risk.py` with pair specs, and analytic bond duration / convexity / DV01 (informational).

**Verification:** tests 1656 -> 1722; forex traded live in two Lean runs (220 fills, notional within 0.15%).

### 61. V4.7 — early-assignment/corporate-action modeling, a learned strategy-selector model, and bond analytics wired into the trained model

**Severity:** n/a (follow-up/architecture pass, no defect) · **Status:** 🟡 `partial` (bond-analytics sub-item now 🟢 fixed — see below; early-assignment detector and strategy-selector model remain default-off/dormant)

**Problem:** Deferred from V4.6: full early-assignment/corporate-action modeling; learned model picking multi-leg strategies; bond analytics as real trained features (previously informational-only specifically to avoid forcing a retrain).

**Fix:** `dividend_backfill.py` (yfinance ex-dividend history + cadence-based next-date projection); Barone-Adesi-Whaley American-exercise pricer; `options_assignment_risk.py` scoring; default-off auto-close sweep; capture path in observation-mode order branch (real-order path never fires without IB); `train_strategy_selector.py`, `inference/strategy_selector_inference.py`, router reranking (active only once model trained/enabled); 3 new bond features (`bond_analytic_modified_duration`, `bond_analytic_convexity`, `bond_dv01`) into `input_set`, computed in both `main.py` and `train.py` offline pipeline.

**Verification:** Tests 1722→1813 (91 new, incl. American≥European price invariant and put-always-zero-assignment-risk invariant); `main.py` trace only. **V5.2.8: "requires retrain before deploy" caveat stale — none needed**: `ml/feature_schema.json`'s 49 `feature_names` byte-identical to current 49-entry `input_set`; `ml/scaler_stats.json` arrays length-49 aligned; `git diff --stat HEAD` zero drift (closed by #70's retrain, verified via backtests V5.2.4-V5.2.7). Early-assignment/strategy-selector remain dormant/default-off — no live signal to verify against.

### 62. Phase 4.8 — closing operational/surfacing gaps: `lean` CLI in retraining-worker, a `main.py` scoping bug fix, new Options & Strategy webui page

**Severity:** n/a (surfacing pass), plus one real bug rated 4/10 (silently wrong data persisted, never a crash) · **Status:** 🟢 `fixed`

**Problem:** A 3-agent audit found `lean` missing from the production image used by `retraining-worker`, the compose `data/reference` mount missing (silently zeroing Forex/futures/FRED specs), `aq` lacking a bulk-backfill dispatcher, stale `aq test` subsystem file lists, and a real bug where `corporate_action_payload` was computed in Pass 1's per-symbol loop but read in Pass 2's separate loop (no block scoping, so every symbol reused the last one's value); several V4.7 fields (bond analytics, assignment risk, dividend schedule, strategy-selector scores) were computed but never reached `state.json`.

**Fix:** Added `lean` to production requirements plus a Docker socket mount, fixed the compose mount/comment, added `aq backfill <target>`, fixed the stale dict and threaded the payload through `pass1_state` per-symbol, wired all 5 fields into `signals[symbol_key]` in `_write_state()`, and added a `/options-strategy` page.

**Verification:** The bug fix was confirmed via call-graph trace plus a full green suite; python tests 1813→1818, webui 13 tests across 2 files, npm build/lint/test clean.

### 63. V4.9 Priority 0 — the #36/#50 profiling wrapper was never reverted: a live per-bar disk write on the hottest path

**Severity:** 6/10 (real continuous synchronous disk I/O on every symbol-bar call in any live/paper/backtest run) · **Status:** 🟢 `fixed`

**Problem:** #36's claim that the `_build_model_input()` wrapper "was fully reverted" (per #50) was false — `main.py` unconditionally opened `model_input_timing.log` and wrote a line every symbol-bar call, ungated, with 45,187 accumulated lines (~983KB) untracked in repo root.

**Fix:** Impl renamed back to `_build_model_input`, wrapper deleted; dead `perf_counter` import removed; log file deleted. Real per-call timing collection remains an open task — `scripts/profile_inference.py`'s in-process harness (no disk I/O) intended path forward.

**Verification:** `py_compile main.py` clean; grep confirms zero references to removed names/file; `main.py` via trace only (unit-untestable by convention).

### 64. V4.9 Priority 4 — `_build_options_chains_payload()`'s gating, considered and declined

**Severity:** n/a (no code change — a documented decision) · **Status:** 🟢 `fixed` (declined by design, no code change)

**Problem:** A candidate optimization to gate `_build_options_chains_payload()` (runs once per bar per configured option asset) behind `self.options_risk_enabled`.

**Fix:** Declined — configuring an option asset is already the deliberate visibility trigger (it feeds `state.json`/webui regardless of multi-leg trading), matching the "compute for visibility even when trading is off" pattern bond analytics/assignment risk follow, and it never appeared as a meaningful profiling cost.

**Verification:** Decision recorded so future passes don't re-investigate from scratch.

### 65. V4.9 Priorities 1-3, 5-8 — sequence batching, topology percentile-tolerance caching, options chain-grouping hoist, non-blocking experience delivery, IPC benchmark, HFT documentation

**Severity:** n/a (feature/optimization pass, all off by default) · **Status:** 🟢 `fixed`

**Problem:** A profiling-roadmap continuation: the sequence encoder cost was paid once per symbol, the fixed topology cache tolerance was poorly calibrated, per-bar options cost was hoistable, live/paper experience-event delivery was blocking, the `ProcessPoolExecutor` IPC assumption was unmeasured, options profiling coverage was missing, and the framing of which latency work is genuine HFT-fork prep was unclear.

**Fix:** Added batched sequence inference (`run_exported_sequence_multitask_model_batched()`, default off, falling back on <2 sequences or any failure), a percentile-based rolling-window tolerance, a hoisted `group_chain_by_expiry()` per routing call, non-blocking `ExperienceQueue.push()` (`async_enabled`, default off), an IPC benchmark confirming `ProcessPoolExecutor` is dramatically slower than sequential on this Windows/spawn machine, an `"options"` workload in `profile_subsystems.py`, and an architecture doc section separating genuine HFT-transfer work from daily-bar-loop speedups.

**Verification:** Tests 1818→1857 (39 new: batching parity, percentile math, chain-grouping parity, async semantics, pool-failure degradation, options workload shape); all new keys grep-verified defaulting `false`/`null` (byte-identical off); `main.py` via call-graph trace only.

### 66. V4.10 — pure-function extraction of `main.py`'s exit logic, 4 webui quality fixes, and 15 new forex/FX assets fetched

**Severity:** n/a (feature/extraction/data pass) · **Status:** 🟢 `fixed`

**Problem:** Exit-decision logic (max-holding-age + trailing-stop) never extracted into a testable pure module unlike comparable decisions elsewhere. Post-V4.9 audit found 4 webui defects: defeated `useMemo` caching, oversized single JS bundle, 2 dead Grafana routes, untested chart/format primitives. Forex — fully wired since V4.6 — had zero live tickers (`aq fetch` had no forex class).

**Fix:** Extracted `evaluate_non_model_exit()`/`compute_position_exit_tracking_update()` into `risk_controls.py`; webui stable empty constants + `React.lazy()`/`Suspense` 3D-bundle split + removed dead routes + chart/format primitive tests; `"forex"` entry in `fetch.py` asset-class config plus bid/ask-synthesizing Lean CSV writer; `forex_pair_specs.json` 7→15 pairs, all fetched full-window (universe 74→89); `forex_risk.enabled` stays off by default.

**Verification:** Extraction byte-identical via static call-graph trace only (`main.py` unexecutable by tests); forex fetch/writer tests use injected `fetch_fn` (zero network); webui suite 37/37 (from 13); npm build/lint/test clean; `python train.py --dataset-only` deliberately **not** run to confirm forex classification — user chose manual training later; `asset_universe.md` marks pairs "Trading (expected)," not confirmed.

### 67. V4.10 follow-up — opt-in live (Lean/IB-calibrated) futures margin source, toggleable via `aq config`

**Severity:** n/a (feature, off by default) · **Status:** 🟡 `partial` (code-complete, genuinely Lean-API-unverified)

**Problem:** `futures_contract_specs.json` carried since V4.6 an explicit "documented future enhancement, not implemented" note asking to prefer IB's live margin over static reference numbers.

**Fix:** Added `phase_v2.futures_risk.margin_source` (default `"static"`), settable via generic `aq config set`. `"live"` mode attaches Lean's local IB-calibrated `BuyingPowerModel` per futures security individually (never global `SetBrokerageModel`), queried via new `_resolve_futures_contract_spec()`; `build_live_contract_spec()`/`resolve_futures_margin_source()` in `risk/futures_risk.py` produce spec interchangeable with the static path; every live-margin call site wrapped in try/except falling back to static/default on any failure.

**Verification:** 8 new tests in `tests/test_futures_risk.py` (26 total): validation, live-spec shape, interchangeability with static path; `main.py` wiring trace-only; never run against a real backtest with a futures position actually sized — genuinely Lean-API-unverified (margin-query API has evolved across Lean versions).

### 68. `cpp_inference_ext` was never built for the actual deployed image — closed via a soft-fail Docker build step

**Severity:** low (silent perf-only gap, not correctness) · **Status:** 🟢 `fixed`

**Problem:** The only compiled extension was hand-built for dev-machine Python 3.14 (ABI-incompatible with the deployed `python:3.11-slim`), and the Dockerfile lacked a compiler/pybind11/extension entirely, so C++ acceleration never ran deployed — a 100% silent gap.

**Fix:** Added a soft-fail `RUN` step installing `build-essential`+`pybind11`, pip-installing `cpp_inference_ext`, and purging `build-essential` in the same layer, wrapped in `(...) || echo ...` so a toolchain/ABI failure degrades to the NumPy fallback rather than breaking the build; a `.dockerignore` block keeps locally-built incompatible binaries out of the published image.

**Verification:** Confirmed in Phase 4.12.3: `docker compose build engine` succeeds and in-image `import cpp_inference` loads the real compiled linkage (`cpp_inference.cpython-311-x86_64-linux-gnu.so`), not the fallback.

### 69. Audit follow-up — `main.py` CI syntax-check gate, and a Windows-specific inference-parallelism slowdown guard

**Severity:** low · **Status:** 🟢 `fixed`

**Problem:** `main.py` had zero CI coverage, not even a syntax check (`AlgorithmImports` is undefined outside a real Lean process), and `phase_v2.inference_parallelism.enabled` was unguarded despite #65 measuring it dramatically slower than sequential on Windows/spawn — with the key also absent from `config.json`, so `aq config set` on it failed rather than silently succeeding.

**Fix:** Added a `python -m py_compile main.py` CI step (parse only; mypy/pyright via `quantconnect-stubs` was declined as too noisy), a `windows_parallelism_slowdown_warning()` that fires `Debug()` only on win32 after real pool construction, a key-specific stderr warning citing the #65 measurement, and an explicit `phase_v2.inference_parallelism: {"enabled": false}` block in `config.json`.

**Verification:** New `test_parallel_inference.py` cases (win32 vs linux/darwin) plus 4 in `test_aq_cli.py` confirm it fires only on this path, only when truthy, and only against `config.json` (not `lean.json`).

### 70. V4.11 — full Codespace retrain + walk-forward executed, three latent `train.py` bugs fixed

**Severity:** n/a (milestone) · **Status:** 🟢 `fixed` (the era-sign question moved to #71)

**Problem:** the first real retrain surfaced forex quote bars dropped by the trade-bar parser, duplicate regime columns on an empty frame, a manifest `KeyError`, and stale forex zips on the Codespace.

**Fix:** quote bars collapsed to midpoints, an empty-frame guard, a `.get()` fallback, and fresh zips re-synced.

**Verification:** rank_20d t 2.03 and CI lower bound +0.0065 (both pass), still blocked by era-sign instability; a 2019-21 Lean run end to end at Sharpe -0.31.

### 71. Phase 4.12 — kill era-sign instability, close remaining non-IB items, expand breadth, alt-data + RL sizing

**Severity:** n/a (milestone) · **Status:** 🟢 `fixed`

**Problem:** promotion was blocked by a COVID-era sign inversion, a crypto-only weekend cross-section contaminated the IC, `average_correlation` was hardcoded 0.0, and alt-data and RL sizing were untried.

**Fix:** per-era diagnostics and an era noise floor, `min_universe_size` 20, the correlation fix, VIX/VXV/NFCI features, a 104-asset universe with scaled caps, and an offline RL sizing layer shipped disabled after a negative result.

**Verification:** t 2.03 -> 2.90, CI lower 0.0065 -> 0.0585; sequence rank_5d promotable for the first time; walk-forward MCC 0.019 (CI entirely positive).

### V4.12.2 — close every webui/CLI integration gap Phase 4.12 left behind

**Severity:** n/a (integration-completeness pass) · **Status:** 🟢 `fixed`

**Problem:** Backend/CLI complete, webui not (~4/10): position-sizing multipliers, newly-promotable sequence `rank_5d` head, per-era diagnostic table, alt-data/bond macro features computed/persisted but never rendered; macro data never reached `state.json` at all.

**Fix:** `DynamicSizing` type + `AssetSizingTable.tsx` labeled chips; extracted `RankingQualityGate` sub-component rendered for all three heads plus per-era table; `state["macro"]` added to `_write_state()` (mirroring derivatives-macro precedent) + new `MacroSnapshotPanel.tsx`; CLI audited — no gaps.

**Verification:** Full pytest 1989 passed (11 errors all pre-existing Docker-fixture, not regression); npm build clean, vitest 46/46; no `main.py`-level test for the macro line per convention — direct code trace; also fixed stale docs across 6 subsystem READMEs missing from Phase 4.12 write-up.

### Phase 4.12.3 — every remaining Docker-dependent item closed, Phase 4 arc complete

**Severity:** n/a (closure phase) · **Status:** 🟢 `fixed` (nothing IB-independent left open)

**Problem:** 4 Docker-outage-blocked items: #68 linkage check, B1 topology training (#56), two user-run backtests, isolator timing at new 104-asset universe.

**Fix:** Root-caused outage to stuck `wslinstaller.exe` wedging `WSLService` — required genuine cold restart (not "shut down then power on," which resumes the same broken session under Windows Fast Startup). Then: confirmed real `.so` linkage in engine image; trained topology overlay first time ever (6 clusters from 4,937 samples, via 3-month observation-mode backtest after repeated full-window OOM crashes forced window shrink); ran observation-mode data-generation backtest + full representative 2019-2021 backtest with drawdown enforcement genuinely active; measured `Initialize()` ~105s at 104 assets (above 90s isolator budget referenced in original plan, completed without isolator-timeout error).

**Verification:** Backtest (full window, `bypass_safety_gates: false`): clean ~31 min, 3,606 orders, no forced-liquidation lock; Sharpe -0.313→-0.145, Net 1.04%→3.41%, Drawdown 8.9%→6.6% — still not significant (PSR 1.84%), fees ($2,769) consume nearly all net profit; RL re-run on fresh datasets reproduced identical negative result (not fluke); standing rule adopted: all model training on Codespace via CLI, never locally, given RAM constraints.

### 72. V5.1 Phase 1's net-edge cost gate blocked 100% of trades — Lean Backtest 1 produced 0 orders end to end

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** The Priority 6.5 net-edge gate re-derived its own pass/fail from raw `net_edge_bps` instead of trusting `build_net_edge_decision()`'s `passes` field, and the "disabled" state still carried `net_edge_bps=0.0`, so with the `aggressive` preset's `min_net_edge_bps: 2.0`, `0.0 < 2.0` evaluated True every symbol/bar and routed every directional signal away from trading — 100% blocked, 0 orders for the whole backtest.

**Fix:** Removed the re-derived comparison and `min_net_edge_bps` parameter from `build_market_analysis_decision()`, which now trusts `net_edge.get("passes", True)`, the single verdict already computed by `build_net_edge_decision()`.

**Verification:** 5 regression tests in `test_market_analyzer.py` assert the exact "disabled" dict shape reaches `"trade"`; the root cause was surfaced by a real backtest (0 orders) since no prior unit test exercised a realistic non-`None` disabled dict.

### 77. V5.1 Phase 1's `min_rank_confidence_spread` gate defeated by its own cross-sectional normalization fix — real Lean Backtest 1 traded but lost money

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `_select_book_group()`'s conviction gate read the cross-sectionally-normalized `predicted_rank_20d` (introduced by the F1 fix, #73) instead of the raw score, and a fixed top-6/bottom-6 selection percentile-ranks to a ~0.90+ spread regardless of dispersion, so the `aggressive` preset's `min_rank_confidence_spread: 0.20` never disengaged the book across the whole 2019-2021 run — Sharpe −0.145→−2.526 and net profit +3.41%→−3.11%.

**Fix:** Added an optional `spread_check_ranks` parameter to `_select_book_group()`/`build_rank_based_book()` that `main.py` builds from each symbol's pre-normalization `raw_rank_score` alongside the normalized `book_candidates`, changing only the engagement gate's input while sizing/confidence still read the normalized value.

**Verification:** 6 new tests in `test_portfolio_book_construction.py` (including one reproducing the bug directly and one proving selection is unaffected); the deferred Lean re-verification was superseded by the real runs recorded from #89 onward (#127 for the latest).

### 78. `tests/test_retraining_worker.py` — 7 of 11 tests spawned a real, unmocked subprocess, adding ~17 minutes to every full suite run

**Severity:** 3/10 (dev-velocity/CI-cost only, no correctness impact) · **Status:** 🟢 `fixed`

**Problem:** 7 tests in `test_retraining_worker.py` patched the first four of `run_once()`'s five best-effort trainer stages but never `train_strategy_selector`, so each spawned a real `subprocess.run()` shelling `train_strategy_selector.py` (~140-168s apiece) — collectively ~1,050-1,200s of a ~28-minute suite.

**Fix:** Added `patch("retraining.worker.train_strategy_selector")` alongside the other stage patches in all 7, matching the file's per-stage mocking convention.

**Verification:** The file re-runs 11/11 passed in 86.8s total (down from >1,050s for the same 7 tests), roughly 15-16 minutes off every future full-suite run.

### 79. `data_pipeline/fred_backfill.py::fetch_fred_series()` hung/reset on every request — FRED's graph-export endpoint requires HTTP/2, which stdlib `urllib` cannot speak

**Severity:** 7/10 (blocked V5.1 Phase 2's CODESPACE RUN 1 entirely — 0 of 12 FRED series fetchable) · **Status:** 🟢 `fixed`

**Problem:** stdlib `urllib.request` (HTTP/1.1-only) could no longer reliably reach FRED's `fredgraph.csv` endpoint — an external FRED-side change, not a regression — so all 12 series failed with read timeouts; a secondary finding was that the prior browser-spoofing `User-Agent` caused an immediate `RST_STREAM` even over HTTP/2, plausibly FRED's WAF cross-checking UA against the TLS fingerprint.

**Fix:** Swapped to `httpx.Client(http2=True)` (adding `httpx[http2]>=0.27.0`) and removed the browser-spoofing `User-Agent` entirely.

**Verification:** Network-mocking tests were rewritten against `httpx.Client` in `test_fred_backfill.py` (31/31 pass) and verified live locally and on the Codespace: all 12 series, including 3 new ones, fetch successfully with full historical coverage.

### 80. `train.py::build_dataset_manifest()`'s new `computed_but_unused_features` (V5.1 Phase 2) flagged ~70 legitimate columns as orphaned on the first real dataset build

**Severity:** 6/10 (would have buried the 3 genuine orphans under ~70 false positives) · **Status:** 🟢 `fixed`

**Problem:** `train.py::build_dataset_manifest()`'s new `computed_but_unused_features` (V5.1 Phase 2) built on the post-scaling dataset but `_computed_but_unused_feature_columns()` excluded only `base_feature_names`/`context_feature_names` — never `scaled_feature_names`, `categorical_feature_names`, or raw OHLCV/bookkeeping columns — so it flagged ~70 legitimate columns as orphaned; tiny synthetic fixtures never included those column classes.

**Fix:** Threaded `scaled_feature_names`/`categorical_feature_names` into the exclusion set and expanded `_NON_FEATURE_DATASET_COLUMNS` with `RAW_COLUMNS` plus `security_type`/`market`/`quality_tier`/`trading_eligible`/`training_eligible`.

**Verification:** A regression test covers all three previously-missed classes, and a Codespace real-dataset build returns exactly the 3 genuine orphans (`futures_term_structure_slope`, `options_implied_vol_skew`, `options_put_call_ratio`).

### 81. `portfolio/book_neutrality.py::apply_book_neutrality()`'s sector-neutral step silently erased entire legs of the live/simulated book

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** sector demeaning drove every member of a zero-dispersion bucket to zero, which is the normal case for equal-weighted roles; the all-forex bucket erased the short leg whenever forex was in it (`mean_names_short=0.00` with `bottom_n=6`).

**Fix:** a bucket within `sector_max_net_weight` is left alone; above it the whole bucket is shrunk proportionally (sign kept) until its net equals the cap.

**Verification:** `tests/test_book_neutrality.py` (12 tests); offline net Sharpe 0.49 -> 0.97 with six shorts; confirmed in every Lean run since #89.

### 82. V5.1 Phase 4's walk-forward net-performance step crashed on window 1 — fed the exported model the wrong feature list (49 raw names instead of the 66 it was actually trained on)

**Severity:** 7/10 (crashed the entire walk-forward run on window 1) · **Status:** 🟢 `fixed`

**Problem:** V5.1 Phase 4's walk-forward net-performance call site passed the outer `feature_names` (49 raw pre-scaling names) instead of the 66-column `model_input_names` the models were actually trained against, crashing window 1 with `ValueError: _conv1d_causal: in_channels mismatch (49 vs weight's 66)`.

**Fix:** Both call sites now use `dataset_manifest["model_input_names"]`.

**Verification:** The exact run that crashed window 1 completed all 6 windows post-fix; no unit test caught it because fixtures used tiny single-feature lists where "raw" and "model input" names were never genuinely distinct.

### 83. V5.1 Phase 4's walk-forward sequence training hits a hard memory ceiling on the project's Codespace machine type for larger training windows

**Severity:** 6/10 (no corruption — degraded cleanly to multitask fallback — but weakened statistical power of 3 of 6 windows) · **Status:** 🟢 `fixed` (root cause found and fixed at start of Phase 5)

**Problem:** Walk-forward sequence training was SIGTERM-killed on windows >~130-147k rows (3 of 6 in CODESPACE RUN 3) while constructing the dense `(rows, 30, 66)` tensor; a partial fix (freeing the parent's held dataset) recovered one window but not the ceiling, root-caused to building the full `sequences` array once and extracting the backtest split ~250 lines later — ~1.08GB resident through the whole training loop on a 7.8GB machine.

**Fix:** Moved the split extraction next to the train/validation splits, added `del sequences; gc.collect()` before training, and switched `evaluation/model_predictions.py::build_sequence_windows()` from float64 to float32 to match `train.py`.

**Verification:** Standalone re-runs on the 3 largest windows (146,868 / 153,696 / 160,219 rows) succeeded first attempt; the summary regenerated at full 6/6 windows, with sequence Sharpe windows 3-5 moving from fallback values (0.91, −0.26, −0.26) to real ones (0.39, 0.62, 1.47), all positive.

### 84. Rank heads were sigmoid-squashed at inference but trained raw against an MSE target

**Severity:** 8/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** Rank heads (`rank_5d`/`rank_20d`/`sector_neutral_rank_20d`) trained raw linear output against a `[0,1]` percentile target, but export wrapped every head in a leftover `"sigmoid"` — compressing live `predicted_rank_20d` into ~[0.475, 0.75], silently tightening `min_rank_confidence_spread` ~4x, capping confidence near 0.5, and zero-sizing bottom-ranked shorts, all invisible to rank-quality gates since rank-IC is invariant under monotone transforms.

**Fix:** Set the export activation to `None` for every rank head and added per-bar cross-sectional percentile normalization at inference (`portfolio/rank_signal.py::cross_sectional_rank_scores()`), since a pure ranking loss makes absolute output scale meaningless by construction.

**Verification:** Manual code/architecture fix (V5.1), no backtest cited.

### 85. `sector_mapping.json` covered 29 of the universe's 104 assets

**Severity:** 6/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** `sector_mapping.json` covered only 29 of the universe's 104 assets — 75 tickers (all 15 forex pairs, most crypto/equities) defaulted `"Unknown"`, making `target_sector_neutral_rank_20d` (a live head with `loss_weight: 0.3`) nearly duplicate plain `rank_20d` for 72% of the universe, while genuinely small sectors NaN'd under `min_sector_size: 3`.

**Fix:** Added a full 104-ticker mapping (GICS-like buckets for equities; `Forex`/`Crypto`/`Fixed Income`/`Broad Market ETF` for the rest), leaving `AAA` deliberately unmapped as a documented ambiguous legacy ticker.

**Verification:** Manual review (V5.1), no backtest cited.

### 86. The constructed book was silently truncated by `max_active_positions`, not by rank

**Severity:** 5/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** `top_n=10 + bottom_n=10` requested 20 names but `max_active_positions=15`, so excess names were rejected in `self.symbols` iteration order — an accident of universe ordering, not conviction.

**Fix:** Presets now set `max_active_positions >= top_n + bottom_n`, and when the cap binds, Pass 2 sorts candidates by rank-confidence so the strongest convictions survive.

**Verification:** Manual code/config fix (V5.1), no backtest cited.

### 87. `capacity_curve()`'s binding-ticker search let a forex pair's fake zero dollar volume dictate the whole book's capacity

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `capacity_curve()`'s binding-ticker search picked the lowest-average-dollar-volume held name, and forex pairs always report `liquidity_log_dollar_volume == 0.0` (Yahoo reports no FX volume), so any forex pair won automatically and produced a sub-$1 `capacity_usd` failing every promotion gate regardless of the rest of the book's real liquidity; a secondary bug was using `np.exp()` where `log1p()`'s inverse is `np.expm1()`.

**Fix:** Excluded exact-zero tickers from the binding search (a true zero is no liquidity signal, not "most illiquid") and fixed `np.exp`→`np.expm1`.

**Verification:** 3 new tests in `test_rank_book_simulator.py` cover zero-volume exclusion, the all-zero fallback, and an exact value distinguishing `expm1` from `exp`.

### 88. A pre-backtest review found six critical bugs in code/config that had never executed a Lean bar

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** the newly enabled net-edge gate, cost model, kill switch and reconciliation had six defects that together locked a half-dead book: long-only edge (every short vetoed), edge calibrated on the 1-day not the 20-day return (~14x too low), no minimum sample for the kill switch's Sharpe, reconciliation against pre-sizing weights, slippage measured as the overnight gap, and a corporate-action payload leaking across symbols; plus a sector cap tighter than the per-name cap.

**Fix:** direction-aware edge, calibration on `target_return_{horizon}d` (28 -> 396 bps per rank unit), `min_bars_for_sharpe`, reconciliation on post-sizing weights within the universe, the slippage trigger parked until a fill-time reference exists, the payload carried per symbol, `sector_max_net_weight` 0.15.

**Verification:** targeted tests in the cost-model, kill-switch, reconciliation and neutrality files; the next Lean runs (#89 onward).

### 89. The book went dead after 3 weeks in the first real V5.1 Lean backtest — two more bugs found and fixed, one root cause still open

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** First real V5.1 backtest (2019-01-01→2021-03-31) opened 4 positions January 2019, closed them ~2 weeks later, then zero orders for remaining 2.2 years (Sharpe −61.3, 8 total orders). Two confirmed bugs: `risk/kill_switch.py::_rolling_sharpe()` numerically unstable on near-zero-variance return windows (mostly-flat post-liquidation returns made `mean/std*sqrt(252)` explode, e.g. ±2.25 swings from noise alone), trip sticky by design; and `min_rank_confidence_spread: 0.2` was a guessed constant the offline simulator hardcoded to `0.0` — never exercised against real data before shipping.

**Fix:** Added `min_return_std_for_sharpe` floor (default 0.0005), composable with existing bar-count guard; added `aq evaluate --calibrate-book-spread`, deriving threshold from real per-date raw-score dispersion via shared `compute_confidence_spread()` — calibrated 0.5014 (vs guessed 0.2/0.18), applied to base config and both presets; also fixed `cmd_evaluate()` bug where `--calibrate-book-spread` alone incorrectly triggered a full `--rank-book` run.

**Verification:** Suite green (2412+ passed); follow-up real backtest confirmed trading resumed/continued 14 months (768-1106 orders) instead of dying at 3 weeks — both fixes effective. Open caveat: calibration (spread clears 0.2 nearly every date) contradicted original "compressed raw scores" hypothesis, so the exact January-2019 cutoff mechanism wasn't confirmed — see #90/#91 for larger gap exposed next.

### 90. A real Lean backtest, once it finally traded continuously, showed Sharpe -4.2 to -4.4 against a +2.18 offline number — three compounding mechanisms found and fixed (V5.2.1)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (V5.2.1; the investigation this entry's own open caveat seeded was continued and closed through #91-#93)

**Problem:** Book traded continuously but Sharpe was −4.42 (gated)/−4.18 (bypassed) vs +0.26 to +2.18 offline. Three compounding mechanisms: (1) offline never modeled ~1-bar execution lag (live fills at next bar's open); live `MarketOnCloseOrder` fix ruled out impossible at Daily resolution; (2) V4.3.0 position-scaling fired resize orders on non-rebalance bars, pushing order count (768-1106) far above offline's rebalance-only assumption; (3) cost gate under-costed resizes vs Lean's real floor-dominated commission (~$0.85-1.09/order).

**Fix:** `simulate_rank_book()` gained opt-in `entry_lag_bars`; new `is_position_resize_permitted()` gates resizing to rebalance bars only; cost gate's `order_value` reflects actual incremental trade delta.

**Verification:** Suite green (2428 passed). Update: follow-up real backtest (2026-08-07) Sharpe −4.421 — essentially unchanged; all three mechanisms empirically ruled out as explanation — see #91 for ground-truth diagnostic tool built next.

### 91. Book-history reconciliation (V5.2.2/V5.2.3) finds two unexplained live-vs-offline selection divergences

**Severity:** 9/10 -> 2/10 · **Status:** 🟢 `fixed` (crypto/FX a log artifact, #97; NVDA/GE/WFC/BA the missing factor files, #100/#102; XOM's residual closed in V6.1.0, #187)

**Problem:** the new `--reconcile-book-history` found crypto/FX in offline's book on 107 of 112 dates and in live's on none, and only 35-55% equity overlap.

**Fix:** `bar_index` counted every asset-class tick (now equity sessions only), an empty book force-sold everything, crypto/FX were not book-eligible, and the bond duration beta was recomputed every bar instead of locked once.

**Verification:** orders roughly halved and Sharpe -4.42 -> -3.35 over V5.2.4-V5.2.5; the remaining ticker divergence was root-caused in #100.

### 92. Deep-dive into the remaining NVDA/GE/WFC/XOM/BA/forex/crypto divergence finds crypto/FX never actually trade, and a systemic live-vs-offline risk-gate gap (V5.2.6)

**Severity:** 10/10 · **Status:** 🟢 `fixed` (V5.2.6)

**Problem:** Crypto/FX were regularly selected but never placed a single real order — forex's synthetic quote-bar conversion hardcodes `volume=0.0`, tripping the liquidity gate's zero-volume block — and live carries ~10 risk/execution gates that offline's Sharpe engine never models, two of them duplicating a signal already an active input feature.

**Fix:** Added `zero_volume_fallback_ddv` (always for forex; for crypto only when `quality_tier=="core"`) to substitute a realistic daily-dollar-volume estimate without bypassing participation/cost gates, added book-selection-aware confidence thresholds, narrowed the `risk_off`/`topology_elevated` overrides using real-data-derived thresholds, and added `aq evaluate --calibrate-confidence-threshold` plus a `book_member_decisions` diagnostic.

**Verification:** 33 new tests, suite 2530 passed; a real backtest (2026-08-10) improved Sharpe −4.103→−2.984. A first attempt crashed on a deferred-write bug (`spread_check_ranks` UnboundLocalError) catchable only via a real bar-to-bar Lean run (fixed, re-run succeeded), surfacing two further bugs — forex sizing and sticky kill-switch lockout — see #93.

### 93. Forex order sizing rounds to zero at realistic book scale, and a sticky kill-switch trip locks out the book for 13+ months (V5.2.7)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (V5.2.7)

**Problem:** `_forex_lot_count_for_weight()` divided notional by full 100,000-unit lot value — at realistic 4-12% weights notional never reached one lot, so every forex order silently rounded to zero. Kill-switch trip 2020-02-27 never auto-cleared, locking 100% of book decisions into `reduce_risk` for remaining 13 months.

**Fix:** New `compute_forex_order_units()` sizes orders in raw base-currency units, not lots (earlier lot-rounding design caught in review — would have reproduced bug under a new name). Split `bypass_safety_gates` into `bypass_sticky_trade_lock`/`bypass_regime_drawdown_gate`; only sticky-lock bypass enabled this round to isolate effect.

**Verification:** 18 new tests; suite 2523 passed. Real backtest (2026-08-11): Sharpe -2.984→-2.17; `notional_ratio` within 0.15% of 1.0 across 193 records; 220 real forex fills across 9 pairs, first time ever. Kill-switch trips 26x, clears every time (vs once, stuck forever). Crypto (BTCUSD/LTCUSD) still never trades — separate unresolved Lean/Coinbase zero-volume delivery quirk, out of scope.

### 94. Kill-switch sensitivity sweep, an offline gate-aware replay, a training-side gate-aware ranking weight (V5.2.8)

**Severity:** n/a (investigation and opt-in tooling) · **Status:** 🟢 `fixed`

**Problem:** was the kill switch's 26 trips in 2.2 years mistuned, and could training see the live gates?

**Fix:** `evaluation/kill_switch_replay.py` (`--replay-kill-switch`, approximate by design) and an opt-in per-date gate-friendliness loss weight (`gate_aware_ranking_weights`); a 20-combination sweep showed the lockout is near-binary, so no config change.

**Verification:** 33 tests; part of the "overlap erosion" was later found to be vetoed dates read as 0% overlap (#131).

### 95. Full-scale production retrain with gate-aware ranking weights promoted to active `ml/` (V5.2.9)

**Severity:** n/a (training round) · **Status:** 🟢 `fixed`

**Problem:** #94's weights had only a 3-epoch smoke test and no flag-off control.

**Fix:** full Codespace retrain with the flag on, promoted to `ml/` (backup kept), plus a 6-window walk-forward; RL sizing stayed disabled (negative a third time).

**Verification:** rank_20d IC 0.152 -> 0.173 and walk-forward net Sharpe ~0.65 (5 of 6 windows positive); V5.6.0's flag-off control showed the IC jump was not the weights' doing (no measurable effect).

### 96. Real limit-order support: stale docs corrected, `PartiallyFilled` made testable, two new offline diagnostic tools (V5.3.1, closes #34)

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified`

**Problem:** `phase_v2.limit_orders.enabled` was actually default-on all along, but `Problems.md`/`Changelog.md`/`execution/README.md`/a `main.py` comment claimed "default off." `PartiallyFilled` had never fired in 45 real backtests; partial-fill logic wasn't unit-testable (not importable outside Lean process).

**Fix:** Docs corrected. Investigated future/option `fallback_to_market_on_timeout=false` asymmetry — deliberate rationale already exists in `main.py` (margin/expiry risk), left unchanged. Extracted `should_clear_pending_limit_order()`/`resolve_limit_order_timeout_action()` into `execution/order_gate.py`, wired behavior-preserving — partial-fill contract unit-testable for first time. Two diagnostics: `evaluation/limit_fill_simulator.py` (`aq evaluate --simulate-limit-fills`) and standalone `scripts/order_events_audit.py`. `max_slippage_divergence_bps` left deliberately uncalibrated (synthetic fill data answers different question than real slippage).

**Verification:** 26 new tests; suite green (combined count see #97). Simulator vs real dataset: 82.95% fill rate, directionally consistent with order-events evidence; audit tool reproduces verified 23/23 pairing across 43 real backtests. #98's 2026-08-14 backtest exercised refactored code live first time: still 12/12, zero regressions. `PartiallyFilled` never appeared — permanent expected caveat (Lean's Daily-resolution fills), not defect.

### 97. Book-history reconciliation: bond duration-beta cold start, reconciliation eligibility, FX/crypto absence a log artifact, kill-switch count corrected (V5.3.1)

**Severity:** 9/10 -> 2/10 · **Status:** 🟢 `fixed`

**Problem:** the bond duration beta locked at 0.0 for ~230 bars because its warm-up floor was 21 instead of the 260-bar history; reconciliation assumed every name eligible; the README's "0 real kill-switch trips" was never measured.

**Fix:** warm-up floor = `long_bar_history_size` (also fixes `cross_asset_sensitivity`'s cold start), eligibility read from the logged universe, a run-segmented presence summary (FX/crypto absence existed only in one old run), and the trip count reported as unmeasurable instead of 0.

**Verification:** 11 tests; the warm-up fix confirmed in a Lean A/B (#98: Sharpe -1.72 -> -1.03, orders halved).

### 98. Real V5.3.1 backtest (2026-08-14): Sharpe improves again; a suspected "7-month disengagement regression" is pre-existing

**Severity:** 4/10 · **Status:** 🟢 `fixed` (closed in V5.3.2 as a genuine low-IC era; its modern form is the rolling-IC gate, #161 / #176)

**Problem:** the run (Sharpe -1.03, 230 orders) seemed to disengage for seven months from 2019-01, but it had been compared against a contaminated multi-run log.

**Fix:** against the true previous run the gap shrank 202 -> 169 days; all four model/head pairs show near-zero IC in 2019-04..09, so the spread gate correctly refuses to trade then (no code change).

**Verification:** gap analysis on both runs' own order events; per-era IC diagnostics in the training metrics.

### 99. Reconciliation tool's own cross-run contamination and live-vs-offline tie-break order fixed (V5.3.2)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (the ticker divergence it pointed at: #100 / #102)

**Problem:** reconciliation deduplicated dates across the cumulative `book_history.jsonl` (160 of 174 dates recur across runs, one in eight) and carried hysteresis across run boundaries; ties resolved in a different order live (universe order) and offline (dataset order).

**Fix:** `segment_logged_records_by_run()` with the latest run by default (`--reconcile-run-index`, `--reconcile-all-runs`), and offline raw scores rebuilt in universe order.

**Verification:** 12 tests; per-run overlap 21-35%; the remaining large raw-score gaps on five tickers pointed to a feature difference (#100).

### 100. Missing Lean split/dividend factor files for 63 of 77 equity tickers — offline trained on unadjusted prices (V5.3.3)

**Severity:** 7/10 -> 2/10 · **Status:** 🟢 `fixed` (confirmed live, #102; the generated files were later found to double-adjust and were repaired, #130)

**Problem:** without a factor file `apply_split_adjustments()` silently kept raw prices, so dividends and the GE spinoff made artificial return dips that live (adjusted by Lean) never saw.

**Fix:** `data_pipeline/factor_file_backfill.py` derives Lean-format factor files from yfinance history (63 written), datasets regenerated, `min_rank_confidence_spread` recalibrated.

**Verification:** 14 tests; the Lean run cut mismatch GE 52% -> 15%, BA 48% -> 12%, NVDA 69% -> 25%, WFC 78% -> 55%.

### 101. `aq evaluate --all`'s non-JSON reporting crashed on Windows — a Greek Δ character isn't in the cp1252 console codec

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** Refreshing README evaluation numbers post-#100 (`aq evaluate --all`, non-`--json`) crashed on Windows with `UnicodeEncodeError: 'charmap' codec can't encode character 'Δ'` — `aq_cli.py`'s delta-print line used a literal Δ, absent from the cp1252 console codec. The crash hit mid-`--all`, after rank-book reporting but before capacity/stress/calibrate-edge and the README refresh, so Windows-console runs silently left those numbers stale, with the error only on stderr.

**Fix:** Replaced Δ with an ASCII `delta_net_sharpe` label.

**Verification:** `py_compile aq_cli.py` clean; `test_aq_cli.py` (216 tests) green; both `--all` re-runs completed end-to-end, refreshing sections stuck since Aug 13.

### 102. Real V5.3.3 backtest (2026-08-17): factor-file fix strongly confirmed live — but the confidence-spread recalibration made real Sharpe worse

**Severity:** 6/10 · **Status:** 🟢 `fixed` (the factor files confirmed; the spread floor re-decided later: 0.1985 in V5.6.0, 0.184 on the live pool, #146)

**Problem:** the run changed one thing on the live path, `min_rank_confidence_spread` 0.5014 -> 0.2831: orders 230 -> 695, Sharpe -1.03 -> -1.80, mostly from trading through the known no-skill eras (2019-04..09, 2019-12..2020-03).

**Fix:** none in code: dispersion measures whether the model differentiates names, not whether it is right, so the spread floor alone cannot gate skill; that became the rolling-IC gate (#103).

**Verification:** reconciliation of the run's own book history: overlap 56.9% (best yet), raw-score delta 0.019, mismatch GE 15%, BA 12%, NVDA 25%, WFC 55%.

### 103. A rolling trailing-IC gate, addressing #102 — built, offline-verified, wired into `main.py`

**Severity:** 6/10 · **Status:** 🟢 `fixed` (on since V5.5.0; window and floor re-decided by R-GATE, #146)

**Problem:** the spread floor traded through no-skill eras because dispersion looked normal when skill was absent.

**Fix:** `portfolio/rolling_ic_gate.py` vetoes engagement on the trailing realised 20-day rank IC from a live buffer of past predictions (torch-free `evaluation/rank_ic_core.py`), with `--calibrate-rolling-ic-floor` and `--replay-rolling-ic-gate`; `min_names_per_date` drops dates with 2-3 names (forced to IC ±1) and `min_resolved_dates_required` is 20 (40 was unreachable).

**Verification:** 51 tests; the replay vetoed 0% of the good era and 22-38% of the bad ones; in Lean (2026-08-19) orders fell 33% and the gate did most vetoes, but Sharpe stayed -1.83, so what it lets through was not profitable either.

### 104. Chronic Lean embedded-Python teardown hang ("endless loop") — fires only after normal completion, never affects results

**Severity:** 3/10 · **Status:** 🔴 `closed` (environmental: the pinned Lean image hangs on a 15-line algorithm; clean on the Codespace host, #204)

**Problem:** after every normally completed run the engine log shows `PythonInitializer.Shutdown()` timing out after 10 s (`Failed to shutdown python`), always after the results were written.

**Fix:** none possible in this code: a shutdown probe found no live Python thread, and the strongest cleanup (slippage models detached, GC unfrozen, containers cleared) still hung; the experiment stays behind `diagnostics.teardown_cleanup` (off).

**Verification:** engine logs (`log.txt`, never the algorithm log); the trivial algorithm in `scripts/lean_teardown_smoke/`.

### 105. Train-vs-live feature-parity audit (V5.3.6) — scaler exact, no live-path formula drift in the OHLCV-recomputable families

**Severity:** n/a (verification pass) · **Status:** 🟢 `fixed` (verified clean; re-opened and closed by #137 / #140 / #141)

**Problem:** the XOM-class divergence needed a per-feature cause or a systematic rule-out.

**Fix:** `evaluation/feature_parity.py` and `scripts/feature_parity_audit.py`: scaler-mapping checks and row-faithful replicas of the base technicals, indicators, momentum, macro proxies and liquidity features, with residual mismatches classified by position (warm-up, date gaps).

**Verification:** 15 tests; on 163k real rows the scaler matches to 7e-13 and fewer than 20 rows (0.01%) stay unexplained; the crypto zero-volume lead was later settled as quote-only zips (#105's note, BT1's bar probe).

### 106. Gate sweep, kill-switch offline finding, promotion-gate null calibration, first Codespace retrain on a synced tree (V5.3.6)

**Severity:** n/a (calibration round) · **Status:** 🟢 `fixed` (every pending decision taken in V5.6.0 / V5.7.0, #142-#146)

**Problem:** which floors and promotion criteria were calibrated, and could the Codespace retrain the full tree?

**Fix:** `scripts/gate_sweep.py` (offline net Sharpe +1.50; a rolling-IC floor of 0.05 doubles bad-era coverage at no good-era cost; dispersion floors bite the good era; the kill switch never trips offline), `promotion_gate_null_calibration.py` (t >= 2 has a 2.75% null rate), `overlap_vs_sharpe_analysis.py`, and a full Codespace retrain over scp (`gh cs cp` upload is broken).

**Verification:** results JSONs under `ml/evaluation/`; V5.6.0 re-ran the sweep on the retrained models and kept the 0.05 floor by its pre-registered rule.

### 107. Null-calibrated era promotion rule (V5.3.7): `era_rule` selector shipped

**Severity:** n/a (promotion methodology) · **Status:** 🟢 `fixed`

**Problem:** #106's "66% of noise runs flip two eras" used coarse buckets; the question was whether the strict era-sign gate is calibrated.

**Fix:** on the gate's own criterion (90-day eras, |IC| >= 0.05) 400 permutations produce no opposite-sign era, so the strict rule is calibrated; `promotion_gate.era_rule` adds `"flip_fraction"` (blocks only above `max_era_sign_flip_fraction` 0.34) next to `"legacy"`, and the V5.3.7 candidate was promoted (owner decision).

**Verification:** 6 tests; promoted multitask book net Sharpe 1.68 offline; the walk-forward blocked by Codespace reboots finished in V5.6.0 (`--resume-run-id`, rank_20d IC 0.101).

### 108. Monte Carlo simulation testing layer — `aq evaluate --rank-book --monte-carlo` with an auto-refreshing README section

**Severity:** n/a (feature) · **Status:** 🟢 `fixed`

**Problem:** risk was shown as one equity path.

**Fix:** `evaluation/monte_carlo.py` (seeded stationary block bootstrap of the book's daily net returns, 1,000 runs), `aq evaluate --monte-carlo`, a README chart with the average run in red and percentile tables, and a webui panel via `/api/evaluation`.

**Verification:** 9 Python and 6 webui tests; first run on the promoted book: return p5 / p50 / p95 -2.0% / +9.4% / +21.5%.

### 109. Deep GitHub Actions testing suite — windows+ubuntu matrix with calibrated coverage gate, ruff lint, vitest in CI, CLI smoke battery, actionlint, workflow meta-tests; non-blocking release visibility (V5.3.9)

**Severity:** n/a (verification-infrastructure round) · **Status:** 🟢 `shipped`

**Problem:** Auditing `ci.yml` found the 100 vitest frontend tests never ran in CI, no Python lint or coverage measurement/gate existed, runners were Linux-only despite Windows being the dev platform (the class of past bugs like #10's float-summation variance), and `release.yml` published to PyPI/Docker/GitHub-Release on tag push with zero test visibility.

**Fix:** Rewrote `ci.yml` into five jobs — `python-tests` (ubuntu+windows matrix, full offline suite with `--cov-fail-under=80` calibrated from the measured 82% total minus two points of slack, coverage artifact from ubuntu), a new `python-lint` ruff job (E/F ruleset calibrated to existing style; 604 pre-existing findings triaged to zero), `webui-tests` now also running `npx vitest run --pool=threads`, a `cli-smoke` packaging-drift battery, and `workflows-lint` actionlint validation. Added a non-blocking `tag-tests` visibility job to `release.yml` (releases proceed regardless, gaps visible on the tag run), 7 meta-tests in `test_ci_workflows.py` pinning all this, and coverage config in pyproject so local matches CI.

**Verification:** ruff clean; full suite 2751 passed / 11 deselected including the new meta-tests (the subsystem-mapping guard itself caught the unregistered test file mid-round).

### 110. V5.3.10 - CI regression fixes (requirements parse meta-test, pinned actionlint single-step) + aq test --ruff flag + main.py extraction batch #1

**Severity:** n/a · **Status:** 🟢 `shipped`

**Problem:** V5.3.10 addressed three items: two CI regressions (a PowerShell-backtick-mangled `requirements-dev.txt` line failing the ubuntu install at 9s, and a two-step actionlint PATH pattern losing the binary between steps), the lack of a fast lint gate, and further `main.py` extraction.

**Fix:** Fixed both CI regressions and pinned them with meta-tests, added the `aq test --ruff` flag (runs ruff before pytest so lint failures fail fast, used by the ci.yml lint job), and extracted `_midpoint_bar_from_quote_bar()`/`_pad_sequence_history()` verbatim into `data_pipeline/bar_synthesis.py` as thin main.py delegations.

**Verification:** py_compile clean; ruff clean; 2757 tests green.

### 111. V5.3.11 - CI python-lint job fixed (bare ruff, no editable-install import chain); duplicate py_compile step removed; pip-audit dependency-CVE scanning job added

**Severity:** n/a (CI infrastructure) · **Status:** 🟢 `shipped`

**Problem:** The `python-lint` job (V5.3.10) used `aq test --ruff`, which imports `aq_cli`→`data_pipeline.fetch`→pandas, but the lint job intentionally runs in a minimal ruff-only environment, so it failed with `ModuleNotFoundError` at ~9s; the same job also held a duplicated "Syntax-check main.py" step.

**Fix:** Reverted to bare `ruff check .` (the minimal lint env is by design; local devs use `aq test --ruff` with full deps), removed the duplicate py_compile step, and added a new `dependency-audit` job running `pip-audit --requirement requirements/*.txt` against runtime and dev deps on every push/PR to catch CVEs before a release tag.

**Verification:** `ci.yml` parses cleanly with 6 jobs; meta-tests updated to match.

### 112. V5.4.1 - RL sizing reward asymmetry fix, regime conditioning, auto-rollback hardening, prediction provenance counters

**Severity:** n/a (model improvement) · **Status:** 🔴 `closed` (RL retrained with the fixes, still no edge over a constant 1.0)

**Problem:** the RL sizing reward was symmetric, so "do nothing" (constant 1.0) was always optimal and the policy learned exactly that three times.

**Fix:** `asymmetric_penalty_weight`, regime trend one-hots in the state, `retraining/rollback_hardening.py` (degradation score, dry-run target selection) and per-session prediction-provenance counters at shutdown.

**Verification:** V5.6.0's retrains with a penalty sweep still lost to the constant on unpenalised backtest P&L (a fourth honest negative); `rl_sizing_enabled` stayed false then.

### 113. V5.4.2 pre-backtest audit — critical missing-import bug found and fixed; parity tests added; config validated

**Severity:** 8/10 (would have crashed forex path + silently killed sequence model on every bar) · **Status:** 🟢 `fixed and verified`

**Problem:** The V5.3.10 extraction of `_midpoint_bar_from_quote_bar()` and `_pad_sequence_history()` into `data_pipeline/bar_synthesis.py` never added the corresponding import to main.py, so the thin delegation bodies referenced unbound names — a runtime `NameError` that `py_compile` and CI both missed since no test imports main.py. The blast radius was a hard crash on the first forex quote-bar tick, a silently dead sequence model every bar, and a permanently-zero `sequence_served` counter.

**Fix:** Added the module-scope import in main.py, 5 parity tests in `test_bar_synthesis_parity.py` registered in `_SUBSYSTEM_TEST_FILES`, and removed a duplicate "Syntax-check main.py" CI step (a V5.3.11 rebase regression).

**Verification:** Full suite 2769 passed / 0 failed; py_compile clean; ruff clean; all 6 pre-backtest config checks PASS.

### 112. V5.4.2 - residual_rank_20d head documented as non-promotable

**Severity:** n/a (signal quality) · **Status:** 🔴 `closed` (the head is noise; it stays demoted)

**Problem:** `residual_rank_20d` never cleared its promotion gate (IC ~0.01, t < 1).

**Fix:** listed as demoted in `config.json`; the retrain validation gate no longer judges it (#139).

**Verification:** V5.6.0's walk-forward: IC -0.002 (95% CI -0.029..0.025); zeroing its loss weight did not beat the seed spread.

### 114. V5.4.4 - CI python-lint red since V5.4.3; Monte Carlo README PNG showed only the average; HRP single-sided books silently halved

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** two ruff findings had kept `python-lint` red; the test suite overwrote the real Monte Carlo PNG (and the test badge) with fixture output; `build_hrp_allocation()` gave a single-sided book only half its gross; a zero close made a -100% return in HRP's covariance.

**Fix:** ruff findings removed; the chart renders only for the real README and the badge writer is mocked in that test; single-sided books get the full gross on their one leg; any pair touching a non-positive close is skipped.

**Verification:** regression tests for each; suite 2816 passed, ruff clean.

### 115. V5.4.4 - installed `aq` console script broken for `evaluate`/`audit`; mean-reversion baseline was a placeholder

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `pyproject.toml` packaged only `risk`/`execution`/`data_pipeline`, so the installed `aq evaluate` raised `ModuleNotFoundError` (masked by the repo root on `sys.path`); `mean_reversion_baseline()` accrued a hardcoded placeholder, so its Sharpe was always 0.

**Fix:** the missing packages and `generate_evaluation_report` added to the packaging lists; the baseline accrues real next-day returns.

**Verification:** `aq evaluate --benchmarks` from the installed script; two baseline tests; suite 2834 passed.

### 116. V5.4.5 - pre-backtest audit: round-trip commission undercounted 2x in the net-edge gate; paper mode ignored every risk lock

**Severity:** 6/10 · **Status:** 🟢 `fixed` (the IB paper part is deferred with the IB items)

**Problem:** `estimate_round_trip_cost_bps()` charged one side's commission for a round trip, so live let through trades the simulator would not; `resolve_order_permission()` checked the risk locks only in live mode, so a tripped kill switch could not stop paper orders.

**Fix:** each side pays `max(rate, dollar floor)`, twice; paper mode requires healthy risk locks (`paper_orders_blocked_risk_lock`).

**Verification:** cost-model and order-gate tests; suite 2858 passed.

### 117. V5.4.5 - NaN propagation family: NaN skipped safety triggers, poisoned fill prices, reconciliation reported false-clean, NaN ranks bypassed the spread veto

**Severity:** 7/10 latent · **Status:** 🟢 `fixed`

**Problem:** every guard in the family was a one-sided float comparison or an `is not None` check, all pass-through for NaN.

**Fix:** finite-or-None normalisation of the kill switch's inputs and its rolling Sharpe, non-finite prices degrade to zero slippage, reconciliation fails closed on non-finite weights, an explicit `non_finite_cost_estimate` reason, a finite-rank eligibility guard in book construction, a skipped non-positive gross cap and a re-clamped minimum position weight.

**Verification:** 24 tests across the seven modules.

### 118. V5.4.5 - HRP equal-weight fallback broke dollar-neutrality on asymmetric two-sided books

**Severity:** 4/10 (dormant under the shipped `allocation_method: "rank"`, but live the moment the planned `"hrp"` flip happens early in a run when history is thin) --- **Status:** 🟢 `fixed`

**Problem:** Both fallback paths in `build_hrp_allocation()` (<2 names with usable history; scipy exception) divided gross across both legs combined (`gross / len(longs + shorts)`), so a two-sided book with unequal legs (e.g. 6 longs / 2 shorts) came out +0.75·gross / −0.25·gross instead of dollar-neutral, contradicting the function's own docstring; the main HRP path normalized per leg correctly and existing tests only pinned symmetric cases.

**Fix:** One shared `_equal_weight_fallback()` using the same leg-total convention as the HRP path (computed once at the top, shared by all three paths), with new tests for asymmetric thin-history, linkage-exception, and single-sided books.

**Verification:** New tests green; full suite 2858 green.

### 119. V5.4.5 - V5.4.1's RL asymmetric-penalty reward fix was dead code at its only production call site

**Severity:** 3/10 (RL sizing overlay is default-off and not part of the current backtest, but every future retrain would have validated a model trained under the OLD symmetric reward while the changelog claimed otherwise) --- **Status:** 🟢 `fixed`

**Problem:** `compute_action_reward()`'s `asymmetric_penalty_weight` (V5.4.1) was dead code at its only production call site — `build_bandit_rows()` never accepted or forwarded it and `main()` never loaded it from config, so real training used the exact symmetric reward whose failure mode motivated the fix; only `test_rl_sizing_v541.py` exercised it via explicit kwargs.

**Fix:** Added `phase_v2.rl_sizing.training.asymmetric_penalty_weight` (default 1.0, byte-identical until set), loaded in `main()`, threaded through `build_bandit_rows()` into `compute_action_reward()`, and recorded in `training_metrics_payload` for provenance.

**Verification:** New tests prove the threading changes rewards (the dead-config regression) plus reward-level asymmetry; full suite 2858 green.

### 120. V5.4.7 - one NaN event could permanently wedge the Redis->Postgres pipeline; torn JSON writes 500'd the API

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** a bare `NaN` passed Redis and then failed PostgreSQL's JSONB insert, rolling back and stranding every batch that held it; status files were truncated-then-written, so a racing reader got HTTP 500s.

**Fix:** `json_safety.py` (finite sanitising serialiser, atomic writes, lenient reads) for both producers and every status writer; the Postgres workers persist the clean prefix and dead-letter a poison row (the audit chain stops at the first one so it cannot fork), while an outage still leaves everything pending.

**Verification:** `tests/test_json_safety.py` plus worker poison-batch and outage tests; suite 2929 passed.

### 121. V5.4.7 - gating blend deflated magnitude/volatility by missing-head weight mass; NaN confidence scored as perfect

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `_weighted_blend()` did not renormalise when an expert lacked a multitask head (volatility ~25% too low, positions oversized); `_clamp01()` turned NaN into 1.0, clearing the trade gate.

**Fix:** the blend divides by the contributing weights; non-finite clamps to 0.0; `_performance_score()` keeps a real 0.0; the interpreter's layernorm has an eps floor.

**Verification:** tests in `test_v547_bug_hunt.py` and `test_gating_network.py`.

### 122. V5.4.7 - retraining gates compared against fake zeros: missing files deadlocked promotion, NaN passed every gate

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `validation_gate.py` defaulted missing metrics to 0.0, which deadlocked promotion when the active side's file was missing and passed vacuously when the candidate's was; NaN failed no one-sided comparison.

**Fix:** required candidate metrics are finite-or-None and fail closed with an explicit reason; a missing active baseline fails `active_baseline_metrics_missing`; `backtest_gate` treats non-finite returns as no edge.

**Verification:** fail-closed tests in both directions in `test_v547_bug_hunt.py`.

### 123. V5.4.7 - data-pipeline corruption class: Yahoo NaN frames written as bars, FRED cache destroyed by a narrow refetch, config.json truncation

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** rate-limited Yahoo responses wrote NaN rows as bars, yfinance's exclusive end never fetched the last day, a narrow FRED refetch replaced the whole cache, `aq fetch --apply` could truncate `config.json`, and two liquidity guards divided by zero or lowered cost below the ceiling.

**Fix:** NaN frames dropped, `end + 1 day`, merged FRED caches, atomic config and cache writes (`json_safety`), conservative liquidity blocks and an explicit error for an empty sequence history.

**Verification:** regression tests in `test_v547_bug_hunt.py`.

### 124. V5.4.7 - auto-rollback/promote artifact verification gaps; Telegram watermark freeze; worker startup crash-loop

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** promote copied artifacts without verifying them, a rollback to an empty version "succeeded", a null JSONB field froze the Telegram watermark forever, and a Redis-down ping crash-looped both Postgres workers.

**Fix:** `verify_version_artifacts()` before any promote, `no_artifacts_found` and a version-id charset check on rollback, junk-tolerant alert formatting that advances the watermark, and a startup that warns and reconnects.

**Verification:** promote, rollback, Telegram and startup-outage tests.

### 125. V5.4.7 - `aq` help surfaces drifted: stale `--all` text since V5.4.4; README missing five flags; CI covered 2 of ~23 help screens

**Severity:** 3/10 (docs/tooling trust, not capital) --- **Status:** 🟢 `fixed`

**Problem:** `aq evaluate --all`'s help text was stale since V5.4.4 (benchmarks had joined the bundle), the README's `aq train`/`aq evaluate` synopses were missing six shipped flags, CI's cli-smoke job exercised only two help screens, and ci.yml's `ruff` install was unpinned (new ruff releases could change CI independently of repo changes).

**Fix:** Updated the `--all` help and code comment and documented all missing flags with per-flag bullets; added `tests/test_cli_help_surface.py` (parametrized exit-0 `--help` across every parser leaf plus a two-directional README↔`build_parser()` flag-sync guard) and pinned `ruff==0.16.4`; reinstalled the editable `aq` per the #115 packaging rule.

**Verification:** 36 new meta-tests green; full suite 2929 green; ruff clean.

### 126. V5.4.10 - 34% of backtest data requests failed on missing crypto quote zips

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Lean's `AddCrypto` requests a quote feed too and the pipeline wrote only trade zips; only the traded LTCUSD mattered (`main.py` never reads crypto quote bars).

**Fix:** `aq backfill yfinance --quotes` synthesises zero-spread Lean crypto quote zips from the trade zip (real bid/ask rows kept); LTCUSD first, the observation-only pairs in V5.6.0.

**Verification:** 6 tests in `test_yfinance_backfill.py`; the data monitor no longer reports them.

### 127. 2026-08-27 backtest written up: Sharpe -2.51 against an offline +1 — what the run actually traded (V5.5.0)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (decomposed and fixed by #128-#134)

**Problem:** the run (Sharpe -2.51, -4.25%) did not trade the offline book: equity long ~2.5% of NAV, forex short 13% and -$3.0k, 135 of 171 equity entries outside the book, 16 bps equity fees and 115 overlapping orders.

**Fix:** `evaluation/backtest_audit.py` (`aq evaluate --audit-backtest`), which made the decomposition repeatable; Lean's Sharpe also subtracts a risk-free rate the offline tools do not (-1.16 without).

**Verification:** 21 tests on synthetic runs; the 2026-10-07 run after the fixes: Sharpe -1.05 (+0.17 without risk-free).

### 128. Offline/live execution parity: ten divergences between `aq evaluate` and `main.py`, fixed (V5.5.0)

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** live traded the legacy probability signal outside the book without a budget, shrank book weights ~8x through the multiplier chain, sized forex by margin (several x NAV), stacked duplicate limit orders, lost hysteresis memory on a veto, never saw its own fills in exit tracking, overcharged fill slippage and decided forex/crypto on the previous bar; the offline simulator used another head, cap, gate set and weighting.

**Fix:** a legacy sleeve budget (`portfolio/legacy_sleeve.py`), a book-weight floor, forex capped to its book weight with its own short budget, one order per symbol, the formed book remembered through a veto, exit tracking that adopts held positions, per-side fill slippage, and `aq evaluate --as-live` (`evaluation/live_parity.py`) mirroring the live decisions.

**Verification:** wiring tests against an `AlgorithmImports` stub (`tests/test_main_wiring.py`) plus 93 round and parity tests; the 2026-10-07 run showed no overlapping orders, forex shorts within cap and equity fees 5.7 bps.

### 129. Crypto never traded: one global 0.45 volatility cutoff made BTC/LTC permanently "elevated"; teardown and timing probes added (V5.5.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` — crypto trades (16 trades) and the probes were read once (cleanup changed nothing for the teardown hang, which stays open as #104)
**Problem:** `ELEVATED_VOLATILITY_THRESHOLD = 0.45` (annualized) sits below crypto's own distribution — **77% of crypto samples in the backtest window exceed it** (85% over all history; p80 0.87 / 1.11) — so the analyzer's Priority 3 cancelled 13 of the 26 BTC/LTC book selections (the 08-27 run); zero-volume blocked only one. Separately #104 (teardown hang) and #63 (no real per-call timing) were still unresolved, and the hang happens with `alive_threads=[]`, i.e. outside Python.
**Fix:** `phase_v2.topology.elevated_volatility_threshold` accepts `{"default": 0.45, "crypto": 0.87}` (`resolve_elevated_volatility_thresholds`; `aq evaluate --calibrate-volatility-threshold` derives the per-class percentile). New `performance_probe.py` (stdlib-only): opt-in `TimingProbe` (one `timing-probe:` line at shutdown), `collect_teardown_diagnostics` (OS thread names, GC counts), `release_symbol_containers` (opt-in pre-shutdown cleanup experiment: clear per-symbol containers, `gc.unfreeze()`, collect), and a `crypto-bar-probe` for the first bars per crypto symbol. All default off in code, switched on in `config.json` for the final run only.
**Verification:** 6 calibration + 6 probe + resolver/topology tests. #104's verdict must come from the **engine** `log.txt` (`PythonInitializer.Shutdown(): ended`), never the algorithm log.

### 130. 62 equity factor files were applied on top of already-adjusted data: prices x0.05 (AMZN), dividends counted twice (V5.5.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (dataset and models rebuilt from single-adjusted zips, #156 / #162)

**Problem:** #100 wrote factor files for zips the yfinance backfill had already split- and dividend-adjusted, so prices were adjusted twice (AMZN $84 -> $4) and per-share fees cost 16-49 bps a side.

**Fix:** `factor_file_backfill.py --audit` / `--repair-adjusted-zips --apply` remove the files (backup kept) and generation skips backfill-written zips; a sentinel-only file must never replace one (Lean then serves no data until 2050).

**Verification:** 11 tests; the next engine log listed only the genuine `AAA` under numerical precision.

### 131. Four latent defects found by the new guards (V5.5.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** (1) the wheel omitted `monitoring`, `topology`, `liquidity`, `experience` and `risk_controls`, so `aq assets`, `--replay-kill-switch`, feature-parity and the paper-readiness report raised `ModuleNotFoundError` on any non-editable install; (2) `scripts/feature_parity_audit.py`'s synthetic check was **silently dead** — a swallowed `SKIPPED` still printed PASS; (3) `compute_factor_exposure()` averaged residuals only (~0 by construction), so its alpha metrics were always 0.0; (4) `--reconcile-book-history` read a vetoed live rebalance as 0% overlap and its hysteresis replay ignored the veto.

**Fix:** The five `pyproject.toml` entries plus `tests/test_packaging_modules.py` and a real-wheel `scripts/wheel_smoke.py`; the audit's date alignment, a real replica call and `--synthetic-only` (fails when the check did not run); alpha = intercept + residuals; vetoed dates flagged and excluded, with `--hysteresis-survives-veto`.

**Verification:** The smoke script passes on a real wheel (0 import / 0 help failures across 23 subcommands); 22/22 synthetic feature families match `train.py` to 3e-18; regression test per item.

### 132. V5.5.0's first backtest attempt crashed on bar 1: Lean's star import shadows `time` (and a second trap hid behind it)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (verified: the re-run, `backtests/2026-10-07_15-39-04`, completed in 2840 s)

**Problem:** `backtests/2026-10-07_15-19-36` stopped after 11 seconds with `type object 'datetime.time' has no attribute 'perf_counter'` at `_ensure_ready`: `from AlgorithmImports import *` exports Lean's `time` (`datetime.time`), shadowing the stdlib module `main.py` imported for the timing probe. The wiring tests never ran `_ensure_ready()` and their stub did not export `time`, so 3132 green tests could not see it. The same run's engine log carried the worse trap in #130 (sentinel-only factor files moved ~62 tickers' data start to 12/30/2050).

**Fix:** `main.py` uses `from time import perf_counter as _perf_counter` after the star import; the wiring stub exports `time = datetime.time`; `tests/test_main_ensure_ready_smoke.py` runs the real `initialize()`/`_ensure_ready()` (skipped on a fresh checkout), a structural test forbids `time.<attr>` in `main.py`, and #130's repair now removes the files.

**Verification:** Mutation-checked (reintroducing `import time` fails the smoke test with the identical message); a static check confirmed every `self.<attr>` read is assigned somewhere. Lesson recorded in AGENTS.md: read the engine log of any run, even a crashed one, before declaring the failure understood.

### 133. 2026-10-07 backtest (V5.5.0 first full run): Sharpe -4.55, 230 of 355 trades closed within 2 days, crypto and most forex blocked

**Severity:** 9/10 · **Status:** 🟢 `fixed` (verified in the re-runs, #134)

**Problem:** every sell was exempt from the cooldown so the legacy signal flipped positions within a day, book positions fell to the legacy signal during a veto, market and limit orders stacked in one bar, and the liquidity gate read crypto/forex volatility as spread (no crypto trades, most forex simulated).

**Fix:** only forced exits skip the cooldown, book-owned positions are held through a veto (`hold_owned_positions_on_veto`), a second entry waits for an in-flight order, and the spread proxy is capped per class.

**Verification:** 14 tests in `test_v550_backtest_findings.py`; the re-run had no stacked orders and crypto traded.

### 134. Re-entries were force-sold the next day: the closing fill never cleared the exit-tracking state (V5.5.0)

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** a close fills a bar late, so exit tracking never saw the position go flat and the next entry inherited the old entry bar and peak, then was force-sold by the age exit or trailing stop the next day (154 of 196 re-entries).

**Fix:** `compute_position_exit_tracking_update(..., clear_stale_state=True)` clears a flat symbol's stale state.

**Verification:** pure and stub-driven tests; the 19:28 run had no trade under 2 days (mean hold 24 days), Lean Sharpe -1.05.

### 135. Feature reconciliation of the 2026-10-07 run: live features diverged from `full_dataset.csv` (V5.5.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (#137, #140, #141)

**Problem:** `--reconcile-features` on XOM and NVDA differed on 16-20 of ~52 features almost every day: price-level features from the double-adjusted dataset (#130), cross-asset features from a timing difference.

**Fix:** the tick order (#137), Lean's forex fill-forward calendar (#140) and two missing FRED drivers (#141); dataset regenerated and models retrained.

**Verification:** BT1's snapshots against the new dataset left only the four `sens_*` features, which predated the FRED fix.

### 136. CI on `main` red since the V5.5.0 push: 29 `NameError: Slice` errors, README links into gitignored READMEs, 43 gitleaks findings (V5.6.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Python 3.11 evaluates `main.py`'s `Slice` annotation at import (3.14 does not), the README linked gitignored READMEs, and gitleaks read exported-model `*_key` tensor names as credentials.

**Fix:** the stubs export `Slice` and an AST guard catches new import-time Lean names, the three READMEs are un-ignored and the link test fails on ignored targets, and `.gitleaks.toml` allowlists exactly the tensor-name lines.

**Verification:** mutation-checked guard tests; gitleaks 43 -> 0 findings (a planted key still fails); CI green since V5.7.1.

### 137. Feature divergence #135 solved: live built cross-asset features one tick behind the dataset (V5.6.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `main.py` builds the topology, peer, macro and momentum-rank payloads before the tick's bars join the windows, so live(D) equalled the dataset's D-1, and training also saw crypto's same-day bar (a lookahead).

**Fix:** `features/cross_asset_timing.py`: one window-to-inputs construction for `main.py` and a `CrossAssetTimeline` that replays the live visibility rule offline from raw per-ticker history (equity visible at the close, crypto/forex at the next midnight).

**Verification:** `tests/test_cross_asset_timing.py` replays `main.py`'s tick order to 1e-12; BT1's live NVDA/XOM snapshots match on every cross-asset and price feature.

### 138. Crypto fills paid $0 fees: Lean's default crypto fee model charges nothing (V5.6.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `add_crypto(..., Market.COINBASE)` does not bring a fee model, so every crypto fill carried $0 fees and the net-edge gate assumed IB's equity commission.

**Fix:** `costs.fee_by_type.crypto` assigns Lean's `CoinbaseFeeModel()`, the net-edge gate charges each class its own fee, and the simulator gets the same per-ticker rate.

**Verification:** cost-model, simulator and wiring tests; BT2 realised 46.7 bps per crypto fill, unchanged through BT7.

### 139. Training-pipeline and tooling defects fixed before the V5.6.0 retrain

**Severity:** 6/10 · **Status:** 🟢 `fixed` — unit-tested; the retrain itself is recorded in the entries that follow

**Problem:** Six defects blocked the V5.6.0 retrain: `validation_gate` judged the never-promotable `residual_rank_20d` head (rejecting every candidate); `train_rl_sizing.py` compared its penalised policy against an unpenalised constant with no way to pick the penalty; a VM reboot at walk-forward window 5 lost the run three times; `--reconcile-book-history` loaded all 251 dataset columns and re-ran the model per head (~1.3 GB, killed on this PC); `overlap_vs_sharpe_analysis.py` collapsed runs sharing a sim window; and topology cost 332 ms/call, 87% of it pure-Python Pearson loops.

**Fix:** The ranking gate now reads `ranking.heads` (`rank_5d`/`rank_20d`, passes if any clears); `policy_beats_constant_unpenalized` + `--penalty-sweep` on a chronological holdout; per-window `window_result.json` + `train.py --resume-run-id`; `predict_heads()` + `row_mask` + chunked column-pruned reads (~0.5 GB); per-run points; numpy correlation matrix with a scalar fallback (1.16 s → 0.16 s for 104 symbols, exact to 1e-12).

**Verification:** Tests per item (`test_validation_gate`, `test_train_rl_sizing`, `test_walk_forward_multimodel`, `test_model_predictions`, `test_overlap_vs_sharpe_analysis`, `test_market_topology`).

### 140. Lean fills forward forex bars: live windows hold flat Sunday bars the dataset never had (V5.6.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** Lean emits a flat forex bar for every open day without data (Sundays, a missing weekday), so live forex windows carried zero-return days and topology strength matched live on only 32% of NVDA dates.

**Fix:** `fill_forward_open_forex_days()` builds the same calendar in `CrossAssetTimeline`, and `train.engineer_forex_features_on_lean_calendar()` computes forex features on it while labels stay on real bars.

**Verification:** a replay test with an independent Lean-style fill; NVDA topology strength 32% -> 96% exact.

### 141. Two FRED sensitivity drivers existed only on the Codespace: 4 model features were 0 live and real in training (V5.6.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed` — files pulled local; the next backtest must show the four features non-zero
**Problem:** `sens_real_rate_beta/interaction` and `sens_dollar_beta/interaction` are regressions on the FRED series `treasury_10yr_real` and `dollar_index`, which `data/reference/fred_series/` on this PC never had (nor `breakeven_inflation_10y`); only the Codespace copy did. Every dataset built there trained on real values; every Lean run (and `aq evaluate`) read empty series and fed 0.0. BT1's snapshots showed it directly (live 0.0 vs offline 0.1456 on all 45 dates for both symbols) once everything else matched.
**Fix:** the three CSVs copied to the local `data/` (now identical to the Codespace's file list: 1302 files each way). A silent per-driver zero is a skew by construction, so the drift check is the reconcile tool: after the next backtest `aq evaluate --reconcile-features` must list no `sens_*` feature.
**Verification:** file lists diffed both ways; the `sens_*` rows of BT1's reconciliation are the before-picture.

### 142. Backtests of the V5.6.0 models: BT1 (diagnostic, 2020-H1), BT2 and BT3 (full 2019-21) (V5.6.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** did the retrained models and the data fixes improve Lean, and what does forex earn?

**Fix:** forex trading switched off (`forex_risk.enabled` false; forex still feeds features): it lost money after fees in both runs because IB's $2 minimum is ~8 bps a fill on 2.6%-of-NAV positions.

**Verification:** BT2 Lean Sharpe -0.95 (+0.54 without risk-free), BT3 -0.76 (+0.81), net +2.61%, drawdown 1.4%; crypto paid 46.7 bps a fill (#138 verified); 90% of snapshot dates agree on all 52 features.

### 143. What costs the as-live book its Sharpe: lever attribution, a forex-slot defect and four rule-driven changes (V5.6.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (confirmed in Lean, #144)

**Problem:** `scripts/as_live_levers.py` changed one live mechanism at a time: the elevated-topology veto on book members cost 0.70 Sharpe; disabled forex still won book slots; the equity spread proxy exceeded its own 25 bps cap on 62% of days (118 BT3 decisions liquidity-blocked).

**Fix:** by rule: no topology veto for book members, disabled classes kept out of the book (`book_candidate_trading_eligible`), edge 396 -> 574 bps per rank unit, the slippage trigger at 80 bps (p99 x 1.5), an equity spread cap of 0.001.

**Verification:** as-live Sharpe -0.38 -> +0.78 offline; book overlap with Lean 77% on BT3 (0.31 before).

### 144. BT4: the round-3 changes in Lean (V5.6.0 final run, `backtests/2026-10-09_22-13-03`)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (the kill-switch throttle and the spread-floor recalibration followed in #146)

**Problem:** did #143's changes hold in Lean?

**Fix:** none needed: decisions reaching `trade` 71 -> 321, liquidity and topology blocks 0, net-edge blocks 1.

**Verification:** Lean Sharpe -0.04 (+0.66 without risk-free), net +4.73%, drawdown 2.8%; the simulator was ~2x optimistic on return but ranked the changes right.

### 145. The offline simulator modelled almost none of Pass 2 and its gate took 15 minutes: rebuilt on main.py's own functions (V5.7.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** the as-live simulator skipped the kill switch, sizing chain, liquidity and net-edge gates, HRP and per-name impact, charged impact on a $1M book, and each rolling-IC gate took ~12 minutes.

**Fix:** `evaluation/rolling_ic_series.py` (one state per date, shared by every floor) and `simulate_rank_book` driven by `live_parity`'s builders of the live pure functions, impact at the real NAV, the spread calibration on the live pool, `--audit-fills`.

**Verification:** with observation-only rows kept, backtest +0.66 / +4.2% against Lean BT4's +0.66 / +4.7%.

### 146. Gate research on the rebuilt simulator, both splits: one rule-driven flip, five rejected, the kill switch kept (V5.7.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (confirmed in Lean by BT5, #148)

**Problem:** the kill switch was the main throttle, the spread floor had been calibrated with forex in the pool, and the rolling-IC gate vetoed 157 of 281 rebalances.

**Fix:** by R-GATE on both splits: IC gate window 80 / floor 0.0, spread floor 0.184 on the live pool, legacy cap 0.10 -> 0.05; the kill switch, hold-on-veto, HRP, own-tick and impact kept or rejected by measurement.

**Verification:** `scripts/gate_research.py`; the bundle scores +0.95 backtest / +1.24 validation and the simulated kill switch locks 6 of BT4's 8 dates.

### 147. Execution-cost leads closed with measurements: no data-source gap, market fills pay the modelled 5 bps, no limit order was stale (V5.7.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (IB paper fills stay deferred with #116's IB part)

**Problem:** a median 5 bps fill-vs-open gap was blamed on a data-source gap, and 11 limit orders were flagged open > 5 days.

**Fix:** `evaluation/fill_price_audit.py` (`aq evaluate --audit-fills`) and limit-order ages in weekday sessions (`--max-open-sessions`).

**Verification:** on BT4's 495 fills the dataset open equals the Lean zip open (0.0 bps), equity market fills pay the configured +4.98 bps, and 0 limit orders were stale.

### 148. BT5: the V5.7.0 gate bundle in Lean, and a kill-switch trigger that counted price improvement as slippage (V5.7.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (the trigger needed a second fix, #153)

**Problem:** 24 member decisions were locked by `kill_switch_slippage_divergence_above_cap`, because `abs(fill - open)` counted a limit fill below the open on a buy as slippage.

**Fix:** the divergence counts only adverse slippage given the fill's direction.

**Verification:** pure and wiring tests; BT5 passed R-LEAN: Lean Sharpe +0.07 (+0.71 without risk-free), net +5.57%, drawdown 3.6%.

### 149. Crypto: no observation-only name graduates, and BTC/LTC stay (V5.7.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (a decision; the machinery ships default-off)

**Problem:** the crypto pool was two names and BT5's 13 crypto book trades earned $64 gross for $257 of fees.

**Fix:** none in behaviour: no name passes R-GATE alone, all ten together collapse the book and removing BTC/LTC loses too; `trading_eligibility_basis: "history"` ships off for a later look.

**Verification:** `scripts/crypto_graduation_research.py` on both splits with Coinbase fees.

### 150. V5.7.0 retrain: leakage fixed, honest numbers are lower, R-MODEL fails, V5.6.0 stays (V5.7.0)

**Severity:** 6/10 · **Status:** 🔴 `closed` as a promotion (the purge, diagnostics and holdout machinery ship)

**Problem:** a large train/validation IC gap, no purge at split boundaries, forex invisible to the model.

**Fix:** a 20-day label purge, a forex one-hot, `fx_carry_3m` and a separate forex rank group; seven variants inside the seed spread, so the control was the candidate.

**Verification:** R-MODEL failed (walk-forward IC 0.049 with 25% flips, as-live 0.29 against 0.95), so V5.6.0 stayed; part of the drop is removed leakage; the one-look holdout shows rank IC +0.055-0.072 (t 2.7-4.0) that the gates strangle; RL negative a fifth time.

### 151. Forex sleeve: no within-pool rank edge, R-FX fails, forex stays off (V5.7.0)

**Severity:** 4/10 · **Status:** 🔴 `closed` (superseded by #163, then R-FX6 turned forex off, #181)

**Problem:** forex was off because IB's $2 minimum ate a ~$0 gross edge; a fee-aware within-pool sleeve was the plan.

**Fix:** none shipped: the 15-pair rank IC is negative on both splits for the shipped and the retrained models (-0.03..-0.07), every sleeve configuration is net-negative, and the carry feature created no signal.

**Verification:** `scripts/forex_sleeve_research.py`, `ml/evaluation/forex_sleeve_research_candidate_v570.json`.

### 152. Gating, label timing and the shipped checks that need no change (V5.7.0)

**Severity:** 2/10 · **Status:** 🟢 `fixed` (verified, no code change)

**Problem:** did the weak learned gating model (MCC 0.0097) or close-to-close labels distort the book?

**Fix:** none needed: gating feeds only the capped legacy sleeve, and the live score's IC against open-to-open returns is within 1-6% of close-to-close.

**Verification:** the realised-IC comparison on both splits.

### 153. BT6: the direction-aware slippage fix did nothing; the trigger was crypto limit-fill drift (V5.7.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (verified in BT7)

**Problem:** BT6 had the same slippage-locked dates as BT5: the tracker compared a limit fill with the bar's open although the order went in hours later, so its gap is intraday drift, not cost.

**Fix:** `_track_slippage_divergence` ignores fills of tracked limit orders; market fills are unchanged. After any Codespace pull diff all of `ml/` (a stale `expert_models/` cost one invalid run).

**Verification:** BT7 (`backtests/2026-10-11_14-23-30`): Lean Sharpe +0.47 (+1.15 without risk-free), net +8.64%, drawdown 2.8%, kill-switch dates 12 -> 6; a residual non-limit path still labels 35 decisions.

### 154. Closing the minor leads against BT7 (V5.7.0)

**Severity:** 2/10 · **Status:** 🟢 `fixed` (accepted residuals, no code change)

**Problem:** the topology cache tolerance, the XOM/NVDA selection residuals, AAA's late Lean start and the live-only `fx_carry_3m` were still open.

**Fix:** each measured and accepted: topology strength differs on 4-5% of dates from run state, not the cache; selections 6% per symbol with every other feature exact; AAA is observation-only; the carry feature is kept for the next retrain.

**Verification:** BT7's `--reconcile-features`.

### 155. CI-only failure: a constant return window correlated as noise on Python <= 3.11 (V5.7.1)

**Severity:** 3/10 · **Status:** 🟢 `fixed and verified` (reproduced on Python 3.10, fixed, 54/54 topology tests pass there and on 3.14)
**Problem:** `test_vectorised_correlations_match_the_scalar_pearson_for_every_pair` failed on every CI job since V5.6.0 (CI runs 3.11, the dev PC 3.14): `_pearson_correlation` relied on an exact zero variance for a constant window, but Python <= 3.11 sums naively so `mean([0.001] * 24) != 0.001` and the variance came out ~1e-35, giving a ~1e-17 correlation instead of 0.0 and breaking the alphabetical top-peer tie. Lean also runs 3.11, so live peer ranking for a flat series could differ from the 3.14 dataset the same way.

**Fix:** A window whose values are all equal now returns 0.0 in the scalar path and zeroes that row and column in the vectorised matrix (decided on the values, independent of `sum()` rounding). Tests: 4 constant levels through both paths.

**Verification:** With the old code the original test and all 4 new cases fail on 3.10; with the fix all 54 topology tests pass on 3.10 and 3.14.

### 156. All Lean data stopped at 2021-03-31; the holdout was a separate root (V5.8.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** every zip ended 2021-03-31, so ten crypto pairs never reached 250 train rows, forex mixed two sources, 15 obsolete factor files remained and the shipped models had no rank edge on a new validation split (pooled IC -0.003).

**Fix:** all 104 zips rewritten 2013-01..2026-09 from one Yahoo source (a bad EURGBP print overridden), crypto quote zips and 19 FRED series refreshed, Coinbase listing dates recorded, and new splits train 2014-12..2021-12 / validation 2022-01..2023-06 / backtest 2023-07..2025-06 / holdout 2025-07..2026-09 (read once).

**Verification:** `aq evaluate --audit-data` (20 flags, all real events); local and Codespace `data/` trees identical by content digest.

### 157. Eight audit tools, so each question below is answered by a measurement (V5.8.0)

**Severity:** n/a (tooling) · **Status:** 🟢 `fixed`

**Problem:** the backtest audit counted bonds as "equity" (it groups by Lean securityType), the rolling-IC gate had never been compared with the IC it estimates, there was no check that a data rewrite is sound, no single view of which heads are promotable, and nobody could say whether a feature was a ticker ID.

**Fix:** `--ic-by-class` (within vs between class IC), `--audit-gates` (gate reading vs fully resolved IC, false-veto share; a constant true IC of +0.05 must be vetoed on well under half of the rebalances, pinned by a test), `--audit-data`, `--audit-heads` (R-HEAD), `--audit-features` (ticker-ID suspects, class-constant features, per-split IC sign, permutation drop), `aq clean ml`, per-order slippage trace in the book-history record, and `scripts/codespace_status.sh`.

**Verification:** a test file per module with synthetic data, `aq evaluate --audit-heads` on the shipped models: 2 of the heads the live path reads fail their own gate (`multitask.rank_20d` not promotable, `gating` MCC 0.0096 below the baseline's 0.031).

### 158. Bond duration beta leaked later data into every training row and was a per-ticker constant (V5.8.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (point-in-time on both sides; the retrained model is judged in the entries that follow)

**Problem:** `bond_empirical_duration_beta` was one OLS slope over a bond ETF's WHOLE 2014-2021 history broadcast to every row (so validation and backtest returns shaped the training feature, and it identified the ticker); live froze its own estimate after 260 bars and never saw that value.

**Fix:** `features/bond_features.py::rolling_duration_beta` / `rolling_duration_beta_series` (trailing 252 bars; the vectorised series equals the scalar at every row to 4e-16, holes included), used by `train.build_bond_features_by_date` and `main.py::_bond_empirical_duration_beta_for_symbol` behind `phase1.features.bond_duration_beta.mode` (default `full_history` = unchanged).

**Verification:** `tests/test_v580_live_parity.py` replays `main.py`'s deque over 400 bars and matches the training column on every row.

### 159. Latency and memory: the biggest per-tick costs measured and cut (V5.8.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** per tick, inference took 166-494 ms (57 separate model calls), topology 332-542 ms and `write_state` rewrote ~1.2 MB of JSON; the sequence trainer held a 1.3 GB tensor.

**Fix:** flat models for all symbols in one matmul per layer (64 -> 2 ms), vectorised topology lookups and peer ranking, trimmed scaler and sensitivity work, per-split sequence tensors, and throttleable dashboard writes in backtests (`diagnostics.state_write`).

**Verification:** equality tests for every changed numeric path; a 3.25-year Lean run in 48 minutes against 53 for 2 years before.

### 160. The Codespace retrain was killed five times: a memory spike, a push that overwrote the retrain's artifacts, VM restarts (V5.8.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** the sequence trainer's full-split forward pass spiked past the 8 GB Codespace, a mid-retrain push overlaid the new scaler and models with the old ones while reporting "verified", and VM restarts killed nohup jobs.

**Fix:** `forward_in_batches` for full-split passes, float32 chunked reads, `codespace_sync.ps1 -CodeOnly` / `-NoDatasets`, detached launchers with pid files (`codespace_start_bg.sh`) and status / memory helpers.

**Verification:** the sequence model trains in 9.5 minutes; the rebuilt dataset is byte-identical to stage A's.

### 161. The rolling-IC gate vetoes the better periods: decided by R-GATE (V5.8.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (decided by rule; the offline benefit did not transfer to Lean, #172, so the gates are safety controls)

**Problem:** the gate's vetoes are anti-informative: 82% of backtest vetoes are false and the forward IC on vetoed dates (+0.156) beats the overall (+0.095), because trailing IC mean-reverts.

**Fix:** R-GATE on both splits chose window 120 / floor 0.0 and a spread floor of 0.10; the kill switch stays, hold-on-veto, HRP and impact stay rejected.

**Verification:** `--audit-gates`; ~40 variants with neighbouring floors swinging ±0.5 Sharpe, so the pick is a rule-made noise-level choice.

### 162. V5.8.0 retrain, R-MODEL8 and the walk-forward (V5.8.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (the owner kept the candidate on 2026-10-13; read in Lean by BT1 / BT2, #172 / #174)

**Problem:** the shipped V5.6.0 models had no rank edge on the new splits and their as-live book vetoed 97% of rebalances.

**Fix:** a retrain on 2014-12..2021-12 (20-day purge, bond and forex rank groups, point-in-time bond beta) where no variant beat the control by more than the seed spread; R-MODEL8 failed one clause numerically and the owner kept the candidate; the learned gating network was switched off by R-HEAD.

**Verification:** a 12-window walk-forward: rank_20d IC +0.0525 (CI +0.019..+0.083, positive in 10 of 12), but the idealized book is net-positive in only 4 of 12 windows, because costs eat most of the IC; the holdout verdict is #169.

### 163. Forex: a carry-ranked sleeve at the minimum cap (V5.8.0, R-SLEEVE)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (dropped later by R-FX6, #181)

**Problem:** no signal gave forex a net-positive sleeve on both splits; carry had the best within-pool IC (+0.07, t 0.7).

**Fix:** by the owner's every-area-trades decision and R-SLEEVE the carry sleeve shipped at the minimum cap (gross 0.10, 2 per side, its own loss guard; `features/fx_signals.py`).

**Verification:** BT2: -$188 gross, -$544 net over 3.25 years, the guard never tripped.

### 164. Bonds: they lost money in the book; a momentum-ranked sleeve passes R-SLEEVE (V5.8.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (shipped at the minimum cap after BT1)

**Problem:** every bond ETF the V5.7 book traded lost money (hidden because the audit filed bonds under equity), and the model has no stable within-bond edge.

**Fix:** `phase_v2.bond_sleeve`: the 22 ETFs ranked among themselves by vol-scaled momentum (positive on both splits offline) outside the main pool; after BT1's -$540 in Lean, R-SLEEVE's minimum-cap branch cut the gross 0.30 -> 0.10.

**Verification:** BT2 with gross 0.10: +$37 gross, -$31 net over 34 trades, the loss guard never tripped.

### 165. Crypto: all twelve pairs trade, the ten extra ones capped (V5.8.0, R-SLEEVE)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (the per-name cap was cut further by R-CRYPTO, #180)

**Problem:** with data to 2026 every pair is trading-eligible, none with a proven edge, at 49-56 bps a fill.

**Fix:** graduates capped at 1% per name / 5% class gross with BTC/LTC exempt (`apply_class_weight_caps`, shared live and offline), a loss guard and the venue listing guard (no order before listing, during XRP's suspension or after EOS's delisting).

**Verification:** capped +0.71 / +0.31 against core-only +0.71 / +0.41 offline; BT2's crypto +$775 gross but -$356 net after $1,131 of fees.

### 166. RL sizing, a sixth time: no edge, so it ships at the minimum range with a shadow guard (V5.8.0, R-SLEEVE)

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** the book-level policy again does not beat a constant 1.0, and no multiplier range gains +0.05 Sharpe on both splits.

**Fix:** RL runs at `[0.9, 1.1]` with `dynamic_risk.rl_shadow_guard` (back to 1.0 while its trailing excess return is below -0.2% of NAV); the forex sleeve does not use it.

**Verification:** offline -0.018 / +0.025 with the guard; the Lean effect is bounded by ±10% of a position and not separable.

### 167. Latency and resources: what shipped, what R-LAT rejected (V5.8.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** a 2.25-year Lean run took 6,900-8,800 s, dominated by inference, topology, state writes and `build_model_input`.

**Fix:** the #159 cuts plus batched offline head scoring (an as-live pass 10 min -> 83 s); R-LAT rejected re-parsing `config.json` at rollover (0.2-0.6% of a run) and pruning Lean's code snapshot (~1 MB a run).

**Verification:** equality tests in the exported-model, topology, predictions and probe files; BT1's timing probe.

### 168. Feature audit verdict: the flagged features are class descriptors, not leaks (V5.8.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (no input-set change)

**Problem:** `--audit-features` flagged 13 per-ticker-constant features, 26 constant for forex and 18 that flip IC sign between splits.

**Fix:** none: they are instrument descriptors by design or not applicable to FX; the only real look-ahead (the bond beta) was already point-in-time, and the backtest split keeps a pooled IC of +0.060 (t 2.34), mostly within classes.

**Verification:** `evaluation/feature_quality_audit.py` tests; BT2's live features equal the dataset on 89 of 90 equity dates.

### 169. Holdout, one look (2025-07-01..2026-09-29): no out-of-sample rank edge, the gated book loses 2.4% (V5.8.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed` (reported as measured, nothing tuned on it)

**Problem:** did the in-window edge persist after 2025-05?

**Fix:** none: every head's IC is at most +0.037 with t < 1.5; the idealized book makes -0.81 Sharpe and the as-live book -0.59 (-2.4%), vetoed on 153 of 172 rebalances at 13% mean gross.

**Verification:** `ml/evaluation/holdout_report.json` (frozen models and config); BT2 repeated the window in Lean at -1.61%.

### 170. Learned topology sizing, measured offline for the first time (rule R-TOPO): stays on (V5.8.0)

**Severity:** 2/10 · **Status:** 🟢 `fixed` (no change)

**Problem:** the live topology sizing multiplier (0.5..1.0) was invisible to every offline run.

**Fix:** dataset rows scored with the live prototype distances through the same `topology_sizing_multiplier`; on vs off differs in sign by split and clears no margin, so it stays on (it acts as a uniform shrink).

**Verification:** `tests/test_learned_topology.py`, `test_topology_sizing_research.py`.

### 171. README results are refreshed by the commands that produce them; Monte Carlo is part of `--all` (V5.8.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** the README's Monte Carlo section claimed to refresh with every `aq evaluate` but only re-rendered a stale result (`--monte-carlo` was not in `--all`), `--monte-carlo` crashed with a KeyError on fewer than 30 daily returns, the as-live book and all V5.8.0 research were not on the page, and a second Lean run overwrote the first one's row.

**Fix:** `aq evaluate --all` includes Monte Carlo (a short dataset reports SKIPPED), `evaluation/readme_research.py` renders the as-live book per split and the research/audit block, `generate_backtest_report.build_history_markdown` lists every finished Lean run, and the audit flags and research scripts refresh the README on exit.

**Verification:** `tests/test_readme_research.py`, `test_generate_backtest_report.py`, `test_aq_cli.py`.

### 172. BT1 (Lean, 2023-07-01..2025-06-30): the retrained candidate loses 5.0% in the engine; the offline +0.62 does not reproduce (V5.8.0)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (measured and attributed; the regime skew it exposed is #173)

**Problem:** BT1 (`backtests/2026-10-13_17-54-47`): Lean Sharpe -2.98 (-0.75 without risk-free), net -5.03%, drawdown 8.2%, with the loss in the main equity book; the offline as-live book (+0.62) and Lean correlate at 0.02 daily.

**Fix:** none in the book: the gates that made the offline number did not dodge the same days in Lean; `--audit-backtest` now splits P&L by config class (bonds -$540), `--reconcile-features` applies crypto/forex's late-bar row, and the backtest state-write throttle goes on (34% of the run).

**Verification:** the run's audits, fill audit and reconciliations; an engine log clean apart from #104.

### 173. The models read a regime vector the dataset never produced: live fed the account drawdown into the `regime_*` inputs (V5.8.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (confirmed in BT2)

**Problem:** the dataset builds `regime_*` at zero drawdown while `main.py` passed the real one, so the regime inputs differed on 64 of 94 BT1 dates and a losing book changed its own inputs (top/bottom-6 overlap 0.66 at -8%).

**Fix:** `regime.build_model_input_regime_vector` (drawdown pinned to 0) feeds both training and live model inputs; risk decisions keep the real-drawdown vector.

**Verification:** `tests/test_regime_model_input.py`; BT2's equity features equal the dataset on 89 of 90 dates and the book replay shares 0.81 of names (0.77 in BT1).

### 174. BT2 (Lean, 2023-07-01..2026-09-30): capital preserved, no edge demonstrated, the regime fix confirmed (V5.8.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (measured and written up; the verdict is no demonstrated edge)

**Problem:** BT2 (`backtests/2026-10-14_07-27-32`): net -0.58%, drawdown 4.3%, Lean Sharpe -2.03 (-0.03 without risk-free); costs ($2,195) exceeded the gross result ($1,614), crypto alone $1,131 at 70 bps a fill.

**Fix:** none: R-LEAN8's engine and drawdown clauses hold, its Sharpe bar is missed (+0.14 on the backtest stretch), and the gain over BT1 comes from a changed config, one path, so it is evidence for the fix, not an edge.

**Verification:** `--audit-backtest` with both split periods, `--audit-fills`, `--reconcile-features`; holdout stretch -1.61%, in line with the offline -2.4%.

### 175. Lean's benchmark was a constant since 2021: the default hourly SPY feed had no data in the window (V6.0.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** without `set_benchmark` Lean used its sample hourly SPY zip ending 2021-03-31, so every V5.8 run charted SPY as a constant and its Alpha, Beta and Information Ratio were meaningless.

**Fix:** `runtime.benchmark_ticker` -> `set_benchmark(lambda time: <the daily SPY price>)` (a Symbol argument makes Lean add the hourly feed again); the report redraws a flat benchmark from the daily zip.

**Verification:** `tests/test_risk_controls.py`, `test_main_ensure_ready_smoke.py`; BT1 had 813 distinct benchmark values and no hourly request.

### 176. The offline simulator is not a model of Lean yet: R-CAL says branch B, and the gap is attributed (V6.0.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (the tools and the verdict)

**Problem:** V5.8's as-live Sharpe overstated BT1 by +1.4 and no tool compared the two day by day.

**Fix:** `aq evaluate --attribute-lean` rebuilds a Lean run's daily P&L per ticker and component (reconciles within $2), and `scripts/lean_calibration.py` compares it with the simulator rung by rung; the cadence phase, next-open fills, the per-order floor, live's resize / cooldown / stop and topology sizing were added to the simulator.

**Verification:** daily correlation 0.38 -> 0.70 and decision agreement 23 -> 63% on BT1, but R-CAL (r >= 0.5, gap <= 2 pp, agreement >= 80% on every window) failed: branch B, so gates stay frozen and alpha is judged on the ungated book.

### 177. Forex features: Lean's fill-forward bar repeats the previous range, the dataset's was flat, and the betas counted filled days (V6.0.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Lean's fill-forward forex bar clones the previous bar's high and low while the dataset's is flat at the previous close, and live regressed the sensitivity betas over the filled window.

**Fix:** `forex_fill_forward_bars: "flat"`: live flattens a fill-forward bar (`flatten_fill_forward_bar`, the dataset's definition) before it joins the windows, and forex keeps real-bar-only histories for the betas.

**Verification:** `tests/test_v600_forex_parity.py`; BT1's EURUSD / GBPJPY diverge on 8.8% of dates, the rest reconciler conventions.

### 178. Crypto and forex cross-asset features read a correlation window one bar longer than the dataset's; the TLT date is not the topology cache (V6.0.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (BT1 reconciliation: ETHUSD 1 of 170 dates, BTCUSD, XOM, NVDA, TLT 0, against 58% for ETHUSD's momentum rank in BT2)

**Problem:** BT2 reconciliation: ETHUSD `cs_momentum_rank_20` diverged on 58% of dates, `topology_correlation_strength` on 51%, the regime scores on 14%. The dataset row of a crypto/forex bar of day D sees the bars that closed before it (key D + 1.0: equity through D, crypto through D - 1); live builds exactly that at the symbol's own midnight tick, but re-scored the symbol on the next equity tick (key D + 1.5) with one more crypto bar in the window. The topology cache (#36) is not involved: it reuses only the SMACOF embedding, never `correlation_strength`, `top_peer_returns` or the risk label (pinned by a test over 15 bars); BT2's TLT diverged on 1 of 210 dates (2 of 53 features), XOM and NVDA on 1 of 210, inside R-PARITY's 10%.

**Fix:** `phase1.features.late_bar_cross_asset: "own_tick"`: `features.cross_asset_timing.LateBarCrossAssetCache` keeps the topology node and momentum map a crypto/forex symbol had at its own tick and the equity-tick re-score uses them; `--reconcile-features` then compares those payload features with the previous dataset row.

**Verification:** `tests/test_v600_late_bar_cross_asset.py`, `tests/test_market_topology.py` (cache never changes the model-input fields).

### 179. Main book: one change beats its costs, a slower book (R-BOOK) (V6.0.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (decided by rule; kept by V6.1's every-phase re-score, #195)

**Problem:** a rank IC of +0.05 does not pay a top-6/bottom-6 book's costs.

**Fix:** of ~12 single changes on the ungated calibrated book, only B1 passes R-BOOK: `rebalance_every_bars` 10 -> 20 and `exits.max_holding_bars` 20 -> 40 (+0.42 / +0.42 Sharpe validation / backtest).

**Verification:** `scripts/book_variant_research.py`; the 60-day head cannot be adopted (not promotable on any seed).

### 180. Crypto fees: limit exits, the passive-but-filled offset, a route-aware fee and smaller graduates (R-CRYPTO winner C5) (V6.0.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (corrected by BT1's fee evidence)

**Problem:** BT2 paid $1,131 of crypto fees on $775 of gross P&L; every exit was a market order at 80 bps.

**Fix:** crypto exits rest as limit orders (risk exits still go to market), a 5-bar crypto timeout, a route-aware net-edge fee (maker 60 / taker 80) and graduates capped at 0.5% per name / 2.5% class; the research's offset 0.0 was reverted to 1.0 after BT1 (a limit at the last close is charged as taker).

**Verification:** wiring, order-gate and cost tests; V6 BT2 paid 63.9 bps a crypto fill and $546 in total.

### 181. Forex sleeve dropped by rule R-FX6 (V6.0.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (decided by rule)

**Problem:** the minimum-cap carry sleeve lost $544 net in BT2 (IB's minimum is ~11 bps a fill on its tickets).

**Fix:** none of 48 variants is positive on the backtest split, so R-FX6 drops it: `forex_risk.enabled` false (also takes the pairs out of the book and liquidates held ones); forex still feeds the cross-asset features.

**Verification:** BT1 made zero forex orders.

### 182. Latency: three measured cuts, two rejected by estimate (V6.0.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `_build_model_input` took 2.75 ms a call and the regime experts ran per symbol.

**Fix:** the sensitivity betas from cached float64 arrays, one sorted FRED index, and the experts for every symbol in one pass (`batch_experts_across_symbols`, 79 -> 16 ms a tick, bit-identical); R-LAT rejected re-using own-tick predictions and caching the indicator block.

**Verification:** `scripts/profile_main_tick.py` (2.75 -> 1.8 ms); equality tests in the sensitivity, across-symbols and FRED files.

### 183. Datasets and the backups: `full_dataset.csv` is the V5.8.0 window again, and the ETH/LTC vintage rows differ only in dead rows (V6.0.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** the local `full_dataset.csv` and split files were the pre-V5.8.0 window, and the Codespace-built datasets had ETH/LTC rows differing from local.

**Fix:** `scripts/build_holdout_dataset.py --full-splits --write-split-files` rebuilds all four splits with the active scaler (never refit); old backups and `data_holdout/` deleted (`aq clean ml --apply`, 13.7 GB); `available_to` refreshed from the zips.

**Verification:** zero differing feature cells against the dataset V5.8.0 was scored on; identical ETH/LTC zip digests; the installed-model manifest unchanged.

### 184. #104 teardown: the trivial algorithm hangs on the newest Lean image too (V6.0.0)

**Severity:** 3/10 · **Status:** 🔴 `closed` (environmental)

**Problem:** was the teardown hang specific to the pinned `lean:17900` image?

**Fix:** none: the 15-line `scripts/lean_teardown_smoke` also times out on `lean:latest` (2026-10-12), after the results; the pin stays.

**Verification:** `ml/evaluation/v600/teardown_smoke_*_engine_log.txt`.

### 185. BT1 (Lean, 2023-07-01..2026-09-30, the V6 config): +6.72% net, Sharpe +0.55 without the risk-free rate, drawdown 5.40% (V6.0.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (written up; the drawdown clause is #196's)

**Problem:** BT1 (`backtests/2026-10-15_14-55-24`): Lean Sharpe -1.55, net +6.72%, drawdown 5.40% (limit 5%), with the main book -$3.0k on the backtest stretch and +$5.9k on the seen holdout; crypto limit fills paid 70.9 bps against a 70 bps bound.

**Fix:** the crypto limit offset back to 1.0 (a maker fill); R-POSTURE kept the gross cap at 1.0 (main-book P&L +$4.7k, Sharpe +0.55).

**Verification:** attribution reconciles to the cent; features reconcile on 0 of 170 dates for equities; the pre-run prediction correlated 0.51 daily with the main book but missed its level, so branch B stands.

### 186. BT2 (Lean, same span, the corrected crypto config): +5.28% net, crypto fees halved, one small change moves a Lean path (V6.0.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (written up; the consistency and drawdown clauses fail, reported)

**Problem:** BT2 (`backtests/2026-10-15_17-29-50`): net +5.28%, Lean Sharpe -1.67 (+0.44 without), drawdown 5.50%; crypto paid 63.9 bps a fill ($546), but the main book earned $0.9k against BT1's $2.9k with identical selections.

**Fix:** none: a different crypto P&L moves the whole-portfolio return the kill switch reads, which froze the equity book on different days, so one Lean path cannot rank configs at this precision; the whole-span gain over V5.8 sits in the seen holdout.

**Verification:** attribution, audit and reconciliation files under `ml/evaluation/v600/`.

### 187. Phase-0 defects: the holdout report scored the backtest split, a silent rank-head fail-open, attribution by ticker and today's config, a preset trap, a NumPy deprecation (V6.1.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `holdout_report.py` would have reported the backtest split as the holdout; the fail-open rank-head policy was recorded only as a reason string; `--attribute-lean` labelled positions by the day's book and read today's config; `presets.moderate` kept the pre-R-GATE spread; `pd.Timedelta(days=n)` raised a NumPy deprecation.

**Fix:** holdout rows by `phase1.windows.holdout`, a logged `demotion_fallback`, attribution by the component that opened a position and the run's frozen config, the preset spread 0.10, `pd.Timedelta(n, unit="D")`.

**Verification:** the holdout, rank-signal, head-audit and attribution tests; the book replay leaves no ticker-specific residual, closing #91 / #100.

### 188. The calibration tool simulated every Lean run with today's config and threw away why the simulator vetoed (V6.1.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `scripts/lean_calibration.py` built the simulator from the current `config.json` for every window, so once V6 moved the book to 20/40 a re-run of a V5.8.0 window would have simulated the wrong book; it kept only engaged / vetoed per offline rebalance (the reason was dropped), counted a date the simulator never reached as a plain disagreement, compared only main book + crypto, and live's book history logged the rolling-IC gate's veto but not its reading.

**Fix:** each window runs on its run's frozen config (`ml/evaluation/run_configs/<run folder>.json` through `lean_attribution.run_config_path`); `disagreement_table` lists every live-vs-offline disagreement with the offline reason and counts `missing_offline` dates apart; `--components` / `--rcal2` add the legacy signal and the three R-CAL2 windows (V6 BT2 backtest and holdout stretches, V5.8.0 BT2 backtest stretch) with a per-component correlation; `build_book_history_record` stores `rolling_ic` (mean, resolved dates, non-finite -> null) on every rebalance record.

**Verification:** `tests/test_lean_calibration.py`, `tests/test_portfolio_book_construction.py`, `aq test --live`.

### 189. Forex: Lean's market holidays dropped bars live never receives, the dataset kept them (V6.1.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (dataset rebuilt on the Codespace; BT1's reconciliation confirms)

**Problem:** EURUSD / GBPJPY diverged on 15 of 170 dates (`sens_*` betas for 6 dates, momentum / topology on 2024-01-23, MACD for 6 months, and 44 artefact cells on 2025-12-26 / 2026-01-02). Lean's market-hours database lists Forex-oanda holidays (12/25-26/2022, 1/1-2/2023, 12/24 and 12/31/2023): no bar is delivered and nothing is filled forward, but the OANDA zips carry real bars on 2022-12-26 / 2023-01-02 and the dataset filled every non-Saturday gap, so its windows held 2-4 bars live never sees (the shift lasts 20 / 252 / 260 bars). GBPJPY's live momentum on 2024-01-22, 0.03953, equals the holiday calendar exactly and not the dataset's 0.04478.

**Fix:** `features.cross_asset_timing.lean_market_holidays` reads the database; `phase1.features.forex_lean_holidays` (on) drops holiday zip bars and stops filling them in `fill_forward_open_forex_days`, the timeline, the dataset's forex features and the parity replica; the reconciler compares any tick that holds a fill-forward bar (Sunday, or a weekday the zip lacks) on its payload features only (`forex_tick_holds_fill_forward_bar`); the bar probe takes `date_ranges` so BT1 logs Lean's bars on the holiday dates.

**Verification:** `tests/test_v610_forex_holidays.py` (including the GBPJPY momentum reproduced from the real zip), `test_cross_asset_timing.py`.

### 190. The simulator lacked the mechanisms that decided the V6 Lean runs, and charged no exit cost on a rebalance date (V6.1.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed` (R-CAL2 stays branch B by the rule)

**Problem:** live re-runs every member each session, watches the kill switch on the whole portfolio, trades crypto on weekends, caps 12 positions, passes members through the analyzer and runs the legacy signal; the simulator did none of this, charged no cost on age/stop exits on a rebalance date and read a non-existent regime key.

**Fix:** `simulate_rank_book` options for each mechanism (defaults reproduce V6 exactly), the shared `derive_signal` in `main.py`, `scripts/build_legacy_probability.py`, a warm rolling-IC gate and `lean_calibration.py --rcal2`.

**Verification:** R-CAL2: correlation 0.71 / 0.67 / 0.68, gap +1.2 / -2.5 / -0.5 pp, agreement 77 / 94 / 76% on the three windows, so not calibrated but close; replaying live's gate decisions lifts the correlation to 0.74-0.83.

### 191. Latency: the feature path did not regress; Lean's per-tick cost is the host and the container (V6.1.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (environmental)

**Problem:** V6 BT2 took 111 minutes against V5.8.0's 48 on the same span, already in the warm-up year.

**Fix:** none in the code: `_build_model_input` is 1.9 ms native (2.9 ms in V5.8.0), 5.3 ms in the Lean image and 8.9 ms in the engine on the 2011 4 GB PC; `TimingProbe` now records CPU time and a whole-tick section, and the profiler runs inside the Lean image.

**Verification:** `tests/test_performance_probe.py`; profiles under `ml/evaluation/v610/`; #204 measured 0.6 ms on a faster host.

### 192. Live crypto cannot fill through Interactive Brokers (V6.1.0)

**Severity:** 5/10 · **Status:** 🟡 `partial` (checked and flagged; the routing decision is an IB deployment item)

**Problem:** the book prices Coinbase fees (`CoinbaseFeeModel`, a cash account) and the backtests fill on Lean's Coinbase market, while the live credentials this project renders are Interactive Brokers'. QuantConnect's staff answer in the IB-crypto thread is "Interactive Brokers does not support crypto" (the LEAN pull request #8446 for it is still open), and Lean's Coinbase brokerage supports crypto on cash accounts only, with market, limit and stop orders.

**Fix:** `execution.lean_config_render.validate_live_crypto_route` (advisory, never changes trading) is printed by `aq render-lean-config`; RUNBOOK's deploy checklist names it. Choosing the live crypto brokerage (Coinbase) or switching the crypto classes off before a live deploy stays with the deferred IB items.

**Verification:** `tests/test_lean_config_render.py`; sources: quantconnect.com/forum/discussion/18507, quantconnect.com/docs/v2/writing-algorithms/reality-modeling/brokerages/supported-models/coinbase.

### 193. The README performance section mixed V5.8.0 text with V6 results (V6.1.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (V6.3.0: every block regenerated on the shipped config and BT4; `scripts/readme_freshness.py` finds none stale, #206)

**Problem:** every offline block (Monte Carlo, evaluation, benchmarks, as-live, research, kill-switch replay) dated from V5.8.0 and two contradicted the shipped config (the forex sleeve "shipped at gross 0.10", crypto caps 0.01 / 0.05); `_updated_at()` stamped render time, so a re-render made old data look fresh; `--audit-backtest`, `--attribute-lean`, `--audit-fills` and `--reconcile-features` did not refresh the README; Monte Carlo bootstrapped only the offline idealized book and said nothing about its source; `README.md` / `REPRODUCIBILITY.md` said `--all` excludes Monte Carlo.

**Fix:** the research builder reads `v600/{forex,crypto}_research.json` and the shipped `config.json` (no typed settings), plus the R-CAL2 and rule-chain results; stamps show the source artifact's time and the render time; the four audit flags refresh the README; `aq evaluate --lean-monte-carlo` adds the Lean run's own bootstrap to the block with its source named; the run history keeps ten runs; docs corrected.

**Verification:** `tests/test_readme_research.py`, `test_generate_evaluation_report.py`, `test_cli_help_surface.py`.

### 194. Retrained candidates and head blends: nothing beats the installed stack by more than seed noise (R-MODEL9, R-HEAD2; V6.1.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (decided by rule; the installed models and blend stay)

**Problem:** the installed multitask is the weakest of three control seeds, the trainers overfit (train IC 0.37, validation ~0), and the live blend serves the weaker sequence model first.

**Fix:** none installed: 29 candidates; the best (`v9_reg`, swapped priority) gains +0.019 validation IC against a seed spread of 0.071, so R-MODEL9 fails; R-HEAD2's head blends lose on backtest. The tools ship (`model_candidate_research.py`, `prepare_v610_candidates.py`, a swapped-priority decision score).

**Verification:** `tests/test_v610_research.py`, `test_model_candidate_research.py`; `ml/evaluation/v610/model_ic.json`, `research.json`.

### 195. Book cadence, net-edge holding period, legacy budget, gates, gross cap: decided on every rebalance phase (R-BOOK2, R-LEGACY, R-GATE; V6.1.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (decided by rule; legacy L2 declined by the owner in V6.2.0)

**Problem:** V6.0.0 picked the 20-bar book on one rebalance phase, but the shipped book's ungated validation Sharpe spans -1.02..+0.57 across its 10 phases.

**Fix:** none adopted on all-phase medians: the 10/20 book is a near miss (+0.099 against +0.10), the holding-period change fails, legacy L2 (gross 0.15) passes the margins but not R-LEGACY's positive-on-both-splits clause, the gates are skipped (branch B); the RL guard state no longer leaks between runs.

**Verification:** `scripts/v610_research.py`; `ml/evaluation/v610/research.json`.

### 196. BT1 (Lean, the V6.1 config = V6 BT2's): identical to V6 BT2, which confirms determinism (V6.1.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (written up; the drawdown clause fails, #197)

**Problem:** did V6.1's `main.py` changes alter behaviour, and why did the live rolling-IC gate read lower than offline?

**Fix:** none in behaviour: all 1,268 order events equal V6 BT2's (+5.28%, drawdown 5.50%); live counts a crypto pair's IC event twice per date (its own tick and the next equity tick), which the offline gate now replicates (`with_live_event_duplicates`); R-POSTURE2 set a cap of 0.80 for BT2.

**Verification:** features reconcile on 0 of 170 dates for seven tickers; the gate replica raises live-vs-offline agreement to 92%; the pre-run prediction correlates 0.62 daily.

### 197. BT2 (Lean, gross cap 0.80 by R-POSTURE2): lower exposure, worse path; the shipped cap stays 1.0 (V6.1.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (written up)

**Problem:** BT2 (`backtests/2026-10-16_21-27-47`): net +3.80%, drawdown 7.80% against BT1's +5.28% / 5.50%; the main book fell from $1.5k to $0.4k.

**Fix:** the cap is not confirmed (R-LEAN10's BT2 clause fails), so it stays 1.0: a smaller book changes which sessions the kill switch locks, so one path moves by more than the scaling.

**Verification:** `ml/evaluation/v610/attribution_bt2_v610.json`, `config_bt2.json`.

### 198. CI red on the V6.1.0 commit: a test read the gitignored `ml/model_weights.json`; ubuntu-latest moves to 26.04 (V6.2.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (GitHub CI green on the V6.2.0 commit `5d5ae86`, 2026-10-18)

**Problem:** run 39036302436 failed python-tests (ubuntu, windows) and subsystem-matrix (ml) on one test: `test_v610_harness_warms_the_gate_on_earlier_rows_and_models_the_legacy_signal` reached `AsLiveHarness.v610_mechanisms()`, which reads `ml/model_weights.json`, present locally and on the Codespace but gitignored. CI also warned that `ubuntu-latest` moves to Ubuntu 26.04 from 2026-10-19 and that the Node 20 actions are forced onto Node 24.

**Fix:** the test brings its own `ml_dir` (a stub `model_weights.json`) and score cache in `tmp_path`; `scripts/clean_checkout_test.ps1` runs CI's pytest command in a detached worktree of HEAD plus the working-tree changes, with no gitignored file (an AGENTS.md wrap-up step, `tests/README.md`); the Linux jobs pin `ubuntu-24.04` and the actions move to checkout / setup-python / setup-node / upload-artifact v7 (release notes read: nothing this repo uses changed); `codespace_stop_jobs.sh` matches the V6.1+ job names. A flaky test found on the way: two run folders created in one filesystem tick sorted either way (`_iter_backtest_result_jsons` now breaks mtime ties by name).

**Verification:** clean-checkout run 3,571 passed / 0 failed; actionlint 1.7.7 clean; `tests/test_ci_workflows.py`, `test_generate_backtest_report.py`.

### 199. Lean's Sharpe charged a stale 5.5% risk-free rate and annualised a 7-day equity curve at 252 days (V6.2.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Lean's sample risk-free file ended 2023-07 at 5.5% and was filled forward through 2026, and a weekend-trading equity curve (~365 returns a year) was annualised at 252.

**Fix:** `evaluation/lean_statistics.py` reproduces Lean's Sharpe / Sortino / PSR exactly (`aq evaluate --lean-stats`), `scripts/refresh_lean_interest_rate.py` appends FRED DPCREDIT's change points (average 5.49% -> 4.69%), and `runtime.trading_days_per_year` is 365 (owner decision).

**Verification:** eight past runs reproduced to the printed digits; V6.1 BT1 re-priced -1.673 -> -0.971.

### 200. Idle cash earned nothing in Lean: a T-bill sweep (BIL), outside the strategy and its risk controls (V6.2.0)

**Severity:** 7/10 · **Status:** 🔴 `closed` (the sweep shipped and is confirmed; the lock-path sensitivity is a documented design limit, R-KILL branch C, #211)

**Problem:** the mostly vetoed book left 70-95% of NAV in cash that earned nothing while Lean's Sharpe subtracts the full risk-free rate.

**Fix:** `portfolio/cash_sweep.py` holds idle NAV in BIL (outside the universe and every strategy control) under a no-borrow and a Lean-margin limit; the risk controls read the strategy's own value (`advance_strategy_value`); the simulator, attribution and harness model it.

**Verification:** Lean BT1 / BT3: +16.85%, Sharpe -1.673 -> +0.082, sweep +$10,699 (predicted +$10,062), identical rebalance decisions; the kill switch's lock dates moved (14 -> 46) because the larger NAV let a borderline order pass and the switch sits at its floor.

### 201. Crypto counted twice in the rolling-IC gate: decided by R-DEDUPE - not adopted (V6.2.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (decided by rule; the double count stays)

**Problem:** live records a late-bar symbol's IC event on its own tick and the next equity tick (#196).

**Fix:** `rolling_ic_gate.late_bar_event_count` ("per_tick" default, "once") through one predicate, `should_record_ic_event`, live and offline; "once" lifts validation -0.45 -> +0.13 but costs -0.09 on backtest against a +0.10 bar, so not adopted (worth revisiting with more data).

**Verification:** `tests/test_v620_dedupe.py`; `ml/evaluation/v620/research.json` (`dedupe`).

### 202. Phase luck: a staggered tranche book, decided by R-STAGGER - not adopted (V6.2.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (one tranche stays; V6.3.0's second look also adopted nothing, #212)

**Problem:** the book's Sharpe depends on its rebalance phase (-1.02..+0.57 on validation); tranches at offsets should average that out.

**Fix:** tranche helpers in `portfolio.book_construction` and `evaluation/tranche_book.py` (K phase-shifted runs, each tranche's kill switch fed the others' returns); S2 passed every `rule_verdict` margin (+0.26 / +0.52) but widened the validation phase range, the clause the lead exists for; the live path is built only on adoption.

**Verification:** `tests/test_v620_tranche_book.py`; `ml/evaluation/v620/research.json` (`stagger`).

### 203. Regularised retrain (more seeds, label noise, a train-chosen feature subset): R-MODEL10 installs nothing (V6.2.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (decided by rule; the installed models stay)

**Problem:** could stronger regularisation, judged as an ensemble against ensemble noise, beat the installed models?

**Fix:** `label_noise_std`, per-model input features (so a subset model could ship), `select_feature_subset.py` (17 of 68 inputs on the train split) and a resampled-ensemble yardstick (0.034); every candidate fails clause 1 and no decision head passes R-HEAD.

**Verification:** `tests/test_v620_model_inputs.py`, `test_model_candidate_research.py`; `ml/evaluation/v620/model_ic.json`, `candidates.json`.

### 204. Latency and the #104 teardown measured on a faster host: both are the dev PC (V6.2.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (measured; no code change)

**Problem:** was the 8.9 ms per `_build_model_input` call in Lean, and the teardown timeout, the code or the 2011 4 GB PC?

**Fix:** none: on a 4-core DinD Codespace the call costs 0.6 ms in and out of the Lean image, a 3.25-year run takes ~10 minutes and all three runs shut down cleanly.

**Verification:** `ml/evaluation/v620/profile_codespace_*.json`; the three engine logs.

### 205. BT2 (Lean, the shipped V6.2.0 code and config): identical to BT3; run tooling defects found on the way (V6.2.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** confirm the shipped code in Lean (`backtests/2026-10-17_21-39-55`).

**Fix:** BT2 equals BT3: +16.85%, Lean Sharpe +0.082 (-0.776 on the old basis), drawdown 4.30%, sweep +$10,699, strategy ex sweep $6,148 (Sharpe +0.54); the sweep and the 365 basis ship. On the way: `find_book_history_for_run` reads the engine log's UTC start, `codespace_sync.ps1` resolves one of two Codespaces, equal-mtime run folders sort by name.

**Verification:** `ml/evaluation/v620/attribution_bt2_v620.json`, `lean_stats_2026-10-17_21-39-55.json`; attribution and report tests.

### 206. The README's backtest section had Lean's raw statistics dump and no bet, concentration or cost measures: rebuilt as "Backtest Statistics" (V6.3.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** Lean's 27 statistics were one unsorted dump without AUM, leverage, bets, HHI, drawdown percentiles, cost per turnover, deflated Sharpe, classification scores or per-class risk, and the T-bill carry was mixed into every number.

**Fix:** `evaluation/backtest_statistics.py` (López de Prado ch. 14, portfolio and strategy-ex-sweep columns, a reason instead of a fabricated number), `evaluation/readme_statistics.py`, `aq evaluate --backtest-stats` / `--lean-report` (run by `aq backtest`) / `--classification`, and `scripts/build_trial_registry.py` for the deflated Sharpe's N.

**Verification:** hand-computed formula tests and a synthetic run (`tests/test_backtest_statistics.py`); on BT2 net PnL, fees, drawdown and the Lean-formula Sharpe match Lean.

### 207. Each Lean-run `aq evaluate` flag picked "the latest run" its own way and none honoured the README pin (V6.3.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** five flags chose the newest run by name, with or without an engine log, while the README used the pin, so two blocks could describe two runs.

**Fix:** one resolver, `generate_backtest_report.resolve_lean_run_dir` (explicit, pin, newest finished run), for every Lean-reading flag.

**Verification:** `tests/test_generate_backtest_report.py`, `test_aq_cli.py`, `test_lean_report.py`.

### 208. The T-bill sweep was counted as equity in the order audit's per-class P&L (V6.3.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** BIL is a Lean equity outside the universe, so `--audit-backtest` filed $10.7k of carry under "equity" and made the book look equity-long.

**Fix:** `backtest_audit.class_by_ticker_from_config` gives the sweep ticker its own class `cash_sweep` and falls back to `security_type`.

**Verification:** `tests/test_backtest_audit.py`, `test_backtest_statistics.py`.

### 209. Codespaces billed while idle and the Lean host was undecided (lead 5) (V6.3.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** the monthly Codespace budget was ~90% used, the DinD Lean recipe was typed by hand and the docs still said Lean cannot run on a Codespace.

**Fix:** AGENTS.md rule 13 (on only while a job runs, bundled work, DinD deleted after its pull), `scripts/codespace_lean_run.ps1` + `codespace_lean_dind.sh`, and `codespace_session_v630.sh` for the whole offline phase in one lifetime; Lean runs on a temporary DinD Codespace from now on.

**Verification:** `tests/test_codespace_lean_scripts.py`; Changelog V6.3.0 "Hosts".

### 210. R-CAL3: the offline simulator against V6.2.0's BT2 - branch B, the gates stay frozen (V6.3.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (decided by rule)

**Problem:** is the simulator calibrated on the shipped config, so the gates could be tuned?

**Fix:** none allowed: correlation 0.79 / 0.70, gap +1.3 / -3.0 pp, agreement 78% / 94% on BT2's two stretches fail R-CAL2's clauses, so R-GATE3 is skipped.

**Verification:** `ml/evaluation/v630/calibration.json`.

### 211. R-KILL: the kill switch's window and a release band against its lock-path fragility - branch C, nothing adopted (V6.3.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (decided by rule; #200 closes as a design limit)

**Problem:** at the -1.0 floor a few dollars flipped Lean's lock path (46 against 14 lock dates on identical decisions).

**Fix:** `risk.kill_switch.release_rolling_sharpe` (default `null`) through one function live and offline; the 120-bar window gains +0.24 Sharpe but locks on less than half of KS0's dates (safety clause fails), the release band is stable (0.99) but -0.06, so KS0 stays.

**Verification:** `tests/test_kill_switch.py`, `test_v630_round.py`, `test_v630_research.py`; KS0's offline lock path is already stable (0.94), so Lean's flip is the NAV path.

### 212. R-STAGGER2: S2's second look with phase measures that ignore one lucky phase - not adopted (V6.3.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (decided by rule; the live tranche path stays unbuilt)

**Problem:** S2 passed every margin in V6.2 but widened the phase range; the re-look replaced the range with robust measures.

**Fix:** none adopted: +0.26 / +0.52 and the worst-phase clause pass, but the validation interquartile range widens 0.50 -> 0.67 (limit 0.62); both looks count in the trial registry.

**Verification:** `ml/evaluation/v630/research.json` (`stagger`); `tests/test_v630_research.py`.

### 213. BT4 (Lean, the V6.3.0 code, BT2's config plus the null release band): identical to BT2 order for order (V6.3.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (the final run of the phase)

**Problem:** confirm the new code is a no-op on the shipped path (`backtests/2026-10-18_12-55-00`, DinD Codespace).

**Fix:** none needed: all 1,596 order events and 27 statistics equal BT2's, clean teardown; no rule shipped a change, so BT5 was not run. The statistics show the strategy at 0.17x of NAV, a 51.7% hit ratio and a 46% deflated Sharpe.

**Verification:** `aq evaluate --lean-report --backtest-dir backtests/2026-10-18_12-55-00` (0 failed steps).

### 214. Engine image checked on the DinD host; run tooling fixed on the way (V6.3.0)

**Severity:** 4/10 · **Status:** 🟡 `partial` (the local image is stale until Docker Desktop starts on the PC)

**Problem:** the live path changed in V6.2, so the engine image needed rebuilding, and Docker Desktop cannot start on the PC.

**Fix:** `scripts/codespace_engine_check.sh` builds it on DinD and checks `/api/assets-status` (the engine alone: alpine redis/postgres cannot start there), which now reports the sweep; the DinD runner puts the Lean CLI on PATH and each Codespace gets its own ssh config.

**Verification:** HTTP 200 with the sweep settings (`ml/evaluation/v630/engine_assets_status.json`); `tests/test_assets_status.py`.

### 215. Data refresh to 2026-10-16: rows are appended in the stored vintage, never rewritten (V6.4.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (decided; nothing pending)

**Problem:** the data ended 2026-09-30; a full Yahoo rewrite would move every adjusted row (each new dividend rescales history), and with it the dataset, the models' inputs and the BT5 = BT4 check.

**Fix:** `scripts/data_append_refresh.py` fetches from 14 days before the last stored date, puts today's vintage back on the stored basis (old / new close at the latest common date, 1.0 unless a dividend or split intervened), appends only the new rows and merges the FRED caches the same way; `scripts/data_append_guard.py` hashes every row up to 2026-09-30 before and after.

**Verification:** 144 files, 0 changed rows up to the cutoff (`ml/evaluation/v640/data_append_guard.json`); the Codespace's copy is checked against the same pre-refresh hashes; the rebuilt dataset may differ from V6.1's only in new rows and newly resolved `target_*` cells.

**Result:** Yahoo returned the 12 sessions to 2026-10-16 for 105 assets (the 104 plus BIL / SPY); no splice factor was further than 0.62% from 1 (ABT, a dividend), 144 files show 0 changed rows up to the cutoff on the PC and again on the Codespace, and the rebuilt dataset has 1,296 new rows and 12 differing columns, all `target_*` (labels that resolved). Four FRED series published a monthly rate late for a date inside the old window: it stays out, so the features of that day are unchanged.

### 216. R-DEDUPE2: crypto counted twice in the rolling-IC gate, second look on the longer span (V6.4.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (decided by rule; #201 closes: the double count stays)

**Problem:** #201's rule did not adopt `late_bar_event_count: "once"` (validation +0.13, backtest -0.09 against a +0.10 bar) and said to revisit it with more data.

**Fix:** the same variant, as-live, scored on validation and the pooled post-validation span (backtest + holdout, the holdout read logged); adopted iff `verdict_as_live` passes (backtest gain >= +0.10, validation >= -0.02, >= 60% of phases beat the base median on both splits, drawdown within 1 pp). The margins are not loosened; #201 closes either way.

**Verification:** `scripts/v640_research.py` stage `dedupe`; `tests/test_v640_research.py`.

**Result:** On the pooled backtest + holdout span "once" scores a median Sharpe of 0.13 against 0.24 for "per_tick" (-0.10, the bar was +0.10) while validation gains +0.58; it beats the base median on 40% of phases (60% needed). Not adopted: more data did not change V6.2's reading, and the rule's margins stay.

### 217. L1: engaged-day rank skill - does the gate protect capital or hide weakness? (V6.4.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (decided by rule: the gate hides weakness, it does not protect capital)

**Problem:** the gate vetoes most rebalances (mean exposure 0.17x) while the pooled IC (~0.05) cannot pay for a full book; is the IC higher when the gate lets the book trade?

**Fix:** report, no config change. On validation and backtest (holdout report only) the gate's per-date verdict splits the dates; rank IC (daily mean, non-overlapping, HAC t), the top-6/bottom-6 spread and the as-live Sharpe over the days whose latest rebalance was engaged are compared with all days. Bar (owner): engaged - all >= +0.02 IC and >= +0.15 Sharpe (median over phases) on BOTH splits, else "the gate hides weakness" and L6 / L7 cannot ship.

**Verification:** `evaluation/engaged_day_skill.py`; `tests/test_engaged_day_skill.py`.

**Result:** Engaged days carry LESS rank skill than the days the gate vetoes: IC 0.006 -> -0.003 (validation), 0.093 -> 0.088 (backtest), -0.004 -> -0.034 (holdout, report only); the vetoed dates read +0.021 / +0.129 / +0.037. The as-live Sharpe margin is +0.01 / +0.03 against +0.15 needed, so the gate is a safety control that does not select good days, and L6 / L7 close by their precondition. The engaged-day pooled IC of 0.09 on backtest is real (HAC t 2.8), but so is the vetoed-day IC: the veto discards good days as often as bad ones.

### 218. L2: direction heads - calibrated signal or diagnostic only? (V6.4.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (decided by rule: direction = diagnostic only)

**Problem:** the direction heads reach ~57-58% accuracy with a weak log-loss, and the Lean book's side accuracy is ~51%; they are not in the book.

**Fix:** temperature scaling or isotonic regression fitted on validation only (the method chosen by cross-fitted log-loss), per-class thresholds, and three overlays on the percentile ranks (`portfolio/direction_overlay.py`): blend w=0.25, blend w=0.5, agree-filter margin 0.05. Shipped iff `verdict_as_live` passes AND the median turnover rises <= 20%; otherwise "direction = diagnostic only".

**Verification:** `evaluation/probability_calibration.py`, `tests/test_probability_calibration.py`, `tests/test_direction_overlay.py`.

**Result:** Both direction_20d heads are over-confident (validation ECE 0.21 / 0.17, log-loss 0.81 / 0.77, worse than a coin flip's 0.693); the best temperature hits the search bound (T = 20) and brings the cross-fitted log-loss to 0.706 / 0.694: calibrated, the heads carry no information (backtest balanced accuracy 0.528 / 0.536). The overlays: C1 blend 0.25 -0.37 backtest Sharpe, C2 0.5 -0.27, C3 agree-filter 0.0 (the calibrated probabilities never leave 0.5 +- 0.05, so nothing is filtered). Nothing ships.

### 219. L3: the legacy signal against the main MoE book (V6.4.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (decided by rule: the legacy sleeve and the models stay)

**Problem:** legacy made ~+$1.45k against the main book's ~+$1.04k on the same Lean run; is it a better primary signal, a feature, or a permanent parallel sleeve?

**Fix:** (a) legacy budget off / half (0.025 / 0.01) / double (0.10 / 0.04, with the legacy-positive clause), as-live: shipped iff `verdict_as_live` passes and validation improves. (b) one controlled retrain: the multitask model with the previous day's legacy probability (z-scored on train) as an input, 5 seeds, against the installed models with the yardstick fixed at the owner's 0.034, plus `verdict_as_live` with validation improving and latency <= 1.5x. (c) report: legacy IC against rank_20d's by class and regime.

**Verification:** `scripts/v640_research.py` stage `l3`; `ml/evaluation/v640/model_ic.json`.

**Result:** (a) off +0.01 / half -0.05 / double -0.18 backtest Sharpe against the shipped 0.05 / 0.02 (validation +0.17 / +0.08 / -0.01): no budget passes, and doubling fails the legacy-positive clause. (b) the multitask model with the previous day's legacy probability (z-scored, 5 seeds, in-sample on train) does not beat the installed models by the 0.034 yardstick on validation (swapped priority, the only one where multitask ranks) and its backtest HAC t is < 2: no candidate directory, no book score. (c) IC of the legacy score by class and regime is in `research.json` (`l3.ic_by_class_and_regime`).

### 220. L4: within-class equity ranking against the global pool (V6.4.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (decided by rule: pooled equity + crypto ranks stay)

**Problem:** equity carries ~88% of the risk share at a Sharpe of ~0.23; does ranking inside equities (or inside sectors) beat the pooled equity + crypto rank?

**Fix:** W1 crypto leaves the main rank group, W2 `rank_signal.normalization: "sector_relative"`, W3 both. Shipped (best backtest median) iff the whole book stays non-inferior (>= -0.02 on both splits), the engaged equity IC and the equity sleeve's gross Sharpe rise on both splits, and the holdout Sharpe falls by <= 0.10 (one logged read).

**Verification:** `portfolio/rank_signal.py::sector_relative_scores`, `tests/test_rank_signal.py`, `tests/test_v640_round.py` (live and offline use the same function).

**Result:** W1 (crypto leaves the main rank group) lifts validation (+0.87 Sharpe) and loses on backtest (-0.31); W2 (sector-relative ranks) loses on both (-0.54 backtest); W3 -0.59. No variant keeps the whole book non-inferior, so the holdout veto was never read for a leader.

### 221. L5: turnover against IC - the rebalance / max-hold grid (V6.4.0)

**Severity:** 4/10 · **Status:** 🔴 `closed` (adopted offline, reverted by R-LEAN13 on BT6; the book stays 20 / 40)

**Problem:** with IC ~0.05 which (rebalance, hold) maximises the net Sharpe? V6's slower 20/40 book helped, yet the walk-forward net Sharpe is negative in 8 of 12 windows.

**Fix:** rebalance {10, 20, 40} x hold {20, 40, 60} against 20/40, as-live, across rebalance phases: shipped iff `verdict_as_live` passes and the median AND p25 phase Sharpe are >= the base's on both splits (at most one Lean confirm).

**Verification:** `scripts/v640_research.py` stage `l5`.

**Result:** Only R10/H20 passed the offline rule: as-live median Sharpe validation -0.45 -> +0.15, backtest +0.89 -> +1.06 (+0.17, bar +0.10), p25 +0.39 -> +0.68, turnover 7.5x -> 10.8x; every other cell failed. The confirming Lean run (#230) reversed it: with the 10 / 20 book and core-only crypto the strategy's Sharpe is -1.12 against +0.35 and its P&L -$10.9k against +$3.9k (fees $1,736 against $1,237, hit ratio 44% against 52%), so R-LEAN13 reverts it. The offline simulator tracks Lean's daily returns at a correlation of ~0.7 (R-CAL branch B) and does not price a faster book's costs and fills like the engine: a cadence change is not decidable offline. `config.json` keeps 20 / 40; the sim-side knobs stay.

### 222. L6: a staggered book judged on phase spread (V6.4.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (decided by rule: closed by its precondition, no variant scored)

**Problem:** S2 passed the level margins twice but widened the phase interquartile range (0.50 -> 0.67).

**Fix:** T2, T2h (half-way adjustment), T3, T3h, ungated: shipped iff the median >= base on both splits, the validation IQR <= base, p10 >= base on both splits, the cost drag rises <= 30%, and L1 showed the gate protects capital. The live tranche path is built only on adoption.

**Verification:** `portfolio/book_construction.py::partial_adjust_weights`, `tests/test_v640_round.py`.

**Result:** L1 found the gate hides weakness, so no tranche variant could ship; scoring them (about 1.5 hours of Codespace time) could not change the decision, and `scripts/v640_research.py` now closes L6 and L7 by `blocked_by_l1` unless `--score-blocked-stages` is given. The code that would score them (`partial_adjust_weights`, `simulate_rank_book(partial_adjust_fraction=)`) stays, tested, for a later phase.

### 223. L7: kill-switch design - the lock that one borderline order flips (V6.4.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (decided by rule: closed by its precondition, no variant scored)

**Problem:** at the -1.0 floor a few dollars moved the lock from 14 to 46 dates (#200); R-KILL rejected "lock less often".

**Fix:** `risk.kill_switch.trip_confirm_bars` (default 1 = today) through the same function live and offline; KD1 confirm 3, KD2 120 bars + confirm 3, KD3 release -0.5 + confirm 3, KD4 floor -1.5. Shipped (lowest false-lock share) iff the false-lock share (a lock before the unlocked book's top-third 20-day return) is below KS0's on both splits, the p95 phase drawdown <= KS0's + 0.5 pp, stability >= KS0's, the Sharpe change >= -0.02, and L1 holds. The switch already reads strategy-only returns (V6.2), so that option is the status quo.

**Verification:** `risk/kill_switch.py`, `evaluation/kill_switch_replay.py::false_lock_share`, `tests/test_kill_switch.py`, `tests/test_v640_round.py`.

**Result:** Closed with #222 by the L1 precondition. `risk.kill_switch.trip_confirm_bars` (default 1) ships as a tested, default-off knob with its false-lock measure (`false_lock_share`); the strategy-only equity option is the V6.2 status quo.

### 224. L8: which experts earn their place in the legacy signal? (V6.4.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (decided by rule: every expert stays)

**Problem:** the four regime experts and the gating blend feed only the legacy signal (the main book ranks on the rank heads); attribution is by class, not by expert.

**Fix:** contribution(e) = IC(legacy score) - IC(legacy score without e) on the engaged equity dates, both splits; experts at <= 0 on both splits are disabled together (`gating_network.disabled_experts`) iff the book is non-inferior as-live (>= -0.02 on both splits).

**Verification:** `moe/gating.py` (`excluded_experts`), `scripts/build_legacy_probability.py::legacy_probability_from_components`, `tests/test_gating_network.py`.

**Result:** No expert is at or below zero contribution on BOTH splits (bullish +0.012 / -0.001, bearish -0.010 / +0.009, sideways +0.007 / -0.017, volatility +0.003 / -0.0002 IC points on the engaged equity dates): nothing is disabled. The contributions flip sign between splits, which is noise-sized next to IC 0.01.

### 225. L9: crypto core against graduates - a repeatable rank effect or a few fills? (V6.4.0)

**Severity:** 3/10 · **Status:** 🔴 `closed` (adopted offline, reverted by R-LEAN13 on BT6; crypto graduates stay in the book)

**Problem:** crypto_core made ~+$3.9k on 13 fills; the graduates +$85 on $141 of fees.

**Fix:** bootstrap by trade on BT4's closed trades, leave-one-name-out (as-live), crypto IC; graduates on against off (only BTC / LTC selectable): graduates stay iff they beat core-only on the median Sharpe of BOTH splits.

**Verification:** `evaluation/trade_bootstrap.py`, `tests/test_trade_bootstrap.py`.

**Result:** BT4's closed trades: the core (BTC, LTC) made 13 round trips, mean +$302 (95% bootstrap interval +$73..+$601), BTC +$1,705 and LTC +$2,225, the three best trades 79% of its P&L; the graduates 61 round trips, mean -$1.1 (interval -$19..+$18), net about -$70. As-live, graduates on / core only: validation +0.15 / +0.07, backtest +1.06 / +1.08, so the owner's rule shipped core-only offline. BT6 (#230) changed the book AND the graduates together, failed R-LEAN13 and both changes were reverted; the effect of core-only alone was not measured in Lean. `class_weight_caps.crypto.core_only` (default false, `crypto_graduate_excluded`) stays as a tested knob.

### 226. L10: the residual rank head as a blend component (V6.4.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (decided by rule: the residual head stays demoted)

**Problem:** `residual_rank_20d` was demoted yet shows a positive walk-forward IC (~0.024).

**Fix:** blends R1 (0.4 / 0.4 / 0.2), R2 (0.35 / 0.35 / 0.3), R3 (0.5 / 0 / 0.5) over rank_20d / rank_5d / residual_rank_20d, as-live: shipped iff `verdict_as_live` passes and neither the market nor the momentum loading of the book moves by more than 0.10.

**Verification:** `scripts/v640_research.py` stage `l10`.

**Result:** R1 (0.4 / 0.4 / 0.2) -0.12 backtest Sharpe and -0.42 validation, R2 -0.32 / -0.27, R3 +0.02 / -0.32: none passes.

### 227. L11: book-call probabilities in Lean, and the Lean-vs-offline parity rule R-L11 (V6.4.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (R-L11 verified on BT5)

**Problem:** the Backtest Statistics' classification table showed n/a log-loss for the Lean book calls: the book history dropped the head probabilities `main.py` already held.

**Fix:** `diagnostics.book_history.include_probabilities` (a diagnostic, never an order input) logs `probability_up` and the two models' `direction_20d` per allocated and decided symbol; `evaluation/classification_parity.py` scores Lean and the offline head on the identical calls. R-L11 tolerance: |accuracy delta| <= 0.01, |neg log-loss delta| <= 0.01, median |probability gap| <= 0.005.

**Verification:** `tests/test_classification_parity.py`, `tests/test_v640_round.py`; BT5 (below).

**Result:** BT5 (`backtests/2026-10-22_10-56-13`) logged the probabilities; all 444 book calls matched an offline prediction: accuracy of the head's own call 54.73% (Lean) against 54.50% (offline), delta +0.0023; negative log-loss -0.7157 against -0.7149, delta -0.0008; median |probability gap| 1e-16, max 0.029 - inside the 0.01 / 0.01 / 0.005 tolerance. The Classification Scores row now has a Lean log-loss. The head's call is a coin flip (log-loss 0.716 against 0.693): the parity is exact, the information is not there.

### 228. L12: the paper-period protocol and its band check (V6.4.0)

**Severity:** 4/10 · **Status:** 🟡 `partial` (protocol, tool and frozen bands shipped; the paper run itself needs the IB paper account)

**Problem:** every recent rule names paper trading as the honest test, with no pre-registered success criterion.

**Fix:** frozen config; at least 6 rebalances and 120 trading days; success = every checklist metric inside the 5-95% band of the contiguous 6-rebalance windows of the pinned final Lean run (veto rate, kill-switch lock share, strategy exposure, fills per rebalance, slippage, fee bps, strategy and sweep P&L per day, hit ratio, turnover); no live capital. `diagnostics.book_history.paper_enabled` writes the bounded book history in paper mode; `aq evaluate --paper-check` compares.

**Verification:** `evaluation/paper_protocol.py`, `tests/test_paper_protocol.py`; a tool dry run on BT5's tail after 2026-09-30, labelled as such.

**Result:** Frozen bands (5-95% of the 166 contiguous 6-rebalance windows of BT5, `backtests/2026-10-22_10-56-13`, the run of the shipped config; `ml/evaluation/v640/paper_bands.json`): veto_rate 0..1; lock_rebalance_share 0..1; strategy_gross_exposure 0.01115..0.2819; fills_per_rebalance 0..15.83; median_slippage_bps 1.644e-12..5.002; p90_slippage_bps 1.644e-12..51.42; fee_bps_per_turnover 2.725..17.98; strategy_pnl_bps_per_day -4.355..16.37; sweep_pnl_bps_per_day 0.4483..1.067; daily_hit_ratio 0.125..0.625; annualized_turnover 0..8.653. The veto-rate and lock-share bands span 0..1 (the gate and the kill switch flip from window to window), so only the exposure, fills, slippage, fee, P&L, hit-ratio and turnover bands can fail a paper run. `aq evaluate --paper-check` on BT5's own 2026-04..10 window lands inside every band, as it must (a tool dry run, not a paper result).

### 229. BT5 (Lean, V6.3's book plus the probability logging, 2023-07-01..2026-10-16) equals BT4 order for order (V6.4.1)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (the baseline of the phase)

**Problem:** prove the V6.4.0 instrumentation is a no-op on the trading path, extend the span to the appended data, and give R-L11 its Lean run (the Codespace budget was spent, so this ran on the PC's own Docker).

**Fix:** none needed: 1,596 of 1,596 order events through 2026-09-30 are identical to BT4's (`ml/evaluation/run_configs/v640_bt5.json`), plus 50 events in October; the engine log reaches the teardown (the PC's usual timeout).

**Verification:** net +$14,770 (Lean Sharpe -0.11), strategy without the sweep +$3,904 (Sharpe +0.35, deflated 29%), drawdown 4.33%, fees $1,237: October 2026 cost the strategy about $2.2k against BT4's +$6,093. `aq evaluate --lean-report` ran with 0 failed steps (#227).

### 230. BT6 (Lean, the adopted 10 / 20 book + core-only crypto) fails R-LEAN13 and is reverted (V6.4.1)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (decided by rule; `config.json` unchanged from BT5's book)

**Problem:** #221 and #225 were adopted by the offline rules; the pre-registered confirm is one Lean run judged by R-LEAN13 (strategy Sharpe not below the baseline's by more than 0.10, drawdown within +1 pp, a complete run).

**Fix:** `evaluation/lean_verdict.py` (`python -m evaluation.lean_verdict --baseline <BT5> --candidate <BT6>`): BT6 (`backtests/2026-10-22_12-41-40`, `v640_bt6.json`) made -$2,329 net, the strategy -$10,937 (Sharpe -1.12 against +0.35), drawdown 5.20% against 4.33%, fees $1,736 against $1,237, 1,873 order events against 1,646, hit ratio 44% against 52%: the Sharpe clause fails, so the three keys are back at 20 / 40 / graduates in.

**Verification:** `ml/evaluation/v640/r_lean13.json`; `tests/test_lean_verdict.py`. The run is the first Lean evidence that the offline as-live simulator cannot rank book cadences (it said +0.6 Sharpe on validation and +0.17 on backtest).
