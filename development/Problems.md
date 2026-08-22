# Problems

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

Every entry follows **Problem** → **Fix** → **Verification** (real Lean backtest, unit tests, or manual review; standing convention: `main.py` itself has zero direct unit test coverage, so many Lean-adapter fixes are verified only by manual review or a real backtest).

---

### 88a. Lean CLI's generated Windows dependency mount was unreliable, and startup imported the training stack

**Severity:** 6/10 · **Status:** 🟢 `fixed` (V5.1.11)

**Problem:** On some Windows Docker Desktop hosts Lean CLI's generated temp `requirements.txt` mount could be rejected by Docker even though project files were readable; separately, `main.py` importing `performance` at module scope pulled the training/PyTorch graph into Lean's 90-second startup isolator window.

**Fix:** `aq backtest` builds cached local image with Redis pre-installed (no generated requirements mount); Windows wrapper grants Docker read access to Lean-created temp dirs; `main.py` imports `evaluate_all_triggers` only inside dashboard view. Follow-up added missing `httpx` to `requirements/lean-runtime.txt` (needed by `data_pipeline.fred_backfill`, post-last-known-good-backtest).

**Verification:** Regression tests cover both boundaries without real Lean runs. `httpx` add initially flagged unverified vs real backtest — since resolved: still present in `requirements/lean-runtime.txt`, `fred_backfill` still module-scope imported, 4 real backtests succeeded since (V5.2.4-V5.2.7) exercising this chain.

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

**Problem:** First-ever clean-install + bare-`pytest` CI run (vs local dev's populated `.venv`) surfaced three masked problems: nonexistent PyPI package name; pytest import-mode not adding repo root to `sys.path`; then 4 failures + 11 errors — reference files `futures_contract_specs.json`/`sector_mapping.json` swallowed by blanket `.gitignore` rule; genuine Python 3.11-vs-3.14 float-summation stdlib difference in `empirical_duration_beta()`; Lean-backtest skip-guard checking binary presence rather than usable Lean Data folder.

**Fix:** Corrected package (`lean>=1.0.225`); `pythonpath = ["."]`; `.gitignore` exception + committed both files; exact-zero variance check → `<1e-12` tolerance; skip guard requires real Lean Data file.

**Verification:** All 4 previously-failed tests + 3 new regression tests pass locally. **Confirmed: real GitHub Actions run passed** post-fix (user-confirmed).

---

### 11. `_write_state()`'s per-bar throttle was unreachable

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Dead guard clause meant 7 output files fully rewritten every bar instead of once per timestamp.

**Fix:** Removed impossible clause (`if ... and signals is None`).

**Verification:** Found during latency audit of `main.py` hot path.

---

### 12. `observation_equity_curve.csv` quadratic rewrite (N-per-bar entries + full-file rewrite every bar)

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `mark_to_market()` ran once per symbol per bar → `N·B` equity-curve entries instead of `B`; with #11's every-bar flush plus full-file CSV rebuild, write cost `O((bars·symbols)²)`.

**Fix:** `on_data()` accumulates closes, calls `mark_to_market()` once per bar; CSV writer replaced with append-only flush (`_flush_observation_equity_csv()`) tracked by written-count offset.

**Verification:** Unit test asserts one entry per multi-symbol call; row-count-equals-bar-count verified via real Lean backtest integration output.

---

### 13. Per-bar/per-poll `config.json` reads on every session rollover, uncached

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** At Daily resolution the once-per-session rollover check fires every bar, each firing doing uncached `open()`+`json.load()` of `config.json` in multiple places (`main.py`, `retraining/worker.py` poll loop).

**Fix:** New `execution/config_cache.py::read_cached()`, mtime-gated cache keyed `(config_path, loader)` — first path-only key collided across readers of same file, returning wrong values and crashing `_recompute_broker_config()` on bar 1 of a real backtest; fixed by keying on loader too.

**Verification:** New `tests/test_config_cache.py` (incl. collision regression); re-confirmed via real Lean backtest integration re-run.

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

**Problem:** Loading all model/expert/topology artifacts plus deriving ~40 config values inside `initialize()` pushed isolator-timed cost past Lean's non-configurable 90s cap at 20 assets — every `lean backtest .` failed.

**Fix:** Split into minimal Lean-critical path (dates/cash/subscriptions/warm-up) plus `_ensure_ready()` carrying artifact/config loading, deferred to first `on_data()` (no isolator limit there).

**Verification:** Disk-log instrumentation (`self.Debug()` inside timed-out `initialize()` is silently lost) confirmed `initialize()` completes in 1.85s, full window ~51s. Non-Lean suite (525 tests) green throughout.

---

### 17. Matplotlib font cache rebuilt from scratch on every single `lean backtest .` run

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Lean's `AlgorithmImports` bridge imports matplotlib; ephemeral per-run containers meant 20-40+s font-cache rebuild every run — occasionally breaching 90s isolator cap even after #16.

**Fix:** `main.py` sets `MPLCONFIGDIR` to host-mounted `.matplotlib_cache/` before any other import; cache survives containers.

**Verification:** Two consecutive real runs: cold-cache rebuild + ~82s import vs warm-cache none + ~58s import, zero timeout.

---

### 18. Two structural "never recovers" traps suppressed real backtest trade count to 12 over 3 years

**Severity:** 5/10 · **Status:** 🟢 `addressed` (opt-in statistical bypass, default behavior unchanged)

**Problem:** One-time mass liquidation crossing 12% total-drawdown limit froze trading remaining 374 days of 3-year backtest — sticky lock plus `peak_equity` running-max never falling meant lock could never self-clear. Earlier-firing (8%) twin existed independently in regime `risk_off` drawdown branch.

**Fix:** Opt-in `phase_v2.backtest.bypass_safety_gates` (default `false`, backtest-only) bypasses only these two mechanisms; other gates fully active; live/paper unaffected regardless of flag.

**Verification:** Deliberately not wired into `aq trade-lock` (separate pre-existing meaning); scoped to statistical/model-quality backtesting only, never representative of live behavior.

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

**Problem:** BTCUSD raw volume jumped ~520,000x one date (real Coinbase feed unit-convention change), producing 5.2-million-percent single-day "return" through unclipped `StandardScaler`, poisoning 30 rows of sequence sliding window — 66%+ of entire backtest squared error.

**Fix:** Three layers: clamp `volume_change_1d` to `[-1.0, 20.0]`; winsorize scaler-fit columns pre-fit; clip scaled values to `±10σ` (persisted to `scaler_stats.json` so `main.py` applies identical bound at runtime). Plus automated regression-quality gate catching future blowups without manual investigation.

**Verification:** Post-fix max absolute scaled value exactly 10.0 (clip firing); retrained RMSE/MAE ratio 31x → 1.59x.

---

### 24. `train.py` never applied Lean's own split/dividend factor files — offline dataset had fake ±74%/+745% "returns"

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `train.py`'s independent raw-zip reader bypassed Lean split/dividend adjustment — real corporate actions (AAPL 2020 4-for-1, USO reverse split) produced fake ±74%/+745% "returns" in every label/feature spanning boundary, for every equity with split/dividend history. Lean's live/backtest engine unaffected; purely offline train/runtime parity gap.

**Fix:** New `train.py::apply_split_adjustments()` reads each equity's real Lean factor file, rescales OHLCV exactly as Lean does; `yfinance_backfill.py` → `auto_adjust=True`; per-security-type label-outlier guard defense-in-depth.

**Verification:** Real data: AAPL split-boundary "return" -74% → ~3.4%; USO +745% → ~5.6%.

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

**Problem:** `split_into_non_overlapping_eras()`/`purged_embargoed_folds()` did Timestamp arithmetic on `np.asarray(dates)` — correct only for datetime input; real callers pass stringified date columns, crashing first real run despite passing all unit tests (synthetic datetime fixtures).

**Fix:** Both functions plus identically-bugged caller coerce via `pd.to_datetime(np.asarray(dates))` — robust to string/Timestamp/datetime64.

**Verification:** New regression tests use plain string dates, real object-array shapes — specifically preventing "passes unit tests, fails first real run" gap recurring.

---

### 28. Portfolio book's `"short"` signal silently zeroed to no position

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `_build_dynamic_sizing_payload()` guard recognized only `{"buy", "sell"}` — never updated when `"short"` became valid, so book-selected shorts sized to exactly zero. Never observed in practice (book feature defaults off).

**Fix:** Guard recognizes `{"buy", "sell", "short"}`.

**Verification:** Covered implicitly by portfolio-book suite plus future end-to-end backtests with book enabled.

---

### 29. Multi-asset-class support (bonds/futures/options + IB) — explicit non-goals

**Severity:** n/a (scope note) · **Status:** 🟢 `fixed` (core multi-asset-class trading is fully implemented; remaining items are permanent non-goals)

**Problem:** Tracked multi-asset-class gaps after initial architecture pass — options order placement against resolved contract, real derivatives-macro data, per-asset-class book slot caps — originally deferred.

**Fix:** All three resolved later: real option contract order placement; real futures/options derivatives-macro features (offline and live); optional `per_asset_class_slots` book parameter (default `None`, byte-identical to prior pooled ranking).

**Verification:** 7 new tests for per-class slotting (ranking, exclusion, thin-class isolation, confidence-spread gating, backward compat). Remaining items (ML-driven multi-leg spread selection, IBC headless TWS login, live IB margin, bulk historical derivatives fetch) permanent non-goals blocked on external dependencies — tracked in README Known Limitations.

---

### 30. `Dockerfile.retraining_worker` missing `data_pipeline/` (and pre-existing: `liquidity/`) copy

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** Top-level `data_pipeline.fred_backfill` import never copied into `Dockerfile.retraining_worker`; pre-existing gap: `liquidity/` also missing. Either crashes first retrain.

**Fix:** Both COPYs added. Superseded July 17 consolidation: Dockerfile gone; compose's `retraining-worker` builds consolidated `aether-quant-engine:latest` (`COPY . .`), whose comment names this entry as structurally eliminated.

**Verification:** Import-graph tracing (#2/#20 method); confirmed directly — bug class now impossible.

---

### 31. Infrastructure/latency pass — `aq test` silently ran a real Lean backtest, per-bar inference hot path never profiled, CI Docker builds never cached

**Severity:** 8/10 (aq test) / 6/10 (inference latency) / 4/10 (CI cache) · **Status:** 🟢 `fixed`

**Problem:** `aq test`'s Lean-backtest file checked binary presence only — routine runs paid real (over-an-hour) backtest cost; inference hot path unprofiled; CI Docker release builds uncached.

**Fix:** Opt-in `lean_backtest` pytest marker (excluded by default; `--lean`/`--full` opt-in) + per-subsystem `aq test` flags; new `scripts/profile_inference.py` harness; hot-path fixes: causal-conv Python loop → batched `einsum`; 4 per-expert dispatch calls → one batched; `cache-from`/`cache-to: type=gha` on release Docker step.

**Verification:** Collect-only 1132/1143 (11 deselected); non-Lean run >1h → ~73s-4min; measured 448.4s→290.6s (-35.2%, 10k-iteration real-weight workload); 200-trial fuzz parity old loop vs batched conv1d.

---

### 32. Latency deep-dive follow-up — weight-array/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension attempt

**Severity:** n/a (optimization pass) · **Status:** 🟢 `fixed`

**Problem:** Re-profiling after #31: repeated `numpy.asarray()` conversions of same static JSON-loaded weights every bar — largest remaining cost.

**Fix:** `convert_state_dict_arrays()` converts once at load (zero downstream API change); batched-stack caching precomputes expert weights in `_ensure_ready()`; added `aq profile` CLI, opt-in per-symbol multiprocessing (default off, sequential fallback), C++/pybind11 extension (`cpp_inference_ext`) accelerating batched linear layer.

**Verification:** Measured 448.4s→48.4s (-89.2%); mean latency/symbol/bar 44.8ms→4.83ms; 14 parity tests prove cached path bit-identical; extension gave further modest consistent speedup (two paired comparisons); naming-collision bug (source dir shadowing built module) + wrong-Python-env install caught/fixed during verification; multiprocessing win/loss left to a real backtest — not attempted enabled this pass.

---

### 33. Execution/risk realism pass — real `SlippageModel` wired to fills

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** `build_liquidity_decision()` computed a real spread+impact estimate every bar, nothing consumed it — no security had a `SlippageModel`; simulated fills hardcoded zero slippage; historical backtests had systematically too-good fills.

**Fix:** Pure `slippage_amount()`/`resolve_slippage_bps()`/`resolve_fill_slippage()` in `execution/order_gate.py`, threaded into Lean fill path (new `_LiquidityAwareSlippageModel` adapter) + simulated-fill path; cost source and safety clamp later made config-configurable.

**Verification:** 12+13 new tests (`test_order_gate.py`/`test_simulated_portfolio.py`) incl. default-vs-explicit-zero parity; adapter not unit-testable in isolation (same `main.py`-outside-Lean constraint); logic lives in tested pure functions.

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

### 37. Inference tail latency (p99 3-5x p50) — investigated and fixed

**Severity:** 4/10 · **Status:** 🟢 `fixed and verified`

**Problem:** No prior investigation into why p99 ran 3-5x p50 (fact known from #32); separate stale on-disk profiling output showed misleadingly bad numbers, regression status unclear.

**Fix:** Harness reran multiple times — discrepancy was a stale/unrelated local run, not regression; iteration bucketing ruled out warmup; `--no-gc` isolated reproduced GC-pause contribution to max tail specifically; follow-up shipped `gc.freeze()` after model load, config-gated off pending backtest validation vs Lean's .NET/Python interop GC boundary.

**Verification:** Paired GC-on/off runs: max latency -66-95% with GC disabled, p50 unaffected (tail-only effect); `gc.freeze()` clean across full real backtest (2026-07-20, #54).

---

### 38. 2-leg vertical spread selection for options — explicit scope-in of a previously-non-goal feature

**Severity:** n/a (feature scope-in) · **Status:** 🟡 `partial`

**Problem:** Multi-leg spread selection was explicit non-goal (#29); this pass closes minimal 2-leg vertical-spread slice.

**Fix:** New `select_vertical_spread_legs()`/`build_vertical_spread_position_sizing()` (net-vega sized), wired through `risk/asset_class_router.py` + new `_apply_option_spread_order()` using Lean's own `OptionStrategies` atomic combo-order primitive (previously completely unused here); two real bugs (field-existence check ordering; early draft breaking option orders entirely for spread case) caught/fixed during implementation.

**Verification:** 20 new tests (leg selection/sizing/degrade paths) + critical zero-behavior-change parity for single-leg path. **Real-backtest verification still genuinely open** — no option/future asset configured in universe yet, so never exercised against real Lean order placement, margin, or partial-fill behavior.

---

### 39. Final pre-backtest bug sweep — 4 fixes found and fixed before this project's first real `lean backtest .` run

**Severity:** 6/10 (test-harness bug) / 5/10 (liquidity threshold collision) / 3/10 (limit-order timeout) / 2/10 (book-slot crash risk) · **Status:** 🟢 `fixed`

**Problem:** Sweep found: (1) wrong dict-key path in Lean coverage test silently failing 3 real assertions regardless of backtest correctness; (2) two liquidity thresholds drifted to same value, collapsing two-tier gate to one; (3) limit-order timeout handler contradicting dependency's documented "unknown status = still pending" contract; (4) no shape validation on optional per-asset-class book-slot config (unpack-crash risk).

**Fix:** Key path fixed; `thin < high_impact` ordering restored; handler pops-without-cancel only on genuinely terminal statuses; new `normalize_per_asset_class_slots()` pure validator degrading gracefully on malformed entries.

**Verification:** 6 new validator tests; other three fixes verified via direct inspection/config check (pre-real-backtest by design — the point of entry); suite green after all four.

---

### 40. `aq backtest` silently re-pulled the ~42.5GB Lean engine image on every run

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** `lean backtest .` resolved mutable `quantconnect/lean:latest` unpinned — whenever QC moved the tag, even machines with the full 42.5GB image cached re-pulled, indefinitely, every clone and run.

**Fix:** Pinned immutable `quantconnect/lean:17900` by default, always passed explicitly; `aq backtest --image <other>` for deliberate newer-build opt-in.

**Verification:** Tests confirm pin-by-default + working override flag; documented in README Getting Started.

---

### 41. First real backtest: only 14 trades, none ever closed

**Severity:** 6/10 (blocks a statistically meaningful backtest) · **Status:** 🟢 `fixed` (superseded by #43)

**Problem:** First real backtest produced 14 orders, all openings, zero closes — model's `probability_up` clustered 0.46-0.49 vs buy/sell thresholds 0.50/0.42, almost nothing crossing either line. Secondary finding: soft `max_active_positions` cap (same-bar overshoot counting only already-filled positions).

**Fix:** None here — proposed threshold-tightening lever diagnosed but never shipped. #43 found real causes structural (position-cap overshoot, risk vetoes blocking exits, neutered circuit breaker, no exit mechanism) plus a training-pipeline defect, pivoting trading entirely to `rank_20d`/`portfolio_book`.

**Verification:** Diagnosis only, confirmed against real output files (`state.json`, order-events, logs).

---

### 42. Pre-live security review — broker/API credentials could be published; DB exposed to the LAN behind a repo-published password

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** Pre-live pass found: runbook instructed hand-editing real IB credentials into git-tracked `lean.json`; `.dockerignore` didn't exclude secret files from published images; Postgres/Redis published to `0.0.0.0` behind a password published in this public repo; nothing structurally prevented future secret commits.

**Fix:** Credential render step (`aq render-lean-config`) overlays secrets from gitignored `.env.live` onto gitignored `lean.live.json` (tracked `lean.json` stays empty); secret list mirrored into `.dockerignore` (caught second instance of the bug in fix's own new file); DB/Redis bound to `127.0.0.1` + fail-closed live-mode guard vs default password; added `aq secrets-check` and opt-in pre-commit hook.

**Verification:** New `tests/test_dockerignore_secrets.py` evaluates real Docker pattern semantics, not literal line-grep; no secret anywhere in git history; no deserialization-RCE surface; deferred audit-logging item closed later — see #44's audit-log update.

---

### 43. Full pre-live model overhaul: trading-logic bugs + training-pipeline bugs, pivot to the one significant signal

**Severity:** 9/10 · **Status:** 🟢 `fixed` (see #52/#54)

**Problem:** Second backtest after #41's recalibration produced bit-identical results to pre-fix (same 14 trades/profit) — calibration had zero effect on actual trades. Causes spanned trading logic (soft position-cap overshoot; sell-vetoing risk logic; sell threshold ~10σ from live output; neutered drawdown breaker; no stop-loss/trailing/max-holding-age exits) and training (untrained epoch-1 checkpoints from broken early stopping; degenerate threshold search; MoE blend diluting skill to 0.5; no skill-floor gates; 35/85 static one-hot inputs; ~52-row crypto training; trading ignoring `rank_20d`/`rank_5d` — the only statistically significant signal in the codebase).

**Fix:** Early stopping rewritten (`min_best_epoch` floor); non-degenerate threshold-search bounds; unified asset-context columns; dead features removed; `min_training_rows`/skill-floor gates raised; no-skill experts zeroed; `portfolio_book` wired to trade `rank_20d` directly; exit-veto bypass; safety exits (max holding age + trailing stop); adaptive sell band; same-bar position-cap fix; drawdown breaker re-armed; crypto/`InteractiveBrokersFeeModel` crash fixed.

**Verification:** Real backtest (2026-07-17): 653 orders (vs stuck-at-14), 11.1% drawdown — mechanical fixes confirmed, still -4.6%/Sharpe -0.59 (edge not yet profitable); tests extended across `train.py`, gating, `market_analyzer`, `validation_gate`, experts, `portfolio_book_construction`; superseded by #52/#54: rank-pivot roadmap's 2026-07-20 backtest profitable (Sharpe 0.403, Net +10.4%).

---

### 44. Lean CLI couldn't feed the retraining loop — undocumented second `requirements.txt` convention

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `main.py`'s `ExperienceQueue` silently no-oped during every real `lean backtest .` run (missing `redis`). Lean CLI auto-installs deps from project-root `requirements.txt`, separate from the repo's own `requirements/requirements.txt` convention which Lean never reads; everything else happened to exist in the image, so invisible until `redis`.

**Fix:** Repo-root `requirements.txt` containing `redis>=5.0.0`, cross-referenced from `requirements/README.md`.

**Verification:** Not re-verified against a real run this session (left for user); confirmed correct reading Lean CLI's source (`lean_runner.py`).

---

### 45. `av` (Aether-Vault CLI) was broken on this machine — never actually run once in this repo

**Severity:** 4/10 · **Status:** 🟢 `fixed`

**Problem:** `retraining/vault_client.py` commit stage shells out to `av`, failing every call (`ModuleNotFoundError: questionary`); never initialized (`.av/` absent) — invisible because `commit_candidate_to_vault()` degrades gracefully by design.

**Fix:** Installed `questionary` into correct environment (`av.exe` resolves via separate user-scoped Python 3.14 install, not repo `.venv`); ran `av init --mode local -y --no-repl` in repo root.

**Verification:** Confirmed via `av status`; local-only accepted (no remote registry; degrades to local pending-push queue).

---

### 46. `xreadgroup(block=0)` meant "block forever," not "don't block" — idle Redis-stream workers timed out every cycle

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** `experience/postgres_worker.py`/`audit/postgres_worker.py` called `xreadgroup(..., block=0)` believing it non-blocking; Redis `BLOCK 0` blocks forever — with client `socket_timeout=5`, every idle poll raised a timeout exception. Invisible because `fakeredis` doesn't reproduce blocking-socket-timeout behavior.

**Fix:** Removed `block=0` from both call sites — default `None` omits `BLOCK`, letting existing correct `sleep(1)` idle loops work.

**Verification:** Real Compose Redis: both workers 0% CPU, zero errors post-fix; `tests/test_postgres_worker.py`/`tests/test_audit_postgres_worker.py` (18 tests) pass unchanged — they never asserted on `block`.

---

### 47. `retraining-worker`'s `./data` volume mount was read-only — `train.py` could never complete inside the real container

**Severity:** 7/10 · **Status:** 🟢 `fixed`

**Problem:** Compose mounted `./data:/app/data:ro`, but crypto daily-series derivation (#15) must read-then-write `data/crypto/coinbase/daily/*.zip` every invocation — container crashed `OSError: Read-only file system`. Never caught before because rehearsals ran `train.py` on the host, where writable.

**Fix:** Mount changed to writable (`./data:/app/data`).

**Verification:** Rehearsal re-run after `docker compose up -d --force-recreate` confirms completion past this point.

---

### 48. Force-recreating `retraining-worker` mid-cycle orphaned a stuck `retraining_events`/`model_versions` row — no startup reconciliation existed

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Mid-cycle recreation killed an in-flight `train.py` subprocess before Postgres report-back, leaving `retraining_events`/`model_versions` rows permanently stuck `"running"`/`"candidate"` — cooldown check then blocked all future retraining (nothing detected orphaned rows). Related: container ran `python -m retraining.worker` as PID 1 without init process, so a subprocess killed on orchestrator timeout could become an unreapable zombie, blocking even `docker compose stop`.

**Fix:** Startup reconciliation `fetch_stale_active_events()`/`reconcile_stale_running_events()` marks stale `running`/`planned` rows `failed` (rejecting still-`candidate` `model_versions` rows) after configurable `stale_running_timeout_seconds` (default 10800s = sum of stage timeouts); `init: true` on Compose service (Docker's tini) so killed subprocesses are reaped.

**Verification:** 8 new tests across `postgres_registry`, `orchestrator`, `retraining_worker`; suite green (1465 passed) before/after; zombie scenario hit live and manually recovered (`docker rm -f`) before `init: true`; `docker compose config --quiet` clean.

---

### 49. Full end-to-end retraining-loop rehearsal against the real Compose stack — three real cycles ran, all correctly rejected; rollback rehearsed both ways

**Severity:** n/a (operational-maturity verification, not a bug) · **Status:** 🟢 `verified`

**Problem:** N/A — rehearsal proving a genuine closed loop vs mocked-unit-test logic. One follow-up deliberately unfixed: `lean` CLI absent from worker image, so `backtest_gate` silently no-ops rather than crashing — flagged known deliberate infrastructure gap.

**Fix:** None (verification exercise).

**Verification:** Three real cycles via worker poll loop (`plan→train→train_topology→train_gating→train_multitask→train_sequence→validate`); `train_sequence` timed out once at its 1800s cap (real resource-constrained-host finding, not crash), pipeline continued to `validate`; all three candidates rejected on legitimate quality grounds (consistent with #43 weak-edge finding); rollback tested vs real Postgres/files — happy path flips status `active`, tamper path (corrupted hash) refused with no files copied/no row touched; `backtest_gate` never organically exercised (nothing cleared `validate`), confirmed structurally unable to run as configured.

---

### 50. This dev machine's 4GB RAM couldn't reliably run a real `lean backtest .` — blocked verifying #34/#36/#37/#38

**Severity:** n/a (hardware constraint) · **Status:** 🟢 `fixed` (superseded — see #54)

**Problem:** Four consecutive real `aq backtest` attempts failed at Lean's hardcoded 90-second `initialize()` isolator cap. Precise root cause: plain top-level imports (torch/pandas/sklearn) alone took ~82 seconds under memory pressure (~300MB free on this 4GB host) — not a code regression. Blocked verification of #34/#36/#37/#38.

**Fix:** Narrowed `main.py`'s `from audit import ...` (transitively pulling unused Postgres/status-export code) to `from audit.redis_queue import ...`, trimming import cost inside timed window. Documented (not a code fix): failed `lean backtest` containers aren't reliably cleaned up on failure, leaving orphaned `lean_cli_*` containers holding memory.

**Verification:** `python -m py_compile main.py` + suite green. Superseded 2026-07-20 (#54): real backtest completed successfully on same machine, verifying #34/#36/#37 (~40 min run, manual zombie cleanup needed). #38 remains open for unrelated reason (no option asset registered).

---

### 51. `GET /api/assets-status` 500'd in Docker — `lean.json` (entry #42's exclusion) was never mounted back in, and the reader didn't degrade gracefully

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Endpoint 500'd in real deployment. #42 excludes `lean.json` from the published image but nothing volume-mounted it back at deploy time, so `build_assets_status_from_disk()` hit an uncaught `FileNotFoundError`.

**Fix:** Read-only runtime mount (`./lean.json:/app/lean.json:ro`) on `engine` service (never baked into image, preserving #42); reader catches `FileNotFoundError`, degrades to empty `lean_config` so `ib_readiness_status()` reports graceful degraded status instead of 500ing.

**Verification:** New `test_build_assets_status_from_disk_degrades_gracefully_when_lean_json_missing`; all 8 tests in file pass; real rebuilt container returns 200 with correct content where it previously 500'd.

---

### 52. The rank-pivot roadmap: trading path switched to `rank_20d`, universe expanded 30→74 assets, four Stage-4 regularization gaps closed

**Severity:** 9/10 · **Status:** 🟢 `fixed` (retrained and backtest-verified — see #54; one caveat still open, below)

**Problem:** Trading path traded the noise-objective direction head (backtest MCC ~0.02-0.04) instead of `rank_20d` — the one genuinely skillful signal — and even that far faster than its ~20-day horizon supports. Gaps: purged-CV configured but never called; no rank-IC early stopping; dead 1-day direction head fully weighted in loss; no seed-ensembling or cross-head consistency regularization.

**Fix:** Five config-gated changes: (1) `strategy_mode`→`long_short`, rank-based sizing enabled, sequence `rank_20d` blended into traded probability, book widened top/bottom 8; (2) 5-bar rebalance scheduler `should_rebalance_this_bar()` matching horizon; (3) universe 30→74 (54% equity/30% bond/16% crypto), dataset rebuilt to 113,804 rows; (4) rank-IC early stopping, dead direction-head loss down-weighted (not removed), seed-ensembling + horizon-consistency regularization in `train_multitask.py`/`train_sequence.py`; (5) previously dead `purged_embargoed_folds()` wired into real diagnostic (`purged_cv_rank_20d`). Also fixed `yfinance_backfill.py` `float()`-on-MultiIndex deprecated pandas fallback.

**Verification:** New functions unit-tested; suite green 1465→1497. Update 2026-07-20 (Codespaces retrain, #53): early stopping fired (best_epoch far off old floor); full-series IC improved — multitask 0.172/t=7.55 (vs 0.073/t=4.40), sequence 0.127/t=5.70. Open caveat: promotion bar (non-overlapping t-stat ≥ 2.0) unmet (multitask 1.40, sequence 0.43). Real backtest (2026-07-20, #54) profitable (Sharpe 0.403, Net +10.4%), confounded by concurrent `bypass_safety_gates` change.

---

### 53. GitHub Codespaces set up as cloud training offload; a real Alpine-base devcontainer bug found and fixed

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** 4GB machine spent hours wall-clock on ~800 CPU-seconds of training (#50/#52). Codespaces setup hit a real bug: `docker-in-docker` feature silently swapped the pinned Debian image to Alpine, breaking `pip install` against musl libc (matches upstream `devcontainers/images#1114`). Deeper blocker: Codespaces containers run unprivileged — Lean/Docker backtests can't run inside a Codespace at all; platform limitation, unfixable from this repo.

**Fix:** Dropped `docker-in-docker` (training needs none), kept `sshd` only; prepended CPU-only `pip install torch --index-url .../cpu` to `postCreateCommand` (bare install resolved a CUDA build failing to import GPU-less). Git hygiene: 9 generated `ml/` artifact files tracked inconsistently — `.gitignore`d and untracked.

**Verification:** Verified via 5 systematic A/B Codespace rebuilds (with/without docker-in-docker, sshd); full 8-artifact retrain <15 min on fixed Codespace vs 4+ hours unfinished locally; `git check-ignore -v`/`git status` confirm clean/untracked.

---

### 54. First real `aq backtest` against rank-pivot models: Sharpe -0.59 → +0.40, plus a universe-selection bug (BNBUSD/TRXUSD never listed on Coinbase)

**Severity:** n/a (verification milestone) / 3/10 (ticker bug) · **Status:** 🟢 `verified` / `fixed`

**Problem:** Rank-pivot roadmap (#52/#53) needed real `lean backtest .` confirmation. Separately, two Stage-3 crypto tickers from #52's expansion (BNBUSD, TRXUSD) could never subscribe — Coinbase never listed Binance Coin or TRON pairs, though Yahoo Finance returned price history masking the mis-selection.

**Fix:** Swapped for ETCUSD (Ethereum Classic) and ZECUSD (Zcash), both confirmed present in Lean's local Coinbase symbol-properties database, backfilled via `aq fetch crypto --apply`.

**Verification:** Sharpe -0.59→0.403; Net Profit -4.604%→+10.438%; Drawdown 11.1%→4.0%; Win Rate 47%→58%; rebalance scheduler confirmed working (turnover barely moved despite order count rising — bigger book, long_short trading both sides). Disclosed confound: `bypass_safety_gates` flipped `true` same run, improvement not cleanly attributable to rank-pivot alone — clean-comparison backtest reverted left as manual follow-up. Swap dry-run row-count/date-range checked pre-`--apply`; `config.json` JSON-validated; rebuild confirmed registration with same observation-only classification as other Stage-3 crypto; log confirmed #34's limit orders fire (rounded limit-price log line).

---

### 55. Every webui tab except `/` 404'd on a direct load when served by FastAPI

**Severity:** 6/10 · **Status:** 🟢 `fixed`

**Problem:** Bundle mounted as `StaticFiles(directory=WEBUI_DIST, html=True)` — `html=True` maps directory paths only, not unknown paths, so direct load/hard refresh of `/risk`, `/topology`, `/neural-network`, `/tracing`, `/operations` returned raw 404 (client-side nav worked; vite SPA fallback masked it in dev).

**Fix:** `SpaStaticFiles(StaticFiles)` subclass overriding `get_response()` falls back to `index.html` on 404, limited to extensionless paths so genuinely missing assets (`/assets/*.js`) still 404. Subtleties: Starlette raises `HTTPException(404)` rather than returning one, and raises Starlette's specifically (FastAPI's is a subclass — catching that misses it).

**Verification:** Parametrized tests for all six client routes, missing-asset-still-404 case, `/api/*` not shadowed.

---

### 56. `train_topology.py` learned prototype z offsets on the pre-V4 `0..1` scale

**Severity:** 1/10 (latent; unreachable until a model exists) · **Status:** 🟢 `fixed`

**Problem:** V4-W3 made z a real `0..100` correlation-distance axis in 3D embedding mode, but prototype z offsets were still emitted on old `0..1` formula — overlay moved nodes x/y, effectively not z.

**Fix:** Z normalized `[-1, 1]`; `topology/learned_topology.py::_score_node()` scales by active `max_offset_z` before same clamp as x/y — provably identity-preserving 2D, proportionally larger 3D; `offset_schema` detection field (no migration branch — no old-format model ever existed). Training the first real topology model remains a separate user milestone (`aq train --topology-only` added) — none ever trained, overlay dormant.

**Verification:** Byte-identical output vs old raw formula in 2D; 60x more z travel under raised 3D cap.

---

### 57. Futures/options had a live incremental-vs-absolute order-sizing bug — fixed, plus position scale-up for all 5 asset classes

**Severity:** 5/10 (dormant, reachable only via `futures_risk.enabled`/`options_risk.enabled`, both default off) · **Status:** 🟢 `fixed`

**Problem:** Equity/crypto/bond add-to-position blocked by simple `main.py::_apply_signal()` gate; futures/options had none — worse, correctly-recomputed **absolute** per-bar targets fired through **incremental** primitives (`MarketOrder`/`Buy`) every bar the signal held, stacking contracts unbounded; options could additionally orphan a position by re-selecting strike/expiry each bar without closing the old one.

**Fix:** New `risk_controls.py::compute_incremental_order_quantity()` — futures/options submit only signed delta toward absolute target, unconditionally (genuine bug fix, no flag). Two opt-in tiers: `position_scaling.enabled` (default false) scale-up/down with churn guard; `rotate_on_drift` (default false) liquidate-then-reenter drifted contracts.

**Verification:** Default path unreachable via grep/call-graph trace (sizing returns 0/None first); tests 1521→1558 passing (`tests/test_risk_controls.py`, `tests/test_order_gate.py`); `main.py` has no direct unit tests (subclasses `QCAlgorithm`) — trace-only.

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

**Problem:** 3-agent audit: `lean` CLI missing from production image used by `retraining-worker`; compose missing `data/reference` mount (silently zeroing Forex/futures/FRED specs) + stale comment; `aq` lacking bulk-backfill dispatcher; `aq test` subsystem file lists stale; real bug — `corporate_action_payload` computed in Pass 1's per-symbol loop but read in Pass 2's separate loop, so (no block scoping in Python) every symbol reused whatever Pass 1 left from the last symbol processed. Several V4.7 fields (bond analytics, assignment risk, dividend schedule, strategy-selector scores) computed but never reached `state.json` despite a comment claiming otherwise.

**Fix:** `lean` added to production requirements + Docker socket mount; compose mount/comment fixed; added `aq backfill <target>`; stale dict fixed; payload threaded through `pass1_state` per-symbol; all 5 fields wired into `signals[symbol_key]` in `_write_state()`; new `/options-strategy` page.

**Verification:** Bug fix via call-graph trace plus full suite green; 1813→1818 python tests; webui 13 tests across 2 files; npm build/lint/test clean.

---

### 63. V4.9 Priority 0 — the #36/#50 profiling wrapper was never reverted: a live per-bar disk write on the hottest path

**Severity:** 6/10 (real continuous synchronous disk I/O on every symbol-bar call in any live/paper/backtest run) · **Status:** 🟢 `fixed`

**Problem:** #36's claim that the `_build_model_input()` wrapper "was fully reverted" (per #50) was false — `main.py` unconditionally opened `model_input_timing.log` and wrote a line every symbol-bar call, ungated, with 45,187 accumulated lines (~983KB) untracked in repo root.

**Fix:** Impl renamed back to `_build_model_input`, wrapper deleted; dead `perf_counter` import removed; log file deleted. Real per-call timing collection remains an open task — `scripts/profile_inference.py`'s in-process harness (no disk I/O) intended path forward.

**Verification:** `py_compile main.py` clean; grep confirms zero references to removed names/file; `main.py` via trace only (unit-untestable by convention).

---

### 64. V4.9 Priority 4 — `_build_options_chains_payload()`'s gating, considered and declined

**Severity:** n/a (no code change — a documented decision) · **Status:** 🟢 `fixed` (declined by design, no code change)

**Problem:** Candidate optimization: gate `_build_options_chains_payload()` (runs once per bar per configured option asset) behind `self.options_risk_enabled`.

**Fix:** Declined. Configuring an option asset is already the deliberate visibility trigger (feeds `state.json`/webui regardless of multi-leg trading enabled), matching the "compute for visibility even when trading is off" pattern bond analytics/assignment risk follow; never appeared as meaningful profiling cost.

**Verification:** Decision recorded so future passes don't re-investigate from scratch.

---

### 65. V4.9 Priorities 1-3, 5-8 — sequence batching, topology percentile-tolerance caching, options chain-grouping hoist, non-blocking experience delivery, IPC benchmark, HFT documentation

**Severity:** n/a (feature/optimization pass, all off by default) · **Status:** 🟢 `fixed`

**Problem:** Profiling-roadmap continuation: sequence encoder cost paid once per symbol; fixed topology cache tolerance poorly calibrated; hoistable per-bar options cost; blocking experience-event delivery in live/paper; unmeasured `ProcessPoolExecutor` IPC assumption; missing options profiling coverage; unclear framing of which latency work is genuine HFT-fork prep.

**Fix:** P1 — `run_exported_sequence_multitask_model_batched()` stacks all symbols into one batched pass (default off; falls back on <2 sequences or any failure). P2 — percentile-based rolling-window tolerance (`correlation_stability_tolerance_percentile`, default `null` = old behavior). P3 — `group_chain_by_expiry()` hoisted to once per routing call. P5 — `ExperienceQueue.push()` non-blocking `async_enabled` mode (default off). P6 — IPC benchmark confirming `ProcessPoolExecutor` dramatically slower than sequential on this Windows/spawn machine (measured). P7 — `"options"` workload in `profile_subsystems.py`. P8 — `development/architecture.md` section separating genuine HFT-transfer work from daily-bar-loop speedups.

**Verification:** Tests 1818→1857 (39 new: batching parity, percentile math, chain-grouping parity, async semantics, pool-failure degradation, options workload shape); all new keys grep-verified defaulting `false`/`null` (byte-identical off); `main.py` via trace only.

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

**Problem:** Only compiled extension was hand-built for dev-machine Python 3.14, ABI-incompatible with deployed `python:3.11-slim`; Dockerfile lacked compiler/pybind11/extension entirely — C++ acceleration never ran deployed, a 100% silent gap (fallback silent by design).

**Fix:** Soft-fail `RUN` step installing `build-essential`+`pybind11`, pip-installing `cpp_inference_ext`, purging `build-essential` same layer, wrapped `(...) || echo ...` so toolchain/ABI failure degrades to NumPy fallback rather than breaking build; `.dockerignore` excludes block locally-built incompatible binaries leaking into published image.

**Verification:** Unconfirmed two phases (Docker/WSL2 outage); Phase 4.12.3 confirmed: `docker compose build engine` succeeds and in-image `import cpp_inference` loads real compiled linkage (`cpp_inference.cpython-311-x86_64-linux-gnu.so`), not fallback.

---

### 69. Audit follow-up — `main.py` CI syntax-check gate, and a Windows-specific inference-parallelism slowdown guard

**Severity:** low · **Status:** 🟢 `fixed`

**Problem:** `main.py` had zero CI coverage — not even syntax check (`AlgorithmImports` undefined outside real Lean process). Separately, `phase_v2.inference_parallelism.enabled` unguarded despite #65 Priority 6 measuring it dramatically slower than sequential on Windows/spawn; key also absent from `config.json`, so `aq config set` on it failed outright rather than silently succeeding.

**Fix:** `python -m py_compile main.py` CI step (parse only; mypy/pyright via `quantconnect-stubs` considered, declined as too noisy); `windows_parallelism_slowdown_warning()` fires `Debug()` only on win32 after real pool construction; key-specific stderr warning citing #65 measurement; explicit `phase_v2.inference_parallelism: {"enabled": false}` block added to `config.json` (previously code-side-only, key unsettable).

**Verification:** New `tests/test_parallel_inference.py` cases (win32 vs linux/darwin) + 4 in `tests/test_aq_cli.py` (fires only this path, only truthy, only vs `config.json` not `lean.json`).

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

**Problem:** Priority 6.5 net-edge gate re-derived its own pass/fail from raw `net_edge_bps` instead of trusting `build_net_edge_decision()`'s `passes` field; "disabled" state still carried real `net_edge_bps=0.0`, so with the `aggressive` preset's `min_net_edge_bps: 2.0`, `0.0 < 2.0` evaluated True every symbol/bar, routing every directional signal away from trading — 100% blocked, 0 orders entire backtest.

**Fix:** Removed re-derived comparison + `min_net_edge_bps` parameter from `build_market_analysis_decision()`; trusts `net_edge.get("passes", True)`, the single verdict already computed by `build_net_edge_decision()`; call site updated.

**Verification:** 5 regression tests in `tests/test_market_analyzer.py` incl. exact "disabled" dict shape asserted reaching `"trade"`; root cause surfaced by real backtest (0 orders); no prior unit test exercised realistic non-`None` disabled dict.

---

### 77. V5.1 Phase 1's `min_rank_confidence_spread` gate defeated by its own cross-sectional normalization fix — real Lean Backtest 1 traded but lost money

**Severity:** 8/10 · **Status:** 🟢 `fixed`

**Problem:** `_select_book_group()` conviction gate read the cross-sectionally-normalized `predicted_rank_20d` (introduced by F1 fix, #73) instead of raw score; fixed top-6/bottom-6 selection percentile-ranked always shows ~0.90+ spread regardless of dispersion, so the `aggressive` preset's `min_rank_confidence_spread: 0.20` never disengaged book across the whole 2019-2021 run. Sharpe −0.145→−2.526; net profit flipped +3.41%→−3.11%.

**Fix:** Optional `spread_check_ranks` parameter on `_select_book_group()`/`build_rank_based_book()`; `main.py` builds it from each symbol's pre-normalization `raw_rank_score` alongside normalized `book_candidates`; sizing/confidence still reads normalized value — only engagement gate's input changed.

**Verification:** 6 new tests in `tests/test_portfolio_book_construction.py` incl. one reproducing bug directly, one proving selection unaffected; not yet re-verified with a Lean backtest — deliberately held in reserve, bundled with Phase 2's retrained-model backtest.

---

### 78. `tests/test_retraining_worker.py` — 7 of 11 tests spawned a real, unmocked subprocess, adding ~17 minutes to every full suite run

**Severity:** 3/10 (dev-velocity/CI-cost only, no correctness impact) · **Status:** 🟢 `fixed`

**Problem:** 7 tests patched the first four of `run_once()`'s five best-effort trainer stages but never `train_strategy_selector` — each spawned a real `subprocess.run()` shelling `train_strategy_selector.py` (~140-168s apiece), collectively ~1,050-1,200s of a ~28-minute suite.

**Fix:** Added `patch("retraining.worker.train_strategy_selector")` alongside other stage patches in all 7, matching the file's per-stage mocking convention.

**Verification:** File re-run 11/11 passed, 86.8s total (down from >1,050s for the same 7 tests) — roughly 15-16 minutes off every future full-suite run.

---

### 79. `data_pipeline/fred_backfill.py::fetch_fred_series()` hung/reset on every request — FRED's graph-export endpoint requires HTTP/2, which stdlib `urllib` cannot speak

**Severity:** 7/10 (blocked V5.1 Phase 2's CODESPACE RUN 1 entirely — 0 of 12 FRED series fetchable) · **Status:** 🟢 `fixed`

**Problem:** stdlib `urllib.request` (HTTP/1.1-only) could no longer reliably reach FRED's `fredgraph.csv` endpoint — external FRED-side change, not regression; all 12 series failed with read timeouts. Secondary finding: browser-spoofing `User-Agent` header (prior code's own) caused immediate `RST_STREAM` even over HTTP/2, plausibly FRED's WAF cross-checking UA vs TLS fingerprint.

**Fix:** Swapped to `httpx.Client(http2=True)`; added `httpx[http2]>=0.27.0`; removed browser-spoofing `User-Agent` entirely (left unset).

**Verification:** Network-mocking tests rewritten against `httpx.Client` in `tests/test_fred_backfill.py`; 31/31 pass; verified live locally and on Codespace: all 12 series incl. 3 new ones fetch successfully with full historical coverage.

---

### 80. `train.py::build_dataset_manifest()`'s new `computed_but_unused_features` (V5.1 Phase 2) flagged ~70 legitimate columns as orphaned on the first real dataset build

**Severity:** 6/10 (would have buried the 3 genuine orphans under ~70 false positives) · **Status:** 🟢 `fixed`

**Problem:** Manifest builds on the post-scaling dataset, but `_computed_but_unused_feature_columns()` excluded only `base_feature_names`/`context_feature_names` — never `scaled_feature_names`, `categorical_feature_names`, or raw OHLCV/bookkeeping columns — so every `_scaled` sibling, categorical one-hot, and bookkeeping column (timestamp/open/high/low/close/volume, security_type, etc.) was flagged orphan; tiny synthetic fixtures never included these column classes.

**Fix:** Threaded `scaled_feature_names`/`categorical_feature_names` into exclusion set; expanded `_NON_FEATURE_DATASET_COLUMNS` with `RAW_COLUMNS` plus `security_type`/`market`/`quality_tier`/`trading_eligible`/`training_eligible`.

**Verification:** Regression test covering all three previously-missed classes; Codespace real-dataset build returns exactly the 3 genuine orphans (`futures_term_structure_slope`, `options_implied_vol_skew`, `options_put_call_ratio`).

---

### 81. `portfolio/book_neutrality.py::apply_book_neutrality()`'s sector-neutral step silently erased entire legs of the live/simulated book

**Severity:** 9/10 (live-path bug — shipped default since V5.1 Phase 1) · **Status:** 🟢 `fixed`

**Problem:** Sector-neutral demeaning subtracted each bucket's mean signed weight from members, driving members to exactly zero whenever a bucket has zero within-bucket dispersion — true by construction since callers equal-weight names per role. `"Forex"` (all 15 tickers one bucket) structural, not rare: whenever the short leg had forex representation, demeaning erased it entirely. Found via `aq evaluate --rank-book` showing `mean_names_short=0.00` despite `bottom_n=6`.

**Fix:** Replaced demean-to-zero: leave bucket untouched if `|net| <= sector_max_net_weight`, else shrink whole bucket proportionally (sign preserved, never amplified) so net lands exactly at cap; single-member buckets no longer special-cased; side effect judged correct — single-member bucket already exceeding cap now capped too (previously exempt).

**Verification:** `tests/test_book_neutrality.py` rewritten, 12 tests incl. monolithic-role regression guard; end-to-end on Codespace real model/data: `net_sharpe` 0.4856→0.9694, `mean_names_short` 0.00→6.00; not yet re-verified with a Lean backtest — `sector_neutral: true` config default since Phase 1, affecting live decision path too.

---

### 82. V5.1 Phase 4's walk-forward net-performance step crashed on window 1 — fed the exported model the wrong feature list (49 raw names instead of the 66 it was actually trained on)

**Severity:** 7/10 (crashed the entire walk-forward run on window 1) · **Status:** 🟢 `fixed`

**Problem:** Net-performance call site passed outer `feature_names` (49 raw pre-scaling names from `config["phase1"]["features"]["input_set"]`) instead of the 66-column `model_input_names` models actually trained against — `ValueError: _conv1d_causal: in_channels mismatch (49 vs weight's 66)`.

**Fix:** Both call sites now use `dataset_manifest["model_input_names"]`.

**Verification:** Exact run that crashed window 1 completed all 6 windows post-fix; no unit test caught it — fixtures used tiny single-feature lists where "raw" vs "model input" names never genuinely distinct.

---

### 83. V5.1 Phase 4's walk-forward sequence training hits a hard memory ceiling on the project's Codespace machine type for larger training windows

**Severity:** 6/10 (no corruption — degraded cleanly to multitask fallback — but weakened statistical power of 3 of 6 windows) · **Status:** 🟢 `fixed` (root cause found and fixed at start of Phase 5)

**Problem:** SIGTERM-killed on windows >~130-147k rows (3 of 6 in CODESPACE RUN 3), always constructing dense `(rows, 30, 66)` tensor; partial fix (freeing parent's held dataset) recovered one window, not ceiling. Root cause: built full `sequences` array once but extracted backtest split ~250 lines later — ~1.08GB resident through entire training loop on machine with 7.8GB RAM, zero swap.

**Fix:** Moved split extraction next to train/validation splits; `del sequences; gc.collect()` before training starts; switched `evaluation/model_predictions.py::build_sequence_windows()` float64→float32 matching `train.py` dtype.

**Verification:** Standalone re-runs on 3 largest windows (146,868 / 153,696 / 160,219 rows) succeeded first attempt; summary regenerated at full 6/6 windows; sequence Sharpe windows 3-5 moved from fallback values (0.91, −0.26, −0.26) to real sequence values (0.39, 0.62, 1.47), all positive.

---

### 84. Rank heads were sigmoid-squashed at inference but trained raw against an MSE target

**Severity:** 8/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** Rank heads (`rank_5d`/`rank_20d`/`sector_neutral_rank_20d`) trained raw linear output vs `[0,1]` percentile target, but export wrapped every head in leftover `"sigmoid"` — compressing live `predicted_rank_20d` into ~[0.475, 0.75], silently tightening `min_rank_confidence_spread` ~4x, capping confidence near 0.5, zero-sizing bottom-ranked shorts; invisible to rank-quality gates because rank-IC is invariant under monotone transforms.

**Fix:** Export activation `"sigmoid"`→`None` for every rank head; per-bar cross-sectional percentile normalization at inference (`portfolio/rank_signal.py::cross_sectional_rank_scores()`), since pure ranking loss makes absolute output scale meaningless by construction.

**Verification:** Manual code/architecture fix; no backtest cited.

---

### 85. `sector_mapping.json` covered 29 of the universe's 104 assets

**Severity:** 6/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** 75 of 104 tickers defaulted `"Unknown"` (all 15 forex pairs, most crypto/equities), making `target_sector_neutral_rank_20d` (live head, `loss_weight: 0.3`) nearly duplicate plain `rank_20d` for 72% of universe; genuinely small sectors NaN'd under `min_sector_size: 3`.

**Fix:** Full 104-ticker mapping (GICS-like buckets equities; `Forex`/`Crypto`/`Fixed Income`/`Broad Market ETF` rest); `AAA` deliberately unmapped as documented ambiguous legacy ticker.

**Verification:** Manual review; no backtest cited.

---

### 86. The constructed book was silently truncated by `max_active_positions`, not by rank

**Severity:** 5/10 · **Status:** 🟢 `fixed` (V5.1)

**Problem:** `top_n=10 + bottom_n=10` requests 20 names but `max_active_positions=15`; excess rejected in `self.symbols` iteration order — accident of universe ordering, not conviction.

**Fix:** Presets set `max_active_positions >= top_n + bottom_n`; when cap binds, Pass 2 sorts candidates by rank-confidence so strongest convictions survive.

**Verification:** Manual code/config fix; no backtest cited.

---

### 87. `capacity_curve()`'s binding-ticker search let a forex pair's fake zero dollar volume dictate the whole book's capacity

**Severity:** 5/10 · **Status:** 🟢 `fixed`

**Problem:** Binding-ticker search picks lowest-average-dollar-volume held name; forex pairs always report `liquidity_log_dollar_volume == 0.0` (Yahoo reports no FX volume), so any forex pair won automatically, producing sub-$1 `capacity_usd` (0.3-0.6 observed) failing every promotion gate regardless of rest of book's real liquidity. Secondary bug: inverse of `log1p()` is `np.expm1()`, not `np.exp()` (used instead).

**Fix:** Exact-zero tickers excluded from binding search (true zero = no liquidity signal, not "most illiquid"); `np.exp`→`np.expm1` fixed alongside.

**Verification:** 3 new tests in `tests/test_rank_book_simulator.py` (zero-volume exclusion, all-zero fallback, exact value distinguishing `expm1` from `exp`).

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

**Problem:** Crypto/FX were regularly selected but never placed one real order — forex's synthetic quote-bar conversion hardcodes `volume=0.0`, tripping liquidity gate's zero-volume block. Live also carries ~10 risk/execution gates offline's Sharpe engine never models, two duplicating signal already an active input feature.

**Fix:** Added `zero_volume_fallback_ddv` (forex always; crypto only `quality_tier=="core"`) substituting realistic daily-dollar-volume estimate without bypassing participation/cost gates. Book-selection-aware confidence thresholds; narrowed `risk_off`/`topology_elevated` overrides using real-data-derived thresholds; `aq evaluate --calibrate-confidence-threshold` + `book_member_decisions` diagnostic.

**Verification:** 33 new tests; suite 2530 passed. Real backtest (2026-08-10): Sharpe -4.103→-2.984. First attempt crashed deferred-write bug (`spread_check_ranks` UnboundLocalError), catchable only via real bar-to-bar Lean run — fixed, re-run succeeded. Surfaced two further bugs (forex sizing, sticky kill-switch lockout) — see #93.

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

### 95. Full-scale production retrain with gate-aware ranking weights promoted to active `ml/`; RL sizing re-confirmed negative a third time; full-epoch walk-forward validation (V5.2.9)

**Severity:** n/a (production training round, no defect) · **Status:** 🟢 `fixed and verified`

**Problem:** #94 shipped flag off, verified only via 3-epoch smoke, no flag-off control — does it hold at real (120/60-epoch) scale? Full training/validation/promotion cycle ready? Topology training needs real backtest experience events via local Postgres/Redis — out of scope (user instruction).

**Fix:** Enabled `gate_aware_ranking_weights.enabled: true` (user's explicit choice). Full Codespace pipeline at real epoch counts (baseline/gating/multitask/sequence/RL sizing); selector/topology skipped (no Postgres/option data). Promoted to active `ml/`, backed up to `ml/_backup_pre_v529_full_retrain/`. Full 6-window `--walk-forward`, validation only.

**Verification:** rank_5d IC 0.097→0.109; rank_20d IC 0.152→0.173; sector-neutral/residual ranks up. Direction MCC regressed slightly — dataset refresh and flag changed simultaneously, not cleanly attributable; net judged positive. RL negative reproduced third time; stays disabled. Walk-forward: rank_20d_ic mean 0.085 (stable, 0% sign flips), net Sharpe mean ~0.65 (5/6 windows positive). Topology untouched; rollback available.

**Follow-ups:** representative Lean backtest (user, manual); topology-training backtest; isolating dataset-refresh vs flag effect.

---

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

### 101. `aq evaluate --all`'s non-JSON reporting crashed on Windows — a Greek Δ character isn't in the cp1252 console codec

**Severity:** 3/10 · **Status:** 🟢 `fixed`

**Problem:** Refreshing README evaluation numbers post-#100 (`aq evaluate --all --model sequence`/`--model multitask`, non-`--json`) crashed both with `UnicodeEncodeError: 'charmap' codec can't encode character 'Δ'` — `aq_cli.py`'s delta-print line (`f"  Δnet_sharpe vs entry_lag_bars=0: ..."`) used literal Δ, absent from Windows cp1252 console codec (unlike em-dashes safe elsewhere). Crash hit mid-`--all`, after rank-book reporting but before capacity/stress/calibrate-edge ran and before README refresh call — Windows-console `--all` runs silently left capacity/cost-stress numbers stale, README unrefreshed, error only on stderr.

**Fix:** Δ replaced with ASCII `delta_net_sharpe` label.

**Verification:** `py_compile aq_cli.py` clean; `tests/test_aq_cli.py` (216 tests) green; both `--all` re-runs completed end-to-end, refreshing sections stuck since Aug 13.

---

### 102. Real V5.3.3 backtest (2026-08-17): factor-file fix strongly confirmed live for 3-4 of 5 tracked tickers — but the confidence-spread recalibration made real Sharpe measurably worse, isolated cleanly to that one change

**Severity:** 6/10 · **Status:** 🟢 `fixed and verified` (factor-file fix, #100, for GE/BA/NVDA/WFC); 🔴 `regressed` (confidence-spread recalibration) — recommend reconsidering the applied value

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

### 103. A rolling trailing-IC gate, addressing #102's recommendation directly — built, offline-verified against real data, wired into `main.py` behind `enabled: false`; live effect not yet tested

**Severity:** 6/10 (same issue as #102) · **Status:** 🟡 `built and offline-verified, not yet live-tested` — real `aq backtest` still needed before this can close #102

**Problem:** #102 found `min_rank_confidence_spread` (same-day raw-score dispersion) can't tell "model differentiates symbols today" from "differentiation directionally correct" — recalibrated threshold traded through known no-skill eras because dispersion looked normal when skill didn't exist. #102's recommendation: smarter calibration accounting for per-era IC stability.

**Fix:** Independent second veto — `portfolio/rolling_ic_gate.py::evaluate_rolling_ic_gate()` gates book engagement on TRAILING REALIZED rank-IC (was model right recently), computed from live in-memory buffer of past predictions resolved against realized 20-day forward return, entirely separate from `min_rank_confidence_spread`. New `evaluation/rank_ic_core.py` extracts correlation/resolution math from `train.py`/`performance/rank_ic_monitor.py` into torch-free module so `main.py` imports without risking #16's isolator-timeout failure class (`train.py` imports torch/sklearn at module scope; `performance/__init__.py` transitively imports train.py). Two tools mirror existing patterns: `aq evaluate --calibrate-rolling-ic-floor` (floor derived from real walk-forward rolling-IC distribution, never guessed) and `aq evaluate --replay-rolling-ic-gate` (day-by-day no-lookahead replay, per-era breakdown vs three known bad eras — critical pre-`main.py` checkpoint). `portfolio/book_construction.py` gained additive `None`-default parameters (`rolling_ic_gate_result`, `veto_reason_out`) rather than return-type change — `build_rank_based_book()` has 6+ callers beyond `main.py`. `build_book_history_record()` gained `gate_veto_reason`; `main.py` book-history write condition fixed to log every genuine rebalance bar even when book returns empty (previously vetoed bar left zero trace, true since #91/V5.2.4 for existing dispersion gate too).

**Real bug found and fixed mid-round, via gate's own checkpoint:** first calibration+replay showed wrong pattern — era_2/era_3 0% disengagement even at raised floor while calibrated minimum was implausible -0.9999999999999999. Root cause: origin dates with 2-3 resolved names are mathematically FORCED to Spearman ±1 regardless of skill (two points fit any line); thin-universe readings averaged into `mean_ic` at equal weight with 100-name dates, dominating the low tail. Fixed via new `min_names_per_date` threaded through `rank_ic_from_arrays()`/`aggregate_rank_ic_observations()`/`compute_rolling_ic_state()` (default 2 preserves callers; tools/live default 10). Second bug surfaced: with filtering, `num_resolved_dates` structurally plateaus ~22-24 of 40-day window across entire dataset (start/middle/end checked, not warmup artifact) — `min_resolved_dates_required=40` could never satisfy, gate always fell back "insufficient history"; lowered to 20.

**Result after both fixes — real, measured:** calibrated floor at p25 (+0.020, `min_names_per_date=10`) replayed vs required=20: 20/82 rebalance dates disengaged (24.4%), cleanly concentrated — era_0 **0%**, era_1 (Apr-Sep 2019) **37.5%**, era_2 (Dec 2019-Mar 2020) **22.2%**, era_3 (Jun-Sep 2020) **22.2%**. Era_3 spot-check: readings mostly strongly positive (0.19-0.63) with brief real no-skill dip mid-July 2020 (0.005 then -0.091) gate correctly narrowly catches.

**Verification:** New tests: `test_rank_ic_core.py` (13), `test_rolling_ic_gate.py` (14), `test_rolling_ic_gate_calibration.py` (7, incl. no-lookahead prefix-invariance), `test_rolling_ic_gate_replay.py` (8, headline property), `test_portfolio_book_construction.py` extended (+9 incl. byte-identical-when-`None` guard). Suite 2688 passed, 0 failures (11 pre-existing Docker errors unrelated). Both CLI tools ran vs real `ml/datasets/backtest_dataset.csv`; fresh `--reconcile-all-runs` vs all 9 backtests confirmed optional parameters changed nothing existing. Config ships `enabled: false`.

**Follow-ups:** user's manual `aq backtest` verifies actual Sharpe improvement over #102's -1.798 baseline (same discipline as #102: offline story looked right for confidence-spread too, real backtest showed regression). Before run: `aq config set phase_v2.rolling_ic_gate.min_rolling_mean_ic 0.02`, then `...enabled true`. After: check `gate_veto_reason` in `book_history.jsonl` for `"rolling_ic_below_floor"` during bad eras specifically (vs `"min_rank_confidence_spread_below_floor"`, meaning old gate doing all work). Workstream B (feature-level XOM investigation, see #91/#100) scoped, not started — independent.

**Update (2026-08-19 real backtest — written up in V5.3.5.3):** prescribed run happened (`backtests/2026-08-19_13-33-56`, both `aq config set` commands applied, gate live at floor 0.02). **Headline: Sharpe -1.798 → -1.832 — gate did NOT recover regression** (Net -5.51%→-5.888%, Drawdown 6.90%→6.400%). But mechanism works as built: orders fell 695→462 (-33%), fees $880→$596.54, and `gate_veto_reason` answers verification question directly — new veto fired 106x vs old spread gate's 21x (plus 260 pre-existing `thin_universe_or_zero_top_n`) across cumulative log, i.e. `rolling_ic_below_floor` genuinely does most disengagement work now, not a passenger. Honest interpretation: gate refuses low-skill stretches, but what it ALLOWS through isn't profitable either — engagement quality outside bad eras is binding constraint; pre-V5.3.3 -1.034 baseline unrecovered. Per user decision, gate stays enabled at 0.02, spread stays 0.2831 — V5.3.5.3 measures exactly this configuration. Workstream B shipped in V5.3.5.3 (see Changelog): `build_book_history_record()` allowlist-bounded `feature_snapshot` field, `phase_v2.diagnostics.book_history.include_feature_snapshot`/`feature_snapshot_symbols` flags, `aq evaluate --reconcile-features --symbol XOM`; XOM verdict awaits snapshot-collecting backtest.

---

### 104. Chronic Lean embedded-Python teardown hang ("endless loop") — fires only after normal completion, never affects results; probe shipped, culprit unnamed

**Severity:** 3/10 (exit-log noise only — results are always fully written first) · **Status:** 🟡 open (differential analysis done, diagnostic probe shipped, awaiting one more real run to name the resource)

**Problem:** commit c2ed98c's "endless loop found in backtest log" is Lean embedded-interpreter teardown timing out: after `PythonInitializer.Shutdown(): start/calling engine shutdown...`, ~10s elapse, then `Isolator.ExecuteWithTimeLimit(): Execution Security Error: Operation timed out - 0.1666... minutes max. Check for recursive loops. (Isolator.cs:179)` and `Program.Exit(): Failed to shutdown python System.TimeoutException (Launcher/Program.cs:145)`. Classic CPython finalization blocking on still-alive non-daemon thread or native handle while isolator kills interpreter at its 10s limit.

**Differential analysis (all local logs checked):**
- **Chronic, not new:** 72 of 78 runs reaching teardown hang identically, back to earliest log on disk (2026-05-07), spanning many code versions — nothing recent introduced it.
- **Never affects results:** hang occurs after statistics/JSONs/order-events fully written; impact limited to ERROR line, failed exit code, ~10s wall clock.
- **Normal completion vs error termination is the discriminator:** both genuinely-clean completed runs (2026-07-06_17-35-38, 2026-07-19_16-48-18) terminated via mid-run Python runtime error or Stopped state; essentially every run whose Python execution reached normal completion hangs — something built during bar processing survives to block finalization.
- **Ruled out:** duration/window size (4.53s run hung; 14.53s exited cleanly); inference parallelism pool (#70's explicit pool.shutdown() exists, ships default-off anyway); audit/experience queues (no threads / daemon=True drain thread); matplotlib/pyplot use in main.py (none); cpp_inference_ext in hot path (none).

**Fix (this round):** no speculative fix without named culprit. `main.py::on_end_of_algorithm()` gained zero-risk shutdown-probe: Debug line dumping every still-alive thread (name + daemon flag) right before teardown begins, so next run's log shows exactly what survives and blocks finalization.

**Verification:** py_compile only so far (no unit test can exercise embedded-interpreter teardown). Decisive evidence is next real backtest: log should carry `shutdown-probe:` line immediately before timeout (or clean exit with probe present narrows trigger).

**Follow-ups:** read `shutdown-probe: alive_threads=[...]` from next run's log; once surviving resource named, add targeted cleanup (explicit close/shutdown of owning library object), re-verify with subsequent run's clean `PythonInitializer.Shutdown(): ended`.
