# Problems

Bugs and infrastructure issues found in this codebase, how they were fixed
(or why they're still open), a severity rating (1 = cosmetic, 10 = critical
data-loss/safety issue), and a status. Ordered by entry number (oldest
first); note entries #73-76 don't exist (skipped in the original numbering)
and entry #88 appears twice (`88a` and `88`) from an earlier numbering
mistake — both are kept as-is rather than renumbered, to avoid breaking
cross-references elsewhere in this repo (Changelog.md, memory files, etc.).

**Status legend:**
- 🟢 `fixed` — code changed (or a final decision made) and verified or
  self-evidently complete; nothing meaningfully pending.
- 🟡 `partial` — a fix shipped but verification is incomplete/pending
  (e.g. still needs a real Lean backtest or IB connection to confirm), or
  a real known caveat/open sub-issue remains.
- 🔴 `closed` — no code fix was applied: declined/won't-fix, a non-goal,
  moot with no action taken, or superseded without ever being fixed on
  its own terms.

Every entry follows: **Problem** (what was wrong) → **Fix** (what
changed) → **Verification** (how it was confirmed — real Lean backtest,
unit tests, or manual code review; this codebase has a standing
convention that `main.py` itself has zero direct unit test coverage, so
many Lean-adapter fixes are verified only by manual review or a real
backtest, never a unit test).

---

### 88a. Lean CLI's generated Windows dependency mount was unreliable, and startup imported the training stack

**Severity:** 6/10 · **Status:** 🟢 `fixed` (V5.1.11)

**Problem:** On some Windows Docker Desktop hosts, Lean CLI's generated temp `requirements.txt` mount could be rejected by Docker even though ordinary project files were readable. Separately, `main.py` importing `performance` at module scope pulled in the full training/PyTorch import graph during Lean's 90-second startup isolator window.

**Fix:** `aq backtest` now builds a cached local image with Redis pre-installed (no generated requirements mount); a Windows wrapper grants Docker read access to Lean-created temp dirs; `main.py` now imports `evaluate_all_triggers` only inside the in-memory dashboard view. A follow-up review found `requirements/lean-runtime.txt` was missing `httpx` (needed by `data_pipeline.fred_backfill`, added after the last known-good backtest) and added it.

**Verification:**
- Regression tests cover both import/mount boundaries without running a real Lean backtest.
- The `httpx` follow-up fix was flagged as unverified against a real Lean backtest at the time — since resolved by evidence: `httpx` is still in `requirements/lean-runtime.txt`, `fred_backfill` is still imported at module scope, and 4 real Lean backtests have completed successfully since (V5.2.4 through V5.2.7), each exercising this exact import chain.

---

### 1. `experience-worker` crash loop — missing `numpy` dependency

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/observation_metrics.py` imports `numpy`, but `requirements-worker.txt` (backing the `experience-worker` Docker service) never listed it — the container crash-looped with `ModuleNotFoundError`.

**Fix:** Added `numpy>=1.24.0` to `requirements-worker.txt`; applied the same fix proactively to the new trigger-worker's requirements file.

**Verification:**
- Rebuilt and restarted the container; confirmed clean startup via `docker compose logs`.

---

### 2. `Dockerfile.worker` missing `execution/` copy

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/simulated_portfolio.py` imports `execution.order_gate`, but `Dockerfile.worker` never copied `execution/` into the image — a rebuild would have failed with `ModuleNotFoundError`.

**Fix:** Added `COPY execution/ ./execution/`; applied the same pattern proactively to the new `Dockerfile.trigger_worker`.

**Verification:**
- Caught by tracing the import graph before any rebuild was attempted; documented as a standing Docker-copy-list lesson in `development/architecture.md`.

---

### 3. Simulated portfolio/positions snapshot not mode-aware

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** The webui's Positions panel and portfolio summary always read from the real (flat, uninvested) `self.Portfolio` even in `observation` mode, contradicting the already-mode-aware drawdown figure shown next to it.

**Fix:** Added `_snapshot_portfolio_summary()` and made `_snapshot_positions()` mode-aware, reading from `SimulatedPortfolioState` whenever real orders are blocked.

**Verification:**
- Found and confirmed via live screenshot review with the user.

---

### 4. Webui: empty space above Market Scene panel

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** CSS Grid's default `align-items: stretch` padded the shorter left column with blank space to match the taller right column.

**Fix:** Added `items-start` to the outer grid and switched both column wrappers to `flex flex-col gap-4`.

**Verification:**
- Confirmed via live Playwright screenshot review.

---

### 5. Webui: Signal Distribution / Rejected By Reason tables overflow the panel

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Long reason strings forced an HTML `<table>` wider than its CSS Grid track, and Grid's default `min-width: auto` couldn't shrink to contain it, pushing content off-panel.

**Fix:** Replaced the `<table>` with flexbox rows, added `min-w-0` to allow shrinking, and `break-words` on labels.

**Verification:**
- Confirmed via the same live screenshot review as #4.

---

### 6. `aether-grafana` container name collision blocks the real Grafana service

**Severity:** 3/10 · **Status:** 🟢 `fixed` (moot, no code change needed)

**Problem:** An orphaned, unmanaged `aether-grafana` container (port 3000, non-compose volume) would have blocked `docker compose up -d grafana` from creating the real service (same container name).

**Fix:** No action taken — Grafana was removed from the stack entirely in V2-18 (replaced by the React tracing dashboard), so the collision scenario stopped applying.

**Verification:**
- Re-checked 2026-07-04: `docker ps -a` shows no such container and no `grafana` service exists anymore.

---

### 7. ~85GB of orphaned duplicate Lean engine images + stale containers/volumes

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** Two untagged 42.5GB `quantconnect/lean` images, several stale one-off containers, unused pip-cache volumes, and stray/unpinned image tags were accumulating disk space from past Lean CLI/dependency updates.

**Fix:** Removed all confirmed orphans (`docker rmi`/`docker volume rm`) after two verification passes — a first pass missed one image (`650dd8d4063a`) and an unrelated Grafana volume/image, caught and corrected in a follow-up check.

**Verification:**
- Re-verified via `docker images -a`/`docker volume ls` after removal; unrelated Aether-Vault project images/volumes explicitly left untouched.

---

### 8. Bare `pytest` (no path) fails from repo root

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** Bare `pytest` from the repo root also crawled `backtests/*/code/tests/` (each backtest run copies the full algorithm code including tests), causing ~76 duplicate-module-name collection errors.

**Fix:** `pyproject.toml`'s `[tool.pytest.ini_options]` now sets `testpaths = ["tests"]`, so bare `pytest` only collects `tests/`.

**Verification:**
- `README.md`'s documented `pytest tests/` form still works; bare `pytest` now also works correctly.

---

### 9. Total-drawdown trade lock never auto-clears within a run

**Severity:** 4/10 · **Status:** 🟢 `addressed` (manual override, not a default-behavior change)

**Problem:** A total-drawdown breach lock never clears for the rest of a run (unlike the daily-drawdown lock) — a real run's data showed this blocking ~79% of events after one early breach. This is treated as intentional capital-preservation behavior, not a bug to silently patch.

**Fix:** Added `phase_v2.risk.manual_trade_lock_override` (read once per session rollover) plus the `aq trade-lock --on/--off/--auto` CLI command and an auto-clear-on-successful-promotion hook in `retraining/orchestrator.py::promote()`. Default sticky behavior is unchanged.

**Verification:**
- Documented in the Manual Trade-Lock Override Contract (`development/architecture.md`).

---

### 10. `ci.yml`'s `test` job fails on GitHub's Linux runner — root cause found and fixed

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** The first-ever clean-install + bare-`pytest` CI run (unlike every local dev session, which always used an already-populated `.venv`) surfaced three independent, previously-masked problems: a nonexistent PyPI package name in dev requirements, `pytest`'s import-mode not adding the repo root to `sys.path`, and (after those two were fixed) 4 real test failures plus 11 errors — two small reference files (`futures_contract_specs.json`, `sector_mapping.json`) were swallowed by a blanket `.gitignore` rule, one genuine Python 3.11-vs-3.14 float-summation stdlib difference in `empirical_duration_beta()`, and a Lean-backtest test file's skip-guard only checking binary presence rather than a usable Lean Data folder.

**Fix:** Corrected the package name (`lean>=1.0.225`), added `pythonpath = ["."]`, added a `.gitignore` exception + committed the two reference files, changed an exact-zero variance check to a `<1e-12` tolerance, and strengthened the Lean-test skip guard to check for a real Lean Data file.

**Verification:**
- All 4 previously-failed tests plus 3 new regression tests pass locally.
- **Confirmed: the real GitHub Actions run passed** after this fix shipped (user-confirmed).

---

### 11. `_write_state()`'s per-bar throttle was unreachable

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** A dead guard clause meant 7 output files were fully rewritten on every single bar instead of once per timestamp as intended.

**Fix:** Removed the impossible clause (`if ... and signals is None`), restoring the once-per-timestamp cap.

**Verification:**
- Found during a latency audit of `main.py`'s hot path; no behavior change beyond "actually do what the code intended."

---

### 12. `observation_equity_curve.csv` quadratic rewrite (N-per-bar entries + full-file rewrite every bar)

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `mark_to_market()` was called once per symbol per bar (not once per bar), producing `N·B` equity-curve entries instead of `B`; combined with #11's every-bar flush and a full-file CSV rebuild each time, total write cost was `O((bars·symbols)²)`.

**Fix:** `on_data()` now accumulates all symbols' closes and calls `mark_to_market()` once per bar; the CSV writer was replaced with an append-only flush (`_flush_observation_equity_csv()`) tracked by a written-count offset.

**Verification:**
- New unit test asserts one equity-curve entry per multi-symbol `mark_to_market()` call.
- Row-count-equals-bar-count verified via the real Lean backtest integration test's output file.

---

### 13. Per-bar/per-poll `config.json` reads on every session rollover, uncached

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** At Daily resolution the "once per session" rollover check fires every bar, and each firing did a full uncached `open()`+`json.load()` of `config.json` in multiple places (`main.py`, `retraining/worker.py`'s poll loop).

**Fix:** New `execution/config_cache.py::read_cached()`, an mtime-gated cache keyed by `(config_path, loader)`. A first version keyed by path alone caused two different readers on the same file to collide and return the wrong cached value, crashing `_recompute_broker_config()` on bar 1 of a real Lean backtest — caught and fixed by keying on the loader too.

**Verification:**
- New `tests/test_config_cache.py` (including the multi-loader-collision regression).
- Re-confirmed fixed via a real Lean backtest integration test re-run.

---

### 14. Redis push in backtest mode — deliberately left unoptimized

**Severity:** n/a · **Status:** 🟢 `resolved` (confirmed no-op, no code change needed)

**Problem:** `experience/redis_queue.py::push()` does a blocking Redis write every bar even in backtest mode, which could in principle be skipped for a performance win — but an unconfirmed downstream dependency on backtest-mode experience events made skipping it risky.

**Fix:** No code change — the project owner confirmed no downstream process reads backtest-mode experience events from Postgres, closing the open question this entry was tracking.

**Verification:**
- Resolved by direct confirmation from the project owner, not by testing.

---

### 15. `ensure_derived_crypto_daily_series()` silently discarded yfinance-backfilled crypto history on every `train.py` run

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** This function rebuilt derived crypto daily zips (ETHUSD/LTCUSD) via a full-overwrite `ZipFile` write from sparse raw minute data, wiping out 1000+ days of separately yfinance-backfilled history back down to 3-4 real rows every time `train.py` ran.

**Fix:** The function now reads the existing output zip first and merges by date — freshly computed minute-derived rows win only where real minute data exists; every other date survives.

**Verification:**
- New regression test: `test_ensure_derived_crypto_daily_series_merges_with_existing_backfill`.

---

### 16. `main.py::initialize()` exceeded Lean's hard 90-second isolator timeout at 20 assets

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** Loading all model/expert/topology artifacts and deriving ~40 config values inside `initialize()` pushed total isolator-timed cost over Lean's non-configurable 90-second cap once the universe reached 20 assets — every `lean backtest .` attempt failed.

**Fix:** Split `initialize()` into a minimal Lean-critical path (dates/cash/subscriptions/warm-up) plus a new `_ensure_ready()` carrying all artifact/config loading, deferred to the first `on_data()` call (no isolator limit there).

**Verification:**
- Direct disk-log instrumentation (since `self.Debug()` output inside a timed-out `initialize()` is silently lost) confirmed `initialize()` now completes in 1.85s, full isolator window ~51s, safely under the cap.
- Full non-Lean suite (525 tests) stayed green throughout.

---

### 17. Matplotlib font cache rebuilt from scratch on every single `lean backtest .` run

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Lean's own `AlgorithmImports` bridge imports matplotlib, and Lean CLI's ephemeral per-run Docker containers meant the font cache was rebuilt (20-40+ seconds) on every single run, occasionally still exceeding the 90-second isolator cap even after entry #16's fix.

**Fix:** `main.py` sets `MPLCONFIGDIR` to a host-mounted `.matplotlib_cache/` directory (before any other import) so the cache survives across ephemeral containers.

**Verification:**
- Confirmed via two consecutive real Lean runs: cold-cache run showed the rebuild message and ~82s import; warm-cache run showed no rebuild message and ~58s import, zero isolator timeout.

---

### 18. Two structural "never recovers" traps suppressed real backtest trade count to 12 over 3 years

**Severity:** 5/10 · **Status:** 🟢 `addressed` (opt-in statistical bypass, default behavior unchanged)

**Problem:** A one-time mass liquidation crossing the 12% total-drawdown limit froze trading for the remaining 374 days of a 3-year backtest — the sticky lock combined with a `peak_equity` running-max that can never fall meant the lock could never clear on its own. A second, earlier-firing (8%) version of the same trap existed independently in the regime `risk_off` drawdown branch.

**Fix:** New opt-in `phase_v2.backtest.bypass_safety_gates` flag (default `false`, backtest-only) bypasses only these two specific mechanisms; every other gate stays fully active. Live/paper mode is completely unaffected regardless of the flag.

**Verification:**
- Deliberately not wired into `aq trade-lock` (separate, pre-existing meaning) to avoid collision.
- Explicitly documented as scoped to statistical/model-quality backtesting only, never representative of live behavior.

---

### 19. Neural-network webui tab's gating exclusion went stale the moment gating became learnable

**Severity:** 2/10 · **Status:** 🟢 `fixed`

**Problem:** The gating network was hardcoded as excluded from the `/neural-network` webui's network list ("no learned weight matrix") and the 3D scene's render order was hardcoded to exactly 5 names — both became inaccurate once gating gained an optional learned model.

**Fix:** Removed gating from the exclusion list, wired it through the same generic network-summary path as the other models, and added it to the 3D scene's render-order array.

**Verification:**
- Noted as a standing gotcha for future networks: the render-order array is a silent filter that must be updated manually for anything new to appear in the 3D scene.

---

### 20. `Dockerfile.retraining_worker` never copied `risk/`, so `retraining.worker` could not have started

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `retraining/orchestrator.py` imports `risk.manual_override` at module level, but `Dockerfile.retraining_worker`'s `COPY` list never included `risk/` — every container startup would have crashed with `ModuleNotFoundError`.

**Fix:** Added `COPY risk/ ./risk/` (confirmed lightweight, no heavy transitive deps) alongside a new `COPY train_multitask.py .` for the same session's new retraining stage.

**Verification:**
- Found via static import-graph tracing before any rebuild was attempted.
- **The image still needed a rebuild** to actually pick up the fix — not run in this session.

---

### 21. Per-bar model forward-pass count doubled (5 → 11) — measured, not currently a problem

**Severity:** 2/10 · **Status:** 🟢 `measured, not currently a problem`

**Problem:** Adding the multitask/sequence models roughly doubled per-symbol-per-bar forward passes (5 → 11, though batching keeps top-level calls at 5); this had never been measured against any real budget.

**Fix:** No code change — measured via `aq profile --batched`, found ~12ms mean per symbol per bar, negligible against the only real enforced constraint (Lean's 90s `initialize()` isolator cap, unrelated to per-bar cost).

**Verification:**
- 10,000-iteration profiling runs (batched and unbatched) with real exported weights; the sequence encoder's causal convolution flagged as the largest remaining cost and a future optimization candidate.

---

### 22. `tests/test_retraining_worker.py` silently ran real training (subprocess-level hang, up to ~30 minutes per test)

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** 7 of 10 tests were never updated to mock the newer `train_multitask`/`train_sequence` stages, so in any environment with real dataset/scaler artifacts they fell through to genuine subprocess training with up to 30-minute timeouts — easily mistaken for a hang.

**Fix:** Added `patch("retraining.worker.train_multitask")`/`train_sequence` to all 7 affected tests, matching the file's existing mock pattern.

**Verification:**
- The previously-hanging test now completes in ~1.2s; the full 10-test file runs in ~1.2s total.

---

### 23. BTCUSD volume-feed unit discontinuity blew up the sequence model's RMSE 31x

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** BTCUSD's raw volume column jumped ~520,000x on one date (a real Coinbase feed unit-convention change), producing a 5.2-million-percent single-day "return" that passed straight through an unclipped `StandardScaler`, poisoning 30 rows of the sequence model's sliding window and accounting for 66%+ of its entire backtest squared error.

**Fix:** Three layered defenses: clamped `volume_change_1d` to `[-1.0, 20.0]`, winsorized scaler-fit columns before fitting, and clipped scaled values to `±10σ` (persisted to `scaler_stats.json` so `main.py` applies the identical bound at runtime). Also added an automated regression-quality gate so a future blowup is caught without manual investigation.

**Verification:**
- Post-fix: max absolute scaled value across every column is exactly 10.0 (clip firing correctly); retrained sequence model's RMSE/MAE ratio dropped from 31x to 1.59x.

---

### 24. `train.py` never applied Lean's own split/dividend factor files — offline dataset had fake ±74%/+745% "returns"

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `train.py`'s independent raw-zip reader bypassed Lean's own split/dividend adjustment, so real corporate-action dates (e.g. AAPL's 2020 4-for-1 split, USO's reverse split) produced fake ±74%/+745% "returns" in every training label and every feature spanning the split boundary — for every equity with a real split/dividend history. Lean's own live/backtest engine was unaffected; this was purely an offline train/runtime parity gap.

**Fix:** New `train.py::apply_split_adjustments()` reads each equity's real Lean factor file and rescales OHLCV exactly as Lean's own engine does. Also fixed `yfinance_backfill.py` to use `auto_adjust=True` for future-proofing, and added a per-security-type label-outlier guard as defense-in-depth.

**Verification:**
- Verified on the real dataset: AAPL's split-boundary "return" corrected from -74% to a normal ~3.4%; USO's from +745% to ~5.6%.

---

### 25. No quality gate ever existed for regression heads (magnitude/volatility/rank) — only direction MCC was gated

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Only direction models were quality-gated; the regression heads had no gate at all — exactly how entry #23's 31x RMSE blowup shipped silently for an entire session.

**Fix:** New `train.py::assess_regression_quality()`, gating on RMSE/MAE and backtest/train RMSE ratios, wired into both `train_multitask.py` and `train_sequence.py`, surfaced on the `/neural-network` webui page.

**Verification:**
- Mirrors the existing `assess_expert_quality()` shape and gating convention.

---

### 26. `main.py`'s sequence-model runtime buffer size never read the trained model's own `window_size`

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** The runtime buffer size came only from `config.json`, never from the loaded model's own schema — a retrained model with a different window size would silently disable the sequence signal entirely via a shape-mismatch exception, with no error surfaced.

**Fix:** New `resolve_sequence_window_size()` — the trained model's own schema value now wins whenever a schema is loaded, falling back to config only when none exists.

**Verification:**
- Extracted as a pure function specifically so it's unit-testable outside Lean's runtime.

---

### 27. Phase 2's new era/fold-splitting functions crashed on real training runs — assumed datetime input, but the real dataset's `date` column is plain strings

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `split_into_non_overlapping_eras()`/`purged_embargoed_folds()` did Timestamp arithmetic directly on `np.asarray(dates)`, correct only for datetime-typed input — but every real caller passes a stringified date column, crashing on the very first real training run despite passing all unit tests (which used synthetic datetime fixtures).

**Fix:** Both functions (plus an affected caller with the identical bug) now coerce via `pd.to_datetime(np.asarray(dates))`, robust to string/Timestamp/datetime64 input alike.

**Verification:**
- New regression tests use plain string dates and real object-array shapes, not just synthetic datetime fixtures — specifically to prevent this "passes every unit test, fails on first real run" gap from recurring.

---

### 28. Portfolio book's `"short"` signal silently zeroed to no position

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `_build_dynamic_sizing_payload()`'s guard clause only recognized `{"buy", "sell"}`, never updated when `"short"` was introduced as a third valid book signal — every book-selected short position would size to exactly zero, defeating the book's short-selling role. Never observed in practice since the book feature defaults off.

**Fix:** The guard now recognizes `{"buy", "sell", "short"}`.

**Verification:**
- No dedicated new test; covered implicitly by the existing portfolio-book test suite plus any future end-to-end backtest with the book enabled.

---

### 29. Multi-asset-class support (bonds/futures/options + IB) — explicit non-goals

**Severity:** n/a (scope note) · **Status:** 🟢 `fixed` (core multi-asset-class trading is fully implemented; remaining items are permanent non-goals)

**Problem:** Tracked which multi-asset-class gaps remained after the initial architectural pass — options order placement against a resolved contract, real derivatives-macro data, and per-asset-class book slot caps were all originally deferred.

**Fix:** All three resolved in follow-up passes: real option contract order placement, real futures/options derivatives-macro features (offline and live), and an optional `per_asset_class_slots` book-construction parameter (default `None`, byte-identical to prior pooled-ranking behavior).

**Verification:**
- 7 new tests for per-class book slotting (ranking, exclusion, thin-class isolation, confidence-spread gating, backward-compatibility).
- Remaining items (ML-driven multi-leg spread selection, IBC headless TWS login, live IB margin, bulk historical derivatives fetch) are explicit, permanent non-goals blocked on external dependencies this repo doesn't control — tracked in the README's Known Limitations, not as open work here.

---

### 30. `Dockerfile.retraining_worker` missing `data_pipeline/` (and pre-existing: `liquidity/`) copy

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `train.py` gained a new top-level `data_pipeline.fred_backfill` import (real bond yield-curve features) that `Dockerfile.retraining_worker` never copied — plus a pre-existing, separately-discovered gap where `liquidity/` (needed by `train.py` for an earlier feature) was also never copied. Either would crash the container on first real retrain.

**Fix:** Added `COPY data_pipeline/ ./data_pipeline/` and `COPY liquidity/ ./liquidity/`. Superseded shortly after by the July 17 Docker consolidation: `Dockerfile.retraining_worker` no longer exists at all — `docker-compose.yml`'s `retraining-worker` service now builds from the single consolidated `aether-quant-engine:latest` image (`COPY . .`), whose own comment names this entry explicitly as one of the bugs it structurally eliminates.

**Verification:**
- Found via import-graph tracing, same method as #2/#20.
- Confirmed current state directly: `Dockerfile.retraining_worker` is gone, `docker-compose.yml` points `retraining-worker` at the shared consolidated image, and this entire bug class (a per-worker COPY list drifting out of sync with its actual import graph) is now structurally impossible — no rebuild needed.

---

### 31. Infrastructure/latency pass — `aq test` silently ran a real Lean backtest, per-bar inference hot path never profiled, CI Docker builds never cached

**Severity:** 8/10 (aq test) / 6/10 (inference latency) / 4/10 (CI cache) · **Status:** 🟢 `fixed`

**Problem:** `aq test`'s Lean-backtest test file only checked whether the Lean binary was installed, not whether a real (over-an-hour) backtest was actually wanted — every routine `aq test` run silently paid that cost. Separately, the per-bar inference hot path had never been profiled at all, and CI's Docker release builds had no layer caching.

**Fix:** Added an opt-in `lean_backtest` pytest marker (excluded by default, `--lean`/`--full` opt back in), plus new per-subsystem `aq test` flags. Built `scripts/profile_inference.py` (first-ever profiling harness) and found/fixed two real hot-path costs: a Python-loop causal convolution (rewritten to one batched `einsum`) and 4 separate per-expert dispatch calls (batched into one). Added `cache-from`/`cache-to: type=gha` to the release workflow's Docker build step.

**Verification:**
- `pytest --collect-only`: 1132/1143 collected, 11 correctly deselected; full non-Lean run dropped from over an hour to ~73s-4min.
- Measured: 448.4s → 290.6s (-35.2%) on a 10,000-iteration real-weight profiling workload.
- 200-trial fuzz-tested parity between the old loop and the new batched conv1d against the original logic.

---

### 32. Latency deep-dive follow-up — weight-array/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension attempt

**Severity:** n/a (optimization pass) · **Status:** 🟢 `fixed`

**Problem:** Re-profiling after #31 found `numpy.asarray()` conversions of the same static, JSON-loaded model weights (re-converted from scratch on every single bar) as the new single largest remaining cost.

**Fix:** New `convert_state_dict_arrays()` converts weights to ndarrays once at load time (zero API/behavior change downstream); new batched-stack caching precomputes stacked expert weight arrays once in `_ensure_ready()`. Also added the `aq profile` CLI command, an opt-in per-symbol multiprocessing path (default off, falls back to sequential on any failure), and a working C++/pybind11 extension (`cpp_inference_ext`) accelerating the batched linear layer.

**Verification:**
- Measured: 448.4s → 48.4s (-89.2%) on the same workload; mean per-symbol-bar latency 44.8ms → 4.83ms.
- 14 new parity tests proving the cached path is bit-identical to uncached.
- C++ extension measured a further modest, consistent (if noisy) speedup across two paired comparisons; a real naming-collision bug (source dir shadowing the built module) and a wrong-Python-environment install were both caught and fixed during verification, not after.
- Real per-symbol multiprocessing's actual win/loss is explicitly left to a real Lean backtest — not attempted with the flag enabled this pass.

---

### 33. Execution/risk realism pass — real `SlippageModel` wired to fills

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `build_liquidity_decision()` already computed a real spread+impact cost estimate every bar, but it went nowhere — no Lean security had a `SlippageModel` attached, and the simulated-fill path always used a hardcoded zero slippage. Every historical backtest/observation-mode run had systematically too-good fills.

**Fix:** New pure `slippage_amount()`/`resolve_slippage_bps()`/`resolve_fill_slippage()` functions in `execution/order_gate.py`, threaded into both the real Lean fill path (a new `_LiquidityAwareSlippageModel` adapter) and the simulated-fill path. The cost-estimate source and safety clamp were later made config-configurable rather than hardcoded.

**Verification:**
- 12+13 new tests across `test_order_gate.py`/`test_simulated_portfolio.py`, including default-vs-explicit-zero parity.
- The Lean-side adapter itself isn't unit-testable in isolation (same `main.py`-outside-Lean constraint as elsewhere) — all real logic lives in the tested pure functions.

---

### 34. Real limit-order support — every tradable asset class, config-gated

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` (V5.3.1, #96; `PartiallyFilled` staying unobserved is a permanent, honest caveat — not a blocker, see below)

**Problem:** Every real order was an all-or-nothing `MarketOrder()`/`SetHoldings()` market fill across all 5 asset-class call sites, with no limit-order alternative.

**Fix:** New config-gated (`phase_v2.limit_orders`) real `LimitOrder()` support for all 5 asset classes: a shared `_try_submit_limit_order()` helper, a real `on_order_event()` fill callback, per-asset-class timeout/fallback-to-market handling. Caught and fixed a futures quantity-sign bug and an option contract-vs-chain-symbol bookkeeping bug during implementation.

**Verification:**
- 12 pure-function tests + 4 CLI reachability tests.
- Confirmed firing in a real backtest (2026-07-20, #54) — a real `LimitPrice was rounded` log line.
- V5.2.8: scanned 33 real `order-events.json` files. Statuses observed: `{submitted, filled, canceled, cancelPending, invalid}` — `cancelPending` always pairs 1:1 with `canceled` (e.g. 644/620/23/23), confirmed genuine unfilled-timeout cancels. `classify_order_status()` now classifies `"CancelPending"` explicitly (precision fix, no behavior change). `PartiallyFilled` never once appeared — a permanent, honest caveat.
- V5.3.1 (#96): confirmed `enabled: true` by default all along (this entry's own text above was stale — corrected in the inline docs, left here as historical record); evidence widened to 45 files, same pattern holds. `PartiallyFilled`'s downstream handling now directly unit-tested via two extracted pure functions. Two new offline diagnostic tools shipped.
- **V5.3.1 real backtest confirmation (2026-08-14, #98):** the extracted pure-function refactor (`should_clear_pending_limit_order()`/`resolve_limit_order_timeout_action()`) was live-exercised for the first time — real order-events show the identical `cancelPending`/`canceled` 12/12 pairing as every prior run, zero regressions from the refactor. `PartiallyFilled` still never appeared (permanent caveat, not a defect — Lean's own fill granularity at Daily resolution makes true partials rare/absent by construction). Marking this entry green.

---

### 35. Disabling an asset class never liquidated already-open positions

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Flipping `phase_v2.futures_risk.enabled`/`options_risk.enabled` to `false` mid-run correctly zeroed new position *sizing* but never touched an already-open position from before the flag flipped — the signal-derivation logic has no awareness of these flags, so the position sat untouched indefinitely, silently failing every bar.

**Fix:** New pure `resolve_asset_class_enabled()`/`should_liquidate_disabled_asset_class_position()` functions plus a new per-bar sweep (`_liquidate_positions_for_disabled_asset_classes()`) that liquidates real or simulated positions for any now-disabled asset class. Equity/crypto/bond have no such flag and are unaffected by construction.

**Verification:**
- Full truth-table tests for both pure functions; parity test confirming the new simulated-exit path matches calling `exit()` directly.
- One item flagged unverified until a real backtest: reading `Portfolio[...].Invested` at a new, earlier point in the bar's execution order.

---

### 36. Latency profiling extended beyond inference — `build_market_topology()` found to be a much larger per-bar cost than the entire inference step

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified`

**Problem:** Every per-bar subsystem besides inference (regime, topology, liquidity, gating, analyzer, indicators) had never been profiled. `build_market_topology()` turned out to cost ~500-600ms per call — comparable to or larger than the entire per-symbol inference total across the whole universe — and is called once per bar, not per symbol.

**Fix:** New `scripts/profile_subsystems.py` harness plus `aq profile --<subsystem>` flags. A follow-up shipped a real fix: `build_market_topology()` gained an opt-in (`phase_v2.topology.cache_enabled`, default off) correlation-stability cache that skips the expensive embedding step entirely when pairwise correlations haven't moved beyond a tolerance since the prior bar; a later update added a self-relative percentile-based tolerance mode as an alternative to guessing a fixed threshold.

**Verification:**
- New tests directly proving zero embedding calls fire when correlations are provably unchanged (via mocking), plus tolerance-exceeded/universe-changed/missing-state fallback cases.
- Confirmed running cleanly across a full real 2019-2021 backtest (2026-07-20, see #54) with no per-bar cost issue surfacing.
- **Honest caveat preserved:** whether the cache's precondition (correlation stability) holds often enough on *real* market data to be worth enabling was never established from synthetic data alone — left off by default pending a dedicated real-data calibration session.

---

### 37. Inference tail latency (p99 3-5x p50) — investigated and fixed

**Severity:** 4/10 · **Status:** 🟢 `fixed and verified`

**Problem:** No prior investigation existed into *why* the inference hot path's p99 routinely ran 3-5x its p50 — only the fact that it did (from #32) was known. A separately-found stale on-disk profiling output file also showed misleadingly bad numbers, unclear if that was a regression.

**Fix:** Reran the profiling harness multiple times and confirmed the stale-file discrepancy was a stale/unrelated local run, not a regression. Added iteration-bucketing (ruled out a cold-start/warmup cause) and a `--no-gc` flag, which isolated real, reproduced GC-pause contribution to worst-case (max) tail latency specifically. A follow-up shipped `gc.freeze()` after model load, config-gated off pending real-backtest validation of its interaction with Lean's .NET/Python interop GC boundary.

**Verification:**
- Two paired GC-on/GC-off runs showed max latency dropping 66-95% with GC disabled, p50 unaffected (confirming a tail-only effect, not a general speedup).
- `gc.freeze()` confirmed running cleanly across a full real backtest (2026-07-20, see #54) with the flag on and no interop crash.

---

### 38. 2-leg vertical spread selection for options — explicit scope-in of a previously-non-goal feature

**Severity:** n/a (feature scope-in) · **Status:** 🟡 `partial`

**Problem:** Multi-leg options spread selection was previously an explicit non-goal (entry #29); this pass closes the minimal 2-leg vertical-spread slice of that gap.

**Fix:** New `select_vertical_spread_legs()`/`build_vertical_spread_position_sizing()` (net-vega sized), wired through `risk/asset_class_router.py` and a new `_apply_option_spread_order()` using Lean's own `OptionStrategies` atomic combo-order primitive (previously completely unused in this codebase). Two real bugs (a field-existence check ordering issue, and an early draft that would have broken option orders entirely for the spread case) were caught and fixed during implementation, not after.

**Verification:**
- 20 new tests for leg selection/sizing/degrade paths, plus a critical zero-behavior-change parity test for the existing single-leg path.
- **Real-backtest verification is still genuinely open** — no option/future asset is configured in the universe yet, so this feature has never actually been exercised against real Lean order placement, margin, or partial-fill behavior.

---

### 39. Final pre-backtest bug sweep — 4 fixes found and fixed before this project's first real `lean backtest .` run

**Severity:** 6/10 (test-harness bug) / 5/10 (liquidity threshold collision) / 3/10 (limit-order timeout) / 2/10 (book-slot crash risk) · **Status:** 🟢 `fixed`

**Problem:** A dedicated pre-backtest sweep of the trading-critical path found: (1) a wrong dict-key path in the Lean coverage test that would have silently failed 3 real assertions regardless of backtest correctness, (2) two liquidity thresholds that had drifted to the same value, silently collapsing a two-tier gate to one, (3) a limit-order timeout handler that contradicted its own dependency's documented "unknown status = still pending" contract, (4) no shape validation on the optional per-asset-class book-slot config, risking an unpack-crash on malformed input.

**Fix:** Fixed the test's key path; restored `thin < high_impact` threshold ordering; changed the timeout handler's condition to only pop-without-cancel on genuinely terminal statuses; added a new `normalize_per_asset_class_slots()` pure validator that degrades gracefully on malformed entries.

**Verification:**
- 6 new tests for the slot validator; the other three fixes verified via direct code inspection/config check (pre-real-backtest, by design — that's the point of this entry).
- Full suite green after all four fixes.

---

### 40. `aq backtest` silently re-pulled the ~42.5GB Lean engine image on every run

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `lean backtest .` resolved the mutable `quantconnect/lean:latest` tag with no pin — any time QuantConnect moved that tag, even a machine with the full 42.5GB image already cached would re-trigger a real re-pull, indefinitely, on every clone and every subsequent run.

**Fix:** Pinned to an immutable numbered build tag (`quantconnect/lean:17900`) by default, always passed explicitly to `lean backtest .`; a new `aq backtest --image <other>` flag allows deliberate opt-in to a newer build.

**Verification:**
- New/updated tests confirm the pinned image is used by default and the override flag works.
- Documented in the README's Getting Started section.

---

### 41. First real backtest: only 14 trades, none ever closed

**Severity:** 6/10 (blocks a statistically meaningful backtest) · **Status:** 🟢 `fixed` (superseded by #43)

**Problem:** The first real Lean backtest produced only 14 orders, all openings, zero closes — the model's `probability_up` output clustered tightly around 0.46-0.49 while the buy/sell thresholds sat at 0.50/0.42, so almost nothing crossed either line. A soft `max_active_positions` cap (same-bar overshoot from counting only already-filled positions) was also found as a secondary issue.

**Fix:** No fix applied under this entry — the threshold-tightening lever it proposed was diagnosed but never actually shipped. Entry #43 found the real causes were structural (position-cap overshoot, risk vetoes blocking exits, a neutered circuit breaker, no exit mechanism) and a training-pipeline defect, and pivoted trading to the `rank_20d`/`portfolio_book` signal entirely instead.

**Verification:**
- Diagnosis only, confirmed against real output files (`state.json`, order-events, logs) from the actual backtest run.

---

### 42. Pre-live security review — broker/API credentials could be published; DB exposed to the LAN behind a repo-published password

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** A dedicated pre-live security pass found: `lean.json`'s documented runbook instructed hand-editing real IB credentials directly into a git-tracked file; `.dockerignore` didn't exclude secret files from the published Docker image; Postgres/Redis ports were published to `0.0.0.0` (LAN-reachable) behind a password published in this public repo; and nothing structurally prevented a future secret commit.

**Fix:** Added a credential render step (`aq render-lean-config`) that overlays real secrets from a gitignored `.env.live` onto a gitignored `lean.live.json`, leaving the tracked `lean.json` always empty; mirrored the secret list into `.dockerignore` (catching a second instance of the same bug in the fix's own new `lean.live.json` file); bound DB/Redis ports to `127.0.0.1` plus a fail-closed live-mode guard against the default password; added `aq secrets-check` and an opt-in pre-commit hook.

**Verification:**
- New `tests/test_dockerignore_secrets.py` evaluates real Docker pattern semantics, not just literal line-grep.
- Confirmed no secret exists anywhere in git history; no deserialization-RCE surface found.
- A deferred item (dedicated audit logging) was later closed too — see #44's audit-log update.

---

### 43. Full pre-live model overhaul: trading-logic bugs + training-pipeline bugs, pivot to the one significant signal

**Severity:** 9/10 · **Status:** 🟢 `fixed` (see #52/#54)

**Problem:** A second backtest after #41's threshold recalibration produced bit-identical results to the pre-fix run (same 14 trades, same profit) — the calibration change had zero effect on actual trades. Root causes spanned trading logic (soft position-cap overshoot, sell-vetoing risk logic, a sell threshold ~10σ from live output, a neutered drawdown breaker, no stop-loss/trailing/max-holding-age exit) and training (untrained epoch-1 checkpoints from broken early stopping, degenerate threshold search, MoE blend diluting skill to 0.5, no skill-floor gates, 35/85 static one-hot inputs, ~52-row crypto training, and the trading path ignoring `rank_20d`/`rank_5d` — the only statistically significant signal in the codebase).

**Fix:** Rewrote early-stopping (`min_best_epoch` floor), non-degenerate threshold-search bounds, unified asset-context columns, removed dead features, raised `min_training_rows`/skill-floor gates, zeroed no-skill experts, wired `portfolio_book` to trade `rank_20d` directly, added an exit-veto bypass, non-model safety exits (max holding age + trailing stop), an adaptive sell band, a same-bar position-cap fix, and re-armed the drawdown breaker. Also fixed a crypto/`InteractiveBrokersFeeModel` crash.

**Verification:**
- Real backtest (2026-07-17): 653 orders (vs. stuck-at-14), 11.1% drawdown — mechanical fixes confirmed, but still -4.6%/Sharpe -0.59 (edge not yet profitable).
- New/extended unit tests across `train.py`, gating, `market_analyzer`, `validation_gate`, experts, `portfolio_book_construction`.
- Superseded by #52/#54: the rank-pivot roadmap's 2026-07-20 backtest was profitable (Sharpe 0.403, Net +10.4%).

---

### 44. Lean CLI couldn't feed the retraining loop — undocumented second `requirements.txt` convention

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `main.py`'s `ExperienceQueue` silently no-oped during every real `lean backtest .` run (missing `redis` module). Lean CLI auto-installs Python deps from a project-root `requirements.txt`, entirely separate from this repo's own `requirements/requirements.txt` convention, which Lean never reads — every other dependency happened to already exist in the Lean image, so this gap was invisible until `redis` became the first import it didn't bundle.

**Fix:** Added a repo-root `requirements.txt` containing `redis>=5.0.0`, cross-referenced from `requirements/README.md`.

**Verification:**
- Not re-verified against a real `lean backtest .` run this session (left for the user); confirmed correct by reading Lean CLI's own source (`lean_runner.py`).

---

### 45. `av` (Aether-Vault CLI) was broken on this machine — never actually run once in this repo

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `retraining/vault_client.py`'s commit stage shells out to the `av` CLI, which failed on every call (`ModuleNotFoundError: questionary`) and had never been initialized (`.av/` didn't exist) — invisible previously because `commit_candidate_to_vault()` degrades gracefully on failure by design.

**Fix:** Installed `questionary` into the correct environment (`av.exe` resolves through a separate user-scoped Python 3.14 install, not this repo's `.venv`), then ran `av init --mode local -y --no-repl` in the repo root.

**Verification:**
- Confirmed via `av status`; local-only mode accepted as correct (no remote registry configured, degrades to a local pending-push queue).

---

### 46. `xreadgroup(block=0)` meant "block forever," not "don't block" — idle Redis-stream workers timed out every cycle

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/postgres_worker.py` and `audit/postgres_worker.py` called `xreadgroup(..., block=0)` believing it non-blocking; in real Redis, `BLOCK 0` means block indefinitely, so with the client's `socket_timeout=5`, every idle poll raised a client-side timeout exception on every single cycle. Invisible previously because `fakeredis` (used in tests) doesn't reproduce real blocking-socket-timeout behavior.

**Fix:** Removed the `block=0` argument entirely from both call sites — the default `None` correctly omits `BLOCK`, letting the workers' existing correct `sleep(1)` idle loop work as intended.

**Verification:**
- Confirmed against a real Compose Redis instance: both workers sit at 0% CPU with zero errors post-fix.
- `tests/test_postgres_worker.py`/`tests/test_audit_postgres_worker.py` (18 tests) pass unchanged — they never asserted on the `block` argument, which is why this was invisible to the suite.

---

### 47. `retraining-worker`'s `./data` volume mount was read-only — `train.py` could never complete inside the real container

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `docker-compose.yml` mounted `./data:/app/data:ro`, but `train.py`'s crypto daily-series derivation (entry #15) needs to read-then-write `data/crypto/coinbase/daily/*.zip` on every invocation — the real container crashed with `OSError: Read-only file system`. Never caught before because every prior test/rehearsal ran `train.py` on the host, where `data/` is writable.

**Fix:** Changed the mount to writable (`./data:/app/data`).

**Verification:**
- Rehearsal re-run after `docker compose up -d --force-recreate` confirmed `train.py` completes past this point.

---

### 48. Force-recreating `retraining-worker` mid-cycle orphaned a stuck `retraining_events`/`model_versions` row — no startup reconciliation existed

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Recreating the `retraining-worker` container while a real `train.py` subprocess was in flight killed it before it could report back to Postgres, leaving `retraining_events`/`model_versions` rows permanently stuck at `"running"`/`"candidate"` — which blocked all future retraining via the cooldown check indefinitely, since nothing detected an orphaned row. A related finding: the container ran `python -m retraining.worker` as PID 1 with no init process, so a subprocess killed on an orchestrator timeout could become an unreapable zombie, blocking even `docker compose stop`.

**Fix:** Added `fetch_stale_active_events()`/`reconcile_stale_running_events()`, called once at worker startup, marking stale `running`/`planned` rows `failed` (and rejecting still-`candidate` `model_versions` rows) after a configurable `stale_running_timeout_seconds` (default 10800s, the sum of every stage's own timeout). Added `init: true` to the `retraining-worker` Compose service (Docker's built-in tini) so killed subprocesses get properly reaped.

**Verification:**
- 8 new tests across `postgres_registry`, `orchestrator`, `retraining_worker`; full suite green (1465 passed) before and after.
- The zombie/stuck-container scenario was hit live and manually recovered (`docker rm -f`) before the `init: true` fix; `docker compose config --quiet` confirmed the compose change resolves cleanly.

---

### 49. Full end-to-end retraining-loop rehearsal against the real Compose stack — three real cycles ran, all correctly rejected; rollback rehearsed both ways

**Severity:** n/a (operational-maturity verification, not a bug) · **Status:** 🟢 `verified`

**Problem:** N/A — this was a real rehearsal of the retraining loop against live Docker/Postgres/Redis, to prove it's a genuine closed loop and not just mocked-unit-test logic. One follow-up finding was deliberately left unfixed: the `lean` CLI is not installed in the `retraining-worker` image, so `backtest_gate` silently no-ops rather than crashing — flagged as a known, deliberate infrastructure gap.

**Fix:** N/A (verification exercise); no code changed.

**Verification:**
- Three real cycles ran via the worker's own background poll loop (`plan→train→train_topology→train_gating→train_multitask→train_sequence→validate`); `train_sequence` timed out once at its 1800s cap (a real resource-constrained-host finding, not a crash) but the pipeline correctly continued to `validate` anyway.
- `validate` correctly rejected all three candidates on legitimate quality grounds, consistent with #43's weak-edge finding.
- Rollback exercised directly against real Postgres/files: happy path flipped status to `active` correctly; tamper-detection path (deliberately corrupted artifact hash) correctly refused, with no files copied and no Postgres row touched.
- `backtest_gate` itself was never exercised organically (no candidate cleared `validate`) and confirmed structurally unable to run in this container as configured.

---

### 50. This dev machine's 4GB RAM couldn't reliably run a real `lean backtest .` — blocked verifying #34/#36/#37/#38

**Severity:** n/a (hardware constraint) · **Status:** 🟢 `fixed` (superseded — see #54)

**Problem:** Four consecutive real `aq backtest` attempts failed at Lean's hardcoded 90-second `initialize()` isolator cap. Root-caused precisely: `main.py`'s plain top-level imports (torch/pandas/sklearn) alone took ~82 seconds under memory pressure (measured as low as ~300MB free on this 4GB host), not a code regression. Blocked verification of #34/#36/#37/#38.

**Fix:** Narrowed `main.py`'s `from audit import ...` (which transitively pulled in Postgres/status-export code `main.py` never uses) to `from audit.redis_queue import ...`, trimming avoidable import cost inside the isolator-timed window. Also documented (not a code fix) that failed `lean backtest` Docker containers aren't reliably cleaned up on failure, leaving orphaned `lean_cli_*` containers holding memory.

**Verification:**
- Confirmed via `python -m py_compile main.py` and full test suite green after the change.
- Superseded 2026-07-20 (#54): a real `lean backtest .` completed successfully on the same machine, verifying #34/#36/#37 (though the run took ~40 min and needed manual zombie-process cleanup). #38 remains open, but now for an unrelated reason (no option asset registered in the universe).

---

### 51. `GET /api/assets-status` 500'd in Docker — `lean.json` (entry #42's exclusion) was never mounted back in, and the reader didn't degrade gracefully

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `/api/assets-status` 500'd in the real Docker deployment. Entry #42's security fix correctly excludes `lean.json` from the published image, but nothing volume-mounted a local `lean.json` back into the running `engine` container at deploy time, so `build_assets_status_from_disk()` hit an uncaught `FileNotFoundError`.

**Fix:** Added a read-only runtime volume mount (`./lean.json:/app/lean.json:ro`) to the `engine` service in `docker-compose.yml` (never baked into the image, preserving #42's security fix). Defense in depth: `build_assets_status_from_disk()` now catches `FileNotFoundError` and degrades to an empty `lean_config`, so `ib_readiness_status()` reports a graceful degraded status instead of 500ing.

**Verification:**
- New test `test_build_assets_status_from_disk_degrades_gracefully_when_lean_json_missing`; all 8 tests in that file pass.
- Confirmed against the real rebuilt container: `/api/assets-status` now returns 200 with correct content, where it previously 500'd.

---

### 52. The rank-pivot roadmap: trading path switched to `rank_20d`, universe expanded 30→74 assets, four Stage-4 regularization gaps closed

**Severity:** 9/10 · **Status:** 🟢 `fixed` (retrained and backtest-verified — see #54; one caveat still open, below)

**Problem:** The trading path traded the noise-objective direction head (backtest MCC ~0.02-0.04) instead of `rank_20d`, the codebase's one genuinely skillful signal, and traded even that far faster than its ~20-day horizon supports. Separately, four regularization/config gaps existed: purged-CV was configured but never called anywhere, no rank-IC-based early stopping existed, the dead 1-day direction head was still fully weighted in the loss, and no seed-ensembling or cross-head consistency regularization existed.

**Fix:** Five config-gated changes: (1) switched `strategy_mode` to `long_short`, enabled rank-based sizing, blended the sequence model's `rank_20d` head into traded probability, widened the book to top/bottom 8; (2) added an explicit 5-bar rebalance scheduler (`should_rebalance_this_bar()`) to cut turnover to match `rank_20d`'s horizon; (3) expanded the universe 30→74 assets (54% equity/30% bond/16% crypto), rebuilding the dataset to 113,804 rows; (4) added rank-IC-based early stopping, down-weighted (not removed) the dead direction-head loss, added seed-ensembling and horizon-consistency regularization to `train_multitask.py`/`train_sequence.py`; (5) wired the previously dead `purged_embargoed_folds()` into a real diagnostic (`purged_cv_rank_20d` metric). Also fixed a real bug in `yfinance_backfill.py` where `float()` on a MultiIndex-column `Series` silently relied on a deprecated pandas fallback.

**Verification:**
- Every new function shipped with unit tests; full `aq test` green (1497 passed, up from 1465).
- Update 2026-07-20 (real Codespaces retrain, #53): rank-IC early stopping fired correctly (best_epoch far off the old floor); full-series `rank_20d` IC improved over the pre-expansion baseline (multitask 0.172/t=7.55 vs. 0.073/t=4.40; sequence 0.127/t=5.70).
- Open caveat: the project's own promotion-gate bar (non-overlapping t-stat ≥ 2.0) is still not cleared (multitask 1.40, sequence 0.43).
- Real `aq backtest` (2026-07-20, see #54) confirmed a profitable result (Sharpe 0.403, Net +10.4%), though confounded by a concurrent `bypass_safety_gates` change.

---

### 53. GitHub Codespaces set up as cloud training offload; a real Alpine-base devcontainer bug found and fixed

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** The local 4GB-RAM machine could spend hours of wall-clock time on ~800 CPU-seconds of real training work (per #50/#52). Setting up GitHub Codespaces as offload compute hit a real bug: the `docker-in-docker` devcontainer feature silently swapped the pinned Debian-based image to Alpine, breaking `pip install` against musl libc (matches upstream `devcontainers/images#1114`). A deeper blocker: Codespaces containers run unprivileged, so Lean/Docker backtests cannot run inside a Codespace at all, with or without that feature — a platform limitation, confirmed not fixable from this repo.

**Fix:** Dropped `docker-in-docker` entirely (training needs no Docker), kept only the `sshd` feature, and prepended a CPU-only `pip install torch --index-url .../cpu` to `postCreateCommand` (the bare install resolved a CUDA build that fails to import on a GPU-less Codespace). Also fixed a git-hygiene bug: 9 generated `ml/` artifact files were still tracked in git (inconsistent with every other model file); added them to `.gitignore` and untracked them.

**Verification:**
- Verified via 5 systematic A/B Codespace rebuild tests (with/without `docker-in-docker`, with/without `sshd`).
- Full retrain of all 8 model artifacts completed in under 15 minutes on the fixed Codespace, versus 4+ hours unfinished locally.
- `git check-ignore -v` and `git status` confirmed the 9 files are clean/untracked.

---

### 54. First real `aq backtest` against rank-pivot models: Sharpe -0.59 → +0.40, plus a universe-selection bug (BNBUSD/TRXUSD never listed on Coinbase)

**Severity:** n/a (verification milestone) / 3/10 (ticker bug) · **Status:** 🟢 `verified` / `fixed`

**Problem:** The rank-pivot roadmap (#52/#53) still needed a real `lean backtest .` run to confirm results. Separately, two Stage-3 crypto tickers from #52's universe expansion (BNBUSD, TRXUSD) could never subscribe in Lean — Coinbase never listed Binance Coin or TRON pairs at all, though Yahoo Finance happily returned price history for both, masking the mis-selection.

**Fix:** No code fix needed for the backtest itself. For the ticker bug: swapped BNBUSD/TRXUSD for ETCUSD (Ethereum Classic) and ZECUSD (Zcash), both confirmed present in Lean's local Coinbase symbol-properties database, backfilled via `aq fetch crypto --apply`.

**Verification:**
- Real `aq backtest`: Sharpe -0.59 → 0.403, Net Profit -4.604% → +10.438%, Drawdown 11.1% → 4.0%, Win Rate 47% → 58%; the 5-day rebalance scheduler confirmed working as designed (turnover rate barely moved despite order count rising, explained by a bigger book and long_short trading both sides).
- Confound disclosed: `bypass_safety_gates` was flipped to `true` in this same run, so some of the improvement isn't cleanly attributable to the rank-pivot signal alone — a clean-comparison backtest with it reverted is left as a manual follow-up.
- Ticker swap verified via a dry-run row-count/date-range check before `--apply`, `config.json` JSON-validated, and a dataset rebuild confirming the new tickers register with the same observation-only classification as other Stage-3 crypto.
- Real-backtest log confirmed entry #34's limit orders actually fire (rounded limit-price log line).

---
### 55. Every webui tab except `/` 404'd on a direct load when served by FastAPI

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `monitoring/api_server.py` mounted the built bundle as `StaticFiles(directory=WEBUI_DIST, html=True)` — `html=True` only maps directory paths to `index.html`, not unknown paths, so a direct load or hard refresh of `/risk`, `/topology`, `/neural-network`, `/tracing`, `/operations` returned a raw 404 (client-side navigation worked fine; the vite dev server's own SPA fallback masked this in development).

**Fix:** Added a `SpaStaticFiles(StaticFiles)` subclass overriding `get_response()` to fall back to `index.html` on a 404, limited to extensionless paths so a genuinely missing asset (`/assets/*.js`) still 404s. Two subtleties: Starlette raises `HTTPException(404)` rather than returning one, and it raises Starlette's exception specifically (FastAPI's is a subclass, so catching that misses it).

**Verification:**
- `tests/test_api_server.py` gained parametrized cases for all six client routes, a missing-asset-still-404 case, and a case confirming `/api/*` isn't shadowed by the catch-all.

---

### 56. `train_topology.py` learned prototype z offsets on the pre-V4 `0..1` scale

**Severity:** 1/10 (latent; unreachable until a model exists) · **Status:** 🟢 `fixed`

**Problem:** V4-W3 made z a real `0..100`-scale correlation-distance axis in 3D embedding mode, but `train_topology.py` still emitted prototype z offsets on the old `0..1`-scaled formula — the learned overlay would move nodes on x/y and effectively not on z.

**Fix:** `train_topology.py` now emits z normalized to `[-1, 1]`; `topology/learned_topology.py::_score_node()` multiplies it by the active `max_offset_z` before the same clamp x/y already go through — provably identity-preserving in 2D and proportionally larger in 3D. Also added an `offset_schema` detection field (no migration branch needed — no model of the old format has ever existed). Training the first real topology model is a separate, user-run milestone (`aq train --topology-only` added), not part of this fix — no topology model has ever been trained, so the overlay remains entirely dormant.

**Verification:**
- New test proves byte-identical output against the old raw formula in 2D mode; a second test proves 60x more z travel under the raised 3D cap.

---

### 57. Futures/options had a live incremental-vs-absolute order-sizing bug — fixed, plus position scale-up for all 5 asset classes

**Severity:** 5/10 (dormant, reachable only via `futures_risk.enabled`/`options_risk.enabled`, both default off) · **Status:** 🟢 `fixed`

**Problem:** Equity/crypto/bond were blocked from adding to an existing position by a simple gate in `main.py::_apply_signal()`. Futures and options had no such gate at all — worse, they fired their correctly-recomputed **absolute** per-bar sizing target through **incremental** Lean order primitives (`MarketOrder`/`Buy`) every bar the signal held, silently stacking contracts unbounded. Options could additionally orphan a position by re-selecting a different strike/expiry each bar without closing the old one.

**Fix:** New `risk_controls.py::compute_incremental_order_quantity()` — futures/options now always submit only the signed delta toward the absolute target, unconditionally (no flag, since this is a genuine bug fix). Two further opt-in tiers: `position_scaling.enabled` (default false) allows scale-up/down with a churn guard; `rotate_on_drift` (default false) allows liquidate-then-reenter for drifted option contracts.

**Verification:**
- Confirmed byte-identical default behavior via grep/call-graph trace — the fixed code path is unreachable at default config since sizing returns 0/None first.
- 1521 → 1558 tests passing; new coverage in `tests/test_risk_controls.py`, `tests/test_order_gate.py`.
- `main.py` itself has no direct unit tests (subclasses `QCAlgorithm`) — verified via code trace only.

---

### 58. Architecturally-sound options: multi-position book, symmetric scale-down, held-contract sizing, spread combo orders (V4.4)

**Severity:** n/a (architecture pass, no defect) · **Status:** 🟡 `partial` (code-complete, ⚪ IB-unverified — no option assets in the universe, no IB key connected)

**Problem:** Review of #57's options paths found six architectural gaps: single-leg options could only scale up, not down; spreads couldn't scale down at all (no `Sell`-side combo primitive existed); a drifted position with `rotate_on_drift` off was frozen entirely rather than re-managed; single-slot tracking capped the book at one position per underlying; rotation's same-bar liquidate+reenter had no netting; spreads had no limit-order path.

**Fix:** Built the full multi-position book (`option_positions_by_symbol` as `dict[str, list[dict]]`, capped by `max_positions_per_underlying`, default 1 = byte-identical to before), new pure sizing functions for already-held contracts/legs, Sell-side combo scale-down, and combo limit orders. A real gap (at-cap re-pricing firing even with `position_scaling` disabled) was caught during verification and fixed before landing.

**Verification:**
- Default config path confirmed unreachable — `options_risk.enabled=false` forces vega budget to 0.
- 1558 → 1591 tests passing; new coverage in `tests/test_options_strategy.py`, `tests/test_order_gate.py`.
- `main.py` changes verified via exhaustive call-graph trace only (untestable in isolation); real fill/margin behavior remains unverified without IB.

---

### 59. Full `OptionStrategies` coverage: all 43 QuantConnect option structures, registry-driven (V4.5)

**Severity:** n/a (architecture pass, no defect) · **Status:** 🟡 `partial` (code-complete, ⚪ IB-unverified)

**Problem:** Only 2 of QuantConnect's 43 `OptionStrategies` factory structures were implemented (#57/#58); the user wanted full coverage so the model can drive any structure with no gaps.

**Fix:** Replaced near-duplicate per-strategy functions with a `MULTI_LEG_STRATEGY_REGISTRY` data table (all 43 entries, transcribed from real Lean C# source, correcting 2 mistranscribed leg-direction assumptions found in the process) dispatched through ~10 shared shape-family leg selectors; new `options_margin_sizing.py` for naked/uncovered/bounded-max-loss margin tiers; `main.py` generalized to a `"multi_leg"` record kind. Gated behind `multi_leg_strategies_enabled` (default false, byte-identical to before).

**Verification:**
- 1589 → 1656 tests passing (registry completeness, all 43 strategies against synthetic chains, margin tiers, router gating).
- `main.py` rewrite verified via call-graph trace plus the full pre-existing suite passing unchanged (proves the legacy vertical path is identical through the new generalized code).
- Combo-order surface remains IB-unverified.

---

### 60. V4.6 — bounded options follow-ups, arbitrage mispricing detector, Forex/FX, and analytic bond-ETF duration/convexity

**Severity:** n/a (follow-up/architecture pass, no defect) · **Status:** 🟡 `partial` (Forex sub-item now 🟢 fixed and live-verified — see below; arbitrage-detector sub-item remains IB-unverified)

**Problem:** A backlog pass: multi-leg position counting double-counted legs against `max_active_positions`; options rotation had no anti-thrashing guard or same-bar netting; no per-asset strategy override existed; the 6 arbitrage strategies were stubbed with no mispricing detector; no Forex/FX asset class existed; individual-bond trading (requested) turned out to be impossible since this Lean version has no bond security type at all.

**Fix:** Added `_distinct_position_identities()` for correct position counting (also fixed a related exclude-filter bug); `rotation_cooldown_bars` anti-thrashing guard; same-bar rotation netting via re-sizing against fresh portfolio value; per-asset `enabled_strategy_names` override; new `options_arbitrage_detector.py` (closed-form fair-value formulas + bps-floor threshold, default off); new `risk/forex_risk.py` + `forex_pair_specs.json` + `main.py` forex branch for a new Forex asset class; reframed bond work as analytic duration/convexity/DV01 math added to `features/bond_features.py`, informational-only (never fed into the trained model).

**Verification:**
- 1656 → 1722 tests passing across new test files for the arbitrage detector, forex risk, and bond features.
- `main.py` changes verified via call-graph trace plus the full suite unchanged.
- **V5.2.8: Forex sub-item confirmed fully live, not "zero live tickers" as originally stated.** `config.json`'s `phase1.universe.assets` now has 15 real OANDA forex pairs, `phase_v2.forex_risk.enabled: true`, and `risk/forex_risk.py`/`risk_controls.py::compute_forex_order_units()` are fully wired into `main.py` (6 call sites) — exercised in two real Lean backtests (see #92/#93: 220 real forex fills, `notional_ratio` within 0.15% of 1.0 across 193 diagnostic records).
- Arbitrage-mispricing-detector sub-item unchanged: `phase_v2.options_risk.arbitrage_detector.enabled` still `false`, `options_arbitrage_detector.py` operates on option-chain data — still needs an option asset in the universe and remains IB-unverified.

---

### 61. V4.7 — early-assignment/corporate-action modeling, a learned strategy-selector model, and bond analytics wired into the trained model

**Severity:** n/a (follow-up/architecture pass, no defect) · **Status:** 🟡 `partial` (bond-analytics sub-item now 🟢 fixed — see below; early-assignment detector and strategy-selector model remain default-off/dormant)

**Problem:** V4.6 deferred three items: full early-assignment/corporate-action modeling, a learned model to pick multi-leg options strategies, and wiring bond analytics into the trained model as real features (previously informational-only specifically to avoid forcing a retrain).

**Fix:** Added `dividend_backfill.py` (yfinance ex-dividend history + cadence-based next-date projection), a real Barone-Adesi-Whaley American-exercise pricer, `options_assignment_risk.py` scoring, and a default-off auto-close sweep. Added a capture path in the observation-mode order branch (the real-order path never fires without IB), `train_strategy_selector.py`, `inference/strategy_selector_inference.py`, and router reranking (only active once a model is trained and enabled). Added 3 new bond feature names (`bond_analytic_modified_duration`, `bond_analytic_convexity`, `bond_dv01`) to `config.json`'s `input_set`, computed in both `main.py` and `train.py`'s offline pipeline.

**Verification:**
- 1722 → 1813 tests passing (91 new, including the American≥European price invariant and a put-always-zero-assignment-risk invariant).
- `main.py` changes verified via call-graph trace only.
- **V5.2.8: the "requires a retrain before deploy" caveat is resolved and stale — no new retrain needed.** `#70`'s full Codespace retrain (already shipped, already verified via real backtests V5.2.4-V5.2.7) closed this: confirmed `ml/feature_schema.json`'s 49 `feature_names` are byte-identical to `config.json`'s current 49-entry `input_set`, `ml/scaler_stats.json`'s mean/scale arrays are length-49-aligned, and `git diff --stat HEAD` shows zero drift on either file.
- Early-assignment-detector/strategy-selector-model sub-items remain dormant/default-off — no live signal exists yet to verify against, correctly excluded from this update.

---

### 62. Phase 4.8 — closing operational/surfacing gaps: `lean` CLI in retraining-worker, a `main.py` scoping bug fix, new Options & Strategy webui page

**Severity:** n/a (surfacing pass), plus one real bug rated 4/10 (silently wrong data persisted, never a crash) · **Status:** 🟢 `fixed`

**Problem:** A 3-agent audit found the `lean` CLI wasn't installed in the production Docker image used by `retraining-worker`; `docker-compose.yml` was missing a `data/reference` mount (silently zeroing Forex/futures/FRED specs) and had a stale comment; `aq` had no bulk-backfill dispatcher; `aq test`'s subsystem file lists were stale; and a real bug — `main.py` computed `corporate_action_payload` in Pass 1's per-symbol loop but read it back in Pass 2's separate loop, so (no block scoping in Python) every symbol's event silently reused whatever value Pass 1 left over from the last symbol it processed. Several V4.7 fields (bond analytics, assignment risk, dividend schedule, strategy-selector scores) were also computed but never actually reached `state.json` despite a code comment claiming otherwise.

**Fix:** Added `lean` to production requirements + a Docker socket mount for `retraining-worker`; fixed the compose mount/comment; added `aq backfill <target>`; fixed the stale test-file dict; fixed the scoping bug by threading `corporate_action_payload` through `pass1_state` per-symbol; wired all 5 missing fields into `signals[symbol_key]` in `_write_state()`; added a new `/options-strategy` webui page.

**Verification:**
- Bug fix verified via direct call-graph trace (`main.py` has no unit tests) plus the full suite staying green.
- 1813 → 1818 python tests passing; webui 13 tests across 2 files; `npm run build`/`lint`/`test` clean.

---

### 63. V4.9 Priority 0 — the #36/#50 profiling wrapper was never reverted: a live per-bar disk write on the hottest path

**Severity:** 6/10 (real continuous synchronous disk I/O on every symbol-bar call in any live/paper/backtest run) · **Status:** 🟢 `fixed`

**Problem:** Entry #36's claim that the `_build_model_input()` profiling wrapper "was fully reverted" (per #50) was false — `main.py` still unconditionally opened `model_input_timing.log` and wrote a line on every symbol-bar call, no config gate, with 45,187 accumulated lines (~983KB) untracked in the repo root.

**Fix:** Renamed `_build_model_input_impl` back to `_build_model_input` and deleted the wrapper; removed the dead `perf_counter` import; deleted the log file. Real per-call timing data collection remains a separate, still-open task — `scripts/profile_inference.py`'s in-process harness (no disk I/O) is the intended path forward instead.

**Verification:**
- `python -m py_compile main.py` clean; grep-confirmed zero remaining references to the removed names/file.
- `main.py` verified via call-graph trace only (unit-untestable by convention).

---

### 64. V4.9 Priority 4 — `_build_options_chains_payload()`'s gating, considered and declined

**Severity:** n/a (no code change — a documented decision) · **Status:** 🟢 `fixed` (declined by design, no code change)

**Problem:** Candidate optimization: gate `_build_options_chains_payload()` (runs once per bar for every configured option asset) behind `self.options_risk_enabled` so it's skipped when options risk management is off.

**Fix:** Declined — no code changed. Configuring an option asset in the universe is already the deliberate trigger for chain visibility (feeds `state.json`/webui independent of whether multi-leg trading is enabled), matching the same "compute for visibility even when trading is off" pattern bond analytics/assignment risk already follow. The function has never appeared as a meaningful cost in any profiling run.

**Verification:**
- Decision recorded so this optimization isn't re-investigated from scratch by a future latency pass.

---

### 65. V4.9 Priorities 1-3, 5-8 — sequence batching, topology percentile-tolerance caching, options chain-grouping hoist, non-blocking experience delivery, IPC benchmark, HFT documentation

**Severity:** n/a (feature/optimization pass, all off by default) · **Status:** 🟢 `fixed`

**Problem:** Continuation of the profiling roadmap item: the largest remaining per-bar inference cost (sequence encoder run once per symbol), a poorly-calibrated fixed topology cache tolerance, a small hoistable per-bar options cost, blocking experience-event delivery in live/paper mode, an unmeasured assumption about `ProcessPoolExecutor` IPC overhead, missing options profiling coverage, and unclear framing of which latency work is genuine HFT-fork prep.

**Fix:** Priority 1 — `run_exported_sequence_multitask_model_batched()` stacks all symbols' sequences into one batched pass instead of one model call per symbol (default off, falls back on <2 sequences or any failure). Priority 2 — a percentile-based rolling-window topology cache tolerance (`correlation_stability_tolerance_percentile`, default `null` = byte-identical old behavior). Priority 3 — hoisted `group_chain_by_expiry()` to compute once per routing call instead of per candidate. Priority 5 — `ExperienceQueue.push()` gained a non-blocking `async_enabled` mode (default off). Priority 6 — a real IPC benchmark confirmed `ProcessPoolExecutor` is dramatically slower than sequential on this Windows/spawn dev machine (measured, not theoretical). Priority 7 — new `"options"` workload in `profile_subsystems.py`. Priority 8 — new `development/architecture.md` section honestly separating genuine HFT-transfer work from daily-bar-loop-only speedups.

**Verification:**
- 1818 → 1857 tests passing (39 new) covering batching parity, percentile-tolerance math, chain-grouping parity, async delivery semantics, pool-failure degradation, options workload shape.
- All new config keys grep-verified to default to `false`/`null` (byte-identical behavior when off).
- `main.py` changes verified via call-graph trace only.

---

### 66. V4.10 — pure-function extraction of `main.py`'s exit logic, 4 webui quality fixes, and 15 new forex/FX assets fetched

**Severity:** n/a (feature/extraction/data pass) · **Status:** 🟢 `fixed`

**Problem:** `main.py`'s exit-decision logic (max-holding-age + trailing-stop) had never been extracted into a testable pure module, unlike every comparable decision elsewhere in the system. A post-V4.9 audit also found 4 webui defects (defeated `useMemo` caching, an oversized single JS bundle, 2 dead Grafana routes, untested chart/format primitives), and Forex, though fully wired since V4.6, had zero live tickers because `aq fetch` had no forex asset class.

**Fix:** Extracted `evaluate_non_model_exit()`/`compute_position_exit_tracking_update()` into `risk_controls.py`. Fixed the webui issues (stable empty constants, `React.lazy()` + `Suspense` code-splitting the 3D bundle, removed the 2 dead routes, added direct tests for chart/format primitives). Added a `"forex"` entry to `fetch.py`'s asset-class config plus a bid/ask-synthesizing Lean CSV writer, extended `forex_pair_specs.json` 7→15 pairs, and fetched all 15 pairs' full-window data (universe 74→89 assets); `forex_risk.enabled` stays off by default.

**Verification:**
- Exit-logic extraction verified byte-identical via static call-graph trace only (`main.py` still can't be executed by a test).
- New forex fetch/writer tests use injected `fetch_fn` (zero real network access); webui suite 37/37 passing (up from 13); `npm run build`/`lint`/`test` clean.
- `python train.py --dataset-only` was deliberately **not** run to confirm the forex trading classification — the user chose to run training manually later; `asset_universe.md` marks the pairs "Trading (expected)," not confirmed.

---

### 67. V4.10 follow-up — opt-in live (Lean/IB-calibrated) futures margin source, toggleable via `aq config`

**Severity:** n/a (feature, off by default) · **Status:** 🟡 `partial` (code-complete, genuinely Lean-API-unverified)

**Problem:** `futures_contract_specs.json` had, since V4.6, an explicit "documented future enhancement, not implemented" note asking to prefer IB's live margin over static reference numbers.

**Fix:** Added `phase_v2.futures_risk.margin_source` (default `"static"`), settable via the existing generic `aq config set`. In `"live"` mode, `main.py` attaches Lean's own local IB-calibrated `BuyingPowerModel` to each futures security individually (never a global `SetBrokerageModel`) and queries it via a new `_resolve_futures_contract_spec()`; new `build_live_contract_spec()`/`resolve_futures_margin_source()` in `risk/futures_risk.py` produce a spec interchangeable with the static path. Every live-margin call site is wrapped in try/except, falling back to the static/default path on any failure.

**Verification:**
- 8 new tests in `tests/test_futures_risk.py` (26 total) covering validation, live-spec shape, and interchangeability with the static path.
- `main.py` wiring verified via call-graph trace only.
- Never run against a real Lean backtest with a futures position actually sized — genuinely Lean-API-unverified (the margin-query API has evolved across Lean versions).

---

### 68. `cpp_inference_ext` was never built for the actual deployed image — closed via a soft-fail Docker build step

**Severity:** low (silent perf-only gap, not correctness) · **Status:** 🟢 `fixed`

**Problem:** The only compiled `cpp_inference` extension was hand-built for this dev machine's Python 3.14, permanently ABI-incompatible with the deployed `python:3.11-slim` image; the Dockerfile never installed a compiler, `pybind11`, or the extension — so the C++ acceleration had never run in any deployed container, a 100% silent gap (the fallback path is silent by design).

**Fix:** Added a soft-fail Dockerfile `RUN` step installing `build-essential` + `pybind11`, pip-installing `cpp_inference_ext`, then purging `build-essential` in the same layer, wrapped in `(...) || echo ...` so any toolchain/ABI failure degrades to the existing NumPy fallback rather than breaking the build. Added matching `.dockerignore` excludes so a locally-built incompatible binary can never leak into the published image.

**Verification:**
- Initially unconfirmed for two phases due to a local Docker/WSL2 outage.
- Confirmed in Phase 4.12.3: `docker compose build engine` succeeds and, inside the built image, `import cpp_inference` succeeds with real compiled linkage (`cpp_inference.cpython-311-x86_64-linux-gnu.so`), not the fallback path.

---

### 69. Audit follow-up — `main.py` CI syntax-check gate, and a Windows-specific inference-parallelism slowdown guard

**Severity:** low · **Status:** 🟢 `fixed`

**Problem:** `main.py` had zero CI coverage, not even a syntax check (no test file can import it, since `AlgorithmImports` is undefined outside a real Lean process). Separately, `phase_v2.inference_parallelism.enabled` had no runtime guard despite entry #65 Priority 6 measuring it as dramatically slower than sequential on Windows/spawn — and the key didn't even exist in `config.json`, so `aq config set` on it actually failed outright rather than silently succeeding.

**Fix:** Added a `python -m py_compile main.py` CI step (proves the file parses, nothing more; an mypy/pyright pass using `quantconnect-stubs` was considered and declined as too noisy). Added `windows_parallelism_slowdown_warning()` (fires a `Debug()` log only on `win32` after real pool construction), a key-specific `aq config set` stderr warning citing the #65 measurement, and an explicit `phase_v2.inference_parallelism: {"enabled": false}` block added to `config.json` (previously code-side-only, making the key un-settable via `aq config`).

**Verification:**
- New tests in `tests/test_parallel_inference.py` (win32 vs. linux/darwin) and 4 new tests in `tests/test_aq_cli.py` (warning fires only for this exact path, only when truthy, only against `config.json` not `lean.json`).

---

### 70. V4.11 — full Codespace retrain + walk-forward executed, three latent `train.py` bugs fixed, primary signal clears the significance bar

**Severity:** n/a (milestone) · **Status:** 🟢 `fixed` (all infra/verification blockers this entry raised were closed in Phase 4.12.3; remaining era-sign instability is a separate, tracked model-quality question, not an infra gap — see #71)

**Problem:** A full model retrain and the Stage-6 walk-forward diagnostic had only ever been coded, never actually run. Running them for real (including, for the first time, the 15 new forex pairs) surfaced 3 genuine latent `train.py` bugs: forex quote-bar data was silently dropped by the trade-bar parser; an empty-frame regime-encoding path produced duplicate columns and crashed walk-forward; a walk-forward manifest `KeyError` on empty per-window inventories. A stale-data sync gap was also found — 4 forex zips on the Codespace were an old 2007-2018 vintage, wrongly classifying those pairs `observation_only`.

**Fix:** Added a forex branch to `load_lean_bars()` collapsing quote bars to a train/serve-parity midpoint; added an empty-frame guard in `add_regime_features()`; added a `.get()` fallback for the manifest `KeyError`. Re-synced fresh forex zips and retrained.

**Verification:**
- Real Codespace retrain: multitask `rank_20d` `non_overlapping_t_stat = 2.028` (≥2.0 pass), `bootstrap_ci_lower = +0.0065` (≥0 pass) — both hard thresholds pass for the first time; verdict still `not_promotable`, blocked solely by era-sign instability (2/9 eras opposite-sign).
- Real user-run Lean backtest (2019-2021, 78-asset model): completed end-to-end, 2,062 orders; every newly-toggled feature ran without crashing. Net +1.04%, Sharpe -0.313 — a faint edge that doesn't yet clear costs.
- A Python shutdown hang traced to the `inference_parallelism` pool was found and fixed separately (#68/#69 pass) via explicit `pool.shutdown()` plus the flag reset to default-off.
- Topology overlay (#56) still dormant — Codespace has no Postgres/experience DB.

---

### 71. Phase 4.12 — kill era-sign instability, close remaining non-IB items, expand breadth, alt-data + RL sizing

**Severity:** n/a (milestone) · **Status:** 🟢 `fixed` (all streams landed and retrained end-to-end; Docker-dependent verification closed in Phase 4.12.3)

**Problem:** V4.11 left the primary `rank_20d` signal blocked from promotion solely by era-sign instability (a COVID-era inversion), plus several other open items: no per-era diagnostics, a crypto-only weekend cross-section contaminating IC observations, a hardcoded-zero regime correlation feature, unused alt-data/breadth opportunities, and an untested RL-based sizing idea.

**Fix:** A1 added full per-era diagnostics to the promotion gate. A2 raised `min_universe_size` 10→20, removing a degenerate crypto-only cross-section that was flipping era signs. A3 added an era-sign noise floor so thin/near-zero eras don't fail the gate identically to genuine inversions. A4 fixed `average_correlation` being hardcoded to 0.0 (reordered feature-build steps) and added, but did not wire in, a beta-neutral ranking target. Stream D added VIX/VXV/NFCI alt-data features. Stream C expanded the universe 89→104 assets with proportional position-cap scaling. Stream E built an offline contextual-bandit RL sizing layer, shipped disabled after an honest negative backtest result.

**Verification:**
- Real Codespace retrain: `rank_20d` t-stat improved 2.028→2.8954, CI lower 0.0065→0.0585 (both gates pass with margin) but still `not_promotable` — 2 real era inversions remain (COVID plus a newly-exposed Dec 2020-Mar 2021 era, both exceeding the noise floor). Sequence `rank_5d` achieved full `promotable` status for the first time in the project's history.
- Walk-forward: 6 expanding windows, cross-window MCC mean 0.0187, CI [0.0136, 0.0239], entirely positive.
- RL sizing: backtest expected reward (-8.542e-5) underperformed the trivial constant-multiplier baseline (-8.264e-5) — ships disabled per pre-committed abandon criteria, later re-confirmed identically in Phase 4.12.3.
- Docker Desktop was down all session (WSL2 crash), blocking #68's linkage check, B1 topology training, both final Lean backtests, and 104-asset isolator timing — all 4 items closed in Phase 4.12.3.

---

### V4.12.2 — close every webui/CLI integration gap Phase 4.12 left behind

**Severity:** n/a (integration-completeness pass) · **Status:** 🟢 `fixed`

**Problem:** A follow-up integration audit found the Phase 4.12 backend/CLI complete, but the webui was not (~4/10): position-sizing multipliers, the newly-promotable sequence `rank_5d` head, A1's per-era diagnostic table, and alt-data/bond macro features were all computed and persisted but never rendered — and macro data never even reached `state.json` in the first place.

**Fix:** Extended the `DynamicSizing` webui type and `AssetSizingTable.tsx` to show each sizing multiplier as a labeled chip; extracted a `RankingQualityGate` sub-component now rendered for all three heads plus a per-era diagnostic table; added `state["macro"]` to `main.py`'s `_write_state()` (mirroring the existing derivatives-macro precedent) and a new `MacroSnapshotPanel.tsx`. CLI was audited and found to have no gaps.

**Verification:**
- Full local pytest: 1989 passed, 11 errors all from the pre-existing Docker-dependent fixture (not a regression).
- `npm run build` clean; `npx vitest run` — 46/46 tests green.
- No new `main.py`-level test added for the `state["macro"]` line, per this project's established `main.py`-untestable convention — verified by direct code trace instead.
- Also fixed stale documentation across 6 subsystem READMEs that had been missing from the original Phase 4.12 write-up.

---

### Phase 4.12.3 — every remaining Docker-dependent item closed, Phase 4 arc complete

**Severity:** n/a (closure phase) · **Status:** 🟢 `fixed` (nothing IB-independent left open)

**Problem:** Phase 4.12 left 4 items blocked by a Docker Desktop/WSL2 outage: the #68 `cpp_inference_ext` Docker linkage check, B1 topology overlay training (#56), two user-run Lean backtests, and Lean isolator timing at the new 104-asset universe size.

**Fix:** Root-caused the outage to a stuck `wslinstaller.exe` process wedging `WSLService` — required a genuine cold restart (not "shut down then power on," which resumes the same broken session under Windows Fast Startup) to clear. With Docker working: confirmed real `cpp_inference` `.so` linkage in the built engine image; trained the topology overlay for the first time ever (6 clusters from 4,937 samples, via a 3-month observation-mode backtest after repeated full-window OOM crashes on this 4GB machine forced shrinking the window); ran both the observation-mode data-generation backtest and the full representative 2019-2021 backtest with drawdown enforcement genuinely active; measured `Initialize()` wall-clock at ~105s for the 104-asset universe (above the 90s isolator budget referenced in the original plan, but the run completed without an isolator-timeout error).

**Verification:**
- Real Lean backtest (full window, `bypass_safety_gates: false`): completed cleanly in ~31 min, 3,606 orders, no forced-liquidation lock triggered. Sharpe improved -0.313 → -0.145, Net Profit 1.04% → 3.41%, Drawdown 8.9% → 6.6% — still not statistically significant (PSR 1.84%) and fees ($2,769) still consume nearly all net profit.
- RL sizing re-run on fresh Codespace datasets reproduced the identical honest negative result, confirming it wasn't a fluke.
- New standing rule adopted: all model training happens on the Codespace via CLI, never locally, given this machine's RAM constraints.

---
### 72. V5.1 Phase 1's net-edge cost gate blocked 100% of trades — Lean Backtest 1 produced 0 orders end to end

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** `analyzer/market_analyzer.py`'s Priority 6.5 net-edge gate re-derived its own pass/fail from the raw `net_edge_bps` value instead of trusting `build_net_edge_decision()`'s `passes` field. The "disabled" state still carried a real `net_edge_bps=0.0`, so with the `aggressive` preset's `min_net_edge_bps: 2.0`, the comparison `0.0 < 2.0` evaluated `True` on every symbol/bar, routing every directional signal away from trading — 100% of trades blocked, 0 orders for the entire backtest.

**Fix:** Removed the re-derived comparison and the `min_net_edge_bps` parameter from `build_market_analysis_decision()`; Priority 6.5 now trusts `net_edge.get("passes", True)`, the single verdict already computed by `build_net_edge_decision()`. `main.py`'s call site updated to match.

**Verification:**
- 5 new regression tests added to `tests/test_market_analyzer.py`, including one constructing the exact "disabled" dict shape and asserting it still reaches `"trade"`
- Root cause surfaced by a real Lean backtest (0 orders); no prior unit test exercised a realistic non-`None` disabled dict

---

### 77. V5.1 Phase 1's `min_rank_confidence_spread` gate defeated by its own cross-sectional normalization fix — real Lean Backtest 1 traded but lost money

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `portfolio/book_construction.py::_select_book_group()`'s conviction gate read the cross-sectionally-normalized `predicted_rank_20d` (introduced by the F1 fix, #73) instead of the raw score. A fixed top-6/bottom-6 selection, once percentile-ranked, always shows ~0.90+ spread regardless of real dispersion, so the `aggressive` preset's `min_rank_confidence_spread: 0.20` never disengaged the book across the whole 2019–2021 run. Sharpe fell from −0.145 to −2.526 and net profit flipped +3.41% to −3.11%.

**Fix:** Added an optional `spread_check_ranks` parameter to `_select_book_group()`/`build_rank_based_book()`; `main.py` now builds it from each symbol's pre-normalization `raw_rank_score` and passes it alongside the normalized `book_candidates`. Sizing/confidence still reads the normalized value — only the engagement gate's input changed.

**Verification:**
- 6 new tests in `tests/test_portfolio_book_construction.py`, including one reproducing the bug directly and one proving selection stays unaffected
- Not yet re-verified with a Lean backtest — deliberately held in reserve, bundled with Phase 2's retrained-model backtest

---

### 78. `tests/test_retraining_worker.py` — 7 of 11 tests spawned a real, unmocked subprocess, adding ~17 minutes to every full suite run

**Severity:** 3/10 (dev-velocity/CI-cost only, no correctness impact) · **Status:** 🟢 `fixed`

**Problem:** 7 tests patched the first four of `RetrainingWorker.run_once()`'s five best-effort trainer stages by name but never `train_strategy_selector`, so each test spawned a real `subprocess.run()` shelling out to `train_strategy_selector.py` (~140–168s apiece) — collectively ~1,050–1,200s of a ~28-minute full suite.

**Fix:** Added `patch("retraining.worker.train_strategy_selector")` alongside the other five stage patches in all 7 affected tests, matching the file's existing per-stage mocking convention.

**Verification:**
- Full file re-run: 11/11 passed, 86.8s total (down from >1,050s for the same 7 tests) — roughly 15–16 minutes off every future full-suite run

---

### 79. `data_pipeline/fred_backfill.py::fetch_fred_series()` hung/reset on every request — FRED's graph-export endpoint requires HTTP/2, which stdlib `urllib` cannot speak

**Severity:** 7/10 (blocked V5.1 Phase 2's CODESPACE RUN 1 entirely — 0 of 12 FRED series fetchable) · **Status:** 🟢 `fixed`

**Problem:** stdlib `urllib.request` (HTTP/1.1-only) could no longer reliably reach FRED's `fredgraph.csv` endpoint — an external, FRED-side behavior change, not a regression in this codebase. All 12 series failed with read timeouts. A secondary finding: a browser-spoofing `User-Agent` header (the prior code's own) caused an immediate `RST_STREAM` even over HTTP/2, plausibly from FRED's WAF cross-checking User-Agent against TLS fingerprint.

**Fix:** Swapped `urllib.request` for `httpx.Client(http2=True)`; added `httpx[http2]>=0.27.0` to requirements; removed the browser-spoofing `User-Agent` header entirely (left unset).

**Verification:**
- Rewrote network-mocking tests in `tests/test_fred_backfill.py` against `httpx.Client`; 31/31 pass
- Verified live (real network) both locally and on the Codespace: all 12 series, including 3 new ones, fetch successfully with full historical coverage

---

### 80. `train.py::build_dataset_manifest()`'s new `computed_but_unused_features` (V5.1 Phase 2) flagged ~70 legitimate columns as orphaned on the first real dataset build

**Severity:** 6/10 (would have buried the 3 genuine orphans under ~70 false positives) · **Status:** 🟢 `fixed`

**Problem:** The manifest is built on the post-scaling dataset, but `_computed_but_unused_feature_columns()` only excluded `base_feature_names`/`context_feature_names` — never `scaled_feature_names`, `categorical_feature_names`, or raw OHLCV/bookkeeping columns — so every `_scaled` sibling column, categorical one-hot, and raw bookkeeping column (timestamp/open/high/low/close/volume, security_type, etc.) was flagged as an orphan. Tiny synthetic test fixtures never included these column classes, so nothing caught it.

**Fix:** Threaded `scaled_feature_names` and `categorical_feature_names` into the exclusion set; expanded `_NON_FEATURE_DATASET_COLUMNS` to include `RAW_COLUMNS` plus `security_type`/`market`/`quality_tier`/`trading_eligible`/`training_eligible`.

**Verification:**
- New regression test covering all three previously-missed column classes
- Re-verified on the Codespace against a real dataset build: `computed_but_unused_features` now returns exactly the 3 genuine orphans (`futures_term_structure_slope`, `options_implied_vol_skew`, `options_put_call_ratio`)

---

### 81. `portfolio/book_neutrality.py::apply_book_neutrality()`'s sector-neutral step silently erased entire legs of the live/simulated book

**Severity:** 9/10 (live-path bug — shipped default since V5.1 Phase 1) · **Status:** 🟢 `fixed`

**Problem:** Sector-neutral demeaning subtracted each bucket's mean signed weight from every member, which drives every member to exactly zero whenever a bucket has zero within-bucket weight dispersion — true by construction, since every caller equal-weights names per role. `"Forex"` (all 15 tickers share one bucket) was a structural, not rare, case: any time the short leg had forex representation, demeaning erased the entire short leg. Found via `aq evaluate --rank-book` showing `mean_names_short=0.00` despite `bottom_n=6`.

**Fix:** Replaced "demean to exact zero" with: leave a bucket untouched if `|net| <= sector_max_net_weight`, otherwise shrink the whole bucket proportionally (sign preserved, never amplified) so its net lands exactly at the cap. Single-member buckets no longer need special-case code. Side effect: a single-member bucket already exceeding the cap is now also capped (previously exempt), judged correct.

**Verification:**
- `tests/test_book_neutrality.py` rewritten, 12 tests including a direct regression guard for the monolithic-role case
- Verified end-to-end on the Codespace, real model/data: `net_sharpe` 0.4856→0.9694, `mean_names_short` 0.00→6.00
- Not yet re-verified with a Lean backtest — `sector_neutral: true` has been the config default since Phase 1, so this affects the live decision path too

---

### 82. V5.1 Phase 4's walk-forward net-performance step crashed on window 1 — fed the exported model the wrong feature list (49 raw names instead of the 66 it was actually trained on)

**Severity:** 7/10 (crashed the entire walk-forward run on window 1) · **Status:** 🟢 `fixed`

**Problem:** `_run_walk_forward()`'s net-performance call site passed the outer `feature_names` (49 raw, pre-scaling names from `config["phase1"]["features"]["input_set"]`) instead of the 66-column `model_input_names` the sequence/multitask models were actually trained against — crashing with `ValueError: _conv1d_causal: in_channels mismatch (49 vs weight's 66)`.

**Fix:** Changed both call sites inside `_run_walk_forward()`'s net-performance block to use `dataset_manifest["model_input_names"]` instead of the outer `feature_names`.

**Verification:**
- Re-verified on the Codespace: the exact same run that crashed on window 1 completed all 6 windows cleanly after the fix
- No unit test caught it — `tests/test_walk_forward_multimodel.py` fixtures used a tiny single-feature list where "raw" and "model input" names were never genuinely distinct

---

### 83. V5.1 Phase 4's walk-forward sequence training hits a hard memory ceiling on the project's Codespace machine type for larger training windows

**Severity:** 6/10 (no result corruption — degraded cleanly to the multitask fallback — but weakened statistical power of 3 of 6 windows) · **Status:** 🟢 `fixed` (root cause found and fixed at the start of Phase 5)

**Problem:** `train_sequence.py` was killed by `SIGTERM` on any window with >~130–147k training rows (3 of 6 in CODESPACE RUN 3), always at the same point: constructing the dense `(rows, 30, 66)` sequence tensor. A partial fix (freeing the parent process's held dataset) recovered one window but not the underlying ceiling. Root cause: `train_sequence.py::main()` built the full `sequences` array once but didn't extract the backtest split until ~250 lines later, so the ~1.08GB array stayed resident through the entire training loop on a machine with 7.8GB RAM and zero swap.

**Fix:** Moved backtest-split extraction up next to the train/validation splits, then `del sequences; gc.collect()` before training starts. Also switched `evaluation/model_predictions.py::build_sequence_windows()` from float64 to float32 to match `train.py`'s own dtype.

**Verification:**
- Re-ran `train_sequence.py` standalone against the 3 largest windows (146,868 / 153,696 / 160,219 rows) — all succeeded on first attempt
- `walk_forward_summary.json` regenerated at the full 6/6 windows; sequence Sharpe for windows 3–5 moved from multitask-fallback values (0.91, −0.26, −0.26) to real sequence-model values (0.39, 0.62, 1.47), all positive

---

### 84. Rank heads were sigmoid-squashed at inference but trained raw against an MSE target

**Severity:** 8/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** `train.py`'s rank heads (`rank_5d`/`rank_20d`/`sector_neutral_rank_20d`) trained with raw linear output against a `[0,1]` percentile target, but the export step wrapped every rank head in a leftover `"sigmoid"` layer — compressing live `predicted_rank_20d` into roughly `[0.475, 0.75]`. This silently tightened `min_rank_confidence_spread` ~4x, capped confidence near 0.5, and zero-sized bottom-ranked shorts. Invisible to rank-quality gates because rank-IC is invariant under monotone transforms.

**Fix:** Export activation changed from `"sigmoid"` to `None` for every rank head; added per-bar cross-sectional percentile normalization at inference (`portfolio/rank_signal.py::cross_sectional_rank_scores()`), since a pure ranking loss makes the head's absolute output scale meaningless by construction.

**Verification:**
- Manual code/architecture fix; no backtest cited in this entry

---

### 85. `sector_mapping.json` covered 29 of the universe's 104 assets

**Severity:** 6/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** 75 of 104 tickers (all 15 forex pairs, most crypto, most equities) defaulted to `"Unknown"`, making `target_sector_neutral_rank_20d` (a live head, `loss_weight: 0.3`) nearly a duplicate of plain `rank_20d` for 72% of the universe, while genuinely small sectors NaN'd out under `min_sector_size: 3`.

**Fix:** Expanded to a full 104-ticker mapping (GICS-like buckets for equities, `Forex`/`Crypto`/`Fixed Income`/`Broad Market ETF` for the rest); `AAA` left deliberately unmapped as a documented ambiguous legacy ticker.

**Verification:**
- Manual code/config review; no backtest cited in this entry

---

### 86. The constructed book was silently truncated by `max_active_positions`, not by rank

**Severity:** 5/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** `portfolio_book.top_n=10 + bottom_n=10` requests 20 names, but `max_active_positions=15`, and `_apply_signal()` rejected the excess in `self.symbols` iteration order — an accident of universe ordering, not conviction.

**Fix:** Config presets now set `max_active_positions >= top_n + bottom_n`; when the cap does bind, Pass 2 sorts candidates by rank-confidence first so the strongest convictions survive.

**Verification:**
- Manual code/config fix; no backtest cited in this entry

---

### 87. `capacity_curve()`'s binding-ticker search let a forex pair's fake zero dollar volume dictate the whole book's capacity

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `evaluation/rank_book_simulator.py::capacity_curve()` picks the lowest-average-dollar-volume held name as the binding constraint. Forex pairs always report `liquidity_log_dollar_volume == 0.0` (Yahoo Finance reports no FX volume), so any forex pair in the book automatically won that search, producing sub-$1 `capacity_usd` (0.3–0.6 observed) and failing every promotion gate regardless of the rest of the book's real liquidity. Secondary bug: the correct inverse of `log1p()` is `np.expm1()`, not `np.exp()` (used instead).

**Fix:** Tickers with `liquidity_log_dollar_volume == 0.0` exactly are now excluded from the binding-ticker search (true zero means no real liquidity signal, not "most illiquid"); `np.exp` → `np.expm1` fixed alongside it.

**Verification:**
- 3 new tests in `tests/test_rank_book_simulator.py` (zero-volume exclusion, all-zero fallback, exact value distinguishing `expm1` from `exp`)

---

### 88. A pre-backtest review found six critical bugs in code/config that had never executed a Lean bar

**Severity:** 9/10 · **Status:** 🟢 `fixed`

**Problem:** A pre-Lean-backtest review of every config value switched on this session (net-edge gate, calibrated cost model, kill switch, reconciliation) found six defects that together would have produced a half-dead book that locked up early and stayed locked: (1) `expected_edge_bps()` measured only long-side edge, vetoing every short unconditionally; (2) `--calibrate-edge` regressed against `target_return_1d` instead of the configured `horizon_days` (20), understating edge ~14x; (3) the kill switch never enforced `evaluation_bars` as a minimum sample for rolling Sharpe, tripping on bar 2–3; (4) reconciliation compared pre-sizing book weight against every held security, a self-sustaining false-drift lock; (5) slippage-divergence measured the overnight gap (fill vs. prior close) instead of true slippage (fill vs. next open); (6) `corporate_action_payload` leaked across symbols in the Phase 1c loop via a stale outer-scope variable. A seventh, adjacent config issue: `sector_max_net_weight: 0.05` was tighter than `max_weight_per_name: 0.12`, silently shrinking book exposure.

**Fix:** Added a `trade_direction` parameter to `expected_edge_bps()`/`build_net_edge_decision()`; `--calibrate-edge` now regresses on `target_return_{horizon_days}d` (`edge_bps_per_rank_unit` moved 28.2→396.3); kill switch gained a `min_bars_for_sharpe` floor; reconciliation now captures the final post-sizing `target_weight` per symbol via a new `_realized_target_weights_by_symbol` and restricts the broker side to `asset_lookup`'s key space; slippage-divergence trigger set to a never-fires sentinel pending a reliable fill-time reference (data collection stays on); `corporate_action_payload` carried through the `pending` list like `topology_payload`/`regime_payload`; `sector_max_net_weight` raised to 0.15 and `apply_book_neutrality()` gained a `>0.0` precondition (closing a config path back into #81's bug).

**Verification:**
- New/extended targeted tests in `test_cost_model.py`, `test_kill_switch.py`, `test_reconciliation.py`, `test_book_neutrality.py`; full suite 2392 passed
- `main.py` itself has no direct unit-test coverage by convention — verified via `py_compile` only
- Not yet re-verified with an actual Lean backtest

---

### 89. The book went dead after 3 weeks in the first real V5.1 Lean backtest — two more bugs found and fixed, one root cause still open

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** The first real Lean backtest after #88's fixes (2019-01-01→2021-03-31) opened 4 positions in January 2019, closed them ~2 weeks later, then placed zero new orders for the remaining 2.2 years (Sharpe −61.3, 8 total orders). Two bugs confirmed: `risk/kill_switch.py::_rolling_sharpe()` was numerically unstable on near-zero-variance return windows (mostly-flat post-liquidation returns made `mean/std*sqrt(252)` explode, e.g. swings to ±2.25 from noise alone) and the trip is sticky by design; and `min_rank_confidence_spread: 0.2` was a guessed constant the offline simulator hardcoded to `0.0`, so it had never been exercised against real data before shipping.

**Fix:** Added a `min_return_std_for_sharpe` floor (default 0.0005) to the kill switch, composable with the existing bar-count guard. Added `aq evaluate --calibrate-book-spread`, deriving the threshold from real per-date raw-score dispersion via a new shared `compute_confidence_spread()`; the calibrated value came back 0.5014 (vs. the guessed 0.2/0.18), applied to base config and both presets. Also fixed a `cmd_evaluate()` bug where `--calibrate-book-spread` alone incorrectly also triggered a full `--rank-book` run.

**Verification:**
- Full suite green (2412+ passed)
- Follow-up real Lean backtest confirmed trading resumed and continued for 14 months (768–1106 orders) instead of dying after 3 weeks — both fixes real and effective
- Open caveat: the calibration result (spread clears 0.2 on nearly every date) contradicted the original "compressed raw scores" hypothesis, so the exact January-2019 cutoff mechanism was not confirmed here — see #90/#91 for the larger gap this exposed next

---

### 90. A real Lean backtest, once it finally traded continuously, showed Sharpe -4.2 to -4.4 against a +2.18 offline number — three compounding mechanisms found and fixed (V5.2.1)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (V5.2.1; the investigation this entry's own open caveat seeded was continued and closed through #91-#93)

**Problem:** With #89's fixes, the book traded continuously but Sharpe was −4.42 (gated)/−4.18 (bypassed) against +0.26 to +2.18 offline. Three compounding mechanisms: (1) offline never modeled the ~1-bar execution lag (live fills at the next bar's open); a live `MarketOnCloseOrder` fix was ruled out as impossible at Daily resolution; (2) V4.3.0 position-scaling fired resize orders on non-rebalance bars, pushing live order count (768–1106) far above offline's rebalance-only assumption; (3) the cost gate under-costed those resizes against Lean's real floor-dominated commission (~$0.85–1.09/order).

**Fix:** `simulate_rank_book()` gained opt-in `entry_lag_bars`; new `is_position_resize_permitted()` gates resizing to rebalance bars only; cost gate's `order_value` now reflects the actual incremental trade delta.

**Verification:**
- Full suite green (2428 passed).
- Update: follow-up real backtest (2026-08-07) showed Sharpe −4.421 — essentially unchanged. All three mechanisms empirically ruled out as the explanation — see #91 for the ground-truth diagnostic tool built next.

---

### 91. Book-history reconciliation (V5.2.2/V5.2.3) finds two unexplained live-vs-offline selection divergences

**Severity:** 9/10 → 2/10 · **Status:** 🟢 `mostly fixed and verified` — crypto/FX divergence resolved (V5.3.1/#97); NVDA/GE/WFC/XOM/BA root-caused (#100) and confirmed live in a real backtest (#102): GE/BA/NVDA/WFC all substantially improved. XOM's residual divergence stays 🟡 open (thin sample)

**Problem:** After #90's fix failed to close the Sharpe gap, a new reconciliation tool (`aq evaluate --reconcile-book-history`) ran against a real backtest (112 dates) and found: (1) crypto/FX in offline's top/bottom-6 on 107/112 dates but live's book on 0/112; (2) equities-only overlap only 34.6–54.8%, independent of crypto/FX.

**Fix:** V5.2.4 — `self.bar_index` incremented on every asset-class tick instead of only equity session bars; fixed via `self.is_equity_session_bar` gating (fixed ~20+ downstream consumers for free), plus a force-sell bug (empty `book_allocations` sold the whole book, not just rotate-outs), plus crypto/FX made book-eligible via last-known-bar processing. V5.2.5 — fixed `bond_empirical_duration_beta` recomputing every bar instead of compute-once-broadcast, via `should_lock_in_duration_beta()`.

**Verification:**
- V5.2.4: orders/fees roughly halved (392 vs 768), Sharpe −4.42→−4.10, overlap 34.6%→49.3% (53.8% hysteresis-replayed).
- V5.2.5: overlap barely moved (48-50%) but Sharpe improved −4.10→−3.35 (~18%).
- V5.3.1 (#97/#98): crypto/FX divergence confirmed a stale-log measurement artifact, not a live bug — resolved. NVDA/GE/WFC/XOM/BA: sector-neutrality ruled out by direct code proof; remains genuinely unexplained.
- V5.3.2 (#99): two real reconciliation-tool bugs found and fixed (cross-run log contamination, live-vs-offline tie-break order) — neither explains this divergence. Real measured evidence now points at a genuine raw-score computation discrepancy for these 5 tickers specifically, not a selection-boundary artifact. Still open.

---
### 92. Deep-dive into the remaining NVDA/GE/WFC/XOM/BA/forex/crypto divergence finds crypto/FX never actually trade, and a systemic live-vs-offline risk-gate gap (V5.2.6)

**Severity:** 10/10 · **Status:** 🟢 `fixed` (V5.2.6)

**Problem:** Crypto/FX were regularly selected into the book but never placed a single real order — forex's synthetic quote-bar conversion hardcodes `volume=0.0`, tripping the liquidity gate's zero-volume block. Separately, live carries ~10 risk/execution gates offline's Sharpe engine never models, two of which duplicate signal the model already has as an active input feature.

**Fix:** Added `zero_volume_fallback_ddv` (forex always, crypto only `quality_tier=="core"`) substituting a realistic daily-dollar-volume estimate without bypassing the real participation/cost gates. Added book-selection-aware confidence thresholds, narrowed `risk_off`/`topology_elevated` overrides using real-data-derived thresholds, shipped `aq evaluate --calibrate-confidence-threshold` + a `book_member_decisions` diagnostic.

**Verification:**
- 33 new tests; full suite 2530 passed.
- Real backtest (2026-08-10) confirmed Sharpe -4.103→-2.984. A first attempt crashed on a genuine deferred-write bug (`spread_check_ranks` UnboundLocalError), only catchable via a real bar-to-bar Lean run — fixed, re-run succeeded.
- Surfaced two further bugs (forex order sizing, sticky kill-switch lockout) — see #93.

---

### 93. Forex order sizing rounds to zero at realistic book scale, and a sticky kill-switch trip locks out the book for 13+ months (V5.2.7)

**Severity:** 9/10 · **Status:** 🟢 `fixed` (V5.2.7)

**Problem:** `_forex_lot_count_for_weight()` divided notional by a full 100,000-unit lot's dollar value — at realistic 4-12% position weights, notional never reached one lot, so every forex order silently rounded to zero. Separately, a kill-switch trip on 2020-02-27 never auto-cleared and locked 100% of book-member decisions into `reduce_risk` for the remaining 13 months.

**Fix:** New `compute_forex_order_units()` sizes orders in raw base-currency units instead of lots (an earlier lot-rounding design was caught in review — it would have reproduced the same bug under a new name). Split `bypass_safety_gates` into `bypass_sticky_trade_lock`/`bypass_regime_drawdown_gate`; enabled only the sticky-lock bypass this round to isolate its effect.

**Verification:**
- 18 new tests; full suite 2523 passed.
- Real backtest (2026-08-11) confirmed Sharpe -2.984→-2.17. `notional_ratio` within 0.15% of 1.0 across 193 records; 220 real forex fills across 9 pairs for the first time ever.
- Kill-switch now trips 26 times and clears every time (vs. once, stuck forever).
- Crypto (BTCUSD/LTCUSD) still never trades — a separate, unresolved Lean/Coinbase zero-volume delivery quirk, out of scope.

---

### 94. Kill-switch sensitivity sweep, an offline gate-aware replay, a training-side gate-aware ranking weight, and continued NVDA/GE/WFC/XOM/BA + overlap-metric investigation (V5.2.8)

**Severity:** n/a (investigation + opt-in tooling, no defect) · **Status:** 🟢 `fixed and verified`

**Problem:** Continues #91-#93: is the kill-switch's 26-trips/2.2yr cadence mistuned or just how this model behaves; could a "gate-realistic" training signal be built offline; NVDA/GE/WFC/XOM/BA and the overlap metric's continued erosion remain unexplained.

**Fix:**
- New `evaluation/kill_switch_replay.py` (`aq evaluate --replay-kill-switch`) — day-by-day offline replay of the kill-switch + sticky trade-lock state machine over the rank book's own returns. Deliberately approximate (dataset-derivable inputs only, no bypass flags).
- New `train.py::compute_gate_friendliness_weight_by_date()` — optional per-date training-loss weight from the stateless topology/regime-severity gates; threaded through as `date_weights` (`None` default = byte-identical), gated behind `gate_aware_ranking_weights.enabled` (default `false`).
- Sensitivity sweep (20 combos): lockout is near-binary — a trip either never happens or locks out ~58-74% of the remaining window. #93's 26-trip *bypassed* result is fully explained by the bypass, not a discrepancy. No config change applied.
- NVDA/GE/WFC/XOM/BA re-checked against real V5.2.7 data — all 5 still recur; the one reusable lead (bond-duration-beta) was ruled out. Both threads remain unexplained.

**Verification:**
- 33 new tests, full suite 2523→2556. `--replay-kill-switch` matches the sweep's own baseline end-to-end.
- Overlap-metric erosion (49.96%→48.59%) reconfirmed — root cause still open.
- Codespace smoke test (3 epochs, flag on) and 6-window `--walk-forward` both ran clean, but neither is a verdict on the flag at production (120/60-epoch) scale — no flag-off control ran.

**Follow-ups:** full state-machine replay; root-causing NVDA/GE/WFC/XOM/BA and the overlap metric.

### 95. Full-scale production retrain with gate-aware ranking weights promoted to active `ml/`; RL sizing re-confirmed negative a third time; full-epoch walk-forward validation (V5.2.9)

**Severity:** n/a (production training round, no defect) · **Status:** 🟢 `fixed and verified`

**Problem:** #94 shipped the flag off by default, verified only via a 3-epoch smoke test with no flag-off control — open whether it holds at real (120/60-epoch) scale, and whether a full training/validation/promotion cycle was ready. Topology training needs a real Lean backtest's experience events through local Postgres/Redis — out of scope (user instruction).

**Fix:** Enabled `gate_aware_ranking_weights.enabled: true` (user's explicit choice). Full Codespace candidate pipeline at real epoch counts (baseline/gating/multitask/sequence/RL sizing); `train_strategy_selector`/`train_topology` skipped (no Postgres/option data, no Lean experience events). Promoted to active `ml/` (backed up to `ml/_backup_pre_v529_full_retrain/`). Full 6-window `--walk-forward` at the same settings, validation only.

**Verification:**
- vs. prior model: rank_5d IC 0.097→0.109, rank_20d IC 0.152→0.173, sector-neutral/residual ranks also up. Direction MCC regressed slightly — dataset refresh and the flag both changed at once, not cleanly attributable. Net judged positive.
- RL sizing: honest-negative reproduced a third time. Stays disabled.
- Walk-forward: rank_20d_ic mean 0.085 (stable, 0% sign flips), net Sharpe mean ~0.65 (5/6 windows positive).
- Active `ml/` now runs the new candidate; topology untouched. Rollback available.

**Follow-ups:** representative Lean backtest (user, manual); topology-training backtest; isolating dataset-refresh vs. flag effect.

---

### 96. Real limit-order support: stale docs corrected, `PartiallyFilled` made testable, two new offline diagnostic tools (V5.3.1, closes #34)

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified`

**Problem:** `phase_v2.limit_orders.enabled` was actually `true` by default all along, but `Problems.md`/`Changelog.md`/`execution/README.md`/a `main.py` comment all claimed "default off." `PartiallyFilled` had never fired in 45 real backtests, and `main.py`'s partial-fill logic wasn't unit-testable at all (not importable outside a real Lean process).

**Fix:** Corrected the stale docs. Investigated the future/option `fallback_to_market_on_timeout=false` asymmetry — found a real, deliberate rationale already in `main.py` (margin/expiry risk) and left it unchanged. Extracted `should_clear_pending_limit_order()`/`resolve_limit_order_timeout_action()` into `execution/order_gate.py`, wired into `main.py` (behavior-preserving) — makes the partial-fill contract unit-testable for the first time. Shipped two new offline diagnostics: `evaluation/limit_fill_simulator.py` (`aq evaluate --simulate-limit-fills`) and standalone `scripts/order_events_audit.py`. Left `max_slippage_divergence_bps` deliberately uncalibrated (synthetic fill data would answer a different question than real slippage).

**Verification:**
- 26 new tests; full suite green (see #97 for the combined count).
- `--simulate-limit-fills` vs. real dataset: 82.95% fill rate, directionally consistent with real order-events evidence. `order_events_audit.py` reproduces the verified 23/23 `cancelPending`/`canceled` pairing across 43 real backtests.
- 2026-08-14 real backtest (#98) ran this exact refactored code live for the first time: `cancelPending`/`canceled` still pair 12/12, zero regressions. `PartiallyFilled` still never appeared — permanent, expected caveat (Lean's Daily-resolution fills), not a defect.

---

### 97. Book-history reconciliation: bond duration-beta's deeper cold-start bug, reconciliation-tool eligibility fix, FX/crypto absence resolved (log artifact), misleading kill-switch count corrected (V5.3.1, continues #91-#95)

**Severity:** 9/10 → 2/10 · **Status:** 🟢 `mostly fixed and verified` (bond warm-up fix verified, see #98; NVDA/GE/WFC/XOM/BA root-caused and confirmed live, see #100/#102 — XOM's thin-sample result stays open)

**Problem:** Beneath the already-shipped V5.2.4/V5.2.5/V5.2.7 fixes, two real bugs remained: `bond_empirical_duration_beta`'s cold-start window, and the reconciliation tool's own hardcoded eligibility assumption. A third suspected cause (FX/crypto missing from book candidacy) turned out to be a measurement artifact. A fourth surfaced along the way: V5.2.10's "0 real kill-switch trips" README claim was never a real measurement.

**Fix:**
- **Bond warm-up floor** (`main.py:598`, `21`→`self.long_bar_history_size`=260): the two `maxlen=260` deques feeding the beta fill during warm-up too (no `is_warming_up` gate), but the old floor left them far short of full, locking the beta at `0.0` for ~230 bars/backtest. Bonus: fixes the identical cold-start gap for `cross_asset_sensitivity` for free.
- **Reconciliation eligibility fix**: `reconcile_book_history_date()`/`replay_book_history_reconciliation()` now read real per-date `trading_eligible` from `book_history.jsonl`'s `"universe"` field instead of hardcoding `True`.
- **FX/crypto ruled out as a live bug**: new run-segmented `summarize_universe_presence_by_symbol()` shows 100% absence only in one old pre-V5.2.4 run, 0% since — the "32% absent" figure was a cumulative-log averaging artifact, wired into `--reconcile-book-history`'s output so it can't hide again.
- **Kill-switch count corrected**: `_count_real_kill_switch_trips()` now always returns `None` (the real event is Redis-only, never reaches the text log it was counting) instead of a fake `0`.
- **NVDA/GE/WFC/XOM/BA**: sector-neutrality ruled out by direct code proof (`apply_book_neutrality()` only reweights an already-selected book) — remains unexplained.

**Verification:**
- 11 new tests; combined with #96, full suite 2574→2609, 0 failures.
- Bond warm-up fix: confirmed via a real A/B backtest — see #98 (Sharpe -1.72→-1.034, orders roughly halved, no downside found).
- Reconciliation eligibility fix: correctly applied, zero net effect on `mean_overlap_fraction` (24.02%) — #98 later found this re-run's target was itself a contaminated multi-run log, so the code fix stays verified via unit tests but 24.02% isn't a clean single-run number.
- FX/crypto segmentation reproduced by hand and by tests.

**Follow-ups:** NVDA/GE/WFC/XOM/BA remains open — next lead is the ranking/hysteresis path itself, not gates or neutrality. See #99 (V5.3.2) for two real reconciliation-tooling bugs fixed and what they did (and didn't) explain.

---

### 98. Real V5.3.1 backtest (2026-08-14): Sharpe improves again; a suspected new "7-month disengagement regression" turns out to be pre-existing, not caused by B1 — corrects a same-session investigation error

**Severity:** 4/10 · **Status:** 🟢 `fixed and verified` (B1 specifically); the underlying gap's root cause stays 🟡 open, see Follow-ups

**Problem:** The first real V5.3.1 backtest (`backtests/2026-08-14_18-46-38`, Sharpe **-1.034**) initially looked like a severe new regression: only 11 new `book_history.jsonl` records, orders down to 230 (from 476), an apparent ~7-month engagement gap from 2019-01-01. The comparison target, `book_history_v529_only.jsonl`, turned out to be an undiscovered 7-run cumulative log — the same contamination class #97/B2 already fixed elsewhere, missed here initially.

**Fix (self-correction):** Isolated the true immediately-prior real backtest (`backtests/2026-08-13_11-30-21`, Sharpe -1.72) and found the identical signature in its own `order-events.json`: a 202-day gap, same re-engagement dates. `git diff` confirms `main.py`'s only functional changes between the two runs were #96's refactor (behavior-preserving) and #97's warm-up floor — `config.json` unchanged. Clean A/B result: gap shrank (202→169 days), orders roughly halved, Sharpe improved (-1.72→-1.034). No evidence the warm-up fix caused or worsened anything.

**Verification:**
- Gap analysis run directly against both real backtests' own `order-events.json` (not the cumulative log) — pre-B1 202-day gap, post-B1 169-day gap.
- Record-diff confirms the isolation methodology was sound; only the comparison target was wrong.
- Isolated reconciliation re-run (11 genuinely-new records): `mean_overlap_fraction` 35.08%, 0/11 exact matches — real number, too thin a sample to compare against #97's contaminated 24.02%.
- #97's other fixes re-confirmed clean: FX/crypto 0% absent, kill-switch count correct.

**Follow-ups:** why `min_rank_confidence_spread` (0.5014) rejects nearly every selection for ~7 months starting January 2019 is a genuine open question — pre-existing, not a regression, scoped as its own future investigation.

**Update (V5.3.2) — closed, documented not a bug:** `ml/sequence_training_metrics.json` and `ml/multitask_training_metrics.json` both carry a `backtest.<head>_ranking_quality.observed.per_era` diagnostic (#71). Checked all 4 combinations (sequence/multitask × rank_5d/rank_20d): every one independently shows strong, significant IC in era 0 (2019-01-01→2019-03-31, t≈2.5-3.1), a simultaneous collapse to statistically-insignificant IC in eras 1-2 (2019-04-01→2019-09-27, t between 0.09 and 0.87), then a sharp recovery in era 3 (t up to 6.7) — the exact window the real backtests disengage in. Four independently-trained model/head combinations agreeing this precisely rules out a model-specific quirk: this is a genuine low-dispersion, near-zero-edge stretch in the real historical data, and `min_rank_confidence_spread`'s entire documented purpose is to refuse trading exactly when this happens. No code change to the gate itself. Also ruled out this round as alternate causes: the regime/drawdown gate (`bypass_regime_drawdown_gate`) is stateless, per-symbol, per-bar, and never empties `book_allocations` — confirmed via `main.py:4493-4521`/`main.py:2770-2775` — so it cannot produce a total, zero-log-entry gap; the sticky kill-switch lock has been bypassed since #93 and confirmed clearing every time, not sticky. The sequence model's zero-padding during its own ~30-live-bar post-warmup fill (`main.py:3496-3507`) is real but far too small to be the cause (30 bars vs. the ~187-260 day observed gap), and is deliberate train/serve parity with `train.py` — not changed.

**Bonus, quantified finding — not applied this round:** the currently-active rank head is `rank_5d`, not `rank_20d` (`rank_20d` is demoted for era-sign instability, confirmed via `resolve_rank_signal_policy()`). `min_rank_confidence_spread=0.5014` was calibrated once in #89, before this demotion existed. Re-running `aq evaluate --calibrate-book-spread` against the *current* active head returns **0.2901** — and the natural per-date spread's own median is **0.36**, already below the live threshold. This means the current 0.5014 is likely rejecting a meaningful share of *all* dates, not just the genuine Apr-Sep 2019 no-skill stretch — real and worth a future round, but deliberately not applied to `config.json` here (no real Lean backtest available this round to verify its actual effect on engagement/Sharpe, and bundling it would have confounded #99's reconciliation-fix comparison).

---

### 99. Reconciliation tool's own cross-run contamination and live-vs-offline tie-break order fixed; NVDA/GE/WFC/XOM/BA re-measured — neither bug explains it, but the real evidence now points somewhere new (V5.3.2, continues #91/#97)

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` (the two tooling bugs); NVDA/GE/WFC/XOM/BA's new lead was chased down, fixed, and confirmed live in a real backtest, see #100/#102 — XOM's thin-sample result stays open

**Problem:** Beneath #97's fixes, two real bugs remained in the reconciliation *tooling itself* (not the live decision path): (1) `--reconcile-book-history`/`--replay-hysteresis` deduplicated dates across `visualization/book_history.jsonl`'s entire cumulative history (last-write-wins) before reconciling — confirmed empirically: of 469 real records / 174 unique dates, **160 dates (92%) recur across more than one historical run**, one date in as many as 8 — so the hysteresis walk silently carried `held_allocations` across real run boundaries as if one continuous backtest, and every overlap number this project has ever reported for this tool was measuring a contaminated mix. (2) `cross_sectional_rank_scores()`/`_select_book_group()` are Python-stable sorts keyed only on rank, so an exact tie resolves by the caller's raw-scores dict insertion order — live builds that dict in `self.symbols`' fixed universe order (`config.json`'s `phase1.universe.assets`), but the reconciliation tooling built it from a pandas `groupby` (dataset row order), a different, uncorrelated order. A tied pair near a top/bottom-N boundary could pick a different winner live vs. offline with byte-identical scores.

**Fix:**
- New `evaluation/rank_signal_calibration.py::segment_logged_records_by_run()` (extracted from #97's `summarize_universe_presence_by_symbol()`, itself refactored to use it — behavior-preserving).
- `aq_cli.py`'s `--reconcile-book-history` dispatch (both the hysteresis-replay and independent-per-date paths, which shared the same contaminated construction) now segments first and defaults to the **most recent run only** — never a silent cross-run merge. New `--reconcile-run-index N` (0-indexed, negative from the end) and `--reconcile-all-runs` (every run independently, never merged) flags. Default JSON payload shape stays byte-identical, additively gains `run_metadata`; `--reconcile-all-runs` additively appends `all_runs`.
- `aq_cli.py`'s raw-scores construction now re-inserts each date's scores in `config.json`'s `phase1.universe.assets` order (the same source `main.py` derives `self.symbols` from) before they reach `cross_sectional_rank_scores()` — zero changes to the live decision path itself (`portfolio/rank_signal.py`/`portfolio/book_construction.py` untouched), since live was already internally consistent and the gap was purely in offline tooling.
- `replay_book_history_reconciliation()`'s docstring updated to state its input must be a single run's own records, never the raw cumulative file.

**Verification:**
- 12 new tests (`test_rank_signal_calibration.py`: 4 for `segment_logged_records_by_run()`; `test_aq_cli.py`: 7 for run-isolation/flags + 1 tie-break fixture proving reconciliation now follows configured-universe order instead of dataset row order; `test_portfolio_book_construction.py`: 1 documenting `build_rank_based_book()`'s tie-break is deliberately insertion-order-dependent). Full suite 2609→2624, 0 failures (11 pre-existing Docker-unavailable errors unrelated to this round).
- Re-run against the real `visualization/book_history.jsonl` (8 runs detected, matching the hand count above): default (most-recent run, 11 dates) reproduces the earlier hand-isolated 35.08% overlap exactly — confirms the fix is correct, not just plausible. `--reconcile-all-runs` shows overlap 21-35% across all 8 runs individually — fairly stable, so #97's old contaminated 24.02% figure wasn't wildly off in *magnitude*, just methodologically invalid.
- **NVDA/GE/WFC/XOM/BA, measured on the densest real run (112 dates):** both bugs fixed, but neither explains this divergence. Mismatch rates stay high (XOM 93%, WFC 78%, NVDA 69%, GE 52%, BA 48% of their appearances) and, critically, on the dates these 5 tickers **do** appear matched on both sides, their raw-score deltas are large (0.11-0.21 on a [0,1] percentile scale) — a genuine tie-break artifact would show near-*zero* deltas on matched days and only flip the rare truly-tied day. Also strongly directional: "live selects it, offline's fresh re-derivation doesn't" outnumbers the reverse roughly 4-5:1 for all 5 tickers, sustained across the whole 2+ year run, not just near run boundaries (rules out a cold-start artifact too).

**New lead (not yet root-caused):** the evidence now points at a real, persistent raw-score computation discrepancy between live and offline for these 5 tickers specifically, not a selection-boundary artifact of any kind. Next step for a future round: compare live's rolling-window feature computation (`main.py`'s deques) against offline's dataset-precomputed features for these 5 tickers directly, looking for a data/feature-pipeline difference specific to them (e.g. corporate-action history, a data-vendor discontinuity, or a rolling-window fill difference) rather than continuing to look at gates, hysteresis mechanics, or tie-breaks — all three are now ruled out by direct evidence across #91/#97/#99.

**Update (V5.3.2) — root cause found for 4 of 5 tickers, see #100.** The next-lead comparison above found it: 63 of 77 equity tickers had no local Lean split/dividend factor file, silently leaving offline's training data unadjusted while live was always correctly adjusted. See #100 for the fix and the real, measured (mixed but net-positive) improvement.

---

### 100. Missing Lean split/dividend factor files for 63 of 77 equity tickers — offline trained on raw, unadjusted prices while live was always correct (V5.3.3, continues #91/#97/#99)

**Severity:** 7/10 → 2/10 · **Status:** 🟢 `fixed and verified` — real backtest confirms it live for GE/BA/NVDA/WFC, see #102. XOM and NVDA's residual divergence stay 🟡 open (small-sample/unexplained, not this bug)

**Problem:** `train.py::apply_split_adjustments()` backward-adjusts OHLCV using a local Lean factor file (`data/equity/usa/factor_files/<ticker>.csv`) — the same adjustment `main.py`'s live feed already gets automatically via Lean's `DataNormalizationMode.Adjusted`. Missing file → silent no-op (`load_factor_file()` returns `None`) → offline trains on **raw, unadjusted prices**. Of 104 configured assets (77 equities), only 22 had a local file; the other 63, including all 5 of #91/#97/#99's tracked tickers, didn't (a local/incomplete data pull, not a deliberate decision). Confirmed via real yfinance data: XOM/WFC/BA all paid material uncorrected dividends in-window; GE additionally had a real 2019-02-26 corporate action (the Wabtec spinoff). Each produces an artificial return-dip offline never corrected, matching the observed live-favors-these-tickers bias exactly. NVDA's dividend is negligible and its splits are both outside the window and mathematically invariant to return-ratio features — **not explained by this mechanism**, reported honestly.

**Fix:** New `data_pipeline/factor_file_backfill.py` (mirrors `dividend_backfill.py`'s `--apply`/dry-run convention) derives real Lean-format factor files from yfinance's dividend/split history. Run for real: 63 new files written, zero fetch failures. `aq train --dataset-only` regenerated `ml/datasets/*.csv` — zero changes needed to `train.py` itself. `min_rank_confidence_spread` recalibrated fresh against the corrected dataset and applied to `config.json` (all 3 locations, including two preset copies `aq config set` can't reach — required a direct JSON edit).

**Verification:** 14 new tests, full suite 2624→2638. Mechanical fix confirmed on real ex-dividend dates (the artificial dip disappears, replaced by a correction matching the event's own magnitude to 2 decimal places). Offline re-measurement showed mixed-but-net-positive improvement; **a real backtest (#102) then confirmed it far more strongly live**: GE mismatch 52%→15%, BA 48%→12%, NVDA 69%→25%, WFC 78%→55% — all real, substantial, measured in a genuinely fresh live run. XOM showed a concerning 100% mismatch but on only 9 appearances, too thin to conclude anything.

**Follow-ups:** XOM's small-sample result and NVDA's residual divergence need a larger sample / different mechanism respectively. A full model retrain on the corrected dataset stays out of scope (Codespace-only).

---

### 101. `aq evaluate --all`'s non-JSON reporting crashed on Windows — a Greek Δ character isn't in the cp1252 console codec

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** Refreshing the README's offline evaluation numbers post-#100 (`aq evaluate --all --model sequence`/`--model multitask`, non-`--json`) crashed both runs with `UnicodeEncodeError: 'charmap' codec can't encode character 'Δ'` — `aq_cli.py`'s "lag tax" delta-print line (`f"  Δnet_sharpe vs entry_lag_bars=0: ..."`) used a literal Δ, which isn't in Windows' default `cp1252` console codec (unlike the em-dashes used safely elsewhere in this file). The crash happened mid-`--all`, after rank-book's own reporting but *before* capacity/stress/calibrate-edge ran and before the README refresh call — so every `--all` run on a real Windows console had been silently leaving capacity/cost-stress numbers stale and the README never refreshed, with no error surfaced anywhere but stderr.

**Fix:** Replaced the Δ with the ASCII `delta_net_sharpe` label.

**Verification:** `python -m py_compile aq_cli.py` clean; `tests/test_aq_cli.py` (216 tests) still green; both `--all` re-runs (sequence and multitask) completed end-to-end afterward with no crash, correctly refreshing capacity/cost-stress/README sections that had been silently stuck since Aug 13.

---

### 102. Real V5.3.3 backtest (2026-08-17): factor-file fix strongly confirmed live for 3-4 of 5 tracked tickers — but the confidence-spread recalibration made real Sharpe measurably worse, isolated cleanly to that one change

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` (factor-file fix, #100, for GE/BA/NVDA/WFC); 🔴 `regressed` (confidence-spread recalibration) — recommend reconsidering the applied value

**Problem:** #100 shipped two changes: the factor-file fix (verified only offline) and an applied recalibration of `min_rank_confidence_spread` (0.5014→0.2831, verification explicitly deferred to "the user's own real backtest run"). That backtest ran (Docker/`aq backtest`, 2019-01-01→2021-04-02, ~6.8 hours). Since the factor-file fix never touches `main.py`'s live path (confirmed in #100), and no other code changed between this run and the prior real one (`backtests/2026-08-14_18-46-38`), this is a clean, single-variable A/B on the recalibration alone.

**Result — real, measured, not assumed:**
- Orders 230→**695** (mechanically as predicted — the lower threshold re-engages far more dates: 130→**360** unique trading days, max gap 169→**65** days).
- Sharpe **-1.034→-1.798** (worse). Net Profit -1.60%→**-5.51%**. Drawdown 5.10%→**6.90%**. Total Fees $335→$880 (more than doubled, tracking the order-count increase).
- Period attribution via the equity curve, same checkpoints both runs: the new run trades through 111 of ~124 days in the *known* no-skill era (2019-04-01→2019-09-27, confirmed via #98's own per-era IC diagnostic, t-stat 0.09-0.87 there) — equity fell **-1.71%** during that exact stretch this run, vs. only -0.53% in the prior run which mostly sat it out. The rest of the underperformance (most of it) comes from 2020-2021: prior run recovered post-COVID-crash (+0.47% Apr 2020→Mar 2021), this run kept declining (-3.27% over the same stretch) — likely the same mechanism, since the per-era diagnostic also shows era 4 (Dec 2019-Mar 2020) at **negative** IC (-0.048) and era 6 (Jun-Sep 2020) at t=0.297 (statistically indistinguishable from zero) — both now traded through where they weren't before.
- **Root cause of the regression, not just the symptom:** `min_rank_confidence_spread`'s calibration methodology (the natural per-date percentile of raw-score dispersion) measures whether the model differentiates symbols at all, not whether that differentiation is directionally *correct*. The per-era IC diagnostic shows real stretches where the model produces plenty of score spread but near-zero or negative predictive validity — natural dispersion and genuine skill are not the same thing, and this calibration approach can't tell them apart.

**Factor-file fix (#100), by contrast, strongly confirmed — better than the offline-only estimate suggested:** fresh `--reconcile-book-history --replay-hysteresis` against this run's own new `book_history.jsonl` (56 dates, the densest live reconciliation sample of this whole investigation): `mean_overlap_fraction` **56.9%** (highest of any run measured all investigation, vs. 21-49% previously) and `mean_raw_score_delta_abs` **0.019** (vs. 0.1-0.2 in every prior run). Per-ticker mismatch rates:
- **GE: 52%→15%**, **BA: 48%→12%**, **NVDA: 69%→25%** — all three now close to fully resolved, a dramatically stronger result live than the offline-only re-measurement in #100 predicted.
- **WFC: 78%→55%** — real improvement, smaller sample (11 appearances).
- **XOM: 65%→100% mismatch (9/9 appearances, 0 matched days)** — the one genuine outlier, but on a sample too thin (9) to conclude anything beyond "still worth watching" — not over-interpreted here.

**Recommendation:** revert or raise `min_rank_confidence_spread` back toward its pre-V5.3.3 level (or find a smarter calibration that accounts for per-era IC stability, not just raw-score dispersion) — the applied 0.2831 value is now shown, on real data, to trade through genuinely bad stretches the higher threshold was correctly avoiding. Do **not** revert the factor-file fix itself — that part is strongly validated. This is exactly the kind of single-variable, real-data-isolated finding this project's process is built to catch: a change that looked justified by its own calibration logic in isolation turned out to have a real, measurable negative effect once tested against live behavior.

**Verification:** all figures above pulled directly from the real backtest's own `1443519757.json`/`-order-events.json`/`-log.txt` and a fresh, run-isolated `--reconcile-book-history` call against its own `book_history.jsonl` — no figure in this entry is estimated or offline-only.

**Follow-ups:** decide and apply a revised `min_rank_confidence_spread` (or gating approach) in a future round, then re-verify with another real backtest; XOM's small-sample 100%-mismatch result needs a larger sample before drawing a conclusion.
