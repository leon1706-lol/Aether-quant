# Problems

<p align="center">
  <img src="https://img.shields.io/pypi/v/aether-quant?style=flat-square&labelColor=1A1A1A&color=FF8C00&logo=pypi&logoColor=white" alt="PyPI version">
  <img src="https://img.shields.io/badge/tests-3535%2F3535%20passing-brightgreen?style=flat-square&labelColor=1A1A1A" alt="3535 of 3535 tests passing">
  <img src="https://img.shields.io/badge/python-3.10%2B-FF8C00?style=flat-square&labelColor=1A1A1A&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/%F0%9F%93%84%20license-PolyForm%20Noncommercial%201.0.0-8B5CF6?style=flat-square&labelColor=1A1A1A" alt="License: PolyForm Noncommercial 1.0.0">
  <img src="https://img.shields.io/badge/problems-186%20entries-0097E8?style=flat-square&labelColor=1A1A1A" alt="186 problem entries">
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

---

### 1. `experience-worker` crash loop — missing `numpy` dependency

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/observation_metrics.py` imports `numpy`; `requirements-worker.txt` (backing `experience-worker`) never listed it — container crash-looped with `ModuleNotFoundError`.

**Fix:** Added `numpy>=1.24.0`; same proactively applied to trigger-worker requirements.

**Verification:** Rebuilt/restarted; clean startup via `docker compose logs`.

---

### 2. `Dockerfile.worker` missing `execution/` copy

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/simulated_portfolio.py` imports `execution.order_gate`; `Dockerfile.worker` never copied `execution/` — rebuild would fail with `ModuleNotFoundError`.

**Fix:** Added `COPY execution/ ./execution/`; same pattern applied to `Dockerfile.trigger_worker`.

**Verification:** Caught via import-graph tracing pre-rebuild; standing lesson documented in `development/architecture.md`.

---

### 3. Simulated portfolio/positions snapshot not mode-aware

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Webui Positions panel/summary always read real (flat, uninvested) `self.Portfolio` even in `observation` mode, contradicting mode-aware drawdown beside it.

**Fix:** Added `_snapshot_portfolio_summary()`; `_snapshot_positions()` mode-aware via `SimulatedPortfolioState` when real orders blocked.

**Verification:** Live screenshot review with user.

---

### 4. Webui: empty space above Market Scene panel

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** CSS Grid default `align-items: stretch` padded shorter left column to match taller right column.

**Fix:** `items-start` on outer grid; wrappers → `flex flex-col gap-4`.

**Verification:** Live Playwright screenshot review.

---

### 5. Webui: Signal Distribution / Rejected By Reason tables overflow the panel

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Long reason strings forced `<table>` wider than its Grid track; default `min-width: auto` blocked shrinking.

**Fix:** Flexbox rows replace `<table>`; added `min-w-0`, `break-words`.

**Verification:** Same screenshot review as #4.

---

### 6. `aether-grafana` container name collision blocks the real Grafana service

**Severity:** 3/10 · **Status:** 🟢 `fixed` (moot, no code change needed)

**Problem:** Orphaned unmanaged `aether-grafana` container (port 3000, non-compose volume) would have blocked `docker compose up -d grafana` (same name).

**Fix:** No action — Grafana removed from stack in V2-18 (replaced by React tracing dashboard); collision moot.

**Verification:** Re-checked 2026-07-04: no such container; no `grafana` service exists anymore.

---

### 7. ~85GB of orphaned duplicate Lean engine images + stale containers/volumes

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Two untagged 42.5GB `quantconnect/lean` images, stale one-off containers, unused pip-cache volumes, stray/unpinned tags accumulating disk.

**Fix:** Removed confirmed orphans (`docker rmi`/`docker volume rm`) after two passes — first missed image `650dd8d4063a` plus unrelated Grafana volume/image, corrected on follow-up.

**Verification:** Re-verified via `docker images -a`/`docker volume ls`; Aether-Vault items untouched.

---

### 8. Bare `pytest` (no path) fails from repo root

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** Bare `pytest` also crawled `backtests/*/code/tests/` (each backtest copies full algorithm code incl. tests) — ~76 duplicate-module-name collection errors.

**Fix:** `pyproject.toml` `[tool.pytest.ini_options]` sets `testpaths = ["tests"]`.

**Verification:** README's `pytest tests/` form still works; bare `pytest` works too.

---

### 9. Total-drawdown trade lock never auto-clears within a run

**Severity:** 4/10 · **Status:** 🟢 `addressed` (manual override, not a default-behavior change)

**Problem:** Total-drawdown lock never clears within a run (unlike daily lock) — real run showed it blocking ~79% of events after one early breach. Treated as intentional capital-preservation behavior, not silently patched.

**Fix:** Added `phase_v2.risk.manual_trade_lock_override` (read once per session rollover), `aq trade-lock --on/--off/--auto` CLI, auto-clear-on-successful-promotion hook in `retraining/orchestrator.py::promote()`. Default sticky behavior unchanged.

**Verification:** Documented in Manual Trade-Lock Override Contract (`development/architecture.md`).

---

### 10. `ci.yml`'s `test` job fails on GitHub's Linux runner — root cause found and fixed

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** The first clean-install bare-`pytest` CI run surfaced four masked problems: a nonexistent PyPI package name, pytest not adding the repo root to `sys.path`, two reference files swallowed by a blanket `.gitignore` rule, a Python 3.11-vs-3.14 float-summation difference in `empirical_duration_beta()`, and a Lean-backtest skip-guard checking binary presence rather than a usable Lean Data folder.

**Fix:** Corrected the package (`lean>=1.0.225`), set `pythonpath = ["."]`, committed both reference files via a `.gitignore` exception, replaced the exact-zero variance check with a `<1e-12` tolerance, and required a real Lean Data file in the skip guard.

**Verification:** The four previously-failed tests plus three new regression tests pass locally, and a real GitHub Actions run passed post-fix (user-confirmed).

---

### 11. `_write_state()`'s per-bar throttle was unreachable

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Dead guard clause meant 7 output files fully rewritten every bar instead of once per timestamp.

**Fix:** Removed impossible clause (`if ... and signals is None`).

**Verification:** Found during latency audit of `main.py` hot path.

---

### 12. `observation_equity_curve.csv` quadratic rewrite (N-per-bar entries + full-file rewrite every bar)

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `mark_to_market()` ran once per symbol per bar, producing `N·B` equity-curve entries instead of `B`, and #11's every-bar flush plus full-file CSV rebuild made write cost `O((bars·symbols)²)`.

**Fix:** `on_data()` now accumulates closes and calls `mark_to_market()` once per bar, with an append-only flush (`_flush_observation_equity_csv()`) tracked by a written-count offset.

**Verification:** A unit test asserts one entry per multi-symbol call; row-count-equals-bar-count was confirmed via real Lean backtest output.

---

### 13. Per-bar/per-poll `config.json` reads on every session rollover, uncached

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** At Daily resolution the once-per-session rollover check fires every bar, each firing doing uncached `open()`+`json.load()` of `config.json` in several places (`main.py`, `retraining/worker.py` poll loop).

**Fix:** New `execution/config_cache.py::read_cached()`, an mtime-gated cache keyed on both path and loader (a path-only key collided across readers and crashed `_recompute_broker_config()` on bar 1 of a real backtest).

**Verification:** New `tests/test_config_cache.py` (with a collision regression), re-confirmed via a real Lean backtest re-run.

---

### 14. Redis push in backtest mode — deliberately left unoptimized

**Severity:** n/a · **Status:** 🟢 `resolved` (confirmed no-op, no code change needed)

**Problem:** `experience/redis_queue.py::push()` does blocking Redis write every bar even in backtest mode — skippable for perf, but unconfirmed downstream dependency made skipping risky.

**Fix:** No code change — owner confirmed nothing reads backtest-mode experience events downstream from Postgres.

**Verification:** Direct owner confirmation, not testing.

---

### 15. `ensure_derived_crypto_daily_series()` silently discarded yfinance-backfilled crypto history on every `train.py` run

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** Function rebuilt derived crypto daily zips (ETHUSD/LTCUSD) via full-overwrite `ZipFile` write from sparse raw minute data, wiping 1000+ days of yfinance-backfilled history to 3-4 rows every `train.py` run.

**Fix:** Reads existing zip, merges by date — fresh minute-derived rows win only where real minute data exists; other dates survive.

**Verification:** Regression test `test_ensure_derived_crypto_daily_series_merges_with_existing_backfill`.

---

### 16. `main.py::initialize()` exceeded Lean's hard 90-second isolator timeout at 20 assets

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** Loading all model/expert/topology artifacts plus deriving ~40 config values inside `initialize()` pushed isolator-timed cost past Lean's non-configurable 90s cap at 20 assets, so every `lean backtest .` failed.

**Fix:** Split into a minimal Lean-critical path (dates/cash/subscriptions/warm-up) plus `_ensure_ready()` carrying artifact/config loading, deferred to the first `on_data()` (no isolator limit there).

**Verification:** Disk-log instrumentation (a timed-out `initialize()`'s `self.Debug()` is silently lost) confirmed `initialize()` completes in 1.85s with a ~51s full window; the 525-test non-Lean suite stayed green.

---

### 17. Matplotlib font cache rebuilt from scratch on every single `lean backtest .` run

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Lean's `AlgorithmImports` bridge imports matplotlib, so ephemeral per-run containers rebuilt the font cache (20-40s) every run, occasionally breaching the 90s isolator cap even after #16.

**Fix:** `main.py` sets `MPLCONFIGDIR` to a host-mounted `.matplotlib_cache/` before any other import, so the cache survives containers.

**Verification:** Two consecutive real runs: ~82s import cold vs ~58s warm, zero timeout.

---

### 18. Two structural "never recovers" traps suppressed real backtest trade count to 12 over 3 years

**Severity:** 5/10 · **Status:** 🟢 `addressed` (opt-in statistical bypass, default behavior unchanged)

**Problem:** A one-time mass liquidation crossing the 12% total-drawdown limit froze trading for the remaining 374 days of a 3-year backtest — the sticky lock plus a `peak_equity` running-max that never fell meant it could never self-clear; an earlier-firing 8% twin sat in the regime `risk_off` drawdown branch.

**Fix:** Opt-in `phase_v2.backtest.bypass_safety_gates` (default `false`, backtest-only) bypasses only these two mechanisms, with other gates fully active and live/paper unaffected.

**Verification:** Scoped to statistical/model-quality backtesting only (never representative of live behavior) and deliberately not wired into `aq trade-lock`.

---

### 19. Neural-network webui tab's gating exclusion went stale the moment gating became learnable

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Gating hardcoded excluded from `/neural-network` list ("no learned weight matrix"); 3D scene render order hardcoded to exactly 5 names — both stale once gating gained optional learned model.

**Fix:** Removed gating from exclusion list; wired through generic network-summary path; added to render-order array.

**Verification:** Standing gotcha noted: render-order array is silent filter needing manual updates for anything new to appear in 3D scene.

---

### 20. `Dockerfile.retraining_worker` never copied `risk/`, so `retraining.worker` could not have started

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `retraining/orchestrator.py` imports `risk.manual_override` at module level; COPY list lacked `risk/` — every start crashes with `ModuleNotFoundError`.

**Fix:** Added `COPY risk/ ./risk/` (lightweight) plus `COPY train_multitask.py .` for that session's retraining stage.

**Verification:** Found via static import-graph tracing pre-rebuild. **Image still needed rebuild** to pick up fix — not run this session.

---

**Update (2026-10-06, V5.5.0):** superseded by #30 - the consolidated engine image removed the per-worker `COPY` lists this entry concerned.

### 21. Per-bar model forward-pass count doubled (5 → 11) — measured, not currently a problem

**Severity:** 2/10 · **Status:** 🟢 `measured, not currently a problem`

**Problem:** Multitask/sequence models roughly doubled per-symbol-per-bar forward passes (5 → 11; batching keeps top-level calls at 5), never measured against any budget.

**Fix:** No code change — measured via `aq profile --batched`: ~12ms mean/symbol/bar, negligible vs only enforced constraint (Lean's 90s `initialize()` isolator cap, unrelated to per-bar cost).

**Verification:** 10,000-iteration profiling runs (batched/unbatched) with real exported weights; sequence encoder causal conv flagged largest remaining cost / future optimization candidate.

---

### 22. `tests/test_retraining_worker.py` silently ran real training (subprocess-level hang, up to ~30 minutes per test)

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** 7 of 10 tests never updated to mock newer `train_multitask`/`train_sequence` stages — with real artifacts present they fell through to genuine subprocess training, up-to-30-minute timeouts (looks like hang).

**Fix:** Added `patch("retraining.worker.train_multitask")`/`train_sequence` to all 7, matching existing mock pattern.

**Verification:** Previously-hanging test ~1.2s; full 10-test file ~1.2s total.

---

### 23. BTCUSD volume-feed unit discontinuity blew up the sequence model's RMSE 31x

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** BTCUSD raw volume jumped ~520,000x on one date (a real Coinbase feed unit-convention change), producing a 5.2-million-percent single-day "return" through an unclipped `StandardScaler` that poisoned 30 rows of the sequence window — 66%+ of the backtest's squared error.

**Fix:** Three layers: clamp `volume_change_1d` to `[-1.0, 20.0]`, winsorize scaler-fit columns pre-fit, and clip scaled values to `±10σ` (persisted to `scaler_stats.json` so `main.py` applies the same bound at runtime), plus an automated regression-quality gate.

**Verification:** Post-fix the max absolute scaled value is exactly 10.0 (clip firing) and the retrained RMSE/MAE ratio fell 31x → 1.59x.

---

### 24. `train.py` never applied Lean's own split/dividend factor files — offline dataset had fake ±74%/+745% "returns"

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `train.py`'s independent raw-zip reader bypassed Lean's split/dividend adjustment, so real corporate actions (AAPL's 2020 4-for-1, USO's reverse split) produced fake ±74%/+745% "returns" in every label/feature spanning the boundary — an offline train/runtime parity gap (Lean's own engine was unaffected).

**Fix:** New `train.py::apply_split_adjustments()` reads each equity's real Lean factor file and rescales OHLCV exactly as Lean does; `yfinance_backfill.py` switched to `auto_adjust=True`, with a per-security-type label-outlier guard as defense-in-depth.

**Verification:** On real data the AAPL split-boundary "return" fell from -74% to ~3.4% and USO's from +745% to ~5.6%.

---

### 25. No quality gate ever existed for regression heads (magnitude/volatility/rank) — only direction MCC was gated

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Only direction models quality-gated; regression heads had none — how #23's 31x blowup shipped silently a whole session.

**Fix:** New `train.py::assess_regression_quality()` gates on RMSE/MAE and backtest/train RMSE ratios; wired into `train_multitask.py`/`train_sequence.py`; surfaced on `/neural-network`.

**Verification:** Mirrors `assess_expert_quality()` shape/convention.

---

### 26. `main.py`'s sequence-model runtime buffer size never read the trained model's own `window_size`

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** Runtime buffer size came only from `config.json`, never model schema — retrained model with different window silently disabled sequence signal via shape-mismatch exception, unsurfaced.

**Fix:** New `resolve_sequence_window_size()` — schema value wins when loaded; config fallback otherwise.

**Verification:** Extracted as pure function for unit-testability outside Lean runtime.

---

### 27. Phase 2's new era/fold-splitting functions crashed on real training runs — assumed datetime input, but the real dataset's `date` column is plain strings

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `split_into_non_overlapping_eras()`/`purged_embargoed_folds()` did Timestamp arithmetic on `np.asarray(dates)`, correct only for datetime input — real callers pass stringified date columns, so the first real run crashed despite all unit tests passing on synthetic datetime fixtures.

**Fix:** Both functions (and an identically-bugged caller) coerce via `pd.to_datetime(np.asarray(dates))`, robust to string/Timestamp/datetime64.

**Verification:** New regression tests use plain string dates with real object-array shapes, closing the "passes unit tests, fails first real run" gap.

---

### 28. Portfolio book's `"short"` signal silently zeroed to no position

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `_build_dynamic_sizing_payload()` guard recognized only `{"buy", "sell"}` — never updated when `"short"` became valid, so book-selected shorts sized to exactly zero. Never observed in practice (book feature defaults off).

**Fix:** Guard recognizes `{"buy", "sell", "short"}`.

**Verification:** Covered implicitly by portfolio-book suite plus future end-to-end backtests with book enabled.

---

### 29. Multi-asset-class support (bonds/futures/options + IB) — explicit non-goals

**Severity:** n/a (scope note) · **Status:** 🟢 `fixed` (core multi-asset-class trading is fully implemented; remaining items are permanent non-goals)

**Problem:** Tracked multi-asset-class gaps after the initial architecture pass — options order placement against a resolved contract, real derivatives-macro data, per-asset-class book slot caps — were originally deferred.

**Fix:** All three resolved later: real option-contract order placement, real futures/options derivatives-macro features (offline and live), and an optional `per_asset_class_slots` book parameter (default `None`, byte-identical to the prior pooled ranking).

**Verification:** Seven new tests for per-class slotting (ranking, exclusion, thin-class isolation, confidence-spread gating, backward compat); the remaining items (ML-driven multi-leg spread selection, IBC headless TWS login, live IB margin, bulk historical derivatives fetch) are permanent non-goals tracked in README Known Limitations.

---

### 30. `Dockerfile.retraining_worker` missing `data_pipeline/` (and pre-existing: `liquidity/`) copy

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** A top-level `data_pipeline.fred_backfill` import was never copied into `Dockerfile.retraining_worker`, which also pre-existing missed `liquidity/` — either would crash the first retrain.

**Fix:** Both COPYs were added, then the whole class was structurally eliminated by the July 17 consolidation (the Dockerfile is gone; compose builds a consolidated `aether-quant-engine:latest` via `COPY . .`).

**Verification:** Import-graph tracing (#2/#20 method) confirmed directly — the bug class is now impossible.

---

### 31. Infrastructure/latency pass — `aq test` silently ran a real Lean backtest, per-bar inference hot path never profiled, CI Docker builds never cached

**Severity:** 8/10 (aq test) / 6/10 (inference latency) / 4/10 (CI cache) · **Status:** 🟢 `fixed`

**Problem:** `aq test`'s Lean-backtest file checked binary presence only, so routine runs paid a real (over-an-hour) backtest cost; the inference hot path was unprofiled and CI Docker release builds were uncached.

**Fix:** Opt-in `lean_backtest` pytest marker (excluded by default; `--lean`/`--full` opt-in) plus per-subsystem `aq test` flags, a new `scripts/profile_inference.py` harness, hot-path fixes (causal-conv Python loop → batched `einsum`; four per-expert dispatch calls → one batched), and `cache-from`/`cache-to: type=gha` on the release Docker step.

**Verification:** Collect-only 1132/1143 (11 deselected), non-Lean run >1h → ~73s-4min; a 10k-iteration real-weight workload measured 448.4s→290.6s (-35.2%), with a 200-trial fuzz parity check between the old loop and batched conv1d.

---

### 32. Latency deep-dive follow-up — weight-array/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension attempt

**Severity:** n/a (optimization pass) · **Status:** 🟢 `fixed`

**Problem:** Re-profiling after #31 showed repeated `numpy.asarray()` conversions of the same static JSON-loaded weights every bar were the largest remaining cost.

**Fix:** `convert_state_dict_arrays()` converts once at load (no downstream API change), batched-stack caching precomputes expert weights in `_ensure_ready()`, and it added `aq profile`, opt-in per-symbol multiprocessing (default off, sequential fallback), and a C++/pybind11 extension (`cpp_inference_ext`) accelerating the batched linear layer.

**Verification:** Measured 448.4s→48.4s (-89.2%; mean 44.8ms→4.83ms per symbol/bar); 14 parity tests prove the cached path bit-identical. A naming-collision bug and a wrong-Python-env install were caught during verification; the multiprocessing win/loss was left to a real backtest and not enabled this pass.

---

### 33. Execution/risk realism pass — real `SlippageModel` wired to fills

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `build_liquidity_decision()` computed a real spread+impact estimate every bar that nothing consumed — no security had a `SlippageModel`, simulated fills hardcoded zero slippage, and historical backtests had systematically too-good fills.

**Fix:** Pure `slippage_amount()`/`resolve_slippage_bps()`/`resolve_fill_slippage()` in `execution/order_gate.py`, threaded into both the Lean fill path (a new `_LiquidityAwareSlippageModel` adapter) and the simulated-fill path; the cost source and safety clamp were later made config-configurable.

**Verification:** 12+13 new tests (`test_order_gate.py`/`test_simulated_portfolio.py`) including default-vs-explicit-zero parity; the adapter itself is not unit-testable in isolation (the usual `main.py`-outside-Lean constraint), so the logic lives in tested pure functions.

---

### 34. Real limit-order support — every tradable asset class, config-gated

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` (V5.3.1, #96; `PartiallyFilled` staying unobserved is a permanent, honest caveat — not a blocker, see below)

**Problem:** Every real order was all-or-nothing `MarketOrder()`/`SetHoldings()` fill across all 5 asset-class call sites; no limit-order alternative.

**Fix:** Config-gated (`phase_v2.limit_orders`) real `LimitOrder()` support, all 5 classes: shared `_try_submit_limit_order()`, real `on_order_event()` fill callback, per-class timeout/fallback-to-market; futures quantity-sign + option contract-vs-chain-symbol bookkeeping bugs caught/fixed during implementation.

**Verification:**
- 12 pure-function + 4 CLI reachability tests; fired in real backtest (2026-07-20, #54): real `LimitPrice was rounded` log line.
- V5.2.8: 33 real `order-events.json` scanned — statuses `{submitted, filled, canceled, cancelPending, invalid}`; `cancelPending`:`canceled` pairs 1:1 (e.g. 644/620/23/23), genuine unfilled-timeout cancels; `classify_order_status()` classifies `"CancelPending"` explicitly (precision fix). `PartiallyFilled` never appeared — permanent honest caveat.
- V5.3.1 (#96): flag was `enabled: true` by default all along (this entry's own text above was stale — corrected inline docs, kept here as historical record); evidence widened to 45 files, same pattern; partial-fill handling unit-tested via two extracted pure functions; two offline diagnostic tools shipped.
- **V5.3.1 real backtest confirmation (2026-08-14, #98):** extracted functions (`should_clear_pending_limit_order()`/`resolve_limit_order_timeout_action()`) live-exercised first time — identical 12/12 pairing, zero regressions. `PartiallyFilled` still absent (permanent caveat — Daily-resolution fill granularity makes true partials rare/absent by construction). Marking green.

---

### 35. Disabling an asset class never liquidated already-open positions

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Flipping `phase_v2.futures_risk.enabled`/`options_risk.enabled` false mid-run zeroed new sizing but left already-open positions (signal derivation unaware of flags) — sat untouched, silently failing every bar.

**Fix:** Pure `resolve_asset_class_enabled()`/`should_liquidate_disabled_asset_class_position()` + per-bar sweep `_liquidate_positions_for_disabled_asset_classes()` liquidating newly-disabled classes' real/simulated positions; equity/crypto/bond have no such flag.

**Verification:** Truth-table tests for both; parity test: simulated exit matches calling `exit()` directly. One item unverified until a real backtest: reading `Portfolio[...].Invested` at new, earlier point in bar execution order.

---

### 36. Latency profiling extended beyond inference — `build_market_topology()` found to be a much larger per-bar cost than the entire inference step

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified`

**Problem:** Per-bar subsystems besides inference (regime, topology, liquidity, gating, analyzer, indicators) never profiled. `build_market_topology()` costs ~500-600ms/call — comparable to or larger than whole-universe inference — once per bar.

**Fix:** `scripts/profile_subsystems.py` harness + `aq profile --<subsystem>` flags. Follow-up fix: opt-in (`phase_v2.topology.cache_enabled`, default off) correlation-stability cache skipping expensive embedding when pairwise correlations unchanged beyond tolerance since prior bar; later update: self-relative percentile-based tolerance mode as alternative to fixed threshold.

**Verification:** Tests prove zero embedding calls fire when correlations provably unchanged (mocking), plus tolerance-exceeded/universe-changed/missing-state fallbacks; ran cleanly across full real 2019-2021 backtest (2026-07-20, #54). **Honest caveat preserved:** whether correlation stability holds often enough on *real* market data never established from synthetic data — left off pending dedicated real-data calibration session.

---

**Update (2026-10-06, V5.5.0):** the topology cache is now enabled in `config.json` (`cache_enabled: true`, percentile tolerance 75); reuse hit counts are reported by the opt-in V5.5.0 timing probe (#129).

### 37. Inference tail latency (p99 3-5x p50) — investigated and fixed

**Severity:** 4/10 · **Status:** 🟢 `fixed and verified`

**Problem:** No prior investigation into why p99 ran 3-5x p50 (fact known from #32); separate stale on-disk profiling output showed misleadingly bad numbers, regression status unclear.

**Fix:** Harness reran multiple times — discrepancy was a stale/unrelated local run, not regression; iteration bucketing ruled out warmup; `--no-gc` isolated reproduced GC-pause contribution to max tail specifically; follow-up shipped `gc.freeze()` after model load, config-gated off pending backtest validation vs Lean's .NET/Python interop GC boundary.

**Verification:** Paired GC-on/off runs: max latency -66-95% with GC disabled, p50 unaffected (tail-only effect); `gc.freeze()` clean across full real backtest (2026-07-20, #54).

---

**Update (2026-10-06, V5.5.0):** `phase_v2.gc_tuning.freeze_after_load_enabled` is now `true`; `gc.freeze()` is one suspect for the teardown hang (#104) and the V5.5.0 teardown-cleanup experiment unfreezes before shutdown.

### 38. 2-leg vertical spread selection for options — explicit scope-in of a previously-non-goal feature

**Severity:** n/a (feature scope-in) · **Status:** 🟡 `partial`

**Problem:** Multi-leg spread selection was explicit non-goal (#29); this pass closes minimal 2-leg vertical-spread slice.

**Fix:** New `select_vertical_spread_legs()`/`build_vertical_spread_position_sizing()` (net-vega sized), wired through `risk/asset_class_router.py` + new `_apply_option_spread_order()` using Lean's own `OptionStrategies` atomic combo-order primitive (previously completely unused here); two real bugs (field-existence check ordering; early draft breaking option orders entirely for spread case) caught/fixed during implementation.

**Verification:** 20 new tests (leg selection/sizing/degrade paths) + critical zero-behavior-change parity for single-leg path. **Real-backtest verification still genuinely open** — no option/future asset configured in universe yet, so never exercised against real Lean order placement, margin, or partial-fill behavior.

---

### 39. Final pre-backtest bug sweep — 4 fixes found and fixed before this project's first real `lean backtest .` run

**Severity:** 6/10 (test-harness bug) / 5/10 (liquidity threshold collision) / 3/10 (limit-order timeout) / 2/10 (book-slot crash risk) · **Status:** 🟢 `fixed`

**Problem:** A final pre-backtest sweep found four defects: a wrong dict-key path silently failing three Lean coverage assertions, two liquidity thresholds collapsed to one value (merging a two-tier gate), a limit-order timeout handler contradicting the dependency's "unknown status = still pending" contract, and no shape validation on optional per-asset-class book-slot config.

**Fix:** Fixed the key path, restored the `thin < high_impact` ordering, made the handler pop-without-cancel only on genuinely terminal statuses, and added a `normalize_per_asset_class_slots()` pure validator degrading gracefully on malformed entries.

**Verification:** Six new validator tests; the other three fixes were verified by direct inspection/config check (pre-real-backtest by design), with the suite green after all four.

---

### 40. `aq backtest` silently re-pulled the ~42.5GB Lean engine image on every run

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `lean backtest .` resolved the mutable `quantconnect/lean:latest` unpinned, so whenever QC moved the tag even machines with the full 42.5GB image cached re-pulled — indefinitely, every clone and run.

**Fix:** Pinned the immutable `quantconnect/lean:17900` by default (always passed explicitly), with `aq backtest --image <other>` for deliberate newer-build opt-in.

**Verification:** Tests confirm pin-by-default plus the working override flag; documented in README Getting Started.

---

### 41. First real backtest: only 14 trades, none ever closed

**Severity:** 6/10 (blocks a statistically meaningful backtest) · **Status:** 🟢 `fixed` (superseded by #43)

**Problem:** First real backtest produced 14 orders, all openings, zero closes — model's `probability_up` clustered 0.46-0.49 vs buy/sell thresholds 0.50/0.42, almost nothing crossing either line. Secondary finding: soft `max_active_positions` cap (same-bar overshoot counting only already-filled positions).

**Fix:** None here — proposed threshold-tightening lever diagnosed but never shipped. #43 found real causes structural (position-cap overshoot, risk vetoes blocking exits, neutered circuit breaker, no exit mechanism) plus a training-pipeline defect, pivoting trading entirely to `rank_20d`/`portfolio_book`.

**Verification:** Diagnosis only, confirmed against real output files (`state.json`, order-events, logs).

---

### 42. Pre-live security review — broker/API credentials could be published; DB exposed to the LAN behind a repo-published password

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** A pre-live review found the runbook instructed hand-editing real IB credentials into git-tracked `lean.json`, `.dockerignore` didn't exclude secret files from published images, Postgres/Redis were published to `0.0.0.0` behind a password published in this public repo, and nothing structurally prevented future secret commits.

**Fix:** A credential render step (`aq render-lean-config`) overlays secrets from a gitignored `.env.live` onto a gitignored `lean.live.json` (tracked `lean.json` stays empty), the secret list is mirrored into `.dockerignore`, DB/Redis are bound to `127.0.0.1` with a fail-closed live-mode guard, and `aq secrets-check` plus an opt-in pre-commit hook were added.

**Verification:** New `tests/test_dockerignore_secrets.py` evaluates real Docker pattern semantics (not a literal line-grep); no secret exists anywhere in git history and there is no deserialization-RCE surface.

---

### 43. Full pre-live model overhaul: trading-logic bugs + training-pipeline bugs, pivot to the one significant signal

**Severity:** 9/10 · **Status:** 🟢 `fixed` (see #52/#54)

**Problem:** A second backtest after #41's recalibration produced bit-identical results (same 14 trades/profit), showing calibration had zero effect on actual trades — causes spanned trading logic (soft position-cap overshoot, sell-vetoing risk logic, a sell threshold ~10σ from live output, a neutered drawdown breaker, no stop-loss/trailing/max-holding-age exits) and training (untrained epoch-1 checkpoints, degenerate threshold search, an MoE blend diluting skill to 0.5, no skill-floor gates, 35/85 static one-hot inputs, ~52-row crypto training, and trading that ignored `rank_20d`/`rank_5d`, the only statistically significant signal).

**Fix:** Rewrote early stopping with a `min_best_epoch` floor, fixed the threshold-search bounds, unified asset-context columns, removed dead features, raised the `min_training_rows`/skill-floor gates, zeroed no-skill experts, wired `portfolio_book` to trade `rank_20d` directly, bypassed the exit veto, added safety exits (max holding age + trailing stop) and an adaptive sell band, fixed the same-bar position cap, re-armed the drawdown breaker, and fixed the crypto/`InteractiveBrokersFeeModel` crash.

**Verification:** Real backtest (2026-07-17) went from stuck-at-14 to 653 orders at 11.1% drawdown (mechanical fixes confirmed; still -4.6%/Sharpe -0.59), with tests extended across `train.py`, gating, `market_analyzer`, `validation_gate`, experts, and `portfolio_book_construction`; superseded by #52/#54's profitable rank-pivot backtest (Sharpe 0.403, Net +10.4%).

---

### 44. Lean CLI couldn't feed the retraining loop — undocumented second `requirements.txt` convention

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `main.py`'s `ExperienceQueue` silently no-oped during every real `lean backtest .` run because `redis` was missing: Lean CLI auto-installs deps from a project-root `requirements.txt`, separate from the repo's `requirements/requirements.txt` convention Lean never reads, and everything else happened to exist in the image.

**Fix:** A repo-root `requirements.txt` containing `redis>=5.0.0`, cross-referenced from `requirements/README.md`; later superseded by #88a's Lean CLI Windows dependency-mount workaround.

**Verification:** Confirmed by reading Lean CLI's source (`lean_runner.py`), with the real-run re-verification left to the user.

---

### 45. `av` (Aether-Vault CLI) was broken on this machine — never actually run once in this repo

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `retraining/vault_client.py`'s commit stage shells out to `av`, which failed every call (`ModuleNotFoundError: questionary`) and had never been initialized (`.av/` absent) — invisible because `commit_candidate_to_vault()` degrades gracefully by design.

**Fix:** Installed `questionary` into the correct environment (`av.exe` resolves via a separate user-scoped Python 3.14 install, not the repo `.venv`) and ran `av init --mode local -y --no-repl` in the repo root.

**Verification:** Confirmed via `av status`; local-only is accepted (no remote registry, degrading to a local pending-push queue).

---

### 46. `xreadgroup(block=0)` meant "block forever," not "don't block" — idle Redis-stream workers timed out every cycle

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/postgres_worker.py`/`audit/postgres_worker.py` called `xreadgroup(..., block=0)` believing it non-blocking, but Redis `BLOCK 0` blocks forever — with a client `socket_timeout=5`, every idle poll raised a timeout exception (invisible to `fakeredis`, which doesn't reproduce blocking-socket behavior).

**Fix:** Removed `block=0` from both call sites; the default `None` omits `BLOCK`, letting the existing correct `sleep(1)` idle loops work.

**Verification:** Real Compose Redis showed both workers at 0% CPU with zero errors; the 18 tests in `test_postgres_worker.py`/`test_audit_postgres_worker.py` pass unchanged (they never asserted on `block`).

---

### 47. `retraining-worker`'s `./data` volume mount was read-only — `train.py` could never complete inside the real container

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** Compose mounted `./data:/app/data:ro`, but crypto daily-series derivation (#15) must read-then-write `data/crypto/coinbase/daily/*.zip` every invocation, so the container crashed with `OSError: Read-only file system` — never caught before because rehearsals ran `train.py` on the (writable) host.

**Fix:** Changed the mount to writable (`./data:/app/data`).

**Verification:** A rehearsal re-run after `docker compose up -d --force-recreate` completes past this point.

---

### 48. Force-recreating `retraining-worker` mid-cycle orphaned a stuck `retraining_events`/`model_versions` row — no startup reconciliation existed

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Recreating `retraining-worker` mid-cycle killed the in-flight `train.py` before it reported back, leaving `retraining_events`/`model_versions` rows stuck `"running"`/`"candidate"` so the cooldown check blocked all future retraining; the container also ran `python -m retraining.worker` as PID 1 without an init process, so a subprocess killed on orchestrator timeout could become an unreapable zombie that blocked even `docker compose stop`.

**Fix:** Startup reconciliation `fetch_stale_active_events()`/`reconcile_stale_running_events()` marks stale `running`/`planned` rows `failed` (rejecting still-`candidate` `model_versions` rows) after a configurable `stale_running_timeout_seconds` (default 10800s), and `init: true` gives the Compose service Docker's tini so killed subprocesses are reaped.

**Verification:** Eight new tests across `postgres_registry`, `orchestrator`, and `retraining_worker`, suite green (1465 passed) before/after; the zombie scenario was hit live and manually recovered (`docker rm -f`) before `init: true`, and `docker compose config --quiet` is clean.

---

### 49. Full end-to-end retraining-loop rehearsal against the real Compose stack — three real cycles ran, all correctly rejected; rollback rehearsed both ways

**Severity:** n/a (operational-maturity verification, not a bug) · **Status:** 🟢 `verified`

**Problem:** N/A — a rehearsal to prove a genuine closed loop rather than mocked-unit-test logic; one follow-up (the `lean` CLI absent from the worker image, so `backtest_gate` silently no-ops rather than crashing) was a known deliberate infrastructure gap, later settled by #62.

**Fix:** None (verification exercise).

**Verification:** Three real cycles ran through the worker poll loop (`plan→train→train_topology→train_gating→train_multitask→train_sequence→validate`), with `train_sequence` timing out once at its 1800s cap (a real resource-constrained-host finding, not a crash); all three candidates were rejected on legitimate quality grounds (consistent with #43), and rollback was tested against real Postgres/files both ways (happy path flips `active`; a corrupted-hash tamper path is refused with nothing copied); `backtest_gate` was never organically exercised (nothing cleared `validate`).

---

### 50. This dev machine's 4GB RAM couldn't reliably run a real `lean backtest .` — blocked verifying #34/#36/#37/#38

**Severity:** n/a (hardware constraint) · **Status:** 🟢 `fixed` (superseded — see #54)

**Problem:** Four consecutive real `aq backtest` attempts failed at Lean's hardcoded 90-second `initialize()` isolator cap, root-caused to plain top-level imports (torch/pandas/sklearn) taking ~82 seconds under memory pressure (~300MB free on this 4GB host) — not a code regression; it blocked verification of #34/#36/#37/#38.

**Fix:** Narrowed `main.py`'s `from audit import ...` (which transitively pulled unused Postgres/status-export code) to `from audit.redis_queue import ...`, trimming in-window import cost; also documented that failed `lean backtest` containers aren't reliably cleaned up, leaving orphaned `lean_cli_*` containers holding memory.

**Verification:** `python -m py_compile main.py` and the suite were green; superseded 2026-07-20 (#54) when a real backtest completed on the same machine, verifying #34/#36/#37 (~40 min run needing manual zombie cleanup), with #38 still open for an unrelated reason (no option asset registered).

---

### 51. `GET /api/assets-status` 500'd in Docker — `lean.json` (entry #42's exclusion) was never mounted back in, and the reader didn't degrade gracefully

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `GET /api/assets-status` 500'd in real deployment: #42 excludes `lean.json` from the published image but nothing volume-mounted it back at deploy time, so `build_assets_status_from_disk()` hit an uncaught `FileNotFoundError`.

**Fix:** Added a read-only runtime mount (`./lean.json:/app/lean.json:ro`) on the `engine` service (never baked into the image, preserving #42); the reader now catches `FileNotFoundError` and degrades to an empty `lean_config` so `ib_readiness_status()` reports gracefully instead of 500ing.

**Verification:** New `test_build_assets_status_from_disk_degrades_gracefully_when_lean_json_missing`; all 8 tests in the file pass and the rebuilt container returns 200 with correct content where it previously 500'd.

---

### 52. The rank-pivot roadmap: trading path switched to `rank_20d`, universe expanded 30→74 assets, four Stage-4 regularization gaps closed

**Severity:** 9/10 · **Status:** 🟢 `fixed` (retrained and backtest-verified — see #54; one caveat still open, below)

**Problem:** Trading path traded the noise-objective direction head (backtest MCC ~0.02-0.04) instead of `rank_20d` — the one genuinely skillful signal — and even that far faster than its ~20-day horizon supports. Gaps: purged-CV configured but never called; no rank-IC early stopping; dead 1-day direction head fully weighted in loss; no seed-ensembling or cross-head consistency regularization.

**Fix:** Five config-gated changes: (1) `strategy_mode`→`long_short`, rank-based sizing enabled, sequence `rank_20d` blended into traded probability, book widened top/bottom 8; (2) 5-bar rebalance scheduler `should_rebalance_this_bar()` matching horizon; (3) universe 30→74 (54% equity/30% bond/16% crypto), dataset rebuilt to 113,804 rows; (4) rank-IC early stopping, dead direction-head loss down-weighted (not removed), seed-ensembling + horizon-consistency regularization in `train_multitask.py`/`train_sequence.py`; (5) previously dead `purged_embargoed_folds()` wired into real diagnostic (`purged_cv_rank_20d`). Also fixed `yfinance_backfill.py` `float()`-on-MultiIndex deprecated pandas fallback.

**Verification:** New functions unit-tested; suite green 1465→1497. Update 2026-07-20 (Codespaces retrain, #53): early stopping fired (best_epoch far off old floor); full-series IC improved — multitask 0.172/t=7.55 (vs 0.073/t=4.40), sequence 0.127/t=5.70. Open caveat: promotion bar (non-overlapping t-stat ≥ 2.0) unmet (multitask 1.40, sequence 0.43). Real backtest (2026-07-20, #54) profitable (Sharpe 0.403, Net +10.4%), confounded by concurrent `bypass_safety_gates` change.

---

### 53. GitHub Codespaces set up as cloud training offload; a real Alpine-base devcontainer bug found and fixed

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** The 4GB machine spent hours wall-clock on ~800 CPU-seconds of training (#50/#52), and Codespaces setup hit a real bug — the `docker-in-docker` feature silently swapped the pinned Debian image to Alpine, breaking `pip install` against musl libc (matching upstream `devcontainers/images#1114`); deeper, Codespaces containers run unprivileged so Lean/Docker backtests cannot run there at all (a platform limitation).

**Fix:** Dropped `docker-in-docker` (training needs none) and kept only `sshd`, prepended a CPU-only `pip install torch --index-url .../cpu` to `postCreateCommand` (a bare install resolved a GPU-failing CUDA build), and `.gitignore`d 9 inconsistently-tracked generated `ml/` artifacts.

**Verification:** Five systematic A/B Codespace rebuilds confirmed the fix; a full 8-artifact retrain ran <15 min on the fixed Codespace vs 4+ hours unfinished locally, with `git check-ignore -v`/`git status` clean.

---

### 54. First real `aq backtest` against rank-pivot models: Sharpe -0.59 → +0.40, plus a universe-selection bug (BNBUSD/TRXUSD never listed on Coinbase)

**Severity:** n/a (verification milestone) / 3/10 (ticker bug) · **Status:** 🟢 `verified` / `fixed`

**Problem:** Rank-pivot roadmap (#52/#53) needed real `lean backtest .` confirmation. Separately, two Stage-3 crypto tickers from #52's expansion (BNBUSD, TRXUSD) could never subscribe — Coinbase never listed Binance Coin or TRON pairs, though Yahoo Finance returned price history masking the mis-selection.

**Fix:** Swapped for ETCUSD (Ethereum Classic) and ZECUSD (Zcash), both confirmed present in Lean's local Coinbase symbol-properties database, backfilled via `aq fetch crypto --apply`.

**Verification:** Sharpe -0.59→0.403; Net Profit -4.604%→+10.438%; Drawdown 11.1%→4.0%; Win Rate 47%→58%; rebalance scheduler confirmed working (turnover barely moved despite order count rising — bigger book, long_short trading both sides). Disclosed confound: `bypass_safety_gates` flipped `true` same run, improvement not cleanly attributable to rank-pivot alone — clean-comparison backtest reverted left as manual follow-up. Swap dry-run row-count/date-range checked pre-`--apply`; `config.json` JSON-validated; rebuild confirmed registration with same observation-only classification as other Stage-3 crypto; log confirmed #34's limit orders fire (rounded limit-price log line).

---

### 55. Every webui tab except `/` 404'd on a direct load when served by FastAPI

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** The webui bundle mounted as `StaticFiles(directory=WEBUI_DIST, html=True)`, and `html=True` maps only directory paths, so a direct load/hard refresh of `/risk`, `/topology`, `/neural-network`, `/tracing`, or `/operations` returned a raw 404 (client-side nav worked, masked in dev by vite's SPA fallback).

**Fix:** A `SpaStaticFiles(StaticFiles)` subclass overrides `get_response()` to fall back to `index.html` on 404, limited to extensionless paths so genuinely missing assets (`/assets/*.js`) still 404 (careful to catch Starlette's own `HTTPException(404)`, not FastAPI's subclass).

**Verification:** Parametrized tests cover all six client routes, the missing-asset-still-404 case, and `/api/*` not being shadowed.

---

### 56. `train_topology.py` learned prototype z offsets on the pre-V4 `0..1` scale

**Severity:** 1/10 (latent; unreachable until a model exists) · **Status:** 🟢 `fixed`

**Problem:** V4-W3 made z a real `0..100` correlation-distance axis in 3D embedding mode, but prototype z offsets were still emitted on the old `0..1` formula, so the overlay effectively moved nodes in x/y rather than z.

**Fix:** Z is normalized to `[-1, 1]`, with `topology/learned_topology.py::_score_node()` scaling by the active `max_offset_z` before the same clamp as x/y (provably identity-preserving in 2D, proportionally larger in 3D) and an `offset_schema` detection field since no old-format model ever existed.

**Verification:** Byte-identical output vs the old raw formula in 2D, and 60x more z travel under the raised 3D cap. A schema-2 `ml/topology_model.json` (6 prototypes, trained 2026-07-29 from live experience events) later exercised the fix in the first-bar smoke test; retraining the overlay was declined because it fits logged live win/loss events and a dataset proxy would be a different distribution.

---

### 57. Futures/options had a live incremental-vs-absolute order-sizing bug — fixed, plus position scale-up for all 5 asset classes

**Severity:** 5/10 (dormant, reachable only via `futures_risk.enabled`/`options_risk.enabled`, both default off) · **Status:** 🟢 `fixed`

**Problem:** Equity/crypto/bond add-to-position was blocked by a simple `main.py::_apply_signal()` gate, but futures/options had none — worse, correctly-recomputed **absolute** per-bar targets fired through **incremental** primitives (`MarketOrder`/`Buy`) every bar the signal held, stacking contracts unbounded, and options could orphan a position by re-selecting strike/expiry each bar without closing the old one.

**Fix:** New `risk_controls.py::compute_incremental_order_quantity()` makes futures/options submit only the signed delta toward the absolute target, unconditionally (a genuine bug fix, no flag), with two opt-in tiers: `position_scaling.enabled` scale-up/down with a churn guard and `rotate_on_drift` liquidate-then-reenter.

**Verification:** The default path is unreachable via grep/call-graph trace; tests rose 1521→1558 passing (`test_risk_controls.py`, `test_order_gate.py`), with `main.py` verified by call-graph trace only (it subclasses `QCAlgorithm` and has no direct unit tests).

---

### 58. Architecturally-sound options: multi-position book, symmetric scale-down, held-contract sizing, spread combo orders (V4.4)

**Severity:** n/a (architecture pass, no defect) · **Status:** 🟡 `partial` (code-complete, ⚪ IB-unverified — no option assets in the universe, no IB key connected)

**Problem:** Review of #57's options paths found six gaps: single-leg options scaled up only, never down; spreads couldn't scale down at all (no `Sell`-side combo primitive); drifted position with `rotate_on_drift` off frozen rather than re-managed; single-slot tracking capped book at one position per underlying; rotation's same-bar liquidate+reenter had no netting; spreads had no limit-order path.

**Fix:** Full multi-position book (`option_positions_by_symbol` as `dict[str, list[dict]]`, capped by `max_positions_per_underlying`, default 1 = byte-identical), pure sizing functions for already-held contracts/legs, Sell-side combo scale-down, combo limit orders; real gap caught during verification and fixed pre-landing (at-cap re-pricing firing even with `position_scaling` disabled).

**Verification:** Default path unreachable — `options_risk.enabled=false` forces vega budget to 0; tests 1558→1591 (`tests/test_options_strategy.py`, `tests/test_order_gate.py`); `main.py` exhaustive call-graph trace only (untestable in isolation); real fill/margin behavior remains IB-unverified.

---

### 59. Full `OptionStrategies` coverage: all 43 QuantConnect option structures, registry-driven (V4.5)

**Severity:** n/a (architecture pass, no defect) · **Status:** 🟡 `partial` (code-complete, ⚪ IB-unverified)

**Problem:** Only 2 of QuantConnect's 43 `OptionStrategies` factory structures implemented (#57/#58); user wanted full coverage so the model drives any structure gap-free.

**Fix:** Near-duplicate per-strategy functions replaced by `MULTI_LEG_STRATEGY_REGISTRY` data table (all 43, transcribed from real Lean C# source, correcting 2 mistranscribed leg-direction assumptions found en route) dispatched through ~10 shared shape-family leg selectors; `options_margin_sizing.py` for naked/uncovered/bounded-max-loss tiers; `main.py` generalized to `"multi_leg"` record kind; gated behind `multi_leg_strategies_enabled` (default false, byte-identical).

**Verification:** Tests 1589→1656 (registry completeness, all 43 strategies vs synthetic chains, margin tiers, router gating); rewrite verified via trace plus full pre-existing suite unchanged (proves legacy vertical path identical through generalized code); combo surface remains IB-unverified.

---

### 60. V4.6 — bounded options follow-ups, arbitrage mispricing detector, Forex/FX, and analytic bond-ETF duration/convexity

**Severity:** n/a (follow-up/architecture pass, no defect) · **Status:** 🟡 `partial` (Forex sub-item now 🟢 fixed and live-verified — see below; arbitrage-detector sub-item remains IB-unverified)

**Problem:** Multi-leg counting double-counted legs vs `max_active_positions`; rotation lacked anti-thrashing guard + same-bar netting; no per-asset strategy override; 6 arbitrage strategies stubbed with no mispricing detector; no Forex/FX asset class; individual-bond trading (requested) impossible — this Lean version has no bond security type.

**Fix:** `_distinct_position_identities()` correct counting (+ related exclude-filter bug); `rotation_cooldown_bars` anti-thrash guard; same-bar netting via re-sizing against fresh portfolio value; per-asset `enabled_strategy_names` override; new `options_arbitrage_detector.py` (closed-form fair-value formulas + bps-floor threshold, default off); new `risk/forex_risk.py` + `forex_pair_specs.json` + `main.py` forex branch; bond work reframed as analytic duration/convexity/DV01 math in `features/bond_features.py`, informational-only (never fed to trained model).

**Verification:** Tests 1656→1722 (new arbitrage-detector/forex-risk/bond-features files); `main.py` via trace plus full suite unchanged. **V5.2.8: Forex sub-item confirmed fully live**, not "zero live tickers" as originally stated — 15 real OANDA pairs in `phase1.universe.assets`, `phase_v2.forex_risk.enabled: true`, `risk/forex_risk.py`/`compute_forex_order_units()` wired into `main.py` (6 call sites), exercised in two real Lean backtests (#92/#93: 220 real forex fills, `notional_ratio` within 0.15% of 1.0 across 193 diagnostic records). Arb-detector unchanged: `phase_v2.options_risk.arbitrage_detector.enabled` still `false`, operates on option-chain data — needs option asset in universe, remains IB-unverified.

---

### 61. V4.7 — early-assignment/corporate-action modeling, a learned strategy-selector model, and bond analytics wired into the trained model

**Severity:** n/a (follow-up/architecture pass, no defect) · **Status:** 🟡 `partial` (bond-analytics sub-item now 🟢 fixed — see below; early-assignment detector and strategy-selector model remain default-off/dormant)

**Problem:** Deferred from V4.6: full early-assignment/corporate-action modeling; learned model picking multi-leg strategies; bond analytics as real trained features (previously informational-only specifically to avoid forcing a retrain).

**Fix:** `dividend_backfill.py` (yfinance ex-dividend history + cadence-based next-date projection); Barone-Adesi-Whaley American-exercise pricer; `options_assignment_risk.py` scoring; default-off auto-close sweep; capture path in observation-mode order branch (real-order path never fires without IB); `train_strategy_selector.py`, `inference/strategy_selector_inference.py`, router reranking (active only once model trained/enabled); 3 new bond features (`bond_analytic_modified_duration`, `bond_analytic_convexity`, `bond_dv01`) into `input_set`, computed in both `main.py` and `train.py` offline pipeline.

**Verification:** Tests 1722→1813 (91 new, incl. American≥European price invariant and put-always-zero-assignment-risk invariant); `main.py` trace only. **V5.2.8: "requires retrain before deploy" caveat stale — none needed**: `ml/feature_schema.json`'s 49 `feature_names` byte-identical to current 49-entry `input_set`; `ml/scaler_stats.json` arrays length-49 aligned; `git diff --stat HEAD` zero drift (closed by #70's retrain, verified via backtests V5.2.4-V5.2.7). Early-assignment/strategy-selector remain dormant/default-off — no live signal to verify against.

---

### 62. Phase 4.8 — closing operational/surfacing gaps: `lean` CLI in retraining-worker, a `main.py` scoping bug fix, new Options & Strategy webui page

**Severity:** n/a (surfacing pass), plus one real bug rated 4/10 (silently wrong data persisted, never a crash) · **Status:** 🟢 `fixed`

**Problem:** A 3-agent audit found `lean` missing from the production image used by `retraining-worker`, the compose `data/reference` mount missing (silently zeroing Forex/futures/FRED specs), `aq` lacking a bulk-backfill dispatcher, stale `aq test` subsystem file lists, and a real bug where `corporate_action_payload` was computed in Pass 1's per-symbol loop but read in Pass 2's separate loop (no block scoping, so every symbol reused the last one's value); several V4.7 fields (bond analytics, assignment risk, dividend schedule, strategy-selector scores) were computed but never reached `state.json`.

**Fix:** Added `lean` to production requirements plus a Docker socket mount, fixed the compose mount/comment, added `aq backfill <target>`, fixed the stale dict and threaded the payload through `pass1_state` per-symbol, wired all 5 fields into `signals[symbol_key]` in `_write_state()`, and added a `/options-strategy` page.

**Verification:** The bug fix was confirmed via call-graph trace plus a full green suite; python tests 1813→1818, webui 13 tests across 2 files, npm build/lint/test clean.

---

### 63. V4.9 Priority 0 — the #36/#50 profiling wrapper was never reverted: a live per-bar disk write on the hottest path

**Severity:** 6/10 (real continuous synchronous disk I/O on every symbol-bar call in any live/paper/backtest run) · **Status:** 🟢 `fixed`

**Problem:** #36's claim that the `_build_model_input()` wrapper "was fully reverted" (per #50) was false — `main.py` unconditionally opened `model_input_timing.log` and wrote a line every symbol-bar call, ungated, with 45,187 accumulated lines (~983KB) untracked in repo root.

**Fix:** Impl renamed back to `_build_model_input`, wrapper deleted; dead `perf_counter` import removed; log file deleted. Real per-call timing collection remains an open task — `scripts/profile_inference.py`'s in-process harness (no disk I/O) intended path forward.

**Verification:** `py_compile main.py` clean; grep confirms zero references to removed names/file; `main.py` via trace only (unit-untestable by convention).

---

### 64. V4.9 Priority 4 — `_build_options_chains_payload()`'s gating, considered and declined

**Severity:** n/a (no code change — a documented decision) · **Status:** 🟢 `fixed` (declined by design, no code change)

**Problem:** A candidate optimization to gate `_build_options_chains_payload()` (runs once per bar per configured option asset) behind `self.options_risk_enabled`.

**Fix:** Declined — configuring an option asset is already the deliberate visibility trigger (it feeds `state.json`/webui regardless of multi-leg trading), matching the "compute for visibility even when trading is off" pattern bond analytics/assignment risk follow, and it never appeared as a meaningful profiling cost.

**Verification:** Decision recorded so future passes don't re-investigate from scratch.

---

### 65. V4.9 Priorities 1-3, 5-8 — sequence batching, topology percentile-tolerance caching, options chain-grouping hoist, non-blocking experience delivery, IPC benchmark, HFT documentation

**Severity:** n/a (feature/optimization pass, all off by default) · **Status:** 🟢 `fixed`

**Problem:** A profiling-roadmap continuation: the sequence encoder cost was paid once per symbol, the fixed topology cache tolerance was poorly calibrated, per-bar options cost was hoistable, live/paper experience-event delivery was blocking, the `ProcessPoolExecutor` IPC assumption was unmeasured, options profiling coverage was missing, and the framing of which latency work is genuine HFT-fork prep was unclear.

**Fix:** Added batched sequence inference (`run_exported_sequence_multitask_model_batched()`, default off, falling back on <2 sequences or any failure), a percentile-based rolling-window tolerance, a hoisted `group_chain_by_expiry()` per routing call, non-blocking `ExperienceQueue.push()` (`async_enabled`, default off), an IPC benchmark confirming `ProcessPoolExecutor` is dramatically slower than sequential on this Windows/spawn machine, an `"options"` workload in `profile_subsystems.py`, and an architecture doc section separating genuine HFT-transfer work from daily-bar-loop speedups.

**Verification:** Tests 1818→1857 (39 new: batching parity, percentile math, chain-grouping parity, async semantics, pool-failure degradation, options workload shape); all new keys grep-verified defaulting `false`/`null` (byte-identical off); `main.py` via call-graph trace only.

---

### 66. V4.10 — pure-function extraction of `main.py`'s exit logic, 4 webui quality fixes, and 15 new forex/FX assets fetched

**Severity:** n/a (feature/extraction/data pass) · **Status:** 🟢 `fixed`

**Problem:** Exit-decision logic (max-holding-age + trailing-stop) never extracted into a testable pure module unlike comparable decisions elsewhere. Post-V4.9 audit found 4 webui defects: defeated `useMemo` caching, oversized single JS bundle, 2 dead Grafana routes, untested chart/format primitives. Forex — fully wired since V4.6 — had zero live tickers (`aq fetch` had no forex class).

**Fix:** Extracted `evaluate_non_model_exit()`/`compute_position_exit_tracking_update()` into `risk_controls.py`; webui stable empty constants + `React.lazy()`/`Suspense` 3D-bundle split + removed dead routes + chart/format primitive tests; `"forex"` entry in `fetch.py` asset-class config plus bid/ask-synthesizing Lean CSV writer; `forex_pair_specs.json` 7→15 pairs, all fetched full-window (universe 74→89); `forex_risk.enabled` stays off by default.

**Verification:** Extraction byte-identical via static call-graph trace only (`main.py` unexecutable by tests); forex fetch/writer tests use injected `fetch_fn` (zero network); webui suite 37/37 (from 13); npm build/lint/test clean; `python train.py --dataset-only` deliberately **not** run to confirm forex classification — user chose manual training later; `asset_universe.md` marks pairs "Trading (expected)," not confirmed.

---

### 67. V4.10 follow-up — opt-in live (Lean/IB-calibrated) futures margin source, toggleable via `aq config`

**Severity:** n/a (feature, off by default) · **Status:** 🟡 `partial` (code-complete, genuinely Lean-API-unverified)

**Problem:** `futures_contract_specs.json` carried since V4.6 an explicit "documented future enhancement, not implemented" note asking to prefer IB's live margin over static reference numbers.

**Fix:** Added `phase_v2.futures_risk.margin_source` (default `"static"`), settable via generic `aq config set`. `"live"` mode attaches Lean's local IB-calibrated `BuyingPowerModel` per futures security individually (never global `SetBrokerageModel`), queried via new `_resolve_futures_contract_spec()`; `build_live_contract_spec()`/`resolve_futures_margin_source()` in `risk/futures_risk.py` produce spec interchangeable with the static path; every live-margin call site wrapped in try/except falling back to static/default on any failure.

**Verification:** 8 new tests in `tests/test_futures_risk.py` (26 total): validation, live-spec shape, interchangeability with static path; `main.py` wiring trace-only; never run against a real backtest with a futures position actually sized — genuinely Lean-API-unverified (margin-query API has evolved across Lean versions).

---

### 68. `cpp_inference_ext` was never built for the actual deployed image — closed via a soft-fail Docker build step

**Severity:** low (silent perf-only gap, not correctness) · **Status:** 🟢 `fixed`

**Problem:** The only compiled extension was hand-built for dev-machine Python 3.14 (ABI-incompatible with the deployed `python:3.11-slim`), and the Dockerfile lacked a compiler/pybind11/extension entirely, so C++ acceleration never ran deployed — a 100% silent gap.

**Fix:** Added a soft-fail `RUN` step installing `build-essential`+`pybind11`, pip-installing `cpp_inference_ext`, and purging `build-essential` in the same layer, wrapped in `(...) || echo ...` so a toolchain/ABI failure degrades to the NumPy fallback rather than breaking the build; a `.dockerignore` block keeps locally-built incompatible binaries out of the published image.

**Verification:** Confirmed in Phase 4.12.3: `docker compose build engine` succeeds and in-image `import cpp_inference` loads the real compiled linkage (`cpp_inference.cpython-311-x86_64-linux-gnu.so`), not the fallback.

---

### 69. Audit follow-up — `main.py` CI syntax-check gate, and a Windows-specific inference-parallelism slowdown guard

**Severity:** low · **Status:** 🟢 `fixed`

**Problem:** `main.py` had zero CI coverage, not even a syntax check (`AlgorithmImports` is undefined outside a real Lean process), and `phase_v2.inference_parallelism.enabled` was unguarded despite #65 measuring it dramatically slower than sequential on Windows/spawn — with the key also absent from `config.json`, so `aq config set` on it failed rather than silently succeeding.

**Fix:** Added a `python -m py_compile main.py` CI step (parse only; mypy/pyright via `quantconnect-stubs` was declined as too noisy), a `windows_parallelism_slowdown_warning()` that fires `Debug()` only on win32 after real pool construction, a key-specific stderr warning citing the #65 measurement, and an explicit `phase_v2.inference_parallelism: {"enabled": false}` block in `config.json`.

**Verification:** New `test_parallel_inference.py` cases (win32 vs linux/darwin) plus 4 in `test_aq_cli.py` confirm it fires only on this path, only when truthy, and only against `config.json` (not `lean.json`).

---

### 70. V4.11 — full Codespace retrain + walk-forward executed, three latent `train.py` bugs fixed, primary signal clears the significance bar

**Severity:** n/a (milestone) · **Status:** 🟢 `fixed` (all infra/verification blockers this entry raised were closed in Phase 4.12.3; remaining era-sign instability is a separate, tracked model-quality question, not an infra gap — see #71)

**Problem:** Full retrain + Stage-6 walk-forward coded but never run. First real run (incl. 15 forex pairs) surfaced 3 latent `train.py` bugs: forex quote-bars silently dropped by trade-bar parser; empty-frame regime-encoding path producing duplicate columns crashing walk-forward; walk-forward manifest `KeyError` on empty per-window inventories. Stale-data sync gap: 4 forex zips on Codespace were old 2007-2018 vintage, wrongly classifying those pairs `observation_only`.

**Fix:** Forex branch in `load_lean_bars()` collapsing quote bars to train/serve-parity midpoint; empty-frame guard in `add_regime_features()`; `.get()` fallback for manifest KeyError; fresh zips re-synced, retrained.

**Verification:** Real Codespace retrain: multitask `rank_20d` `non_overlapping_t_stat = 2.028` (≥2.0 pass), `bootstrap_ci_lower = +0.0065` (≥0 pass) — both hard thresholds pass first time; verdict still `not_promotable`, blocked solely by era-sign instability (2/9 eras opposite-sign). Real user-run backtest (2019-2021, 78-asset model): end-to-end, 2,062 orders, every newly-toggled feature without crashing; Net +1.04%, Sharpe -0.313 — faint edge not clearing costs. Shutdown hang traced to `inference_parallelism` pool fixed separately (#68/#69 pass) via explicit `pool.shutdown()` + flag reset default-off. Topology overlay (#56) still dormant — Codespace has no Postgres/experience DB.

---

### 71. Phase 4.12 — kill era-sign instability, close remaining non-IB items, expand breadth, alt-data + RL sizing

**Severity:** n/a (milestone) · **Status:** 🟢 `fixed` (all streams landed and retrained end-to-end; Docker-dependent verification closed in Phase 4.12.3)

**Problem:** Promotion blocked solely by COVID-era-sign inversion, plus: no per-era diagnostics; crypto-only weekend cross-section contaminating IC observations; `average_correlation` hardcoded 0.0; unused alt-data/breadth opportunities; untested RL-sizing idea.

**Fix:** A1 per-era diagnostics in promotion gate; A2 `min_universe_size` 10→20 removing degenerate crypto-only cross-section flipping era signs; A3 era-sign noise floor so thin/near-zero eras don't fail identically to genuine inversions; A4 correlation fix (reordered feature-build steps) + beta-neutral ranking target added-not-wired; Stream D VIX/VXV/NFCI alt-data features; Stream C universe 89→104 with proportional position-cap scaling; Stream E offline contextual-bandit RL sizing layer, shipped disabled after honest negative backtest result.

**Verification:** Real retrain: t-stat 2.028→2.8954, CI lower 0.0065→0.0585 (both gates pass with margin) but still `not_promotable` — 2 real inversions remain (COVID + newly-exposed Dec 2020-Mar 2021 era, both exceeding noise floor); sequence `rank_5d` achieved full `promotable` first time in project history; walk-forward: 6 expanding windows, cross-window MCC mean 0.0187, CI [0.0136, 0.0239], entirely positive; RL expected reward (-8.542e-5) underperformed trivial constant-multiplier baseline (-8.264e-5) — disabled per pre-committed abandon criteria, identically re-confirmed Phase 4.12.3; Docker down all session (WSL2 crash), blocking #68 linkage check, B1 topology training, both final backtests, 104-asset isolator timing — all closed Phase 4.12.3.

---

### V4.12.2 — close every webui/CLI integration gap Phase 4.12 left behind

**Severity:** n/a (integration-completeness pass) · **Status:** 🟢 `fixed`

**Problem:** Backend/CLI complete, webui not (~4/10): position-sizing multipliers, newly-promotable sequence `rank_5d` head, per-era diagnostic table, alt-data/bond macro features computed/persisted but never rendered; macro data never reached `state.json` at all.

**Fix:** `DynamicSizing` type + `AssetSizingTable.tsx` labeled chips; extracted `RankingQualityGate` sub-component rendered for all three heads plus per-era table; `state["macro"]` added to `_write_state()` (mirroring derivatives-macro precedent) + new `MacroSnapshotPanel.tsx`; CLI audited — no gaps.

**Verification:** Full pytest 1989 passed (11 errors all pre-existing Docker-fixture, not regression); npm build clean, vitest 46/46; no `main.py`-level test for the macro line per convention — direct code trace; also fixed stale docs across 6 subsystem READMEs missing from Phase 4.12 write-up.

---

### Phase 4.12.3 — every remaining Docker-dependent item closed, Phase 4 arc complete

**Severity:** n/a (closure phase) · **Status:** 🟢 `fixed` (nothing IB-independent left open)

**Problem:** 4 Docker-outage-blocked items: #68 linkage check, B1 topology training (#56), two user-run backtests, isolator timing at new 104-asset universe.

**Fix:** Root-caused outage to stuck `wslinstaller.exe` wedging `WSLService` — required genuine cold restart (not "shut down then power on," which resumes the same broken session under Windows Fast Startup). Then: confirmed real `.so` linkage in engine image; trained topology overlay first time ever (6 clusters from 4,937 samples, via 3-month observation-mode backtest after repeated full-window OOM crashes forced window shrink); ran observation-mode data-generation backtest + full representative 2019-2021 backtest with drawdown enforcement genuinely active; measured `Initialize()` ~105s at 104 assets (above 90s isolator budget referenced in original plan, completed without isolator-timeout error).

**Verification:** Backtest (full window, `bypass_safety_gates: false`): clean ~31 min, 3,606 orders, no forced-liquidation lock; Sharpe -0.313→-0.145, Net 1.04%→3.41%, Drawdown 8.9%→6.6% — still not significant (PSR 1.84%), fees ($2,769) consume nearly all net profit; RL re-run on fresh datasets reproduced identical negative result (not fluke); standing rule adopted: all model training on Codespace via CLI, never locally, given RAM constraints.

---

### 72. V5.1 Phase 1's net-edge cost gate blocked 100% of trades — Lean Backtest 1 produced 0 orders end to end

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** The Priority 6.5 net-edge gate re-derived its own pass/fail from raw `net_edge_bps` instead of trusting `build_net_edge_decision()`'s `passes` field, and the "disabled" state still carried `net_edge_bps=0.0`, so with the `aggressive` preset's `min_net_edge_bps: 2.0`, `0.0 < 2.0` evaluated True every symbol/bar and routed every directional signal away from trading — 100% blocked, 0 orders for the whole backtest.

**Fix:** Removed the re-derived comparison and `min_net_edge_bps` parameter from `build_market_analysis_decision()`, which now trusts `net_edge.get("passes", True)`, the single verdict already computed by `build_net_edge_decision()`.

**Verification:** 5 regression tests in `test_market_analyzer.py` assert the exact "disabled" dict shape reaches `"trade"`; the root cause was surfaced by a real backtest (0 orders) since no prior unit test exercised a realistic non-`None` disabled dict.

---

### 77. V5.1 Phase 1's `min_rank_confidence_spread` gate defeated by its own cross-sectional normalization fix — real Lean Backtest 1 traded but lost money

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `_select_book_group()`'s conviction gate read the cross-sectionally-normalized `predicted_rank_20d` (introduced by the F1 fix, #73) instead of the raw score, and a fixed top-6/bottom-6 selection percentile-ranks to a ~0.90+ spread regardless of dispersion, so the `aggressive` preset's `min_rank_confidence_spread: 0.20` never disengaged the book across the whole 2019-2021 run — Sharpe −0.145→−2.526 and net profit +3.41%→−3.11%.

**Fix:** Added an optional `spread_check_ranks` parameter to `_select_book_group()`/`build_rank_based_book()` that `main.py` builds from each symbol's pre-normalization `raw_rank_score` alongside the normalized `book_candidates`, changing only the engagement gate's input while sizing/confidence still read the normalized value.

**Verification:** 6 new tests in `test_portfolio_book_construction.py` (including one reproducing the bug directly and one proving selection is unaffected); the deferred Lean re-verification was superseded by the real runs recorded from #89 onward (#127 for the latest).

---

### 78. `tests/test_retraining_worker.py` — 7 of 11 tests spawned a real, unmocked subprocess, adding ~17 minutes to every full suite run

**Severity:** 3/10 (dev-velocity/CI-cost only, no correctness impact) · **Status:** 🟢 `fixed`

**Problem:** 7 tests in `test_retraining_worker.py` patched the first four of `run_once()`'s five best-effort trainer stages but never `train_strategy_selector`, so each spawned a real `subprocess.run()` shelling `train_strategy_selector.py` (~140-168s apiece) — collectively ~1,050-1,200s of a ~28-minute suite.

**Fix:** Added `patch("retraining.worker.train_strategy_selector")` alongside the other stage patches in all 7, matching the file's per-stage mocking convention.

**Verification:** The file re-runs 11/11 passed in 86.8s total (down from >1,050s for the same 7 tests), roughly 15-16 minutes off every future full-suite run.

---

### 79. `data_pipeline/fred_backfill.py::fetch_fred_series()` hung/reset on every request — FRED's graph-export endpoint requires HTTP/2, which stdlib `urllib` cannot speak

**Severity:** 7/10 (blocked V5.1 Phase 2's CODESPACE RUN 1 entirely — 0 of 12 FRED series fetchable) · **Status:** 🟢 `fixed`

**Problem:** stdlib `urllib.request` (HTTP/1.1-only) could no longer reliably reach FRED's `fredgraph.csv` endpoint — an external FRED-side change, not a regression — so all 12 series failed with read timeouts; a secondary finding was that the prior browser-spoofing `User-Agent` caused an immediate `RST_STREAM` even over HTTP/2, plausibly FRED's WAF cross-checking UA against the TLS fingerprint.

**Fix:** Swapped to `httpx.Client(http2=True)` (adding `httpx[http2]>=0.27.0`) and removed the browser-spoofing `User-Agent` entirely.

**Verification:** Network-mocking tests were rewritten against `httpx.Client` in `test_fred_backfill.py` (31/31 pass) and verified live locally and on the Codespace: all 12 series, including 3 new ones, fetch successfully with full historical coverage.

---

### 80. `train.py::build_dataset_manifest()`'s new `computed_but_unused_features` (V5.1 Phase 2) flagged ~70 legitimate columns as orphaned on the first real dataset build

**Severity:** 6/10 (would have buried the 3 genuine orphans under ~70 false positives) · **Status:** 🟢 `fixed`

**Problem:** `train.py::build_dataset_manifest()`'s new `computed_but_unused_features` (V5.1 Phase 2) built on the post-scaling dataset but `_computed_but_unused_feature_columns()` excluded only `base_feature_names`/`context_feature_names` — never `scaled_feature_names`, `categorical_feature_names`, or raw OHLCV/bookkeeping columns — so it flagged ~70 legitimate columns as orphaned; tiny synthetic fixtures never included those column classes.

**Fix:** Threaded `scaled_feature_names`/`categorical_feature_names` into the exclusion set and expanded `_NON_FEATURE_DATASET_COLUMNS` with `RAW_COLUMNS` plus `security_type`/`market`/`quality_tier`/`trading_eligible`/`training_eligible`.

**Verification:** A regression test covers all three previously-missed classes, and a Codespace real-dataset build returns exactly the 3 genuine orphans (`futures_term_structure_slope`, `options_implied_vol_skew`, `options_put_call_ratio`).

---

### 81. `portfolio/book_neutrality.py::apply_book_neutrality()`'s sector-neutral step silently erased entire legs of the live/simulated book

**Severity:** 9/10 (live-path bug — shipped default since V5.1 Phase 1) · **Status:** 🟢 `fixed`

**Problem:** Sector-neutral demeaning subtracted each bucket's mean signed weight from members, driving members to exactly zero whenever a bucket has zero within-bucket dispersion — true by construction since callers equal-weight names per role. `"Forex"` (all 15 tickers one bucket) structural, not rare: whenever the short leg had forex representation, demeaning erased it entirely. Found via `aq evaluate --rank-book` showing `mean_names_short=0.00` despite `bottom_n=6`.

**Fix:** Replaced demean-to-zero: leave bucket untouched if `|net| <= sector_max_net_weight`, else shrink whole bucket proportionally (sign preserved, never amplified) so net lands exactly at cap; single-member buckets no longer special-cased; side effect judged correct — single-member bucket already exceeding cap now capped too (previously exempt).

**Verification:** `tests/test_book_neutrality.py` rewritten, 12 tests incl. monolithic-role regression guard; end-to-end on Codespace real model/data: `net_sharpe` 0.4856→0.9694, `mean_names_short` 0.00→6.00; not yet re-verified with a Lean backtest — `sector_neutral: true` config default since Phase 1, affecting live decision path too.

---

**Update (2026-10-06, V5.5.0):** "not yet re-verified with a Lean backtest" is superseded by the real runs recorded from #89 onward (#127 for the latest).

### 82. V5.1 Phase 4's walk-forward net-performance step crashed on window 1 — fed the exported model the wrong feature list (49 raw names instead of the 66 it was actually trained on)

**Severity:** 7/10 (crashed the entire walk-forward run on window 1) · **Status:** 🟢 `fixed`

**Problem:** V5.1 Phase 4's walk-forward net-performance call site passed the outer `feature_names` (49 raw pre-scaling names) instead of the 66-column `model_input_names` the models were actually trained against, crashing window 1 with `ValueError: _conv1d_causal: in_channels mismatch (49 vs weight's 66)`.

**Fix:** Both call sites now use `dataset_manifest["model_input_names"]`.

**Verification:** The exact run that crashed window 1 completed all 6 windows post-fix; no unit test caught it because fixtures used tiny single-feature lists where "raw" and "model input" names were never genuinely distinct.

---

### 83. V5.1 Phase 4's walk-forward sequence training hits a hard memory ceiling on the project's Codespace machine type for larger training windows

**Severity:** 6/10 (no corruption — degraded cleanly to multitask fallback — but weakened statistical power of 3 of 6 windows) · **Status:** 🟢 `fixed` (root cause found and fixed at start of Phase 5)

**Problem:** Walk-forward sequence training was SIGTERM-killed on windows >~130-147k rows (3 of 6 in CODESPACE RUN 3) while constructing the dense `(rows, 30, 66)` tensor; a partial fix (freeing the parent's held dataset) recovered one window but not the ceiling, root-caused to building the full `sequences` array once and extracting the backtest split ~250 lines later — ~1.08GB resident through the whole training loop on a 7.8GB machine.

**Fix:** Moved the split extraction next to the train/validation splits, added `del sequences; gc.collect()` before training, and switched `evaluation/model_predictions.py::build_sequence_windows()` from float64 to float32 to match `train.py`.

**Verification:** Standalone re-runs on the 3 largest windows (146,868 / 153,696 / 160,219 rows) succeeded first attempt; the summary regenerated at full 6/6 windows, with sequence Sharpe windows 3-5 moving from fallback values (0.91, −0.26, −0.26) to real ones (0.39, 0.62, 1.47), all positive.

---

### 84. Rank heads were sigmoid-squashed at inference but trained raw against an MSE target

**Severity:** 8/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** Rank heads (`rank_5d`/`rank_20d`/`sector_neutral_rank_20d`) trained raw linear output against a `[0,1]` percentile target, but export wrapped every head in a leftover `"sigmoid"` — compressing live `predicted_rank_20d` into ~[0.475, 0.75], silently tightening `min_rank_confidence_spread` ~4x, capping confidence near 0.5, and zero-sizing bottom-ranked shorts, all invisible to rank-quality gates since rank-IC is invariant under monotone transforms.

**Fix:** Set the export activation to `None` for every rank head and added per-bar cross-sectional percentile normalization at inference (`portfolio/rank_signal.py::cross_sectional_rank_scores()`), since a pure ranking loss makes absolute output scale meaningless by construction.

**Verification:** Manual code/architecture fix (V5.1), no backtest cited.

---

### 85. `sector_mapping.json` covered 29 of the universe's 104 assets

**Severity:** 6/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** `sector_mapping.json` covered only 29 of the universe's 104 assets — 75 tickers (all 15 forex pairs, most crypto/equities) defaulted `"Unknown"`, making `target_sector_neutral_rank_20d` (a live head with `loss_weight: 0.3`) nearly duplicate plain `rank_20d` for 72% of the universe, while genuinely small sectors NaN'd under `min_sector_size: 3`.

**Fix:** Added a full 104-ticker mapping (GICS-like buckets for equities; `Forex`/`Crypto`/`Fixed Income`/`Broad Market ETF` for the rest), leaving `AAA` deliberately unmapped as a documented ambiguous legacy ticker.

**Verification:** Manual review (V5.1), no backtest cited.

---

### 86. The constructed book was silently truncated by `max_active_positions`, not by rank

**Severity:** 5/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** `top_n=10 + bottom_n=10` requested 20 names but `max_active_positions=15`, so excess names were rejected in `self.symbols` iteration order — an accident of universe ordering, not conviction.

**Fix:** Presets now set `max_active_positions >= top_n + bottom_n`, and when the cap binds, Pass 2 sorts candidates by rank-confidence so the strongest convictions survive.

**Verification:** Manual code/config fix (V5.1), no backtest cited.

---

### 87. `capacity_curve()`'s binding-ticker search let a forex pair's fake zero dollar volume dictate the whole book's capacity

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `capacity_curve()`'s binding-ticker search picked the lowest-average-dollar-volume held name, and forex pairs always report `liquidity_log_dollar_volume == 0.0` (Yahoo reports no FX volume), so any forex pair won automatically and produced a sub-$1 `capacity_usd` failing every promotion gate regardless of the rest of the book's real liquidity; a secondary bug was using `np.exp()` where `log1p()`'s inverse is `np.expm1()`.

**Fix:** Excluded exact-zero tickers from the binding search (a true zero is no liquidity signal, not "most illiquid") and fixed `np.exp`→`np.expm1`.

**Verification:** 3 new tests in `test_rank_book_simulator.py` cover zero-volume exclusion, the all-zero fallback, and an exact value distinguishing `expm1` from `exp`.

---

### 88. A pre-backtest review found six critical bugs in code/config that had never executed a Lean bar

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** Pre-Lean-backtest review of every config value switched on this session (net-edge gate, calibrated cost model, kill switch, reconciliation) found six defects together producing half-dead book locking early and staying locked: (1) `expected_edge_bps()` long-side edge only, vetoing every short unconditionally; (2) `--calibrate-edge` regressed against `target_return_1d` instead of configured `horizon_days` (20), understating edge ~14x; (3) kill switch never enforced `evaluation_bars` as minimum sample for rolling Sharpe, tripping bar 2-3; (4) reconciliation compared pre-sizing weight against every held security — self-sustaining false-drift lock; (5) slippage-divergence measured overnight gap (fill vs prior close) not true slippage (fill vs next open); (6) `corporate_action_payload` leaked across symbols in Phase 1c loop via stale outer-scope variable. Seventh adjacent config issue: `sector_max_net_weight: 0.05` tighter than `max_weight_per_name: 0.12`, silently shrinking exposure.

**Fix:** `trade_direction` parameter on `expected_edge_bps()`/`build_net_edge_decision()`; `--calibrate-edge` regresses on `target_return_{horizon_days}d` (`edge_bps_per_rank_unit` 28.2→396.3); kill switch gained `min_bars_for_sharpe` floor; reconciliation captures final post-sizing `target_weight` per symbol via new `_realized_target_weights_by_symbol`, broker side restricted to `asset_lookup` keyspace; slippage-divergence trigger set to never-fires sentinel pending reliable fill-time reference (collection stays on); payload carried through `pending` list like `topology_payload`/`regime_payload`; `sector_max_net_weight` raised to 0.15, `apply_book_neutrality()` gained `>0.0` precondition (closing config path back into #81's bug).

**Verification:** Targeted tests in `test_cost_model.py`, `test_kill_switch.py`, `test_reconciliation.py`, `test_book_neutrality.py`; suite 2392 passed; `main.py` no direct unit-test coverage by convention — `py_compile` only; not yet re-verified with an actual Lean backtest.

---

### 89. The book went dead after 3 weeks in the first real V5.1 Lean backtest — two more bugs found and fixed, one root cause still open

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** First real V5.1 backtest (2019-01-01→2021-03-31) opened 4 positions January 2019, closed them ~2 weeks later, then zero orders for remaining 2.2 years (Sharpe −61.3, 8 total orders). Two confirmed bugs: `risk/kill_switch.py::_rolling_sharpe()` numerically unstable on near-zero-variance return windows (mostly-flat post-liquidation returns made `mean/std*sqrt(252)` explode, e.g. ±2.25 swings from noise alone), trip sticky by design; and `min_rank_confidence_spread: 0.2` was a guessed constant the offline simulator hardcoded to `0.0` — never exercised against real data before shipping.

**Fix:** Added `min_return_std_for_sharpe` floor (default 0.0005), composable with existing bar-count guard; added `aq evaluate --calibrate-book-spread`, deriving threshold from real per-date raw-score dispersion via shared `compute_confidence_spread()` — calibrated 0.5014 (vs guessed 0.2/0.18), applied to base config and both presets; also fixed `cmd_evaluate()` bug where `--calibrate-book-spread` alone incorrectly triggered a full `--rank-book` run.

**Verification:** Suite green (2412+ passed); follow-up real backtest confirmed trading resumed/continued 14 months (768-1106 orders) instead of dying at 3 weeks — both fixes effective. Open caveat: calibration (spread clears 0.2 nearly every date) contradicted original "compressed raw scores" hypothesis, so the exact January-2019 cutoff mechanism wasn't confirmed — see #90/#91 for larger gap exposed next.

---

### 90. A real Lean backtest, once it finally traded continuously, showed Sharpe -4.2 to -4.4 against a +2.18 offline number — three compounding mechanisms found and fixed (V5.2.1)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (V5.2.1; the investigation this entry's own open caveat seeded was continued and closed through #91-#93)

**Problem:** Book traded continuously but Sharpe was −4.42 (gated)/−4.18 (bypassed) vs +0.26 to +2.18 offline. Three compounding mechanisms: (1) offline never modeled ~1-bar execution lag (live fills at next bar's open); live `MarketOnCloseOrder` fix ruled out impossible at Daily resolution; (2) V4.3.0 position-scaling fired resize orders on non-rebalance bars, pushing order count (768-1106) far above offline's rebalance-only assumption; (3) cost gate under-costed resizes vs Lean's real floor-dominated commission (~$0.85-1.09/order).

**Fix:** `simulate_rank_book()` gained opt-in `entry_lag_bars`; new `is_position_resize_permitted()` gates resizing to rebalance bars only; cost gate's `order_value` reflects actual incremental trade delta.

**Verification:** Suite green (2428 passed). Update: follow-up real backtest (2026-08-07) Sharpe −4.421 — essentially unchanged; all three mechanisms empirically ruled out as explanation — see #91 for ground-truth diagnostic tool built next.

---

### 91. Book-history reconciliation (V5.2.2/V5.2.3) finds two unexplained live-vs-offline selection divergences

**Severity:** 9/10 → 2/10 · **Status:** 🟢 `mostly fixed and verified` — crypto/FX divergence resolved (V5.3.1/#97); NVDA/GE/WFC/XOM/BA root-caused (#100) and confirmed live in a real backtest (#102): GE/BA/NVDA/WFC all substantially improved. XOM's residual divergence stays 🟡 open (thin sample)

**Problem:** After #90 failed closing the gap, new reconciliation tool (`aq evaluate --reconcile-book-history`) ran against a real backtest (112 dates) and found: (1) crypto/FX in offline's top/bottom-6 on 107/112 dates but live's book on 0/112; (2) equities-only overlap only 34.6-54.8%, independent of crypto/FX.

**Fix:** V5.2.4 — `self.bar_index` incremented on every asset-class tick instead of equity session bars only, via `self.is_equity_session_bar` gating (~20+ downstream consumers fixed free), plus force-sell bug (empty `book_allocations` sold whole book, not just rotate-outs), plus crypto/FX made book-eligible via last-known-bar processing. V5.2.5 — `bond_empirical_duration_beta` recomputed every bar → compute-once-broadcast via `should_lock_in_duration_beta()`.

**Verification:** V5.2.4: orders/fees roughly halved (392 vs 768), Sharpe −4.42→−4.10, overlap 34.6%→49.3% (53.8% hysteresis-replayed). V5.2.5: overlap barely moved (48-50%) but Sharpe −4.10→−3.35 (~18%). V5.3.1 (#97/#98): crypto/FX divergence confirmed stale-log measurement artifact, not live bug — resolved. NVDA/GE/WFC/XOM/BA: sector-neutrality ruled out by direct code proof; remains unexplained. V5.3.2 (#99): two reconciliation-tool bugs fixed (cross-run contamination, tie-break order) — neither explains divergence; evidence points at genuine raw-score computation discrepancy for these 5 tickers specifically, not selection-boundary artifact. Still open.

---

### 92. Deep-dive into the remaining NVDA/GE/WFC/XOM/BA/forex/crypto divergence finds crypto/FX never actually trade, and a systemic live-vs-offline risk-gate gap (V5.2.6)

**Severity:** 10/10 · **Status:** 🟢 `fixed` (V5.2.6)

**Problem:** Crypto/FX were regularly selected but never placed a single real order — forex's synthetic quote-bar conversion hardcodes `volume=0.0`, tripping the liquidity gate's zero-volume block — and live carries ~10 risk/execution gates that offline's Sharpe engine never models, two of them duplicating a signal already an active input feature.

**Fix:** Added `zero_volume_fallback_ddv` (always for forex; for crypto only when `quality_tier=="core"`) to substitute a realistic daily-dollar-volume estimate without bypassing participation/cost gates, added book-selection-aware confidence thresholds, narrowed the `risk_off`/`topology_elevated` overrides using real-data-derived thresholds, and added `aq evaluate --calibrate-confidence-threshold` plus a `book_member_decisions` diagnostic.

**Verification:** 33 new tests, suite 2530 passed; a real backtest (2026-08-10) improved Sharpe −4.103→−2.984. A first attempt crashed on a deferred-write bug (`spread_check_ranks` UnboundLocalError) catchable only via a real bar-to-bar Lean run (fixed, re-run succeeded), surfacing two further bugs — forex sizing and sticky kill-switch lockout — see #93.

---

### 93. Forex order sizing rounds to zero at realistic book scale, and a sticky kill-switch trip locks out the book for 13+ months (V5.2.7)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (V5.2.7)

**Problem:** `_forex_lot_count_for_weight()` divided notional by full 100,000-unit lot value — at realistic 4-12% weights notional never reached one lot, so every forex order silently rounded to zero. Kill-switch trip 2020-02-27 never auto-cleared, locking 100% of book decisions into `reduce_risk` for remaining 13 months.

**Fix:** New `compute_forex_order_units()` sizes orders in raw base-currency units, not lots (earlier lot-rounding design caught in review — would have reproduced bug under a new name). Split `bypass_safety_gates` into `bypass_sticky_trade_lock`/`bypass_regime_drawdown_gate`; only sticky-lock bypass enabled this round to isolate effect.

**Verification:** 18 new tests; suite 2523 passed. Real backtest (2026-08-11): Sharpe -2.984→-2.17; `notional_ratio` within 0.15% of 1.0 across 193 records; 220 real forex fills across 9 pairs, first time ever. Kill-switch trips 26x, clears every time (vs once, stuck forever). Crypto (BTCUSD/LTCUSD) still never trades — separate unresolved Lean/Coinbase zero-volume delivery quirk, out of scope.

---

### 94. Kill-switch sensitivity sweep, an offline gate-aware replay, a training-side gate-aware ranking weight, and continued NVDA/GE/WFC/XOM/BA + overlap-metric investigation (V5.2.8)

**Severity:** n/a (investigation + opt-in tooling, no defect) · **Status:** 🟢 `fixed and verified`

**Problem:** Continues #91-#93: kill-switch 26-trips/2.2yr cadence mistuned or just model behavior? Gate-realistic training signal buildable offline? NVDA/GE/WFC/XOM/BA + overlap-metric erosion unexplained.

**Fix:** `evaluation/kill_switch_replay.py` (`aq evaluate --replay-kill-switch`) replays kill-switch + sticky trade-lock state machine day-by-day over rank book's own returns; deliberately approximate (dataset-derivable inputs only, no bypass flags). `train.py::compute_gate_friendliness_weight_by_date()` — optional per-date loss weight from stateless topology/regime-severity gates, threaded as `date_weights` (`None` = byte-identical), behind `gate_aware_ranking_weights.enabled` (default `false`). Sweep (20 combos): lockout near-binary — trip either never happens or locks ~58-74% of remaining window; #93's 26-trip *bypassed* result explained by the bypass itself, not discrepancy; no config change. NVDA/GE/WFC/XOM/BA re-checked vs real V5.2.7 data: all 5 recur; bond-duration-beta lead ruled out.

**Verification:** 33 new tests, suite 2523→2556. Replay matches sweep baseline end-to-end. Overlap erosion (49.96%→48.59%) reconfirmed — root cause open. Codespace smoke (3 epochs, flag on) + 6-window walk-forward ran clean, but neither verdicts flag at production (120/60-epoch) scale — no flag-off control ran.

**Follow-ups:** full state-machine replay; root-causing NVDA/GE/WFC/XOM/BA and overlap metric.

---

**Update (2026-10-06, V5.5.0):** (V5.5.0) part of the "overlap erosion" was a measurement artifact: `--reconcile-book-history` read a rebalance live had **vetoed** as 0% overlap. Vetoed dates are now reported separately and excluded from the match statistics (#131); the remaining root causes are #128.

### 95. Full-scale production retrain with gate-aware ranking weights promoted to active `ml/`; RL sizing re-confirmed negative a third time; full-epoch walk-forward validation (V5.2.9)

**Severity:** n/a (production training round, no defect) · **Status:** 🟢 `fixed and verified`

**Problem:** #94 shipped flag off, verified only via 3-epoch smoke, no flag-off control — does it hold at real (120/60-epoch) scale? Full training/validation/promotion cycle ready? Topology training needs real backtest experience events via local Postgres/Redis — out of scope (user instruction).

**Fix:** Enabled `gate_aware_ranking_weights.enabled: true` (user's explicit choice). Full Codespace pipeline at real epoch counts (baseline/gating/multitask/sequence/RL sizing); selector/topology skipped (no Postgres/option data). Promoted to active `ml/`, backed up to `ml/_backup_pre_v529_full_retrain/`. Full 6-window `--walk-forward`, validation only.

**Verification:** rank_5d IC 0.097→0.109; rank_20d IC 0.152→0.173; sector-neutral/residual ranks up. Direction MCC regressed slightly — dataset refresh and flag changed simultaneously, not cleanly attributable; net judged positive. RL negative reproduced third time; stays disabled. Walk-forward: rank_20d_ic mean 0.085 (stable, 0% sign flips), net Sharpe mean ~0.65 (5/6 windows positive). Topology untouched; rollback available.

**Follow-ups:** representative Lean backtest (user, manual); topology-training backtest; isolating dataset-refresh vs flag effect.

---

**Update (V5.6.0) - the flag-off control exists now:** on the regenerated dataset, `gate_aware_ranking_weights.enabled=false` scored validation IC 0.036 (round 2) / 0.061 (round 1) against the control's 0.048-0.077 across two seeds (seed spread 0.028): no measurable effect either way, so the 0.152 → 0.173 IC jump of that round was not due to the gate-aware weights.

### 96. Real limit-order support: stale docs corrected, `PartiallyFilled` made testable, two new offline diagnostic tools (V5.3.1, closes #34)

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified`

**Problem:** `phase_v2.limit_orders.enabled` was actually default-on all along, but `Problems.md`/`Changelog.md`/`execution/README.md`/a `main.py` comment claimed "default off." `PartiallyFilled` had never fired in 45 real backtests; partial-fill logic wasn't unit-testable (not importable outside Lean process).

**Fix:** Docs corrected. Investigated future/option `fallback_to_market_on_timeout=false` asymmetry — deliberate rationale already exists in `main.py` (margin/expiry risk), left unchanged. Extracted `should_clear_pending_limit_order()`/`resolve_limit_order_timeout_action()` into `execution/order_gate.py`, wired behavior-preserving — partial-fill contract unit-testable for first time. Two diagnostics: `evaluation/limit_fill_simulator.py` (`aq evaluate --simulate-limit-fills`) and standalone `scripts/order_events_audit.py`. `max_slippage_divergence_bps` left deliberately uncalibrated (synthetic fill data answers different question than real slippage).

**Verification:** 26 new tests; suite green (combined count see #97). Simulator vs real dataset: 82.95% fill rate, directionally consistent with order-events evidence; audit tool reproduces verified 23/23 pairing across 43 real backtests. #98's 2026-08-14 backtest exercised refactored code live first time: still 12/12, zero regressions. `PartiallyFilled` never appeared — permanent expected caveat (Lean's Daily-resolution fills), not defect.

---

### 97. Book-history reconciliation: bond duration-beta's deeper cold-start bug, reconciliation-tool eligibility fix, FX/crypto absence resolved (log artifact), misleading kill-switch count corrected (V5.3.1, continues #91-#95)

**Severity:** 9/10 → 2/10 · **Status:** 🟢 `mostly fixed and verified` (bond warm-up fix verified, see #98; NVDA/GE/WFC/XOM/BA root-caused and confirmed live, see #100/#102 — XOM's thin-sample result stays open)

**Problem:** Beneath V5.2.4/V5.2.5/V5.2.7 fixes, two real bugs remained: `bond_empirical_duration_beta` cold-start window; reconciliation tool's hardcoded eligibility assumption. Third suspect (FX/crypto missing candidacy) was measurement artifact. Fourth surfaced en route: V5.2.10's "0 real kill-switch trips" README claim was never a real measurement.

**Fix:**
- Bond warm-up floor (`main.py:598`, `21`→`self.long_bar_history_size`=260): the two `maxlen=260` deques feed beta fill during warm-up too (no `is_warming_up` gate), old floor left them far short of full, locking beta at `0.0` ~230 bars/backtest. Bonus: same cold-start gap fixed for `cross_asset_sensitivity`.
- Eligibility: `reconcile_book_history_date()`/`replay_book_history_reconciliation()` read real per-date `trading_eligible` from `book_history.jsonl`'s `"universe"` field instead of hardcoded `True`.
- FX/crypto ruled out live bug: run-segmented `summarize_universe_presence_by_symbol()` shows 100% absence only in one old pre-V5.2.4 run, 0% since — "32% absent" was cumulative-log averaging artifact, wired into `--reconcile-book-history` output so it can't hide again.
- Kill-switch count: `_count_real_kill_switch_trips()` now always returns `None` (real event Redis-only, never reaches counted text log) instead of fake `0`.
- NVDA/GE/WFC/XOM/BA: sector-neutrality ruled out by direct code proof (`apply_book_neutrality()` only reweights an already-selected book) — remains unexplained.

**Verification:** 11 new tests; with #96, suite 2574→2609, 0 failures. Bond warm-up confirmed via real A/B backtest — see #98 (Sharpe -1.72→-1.034, orders roughly halved, no downside found). Eligibility fix applied correctly, zero net effect on `mean_overlap_fraction` (24.02%) — #98 later found that re-run's target itself a contaminated multi-run log, so code fix stands unit-test-verified but 24.02% isn't a clean single-run number. FX/crypto segmentation reproduced by hand and tests.

**Follow-ups:** NVDA/GE/WFC/XOM/BA remains open — next lead is ranking/hysteresis path itself, not gates/neutrality. See #99 (V5.3.2) for two reconciliation-tooling bugs fixed and what they did (and didn't) explain.

---

### 98. Real V5.3.1 backtest (2026-08-14): Sharpe improves again; a suspected new "7-month disengagement regression" turns out to be pre-existing, not caused by B1 — corrects a same-session investigation error

**Severity:** 4/10 · **Status:** 🟢 `fixed and verified` (B1 specifically); the underlying gap's root cause stays 🟡 open, see Follow-ups

**Problem:** First real V5.3.1 backtest (`backtests/2026-08-14_18-46-38`, Sharpe **-1.034**) looked like severe new regression: 11 new `book_history.jsonl` records, orders down to 230 (from 476), apparent ~7-month engagement gap from 2019-01-01. Comparison target `book_history_v529_only.jsonl` turned out an undiscovered 7-run cumulative log — contamination class #97/B2 fixed elsewhere, missed here initially.

**Fix (self-correction):** Isolated true immediately-prior backtest (`backtests/2026-08-13_11-30-21`, Sharpe -1.72): identical signature in its own `order-events.json` — 202-day gap, same re-engagement dates. `git diff`: `main.py`'s only functional changes between runs were #96's refactor (behavior-preserving) + #97's warm-up floor; `config.json` unchanged. Clean A/B: gap shrank 202→169 days, orders roughly halved, Sharpe improved -1.72→-1.034. No evidence warm-up fix caused/worsened anything.

**Verification:** Gap analysis against both runs' own `order-events.json` (not cumulative log): pre-B1 202 days, post-B1 169. Record-diff confirms methodology sound; only comparison target wrong. Isolated re-run (11 genuinely-new records): `mean_overlap_fraction` 35.08%, 0/11 exact matches — too thin to compare vs #97's contaminated 24.02%. #97's other fixes re-confirmed: FX/crypto 0% absent, kill-switch count correct.

**Follow-ups:** why `min_rank_confidence_spread` (0.5014) rejects nearly every selection ~7 months from January 2019 is genuine open question — pre-existing, scoped as own future investigation.

**Update (V5.3.2) — closed, documented not a bug:** `ml/sequence_training_metrics.json` and `ml/multitask_training_metrics.json` carry `backtest.<head>_ranking_quality.observed.per_era` diagnostics (#71). All 4 combinations (sequence/multitask × rank_5d/rank_20d) independently show strong significant IC era 0 (2019-01-01→2019-03-31, t≈2.5-3.1), collapse to insignificant IC eras 1-2 (2019-04-01→2019-09-27, t between 0.09 and 0.87), sharp recovery era 3 (t up to 6.7) — exactly the window backtests disengage. Four independently-trained combinations agreeing rules out model-specific quirk: genuine low-dispersion, near-zero-edge stretch in real historical data; `min_rank_confidence_spread`'s documented purpose is refusing trade exactly then. No gate code change. Ruled out: regime/drawdown gate (`bypass_regime_drawdown_gate`) stateless, per-symbol/per-bar, never empties `book_allocations` — via `main.py:4493-4521`/`main.py:2770-2775` — cannot produce total zero-log-entry gap; sticky lock bypassed since #93, clears every time; sequence model's zero-padding during ~30-live-bar post-warmup fill (`main.py:3496-3507`) real but far too small (30 bars vs ~187-260 day gap), deliberate train/serve parity with `train.py`.

**Bonus, quantified finding — not applied this round:** currently-active head is `rank_5d`, not `rank_20d` (demoted for era-sign instability, via `resolve_rank_signal_policy()`); `min_rank_confidence_spread=0.5014` calibrated in #89 before demotion existed. Re-running `aq evaluate --calibrate-book-spread` vs current head returns **0.2901**; natural per-date spread median **0.36**, already below live threshold — current 0.5014 likely rejecting meaningful share of *all* dates, not just the genuine Apr-Sep 2019 stretch. Worth a future round; deliberately not applied (no backtest available to verify engagement/Sharpe effect; bundling would confound #99's comparison).

---

### 99. Reconciliation tool's own cross-run contamination and live-vs-offline tie-break order fixed; NVDA/GE/WFC/XOM/BA re-measured — neither bug explains it, but the real evidence now points somewhere new (V5.3.2, continues #91/#97)

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` (the two tooling bugs); NVDA/GE/WFC/XOM/BA's new lead chased down, fixed, confirmed live in a real backtest, see #100/#102 — XOM's thin-sample result stays open

**Problem:** Two tooling bugs beneath #97 (not live path): (1) `--reconcile-book-history`/`--replay-hysteresis` deduplicated dates across cumulative `visualization/book_history.jsonl` (last-write-wins) before reconciling — of 469 records/174 unique dates, **160 dates (92%) recur across >1 historical run**, one date in as many as 8; hysteresis silently carried `held_allocations` across run boundaries as one continuous backtest, so every overlap number ever reported measured a contaminated mix. (2) `cross_sectional_rank_scores()`/`_select_book_group()` are stable sorts keyed only on rank; ties resolve by caller's raw-scores dict insertion order — live builds it in `self.symbols` universe order (`config.json`'s `phase1.universe.assets`), tooling from pandas `groupby` (dataset row order); tied boundary pair could pick different winner live vs offline with byte-identical scores.

**Fix:**
- New `evaluation/rank_signal_calibration.py::segment_logged_records_by_run()` (extracted from #97's `summarize_universe_presence_by_symbol()`, refactored onto it).
- `aq_cli.py` dispatch (both paths shared the construction) segments first, defaults to **most recent run only**; new `--reconcile-run-index N` (0-indexed, negative from end), `--reconcile-all-runs` (each independently, never merged); payload byte-identical plus additive `run_metadata`/`all_runs`.
- Raw-scores rebuilt in `phase1.universe.assets` order before `cross_sectional_rank_scores()`; live decision path untouched (`portfolio/rank_signal.py`/`portfolio/book_construction.py` unchanged).
- `replay_book_history_reconciliation()` docstring: input must be single-run records, never raw cumulative file.

**Verification:** 12 new tests (`test_rank_signal_calibration.py`: 4 segmentation; `test_aq_cli.py`: 7 run-isolation/flags + tie-break fixture proving reconciliation follows configured-universe order; `test_portfolio_book_construction.py`: 1 documenting `build_rank_based_book()` tie-break deliberately insertion-order-dependent). Suite 2609→2624, 0 failures (11 pre-existing Docker-unavailable errors unrelated). Vs real `book_history.jsonl` (8 runs detected, matching hand count): default (most-recent, 11 dates) reproduces hand-isolated 35.08% exactly; `--reconcile-all-runs`: overlap 21-35% across all 8 individually — fairly stable, so #97's contaminated 24.02% wasn't wildly off in *magnitude*, just methodologically invalid. **NVDA/GE/WFC/XOM/BA on densest run (112 dates):** mismatch stays high (XOM 93%, WFC 78%, NVDA 69%, GE 52%, BA 48% of appearances); matched-day raw-score deltas large (0.11-0.21 on [0,1] percentile scale) — a tie-break artifact would show near-zero deltas on matched days; "live selects, offline doesn't" leads ~4-5:1 for all 5, sustained whole 2+ year run, not just near boundaries (rules out cold-start artifact too).

**New lead (not yet root-caused):** persistent raw-score computation discrepancy live vs offline for these 5 tickers specifically. Next step: compare live rolling-window feature computation (`main.py` deques) vs offline dataset-precomputed features directly — corporate-action history, vendor discontinuity, or window-fill difference specific to them; gates/hysteresis/tie-breaks all ruled out across #91/#97/#99.

**Update (V5.3.2) — root cause found for 4 of 5 tickers, see #100:** 63 of 77 equity tickers had no local Lean split/dividend factor file — offline trained unadjusted while live was always correctly adjusted.

---

### 100. Missing Lean split/dividend factor files for 63 of 77 equity tickers — offline trained on raw, unadjusted prices while live was always correct (V5.3.3, continues #91/#97/#99)

**Severity:** 7/10 → 2/10 · **Status:** 🟢 `fixed and verified` — real backtest confirms it live for GE/BA/NVDA/WFC, see #102. XOM and NVDA's residual divergence stay 🟡 open (small-sample/unexplained, not this bug)

**Problem:** `train.py::apply_split_adjustments()` backward-adjusts OHLCV via local Lean factor file (`data/equity/usa/factor_files/<ticker>.csv`) — same adjustment live feed gets automatically via Lean's `DataNormalizationMode.Adjusted`. Missing file → silent no-op (`load_factor_file()` returns `None`) → offline trains on **raw, unadjusted prices**. Of 104 assets (77 equities), only 22 had a file; other 63, incl. all 5 tracked tickers, didn't (incomplete data pull, not deliberate). Confirmed via real yfinance data: XOM/WFC/BA paid material uncorrected dividends in-window; GE additionally real 2019-02-26 corporate action (Wabtec spinoff). Each produces artificial return-dip offline never corrected, matching observed live-favors-these-tickers bias. NVDA's dividend negligible, splits outside window and invariant to return-ratio features — **not explained by this mechanism**, reported honestly.

**Fix:** New `data_pipeline/factor_file_backfill.py` (mirrors `dividend_backfill.py`'s `--apply`/dry-run convention), deriving real Lean-format factor files from yfinance dividend/split history. Run for real: 63 files written, zero fetch failures. `aq train --dataset-only` regenerated datasets; zero changes needed to `train.py`. `min_rank_confidence_spread` recalibrated fresh, applied to `config.json` (all 3 locations incl. two preset copies `aq config set` can't reach — direct JSON edit).

**Verification:** 14 new tests, suite 2624→2638. Mechanical fix confirmed on real ex-dividend dates (artificial dip disappears, correction matches event magnitude to 2 decimal places). Offline re-measurement mixed-but-net-positive; **backtest (#102) confirmed far more strongly live**: GE 52%→15%, BA 48%→12%, NVDA 69%→25%, WFC 78%→55%. XOM concerning 100% mismatch but only 9 appearances, too thin to conclude.

**Follow-ups:** XOM small-sample result and NVDA residual divergence need larger sample / different mechanism respectively. Full model retrain on corrected dataset out of scope (Codespace-only).

---

**Update (2026-10-06, V5.5.0):** "full retrain on the corrected dataset out of scope" was done by #106/#107 - **but** the factor files this entry generated were themselves double-adjusting already-adjusted zips (#130, repaired in V5.5.0); a dataset regeneration + Codespace retrain is the follow-up.

### 101. `aq evaluate --all`'s non-JSON reporting crashed on Windows — a Greek Δ character isn't in the cp1252 console codec

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** Refreshing README evaluation numbers post-#100 (`aq evaluate --all`, non-`--json`) crashed on Windows with `UnicodeEncodeError: 'charmap' codec can't encode character 'Δ'` — `aq_cli.py`'s delta-print line used a literal Δ, absent from the cp1252 console codec. The crash hit mid-`--all`, after rank-book reporting but before capacity/stress/calibrate-edge and the README refresh, so Windows-console runs silently left those numbers stale, with the error only on stderr.

**Fix:** Replaced Δ with an ASCII `delta_net_sharpe` label.

**Verification:** `py_compile aq_cli.py` clean; `test_aq_cli.py` (216 tests) green; both `--all` re-runs completed end-to-end, refreshing sections stuck since Aug 13.

---

### 102. Real V5.3.3 backtest (2026-08-17): factor-file fix strongly confirmed live for 3-4 of 5 tracked tickers — but the confidence-spread recalibration made real Sharpe measurably worse, isolated cleanly to that one change

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` (factor-file fix, #100, for GE/BA/NVDA/WFC); the confidence-spread regression is superseded: the floor was recalibrated to 0.1985 (V5.6.0) and 0.184 on the live pool (#146), confirmed by BT5-BT7 (V5.8.0 closure)

**Problem:** #100 shipped factor-file fix (offline-verified only) plus applied recalibration of `min_rank_confidence_spread` (0.5014→0.2831, verification deferred to user's own backtest). That backtest ran (Docker/`aq backtest`, 2019-01-01→2021-04-02, ~6.8 hours). Factor-file fix never touches `main.py`'s live path (#100); no other code changed vs prior real run (`backtests/2026-08-14_18-46-38`) — clean single-variable A/B on recalibration alone.

**Result — real, measured, not assumed:**
- Orders 230→**695** (lower threshold re-engages far more dates: 130→**360** unique trading days, max gap 169→**65** days).
- Sharpe **-1.034→-1.798** (worse). Net Profit -1.60%→**-5.51%**. Drawdown 5.10%→**6.90%**. Fees $335→$880.
- Period attribution via equity curve, same checkpoints: new run trades through 111 of ~124 days in the *known* no-skill era (2019-04-01→2019-09-27, per #98's diagnostic, t-stat 0.09-0.87 there) — equity fell **-1.71%** during that stretch vs -0.53% prior run mostly sitting it out. Rest of underperformance (most of it) from 2020-2021: prior recovered post-COVID (+0.47% Apr 2020→Mar 2021), this run declined (-3.27%) — likely same mechanism: era 4 (Dec 2019-Mar 2020) **negative** IC (-0.048), era 6 (Jun-Sep 2020) t=0.297 (indistinguishable from zero) — both now traded through.
- **Root cause of regression, not just symptom:** dispersion-percentile calibration measures whether model differentiates symbols at all, not whether differentiation is directionally *correct*. Per-era IC shows stretches with plenty of spread but near-zero/negative predictive validity — natural dispersion ≠ genuine skill; this calibration can't distinguish them.

**Factor-file fix (#100), by contrast, strongly confirmed — better than offline-only estimate suggested:** fresh `--reconcile-book-history --replay-hysteresis` vs this run's own `book_history.jsonl` (56 dates, densest sample of whole investigation): `mean_overlap_fraction` **56.9%** (highest of any run, vs 21-49% prior), `mean_raw_score_delta_abs` **0.019** (vs 0.1-0.2 every prior run). Per-ticker mismatch: **GE 52%→15%, BA 48%→12%, NVDA 69%→25%** — close to fully resolved, dramatically stronger than #100 predicted. **WFC 78%→55%** — real improvement, smaller sample (11 appearances). **XOM 65%→100% mismatch (9/9 appearances, 0 matched)** — outlier, sample too thin (9).

**Recommendation:** revert or raise `min_rank_confidence_spread` toward pre-V5.3.3 level, or find smarter calibration accounting for per-era IC stability rather than raw-score dispersion alone — applied 0.2831 shown on real data to trade through bad stretches the higher threshold correctly avoided. Do **not** revert factor-file fix — strongly validated. Exactly the single-variable, real-data-isolated finding this project's process exists to catch.

**Verification:** All figures pulled directly from the run's `1443519757.json`/`-order-events.json`/`-log.txt` plus a run-isolated `--reconcile-book-history` call against its own `book_history.jsonl` — nothing estimated or offline-only.

**Follow-ups:** decide/apply revised threshold future round, re-verify with another backtest; XOM needs larger sample before conclusions.

---

**Update (V5.6.0):** after the retrain the same calibration question was answered by the rule 'spread = the new models' p10': `min_rank_confidence_spread` 0.2831 → 0.1985 (p10 of 586 dates; median 0.26). Same-day dispersion floors still cannot separate skill (gate sweep), which is the rolling-IC gate's job.

### 103. A rolling trailing-IC gate, addressing #102's recommendation directly — built, offline-verified against real data, wired into `main.py` behind `enabled: false`; live effect not yet tested

**Severity:** 6/10 (same issue as #102) · **Status:** 🟢 `fixed and verified` — enabled since V5.5.0 and live in every backtest from 2026-10-07 on; its window/floor were re-decided by R-GATE in #146 and confirmed by BT5-BT7 (V5.8.0 closure; the holdout veto rate is studied in V5.8.0's gate audit)

**Problem:** #102 found `min_rank_confidence_spread` (same-day raw-score dispersion) can't tell "model differentiates symbols today" from "differentiation directionally correct" — recalibrated threshold traded through known no-skill eras because dispersion looked normal when skill didn't exist. #102's recommendation: smarter calibration accounting for per-era IC stability.

**Fix:** Independent second veto — `portfolio/rolling_ic_gate.py::evaluate_rolling_ic_gate()` gates book engagement on TRAILING REALIZED rank-IC (was model right recently), computed from live in-memory buffer of past predictions resolved against realized 20-day forward return, entirely separate from `min_rank_confidence_spread`. New `evaluation/rank_ic_core.py` extracts correlation/resolution math from `train.py`/`performance/rank_ic_monitor.py` into torch-free module so `main.py` imports without risking #16's isolator-timeout failure class (`train.py` imports torch/sklearn at module scope; `performance/__init__.py` transitively imports train.py). Two tools mirror existing patterns: `aq evaluate --calibrate-rolling-ic-floor` (floor derived from real walk-forward rolling-IC distribution, never guessed) and `aq evaluate --replay-rolling-ic-gate` (day-by-day no-lookahead replay, per-era breakdown vs three known bad eras — critical pre-`main.py` checkpoint). `portfolio/book_construction.py` gained additive `None`-default parameters (`rolling_ic_gate_result`, `veto_reason_out`) rather than return-type change — `build_rank_based_book()` has 6+ callers beyond `main.py`. `build_book_history_record()` gained `gate_veto_reason`; `main.py` book-history write condition fixed to log every genuine rebalance bar even when book returns empty (previously vetoed bar left zero trace, true since #91/V5.2.4 for existing dispersion gate too).

**Real bug found and fixed mid-round, via gate's own checkpoint:** first calibration+replay showed wrong pattern — era_2/era_3 0% disengagement even at raised floor while calibrated minimum was implausible -0.9999999999999999. Root cause: origin dates with 2-3 resolved names are mathematically FORCED to Spearman ±1 regardless of skill (two points fit any line); thin-universe readings averaged into `mean_ic` at equal weight with 100-name dates, dominating the low tail. Fixed via new `min_names_per_date` threaded through `rank_ic_from_arrays()`/`aggregate_rank_ic_observations()`/`compute_rolling_ic_state()` (default 2 preserves callers; tools/live default 10). Second bug surfaced: with filtering, `num_resolved_dates` structurally plateaus ~22-24 of 40-day window across entire dataset (start/middle/end checked, not warmup artifact) — `min_resolved_dates_required=40` could never satisfy, gate always fell back "insufficient history"; lowered to 20.

**Result after both fixes — real, measured:** calibrated floor at p25 (+0.020, `min_names_per_date=10`) replayed vs required=20: 20/82 rebalance dates disengaged (24.4%), cleanly concentrated — era_0 **0%**, era_1 (Apr-Sep 2019) **37.5%**, era_2 (Dec 2019-Mar 2020) **22.2%**, era_3 (Jun-Sep 2020) **22.2%**. Era_3 spot-check: readings mostly strongly positive (0.19-0.63) with brief real no-skill dip mid-July 2020 (0.005 then -0.091) gate correctly narrowly catches.

**Verification:** New tests: `test_rank_ic_core.py` (13), `test_rolling_ic_gate.py` (14), `test_rolling_ic_gate_calibration.py` (7, incl. no-lookahead prefix-invariance), `test_rolling_ic_gate_replay.py` (8, headline property), `test_portfolio_book_construction.py` extended (+9 incl. byte-identical-when-`None` guard). Suite 2688 passed, 0 failures (11 pre-existing Docker errors unrelated). Both CLI tools ran vs real `ml/datasets/backtest_dataset.csv`; fresh `--reconcile-all-runs` vs all 9 backtests confirmed optional parameters changed nothing existing. Config ships `enabled: false`.

**Follow-ups:** user's manual `aq backtest` verifies actual Sharpe improvement over #102's -1.798 baseline (same discipline as #102: offline story looked right for confidence-spread too, real backtest showed regression). Before run: `aq config set phase_v2.rolling_ic_gate.min_rolling_mean_ic 0.02`, then `...enabled true`. After: check `gate_veto_reason` in `book_history.jsonl` for `"rolling_ic_below_floor"` during bad eras specifically (vs `"min_rank_confidence_spread_below_floor"`, meaning old gate doing all work). Workstream B (feature-level XOM investigation, see #91/#100) scoped, not started — independent.

**Update (2026-08-19 real backtest — written up in V5.3.5.3):** prescribed run happened (`backtests/2026-08-19_13-33-56`, both `aq config set` commands applied, gate live at floor 0.02). **Headline: Sharpe -1.798 → -1.832 — gate did NOT recover regression** (Net -5.51%→-5.888%, Drawdown 6.90%→6.400%). But mechanism works as built: orders fell 695→462 (-33%), fees $880→$596.54, and `gate_veto_reason` answers verification question directly — new veto fired 106x vs old spread gate's 21x (plus 260 pre-existing `thin_universe_or_zero_top_n`) across cumulative log, i.e. `rolling_ic_below_floor` genuinely does most disengagement work now, not a passenger. Honest interpretation: gate refuses low-skill stretches, but what it ALLOWS through isn't profitable either — engagement quality outside bad eras is binding constraint; pre-V5.3.3 -1.034 baseline unrecovered. Per user decision, gate stays enabled at 0.02, spread stays 0.2831 — V5.3.5.3 measures exactly this configuration. Workstream B shipped in V5.3.5.3 (see Changelog): `build_book_history_record()` allowlist-bounded `feature_snapshot` field, `phase_v2.diagnostics.book_history.include_feature_snapshot`/`feature_snapshot_symbols` flags, `aq evaluate --reconcile-features --symbol XOM`; XOM verdict awaits snapshot-collecting backtest.

---

### 104. Chronic Lean embedded-Python teardown hang ("endless loop") — fires only after normal completion, never affects results; probe shipped, culprit unnamed

**Severity:** 3/10 (exit-log noise only — results are always fully written first) · **Status:** 🔴 `closed` — environmental (reproduced with a trivial algorithm; no code fix possible here)

**Problem:** commit c2ed98c's "endless loop found in backtest log" is Lean embedded-interpreter teardown timing out: after `PythonInitializer.Shutdown(): start/calling engine shutdown...`, ~10s elapse, then `Isolator.ExecuteWithTimeLimit(): Execution Security Error: Operation timed out - 0.1666... minutes max. Check for recursive loops. (Isolator.cs:179)` and `Program.Exit(): Failed to shutdown python System.TimeoutException (Launcher/Program.cs:145)`. Classic CPython finalization blocking on still-alive non-daemon thread or native handle while isolator kills interpreter at its 10s limit.

**Differential analysis (all local logs checked):**
- **Chronic, not new:** 72 of 78 runs reaching teardown hang identically, back to earliest log on disk (2026-05-07), spanning many code versions — nothing recent introduced it.
- **Never affects results:** hang occurs after statistics/JSONs/order-events fully written; impact limited to ERROR line, failed exit code, ~10s wall clock.
- **Normal completion vs error termination is the discriminator:** both genuinely-clean completed runs (2026-07-06_17-35-38, 2026-07-19_16-48-18) terminated via mid-run Python runtime error or Stopped state; essentially every run whose Python execution reached normal completion hangs — something built during bar processing survives to block finalization.
- **Ruled out:** duration/window size (4.53s run hung; 14.53s exited cleanly); inference parallelism pool (#70's explicit pool.shutdown() exists, ships default-off anyway); audit/experience queues (no threads / daemon=True drain thread); matplotlib/pyplot use in main.py (none); cpp_inference_ext in hot path (none).

**Fix (this round):** no speculative fix without named culprit. `main.py::on_end_of_algorithm()` gained zero-risk shutdown-probe: Debug line dumping every still-alive thread (name + daemon flag) right before teardown begins, so next run's log shows exactly what survives and blocks finalization.

**Verification:** py_compile only so far (no unit test can exercise embedded-interpreter teardown). Decisive evidence is next real backtest: log should carry `shutdown-probe:` line immediately before timeout (or clean exit with probe present narrows trigger).

**Follow-ups:** read `shutdown-probe: alive_threads=[...]` from next run's log; once surviving resource named, add targeted cleanup (explicit close/shutdown of owning library object), re-verify with subsequent run's clean `PythonInitializer.Shutdown(): ended`.

**Update (2026-08-27 real backtest — `backtests/2026-08-27_12-01-48`) — CORRECTED 2026-10-06:** this entry originally recorded the run as "exited cleanly", read from the *algorithm* log (`1773747993-log.txt`: `shutdown-probe: alive_threads=[]` + `completed in 2816.67 seconds`). The *engine* log `log.txt` shows the hang **did** happen: `10:51:23 PythonInitializer.Shutdown(): calling engine shutdown...` → `10:51:34 Operation timed out` → `Program.Exit(): Failed to shutdown python`. All 9 runs since 2026-08-10 carry it. The empty `alive_threads` list is still real evidence: the blocker is **not a Python thread** — it is native/.NET-side (a pythonnet-held reference, e.g. Lean `Symbol`/`Slice` objects held by long-lived dicts, or the frozen GC generation since `gc.freeze()`). V5.5.0 (Problems #129) adds a richer opt-in probe + opt-in pre-shutdown cleanup. Status stays 🟡 until a run's **engine** `log.txt` shows `PythonInitializer.Shutdown(): ended`.

**Update (V5.6.0) - closed as environmental:** BT1 ran the strongest cleanup yet (Python slippage model detached from all 104 securities, GC unfrozen, containers cleared, no `gc.freeze()`): still `Operation timed out` at `PythonInitializer.Shutdown()`. A 15-line algorithm (SPY daily, no custom objects, `mini_teardown/`) hangs identically in the pinned `lean:17900` image (`Failed to shutdown python`), so the cause is the engine image, not this code; results are always written first. The experiment code stays behind `phase_v2.diagnostics.teardown_cleanup.release_models` (default off). The `latest` image probe was cut short by the memory reaper.

**V5.8.0 evidence:** BT1 and BT2 both ended with `PythonInitializer.Shutdown(): calling engine shutdown...` and the 10-second `Execution Security Error` only after `*-summary.json`, the order events and the report data were written; results were never affected, so the entry stays 🔴 environmental.

### 105. Train-vs-live feature-parity audit (V5.3.6 WS-A) - scaler artifact verified exact; NO live-path formula drift found in all OHLCV-recomputable families; residual deltas fully attributed to replica boundary artifacts

**Severity:** n/a (verification pass; would have been 9/10 had drift been found) · **Status:** 🟢 `verified clean` for covered families; watch items documented

**Motivation:** #91/#98/#100's XOM-class divergence needed either a per-feature root cause or a systematic rule-out. Two prior bugs WERE feature-drift classes (duration-beta V5.2.5, factor files #100), so this round built the permanent audit instead of another one-off.

**Shipped:**
- `evaluation/feature_parity.py` - pure core: scaler-mapping validation (49 continuous vs 66 schema inputs; the 17 binary one-hots intentionally skip StandardScaler - verified correct-by-design on both sides), forward-transform `clip((raw-mean)/scale, +-clip)`, row-faithful replicas of `engineer_features()`' base technicals + indicators block and `add_liquidity_features()`, per-ticker OWN-calendar momentum (`compute_momentum_long()` - union-calendar pivots provably wrong: TLT pivot-shift diverged from own-calendar on 78% of rows, max 0.16), macro as-of proxies, and an EXACT replica of `cross_sectional_momentum_rank()`'s semantics (NaN values count in the len() denominator while never winning </== comparisons - a plain pandas rank gets this wrong).
- `scripts/feature_parity_audit.py` - three-check driver writing `ml/evaluation/feature_parity_report.json`: (1) synthetic replicas-vs-train parity, (2) real-data forward check raw->artifact->stored column with POSITIONAL classification of residual mismatches (warmup / within-260-bars-after-date-gap = expected build-time-frame artifacts vs unexplained = fail), (3) structured verdicts for shared-function families.
- 15 tests in `tests/test_feature_parity.py` incl. direct replica-vs-train pins and the scaler round-trip invariant.

**Results (real data, 163,227 rows x 104 assets):**
- Scaler artifact <-> dataset: EXACT (<=7e-13) wherever no hole interaction; 49/49 continuous inputs aligned with schema; clip layer semantics confirmed (1,024 legit crypto fat-tail saturations on return_1d).
- Formula parity: 10 base technicals + 6 indicators + cs_momentum + 3 macro proxies + 2 liquidity features VERIFIED against stored columns; every residual mismatch class attributed: warmup offsets from the dropped first raw row, mid-series label-guard drops creating holes that build-time trailing windows legitimately spanned (macd EMA memory), young-ticker NaN denominators, reference-warmup month (Dec 2014 macros).
- Genuinely unexplained: <20 rows total (0.01%): DOGEUSD 2021-01-28..02-02 rsi cluster; AAA 2020-10..11 macd/dist cluster; IGIB/IGSB/NKE single-row volume_change events. No live-path mechanism implicated.
- **XOM-class feature drift: RULED OUT** for all OHLCV-recomputable families at both formula and scaling layers.
- Structural finding: most families flow through SHARED `features/*.py` functions imported by both sides (main.py:179-209) - residual risk there is call-site parameters only (documented per-family in the report).

**Crypto zero-volume quirk (part of #93's open note) - ROOT CAUSE NARROWED:** source Coinbase zips carry REAL always-positive volume (btcusd_trade 0/2279 zeros); BTCUSD additionally ships a QUOTE zip (11-col bid/ask). Live BTCUSD bars arriving volume=0 despite OHLC therefore points at Lean delivering BTCUSD via quote-type data (volume meaningless) while LTCUSD rides trade bars. Fix direction: subscription/data-type level, not our liquidity code; existing `zero_volume_fallback_ddv` already mitigates sizing. Left open pending a targeted Lean-side experiment.

**Initialize() latency static audit:** post-V5.1.11/#16 fixes, main.py's module scope pulls NO torch/sklearn chains (train.py never imported; performance package deferred); remaining startup cost is artifact JSON loading + Lean-side setup. Deferral candidates: none obvious beyond prior fixes; measure precisely inside the next real run's log.

**Shutdown-hang (#104) thread-site enumeration:** live-path Python thread/pool creators are exactly three - main.py's guarded ProcessPoolExecutor (explicitly shutdown, default-off), experience queue's daemon=True drain thread, opt-in parallel-inference pool. No unaccounted non-daemon creator exists in our code -> culprit is library/native side; the shipped `shutdown-probe:` remains the decisive instrument.

**Verification:** 15 new tests green; driver runs end-to-end on real data; report committed under ml/evaluation/.

**Update (V5.6.0):** the crypto zero-volume lead is settled - BT1's bar probe shows BTCUSD/LTCUSD arrive as `TradeBar`s with real volume on 90 of 90 bars (once the quote zips exist). Feature parity itself was re-opened and closed by #137/#140/#141 (the audit's replicas now follow the live tick order and forex's fill-forward calendar).

### 106. Gate sweep, kill-switch offline finding, promotion-gate null calibration, overlap-vs-Sharpe pairs, first Codespace retrain on synced tree (V5.3.6 WS-B/C/D/E + training)

**Severity:** n/a (calibration/verification round) · **Status:** 🟢 `fixed` — every pending decision was taken in V5.6.0/V5.7.0 (spread floor, IC gate, kill switch, promotion rule: #142-#146) (V5.8.0 closure)

**WS-B gate sweep** (`scripts/gate_sweep.py` -> `ml/evaluation/gate_sweep_results.json`; multitask rank_5d mirror, 2019+ window, 82 rebalance dates):
- Base offline book: **net Sharpe +1.497 / gross +1.567** - the offline edge is real; the gap to live -1.8 remains execution-side.
- Rolling-IC floor grid (w40): floor 0.00 -> era_0 0% disengaged, bad eras 31/33/11%; **floor 0.02 (#103 calibrated) -> era_0 0%, bad eras 37.5/33/11%**; floor 0.05 -> era_0 still 0%, bad eras 56/44/22%. Aggressive 0.05 doubles bad-era coverage at zero good-era cost OFFLINE - candidate for the next A/B decision.
- Same-day dispersion floors: even p50 bites era_0 22% (p90 kills it 67%) - reconfirms #102's core lesson that dispersion floors cannot separate skill.
- **WS-D kill-switch grid**: ZERO trips at all nine min_rolling_sharpe x evaluation_bars combos over offline returns -> the live 26-trip/run sensitivity is a LIVE-PATH phenomenon and cannot be floor-tuned from offline replay alone.

**WS-E promotion-gate null calibration** (`scripts/promotion_gate_null_calibration.py` -> JSON; 400 perms of within-date target-rank shuffles): P(null t>=2.0)=**2.75%** so the t-bar is a genuine filter and the real signal's t=2.61 sits beyond null p99. BUT **66% of skill-free runs show >=2 negative eras (mode=2)** -> `era_sign_instability` blocking promotion at 2 flipped eras is statistically uncalibrated/too strict; recommend replacing raw flip counts with a null-comparison rule (flag only beyond null p95, or per-era mean t-test). Real model shows only 1 negative era - better than two-thirds of pure noise.

**WS-C overlap-vs-Sharpe** (`scripts/overlap_vs_sharpe_analysis.py` -> JSON): collection tooling fixed (launcher-log parsing; ordinal pairing documented - sim-window matching is ambiguous because all real runs share one window). Only 3 unique dated segments have computable overlaps today: 0.226/-1.034, 0.269/-1.798, 0.491/-1.832 - highest overlap paired with worst Sharpe, directionally consistent with history but n=3 inconclusive by definition. Accumulates automatically with future runs.

**First Codespace retrain on fully synced tree:** code+ml(806MB incl datasets)+data(213MB) synced via scp -F route (`gh cs cp` broken); pipeline completed (~10 min: baseline val-acc 0.5306 best_epoch 41, 4 experts trained, gating eligible bullish/bearish/sideways); artifacts pulled back to `ml/versions/codespace_v536_20260823/` (NOT promoted - promotion is an explicit user decision). Codespace stopped after pull. Bugs found en route: `gh cs cp` upload broken in current gh (use ssh-config+scp); PowerShell `$()` expansion corrupts remote find commands (single-quote remote commands); engineer-side drop is the LAST row (shift(-1) target NaN), not the first.

**Follow-ups:** decide rolling-IC floor (0.02 shipped vs 0.05 aggressive) and confidence-spread fate before next A/B backtest; adopt null-calibrated era rule behind a flag if agreed; accumulate WS-C pairs from future runs.

**Update (V5.6.0):** the sweep re-run on the retrained models (multitask scoring): rolling-IC floors 0.00/0.02/0.05 all leave the good era 0% disengaged; bad-era coverage rises with the floor (0.05: 56/44/22%). The pre-registered rule - highest floor with zero good-era cost - keeps `min_rolling_mean_ic` at 0.05; kill-switch grid unchanged (zero trips offline).

### 107. Null-calibrated era promotion rule (V5.3.7): era_rule selector shipped; 90-day-era null shows ZERO noise flips - existing strict criterion validated, calibrated flip_fraction knob adopted as the enabling mechanism for the V5.3.7 candidate

**Severity:** n/a (promotion-methodology round) · **Status:** 🟢 `shipped; candidate promoted unconditionally per user decision`

**Correction to #106's readout:** WS-E's "66% of noise runs flip >=2 eras" used five COARSE buckets and no magnitude floor. The gate's own criterion (9-10 consecutive 90-day eras, |mean_ic| >= era_sign_min_abs_ic=0.05, num_dates>=3) re-measured over 400 permutations produces **ZERO opposite-sign eras at every percentile** (`ml/evaluation/promotion_gate_null_gate_scheme.json`) while the real signal sits at fraction 0.222 (2/9). The strict rule is therefore well-calibrated, not broken - the earlier readout was a denominator/magnitude-floor artifact.

**Shipped:**
- `phase1.target.ranking.promotion_gate.era_rule`: `"legacy"` (default, byte-identical) | `"flip_fraction"` - in flip_fraction mode the any-flip hard failure is skipped (recorded as a near-miss diagnostic instead) and blocking comes solely from `max_era_sign_flip_fraction` (existing dormant knob, config value 0.34: above both null-max=0.0 and the real candidate's 0.222, yet still guards >1/3-eras instability).
- `scripts/promotion_gate_null_gate_scheme.py` + JSON results; 6 tests pinning legacy parity, flip-fraction pass/fail boundaries, missing-key default, t/CI gates still applying.
- Registered under `_SUBSYSTEM_TEST_FILES` evaluation bucket.

**Verification:** suite green through the change; candidate metrics carry the new thresholds block.


**V5.3.7 completion addendum:** full 8-family Codespace retrain executed on the synced tree WITH `era_rule: "flip_fraction"` active; gating/multitask/sequence candidates built via `--version-id v537cs20260823` (bare invocations exit-2 on required --version-id - fixed en route). **Walk-forward is infrastructure-blocked**: three consecutive VM reboots killed the job at window 5 across baseline-only / multitask / multitask+sequence configs (uptime evidence; 7.8GB CS RAM; swapon prohibited in container) - partial windows 0..3 preserved under `ml/versions/v537cs20260823/ml/versions/walk-forward-*`; relaunch command ready. Candidate promoted unconditionally per user decision: 15 prior artifacts backed up to `ml/_backup_pre_v537/`, 12 top-level artifact files + expert_models/ promoted (per-family metrics JSONs for gating/multitask/sequence remained pre-V5.3.7 - display-only staleness, recoverable by rerunning the three trainers). Offline evaluation of the PROMOTED multitask rank book: **net Sharpe 1.6805 (lag0) / 1.6933 (lag1)**, net return +10.61%, maxDD -2.63%, turnover 1.32x - above the pre-V5.3.6 mirror (+1.497). Sequence: net Sharpe 0.997/0.955.

**Update (V5.6.0):** the walk-forward relaunch completed on the regenerated dataset (6 expanding windows, `walk-forward-f56af970-...`; the Codespace VM rebooted twice and `--resume-run-id` finished it): `rank_20d` IC mean 0.101 (95% CI 0.066-0.138, 0 sign flips), `rank_5d` 0.059 (0.042-0.081, 0 flips), `backtest_mcc` 0.016 (stable), `residual_rank_20d` -0.002 (unstable, 3 of 6 flips). Infrastructure blocker (#83/#107) closed.

### 108. Monte Carlo simulation testing layer — `aq evaluate --rank-book --monte-carlo` with auto-refreshing README section (all-run curves chart + red average line + foldable deep stats)

**Severity:** n/a (verification-layer feature) · **Status:** 🟢 `shipped and live-verified`

**Problem:** N/A — Monte Carlo simulation over the offline rank book, surfaced as an auto-refreshing README section and a webui panel.

**Fix:** Added `evaluation/monte_carlo.py` (pure, seeded, numpy-only: a stationary block bootstrap, default 20-day blocks, of the book's daily NET returns into N=1000 alternative equity histories, emitting per-run downsampled curves, the element-wise average, and return/Sharpe/maxDD percentile tables + loss probability, degrading cleanly under 30 samples); the `aq evaluate --monte-carlo [--mc-runs --mc-block-size --mc-seed --mc-method]` CLI (implying `--rank-book`) writing `monte_carlo.json` and `monte_carlo_curves.npz`; a README subsection plus the all-runs PNG (faint blue runs + red average + baseline); and a `MonteCarloPanel.tsx` webui panel served via `/api/evaluation`'s `monte_carlo` key.

**Verification:** 9 dedicated python tests plus 4 vitest component tests and 2 state tests (vitest 100/100 across 23 files, tsc/build clean); the first real run on the promoted multitask book (565 days) gave return p5/p50/p95 = −2.00% / +9.38% / +21.45%, Sharpe p5/p95 = −0.18 / 2.52, maxDD p95 = 9.11%, P(negative) = 9.5%.


**V5.3.8 webui integration addendum:** Monte Carlo surfaced as a first-class evaluation panel — `webui/src/components/evaluation/MonteCarloPanel.tsx` (config echo, inline SVG average curve with p5/p95 band, return/Sharpe/maxDD percentile table, loss probability + best/worst) mounted on the Evaluation page; `monitoring/evaluation_state.py` now serves `monte_carlo.json` via `/api/evaluation` (`monte_carlo` key, honest not-evaluated fallback). TS types added (`MonteCarloReport` etc.; legacy fixtures tolerated via optional keys). Tests: 4 vitest component tests (empty state, config/distribution render, SVG paths present, backend not_evaluated parity), 2 python state tests, full vitest suite **100/100 across 23 files**, `tsc -b --noEmit` clean, production build clean. Bugs found en route: float artifact in fixture (9.38-2=7.380000000000001) and missing KillSwitchReplayReport TS type — both fixed.


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


### 112. V5.4.1 - RL sizing reward asymmetry fix (root-cause of 3× honest negative), regime conditioning in state vector, auto-rollback hardening (dry-run + degradation score), prediction provenance counters, topology EWM option deferred

**Severity:** n/a (model-improvement round) · **Status:** 🔴 `closed` — RL sizing retrained with the fixes, still no edge over constant 1.0

**RL sizing root cause identified and fixed:** the reward function was SYMMETRIC - undersizing a winner and oversizing a loser cost identically, so "do nothing" (constant 1.0 baseline) was always optimal, which the policy correctly learned every time (3× honest negative). Fixed with an `asymmetric_penalty_weight` parameter (>1.0 penalizes foregone profit on winning trades). Also added regime trend one-hots (`regime_trend_bullish/bearish/sideways`) to `RL_SIZING_STATE_KEYS` so the linear policy can learn regime-conditional sizing.

**Auto-rollback hardened:** new `retraining/rollback_hardening.py` with `compute_degradation_score()` (continuous 0-1 weighted composite) and `select_rollback_target_dry_run()` (same return shape + `dry_run: True` + degradation score for audit without execution).

**Prediction provenance:** per-session counters (`sequence_served` vs `multitask_fallback`) logged at shutdown via `prediction-provenance:` Debug line alongside #104's shutdown-probe.

**Codespace retrain NOT yet executed** - user must start codespace and trigger; all code changes are in place.

**Update (V5.6.0) - closed:** the RL retrain ran twice on the regenerated data with the penalty sweep (1.0/1.5/2.0/3.0, chosen on a chronological holdout of validation) and judged on unpenalised backtest P&L: policy -8.98e-5 vs constant 1.0 at -8.43e-5 (and -8.75e-5 vs -8.29e-5 on the first dataset). A fourth honest negative; the action set is shrink-only, so the policy can only lose to the baseline unless the state predicts losers. Not installed; `rl_sizing_enabled` stays false.

### 113. V5.4.2 pre-backtest audit — critical missing-import bug found and fixed; parity tests added; config validated

**Severity:** 8/10 (would have crashed forex path + silently killed sequence model on every bar) · **Status:** 🟢 `fixed and verified`

**Problem:** The V5.3.10 extraction of `_midpoint_bar_from_quote_bar()` and `_pad_sequence_history()` into `data_pipeline/bar_synthesis.py` never added the corresponding import to main.py, so the thin delegation bodies referenced unbound names — a runtime `NameError` that `py_compile` and CI both missed since no test imports main.py. The blast radius was a hard crash on the first forex quote-bar tick, a silently dead sequence model every bar, and a permanently-zero `sequence_served` counter.

**Fix:** Added the module-scope import in main.py, 5 parity tests in `test_bar_synthesis_parity.py` registered in `_SUBSYSTEM_TEST_FILES`, and removed a duplicate "Syntax-check main.py" CI step (a V5.3.11 rebase regression).

**Verification:** Full suite 2769 passed / 0 failed; py_compile clean; ruff clean; all 6 pre-backtest config checks PASS.


### 112. V5.4.2 - residual_rank_20d head documented as non-promotable; factor-neutralization check scoped for V5.4.3; Almgren impact model shipped; residual head excluded from decision process via config

**Severity:** n/a (signal-quality documentation) · **Status:** 🔴 `closed` — head confirmed noise; kept demoted

**Finding:** `residual_rank_20d` (the market/sector/size-neutral rank target) has never cleared its promotion gate across any retrain round. Its IC is consistently ~0.01 with t-stat < 1.0 — statistically indistinguishable from noise after neutralization overhead. The active heads list (`rank_20d` 0.5, `rank_5d` 0.5) never included it, so no live behavior change from this entry.
**Action taken:** added `residual_rank_20d` to the documented demoted list in config.json. Factor-neutralization check (decomposing book Sharpe into alpha vs factor components) scoped for V5.4.3 — requires one full offline eval run to produce the decomposition data.

**Update (V5.6.0) - closed:** the walk-forward on the regenerated dataset gives `residual_rank_20d` IC -0.002 (95% CI -0.029..0.025, unstable), and zeroing the residual/sector-neutral head loss weights (variant `v2_book_heads`) did not clear the 0.028 seed spread in either retrain round. The head stays demoted from the book; the retrain validation gate no longer judges it (#139).

### 114. V5.4.4 - CI python-lint red since V5.4.3 (2 ruff findings); Monte Carlo README PNG showed only the average; HRP single-sided books silently halved

**Severity:** 5/10 (CI red blocks the merge signal for every later PR; the HRP bug would have silently halved the default book's exposure the moment `allocation_method: "hrp"` went live) · **Status:** 🟢 `fixed and verified`

**Problem 1 (CI):** `ci.yml`'s `python-lint` job failed after ~8s on every push since V5.4.3, which had shipped two ruff findings — `F841` unused local `next_date` (`evaluation/benchmark_comparison.py:48`) and `F401` unused `scipy.cluster.hierarchy.fcluster` import (`portfolio/hrp_allocation.py:16`) — unnoticed locally because `aq test` runs ruff only under `--ruff`.
**Fix 1:** Removed the dead assignment; dropped `fcluster` and hoisted the function-level `leaves_list` import to module scope.

**Problem 2 (README chart clobbered by the test suite):** the Monte Carlo PNG showed only the red average with a degenerate 2-point x-axis, root-caused (by byte-hashing the PNG before/after isolated test runs, not staleness) to `generate_evaluation_report.py::update_readme_evaluation_sections()` unconditionally rendering the real repo PNG from `load_monte_carlo()`, while a report test monkeypatched `EVALUATION_DIR` to a tmp dir holding a degenerate `(10×2)` fixture — so **every full-suite run overwrote the real chart with the fixture render**.
**Fix 2:** Render the chart only when the target readme resolves to the real `README_PATH`, spy-assert the tmp-readme path doesn't render, add a fully-hermetic companion test, add two regression tests intercepting `Axes.plot`, and regenerate the chart from the real npz.

**Problem 2b (test-badge reset, same bug class):** the README tests badge stayed frozen at `2751` because `test_aq_test_ruff_flag.py::test_ruff_flag_clean_repo_passes_through` mocked `_run_captured` with a hardcoded `"2751 passed"` but (unlike its siblings) didn't mock `aq_cli._update_readme_test_badge`, so the real writer rewrote the README badge every full-suite run.
**Fix 2b:** The test now mocks the badge writer like its siblings.

**Problem 3 (found during V5.4.4 HRP integration, pre-wiring):** `build_hrp_allocation()` split gross unconditionally 50/50 across legs, so a single-sided book (the shipped `long_flat` default) would have received only gross/2 on its one populated leg; latent since the module had no production caller before V5.4.4.
**Fix 3:** Two-sided books keep the ±gross/2 split (byte-identical); single-sided books give the present leg the full gross, with regression tests for long-only (+1.0), short-only (−1.0), and two-sided (±0.5) leg sums.

**Also fixed (test-caught):** `pct_returns_from_closes()` skipped only non-positive *previous* closes, so a 0 current close still emitted a −100% return (a variance bomb into HRP's covariance estimate); now any pair touching a non-positive/None close is skipped.

**Verification:** Full suite 2816 passed / 0 failed (up from 2790); ruff clean; py_compile clean; chart manually inspected.


### 115. V5.4.4 - installed `aq` console script broken for `evaluate`/`audit` (packaging gap); mean-reversion baseline was a hardcoded placeholder

**Severity:** 6/10 (the published CLI's flagship subcommand crashed on import for anyone who installed it; the placeholder silently contributed a meaningless 0.0 row to benchmark comparisons) · **Status:** 🟢 `fixed`

**Problem 1:** Running the installed `aq` console script (`pip install -e .` + `aq evaluate ...`) raised `ModuleNotFoundError: No module named 'evaluation'` — `[tool.setuptools] packages` listed only `risk`/`execution`/`data_pipeline`, but `aq_cli.py` imports `evaluation`, `features`, and `audit` in-process and `evaluation` transitively pulls `portfolio`/`inference`/`analyzer`; the same class of gap hid `generate_evaluation_report` from `py-modules`, breaking the README refresh. Masked locally because pytest and the Lean container put the repo root on `sys.path`.

**Fix 1:** Extended `packages` with `evaluation`, `portfolio`, `features`, `audit`, `inference`, `analyzer` and `py-modules` with `generate_evaluation_report`; `aq evaluate --benchmarks` now runs end-to-end from the installed script.

**Problem 2:** `evaluation/benchmark_comparison.py::mean_reversion_baseline()` (V5.4.3) accrued a hardcoded placeholder (`sum(held_weights.values()) * 0.001`) instead of realized returns, so its Sharpe and total return were structurally 0.0 no matter the data.

**Fix 2:** Real next-day close-to-close accrual mirroring `momentum_baseline()` (plus `pct_change(fill_method=None)` to kill a pandas FutureWarning and stop pad-fill fabricating flat 0% days), moving real backtest-split numbers to −0.119 Sharpe / −20.96% total return; two new tests pin it.

**Verification:** Full suite 2834 passed / 0 failed; vitest 103/103; ruff clean; real `aq evaluate --benchmarks` verified end-to-end from the installed console script.


### 116. V5.4.5 - pre-backtest live-execution audit: round-trip commission undercounted 2x in the net-edge gate; paper mode ignored every risk lock

**Severity:** 6/10 (the gate is enabled+calibrated in the shipped config.json, so every entry/resize decision in the upcoming backtest understated its cost leg; the paper-mode gap would have let a tripped kill switch keep submitting real broker orders) --- **Status:** 🟢 `fixed`

**Problem 1:** `execution/cost_model.py::estimate_round_trip_cost_bps()` computed only ONE side's commission (rate leg and `min_commission_usd` floor alike) inside a function contracted as a round-trip estimate against a parameter named `commission_bps_per_side`; with the shipped config (1.5 bps/side, $1 floor) the commission was understated ~1.5-2x, letting trades through whose true net edge sat between the real and underestimated cost — live more optimistic than the offline simulator, which charged per-side on both-side turnover.

**Fix 1:** Each side's commission is `max(rate leg, dollar floor)` and the round trip pays it twice; the two tests pinning the old single-side math were updated and two new tests pin both sides (rate- and floor-dominated).

**Problem 2:** `execution/order_gate.py::resolve_order_permission()` checked `risk_locks_healthy` only in the `live` branch, so `paper` returned True from flags + broker config alone — a tripped kill switch/drawdown lock/manual lock could not stop real broker orders in the one non-live mode that reaches a brokerage.

**Fix 2:** Paper now requires all three, returning a distinct `paper_orders_blocked_risk_lock` reason; backtest mode unchanged by design.

**Verification:** Full suite 2858 passed / 0 failed; ruff clean.


### 117. V5.4.5 - NaN propagation family: NaN silently skipped safety triggers, poisoned fill prices, reconciliation reported false-clean, and NaN ranks bypassed the book spread veto

**Severity:** 7/10 latent (every guard in the family was a one-sided float comparison or an `is not None` check - all of them are False/pass-through for NaN) --- **Status:** 🟢 `fixed`

**Problem:** A single root cause across the live path — every guard in this family was a one-sided float comparison or an `is not None` check, all of which are False/pass-through for NaN (found by structural review; `nan > x`, `nan < x`, `nan <= x` are all False and max/min pass NaN through).

**Fix:**
- **risk/kill_switch.py:** guards checked only `is not None` before comparing, so a NaN drawdown-velocity/rank-IC/slippage-divergence silently skipped its own condition while the switch appeared armed, and one NaN return made `_rolling_sharpe()` NaN; added `_finite_or_none()` normalization at the five metric inputs and made `_rolling_sharpe()` return None for any non-finite window.
- **execution/order_gate.py:** the clamp meant to guard degenerate estimates was defeated by NaN (`max(nan, 0)` = nan); non-finite price/bps now degrade to 0.0 slippage at both chokepoints.
- **execution/reconciliation.py:** `max(0.0, abs(nan))` kept `max_abs_weight_drift` at 0.0 so a corrupted mark could never trip the kill switch's reconciliation trigger, and an explicit None weight crashed `float(None)`; non-finite weights now force infinite drift (fail-closed) and None degrades through the same path.
- **execution/cost_model.py:** NaN edge/cost failed closed but with the generic below-threshold reason; now an explicit `non_finite_cost_estimate` reason with finite JSON sentinels.
- **portfolio/book_construction.py:** a NaN `predicted_rank_20d` passed eligibility, poisoned sort/hysteresis, and silently disabled the spread veto (NaN comparisons are False); fixed via a `_is_finite_number()` eligibility guard, filtered spread-check ranks, and skipping NaN closes into HRP.
- **portfolio/book_neutrality.py:** a non-positive `gross_exposure_cap` silently scaled the whole book to zero; now skipped with a `gross_cap_skipped_nonpositive_cap` diagnostic step.
- **risk/position_sizing.py:** `min_position_weight > max_position_weight` pushed sized weight above the leverage cap; the floor is now re-clamped by the cap.
- A `train_rl_sizing` runtime note (training skips NaN rows but runtime argmax has no NaN guard) was left as-is, bounded and documented rather than churned.

**Verification:** 24 new tests across the seven modules pin every behavior above; full suite 2858 green.


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

**Severity:** 7/10 (silent permanent data loss of every batch containing one non-finite payload; dashboards intermittently broken under normal concurrent operation) --- **Status:** 🟢 `fixed`

**Problem 1 (pipeline wedge):** `json.dumps` serializes bare `NaN`/`Infinity`, so a poisoned event passed XADD and `json.loads` untouched, then failed at PostgreSQL's JSONB column (`Token 'NaN' is invalid`), failing the whole `executemany`, rolling back every good row in the batch and leaving all of them pending forever (`xreadgroup(..., ">")` only delivers never-delivered messages and nothing reclaimed the PEL) — one bad float silently lost that batch and every later one containing it; numpy scalars additionally raised `TypeError` at the producer and were dropped with only a warning.

**Fix 1:** Added top-level `json_safety.py` (`sanitize_json_finite()`/`dumps_json_safe()`/`atomic_write_json()`/`atomic_write_text()`/`load_json_lenient()`, registered per the #115 rule): both producers serialize through `dumps_json_safe` (non-finite→None, numpy→python), and both Postgres workers gained a poison-row fallback using a first-row probe to distinguish POISON ROW (persist the clean prefix per row, dead-letter + ack the rest) from POSTGRES DOWN (re-raise, everything stays pending as before); the audit twin stops at its first poison row and dead-letters all later rows so the hash chain can't fork.

**Problem 2 (torn reads/writes):** Every status-file writer (`main.py::_write_state`'s seven files, both workers' `status_export.py`, `paper_readiness_report.py`) truncated-then-wrote and `monitoring/api_server.py` read without guarding `JSONDecodeError`/TOCTOU, so a reader racing a writer got HTTP 500s and a writer dying mid-write left a corrupt file.

**Fix 2:** All writers go through `atomic_write_json` (same-dir temp + `os.replace`), readers degrade to the documented 404 shape via `load_json_lenient`, and several inline reads (neural-network state, `/api/state`, evaluation-state walk-forward sort, assets-status) were hardened; state payloads are finite-sanitized so the webui can never receive a bare `NaN` again.

**Verification:** New `test_json_safety.py` (10) plus worker tests (poison-batch wedge, outage-stays-pending, chained-deadletter) and producer sanitize tests; full suite 2929 green.


### 121. V5.4.7 - gating blend deflated magnitude/volatility by missing-head weight mass; NaN confidence scored as PERFECT

**Severity:** 6/10 (positions oversized whenever any expert's optional multitask head was absent - an underestimated volatility feeds vol-targeting directly; NaN confidence sailed straight through Priority 7's trade gate) --- **Status:** 🟢 `fixed`

**Problem 1:** `moe/gating.py::_weighted_blend()` never renormalized — any expert whose optional multitask head was missing contributed an implicit w·0 while weights sum to 1, deflating blended magnitude/volatility toward zero by the missing mass (~25% with one of four heads gone), which underestimates volatility in position sizing and oversizes positions.

**Fix 1:** The blend divides by the contributing weights' sum (None when no contributors or zero mass); direction probability was already correct.

**Problem 2:** `analyzer/market_analyzer.py::_clamp01()` used `max(0.0, min(1.0, value))`, and `min(1.0, nan)` returns 1.0, so a NaN confidence/regime component became a perfect score clearing `min_confidence_to_trade` (gating's own clamp mapped NaN to 0.0 — the two disagreed).

**Fix 2:** Non-finite → 0.0 to match gating; also fixed `_performance_score()`'s `or default` coercing legitimate 0.0 metrics to neutral defaults, and gave the inference interpreter a layernorm eps floor (input sanitization stays deliberately out — downstream guards own that contract).

**Verification:** Blend renormalization, clamp, and eps-floor tests in `test_v547_bug_hunt.py`/`test_gating_network.py`; suite green.


### 122. V5.4.7 - retraining gates compared against FAKE zeros: missing files deadlocked promotion, NaN sailed through every gate

**Severity:** 6/10 (a fresh deploy or deleted report file deadlocked ALL candidate promotion forever while looking like strict quality gates; a NaN metric failed NOTHING - `nan < x` and `nan > x` are both False) --- **Status:** 🟢 `fixed`

**Problem 1:** `retraining/validation_gate.py` defaulted every metric to `0.0` via `.get(key, 0.0) or 0.0`, so with the ACTIVE side's file missing a real candidate's negative drawdown failed "worse than active" and any positive loss failed stability — deadlocking all promotion forever while looking like strict gates; with the CANDIDATE side missing, fake-perfect zeros passed vacuously.

**Problem 2:** train.py-written JSON can carry bare NaN and every gate check is a one-sided comparison, so a NaN sharpe/drawdown/loss/gap failed NOTHING (same pattern in `backtest_gate.py`'s excess-return comparison).

**Fix:** Required candidate metrics extract as finite-or-None, with None failing closed via an explicit `*_missing_or_non_finite` reason; a missing ACTIVE baseline fails with `active_baseline_metrics_missing`; floor-style checks coerce non-finite to 0.0 and `backtest_gate` treats non-finite returns as the no-edge default; verdicts stay byte-identical when everything is present and finite.

**Verification:** Fail-closed tests for both directions in `test_v547_bug_hunt.py`; existing gate tests pass unmodified.


### 123. V5.4.7 - data-pipeline corruption class: Yahoo NaN frames written as real bars; FRED cache destroyed by narrow refetch; config.json truncation window

**Severity:** 5/10 (all require operator-triggered backfills/fetches to hit, but each silently poisons training data or the whole system config) --- **Status:** 🟢 `fixed`

**Problem:** A data-pipeline corruption class (each requires an operator-triggered backfill/fetch, but silently poisons training data or the whole config):
- **Yahoo NaN-frame rows:** rate-limit/delisting responses return non-empty all-NaN frames, so `float(record["Open"])` wrote nan as genuine OHLCV (now dropped, degrading to the honest no-data path).
- **yfinance end-exclusivity off-by-one:** `backfill_to` is inclusive but `yf.download(end=...)` is exclusive, so the configured final day could never be fetched and `needs_backfill` stayed True forever (now fetches `fetch_end + 1 day`).
- **FRED cache truncation:** cache writes were full-file replacement clipped to `--start/--end`, so a narrow refetch destroyed prior history (now merges, new rows winning their own dates).
- **config.json atomicity:** `aq fetch --apply` rewrote the whole config truncate-then-write, so a mid-write crash left it truncated (now atomic via `json_safety`, as are FRED cache writes).
- **liquidity guards:** a non-positive `min_daily_dollar_volume` with `close*volume == 0` divided by zero mid-bar, and negative/non-finite dynamic spreads lowered round-trip cost below the ceiling (both now block conservatively).
- **bar_synthesis:** `pad_sequence_history([])` raised IndexError → now an explicit ValueError naming the broken caller contract.

**Verification:** Regression tests for each in `test_v547_bug_hunt.py`; existing data-pipeline suites updated only where they pinned the buggy behavior.


### 124. V5.4.7 - auto-rollback/promote artifact verification gaps; Telegram watermark freeze; worker startup crash-loop

**Severity:** 4/10 (RL overlay default-off and IB unconnected keep most of these latent, but each breaks its subsystem permanently once triggered) --- **Status:** 🟢 `fixed`

**Problem:** A batch of auto-rollback/promote artifact-verification gaps and worker robustness bugs:
- **promote() never verified artifacts:** rollback verified sha256s but promote copied blindly (now runs `verify_version_artifacts()` before any move/status flip, failing closed with `candidate_artifact_verification_failed`).
- **rollback to a hashless/missing version silently "succeeded":** an empty version dir returned ok=True after copying nothing (now fails with `no_artifacts_found`, and `candidate_dir()` validates version-id charset).
- **Telegram watermark freeze:** an explicit JSONB null crashed f-string formatting before `set_watermark`, so the same poison row refetched forever and blocked all alerts (numeric fields now coerce junk to defaults and the loop advances the watermark past unformattable rows).
- **Worker startup crash-loop:** a Redis-down constructor ping hard-crashed both Postgres workers into restart loops (now warns and lets `run()`'s backoff reconnect).
- **version-id events:** a garbage `--version-id` left the event running until the 3h startup reconcile (documented; reconcile covers it).

**Verification:** Promote preflight/verification/no-artifacts/charset tests; telegram null-format test; startup-outage test.


### 125. V5.4.7 - `aq` help surfaces drifted: stale `--all` text since V5.4.4; README missing five flags; CI covered 2 of ~23 help screens

**Severity:** 3/10 (docs/tooling trust, not capital) --- **Status:** 🟢 `fixed`

**Problem:** `aq evaluate --all`'s help text was stale since V5.4.4 (benchmarks had joined the bundle), the README's `aq train`/`aq evaluate` synopses were missing six shipped flags, CI's cli-smoke job exercised only two help screens, and ci.yml's `ruff` install was unpinned (new ruff releases could change CI independently of repo changes).

**Fix:** Updated the `--all` help and code comment and documented all missing flags with per-flag bullets; added `tests/test_cli_help_surface.py` (parametrized exit-0 `--help` across every parser leaf plus a two-directional README↔`build_parser()` flag-sync guard) and pinned `ruff==0.16.4`; reinstalled the editable `aq` per the #115 packaging rule.

**Verification:** 36 new meta-tests green; full suite 2929 green; ruff clean.


### 126. V5.4.10 \- 34% of backtest data requests failed on missing crypto QUOTE zips; only the traded LTCUSD needed a fix (observation-only assets are quote-less by design)

**Severity:** 2/10 (cosmetic — no results affected; Lean fell back to trade data and this algorithm never reads crypto quote bars) · **Status:** 🟢 `fixed` (data + tooling; see #104-style caveat below — no code in the Lean hot path changed)

**Problem:** The V5.4.8+ backtest reported 107 succeeded / 55 failed (34%) of 162 data requests, every failure a missing `crypto/coinbase/daily/<ticker>_quote.zip`: Lean's default `AddCrypto` requests both a trade and a quote feed, but the pipeline only ever generated `*_trade.zip`, so quote requests failed for every crypto asset except BTC (which had a manual bid/ask quote zip).

**Diagnosis (largely a non-issue):** only the 2 traded crypto assets matter (BTCUSD, LTCUSD = `model_training_and_trading`); the other 10 are `observation_only` and correctly quote-less by design, and `main.py` only ever reads `Slice.quote_bars` for forex, never crypto, so the 44 observation-only requests and even the LTCUSD quote request were functionally benign — Lean fell back to trade data and fills use `main.py`'s own slippage model. The sole genuine gap was traded LTCUSD's missing quote subscription.

**Fix:** Added a crypto sibling of the forex synthesis path in `data_pipeline/yfinance_backfill.py` — `synthesize_crypto_bid_ask_row()` (documented zero-spread approximation matching Lean's 11-column crypto quote CSV, no fake spread invented), `crypto_rows_to_lean_csv()`/`_read_existing_lean_crypto_quote_rows()`, `write_lean_crypto_quote_zip()` (preserving existing real bid/ask rows, raising on a missing trade zip), and CLI `aq backfill yfinance --quotes [--tickers ...] [--apply]`. Only traded LTCUSD was generated (1917 rows); the 10 observation-only assets were left quote-less.

**Verification:** 6 new tests in `test_yfinance_backfill.py`; full suite 2935 green; ruff clean; `ltcusd_quote.zip` validated round-trip. A future backtest should see quote failures drop to ~44 (observation-only remain by design). **Later (V5.6.0):** the 10 observation-only quote zips were also generated, so the monitor no longer reports them.

---

### 127. 2026-08-27 backtest written up: Sharpe −2.51 against an offline +1 — what the run actually traded (V5.5.0)

**Severity:** 9/10 · **Status:** 🟢 `fixed` — decomposed and fixed (#128–#134); verified by the 2026-10-07 19:28 backtest (Lean Sharpe −1.05, +0.17 without a risk-free rate, +0.68% net, vs −2.51 / −1.16 / −4.25% on 08-27). 

**Problem:** `backtests/2026-08-27_12-01-48` (the first live run of the V5.3.7 models + V5.4.x fixes) was never recorded — Sharpe −2.514, −4.25% net, DD 5.3%, 571 orders, $769.88 fees, and a prediction-provenance counter of `sequence_served=78833 multitask_fallback=0` closing V5.4.1's "pending Lean runtime". The new `aq evaluate --audit-backtest` showed it was not trading the offline book: equity long averaged 2.45% of NAV, forex short 13.4% (long up to 45.7%), crypto 0%; equity entries were 36 book vs 135 non-book; forex lost −$3,031 of −$3,422 realized; equity fees averaged 16 bps/fill; 115 same-symbol order pairs overlapped (34 limit) and 21 limit orders stayed open >5 days; 159 of 367 trades closed after 11–15 days; the book engaged on 47 of 172 rebalances (21 spread vetoes, 104 rolling-IC vetoes).

**Fix:** None in this entry — the audit tool (`evaluation/backtest_audit.py`) plus #128/#129/#130/#131; note Lean's −2.514 subtracts a risk-free rate, while the same equity curve scores −1.16 without one (the convention every offline number uses).

**Verification:** `aq evaluate --audit-backtest` reproduces the figures from the run folder alone; 21 unit tests on synthetic Lean runs.

### 128. Offline/live execution parity: ten divergences between `aq evaluate` and `main.py`, fixed (V5.5.0)

**Severity:** 9/10 · **Status:** 🟢 `fixed` — all fixes unit-tested and verified by the 2026-10-07 19:28 backtest: 0 overlapping orders, forex short peak 13.95% (cap 15%), equity fees 5.7 bps/fill (was 16), exit tracking firing (mean hold 24 days, 0 trades under 2 days), book members 49 of 104 equity entries
**Problem:** the live run traded (1) the **old probability signal outside the book** with no budget (135 of 171 equity entries) and a rotation exit that liquidated it after the 10-bar cooldown; (2) book weights shrunk ~8× by the multiplier chain, `rank_sizing_multiplier` tilting shorts to 0.78×; (3) **forex sized by margin (several × NAV), not the book weight**, re-sized on both the equity and forex tick, shorts sharing one 30% budget with equities; (4) **duplicate limit orders** — every bar re-submitted and overwrote the pending record, so the old ticket never timed out (AMZN: three fills, 689 shares); (5) a gate veto **wiping hysteresis memory**; (6) **exit tracking never seeing fills** (fills land a bar late), so `max_holding_bars` never fired and short trailing stops were inverted; (7) a fill-slippage estimate that charged the whole spread per fill; (8) forex/crypto decided on the previous day's bar; (9) an offline simulator that used another rank head, a 0.05 sector cap, raw-unit hysteresis, no gates, flattened on a veto and used equal weights; (10) a rolling-IC floor of 0.02.
**Fix:** `portfolio/legacy_sleeve.py` (10% gross / 2% per name budget, no entries while vetoed; held sleeve positions capped; rotation exit limited to book-owned positions via `update_book_owned_symbols`/`is_rotation_exit_candidate`; exits exempt from the cooldown via `is_cooldown_exempt`); `rank_sizing_applies_to_members: false` + `sizing_floor_fraction: 0.5` (`apply_book_weight_floor`, never undoing a liquidity cut); `cap_forex_target_to_book_weight`, `projected_signed_quantity` (held + open orders), rebalance-gated forex resizes with a 10% deadband and a dedicated `max_forex_short_exposure` 0.15; `resolve_pending_order_action` (keep/cancel-replace, one order per symbol); `remember_formed_book`; exit tracking **adopts** a held, untracked position (direction/price from the real holding); `fill_slippage.source: per_side`; offline `--as-live` (`evaluation/live_parity.py`); IC floor 0.05 (owner decision). Also fixed on the way: every book decision logged `topology_state=unknown` (the payload key is `topology_risk`); the slippage-divergence reference is now the fill bar's open (`compute_fill_slippage_divergence_bps`), still disabled until calibrated; #117's RL argmax guard (`rl_sizing_non_finite_score`).
**Verification:** 25 `main.py` wiring tests against a minimal `AlgorithmImports` stub (`tests/test_main_wiring.py`), 54 round-file tests, 18 simulator/parity tests, 21 audit tests; the real 2019–21 backtest split re-scored **as-live** under the final config (IC floor 0.05): net Sharpe 1.68 (+34.6%, DD 5.5%, 132/178 rebalance attempts vetoed; 1.39 with the Almgren impact model) against the idealized 1.00 — the offline book was never the problem, the execution was. `--factor-exposure` adds a caution: of the idealized book's 0.94 Sharpe only 0.16 is alpha after SPY/momentum (R² 0.54, 57% of variance is SPY). **Still open:** the previous-day forex/crypto bar (modelled offline with a one-day lag, unchanged live) and the sizing-multiplier chain beyond the 0.5 floor.

### 129. Crypto never traded: one global 0.45 volatility cutoff made BTC/LTC permanently "elevated"; teardown and timing probes added (V5.5.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` — crypto trades (16 trades) and the probes were read once (cleanup changed nothing for the teardown hang, which stays open as #104)
**Problem:** `ELEVATED_VOLATILITY_THRESHOLD = 0.45` (annualized) sits below crypto's own distribution — **77% of crypto samples in the backtest window exceed it** (85% over all history; p80 0.87 / 1.11) — so the analyzer's Priority 3 cancelled 13 of the 26 BTC/LTC book selections (the 08-27 run); zero-volume blocked only one. Separately #104 (teardown hang) and #63 (no real per-call timing) were still unresolved, and the hang happens with `alive_threads=[]`, i.e. outside Python.
**Fix:** `phase_v2.topology.elevated_volatility_threshold` accepts `{"default": 0.45, "crypto": 0.87}` (`resolve_elevated_volatility_thresholds`; `aq evaluate --calibrate-volatility-threshold` derives the per-class percentile). New `performance_probe.py` (stdlib-only): opt-in `TimingProbe` (one `timing-probe:` line at shutdown), `collect_teardown_diagnostics` (OS thread names, GC counts), `release_symbol_containers` (opt-in pre-shutdown cleanup experiment: clear per-symbol containers, `gc.unfreeze()`, collect), and a `crypto-bar-probe` for the first bars per crypto symbol. All default off in code, switched on in `config.json` for the final run only.
**Verification:** 6 calibration + 6 probe + resolver/topology tests. #104's verdict must come from the **engine** `log.txt` (`PythonInitializer.Shutdown(): ended`), never the algorithm log.

### 130. 62 equity factor files were applied on top of already-adjusted data: prices ×0.05 (AMZN), dividends counted twice (V5.5.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` — files removed locally (originals in `data/equity/usa/factor_files_backup_pre_v550/`); verified by the 2026-10-07 engine log (`numerical precision` lists only `AAA`, no 2050 start); the V5.8.0 data rewrite and full Codespace retrain (#156, #162) rebuilt the dataset, scaler and models from single-adjusted zips
**Problem:** #100 generated 63 Lean factor files from yfinance splits/dividends, but those tickers' zips had been written by `yfinance_backfill.py` with `auto_adjust=True`, i.e. split- **and** dividend-adjusted. `train.py` and Lean then applied the factors again: AMZN $84.63 (2019) became $4.23, NVDA ≈ $0.02–0.3, so per-share commissions on 20–480× the shares cost 16–49 bps/side; every ex-dividend date gained an extra +yield return (flattering dividend-payers' longs, penalizing their shorts). Evidence: for the generated files `zip close ≈ reference_price × cumulative factor of later events` (XOM 0.64, MSFT 0.88, T 0.55) while the 22 genuine QuantConnect files have `zip == reference_price`; the backfill writer's float-formatted volume (`98898000.0`) fingerprints its zips.
**Fix:** `data_pipeline/factor_file_backfill.py --audit` / `--repair-adjusted-zips [--apply]` (read-only audit; repair **removes** the file after a one-time backup outside `factor_files/`) and generation now skips backfill-written zips. Applied: 62 files removed, 0 remaining, the 23 genuine files untouched. **Do not neutralize with a sentinel-only file:** the first repair did exactly that (`20501231,1,1,0`) and V5.5.0's first backtest attempt logged `data for the following symbols was adjust to a later starting date: [EMB, 12/30/2050], [AGG, 12/30/2050] ...` - Lean read the zero reference price as a numerical-precision problem and gave ~62 tickers no data until 2050. A missing file is what every run before #100 used.
**Verification:** 11 new tests (fingerprint, audit verdicts incl. the 2050 trap, backup-once-then-remove, a removed file is an identity through `train.apply_split_adjustments`, CLI dry-run/apply). Verified in the engine log of the next run: the `numerical precision` line must list at most `AAA` (a genuine file, listed in 08-19 and 08-27 too). **Follow-up:** `full_dataset.csv`, scaler stats and the models were built from the double-adjusted series (returns differ by the ex-date bumps only); regenerate and retrain on the Codespace — do **not** run `aq train --dataset-only` locally, it would refit the scaler against the shipped model weights.

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

### 133. 2026-10-07 backtest (V5.5.0 first full run): Sharpe −4.55, 230 of 355 trades closed within 2 days, crypto and most forex still blocked

**Severity:** 9/10 · **Status:** 🟢 `fixed` — verified by the 2026-10-07 17:50 re-run (#134): 0 market+limit overlaps (was 26) and crypto trades (17 entries, 0 before) with the spread cap; the cooldown/veto-hold fixes were masked by #134 and are re-checked there

**Problem:** `backtests/2026-10-07_15-39-04` (run 1553664308, 2840 s, 809 orders, −2.09% net, DD 2.1%, $860.75 fees) scored Lean Sharpe −4.551; the no-risk-free equity-curve Sharpe is −1.346 against −1.16 on 08-27, so the V5.5.0 fixes did not move the result. Verified good: no 2050 data starts (only `AAA` in `numerical precision`), 0 limit-vs-limit overlaps, forex short peak 10.5% (cap 15%), equity gross peaks 13%/17% long/short, equity fees 6.2 bps/fill (was 16), 98 of 267 equity entries from the book (37%, was 36 of 171; the sleeve still opens 169, so the 'book is the majority' target is not met), 355 closed trades never cluster on one day (max 7). Four defects: **(1) cooldown exemption too wide** — #128 exempted every `sell`, so the noisy legacy probability signal flipped positions out within a day: 230 of 355 trades closed in ≤2 days (mean hold 5.8 days vs 39 on 08-27), $570 of fees for −$786 P&L; **(2) book positions handed to the legacy signal during a veto** — the book was vetoed on 173 of 218 rebalances (133 rolling-IC at the new 0.05 floor, 40 spread), and the owned positions then fell to legacy sells instead of being held as offline does; **(3) stacked orders** — 26 times a market order and a limit order were created in the same bar (the timeout sweep's market fallback, then a fresh entry), in several both filled (TLT −26/−27, −44/−45 shares); **(4) liquidity gate read volatility as spread** — Corwin-Schultz high-low "spreads" of 1.3% (BTC, LTC) and 0.35% (AUD) tripped `max_round_trip_cost_fraction` 0.25%, so all 24 crypto and 126 of 179 forex book selections were simulated, not traded (crypto: 0 trades, #129 still open). Also: 92 equity decisions were `reduce_risk` from `topology_elevated_volatility_pressure` (default 0.45 threshold in the 2020 sell-off) and 207 `simulate` from the volume floor — leads, not changed.
**Fix:** `is_cooldown_exempt(..., is_forced_exit)` exempts only the rotation exit and the max-holding/trailing-stop backstops; `should_hold_owned_position_on_veto` (config `portfolio_book.hold_owned_positions_on_veto`, now true) holds book-owned positions through a veto; `should_skip_for_open_order` blocks a second entry on an untracked in-flight order (`order_already_open`, not audited as a placement); `cap_spread_proxy` clamps the gate/cost spread per class (`liquidity.max_spread_proxy_by_type` crypto 0.001, forex 0.0003; the model feature is untouched). The audit's exposure `max` was 0.0 for negative short series — it now reports `peak`.
**Verification:** 14 new tests (`test_v550_backtest_findings.py`) plus two re-pinned wiring tests (a plain sell is rate-limited, a forced exit is not); full suite green. The next backtest must show: ≤2-day trades well below 230, book positions lasting ≥10 days, no market+limit pairs, crypto trading at least once, forex book selections traded. **Teardown (#104) is unchanged:** engine log still `Operation timed out` / `Failed to shutdown python` even with the cleanup probe (10 containers cleared, 132 objects collected, 1.5 s) — the native thread list shows only .NET/jemalloc threads, so the next lead is outside Python. **Timing probe (#63):** of 2840 s, `topology_payload` 673 s (332 ms x 2027 calls), `inference_cluster` 337 s (166 ms), `build_model_input` 220 s (1.9 ms x 114975), `ensure_ready` 5.0 s; the probes are switched off again.

### 134. Re-entries were force-sold the next day: the closing fill never cleared the exit-tracking state (V5.5.0 regression)

**Severity:** 9/10 · **Status:** 🟢 `fixed` — verified by the 19:28 re-run: Lean Sharpe −1.05 (−1.46 before), +0.17 without a risk-free rate, +0.68% net, 403 orders, $475 fees, 195 closed trades with none under 2 days (mean hold 24 days)
**Problem:** the re-run (`backtests/2026-10-07_17-50-11`, Lean Sharpe −1.46, no-risk-free −0.135, −0.53% net, 589 orders, $611 fees, DD 3.3%; was −4.55 / −1.35 / −2.09% / 809 / $861) still closed 154 of 355 trades within 2 days (−$847 P&L, $402 fees). All 44 first trades per symbol lasted ≥2 days; 154 of 196 re-entries did not. Cause: V5.5.0's exit tracking adopts a position on the bar after it fills, but a close also fills a bar late, so the invested→flat transition was never seen and the old entry bar/peak stayed; the next holding inherited them and `max_holding_age_exceeded` / the trailing stop force-sold it (forced exits bypass the cooldown) the day after it filled.
**Fix:** `compute_position_exit_tracking_update(..., clear_stale_state=True)` clears the state of a flat symbol that still carries it; `main.py` passes it. Verified in the run: crypto traded for the first time (17 entries, +$385), forex short peak 13.8% (cap 15%), 0 overlapping orders, equity fees 5.7 bps/fill; book vetoed on 170 of 216 rebalances (133 rolling-IC, 37 spread).
**Verification:** pure + lifecycle tests (`test_v550_backtest_findings.py`), two stub tests driving `_update_position_exit_tracking` through close → re-entry (`test_main_wiring.py`). **Round 3 (`backtests/2026-10-07_19-28-54`) confirmed it**: equity +$1,603 realized, forex −$171, crypto −$403 (4 LTCUSD longs lost $421–$991, fees $0). **Open leads, not changed:** crypto fills carry `$0` fees (Lean's default Coinbase fee model returns 0 here, so the +$385 is flattered; an explicit percentage fee model needs verifying against Lean first); the book is vetoed ~79% of rebalances (IC floor 0.05 is the owner's call); 92 equity selections were `reduce_risk` from `topology_elevated_volatility_pressure`; the teardown hang (#104) persists (engine log: `Operation timed out`, `Failed to shutdown python`).

### 135. Feature reconciliation of the 2026-10-07 run: live features diverge from `full_dataset.csv` everywhere the dataset was built on the double-adjusted data (V5.5.0 research)

**Severity:** 7/10 · **Status:** 🟢 `fixed` — see #137, #140, #141
**Problem:** `aq evaluate --reconcile-features --symbol XOM|NVDA` (216 snapshots each) diverges on 16-20 of ~52 features on nearly every date. The price/volume-level ones track #130: XOM `liquidity_log_dollar_volume` is off by a constant 0.28 on all 216 dates (dividend-adjusted XOM prices in the stale dataset), NVDA by only 0.006 (no split/dividend effect in the window); `close_to_close_return_20d`/`momentum_20d` differ on 31% of XOM dates. Cross-asset features (`macro_*`, `peer_*_return_1d`, `topology_correlation_strength`, `cs_momentum_rank_20`) diverge on ~100% of dates with identical deltas across both symbols, i.e. a timing/alignment difference between the daily dataset and live's per-asset-class slices, not a per-symbol bug.
**Fix:** none yet — the models were trained on a dataset built with the 62 double-adjusted factor files (now removed), so the next step is dataset regeneration + retrain on the Codespace (never locally), then re-run this reconciliation: price-level divergences should vanish, and what remains is the cross-asset alignment to investigate.
**Verification:** reports in `ml/evaluation/feature_reconciliation.json`; the book-history reconciliation (`--reconcile-book-history ... --reconcile-all-runs`) was not completed — it needs ~1.3 GB RAM and was stopped twice by the low-memory guard on this PC.

**Update (V5.6.0) - closed:** root causes were the tick order (#137), Lean's forex fill-forward calendar (#140) and two FRED drivers missing locally (#141); the dataset was regenerated and the models retrained. The reconciliation of BT1's snapshots against it leaves only the four `sens_*` features (BT1 predates the FRED fix); the next backtest must show none.

### 136. CI on `main` red since the V5.5.0 push: 29 `NameError: Slice` errors, README links into gitignored READMEs, 43 gitleaks findings (V5.6.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed and verified` — CI on `main` is green since the V5.7.1 push (run 38158358489, after #155 fixed the last 3.11-only failure)
**Problem:** run 37667920328 failed `python-tests` (both OSes), `subsystem-matrix (live)`, `fast-guards` and `secret-scan`, and every Dependabot PR inherited it. (1) `main.py` annotates `on_data(self, slice: Slice)`; Python < 3.14 evaluates annotations at import, so the wiring/smoke stubs (no `Slice`) raised `NameError` on CI's 3.11 — the dev PC runs 3.14, which evaluates them lazily, hence green locally. (2) `README.md` linked `backtests/`, `data/`, `storage/` and the vault README, all gitignored. (3) gitleaks' `generic-api-key` rule read the exported-model JSON fields `"weight_key": "head_rank_5d.weight"` / `"bias_key"` (and the tests mocking them) as credentials.
**Fix:** both stubs export `Slice`; `test_lean_runtime_imports.py` gains an AST guard that fails on any interpreter if `main.py` evaluates a new Lean name at import. `.gitignore` un-ignores the three folder READMEs, the vault link became plain text, and `test_docs_links.py` now also fails when a link target is gitignored. `.gitleaks.toml` allowlists exactly the `*_key` tensor-name lines (a planted key still fails) and CI passes `--config .gitleaks.toml`.
**Verification:** guard tests mutation-checked (removing the stub export / restoring the old `.gitignore` fails them); gitleaks 8.18.4 on a `git archive HEAD` export: 43 findings before, 0 after, 2 on a planted secret; suite green.

### 137. Feature divergence #135 solved: live built cross-asset features one tick behind the dataset (V5.6.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed and verified` against the live snapshots of the 2026-10-07 run and of BT1; the dataset and models were regenerated on the Codespace (#140, #141 are its two data-side companions)
**Problem:** `main.py` builds the topology, peer-return, macro-proxy and `cs_momentum_rank_20` payloads at the START of a tick (`:1827-1829`), before the tick's bars join `symbol_windows` (`:1943`), so live(D) equalled the dataset's D-1 on every cross-asset column (NVDA: `peer_rank1_return_1d` equal to the previous row on 203 of 216 dates, to the same row on 0). `train.py` used same-day values — plus a lookahead for crypto, whose day bar closes at midnight UTC, after the US equity close — on dropna'd return frames with holes live never has, and ignored the per-class elevated-volatility cutoffs live applies (#129).
**Fix:** `features/cross_asset_timing.py`: `cross_asset_inputs()` is the one window→(returns, momentum) construction `main.py` calls, and `CrossAssetTimeline` replays the live rule offline from RAW per-ticker history (a bar is visible once its period closed: equity at that day's close, crypto/forex at the next midnight; a row sees bars strictly before its own tick, so Sunday's crypto bar is visible on Monday). The three `train.py` builders use it; `evaluation/feature_parity.py` replicas follow the same tick order.
**Verification:** `tests/test_cross_asset_timing.py` replays `main.py`'s tick order over equity + 7-day crypto + forex calendars and matches the builders to 1e-12 (and fails for the old rule). Against the 216 live NVDA snapshots of the 10-07 run (before #140): `macro_*` 100% exact, `peer_rank*` 100%, `cs_momentum_rank_20` 94.4%, `topology_correlation_strength` 96.3%; the rest are AAA's late start in Lean (`numerical precision … [AAA, 9/30/2020]`) and two short windows left unexplained. Against BT1 (final dataset): topology strength, peers, macro, rank and every price-level feature are exact for NVDA and XOM; only the four `sens_*` features differ (#141, BT1 ran before the fix).

### 138. Crypto fills paid $0 fees: Lean's default crypto fee model charges nothing (V5.6.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` — BT2 realised 46.7 bps per crypto fill (Coinbase maker 60 / taker 80, #142), unchanged through BT7
**Problem:** `main.py` skips `InteractiveBrokersFeeModel` for crypto (it throws) and the comment claimed `add_crypto(..., Market.COINBASE)` brings a Coinbase fee model; it does not — all 30 crypto fills of `backtests/2026-10-07_19-28-54` carry `orderFeeAmount 0.0`, so the +$385 / −$403 crypto P&L never paid an exchange fee, the net-edge gate assumed IB's 1.5 bps, and the offline book charged 6 bps.
**Fix:** `phase_v2.costs.fee_by_type.crypto = {"model": "coinbase", "fee_bps": 80.0, "min_usd": 0.0}`: `main.py` assigns Lean's own `CoinbaseFeeModel()` (present in the pinned `lean:17900` image) to crypto securities, `build_net_edge_decision(..., security_type=)` charges the class its fee instead of the equity commission, and `commission_bps_by_ticker()` gives the offline simulator the same rate (`simulate_rank_book(commission_bps_by_ticker=)`, scaled by the stress multipliers). Absent key = old behaviour. At 80 bps a side only rank-extreme crypto selections clear the gate (0.90 rank: 158 bps edge vs 170 bps cost).
**Verification:** cost-model, simulator, stress-scaling and wiring tests; the 80 bps is Lean's post-2019-10 taker rate from its source (earlier dates charge 25 bps) — confirm in BT1/BT2 order events. **Audit of the 16 crypto trades:** all LTCUSD longs sized at the 0.5 book-weight floor (4–5% NAV on a ~5% daily-vol asset); the four big losses (−$421…−$991) were 22–24% gap-downs within 2–9 days that no stop prevents. Sizing left unchanged: the offline simulator models no sizing multipliers, so a floor change cannot be validated, and the exchange fee is now the effective control.

### 139. Training-pipeline and tooling defects fixed before the V5.6.0 retrain

**Severity:** 6/10 · **Status:** 🟢 `fixed` — unit-tested; the retrain itself is recorded in the entries that follow

**Problem:** Six defects blocked the V5.6.0 retrain: `validation_gate` judged the never-promotable `residual_rank_20d` head (rejecting every candidate); `train_rl_sizing.py` compared its penalised policy against an unpenalised constant with no way to pick the penalty; a VM reboot at walk-forward window 5 lost the run three times; `--reconcile-book-history` loaded all 251 dataset columns and re-ran the model per head (~1.3 GB, killed on this PC); `overlap_vs_sharpe_analysis.py` collapsed runs sharing a sim window; and topology cost 332 ms/call, 87% of it pure-Python Pearson loops.

**Fix:** The ranking gate now reads `ranking.heads` (`rank_5d`/`rank_20d`, passes if any clears); `policy_beats_constant_unpenalized` + `--penalty-sweep` on a chronological holdout; per-window `window_result.json` + `train.py --resume-run-id`; `predict_heads()` + `row_mask` + chunked column-pruned reads (~0.5 GB); per-run points; numpy correlation matrix with a scalar fallback (1.16 s → 0.16 s for 104 symbols, exact to 1e-12).

**Verification:** Tests per item (`test_validation_gate`, `test_train_rl_sizing`, `test_walk_forward_multimodel`, `test_model_predictions`, `test_overlap_vs_sharpe_analysis`, `test_market_topology`).

### 140. Lean fills forward forex bars: live windows hold flat Sunday bars (and filled gap days) the dataset never had (V5.6.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed and verified` (cross-asset side against the 10-07 live values, own-feature side by unit test; a BT2 forex snapshot is not available at a forex tick)
**Problem:** with #137 fixed, `topology_correlation_strength` still matched live on only 32% of NVDA dates — exactly the dates whose cluster contained forex pairs (119 of 119; crypto-only clusters matched). The BT1 bar probe (`crypto_bar_probe.asset_classes: [crypto, forex]`) compared each live bar with the local zip: crypto 45/45 identical, forex bars arrive at 19:00 NY like crypto, but 5–7 of 45 are a SUNDAY bar equal to the preceding Friday close where the zip has no Sunday row — Lean's FillForward emits a flat bar for every open day without data (forex trades Sunday–Friday). The 2019-05-22 weekday missing from the zips for 7 pairs is filled the same way. Live forex windows therefore carry zero-return days, lowering forex volatility and correlation with equities.
**Fix:** `fill_forward_open_forex_days()` (shared) puts those flat bars into the forex history of `CrossAssetTimeline`; `train.engineer_forex_features_on_lean_calendar()` engineers forex rows' trailing features on the filled calendar while labels and the row set stay those of the real bars, so no fake zero-return day enters a target (test: Friday's `target_return_1d` is still the Friday→Monday move). The parity audit replicates forex on the same calendar.
**Verification:** replay test with an independent Lean-style fill; NVDA topology strength 32% → 96.3% exact, `cs_momentum_rank_20` 87.5% → 94.4%, peers 100%. **Open:** AAA is invisible to Lean before 2020-09-30 (factor-file precision) but trained on locally — one observation-only asset, left as is.

### 141. Two FRED sensitivity drivers existed only on the Codespace: 4 model features were 0 live and real in training (V5.6.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed` — files pulled local; the next backtest must show the four features non-zero
**Problem:** `sens_real_rate_beta/interaction` and `sens_dollar_beta/interaction` are regressions on the FRED series `treasury_10yr_real` and `dollar_index`, which `data/reference/fred_series/` on this PC never had (nor `breakeven_inflation_10y`); only the Codespace copy did. Every dataset built there trained on real values; every Lean run (and `aq evaluate`) read empty series and fed 0.0. BT1's snapshots showed it directly (live 0.0 vs offline 0.1456 on all 45 dates for both symbols) once everything else matched.
**Fix:** the three CSVs copied to the local `data/` (now identical to the Codespace's file list: 1302 files each way). A silent per-driver zero is a skew by construction, so the drift check is the reconcile tool: after the next backtest `aq evaluate --reconcile-features` must list no `sens_*` feature.
**Verification:** file lists diffed both ways; the `sens_*` rows of BT1's reconciliation are the before-picture.

### 142. Backtests of the V5.6.0 models: BT1 (diagnostic, 2020-H1) and BT2 (full 2019-21) - what they showed (V5.6.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` — the final run (BT3, forex trading off) confirms the improvement; the offline-vs-Lean gap and the teardown timeout stay open as documented
**Problem/Result:** BT2 (`backtests/2026-10-08_15-01-33`, run 1936881313, new multitask/sequence/gating, spread 0.1985, IC floor 0.05, real crypto fees, forex gate with IB's $2 minimum): Lean Sharpe **−0.949** (−1.046 on 10-07 round 3), **+0.543** without a risk-free rate (was +0.171), net **+1.829%** (was +0.682%), drawdown 1.4%, 503 orders, fees $918.79. The book engaged on 41 of 229 rebalances (10 of 297 before); vetoes were 163 rolling-IC and 25 spread. By class (realized P&L / fees): crypto **+$1,195 / $206** (46.7 bps per fill = Coinbase's maker 60 / taker 80, so #138 is verified), equity **+$1,440 / $203** (7.1 bps), forex **+$3 / $510**. Engine log: `numerical precision` lists only `AAA`, no 2050 starts, the chronic teardown timeout (#104). The offline as-live book on the same models is −0.38 (idealized 0.76): the old +1.68 was inflated by the tick-misaligned features, so the Lean run is the better-calibrated number now.
**Verification of the data fixes (BT2 snapshots vs the final dataset, 229 dates, XOM and NVDA):** 90% of dates agree on all 52 features, no `sens_*` and no price-level divergence is left (#141, #130), `cs_momentum_rank_20` differs on 5–6% of dates and `topology_correlation_strength` on 4–5% (AAA's Lean start of 2020-09-30 and a few short windows).
**Decision from the two V5.5.0+ runs:** forex lost money after fees in both (−$425 net on 10-07, −$507 now) with ~$0 gross across 75–173 entries: positions are ~2.6% of NAV, so IB's $2 minimum is ~8 bps per fill whatever the signal. `phase_v2.forex_risk.enabled` → `false` (zeroes forex sizing and liquidates forex positions; forex bars still feed the topology/peer/macro features, so no model input changes).
**Latency note:** this machine ran BT2 in 8,981 s against 2,840 s for the 10-07 runs and every probed stage was uniformly slower (`ensure_ready` 20 s vs 5 s, inference 494 vs 166 ms/call, topology 542 vs 332 ms/call), so the in-container topology number cannot show the 7× local speed-up (1.16 s → 0.16 s for 104 symbols); judge latency from `scripts/profile_subsystems.py` on an idle machine. The first BT2 attempt crashed in `Initialize()` on Lean's 90-second limit because an evaluation script was running beside it (AGENTS #12).
**BT3 (final configuration, `backtests/2026-10-08_17-48-37`, run 1957851286, 7,846 s):** forex trading off, probes off. Lean Sharpe **−0.763**, **+0.813** without a risk-free rate, net **+2.608%**, drawdown 1.4%, 276 orders, fees $428.37, win rate 52%, no trade open under two days beyond 2. By class (realized / fees): crypto **+$1,396 / $193**, equity **+$1,559 / $235**, forex none. Engine log: `numerical precision` only `AAA`, no 2050 starts, `prediction-provenance sequence_served=78833`; teardown timeout unchanged (#104). Feature snapshots again agree with the dataset (XOM/NVDA: 23 and 30 divergences over 229 dates x 52 features). Progression of the same window and engine: −2.51 (08-27) → −1.05 (10-07 round 3) → −0.95 (BT2) → **−0.76** (BT3); no-risk-free Sharpe 0.17 → 0.54 → **0.81**. The Sharpe is still below zero only because Lean subtracts a risk-free rate at ~1.3% annual volatility (2% → about −1.2); the book earns +2.6% over 2.25 years at 1.4% drawdown.

### 143. What costs the as-live book its Sharpe: lever attribution, a forex-slot defect and four rule-driven changes (V5.6.0 round 3)

**Severity:** 7/10 · **Status:** 🟢 `fixed and verified` — offline as-live −0.38 → **+0.78**, confirmed in Lean by BT4 (#144: Sharpe −0.76 → −0.04, net +2.6% → +4.7%)
**Problem:** `scripts/as_live_levers.py` re-runs the simulator with one live mechanism changed at a time (backtest split, net Sharpe; as-live −0.407, idealized 0.654): the **elevated-topology entry veto** costs 0.70 (without it +0.295), holding positions through a veto 0.44 (+0.036), the 1-bar entry lag 0.23, the two gates together 0.22 (but they protect the validation split: with no gates −0.486 vs as-live 0.105); hysteresis, confidence weighting, the max-holding exit, own-tick forex/crypto (+0.06) and the IC floor (0.02 → −0.277, 0.10 → −0.009 with −11% drawdown) move it by less than 0.2 each. Two defects surfaced beside it: (1) with `forex_risk.enabled=false` the forex pairs still won book slots in the single 6+6 pool and shared the neutrality weights without ever being traded, while the simulator still traded them; (2) the liquidity gate's high-low spread proxy exceeds its own 25 bps round-trip cap on 62% of equity-days (median 33 bps, AAPL 40 bps against a real spread near 1 bp), the #133 defect for equities, so 118 of 492 book-member decisions in BT3 were liquidity-blocked on names like GE, FB, BA and WFC; the simulator has no such gate.
**Fix (rule-driven, config unless noted):** `phase_v2.topology.elevated_veto_applies_to_book_members=false` (rule: ≥ +0.1 Sharpe and drawdown ≤ 1 pp worse: backtest +0.70 and drawdown 15.1% → 14.5%, validation +0.40 with drawdown 2.26% → 3.28%, i.e. 1.02 pp at its edge); `book_candidate_trading_eligible()` (`risk/asset_class_router.py`) keeps disabled asset classes out of the book live and in the as-live metadata (code, parity-tested); `edge_bps_per_rank_unit` 396 → 574 (`--calibrate-edge` on the new models); `kill_switch.max_slippage_divergence_bps` 1e12 → 80 (rule: max(p99 × 1.5, 25 bps); p99 of |fill − bar open| over BT2+BT3 equity and crypto fills is 53 bps, median 5 bps, an upper bound because the dataset's opens differ slightly from Lean's); `max_spread_proxy_by_type.equity=0.001` (the existing per-class cap, gate and cost input only, never the model feature). `aq evaluate --audit-backtest` gained `pnl_by_entry_bucket` and `--book-run-index` (older runs were audited against the latest run's book).
**Rules applied without a change:** legacy sleeve kept (non-book P&L net of fees: equity +$574/+$186/+$374, crypto −$467/+$195/+$162 over the 10-07, BT2 and BT3 runs); beta-neutral test not triggered (alpha Sharpe 0.78 of 1.23 total, market loading 0.09); own-tick forex/crypto declined (+0.06 < 0.1); HRP not evaluable offline (the simulator has no HRP model) and so not flipped; Almgren impact left off (the as-live Sharpe falls 0.78 → 0.53 with the model on, but realized per-fill cost cannot be separated from dataset-vs-Lean price differences without IB or paper fills); hold-on-veto not flipped (backtest +0.44 but validation 0.105 → 0.091, so it does not generalize).
**Verification:** `aq evaluate --rank-book --as-live` (backtest split) after each step: −0.38 → **+0.295** (veto exemption; it equals the lever table's +0.295) → **+0.781** with forex out of the book (net return +11.9%, drawdown −8.4%, 226 rebalances, 181 vetoed; idealized 0.757). Offline only and selected on the window Lean also tests, so treat it as an upper estimate; the liquidity-gate change is not in the simulator at all.
**Book parity measured on BT3** (`--reconcile-book-history --replay-hysteresis --hysteresis-survives-veto`, ~57 min, peak working set ~0.6 GB): on the 41 engaged dates the live book and the offline replay share **77%** of names (0.31 in every earlier run), raw scores differ by 0.0044, 7 of 41 dates match exactly; across 17 runs the overlap correlates with the Lean Sharpe (Spearman 0.62, p=0.007). This is the direct confirmation of the #135 alignment fix. Of 492 book-member decisions, 71 reached `trade`; the rest were net-edge 171 (recalibrated above), liquidity 118 (equity cap above), topology override 80 (exempted above), kill switch 36, isolated 11, risk-off 5.

### 144. BT4: the round-3 changes in Lean (V5.6.0 final run, `backtests/2026-10-09_22-13-03`)

**Severity:** 5/10 · **Status:** 🟢 `fixed and verified` for #143 (the gains are real in Lean); the kill-switch throttle and the spread-floor recalibration below stay open
**Result (run 1634094171, 6,925 s, shipped config, probes off, Docker image rebuilt first):** Lean Sharpe **-0.042** (BT3 -0.763; 10-07 -1.05), without a risk-free rate +0.663 (BT3 +0.813), net profit **+4.73%** (BT3 +2.61%), drawdown 2.8% (1.4%), 534 orders (276), fees $897 (428), win rate 48%. Realized P&L net of fees: crypto book +$1,904 / non-book +$130, equity book +$1,788 / non-book +$731; the legacy sleeve stays net positive. Engine log: `numerical precision` lists only `AAA`, no 2050 starts, `sequence_served=78833`, teardown timeout unchanged (#104). Feature snapshots agree with the dataset (XOM/NVDA: 24 and 31 divergences over 281 dates).
**What each round-3 change did (BT3 -> BT4, book-member decisions):** reaching `trade` 71 -> **321**; `liquidity_blocked` 118 -> **0** (equity spread cap); topology elevated override 80 -> **0** (veto exemption); net-edge blocks 171 -> **1** (edge 574); forex exposure 0 and no forex slots; the slippage trigger never fired. Equity exposure rose from a 2.6% to a 6.7% mean long ratio, which is where the extra return and the extra drawdown come from.
**Offline vs Lean:** the as-live simulation said +0.78 net Sharpe (+11.9%) and Lean delivered +0.66 without a risk-free rate (+4.7% over 2.25 years), so the simulator is optimistic by roughly 2x on return but now ranks changes correctly; it was pessimistic by more than 1 Sharpe at the start of the phase.
**Still open:** (1) the kill switch (`min_rolling_sharpe` -1.0 over 60 bars) is now the main throttle: 96 member decisions were `reduce_risk` on it (36 in BT3); (2) spread-gate vetoes rose from 25 to 85 of 281 rebalances because the spread floor 0.1985 was calibrated on a pool that included forex - recalibrate it on the forex-free pool (`--calibrate-book-spread`) and check against the validation split before changing it; (3) 11 limit orders stayed open longer than 5 days (BT3: 6).

### 145. The offline simulator modelled almost none of Pass 2 and its gate took 15 minutes: rebuilt on main.py's own functions (V5.7.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed and verified` — built, unit-tested, reproduces BT4's kill-switch dates and return level; the decisions it enabled (#146) held up in BT5 (#148)

**Problem:** The as-live simulator (#128) skipped the kill switch, the per-member sizing chain, the liquidity and net-edge gates, HRP and per-name impact; hardcoded `hold_positions_on_veto=True`; calibrated the spread floor on a pool containing disabled forex; charged the Almgren rate as a fraction of NAV on a $1M book (the "0.78 → 0.53" was an artifact); spent ~12 min per rolling-IC gate (full-history re-resolution per date); and the audit's "11 limit orders open > 5 days" counted calendar days against an equity-session timeout.

**Fix:** `evaluation/rolling_ic_series.py` (state per date once, one state serves every floor) and a rebuilt `simulate_rank_book(...)` taking `live_parity.build_live_member_weight_fn / build_hrp_raw_weights_fn / build_live_mechanisms` (the live pure functions, not copies), per-name impact at real NAV, `--calibrate-book-spread` on the live pool, `--audit-fills`, weekday-session limit ages, `run_id` + `per_run_files` on book-history records, and `newey_west_t_stat`; `scripts/as_live_levers.py` caches scoring and shares the IC state (~20 s per variant).

**Verification:** First full as-live run: net Sharpe 0.087 (+0.52%) vs V5.6's 0.781, reproduced exactly with the new mechanisms off; the kill switch is the throttle (off 0.535, sizing chain off 1.139). Keeping observation-only rows — live's percentile normalisation runs over every symbol — gives backtest **+0.661 / +4.16%** (Lean BT4 +0.663 / +4.73%) and validation +0.745 / +2.54%, so the simulator now reproduces the Lean run it was calibrated against. Still book-only, so decisions use the relative R-GATE comparison on both splits.

### 146. Gate research on the rebuilt simulator, both splits: one rule-driven flip, five rejected, the kill switch kept (V5.7.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` — decided offline by the pre-registered R-GATE rule and confirmed in Lean by BT5 (#148)

**Problem:** todo findings 1-5: the kill switch was the main throttle (96 `reduce_risk` decisions in BT4), the spread floor 0.1985 was calibrated with forex in the pool, the rolling-IC gate vetoed 157 of 281 rebalances, and hold-on-veto and HRP were "not evaluable offline".

**Result** (`scripts/gate_research.py`, `ml/evaluation/v570_gate_research.json`; baseline backtest +0.661 / +4.16% vs Lean BT4 +0.663 / +4.73%, validation +0.745 / +2.54%): the **IC gate** (window 80 / floor 0.0) was the only point to pass R-GATE (backtest +0.797, validation +0.787, drawdown 4.05% vs 4.89%) → shipped; the **spread floor 0.1840** (calibrated on the live pool, was 0.1985 with forex in it) also passed (backtest +0.954, validation +1.244) → shipped; the **kill switch**, hold-on-veto, HRP, own-tick and Almgren were kept or rejected by measurement; the **legacy-sleeve cap** went 0.10 → 0.05 (alpha -0.14%/trade, t -0.23, vs book +1.09%, t 2.46).

**Verification:** The shipped bundle in the full as-live simulator gives backtest **+0.954 / +6.48%** and validation **+1.244 / +3.79%**; no kill-switch value, hold-on-veto, HRP or IC-gate neighbour passes R-GATE again; the simulated kill switch locks the same rebalances as Lean (6 of 8 on BT4).

### 147. Execution-cost leads closed with measurements: no data-source gap, market fills pay the modelled 5 bps, no limit order was stale (V5.7.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed and verified` (IB paper fills stay deferred with #116's IB part)

**Problem:** todo finding 6: a median 5 bps fill-vs-open gap was blamed on "a data-source gap, not slippage"; 11 limit orders were flagged "open > 5 days".

**Fix:** `aq evaluate --audit-fills` on BT4 (495 fills) found no price-source gap — the dataset open equals the Lean zip open adjusted by the factor files on all 495 traded ticker-dates (0.0 bps) — with equity market fills at the configured +4.98 bps per side (p99 5.18), equity limit fills a median 0 bps, and crypto market fills +3.9 bps; counted in weekday sessions (`--max-open-sessions`), BT4 has **0** stale limit orders (was 11). Added `evaluation/fill_price_audit.py` and session ages in `backtest_audit`.

### 148. BT5: the V5.7.0 gate bundle in Lean, and a kill-switch trigger that counted price improvement as slippage (V5.7.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed and verified` - the bundle passed R-LEAN in Lean; the trigger needed a second fix, see #153 (BT7)
**Result** (`backtests/2026-10-10_19-22-24`, run 1119587913, 8,796 s, IC window 80 / floor 0.0, spread 0.184, legacy cap 0.05, probes off): Lean Sharpe **+0.068** (BT4 -0.042), **+0.711** without a risk-free rate (BT4 +0.663), net profit **+5.57%** (+4.73%), drawdown 3.60% (2.8%), 583 orders (534), fees $798 ($897), win rate 52%. R-LEAN (no-risk-free Sharpe >= 0.61, drawdown <= 4%) passes. The simulator had predicted +0.954 (book only, no sleeve). Realized P&L net of fees: equity book +$4,449 (BT4 +$1,788), equity non-book +$1,061, crypto book **-$193** (13 trades, fees $257 on $64 gross; BT4 +$1,904) and crypto non-book +$239. The book engaged on 47 of 192 logged rebalances (BT4 39/281); 0 stale limit orders (sessions), 0 overlapping orders; exposure equity 6.5% long / 4.5% short. Engine log: `numerical precision` lists only AAA, no 2050 starts, `sequence_served=78833`, the usual `Failed to shutdown python` teardown (#104). Feature snapshots: XOM 19/192 and NVDA similar dates diverge (32 divergences of 9,984 comparisons), no `sens_*`, no price-level feature; `fx_carry_3m` is live-only until the dataset is rebuilt.
**Problem:** 24 book-member decisions (2 rebalances of the 12 kill-switch ones) were locked by `kill_switch_slippage_divergence_above_cap`, a trigger that never fired in BT4. `compute_fill_slippage_divergence_bps` took `abs(fill - open)`, so a limit order filled BELOW the open on a buy (price improvement, which is what a limit order is for) pushed the rolling average toward the 80 bps cap; the crypto limit fills sit 1-4% under the open.
**Fix:** the function takes the fill's direction and counts only adverse slippage (`main.py` passes `FillQuantity`); without a direction it keeps the absolute gap. Tests: pure cases (buy below / sell above / adverse / unknown side) and a wiring test through `_track_slippage_divergence`.
**Open from the run:** crypto is a cost centre at 49 bps per fill (the book's 13 crypto trades earned $64 gross); the crypto graduation question (#149) and the kill switch (12 of 47 engaged rebalances locked, 120 `rolling_sharpe` decisions) stay the levers to look at next.

### 149. Crypto: no observation-only name graduates, and BTC/LTC stay (V5.7.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed and verified` as a decision (no code change; the machinery below ships default-off)

**Problem:** todo finding 7: the crypto book pool is two names (BTCUSD, LTCUSD; the other ten fail the 250-TRAIN-row rule, ETH has 54) and every fill costs ~56 bps; BT5's 13 crypto book trades earned $64 gross for $257 of fees.

**Fix:** `scripts/crypto_graduation_research.py` (full as-live simulator, both splits, Coinbase fees) found no name passes R-GATE alone (XLM backtest +1.03 but validation -1.67; DOGE/ZEC fail the other side) and all ten together collapse the book; removing BTC/LTC also loses on both splits, so **crypto stays as is**. Shipped default-off: `phase9.asset_quality.trading_eligibility_basis: "history"` (+ `min_trading_history_rows`) lets a thin-history name trade on validation + backtest history scored by the pooled model, to revisit after the V5.7.0 retrain.

### 150. V5.7.0 retrain: leakage fixed, honest numbers are lower, R-MODEL fails, V5.6.0 stays (V5.7.0)

**Severity:** 6/10 · **Status:** 🔴 `closed` as a promotion (no model change); the diagnostics, purge and holdout machinery ship 🟢
**Problem:** todo ML gaps: train/validation IC gap (0.44-0.52 vs 0.03-0.04), no purge at split boundaries, an in-sample "purged CV", 14-date validation, forex invisible to the model, no out-of-window data.
**Result** (Codespace `aq-Training-Ground-Fixed`, tag `v570cs20261010`; label purge 20d, `asset_class_forex` one-hot, `fx_carry_3m`, separate forex rank group): control mean full-daily validation IC **+0.0769** (3 seeds, spread 0.018, HAC t reported); variants v1-v7 (2 seeds) all inside the spread (best v7_small_net +0.0858, ListNet +0.033) -> winner = control. R-MODEL on control + new sequence/gating: walk-forward `rank_20d` IC **0.0488** with 25% sign flips (bar 0.085 / 0), as-live backtest **+0.287** vs active +0.954 (bar >= 0.904), validation +1.022 vs +1.244 -> **fail**, V5.6.0 stays active (restored byte-for-byte). Part of the drop is the removed leakage (no purge in V5.6.0), so the old 0.101 walk-forward IC was optimistic, not the new one pessimistic.
**Holdout, one look** (2021-04..2025-06, candidate only): multitask rank_5d daily IC +0.055 (HAC t 3.95), rank_20d +0.069 (t 2.67); sequence +0.055 / +0.072 - there IS out-of-window rank signal. The as-live book on the holdout loses (Sharpe -0.21, -3.8%, DD 7.6%): the rolling-IC gate vetoed 513 of 630 rebalances and the kill switch locked 315 dates, so in 2021-25 the gates strangle a positive-IC signal. Not tuned (the holdout is report-only); it is the lead for the next retrain/gate round.
**RL (R-RL fail, fifth negative):** main policy -7.7e-5 vs constant -6.5e-5 on the backtest split; forex book-level policy had only 96 validation rows (min 200; re-run at 60): beats constant 1.0 on the backtest split (+2.6e-4 vs -1.6e-4) but not on the holdout (+0.9e-4 vs +1.5e-4). `rl_sizing_enabled` stays false.
**Recipe for the next retrain** (flips reverted in `config.json` so it matches the shipped models): `phase1.windows.purge_label_horizon_days: 20`, `fx_carry_3m` in `phase1.features.input_set`, `phase1.target.ranking.separate_rank_groups: {"forex": ["forex"]}` (+ `separate_rank_group_min_size: 8`), then `scripts/codespace_retrain_v570.sh a|b` (resumable: `RESUME=1`).

### 151. Forex sleeve: no within-pool rank edge, R-FX fails, forex stays off (V5.7.0)

**Severity:** 4/10 · **Status:** 🔴 `closed` (superseded by #163: forex trades again, only as the carry-ranked sleeve at the minimum cap)
**Problem:** todo finding 8: forex is off because IB's $2 minimum is ~10 bps per side at ~2% NAV against ~$0 gross edge; the plan was a fee-aware sleeve (top/bottom-k within the 15 pairs, 20-bar rebalance, dollar deadband) plus RL sizing.
**Result** (`scripts/forex_sleeve_research.py`, as-live simulator, $2 minimum modelled, grid gross {20,30,40%} x k {2,3} x deadband {$1k,$2.5k}): V5.6.0 models - forex within-pool rank IC **-0.065** validation (HAC t -1.16) and **-0.034** backtest (t -0.47); every sleeve config has negative net Sharpe on both splits (validation -0.60..-0.79, backtest -0.25..-0.49), gross return also negative, costs only 13-21 bps/yr. Retrained candidate (forex one-hot, `fx_carry_3m`, separate forex rank group): IC still **-0.070** / **-0.068** (t -0.96 / -1.15); its sleeves are still net-negative on both splits (e.g. k=2, 30% gross: validation Sharpe -0.73, backtest -0.28; backtest gross return at most +0.1%); full grid in `ml/evaluation/forex_sleeve_research_candidate_v570.json`. R-FX offline (net Sharpe > 0 on both splits AND forex IC > 0 on validation) fails; no Lean forex run is justified. The fee floor is no longer the problem (the sleeve's fees are small); the model has no cross-sectional forex signal, and the carry feature did not create one.
**Other pieces:** the forex RL policy is data-starved (96 validation rows) and fails R-RL (#150). The 2021-25 holdout was not used to tune anything here.

### 152. Gating, label timing and the shipped checks that need no change (V5.7.0)

**Severity:** 2/10 · **Status:** 🟢 `fixed` (verified, no code change)
**Problem/Fix:** No code change. **Gating (M3.9):** the learned model (MCC 0.0097) feeds only the MoE direction path (`moe_gating` in `main.py`), which drives the capped legacy sleeve (5% gross after #146; alpha -0.14%, t -0.23); the rank book and as-live simulator never read it, so its effect is bounded by the sleeve cap. **Execution-aligned labels (M3.8):** realized rank IC of the live score against open-to-open vs close-to-close 20-day returns is backtest +0.1494 vs +0.1506 (-0.8%) and validation +0.0466 vs +0.0497 (-6.3%), both inside the plan's 20% threshold, so no open-to-open label variant is needed.

### 153. BT6: the direction-aware slippage fix did nothing; the trigger was crypto limit-fill drift (V5.7.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed and verified in Lean` (BT7), with one residual lead noted below
**Result** (`backtests/2026-10-11_11-42-14`, run 1765941439, third attempt - see below; V5.6.0 models, BT5 config + #148's direction-aware trigger): Lean Sharpe **+0.128**, **+0.768 without a risk-free rate** (BT5 +0.711, BT4 +0.663), net profit **+6.05%** (+5.57%, +4.73%), drawdown 3.60%, 575 orders, fees $797, win rate 53%. R-LEAN passes (>= 0.661, <= 4%). Book engaged 47/192 (as BT5), 0 stale limit orders, 0 expert/inference failures, `sequence_served=78833`, only AAA in the precision line, usual teardown timeout; reconcile XOM 19/192 and NVDA 18/192 divergent dates (the known topology/regime/peer residuals, same as BT5). The simulator predicted backtest +0.954 (book only); Lean no-rf 0.768 is within the 0.2 tolerance. Crypto is still a cost centre: book members -$236 net (13 trades, fees $257), non-members +$239.
**Problem:** the 24 `kill_switch_slippage_divergence_above_cap` decisions (2020-12-24 and 2021-01-27) are IDENTICAL to BT5, so the #148 change (count only adverse slippage) did not touch them. The audit shows why: the 20 fills before those dates include LTCUSD limit buys filled +376 bps from the bar open and an XOM limit buy -127 bps; the tracker compares a fill with the bar's open although the order was submitted hours later, so a limit fill's gap is intraday drift, not execution cost (and a limit fill cannot be worse than its own limit price).
**Fix:** `_track_slippage_divergence` ignores fills of tracked limit orders (`pending_limit_orders`), still consuming the stash; market fills (the ~5 bps cases the metric exists for) are unchanged. Tests: tracked limit fill not counted and stash consumed, market fill unchanged. BT7 is the confirmation.
**Process failures worth keeping:** (1) the first BT6 start failed at once because Docker Desktop was not running; (2) the second ran 1h20m on a CORRUPTED `ml/`: the Codespace pull had overwritten `ml/expert_models/` with the rejected retrain's experts and my restore skipped that folder, giving 262,808 `Expert multitask inference failed` lines (BT5: 0) - caught only by grepping the engine log mid-run, killed, set aside in `backtests_invalid/`. `ml/` was then verified file-for-file (SHA-256) against the pre-retrain push snapshot. Rule: after any pull, diff all of `ml/`, and grep the engine log for `inference failed` in the first minutes.
**BT7 (`backtests/2026-10-11_14-23-30`, limit fills excluded, everything else = BT6):** Lean Sharpe **+0.474**, **+1.151 without a risk-free rate** (BT6 +0.768, BT5 +0.711, BT4 +0.663), net profit **+8.64%**, drawdown **2.80%** (BT4 level), 641 orders, fees $822, win rate 53%; crypto book members now +$476 net (12 trades) instead of -$236. Kill-switch dates 12 -> **6**, member `reduce_risk` decisions 147 -> **72**, book-member `trade` decisions 368 -> **430**; engine log clean (0 inference failures, `sequence_served=78833`, only AAA in the precision line, usual teardown timeout); XOM reconcile 12/192 divergent dates (BT6 19); 0 stale limit orders; dataset open == zip open on 586 traded dates. R-LEAN passes with margin; this is the shipped configuration. The simulator's backtest +0.954 / +6.48% (book only) vs Lean +1.151 / +8.64% (with sleeve and crypto) is now conservative.
**Residual lead:** `kill_switch_slippage_divergence_above_cap` still labels 35 member decisions (down from 24 on 2 dates to a few dates incl. 2020-12-24 and 2021-03-24), so a non-limit path still feeds the 20-fill average above 80 bps (a cancelled limit re-sent as a market order a day later is the prime suspect). It no longer decides the result; to close it the divergence value would have to be written into the book-history record, which needs one more backtest and was out of scope (3 of 3 backtests used).
### 154. Closing the minor leads against BT7 (V5.7.0)

**Severity:** 2/10 · **Status:** 🟢 `fixed` (all closed as accepted residuals with numbers; no code change)

**Problem/Fix:** BT7's `--reconcile-features` closed every minor lead as an accepted residual. **Topology cache tolerance (#36):** `topology_correlation_strength` differs on 7/192 (NVDA, mean |delta| 0.027) and 10/192 (XOM, mean 0.018) rebalance dates — the largest of the 52 features — and fell 19→12 / 18→11 between BT6 and BT7 with no topology change, pointing to run-dependent state, not a cache bias. **XOM/NVDA selection residuals (#91/#97/#100):** now 6% of dates per symbol with the other 52 features exact; closed as accepted. **AAA's late Lean start (#140):** observation-only (139 of 163,234 rows), removable only by an unadopted retrain (#150), left as is. **Live-only `fx_carry_3m`:** kept because the next retrain consumes it (one dict lookup per symbol).

### 155. CI-only failure: a constant return window correlated as noise on Python <= 3.11 (V5.7.1)

**Severity:** 3/10 · **Status:** 🟢 `fixed and verified` (reproduced on Python 3.10, fixed, 54/54 topology tests pass there and on 3.14)
**Problem:** `test_vectorised_correlations_match_the_scalar_pearson_for_every_pair` failed on every CI job since V5.6.0 (CI runs 3.11, the dev PC 3.14): `_pearson_correlation` relied on an exact zero variance for a constant window, but Python <= 3.11 sums naively so `mean([0.001] * 24) != 0.001` and the variance came out ~1e-35, giving a ~1e-17 correlation instead of 0.0 and breaking the alphabetical top-peer tie. Lean also runs 3.11, so live peer ranking for a flat series could differ from the 3.14 dataset the same way.

**Fix:** A window whose values are all equal now returns 0.0 in the scalar path and zeroes that row and column in the vectorised matrix (decided on the values, independent of `sum()` rounding). Tests: 4 constant levels through both paths.

**Verification:** With the old code the original test and all 4 new cases fail on 3.10; with the fix all 54 topology tests pass on 3.10 and 3.14.

### 156. All Lean data stopped at 2021-03-31: ten crypto pairs never reached 250 train rows, the shipped models were stale for live, and the holdout was a separate root (V5.8.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed and verified` (data, audit, parity of both trees; the models retrained on it are #160+)

**Problem:** every zip under `data/` ended 2021-03-31 (BTC's quote zip 2018-12), the train window was 2014-12..2017-12, so ETH had 54 and the other nine crypto pairs 52 train rows (observation-only by the 250-row rule), forex mixed OANDA quotes with Yahoo patches on different clocks, 15 Lean factor files sat beside zips that were already adjusted, and the 2021-25 holdout lived in `data_holdout/` where it could only be read, never trained on. The shipped V5.6.0 models, scored on the new 2022-01..2023-06 validation split, have no rank edge at all: pooled `rank_20d` IC -0.003 (HAC t -0.07), within-bond -0.10 (t -1.07), within-equity +0.036 (t 0.85), between-class -0.06 (`aq evaluate --ic-by-class`).

**Fix:** all 104 universe zips rewritten 2013-01..2026-09 from ONE Yahoo source (forex high/low widened to contain open/close in 57-226 rows per pair, one verified bad EURGBP print on 2022-10-10 corrected through `data_pipeline/price_overrides.json`), crypto quote zips regenerated, the 19 FRED series refetched in full, the 15 obsolete Lean factor files removed (a missing file is an identity; never a sentinel stub, #130), `data/reference/crypto_listing_dates.json` built from Coinbase's own candles (XRP suspended 2021-01-20..2023-07-13, EOS delisted 2025-12-11, ADA listed 2021-03, DOGE 2021-06, ZEC 2020-12). New splits train 2014-12..2021-12 / validation 2022-01..2023-06 / backtest 2023-07..2025-06 / holdout 2025-07..2026-09 (`phase1.windows.holdout`, read once), `runtime.lean_window_override` for a Lean run over the holdout.

**Verification:** `aq evaluate --audit-data`: 104 assets, 20 flagged, every flag a real market event (FB -26% 2022-02, IBM -25% 2026-07, crypto spikes, the CHF/GBP shocks); `factor_file_backfill --audit` 0; the local and Codespace `data/` trees match by name, size and content digest (679 hashed files each).

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

**Severity:** 5/10 · **Status:** 🟢 `fixed` (the per-stage numbers are in and BT1's probe gave the in-Lean split: `write_state` was 34% of the run, throttled for backtests in BT2, 48 minutes for 3.25 years against 53 for 2; the rest is listed as L8 in todo.md)

**Problem:** per-tick `inference_cluster` 166-494 ms (57 separate NumPy-dispatched model calls), topology 332-542 ms (pure-Python pair dict, sort per symbol, SMACOF target by function), `write_state` rewriting ~1.2 MB of JSON every tick, the sequence trainer holding a 1.3 GB dense tensor plus two copies, tests spawning one git process per link.

**Fix:** flat baseline and multitask models for all pending symbols in one matmul per layer (`inference_parallelism.batch_flat_models_across_symbols`, now on): 64 ms -> 2 ms per tick for the multitask model on 57 rows, outputs equal to 5e-16; topology correlation lookups, peer ranking (`np.lexsort`, same alphabetical tie-break) and the SMACOF target from one dense matrix (output identical on 6 random universes incl. constant windows, young windows and exact ties; 230 -> ~160 ms); scaler terms and the sensitivity regression trimmed to the lookback; per-split sequence tensors built straight from the matrix (`row_mask`); vectorised split assignment; dashboard writes throttleable in backtests (`diagnostics.state_write`, default unchanged); `TimingProbe` stages `write_state` and `pass2`; docs-link test 5.8 s -> 0.65 s; chunked dataset read in the lever harness.

**Verification:** equality tests for every changed numeric path; on the full suite the Codespace needs 96 s against the 4 GB PC's 11 minutes and a harness reap.

### 160. The Codespace retrain was killed five times: a memory spike in the sequence trainer, a push that overwrote the retrain's own artifacts, and VM restarts (V5.8.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (every cause removed or made recoverable; the lessons are in `development/infrastructure.md`)

**Problem:** (1) `train_sequence.py` ran the whole 170k-row train tensor through the model in one call at the end (`compute_sequence_multitask_metrics`, the purged-CV pass): several GB of activations on top of 3 GB resident, which the 8 GB no-swap Codespace answers with an external SIGTERM and no OOM line (a 3-second sampler is too coarse to see it; the kill is at the spike). (2) `codespace_sync.ps1 -Mode push` overlays the local `ml/` top-level files, so a mid-retrain push replaced the new scaler, schema, manifest, baseline model and experts with the old ones and still printed "verified" (it only compares the local files' hashes). (3) The VM restarts (uptime 18 min at 16:48) and kills every nohup job. (4) After 3 hours the VM held 1.7 GB of memory outside any process visible from the container, and `train.py`'s dataset build peaks at 5.6 GB.

**Fix:** `forward_in_batches` (4,096 rows) for every full-split forward pass, per-split sequence tensors, a float32 chunked CSV read, a float32 in-memory frame for the baseline/expert trainers, stage-by-stage RSS lines in `train.py`, `performance_probe.install_sigterm_witness`, `codespace_sync.ps1 -Mode push -CodeOnly` (never touches `ml/`, `data/`) and `-Mode pull -NoDatasets`, a restart of the VM to reset its memory, `train.py` re-run with a dataset checksum comparison (`scripts/codespace_rebuild_then_b.sh`: **byte-identical**, so the stage A multitask fits still match the regenerated scaler), detached `setsid` launchers with pid files (`codespace_start_bg.sh`), a walk-forward disk cleaner side-car and `codespace_status.sh` / `codespace_grep.sh` / `codespace_memwatch.sh` / `codespace_diag.sh`.

**Verification:** the sequence model trains through to its artifacts in 9.5 minutes with the batched evaluation (backtest direction MCC 0.0189); the dataset MD5s before and after the rebuild match for all four files.

### 161. The rolling-IC gate vetoes the better periods: lead 1 closed with the audit and decided by R-GATE (V5.8.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (decided by rule; Lean read the gates: 47 of 94 rebalances vetoed in BT1, 140 of 210 in BT2, all by the rolling-IC gate. The offline benefit of the gates did not transfer, see #172, so they are safety controls, not alpha)

**Problem:** on the 2021-25 holdout the gated book lost (-0.21) while the ungated one earned +0.55; the gate vetoed 513 of 630 rebalances although the pooled IC was positive.

**Result** (`--audit-gates`, retrained candidate): the gate's vetoes are anti-informative. Backtest split 2023-07..2025-06: 25% of dates vetoed, 82% of them false, mean forward IC on vetoed dates +0.156 against +0.095 overall; validation: 37% vetoed, forward IC +0.036 vs +0.004. Trailing IC mean-reverts here, so a low trailing reading is followed by BETTER skill. R-GATE grid (window 40/80/120 x floor -0.10..+0.05, spread floors, kill switch, hold-on-veto, HRP, impact) on both splits: the previous config (window 80 / floor 0.0) gave backtest +0.475, validation -0.624; three settings pass; the best validation Sharpe is **window 120, floor 0.0** (+0.966 / +0.048, drawdown 5.5% vs 7.1%), then the spread floor **0.184 -> 0.10** (backtest +1.176 vs +0.966, validation unchanged); the kill switch stays (off: +0.85 / -0.11); hold-on-veto, HRP (validation -1.2) and Almgren impact stay rejected.

**Caveat, stated plainly:** about 40 variants were scored on two splits and neighbouring floors swing by +-0.5 Sharpe (floor +0.05: +1.36 backtest, -1.73 validation), so the selection is a noise-level improvement picked by a fixed rule, not an estimated edge; BT1 and the one-look holdout are the real tests.

### 162. V5.8.0 retrain, R-MODEL8 and the walk-forward (V5.8.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (walk-forward done, R-MODEL8 decided by the owner on 2026-10-13, Lean read in BT1 and BT2: #172, #174)

**Result so far:** the shipped V5.6.0 models, scored on the new splits with their own scaler, have no rank edge on 2022-23 (pooled `rank_20d` IC -0.003, t -0.07) and their as-live book is degenerate (validation: 7 of 335 rebalances engaged; backtest: 0 of 518, the spread floor calibrated on 2014-21 scores vetoes everything, Sharpe exactly 0.0; ungated books -0.03 and +1.07). Stage A (train 2014-12..2021-12, purge 20 d, bond/forex rank groups, point-in-time bond beta, `fx_carry_3m`): control mean full-daily validation IC +0.0229 (3 seeds, spread 0.042); no variant beats it by more than the spread (`v7_small_net` +0.0413 is closest), so the **control wins**. Candidate vs active on the same splits (config of that moment): ungated book validation +0.58 vs -0.03, backtest -0.22 vs +1.07; gated as-live validation -0.62 vs +1.22 (7 engaged rebalances), backtest +0.47 vs 0.0; with the R-GATE settings of #161 the candidate's as-live book was +0.05 / +1.18 (validation / backtest) before the sleeve decisions. **Final config, same for both** (bonds in their sleeve, crypto caps, RL; main book only): candidate validation +0.52 (28 engaged of 139 rebalances) and backtest +0.62 (50 of 79); active models validation +0.94 (10 of 311 engaged) and backtest -0.84 (5 of 484), so the old models still veto 97% of rebalances and their Sharpe rests on a handful of trades. **Walk-forward (12 expanding windows, 2014-12..2025-05):** rank_20d IC +0.0525 (bootstrap CI +0.019..+0.083, positive in 10 of 12 windows, t 2.2-3.2 depending on window overlap, sign flips 0.17), rank_5d +0.022, direction MCC +0.018 but fading (0.042 in window 5, about 0 in windows 9-11); the idealized book is net-positive in only 4 of 12 windows (mean Sharpe -0.16): costs eat most of the IC. **R-MODEL8:** clauses 1-3 pass, clause 4 fails numerically; the owner decided on 2026-10-13 to **keep the candidate** and to keep the four rank heads (below the single-split promotion gate, t 0.55-1.26, but passing the walk-forward) as watchlist; the learned gating network (MCC 0.0007 vs baseline 0.015) is switched to the hardcoded blend by the R-HEAD rule (`gating_network.learned_model_enabled: false`, it never fed the rank book). The out-of-sample verdict is in #169.

### 163. Forex: a carry-ranked sleeve at the minimum cap (V5.8.0, R-SLEEVE)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (shipped at the minimum cap with its guard; BT2: -$188 gross, -$544 net of fees over 3.25 years, guard never tripped, so the sleeve earns nothing and costs 0.5%; keep it capped or drop it, owner call)

**Problem:** no signal source gives forex a net-positive sleeve on both splits (4 signals x k {2,3} x gross {0.10, 0.20, 0.30} x deadband, the $2 IB minimum modelled per order). Within-pool rank IC: model rank +0.026 (t 0.30) validation / -0.014 backtest, **carry +0.070 (t 0.73) / +0.062 (t 0.65)**, time-series momentum -0.013 / -0.081, carry+momentum +0.027 / +0.048. Best variant (carry, k=2, gross 0.30): Sharpe +0.45 validation, -0.13 backtest.

**Fix:** by the owner's decision (every research area ends up trading) and the R-SLEEVE rule the sleeve ships at the **minimum cap**: `forex_risk.enabled` and `forex_sleeve.enabled` true, `signal: carry`, `gross_budget 0.10`, `per_side 2`, dollar deadband $1,000, its own loss guard (1% of NAV over 60 bars, 60-bar cooldown), RL off. `features/fx_signals.py` ranks by the 3-month rate differential, point-in-time.

### 164. Bonds: they lost money in the book; a momentum-ranked sleeve passes R-SLEEVE (V5.8.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (shipped at the minimum cap after BT1's -$540; BT2 with gross 0.10: +$37 gross, -$31 net over 34 trades, guard never tripped)

**Problem:** every one of the 18 bond ETFs the V5.7 book traded lost money (about -$598 gross in BT7), which the audit never showed because it counted bonds as equities. Within-bond rank IC of the retrained model: -0.042 (t -0.58) validation, +0.074 (t 1.20) backtest, so the model has no stable bond edge; the 22 ETFs in the equity pool also made the book a bonds-vs-equities bet.

**Result:** bond sleeve (22 ETFs ranked among themselves, k 2/3, gross 0.10/0.20/0.30): ranked by the model it loses (Sharpe -0.41 validation / -0.61 backtest); ranked by vol-scaled 60/120-day momentum it is positive on both splits (k=2, gross 0.30: **+0.35 validation, +0.20 backtest**, +0.46% over two years) and adding it changes the combined backtest Sharpe by +0.02 (0.472 vs 0.451 without bonds). R-SLEEVE passes ("edge_pass"). The main book with bonds left IN its pool scored +1.18 on the backtest split but only +0.05 on validation; the rule is not to choose by hindsight.

**Fix:** `phase_v2.bond_sleeve` enabled (`signal: ts_momentum`, per_side 2, gross 0.30, deadband $500, loss guard on); bonds leave the main pool (live `_sleeve_class_for_asset`, offline `_universe_asset_metadata`).

**BT1 verdict (#172):** the sleeve traded 17 times and lost -$540 gross (-$574 net) in Lean over the same window it earned +0.46% offline, the second Lean run in which the bond ETFs lost. The Lean evidence overturns the offline edge pass, so R-SLEEVE's trade-anyway branch applies: gross 0.30 -> 0.10 (the minimum cap), loss guard unchanged. The status stays 🟡: BT2 reads the capped sleeve.

### 165. Crypto: all twelve pairs trade, the ten extra ones capped (V5.8.0, R-SLEEVE)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (all twelve pairs trade, the ten extra ones capped; BT2: crypto +$775 gross but $1,131 of fees at 70 bps per fill, -$356 net, holdout stretch -$864: the exchange fee eats the edge, see L11 in todo.md)

**Problem:** with the data to 2026 every pair has >= 1,400 train rows, so all twelve are trading-eligible; none had a proven edge (V5.7.0 #149) and each fill costs 49-56 bps.

**Result** (as-live simulator, Coinbase fees, listing guard): core only (BTC, LTC) backtest +0.707 / validation +0.406; all twelve uncapped +1.176 / +0.043; **capped 1% per name / 5% class gross +0.712 / +0.308** (larger caps are worse on validation); removing a single graduate moves the backtest Sharpe by -0.1..+0.4 and the validation by -0.1..+0.3 (no name is clearly bad, none clearly good). No capped configuration passes R-GATE against core-only.

**Fix:** the graduates trade at the minimum cap: `phase_v2.class_weight_caps.crypto` per name 0.01, class gross 0.05, BTC/LTC exempt (`portfolio/book_construction.py::apply_class_weight_caps`, shared by `main.py` and the simulator); the crypto-graduates loss guard; the venue listing guard (no order before a pair's Coinbase listing, none while XRP was suspended, none after EOS's delisting).

### 166. RL sizing, a sixth time: no edge, so it ships at the minimum range with a shadow guard (V5.8.0, R-SLEEVE)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (shipped at the minimum range with the shadow guard; the multiplier is not logged per order, so the Lean effect is not separable and is bounded by +-10% of a position)

**Problem:** the book-level 20-day reward policy (actions 0.6-1.2) again does not beat constant 1.0 on its own backtest rows (-0.00167 vs -0.00152; 593 rows); the forex policy had 148 usable rows (need 200). Through the new offline hook (the same `rl_sizing_multiplier` as live) no multiplier range gains >= +0.05 Sharpe on both splits (+0.02..+0.04 backtest, -0.01..-0.18 validation).

**Fix:** RL is in use at `[0.9, 1.1]` with `dynamic_risk.rl_shadow_guard` (falls back to constant 1.0 while the policy's trailing 60-bar excess return is below -0.2% of NAV): the offline result with the guard is -0.018 validation / +0.025 backtest. The forex sleeve does not use RL.

### 167. Latency and resources: what shipped, what R-LAT rejected (V5.8.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (the shipped items are pinned by equality tests; the rejected ones are rejected with numbers)

**Problem:** the Lean runtime was 6,900-8,800 s for 2.25 years with a per-tick cost dominated by inference (~164-494 ms), topology (~332-542 ms), state writes and `build_model_input` (1.9 ms x ~115k calls), and the training/evaluation tools held several GB of redundant copies.

**Shipped (each measured, outputs equal to <= 1e-12):** flat baseline and multitask models for all pending symbols in one matmul per layer (57 rows: 64 ms -> 2 ms per tick), topology peers and SMACOF target from one dense matrix (~25% less per call), scaler terms precomputed, sensitivity regression on the trailing window only, state writes throttled in backtests (`diagnostics.state_write`, default unchanged), probes for `write_state` and Pass 2, batched head scoring for the offline tools (an as-live scoring pass 10 min -> 83 s, ~0.6 GB lower peak), float32 chunked dataset reads, per-split sequence tensors and `forward_in_batches` in training, `tests/test_docs_links.py` 5.8 s -> 0.65 s.

**Rejected by R-LAT (< 10% on the touched stage):** L5, parsing the 95 KB `config.json` three times at each session rollover: 6.9 ms per parse x 3 x ~821 rollovers = 17 s of a 2,800-8,800 s run (0.2-0.6%). L11, the Lean code snapshot: measured 486 files / ~6 MB per run (`build/` 1.3 MB), a whole run folder is ~10 MB, so the 532 MB `backtests/` folder is accumulated runs, not snapshot bloat; Lean CLI offers no ignore list and a post-run prune would save ~1 MB.

**Verification:** `tests/test_exported_model.py`, `test_market_topology.py`, `test_model_predictions.py`, `test_performance_probe.py`; the BT1 timing probe reads the end-to-end effect.

### 168. Feature audit verdict: the flagged features are class descriptors, not leaks; no input-set change (V5.8.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (no leak evidence: the flagged features are class descriptors, and BT2's live features equal the dataset's on 89 of 90 equity dates; the out-of-sample weakness is lack of edge, not leakage)

**Problem:** `aq evaluate --audit-features` on validation + backtest flags 13 "ticker-ID suspects" (constant per ticker): `asset_class_*`, `bond_analytic_convexity/modified_duration`, `bond_dv01`, `bond_empirical_duration_beta`, `fx_carry_3m_scaled`, `regime_volatility_high`, `topology_risk_elevated`; 26 features that are constant for forex (volume, bond, macro, alt-data columns); 18 whose IC sign flips between splits.

**Verdict:** the asset-class flags and bond analytics are instrument descriptors by design, the forex-constant columns are simply not applicable to FX, and the point-in-time bond beta (V5.8.0) removed the one real look-ahead leak. A leak would show as in-sample IC that vanishes out of sample: the pooled rank_20d IC is +0.060 (t 2.34) on the untouched backtest split with only 2% of it between classes, and the holdout reads once more. Dropping inputs would force a retrain for no demonstrated gain (the control already won over the small-net and weight-decay variants), so the input set stays; `bond_dv01` stays price-dependent because bonds now trade in a momentum sleeve that reads no model feature.

**Verification:** `evaluation/feature_quality_audit.py` tests; class IC audit (`ml/evaluation/class_ic_audit_backtest.json`); the holdout report decides whether this verdict holds.

### 169. Holdout, one look (2025-07-01..2026-09-29, 104 tickers): no out-of-sample rank edge, the gated book loses 2.4% (V5.8.0)

**Severity:** 8/10 · **Status:** 🟢 `fixed` (reported as measured, nothing tuned on it; BT2 repeated the window in Lean: -1.61%, drawdown -3.85%, against -2.4% offline as-live)

**Result** (`scripts/holdout_report.py`, models and config frozen before the look): daily rank IC against the 20-day return, HAC t: multitask rank_5d +0.019 (1.08), multitask rank_20d +0.037 (0.98), sequence rank_5d +0.023 (1.41), sequence rank_20d -0.0001 (-0.00); the non-overlapping t of every head is below 1.2. The idealized top-6/bottom-6 book makes -0.81 Sharpe (-6.1%, drawdown 12.9%, turnover 8.7x, cost drag 189 bps); the as-live book makes **-0.59 Sharpe (-2.4%, drawdown 4.3%)** with 153 of 172 rebalances vetoed (152 by the rolling-IC gate) and a mean gross exposure of 13%, so the gates turned a -6% book into a -2.4% one by staying mostly in cash.

**Reading:** the in-window evidence (12-window walk-forward IC +0.0525 with CI +0.019..+0.083, backtest split +0.060 at t 2.34, ending 2025-05) did not persist into the 15 months after it. The honest status of the model stack is "weak, unproven edge": the safety layers work, the alpha is not demonstrated out of sample. No parameter was changed after this look.

**Verification:** `ml/evaluation/holdout_report.json`; the README "Research and Audit Results" block carries the same numbers.

### 170. Learned topology sizing, measured offline for the first time (rule R-TOPO): stays on (V5.8.0)

**Severity:** 2/10 · **Status:** 🟢 `fixed` (the offline blind spot is closed; the decision is "no change")

**Problem:** the live shrink-only topology multiplier (0.5..1.0) was invisible to every offline run, so `topology_learning` could not be judged by R-GATE.

**Fix and result:** `topology.learned_topology.learned_sizing_inputs` scores each dataset row with the live prototype distances, `build_live_member_weight_fn(topology_inputs_fn=...)` applies the same `topology_sizing_multiplier`, and `scripts/topology_sizing_research.py` brackets the unknown whole-bar peer term at 0 / 0.5 / 1. The retrained topology (6 clusters, regime labels now in the live `primary_regime` format) shrinks every node (mean multiplier 0.82 / 0.72 / 0.62, learned share 100%). Net Sharpe OFF vs ON(mid): validation +0.52 vs +0.09, backtest +0.62 vs +1.07; the sign differs by split and neither direction clears the R-GATE margins, so it stays ON, the shipped state. A learned share of 100% means the overlay acts as a uniform shrink, not a selector.

**Verification:** `tests/test_learned_topology.py`, `test_v570_live_mechanisms.py`, `test_topology_sizing_research.py`.

### 171. README results are refreshed by the commands that produce them; Monte Carlo is part of `--all` (V5.8.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** the README's Monte Carlo section claimed to refresh with every `aq evaluate` but only re-rendered a stale result (`--monte-carlo` was not in `--all`), `--monte-carlo` crashed with a KeyError on fewer than 30 daily returns, the as-live book and all V5.8.0 research were not on the page, and a second Lean run overwrote the first one's row.

**Fix:** `aq evaluate --all` includes Monte Carlo (a short dataset reports SKIPPED), `evaluation/readme_research.py` renders the as-live book per split and the research/audit block, `generate_backtest_report.build_history_markdown` lists every finished Lean run, and the audit flags and research scripts refresh the README on exit.

**Verification:** `tests/test_readme_research.py`, `test_generate_backtest_report.py`, `test_aq_cli.py`.

### 172. BT1 (Lean, 2023-07-01..2025-06-30): the retrained candidate loses 5.0% in the engine, the offline +0.62 does not reproduce (V5.8.0)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (BT1 measured and attributed; the regime-input skew it exposed shipped as #173 and BT2 ran on it; the main-book posture is the owner's call, L3)

**Result** (`backtests/2026-10-13_17-54-47`, config sha256 `01de086f5b5d42cf`, installed-model manifest `ml/evaluation/v580/installed_manifest_local.txt`): Sharpe -2.98 with Lean's risk-free rate (-0.75 without), net -5.03% (-$5,026), drawdown 8.2%, 514 orders, fees $975. R-LEAN8 fails on Sharpe (needs >= +0.31, half the offline +0.62) and drawdown (limit 5%). The engine log is clean: 0 `inference failed`, `sequence_served=70159` with 0 multitask fallbacks, no 2050 starts, no numerical-precision lines, 0 failed data requests, and the known #104 teardown timeout after the results were written. Realized P&L by config class (new in `--audit-backtest`, which used to file bond ETFs under "equity"): main-book equity -$4,847 gross (132 entries), non-book equity +$171, **bond sleeve -$540 (17 trades; BT7's bonds lost about -$598)**, crypto +$1,180 (net +$648 after $532 fees), forex sleeve -$14 gross / -$88 net.

**Reading:** the loss sits in the main equity book, not in plumbing. Equity and bond features reconcile with the dataset (XOM, NVDA, TLT: only `regime_signal_*` steps on 64 of 94 dates and one topology value), fills sit at the modelled ~5 bps, and the slippage-divergence veto fires 0 times (35 before the submit-price fix). The offline as-live book (+5.95%, Sharpe +0.62) and BT1 are uncorrelated (daily r = 0.02): the offline figure came from gates dodging an ungated book that loses (-0.72 Sharpe, -7.5% on the same split), and the same gates did not dodge the same days in Lean (47 of 94 rebalances vetoed live against 29 of 79 offline; with the live pool and hysteresis replayed the BT1 book shared 0.77 of its names with the offline replay, raw scores 0.0100 apart). That agrees with the holdout (#169): the rank IC of +0.05 does not turn into a book that beats its costs. Crypto and forex bars close after the equity tick, so their own-price features at tick D equal the dataset's previous row (ETHUSD: 37 of 53 features, the other 20 cross-asset / macro features match the same row; EURUSD: its price block 85%); `--reconcile-features` now applies that lag. Forex `atr_pct_14`, `liquidity_spread_proxy` and the `sens_*` betas match neither row (a different high/low and window source), which does not touch P&L because the forex sleeve ranks by carry. The one equity-relevant gap is #173.

**Latency (L0 probe, mean per call):** `write_state` 580 ms x 1,871 = 1,086 s (34% of the 53-minute run), `build_model_input` 3.6 ms x 106,535 = 386 s, `topology_payload` 186 ms = 347 s, `inference_cluster` 152 ms = 284 s, `pass2` 54 ms = 101 s. `write_state` passes R-LAT (>= 10%), so the shipped backtest-only throttle goes on for BT2.

**Verification:** `aq evaluate --audit-backtest / --audit-fills / --reconcile-features / --reconcile-book-history` (reconcile flags now take `--dataset`), `tests/test_backtest_audit.py`.

### 173. The models read a regime vector the dataset never produced: live fed the account drawdown into the `regime_*` inputs (V5.8.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (fixed, tested and confirmed in BT2: equity features equal the dataset on 89 of 90 dates and the live-pool book replay shares 0.81 of the names)

**Problem:** the dataset builds `regime_*` with `portfolio_drawdown=0.0` (it has no account state), while `main.py` passed the real `current_total_drawdown`, so `regime_signal_risk_score` / `_confidence` and the risk one-hots differed from training on 64 of 94 BT1 dates (mean |delta| 0.155 and 0.052). Re-scoring 42 backtest-split dates with the drawdown inserted (both models, both rank heads; the recomputation reproduces the dataset to 7e-7): at -2% nothing changes; at -4% every row's regime inputs change and the top/bottom-6 overlap falls to 0.91; at -8% to 0.66 (mean rank-score change 0.107). A losing book therefore changed its own inputs. Measured with the same replay tool on the live pool, the fix cut the raw-score error between live and the offline replay from 0.0100 (BT1) to 0.0064 (BT2) and lifted the shared names from 0.77 to 0.81 (BT3: 0.77, error 0.0044): a real but modest parity gain, not the whole reason BT2 did better than BT1.

**Fix:** `regime.build_model_input_regime_vector` (drawdown pinned to 0.0) is the one definition; `train._encode_regime_row` and `main.py::_build_model_input` (`_build_model_regime_payload`) both call it. Risk decisions keep the real-drawdown vector, and the second vector is built only while the account is in drawdown (nothing new per bar otherwise).

**Verification:** `tests/test_regime_model_input.py` (dataset encoding equals the model vector over a grid, live model regime is drawdown-independent, live risk regime is not), `ml/evaluation/v580/regime_dd_sensitivity.txt`. BT2's `--reconcile-features` must show the regime features within the 10% rule and `--reconcile-book-history --replay-hysteresis` an overlap back near 77%.

### 174. BT2 (Lean, 2023-07-01..2026-09-30): capital preserved, no edge demonstrated, the regime fix is confirmed (V5.8.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (measured, written up and verified; the verdict is no demonstrated edge, which is the owner's call at L3)

**Result** (`backtests/2026-10-14_07-27-32`, config sha256 `30534b24d02969457369e8ca991df0d562431f13836520b8ae4ade82618094e9`, manifest sha256 `cf8f68fe242da1e837b01598c3ec95bae1aee26c4dad50e4c2393ce622ed05fa`, models unchanged since BT1): 48 minutes, engine log clean (0 `inference failed`, `sequence_served=114283`, 0 multitask fallbacks, 0 numerical-precision lines, 0 2050 starts, 0 failed data requests; the known #104 teardown timeout after the results). **Whole run net -0.58%, drawdown 4.3%, 1,150 orders, fees $2,195; Sharpe -2.03 with Lean's risk-free rate, -0.03 without.** Backtest stretch 2023-07..2025-06: +1.04%, drawdown 3.6%, Sharpe +0.14 (BT1 on the same dates: -5.03%, -0.75). Holdout stretch 2025-07..2026-09 (reported, never tuned on): -1.61%, drawdown 3.9%, Sharpe -0.40. P&L by class (gross / net of fees): equity +$990 / +$350 (main-book members -$279 gross, non-members +$1,270), crypto +$775 / -$356, bonds +$37 / -$31, forex -$188 / -$544. **Costs ($2,195) exceed the gross result ($1,614)**; crypto alone pays $1,131 at 70 bps per fill. The rolling-IC gate vetoed 140 of 210 rebalances; the run ended with the kill switch's rolling-Sharpe lock active.

**Verdict by rule:** R-LEAN8's BT2 clause holds (engine clean); the drawdown limit holds (4.3% <= 5%); the BT1-style Sharpe bar (>= 0.31 on the backtest stretch) is still missed (+0.14). The +0.88 Sharpe gain over BT1 comes from a changed configuration (regime inputs, bond cap), one path each, so it is evidence for the fix, not proof of an edge. The holdout stretch agrees in sign and size with the offline holdout (as-live -2.4%).

**Parity:** equity and bond features equal the dataset on 89 of 90 reconciled dates for XOM, NVDA and TLT (BT1: 65 of 94 diverged on the regime scores), so #173 is confirmed in the engine. Crypto and forex own-price features equal the dataset's previous row (late-bar convention); their cross-asset block belongs to the tick's row, which `--reconcile-features` now applies. The book-history replay (`--replay-hysteresis`) first ranked all 104 tickers while the live main book excludes the bond and forex sleeves (0.46 shared names, an artefact of the tool); with the live pool it shares **0.81 of the names in BT2** (11 of 47 dates exactly, raw scores 0.0064 apart) against 0.77 in BT1 (8 of 47, 0.0100) and 0.77 in BT3 (0.0044), so book parity is at the BT3 level or better.

**Verification:** `aq evaluate --audit-backtest --period 2023-07-01..2025-06-30 --period 2025-07-01..2026-09-30`, `--audit-fills`, `--reconcile-features`, `ml/evaluation/v580/bt2_book_reconcile_pool.txt`, `bt1_book_reconcile_pool.txt`.

### 175. Lean's benchmark was a constant since 2021: the default hourly SPY feed had no data in the window (V6.0.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed` (BT1: no hourly benchmark feed, 813 distinct `Benchmark` values, Lean's Alpha / Beta now meaningful)

**Problem:** `main.py` never set a benchmark, so Lean added its internal **hourly** SPY feed, and `data/equity/usa/hour/spy.zip` is Lean's sample file ending 2021-03-31: BT1 and BT2 charted SPY as a constant 425.9975 (its 2023-06-30 close) on every point, so the README chart showed a flat benchmark and Lean's Alpha, Beta, Information Ratio and Tracking Error were meaningless. Of 599 non-daily zips under `data/`, that file was the only one any run read (`aq evaluate --audit-data`, new `non_daily_files` section); the rest are Lean's own sample data and stay.

**Fix:** `runtime.benchmark_ticker` ("SPY"; unset = Lean's default) -> `risk_controls.resolve_benchmark_ticker` -> `set_benchmark(lambda time: <the daily SPY subscription's price>)` in `initialize()`. The first version passed the SPY Symbol and BT1's first attempt (killed in its first minutes, `backtests_invalid/2026-10-15_14-36-29_bt1_benchmark_hourly_feed`, not counted in the budget) still logged `Adding internal benchmark data feed SPY,...,Hour`: a Symbol argument makes Lean create its own internal hourly feed; a function reads the daily price (checked in a Lean smoke run: no hourly feed, 63 distinct benchmark values over 63 sessions). `generate_backtest_report.py` redraws a flat Lean benchmark from the daily SPY zip (labelled, with a note that the run's Alpha/Beta are meaningless) and takes `--backtest-dir`; the README chart was re-rendered for BT2.

**Verification:** `tests/test_risk_controls.py`, `tests/test_main_ensure_ready_smoke.py` (`set_benchmark` called once with the SPY symbol on the real first-bar setup), `tests/test_generate_backtest_report.py`, `tests/test_data_audit.py`; BT1: no `Adding internal benchmark data feed ... Hour` line in the engine log, > 500 distinct `Benchmark` values, no `/hour/` in `succeeded-data-requests`.

### 176. The offline simulator is not a model of Lean yet: rule R-CAL says branch B, and the gap is now attributed (V6.0.0)

**Severity:** 7/10 · **Status:** 🟢 `fixed` (the tools and the verdict; the BT1 prediction check is in #185)

**Problem:** V5.8.0's as-live Sharpe overstated BT1 by +1.4 and every gate number was tuned on it; no tool compared the two day by day. **Tools:** `aq evaluate --attribute-lean` rebuilds a Lean run's daily P&L per ticker from its order events and the data zips' closes and splits it into main book / legacy signal / bond and forex sleeves / crypto core and graduates (it reconciles to Lean's equity curve within $2 over BT1's 2 years and $0.7 over BT2's 3.25: BT2 main book +$1,184 net, legacy -$834, crypto graduates -$806, forex -$544, crypto core +$538); `scripts/lean_calibration.py` compares it with the offline book rung by rung.

**Result** (main-book + crypto members vs the simulator, BT1 2023-07..2025-06 / BT2 backtest stretch / BT2 holdout stretch; V5.8.0 simulator -> calibrated): daily r 0.38 / 0.47 / 0.28 -> **0.70 / 0.68 / 0.21**, annualised return gap +5.4 / +1.7 / +1.2 pp -> +1.1 / -2.6 / -1.1 pp, rebalance decisions agreeing 23 / 26 / 45% -> **63 / 72 / 52%**, mean weight L1 0.34 -> 0.16 (BT1). What closed the gap: the cadence counted equity holidays that live does not count and on the wrong phase (agreement 23 -> 70%), the order filling at the next open instead of the next close, the IB per-order floor, live's resize threshold, entry cooldown and trailing stop (`rank_book_simulator` gained them, `scripts/as_live_levers.py` passes them), and the learned-topology multiplier. Replaying live's own gate decisions leaves r at 0.67-0.70, so what is left is execution detail, not the gates' reading. **R-CAL (r >= 0.50, |return gap| <= 2 pp, decisions >= 80%, on all three windows): not calibrated, branch B.** Gate numbers are therefore not offline-estimable: the gates stay frozen as safety controls (no R-GATE flip in V6) and alpha is judged on the UNGATED execution-calibrated book.

**Defect found on the way:** `live_parity.build_live_member_weight_fn` read the topology sizing keys from `phase_v2.risk`; `main.py` reads `phase_v2.dynamic_risk` (equal defaults, so harmless until now).

**Verification:** `tests/test_lean_attribution.py`, `test_lean_calibration.py`, `test_v600_simulator_parity.py`; `ml/evaluation/v600/calibration.json`, `attribution_bt{1,2}_v580.json`.

### 177. Forex features: Lean's fill-forward bar repeats the previous range, the dataset's was flat, and the sensitivity betas counted filled days (V6.0.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (BT1 reconciliation: EURUSD and GBPJPY diverge on 15 of 170 dates (8.8%), the rest were two reconciler conventions; the probe confirms Lean's fill-forward bar keeps the previous range)

**Problem:** EURUSD `atr_pct_14`, `liquidity_spread_proxy` and `sens_*` matched neither dataset row. Lean's source (`BaseData.Clone(bool fillForward)` = the previous bar, all fields, flagged `IsFillForward`; `FillForwardEnumerator` changes only the time) shows live windows held a Sunday bar with Friday's high and low, while the dataset (`train.fill_forward_forex_frame`) makes it flat at the previous close; and the dataset's sensitivity regression runs over real-bar rows with driver levels dated by the row, while live regressed over its filled 260-bar window with the delivery tick's date.

**Fix:** `phase1.features.forex_fill_forward_bars: "flat"`: a fill-forward bar is flattened (`data_pipeline.bar_synthesis.flatten_fill_forward_bar`, the dataset's own definition) before it joins the windows, and forex keeps real-bar-only close and driver histories dated by the bar's end time for the betas. The bar probe now logs Lean's own high / low / `fill_forward` for BT1 to confirm the clone behaviour in the engine.

**Verification:** `tests/test_v600_forex_parity.py` (flattened Lean bars rebuild the dataset's filled calendar; the ATR after a weekend equals the dataset's only with flat bars; the live betas equal `train.build_cross_asset_sensitivity_features` on every row to 1e-9).

### 178. Crypto and forex cross-asset features read a correlation window one bar longer than the dataset's; the TLT date is not the topology cache (V6.0.0)

**Severity:** 5/10 · **Status:** 🟢 `fixed` (BT1 reconciliation: ETHUSD 1 of 170 dates, BTCUSD, XOM, NVDA, TLT 0, against 58% for ETHUSD's momentum rank in BT2)

**Problem:** BT2 reconciliation: ETHUSD `cs_momentum_rank_20` diverged on 58% of dates, `topology_correlation_strength` on 51%, the regime scores on 14%. The dataset row of a crypto/forex bar of day D sees the bars that closed before it (key D + 1.0: equity through D, crypto through D - 1); live builds exactly that at the symbol's own midnight tick, but re-scored the symbol on the next equity tick (key D + 1.5) with one more crypto bar in the window. The topology cache (#36) is not involved: it reuses only the SMACOF embedding, never `correlation_strength`, `top_peer_returns` or the risk label (pinned by a test over 15 bars); BT2's TLT diverged on 1 of 210 dates (2 of 53 features), XOM and NVDA on 1 of 210, inside R-PARITY's 10%.

**Fix:** `phase1.features.late_bar_cross_asset: "own_tick"`: `features.cross_asset_timing.LateBarCrossAssetCache` keeps the topology node and momentum map a crypto/forex symbol had at its own tick and the equity-tick re-score uses them; `--reconcile-features` then compares those payload features with the previous dataset row.

**Verification:** `tests/test_v600_late_bar_cross_asset.py`, `tests/test_market_topology.py` (cache never changes the model-input fields).

### 179. Main book: one change beats its costs, a slower book (R-BOOK, branch B, ungated execution-calibrated book) (V6.0.0)

**Severity:** 7/10 · **Status:** 🟡 `partial` (decided by rule; BT1 is the Lean check and R-POSTURE sizes the book from it)

**Problem:** the pooled rank IC of +0.05 does not pay a top-6/bottom-6 book's costs (BT2 main members +$1,184 net of fees over 3.25 years). **Result** (`scripts/book_variant_research.py`, each change alone, ungated net Sharpe validation / backtest): current -0.06 / -0.88; **B1 rebalance 20 bars + max hold 40: +0.42 / +0.42 (as-live +0.10 / +0.11)**; hysteresis 0.10 -0.47 / -1.13, 0.15 -1.84 / +0.07; rank_20d only -0.43 / -0.25; class slots (5/5 + crypto 1/1) -1.62 / -1.13, (equity 6/6) -0.45 / -0.22; 4/4 names -0.92 / +0.52, 10/10 -1.17 / -0.32; sector-neutral head -0.13 / +0.19; residual head -0.58 / +0.89 (both fail validation); the 60-day head (3 seeds, `rank_60d` validation IC +0.031 / +0.017 / -0.006, promotion gate `not_promotable` on every seed) -0.08 / -0.73 and cannot be adopted (R-HEAD). Only B1 passes R-BOOK (backtest gain >= +0.10, validation not worse than 0.02, positive on both splits, drawdown within 1 pp); the greedy combination finds nothing to add. The holdout (seen): ungated -1.69 -> +0.05, as-live -0.97 -> -0.28. About 12 variants were scored on two splits, so this is a rule-picked improvement, not an estimated edge; BT1 decides.

**Fix:** `portfolio_book.rebalance_every_bars` 10 -> 20 and `exits.max_holding_bars` 20 -> 40 (the `aggressive` preset follows). The rest of the config is unchanged.

### 180. Crypto fees: limit exits, the passive-but-filled offset, a route-aware fee and smaller graduates (R-CRYPTO winner C5) (V6.0.0)

**Severity:** 4/10 · **Status:** 🟡 `partial` (decided by rule, corrected by BT1's fee evidence; BT2 reads the realised fee per fill again)

**Problem:** BT2 paid $1,131 of fees on $775 of gross crypto P&L; from the order events the 109 limit fills (entries) cost 60 bps, the 114 market fills (every exit, every timeout fallback) 80 bps. Limit entries were already on; only the exits were market orders.

**Result** (calibrated simulator, crypto-component net / total-book backtest Sharpe, validation | backtest): C0 current -154 / +150 bp NAV; C1 + limit exits (fill rate 0.88 at offset 1.0, 3 bars) -176 / +158; C2 + the best sweep point (offset 0.0, 5 bars: fill rate 0.994) -175 / +159; C3 graduates off -287 / +213 (validation clearly worse); C4 graduates 0.5% / 2.5% -137 / +148; **C5 = C2 + C4: -133 / +155, total backtest Sharpe -0.363 vs -0.354 (clause: not worse than 0.05)**. Validation crypto gross is negative (-124 bp): the venue fee is not the whole problem, the pairs have no edge, which the smaller graduate cap reflects.

**Fix:** `limit_orders.exit_asset_classes ["crypto"]` (the model's sell, the rotation and the age exit rest as limit orders via `execution.order_gate.resolve_exit_order_route`; a trailing stop, the sleeve guard and the kill switch always go to market), `unfilled_timeout_bars_by_class {crypto: 5}` (equities keep 3; the research's per-class offset 0.0 was **reverted after BT1**: Lean charges a limit at the last close as a taker, 70.9 bps on 111 fills against BT2's 60.1 at the global offset 1.0, #185), `fee_by_type.crypto.route_aware` (maker 60 / taker 80 bps, entry fill rate 0.973 from BT2, exit 0.90 from the offset-1.0 / 5-bar sweep; the net-edge gate now prices 61.3 bps per side instead of 80), graduates capped at 0.5% per name / 2.5% class (BTCUSD, LTCUSD exempt). Whether Coinbase fees apply live depends on the configured brokerage (see the report).

**Verification:** `tests/test_main_wiring.py` (limit exits, per-class offset / timeout, risk exits stay market), `test_order_gate.py`, `test_cost_model.py`, `test_crypto_fee_research.py`.

### 181. Forex sleeve dropped by rule R-FX6 (V6.0.0)

**Severity:** 3/10 · **Status:** 🟢 `fixed` (decided by rule; BT1 made zero forex orders)

**Problem:** BT2: -$188 gross, -$544 net over 3.25 years at the minimum cap (the $2 IB minimum on ~$1.8k tickets is ~11 bps a fill). **Result:** 48 variants (carry / carry+momentum x gross 0.10-0.30 x 1-2 names per side x rebalance 20/40 x deadband $1k/$2.5k) on the calibrated cost model: the best by validation (carry, 2 per side, gross 0.30: validation +0.45) has backtest Sharpe -0.17, and **none of the 48 is positive on the backtest split** (32 are positive over the whole 2023-07..2026-09 span); carry's within-class rank IC is +0.070 (t 0.73) validation, +0.052 (t 0.57) backtest. **R-FX6: drop.**

**Fix:** `forex_risk.enabled`, `forex_sleeve.enabled` and `sleeve_guards.forex.enabled` false (`forex_risk` is the clean switch: it also takes the pairs out of the book pool and liquidates held ones). Forex bars still feed the cross-asset features; the sleeve settings stay in the file for a later re-evaluation.

### 182. Latency: three measured cuts, two rejected by estimate (V6.0.0)

**Severity:** 4/10 · **Status:** 🟡 `partial` (stage numbers measured offline, equality pinned; BT1's timing probe reads the end-to-end effect)

**Measured with the new `scripts/profile_main_tick.py`** (the real `main.py` against the permissive stub, 92 symbols, CPU time, fastest of 4): `_build_model_input` 2.75 -> **1.8 ms per call (-35%)**: the sensitivity betas were 55% of it, rebuilt from lists on every call (`features.sensitivity_features_vector`, float64 arrays, 1.54 -> 0.60 ms per symbol; equal to the list path to rounding level, OLS 4.8e-13 relative); the as-of lookups re-sorted a 8,000-row FRED series on every call (`data_pipeline.fred_backfill._sorted_index`, one cached sorted index, identical values); the regime experts and their multitask heads for every pending symbol in one pass (`inference.exported_model.run_exported_models_across_symbols`, `phase_v2.inference_parallelism.batch_experts_across_symbols` now on): 79 -> 16 ms per tick for 92 symbols, **bit-identical outputs** (max abs diff 0.0 on the installed experts).

**Rejected (R-LAT):** re-using the own-tick prediction for crypto/forex on the equity tick would skip ~20% of the calls, but the equity-tick features legitimately differ (FRED as-of date, the real-drawdown regime) so the decisions would not be identical; caching the own-window indicator block per fresh bar saves ~12% at most of the stage for a 300-line refactor of the feature path (below the 10% bar once the cuts above are in).

**Verification:** `tests/test_v600_sensitivity_vector.py`, `test_v600_across_symbols.py`, `test_fred_backfill.py`, `test_v600_config_decisions.py`.

### 183. Datasets and the backups: `full_dataset.csv` is the V5.8.0 window again, and the ETH/LTC vintage rows differ only in dead rows (V6.0.0)

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `ml/datasets/full_dataset.csv` and the three split files were the pre-V5.8.0 window, so `--audit-fills`, the rank-book run and a dozen scripts read stale rows; the Codespace-built candidate datasets carried ETHUSD / LTCUSD rows from 2017-09 and 2018-04 that differed from local. **Fix:** `scripts/build_holdout_dataset.py --full-splits --write-split-files` builds all four splits with the active scaler (never refit) on the Codespace: 181,837 train / 39,197 validation / 55,042 backtest / 34,510 holdout rows (4,160 purged), 104 tickers. Against the candidate evaluation dataset V5.8.0 scored on (validation + backtest): **zero differing feature cells** (only target columns that need later dates differ, 0 split mismatches); against V5.8.0's training `full_dataset.csv`, built before the Codespace's ETHUSD / LTCUSD zips were aligned with the local files, 98 columns differ, ETHUSD and LTCUSD most and the cross-asset features through them (topology strength, momentum rank, sensitivities): the rebuild is the canonical one and removes the vintage nit; the two ETH rows that exist only in the old file are 2017-09-04 and 2017-11-09 (train, pre-listing). The local and Codespace ETH/LTC zip digests are identical. `aq clean ml --apply` (70 items, 13.67 GB), `ml/_backup_pre_v580/`, `data_backup_pre_v580/` and `data_holdout/` are deleted with the installed-model manifest unchanged (47 files), and `scripts/refresh_universe_availability.py` set every asset's `available_to` to 2026-09-30. `--audit-fills` and the rank-book runs take `--dataset`.

### 184. #104 teardown: the trivial algorithm hangs on the newest Lean image too (V6.0.0)

**Severity:** 3/10 · **Status:** 🔴 `closed` (environmental; no engine swap, evidence extended)

**Result:** `scripts/lean_teardown_smoke` (SPY daily, 15 lines, nothing of this project) ran on `quantconnect/lean:17900` (built 2026-07-07) and on `quantconnect/lean:latest` (sha256:6d347912e008..., built 2026-10-12, Python 3.11.14): both log `PythonInitializer.Shutdown(): calling engine shutdown...` then `Operation timed out - 0.1666 minutes` and `Failed to shutdown python` ten seconds later, after the results were written (`ml/evaluation/v600/teardown_smoke_*_engine_log.txt`). The pin stays (changing the engine would confound BT1's attribution and the crypto fee model).

### 185. BT1 (Lean, 2023-07-01..2026-09-30, the V6 config): +6.72% net, Sharpe +0.55 without the risk-free rate, drawdown 5.40% (V6.0.0)

**Severity:** 6/10 · **Status:** 🟡 `partial` (measured and written up; R-LEAN9's drawdown clause fails by 0.4 pp and BT2 confirms the corrected crypto config)

**Result** (`backtests/2026-10-15_14-55-24`, config sha256 `c168ca25a625a860...`, models unchanged since V5.8.0; the first attempt, `backtests_invalid/2026-10-15_14-36-29_bt1_benchmark_hourly_feed`, was killed in its first minutes because the engine log still showed `Adding internal benchmark data feed SPY,...,Hour`, see #175, and is not counted): 125 minutes (the PC was busy; wall times are not comparable with V5.8.0's 48-53 minutes), 611 orders, fees $1,061 (BT2: $2,195 over the same span), net **+$6,724 (+6.72%)**, Sharpe -1.55 with Lean's risk-free rate and **+0.55 without**, max drawdown 5.40%. By stretch (`--audit-backtest --period`): backtest 2023-07..2025-06 -1.52% (drawdown 5.27%, Sharpe -0.20, the same dates V5.8.0's BT2 made +1.04%), holdout 2025-07..2026-09 (seen) +8.37% (drawdown 2.08%, Sharpe +1.61). The Lean benchmark is real now: 813 distinct values (SPY 426 -> 763), Alpha -0.046, Beta 0.062, Information Ratio -1.06, Tracking Error 0.119 are meaningful for the first time. P&L by component, net of fees (`--attribute-lean`, reconciles to the cent): main-book equities +$2,885 (178 fills; backtest stretch -$3,027, holdout stretch +$5,912), legacy signal +$2,148, crypto core +$1,699, crypto graduates +$111, legacy crypto -$91, bonds -$28, **forex 0 fills**.

**R-LEAN9 (BT1):** engine log clean (0 `inference failed`, `sequence_served=114283`, 0 multitask fallbacks, no 2050 start, no numerical-precision line, 0 failed data requests, no `/hour/` request: ok); benchmark moves (ok); sleeves inside their guards (ok); R-PARITY on XOM / NVDA / TLT 0 of 170 dates, BTCUSD 0, ETHUSD 1 (0.6%), EURUSD and GBPJPY 15 (8.8%; the carry convention and the Sunday fill-forward Monday were reconciler artefacts, now handled) - ok, leads 4 and 5 closed; **drawdown <= 5%: 5.40% - fails.** The breach sits in the backtest stretch where the main book lost $3.0k (V5.8.0's BT2 made +$1.5k there); over the whole span the V6 main book earned $2.9k against $1.2k. The offline prediction written before the run (calibrated book, whole span: -3.1% / Sharpe -0.26, ungated +2.0%) had daily correlation **0.51** with Lean's main-book component (0.65 on the backtest stretch, 0.29 on the holdout stretch) and the wrong sign on the holdout stretch (-3.1% a year against +5.7%): the simulator tracks day-to-day moves but not the level, so branch B stands (#176).

**R-POSTURE:** M (main-book members' P&L net of fees: equities + crypto core + graduates) = +$4,695 > 0 and S = +0.55 >= +0.30: the main book's `gross_exposure_cap` stays 1.0. Live capital stays zero (paper only). **R-CRYPTO's Lean check fails:** the 111 crypto limit fills paid 70.9 bps (BT2's paid 60.1), the 42 market fills 80 bps, 72.8 bps overall against the <= 70 bound. The winner's offset 0.0 puts a limit at the last close, which Lean's Coinbase model charges as a taker when it is marketable; the research priced every filled limit as maker. The crypto offset is back at the global 1.0 (a limit half a spread away is a maker fill), the exit fill rate in the route-aware fee is 0.90 (the sweep's offset 1.0 / 5 bars) and BT2 confirms.

**Latency:** the probe's per-stage means (build_model_input 8.5 ms x 150,659, inference 246 ms, topology 438 ms) are 2-3x V5.8.0's on every stage including ones this release did not touch, so the busy host explains them; the stage gains of #182 stand on the microbenchmarks.

**Verification:** `ml/evaluation/v600/attribution_bt1_v600.json`, `backtest_audit_bt1.json`, `reconcile_features_bt1.txt`, `fill_price_audit_bt1.json` (dataset open equals the zip open on every traded date), `bt1_book_reconcile.txt`.

### 186. BT2 (Lean, same span, the corrected crypto config): +5.28% net, crypto fees halved, two V6 runs show how far one small change moves a Lean path (V6.0.0)

**Severity:** 6/10 · **Status:** 🟢 `fixed` (measured and written up; R-LEAN9's BT2 consistency clause and the drawdown clause fail, reported as measured)

**Result** (`backtests/2026-10-15_17-29-50`, config sha256 `a28dbebed6e3a28e...` plus the window override, probes off, models unchanged): 612 orders, fees $963, net **+$5,277 (+5.28%)**, Sharpe -1.67 with Lean's risk-free rate and **+0.44 without**, drawdown 5.50%; backtest stretch -1.63% (drawdown 5.40%), holdout stretch (seen) +7.02% (drawdown 3.27%). The engine log is clean (0 `inference failed`, `sequence_served=114283`, no hourly benchmark feed, 813 distinct benchmark values, no 2050 start). Reconciliation as in BT1 (XOM / NVDA / TLT / BTCUSD 0 of 170 dates, ETHUSD 1, EURUSD / GBPJPY 15). **Crypto fees:** 109 limit fills at 60.0 bps (the offset-1.0 maker rate is back), 44 market fills at 80, **63.9 bps per fill overall against 72.8 in BT1 and 70 in V5.8.0's BT2**, fees $546 against $1,131: R-CRYPTO's Lean check (<= 70) holds; crypto net +$2,292 (core +$2,228, graduates +$205, legacy -$141) where V5.8.0's BT2 lost $356.

**Same span, three configs** (net, drawdown, Sharpe without the risk-free rate; main-book equities net / legacy signal / crypto core): V5.8.0 BT2 -0.58%, 4.3%, -0.03; +$990 gross equity, crypto -$356 net. V6 BT1 +6.72%, 5.40%, +0.55; +$2,885 / +$2,148 / +$1,699. V6 BT2 +5.28%, 5.50%, +0.44; +$905 / +$2,086 / +$2,228. Backtest stretch / holdout stretch: V5.8.0 +1.04% / -1.61%, BT1 -1.52% / +8.37%, BT2 -1.63% / +7.02%.

**Reading:** the two V6 runs differ only in the crypto order route, yet the main-book equities earned $2.9k in one and $0.9k in the other (the holdout stretch $5.9k against $4.0k): a different crypto P&L moves the whole-portfolio return that the kill switch reads, which freezes or releases the equity book on different days (the book replay is identical in both runs: 37 engaged rebalances, 0.80 name overlap with the offline replay, raw scores 0.0069 apart, so the selections did not change, only which entries and resizes were frozen). The backtest-stretch main-book loss is the same in both (-$3.03k, -$3.09k) against +$1.46k for the V5.8.0 config: the slower book (R-BOOK B1) lost in Lean on the very stretch it was selected on (offline ungated: +0.42 Sharpe) and won on the holdout stretch it was never selected on. So R-LEAN9 BT2's consistency clause (main book within +-35% of BT1, the rest within +-20%) fails (-69% main book, crypto core +31%), the drawdown limit fails in both runs (5.40%, 5.50%, the breach is the backtest stretch's main-book loss), and one Lean path cannot rank configs at this precision. The whole-span gain from V5.8.0 to V6 (-0.6% to +5.3..6.7%) comes from the holdout stretch, a window already seen; no edge is demonstrated out of sample, and the posture stays paper only with live capital zero. The shipped config is the BT2 one; reverting B1 is the rule-driven option for the drawdown clause and is left to the owner (it cannot be tested: both Lean runs are used).

**Verification:** `ml/evaluation/v600/attribution_bt2_v600.json`, `backtest_audit_bt2.json`, `reconcile_features_bt2.txt`, `bt2_book_reconcile.txt`.

