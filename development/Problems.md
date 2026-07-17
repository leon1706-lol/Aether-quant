# Problems

Bugs and infrastructure issues found in this codebase, how they were fixed
(or why they're still open), a severity rating (1 = cosmetic, 10 = critical
data-loss/safety issue), and a status tag. Newest first.

---

### 1. `experience-worker` crash loop — missing `numpy` dependency
**Severity:** 6/10 · **Status:** 🟢 `fixed`

`experience/observation_metrics.py` (added in V2-15) imports `numpy` for
`simulated_sharpe`. `experience/__init__.py` imports `observation_metrics` at
package level, so merely importing the `experience` package now transitively
requires `numpy`. `requirements-worker.txt` (backing `Dockerfile.worker`,
the `experience-worker` Docker service) only listed `redis` and
`psycopg[binary]`. Found live while inspecting running containers during
V2-16 planning — the container was stuck in `Restarting (1)` with
`ModuleNotFoundError: No module named 'numpy'`.

**Fix:** added `numpy>=1.24.0` to `requirements-worker.txt`, rebuilt
(`docker compose build experience-worker`), restarted
(`docker compose up -d experience-worker`), confirmed clean startup via
`docker compose logs -f experience-worker`. Applied proactively to the new
V2-16 `requirements-trigger-worker.txt` so the same class of bug isn't
repeated in the new trigger worker.

---

### 2. `Dockerfile.worker` missing `execution/` copy
**Severity:** 6/10 · **Status:** 🟢 `fixed`

V2-15 added `experience/simulated_portfolio.py`, which imports
`execution.order_gate`. `experience/__init__.py` imports
`simulated_portfolio` at package level. `Dockerfile.worker` only copied
`experience/` into the image, not `execution/` — a rebuild of the
`experience-worker` service would have failed immediately with
`ModuleNotFoundError: No module named 'execution'`. Found by tracing the
import chain during V2-15 implementation, before any rebuild was attempted.

**Fix:** added `COPY execution/ ./execution/` to `Dockerfile.worker`.
Documented as a standing lesson in `development/v2_architecture.md`'s
Docker section, and applied proactively to the new
`Dockerfile.trigger_worker` (V2-16) which also needs both `execution/` and
`experience/`.

---

### 3. Simulated portfolio/positions snapshot not mode-aware
**Severity:** 5/10 · **Status:** 🟢 `fixed`

`main.py`'s `_snapshot_positions()` and the top-level `state["portfolio"]`
dict (`total_portfolio_value`, `cash`, `holdings_value`, `invested_positions`)
read unconditionally from the real Lean `self.Portfolio`. In `observation`
mode the real portfolio never invests (by design), so the dashboard's
Positions panel, the Market Scene's portfolio-link weights, and the top-level
Scorecards always showed the flat starting cash — while `current_drawdown`
(already fixed to be mode-aware) showed real simulated drawdown. Result: the
webui showed a visibly contradictory state (e.g. "Portfolio Value $100,000"
next to "Total Drawdown -12.23%"). Found via live screenshot review with the
user during V2-15 verification.

**Fix:** added `_snapshot_portfolio_summary()` and made `_snapshot_positions()`
mode-aware — both now read from `SimulatedPortfolioState` when real orders
are blocked (`_order_permission()` returns `False`), matching the pattern
already used for `_active_position_count`/`_asset_class_exposure`/
`_refresh_risk_state`.

---

### 4. Webui: empty space above Market Scene panel
**Severity:** 2/10 · **Status:** 🟢 `fixed`

`Overview.tsx`'s outer two-column layout used CSS Grid with default
`align-items: stretch`. Since the right column (Signal Board, Positions,
Risk, Monitoring, Observation panels) is taller than the left column
(Scorecards, 3D scene, Asset Heatmap), the grid stretched the left column's
container to match — and the inner `grid gap-4` wrapper's
`align-content: normal` (which behaves as `stretch` for CSS Grid) then
distributed that extra height across the left column's own rows, padding out
each panel's bottom with blank space (most visible in the smallest one,
Scorecards). Found via a live Playwright screenshot during V2-15 review.

**Fix:** added `items-start` to the outer grid and switched both column
wrapper `<div>`s from `grid gap-4` to `flex flex-col gap-4` (a flex column
naturally sizes to its children's content with no cross-stretch behavior).

---

### 5. Webui: Signal Distribution / Rejected By Reason tables overflow the panel
**Severity:** 2/10 · **Status:** 🟢 `fixed`

`ObservationPanel.tsx`'s `CountTable` sub-component rendered label/count
pairs as an HTML `<table>` inside a CSS Grid cell. Long reason strings (e.g.
`liquidity_blocked_insufficient_volume_simulate_instead`) forced the table
wider than its grid track; since CSS Grid items default to `min-width: auto`
(not `0`), the track couldn't shrink to contain it, pushing the count column
off the edge of the panel/viewport. Found via the same live screenshot
review as #4.

**Fix:** replaced the `<table>` with flexbox rows (`flex justify-between`),
added `min-w-0` to the grid containers so they're allowed to shrink, and
`break-words` on the label so long strings wrap instead of overflowing.

---

### 6. `aether-grafana` container name collision blocks the real Grafana service
**Severity:** 3/10 · **Status:** 🟢 `closed (moot)`

Found during a Docker inventory review (unrelated to V2-15/16 code — a
housekeeping finding). A container named `aether-grafana` exists (exited 8
weeks ago) with no `com.docker.compose.*` labels, meaning it was started
with a plain `docker run`, not `docker compose up`. It's bound to host port
3000 (conflicting with the webui dev server) and mounts a `grafana-storage`
volume with an extra bind-mount that isn't in the current `docker-compose.yml`
at all. The current `docker-compose.yml`'s actual `grafana` service also
wants `container_name: aether-grafana` (port 3001, volume `grafana-data`) —
since Docker container names must be unique, this orphaned container would
block `docker compose up -d grafana` from ever creating the real one.

**Re-checked 2026-07-04 (V2-21/22 planning pass):** `docker ps -a` shows no
`aether-grafana` container at all anymore, and `docker-compose.yml` no
longer defines a `grafana` service (removed entirely in V2-18, in favor of
the React tracing dashboard). The collision this item describes can no
longer happen. Closed as moot rather than fixed — no action was taken,
the scenario stopped applying once Grafana was removed from the stack.

---

### 7. ~85GB of orphaned duplicate Lean engine images + stale containers/volumes
**Severity:** 2/10 · **Status:** 🟢 `fixed`

Found during the same Docker inventory review. Two untagged
(`<none>`) `quantconnect/lean` images (`650dd8d4063a`, `cb13534ee02c`,
42.5GB each) are superseded by the currently-tagged
`quantconnect/lean:latest` — leftovers from earlier Lean CLI version
updates. Two exited containers (`quizzical_maxwell`, `loving_antonelli`,
one-off ad-hoc `lean backtest` runs from 2 weeks ago against an unrelated
`Aether-Vault-Test` folder) pin the older image and must be removed before
it can be deleted. Four of five `lean_cli_python_*` volumes are unused
pip-cache leftovers from past dependency-hash changes (only one is mounted
by the current Lean CLI container). Also found: a stray, orphaned
`aether-quant:latest` image tag (pre-rebuild, no longer referenced by any
container since `docker compose` now tags it `aether-quant-aether-quant`),
and unused standalone `redis:latest`/`postgres:latest` image pulls not
pinned by either `docker-compose.yml` (aether-quant or aether-vault).

**Re-checked 2026-07-04 (V2-21/22 planning pass):** `quizzical_maxwell`,
`loving_antonelli`, `cb13534ee02c`, the four named `lean_cli_python_*`
volumes, and the stray `aether-quant:latest`/`redis:latest`/`postgres:latest`
tags are all genuinely gone — the ~85GB figure and the original combined fix
command are stale. **Correction, 2026-07-05:** the first re-check incorrectly
claimed `650dd8d4063a` (one of the two original untagged 42.5GB
`quantconnect/lean` images) was also gone — a plain `docker images` should
have shown it and didn't get checked carefully enough at the time. It is
still present (`docker images -a` confirms a `<none>:<none>` entry with this
exact ID, 42.5GB, no container references it) and is a real, sizeable orphan.
Also found, separately: an unused `grafana-storage` volume and an unused
`grafana/grafana:latest` image (~1.45GB), leftover from before Grafana was
removed in V2-18 — neither referenced by the current `docker-compose.yml`.
**Fixed, 2026-07-05:** `docker volume rm grafana-storage`, `docker rmi
650dd8d4063a`, and `docker rmi grafana/grafana:latest` all applied by the
user; re-verified via `docker images -a`/`docker volume ls` that all three
are gone. All Aether-Vault images, containers, and volumes
(`aether-vault-*`) were explicitly left untouched throughout — they were
never orphans, just a separate project's own (currently stopped) stack.

---

### 8. Bare `pytest` (no path) fails from repo root
**Severity:** 3/10 · **Status:** 🟢 `fixed`

`README.md`'s documented test command is bare `pytest` (no `tests/` path).
Running it from the repo root also crawls `backtests/*/code/tests/`
(each backtest run copies the full algorithm code, including `tests/`, into
its own output folder) — pytest's default rootdir-relative import mode then
hits duplicate-module-name collisions between e.g. `tests/test_risk_controls.py`
and `backtests/2026-07-01_19-40-05/code/tests/test_risk_controls.py`,
producing ~76 collection errors and refusing to run anything. `backtests/`
is gitignored, so this only bites locally once enough backtests have
accumulated — not on a fresh clone. Found while verifying the V2-15 test
suite.

**Workaround in use:** always run `pytest tests/` (explicit path) instead of
bare `pytest`. Not yet fixed at the root: `README.md` still documents the
bare form. A real fix would be a `pytest.ini`/`pyproject.toml` with
`testpaths = tests` and/or `--ignore=backtests`, or excluding `tests/` from
what gets copied into each backtest's `code/` snapshot in the first place.

**Fixed** (incidentally, while adding `pyproject.toml` for the `aq` CLI's
console-script entry point — see #9): `pyproject.toml`'s
`[tool.pytest.ini_options]` now sets `testpaths = ["tests"]`, so a bare
`pytest` from the repo root only collects `tests/` and no longer crawls
`backtests/*/code/tests/`. `README.md`'s runbook still shows the explicit
`pytest tests/` form since it's clearer to a new reader, but bare `pytest`
now works too.

---

### 9. Total-drawdown trade lock never auto-clears within a run
**Severity:** 4/10 · **Status:** 🟢 `addressed` (manual override + auto-clear on promotion, not a behavior change to the default)

`main.py::_refresh_risk_state()`'s session-rollover branch only resets
`trade_lock_active` when `trade_lock_reason != "total_drawdown_limit_breached"`
— a daily-drawdown lock clears every new trading day, but a total-drawdown
breach is never cleared anywhere else in `main.py` for the rest of that run.
Found while investigating a user-reported retraining-cadence question: a
real run's `rejected_by_reason` data showed `total_drawdown_limit_breached`
blocking ~3948 of ~5000 events — the run almost certainly breached this once,
early, and never traded again for the remainder.

This reads as an intentional capital-preservation circuit breaker (consistent
with this codebase's existing bias toward manual gates elsewhere — e.g.
`retraining`'s manual `promote`/`rollback`), not a bug to silently patch away,
so the underlying sticky-by-default behavior is unchanged.

**Addressed via:** a new manual override,
`phase_v2.risk.manual_trade_lock_override` (`true`/`false`/absent), read once
per session rollover by `_refresh_risk_state()` via
`risk/manual_override.py::read_manual_trade_lock_override()` — a deliberate,
narrow exception to "config is stable within a run," scoped to this one key
so a long-running paper/live process can pick up a change without a restart.
Two things can flip it: the new `aq trade-lock --on/--off/--auto` CLI command
(a human decision), and `retraining/orchestrator.py::promote()` (auto-clears
it on every successful promotion, gated by
`phase_v2.retraining.promotion.auto_clear_trade_lock`, default `true`) —
ties "trading resumes" to "a genuinely new model shipped," not to a bare
restart. See the Manual Trade-Lock Override Contract in
`development/v2_architecture.md`.

---

### 10. `ci.yml`'s `test` job fails on GitHub's Linux runner — root cause found and fixed
**Severity:** 3/10 · **Status:** 🟢 `fixed`

Found while setting up the open-source release pipeline (PyPI + GHCR
publishing via `.github/workflows/ci.yml`/`release.yml`). Three distinct
problems surfaced in sequence, all triggered by the same event: this was the
**first time anyone ever ran a truly clean install + bare `pytest` invocation**
of this repo (every local dev session, this one included, always used
`python -m pytest` from an already-populated `.venv`, which masks the
underlying gaps described below).

1. **Fixed** — `requirements/requirements-dev.txt` listed `lean-cli>=35.0`
   and `qcalgorithm>=1.0`, neither of which exists on PyPI under those names
   (confirmed via PyPI's JSON API: both 404). The real QuantConnect package
   is named `lean`, which also pulls in `quantconnect-stubs` transitively
   (what `qcalgorithm` was presumably trying to reach). Changed to
   `lean>=1.0.225`.
2. **Fixed** — bare `pytest` (the installed console script, not
   `python -m pytest`) never had this repo's root on `sys.path`: unlike
   `python -m pytest`, which causes Python itself to prepend the CWD,
   invoking `pytest` directly leaves it to pytest alone to decide what's
   importable, and pytest's default "prepend" import mode only adds the
   nearest `__init__.py`-free directory (`tests/` itself) — not the repo
   root one level up, where `train.py`, `moe/`, `risk/`, `retraining/`, etc.
   all live. Every test file that imports a first-party module failed with
   `ModuleNotFoundError`. Fixed by adding `pythonpath = ["."]` to
   `pyproject.toml`'s `[tool.pytest.ini_options]`, which works identically
   regardless of invocation style or OS.
3. **Fixed** — after both fixes above, dependency install and test
   *collection* both succeeded in CI, but the actual `pytest` run itself
   still failed (`exit code 1`) on GitHub's `ubuntu-latest` + Python 3.11
   runner while passing locally. Root cause was finally obtained by
   installing/authenticating the `gh` CLI (`winget install GitHub.cli` +
   `gh auth login`, a one-time browser device-code prompt) and running
   `gh run view <run-id> --log --job <job-id>` — the fastest path the
   previous pass through this entry had already identified but not yet
   executed. The real pytest summary: `4 failed, 1285 passed, 6 skipped,
   1 warning, 11 errors`. Neither of the two long-standing suspected causes
   (Linux BLAS numeric precision, a Python 3.11-vs-3.14 stdlib behavior
   difference) was the actual culprit for 3 of the 4 failures or the 11
   errors — both hypotheses turned out to be reasonable guesses that the
   real log immediately disproved, a good example of why "grab the real
   traceback" beats guessing from symptoms alone. Three independent root
   causes, all now fixed:
   - **3 of the 4 `FAILED` tests** (`test_futures_risk.py::test_load_futures_contract_specs_from_real_reference_file`,
     `test_ib_backfill.py::test_load_futures_contract_specs_from_real_reference_file`,
     `test_train_cross_sectional_features.py::test_load_sector_mapping_reads_the_checked_in_reference_file`)
     all read one of two small, hand-authored reference files —
     `data/reference/futures_contract_specs.json` and
     `data/reference/sector_mapping.json` — that their own test names call
     "the checked-in reference file." They were never actually checked in:
     `.gitignore`'s blanket `data/**` rule (added to keep bulk Lean market
     data out of a public repo) swallowed these two small config files
     along with it, so every fresh checkout (any CI runner, or a fresh
     local clone) silently had neither file, while every existing local
     dev environment (this one included) had them on disk from whenever
     they were first hand-authored, masking the gap identically to how
     `python -m pytest` masked fix #2 above. Fixed: added a
     `!data/reference/*.json` exception to `.gitignore` and committed both
     files (confirmed non-sensitive: static contract specs and a ticker
     -> sector map, no credentials).
   - **1 of the 4 `FAILED` tests**
     (`test_bond_features.py::test_empirical_duration_beta_none_when_delta_yield_has_zero_variance`)
     — this one WAS a genuine Python 3.11-vs-3.14 stdlib difference, just
     not in the place either standing hypothesis pointed at.
     `features/bond_features.py::empirical_duration_beta()` checked
     `variance_x == 0.0` (exact equality) to detect a mathematically
     constant input series. CPython changed `sum()`'s internal float
     summation algorithm between 3.11 (naive left-to-right) and 3.12+
     (compensated/Neumaier) — on 3.14 (this dev machine) the constant
     series' mean/variance round to exactly `0.0`; on 3.11 (CI) tiny
     summation rounding noise (~1e-20 scale) survives, so the exact
     equality check silently failed and the function returned a wild
     `covariance / near-zero-noise` ratio (`-12.515...`) instead of the
     intended `None`. Fixed: `variance_x < 1e-12` (still many orders of
     magnitude below any real delta-yield variance in this codebase's
     data, and light years above the rounding-noise floor) instead of
     exact equality.
   - **All 11 `ERROR`s** were a single new regression, not present when
     this entry was first opened: `tests/test_lean_backtest_ml_coverage.py`
     is meant to self-skip when no usable local Lean setup exists (its own
     module docstring says so), but fix #1 above (installing the real
     `lean` PyPI package) had the side effect of putting the `lean` binary
     on CI's PATH for the first time — the skip check only ever tested
     binary *presence*, not whether a real backtest could actually run, so
     CI stopped skipping and instead launched a real `lean backtest .`
     that immediately failed with `Unable to locate symbol properties
     file: Data/symbol-properties/symbol-properties-database.csv`. That
     file (like every other Lean bootstrap reference file under `data/`)
     is also caught by the `data/**` gitignore rule above — CI's fresh
     checkout has no Lean Data folder at all, which was always true and
     always the reason this test was meant to skip there; fix #1 just
     changed which half of the skip condition silently stopped holding.
     Fixed: the skip guard now also checks for
     `data/symbol-properties/symbol-properties-database.csv` (the exact
     file the real error named) via a new, independently unit-tested
     `_lean_data_folder_is_usable()` helper, restoring the originally
     intended skip-in-CI/run-locally behavior without needing to vendor
     Lean's bootstrap data into git. `ci.yml`'s explanatory comment updated
     to match (it previously and incorrectly said GitHub runners "don't
     have" the Lean CLI at all).

**Verification**: all 4 previously-`FAILED` tests plus 3 new regression
tests for the strengthened Lean skip guard
(`tests/test_lean_backtest_ml_coverage.py::test_lean_data_folder_check_*`)
pass locally. The 11 real-backtest tests still attempt to run locally
(this dev machine has a real Lean Data folder) and fail fast on a separate,
pre-existing, unrelated local condition — Docker Desktop's daemon isn't
running here — which is expected and not part of this fix; they were never
reachable from CI either way once the skip guard change lands there.
**Confirmed: the real GitHub Actions run on `ci.yml` after this fix
shipped passed** (user-confirmed after pushing) — this closes the loop
that every prior pass through this entry left open (guessing at a root
cause without ever seeing a green run afterward).

**Not blocking releases regardless**: `release.yml`'s `publish-pypi`/
`publish-docker` jobs still don't depend on a test job at all (removed at
the user's explicit request, in favor of testing locally before tagging) —
see `v2_architecture.md`/git history around the `v0.2.0` release.

---

### 11. `_write_state()`'s per-bar throttle was unreachable
**Severity:** 6/10 · **Status:** 🟢 `fixed`

Found during a latency audit of `main.py`'s per-bar hot path (`on_data()`/
`_write_state()`). The guard `if self.last_state_write == now and signals is
None: return` could never short-circuit, because `on_data()` always calls
`self._write_state(mode="runtime", insight=insight, signals=signals)` with a
non-`None` `signals` dict. Result: seven output files (`state.json`,
`scene.json`, `topology_state.json`, `runtime_metrics_snapshot.json`,
`runtime_asset_metrics.csv`, `observation_summary.json`,
`observation_equity_curve.csv`, `performance_triggers.json`) were fully
rewritten on every single bar, not throttled to once per timestamp as the
code's own intent implies.

**Fix:** dropped the impossible clause — `if self.last_state_write == now:
return`. Caps writes at once per distinct `self.Time` value (matching
`on_data()`'s actual call cadence), which is correct for live/paper and
removes the dead-code confusion. No config key needed; no behavior change
beyond "actually do what the code already intended." See also #12/#13,
found in the same audit pass.

---

### 12. `observation_equity_curve.csv` quadratic rewrite (N-per-bar equity-curve entries + full-file rewrite every bar)
**Severity:** 7/10 · **Status:** 🟢 `fixed`

Two compounding issues found in the same latency audit as #11:

1. `experience/simulated_portfolio.py::mark_to_market()` was called once
   *per symbol* per bar (`main.py::on_data()`, inside the per-symbol loop),
   each call unconditionally appending one entry to `self.equity_curve` —
   so after `B` bars × `N` symbols, the list held `N·B` entries instead of
   `B`, and (with all symbols' prices not yet known) each entry only
   reflected one symbol's price, not the whole portfolio's.
2. `main.py::_build_observation_equity_csv()` rebuilt the *entire* CSV
   string from the *entire* in-memory list on every flush. Combined with
   #11's bug (a flush every bar instead of once per timestamp), total
   cumulative write work was `O((bars·symbols)²)` — genuinely
   super-linear, not just slow, and very likely the dominant reason
   backtests scaled worse than linearly with timespan.

**Fix — cadence:** `on_data()` now accumulates a `close_prices_by_symbol`
dict across the per-symbol loop and calls
`mark_to_market(close_prices_by_symbol, bar_index=self.bar_index)` exactly
once after the loop, instead of once per symbol. This shrinks
`equity_curve` to exactly one entry per bar — a real whole-portfolio
snapshot, not `N` intermediate half-updated ones (arguably more correct
semantics, not just faster). Verified no other consumer of
`SimulatedPortfolioState.equity_curve` assumed the old N-per-bar
granularity (only `_build_observation_equity_csv`/its replacement reads
it; `monitoring/api_server.py` reads the CSV file, not the in-memory list).

**Fix — write cadence:** replaced `_build_observation_equity_csv()`'s
full-rebuild with `_flush_observation_equity_csv()`, an append-only flush
tracked via `self._equity_curve_flushed_count`: writes a header once on the
very first flush (mode `"w"`), then appends only the entries produced since
the last flush (mode `"a"`) on every subsequent call. Together, #11 + #12
turn `O((bars·symbols)²)` into `O(bars)`.

**Tests:** `tests/test_simulated_portfolio.py::test_mark_to_market_with_multi_symbol_dict_produces_exactly_one_equity_curve_entry`
asserts a single multi-symbol `mark_to_market()` call produces exactly one
`equity_curve` entry reflecting every symbol's updated price. The CSV
flush's row-count-equals-bar-count property is verified via the real Lean
backtest integration test's output file, matching this codebase's
established integration-only convention for `main.py`-level behavior (see
`tests/README.md`).

---

### 13. Per-bar/per-poll `config.json` reads on every session rollover, uncached
**Severity:** 5/10 · **Status:** 🟢 `fixed`

At Daily resolution, `self.Time.date()` changes every bar, so
`_refresh_risk_state()`'s `if self.current_session_date != current_date:`
guard — correctly intended as "once per session" for a live/paper
deployment — fires every single bar in a backtest. Inside it,
`read_manual_trade_lock_override()` and `read_paper_trading_config()` each
did a full `open()` + `json.load()` of `config.json`, every bar. The
identical pattern existed in `execution/runtime_config_io.py::read_runtime_mode()`,
called every iteration of `retraining/worker.py`'s poll loop (a different
process, same bug class). This is not a bug in *when* the check runs (that
part is correct and intentional, per the code's own comments) — it's that
the read itself is expensive despite `config.json` almost never actually
changing bar-to-bar.

**Fix:** new `execution/config_cache.py::read_cached(config_path, loader)`,
an mtime-gated cache: returns a cached value if the file's mtime hasn't
changed since the last call for that exact `(config_path, loader)` pair,
otherwise calls `loader` fresh. Falls back to calling `loader` directly,
uncached, when the file doesn't exist (preserving each loader's own
missing-file handling). Wrapped `read_manual_trade_lock_override`,
`read_paper_trading_config`, and `read_runtime_mode` with it (each renamed
to a private `_read_*_uncached` helper). Left
`retraining/orchestrator.py::_load_retraining_config()`,
`performance/trigger_worker.py::_load_performance_triggers_config()`, and
`notifications/telegram_worker.py::_load_telegram_config()` uncached —
confirmed these are only called once at process startup, not inside a
repeating loop, so caching adds complexity with no benefit.

**A real bug caught only by the Lean integration test, not by unit tests:**
the first version of `read_cached()` keyed its cache by `config_path`
alone. `_refresh_risk_state()` calls `read_manual_trade_lock_override()`
and `read_paper_trading_config()` back-to-back on the *same* `config.json`
path within the same session rollover — with the path-only cache, the
second call's cache lookup returned the *first* call's cached value (e.g.
`None`, the override's common "unset" value) instead of calling its own
loader, so `self.phase_v2_paper_trading` silently became `None` and crashed
`_recompute_broker_config()` (`'NoneType' object has no attribute 'get'`)
on the very first bar of a real `lean backtest .` run. Every unit test for
the three readers used its own isolated `tmp_path` with only one loader
ever touching it, so none of them could have caught this. Fixed by keying
the cache by `(config_path, loader)` instead of `config_path` alone.
Confirmed fixed by re-running the real Lean backtest integration test
end-to-end (see `tests/test_lean_backtest_ml_coverage.py`), and by a new
regression test,
`tests/test_config_cache.py::test_two_different_loaders_on_the_same_path_do_not_collide`.

**Tests:** `tests/test_config_cache.py` (loader-invoked-once-when-untouched,
invoked-again-after-mtime-change, missing-file passthrough, the
multi-loader-collision regression above). Extended
`tests/test_manual_override.py`, `tests/test_paper_readiness_io.py`,
`tests/test_runtime_config_io.py` with a regression assertion that a value
change is still picked up after the file's mtime changes, guarding against
the cache silently breaking hot-reload.

---

### 14. Redis push in backtest mode — deliberately left unoptimized
**Severity:** n/a · **Status:** 🟢 `resolved` (confirmed no-op, no code change needed)

`experience/redis_queue.py::push()` does a synchronous, blocking `XADD` per
symbol per bar, plus one more at every session rollover (which, per #13, is
every bar at Daily resolution in a backtest). Gating this off when
`runtime_mode == "backtest"` would be trivial — both call sites already
have `self.runtime_mode`/`self._experience_mode` available — and would save
real per-bar network I/O during backtests, which never need live
experience-stream delivery.

**Why this stayed open initially:** `development/v2_architecture.md`'s
Redis Experience Queue section documents `"backtest"` as one of four
normal, expected mode values flowing into Redis, and
`tests/test_experience_queue.py`'s default fixture treats `mode="backtest"`
as the canonical case, not an exclusion. There was at least one plausible
downstream dependency on backtest-mode Redis events reaching Postgres via
`experience-worker` — debugging via the observation dashboard against a
backtest run, or later analysis of a backtest's persisted events — that
had not been confirmed one way or the other. Skipping the push would have
contradicted documented, tested behavior on the strength of an unconfirmed
assumption.

**Resolution:** the project owner personally confirmed no downstream
process reads backtest-mode experience events out of Postgres. Since the
open question this entry was tracking is now answered, it's marked
resolved on that basis alone — `experience/redis_queue.py::push()` itself
is intentionally left unchanged (still pushes in backtest mode), since the
performance cost was never the blocker, only the unconfirmed dependency
was. A future optimization pass may still gate `push()` on
`runtime_mode != "backtest"` if the per-bar I/O ever becomes a real
bottleneck, but that is now a pure performance nice-to-have, not a
correctness fix blocked on missing information.

---

### 15. `ensure_derived_crypto_daily_series()` silently discarded yfinance-backfilled crypto history on every `train.py` run
**Severity:** 7/10 · **Status:** 🟢 `fixed`

Found while expanding the trading universe to 20 assets and extending
`ETHUSD`/`LTCUSD` coverage forward to `2021-03-31` via
`data_pipeline/yfinance_backfill.py --apply`. `train.py::ensure_derived_crypto_daily_series()`
runs unconditionally at the start of every `train.py` invocation for any
asset with `derived_from`/`aggregation: "daily_from_minute_trade"` set
(`ETHUSD`, `LTCUSD`) and rebuilds their daily Lean zip from the raw minute
trade files with a bare `ZipFile(output_zip, "w")` — a full overwrite, not
a merge. Since both tickers' real Coinbase minute data is only a handful
of scattered days, this wiped the yfinance-backfilled rows (1000+ days)
back down to 3-4 real rows the moment `train.py` ran again after the
backfill — the backfill script's own zip write survived on disk right up
until the very next training run silently undid it. Confirmed directly:
`ethusd_trade.zip` had 1241 rows after `--apply`, then 4 rows again
immediately after `python train.py --dataset-only`.

**Fix:** `ensure_derived_crypto_daily_series()` now reads the existing
output zip first (if present) and merges by date — freshly computed
minute-derived rows win on any date real minute data actually covers
(they're genuine trade data), but every other date already in the zip
(i.e. anything `yfinance_backfill.py` wrote) survives the rebuild instead
of being discarded. New regression test:
`tests/test_train_pipeline.py::test_ensure_derived_crypto_daily_series_merges_with_existing_backfill`.

---

### 16. `main.py::initialize()` exceeded Lean's hard 90-second isolator timeout at 20 assets
**Severity:** 8/10 · **Status:** 🟢 `fixed`

Found by actually running `lean backtest .` against the new 20-asset
universe (not caught by any unit test — `main.py` has none; this class of
regression is only observable via a real Lean run). Every `lean backtest .`
attempt failed identically:

```
ERROR:: Security.ExecuteWithTimeLimit(): Execution Security Error:
Operation timed out - 1.5 minutes max. Check for recursive loops.
```

Root cause: `QuantConnect.AlgorithmFactory.Loader.TryCreateAlgorithmInstanceWithIsolator`
wraps Python module import + algorithm instantiation + the `initialize()`
call in a hardcoded 90-second wall-clock limit — not configurable via
`lean.json` or any Lean CLI flag in the local/community engine. `initialize()`
loaded every model/expert/topology artifact (`ml/model_weights.json`, 4
expert exports, `feature_schema.json`, `scaler_stats.json`,
`dataset_manifest.json`, the learned topology model) and derived ~40
risk/regime/topology/liquidity/broker config values, in addition to the
`add_equity`/`add_crypto` subscription loop — the one piece of setup that
must run inside `initialize()`, since Lean only calls `on_data()` once
subscriptions exist. Going 10→20 assets pushed the combined cost over the
90-second cap. Confirmed via direct instrumentation (a side-channel log
file written straight to disk, since `self.Debug()` calls made inside an
`initialize()` call that the Isolator later aborts never reach any log —
they're silently lost, not just delayed) that the per-asset subscription
loop itself is fast (20 assets subscribed in 1.8 seconds total) — the
model/config loading was the reducible cost, not the loop.

**Fix:** split `initialize()` into a minimal Lean-critical path (path
constants, `config.json` load, dates/cash, the `add_equity`/`add_crypto`
loop, warm-up) and a new `_ensure_ready()` method carrying everything else
(all artifact loading and derived config) — deferred to run once, on the
first `on_data()` call, which has no isolator time limit. Verified via the
same disk-log instrumentation: `initialize()` alone now completes in
1.85 seconds, and the full isolator-timed window (module import +
instantiation + `initialize()`) totals ~51 seconds against real 20-asset
data, safely under the 90-second cap. No scheduled events or other Lean
callbacks fire between `initialize()` and the first `on_data()` in this
algorithm, so nothing else needed to change; `on_end_of_algorithm()` also
calls `_ensure_ready()` defensively in case a backtest somehow produces
zero bars. `pytest tests/` (525 tests, everything except the
Docker-dependent Lean integration test) stayed green throughout.

---

### 17. Matplotlib font cache rebuilt from scratch on every single `lean backtest .` run
**Severity:** 6/10 · **Status:** 🟢 `fixed`

Found while re-verifying Problems.md #16's fix: even with `initialize()`
down to 1.85 seconds, a real `lean backtest .` run still occasionally timed
out against the same 90-second isolator cap. The log showed "Matplotlib is
building the font cache; this may take a moment" printed during Python
module import, every single run — 20-40+ seconds of the timed window, on
top of everything else. No file in this repo imports `matplotlib` (grepped
the entire codebase, confirmed only `generate_backtest_report.py` does, and
that never runs inside Lean); the import comes from Lean's own
`AlgorithmImports` bridge (its charting/plotting support). Lean CLI runs
each backtest in a fresh, ephemeral Docker container, so matplotlib's
default cache location never survives between runs — every run rebuilt it
from nothing.

**Fix:** `main.py` now sets `MPLCONFIGDIR` (before any other import, at the
very top of the file) to `.matplotlib_cache/` inside the mounted project
directory. That directory lives on the host filesystem, not the ephemeral
container, so it survives across runs — only the very first run ever pays
the font-cache-build cost again. Confirmed via two consecutive real Lean
runs: the first (cold cache) still showed the "building the font cache"
message and took ~82 seconds just to import; the second (warm cache) showed
no such message and imported in ~58 seconds, with zero isolator timeout.
`.matplotlib_cache/` added to `.gitignore` (generated cache, not committed).

---

### 18. Two structural "never recovers" traps suppressed real backtest trade count to 12 over 3 years
**Severity:** 5/10 · **Status:** 🟢 `addressed` (opt-in statistical bypass, default behavior unchanged)

Found investigating why a real 3-year, 20-asset backtest produced only 12
filled trades: a 5-symbol mass liquidation on 2020-03-23 (portfolio total
drawdown crossed `phase6.risk.max_total_drawdown_pct`, 12%) froze the
algorithm for the remaining 374 days of the window — no trades at all. The
sticky lock (`main.py::_refresh_risk_state()`'s daily auto-clear
deliberately excludes `"total_drawdown_limit_breached"`, by design, for
live capital preservation) is only half the story: `peak_equity` is a
running max that never decreases, so once liquidated to flat cash, the
drawdown-from-peak percentage can never recover on its own — the lock
cannot ever clear again regardless of the sticky-exclusion logic, purely
because the underlying number stays permanently breached. A second,
independent, earlier-firing (8% vs. 12%) version of the identical trap was
found in `regime/market_regime.py::classify_risk_regime()`'s `risk_off`
drawdown branch (`phase_v2.regime_detection.risk_off_drawdown_threshold`),
fed from the same portfolio-wide drawdown number — this alone would
suppress the whole universe's signals even if the 12% lock were fixed in
isolation.

**Fix:** new opt-in flag `phase_v2.backtest.bypass_safety_gates` (default
`false`) and pure helper
`risk_controls.py::is_backtest_safety_bypass_active(runtime_mode, bypass_flag)`
— `True` only when `runtime_mode == "backtest"` and the flag is explicitly
`true`; any non-backtest mode always returns `False` regardless of the
flag. When active, bypasses only these two specific mechanisms (the sticky
lock's exclusion, and the regime override's drawdown branch specifically —
passing `float("inf")` in place of the configured threshold); every other
gate (liquidity, topology, cooldown, exposure caps, the bearish-trend+
high-vol and composite-score regime branches) stays fully active. Live/paper
mode, and a backtest with the flag left at its default `false`, are
completely unaffected.

**Deliberately not wired into `aq trade-lock`:** `--on`/`--off`/`--auto`
already has a separately-documented meaning (`--auto` = "return to fully
automatic \[original, safety-preserving\] behavior") that this must not
collide with or repurpose — a dedicated config key keeps both mechanisms
independently meaningful in every runtime mode.

**Explicitly not a claim about live-representative behavior:** in live/paper
mode both gates are real, designed behavior that would have actually frozen
trading on 2020-03-23. This flag is scoped to statistical/model-quality
backtesting only (enough trade volume for meaningful metrics and to
exercise `performance_triggers.trade_count_interval=100`/
`retraining.validation_gate.min_trade_count=30`, neither of which ever
fires at ~12 trades) — never to be read as "what would happen if deployed."

---

### 19. Neural-network webui tab's gating exclusion went stale the moment gating became learnable
**Severity:** 2/10 · **Status:** 🟢 `fixed`

`monitoring/neural_network_state.py`'s `EXCLUDED_NON_NETWORKS` listed
`moe/gating.py`'s gating network with the reason "deterministic rule-based
combiner ... no learned weight matrix," and `/neural-network`'s 3D scene
(`webui/src/components/neuralnet/NeuralNetworkScene3D.tsx`) hardcoded its
render order to exactly 5 network names, silently dropping anything else
even if the backend did return it. Both became inaccurate the moment
`moe/gating.py` gained an optional learned model (this session, same
Phase E work as entry above) — the gating network now genuinely can have
a learned weight matrix (`ml/gating_model.json`), but the webui had no way
to show it even after one existed, and the "no learned weight matrix"
claim was simply wrong.

**Fix:** removed `gating_network` from `EXCLUDED_NON_NETWORKS` (only
`learned_topology`'s KMeans centroids remain excluded — genuinely not a
layered network); `build_neural_network_state()` now reads
`ml/gating_model.json` through the exact same generic
`_build_network_summary()` path already used for the baseline and the 4
experts, degrading to `status="not_trained"` when no gating model exists
yet (same graceful-optional contract as everything else in this module).
Added `'gating'` to `NeuralNetworkScene3D.tsx`'s `NETWORK_ORDER` array so
it actually renders in the 3D scene once returned by the backend.

**Why this matters beyond gating specifically:** `NETWORK_ORDER` is a
silent filter — any future network the backend starts reporting will not
appear in the 3D scene (though it will still appear in the stats panel's
list, which iterates the array directly) unless someone remembers to add
its name here too. Left as-is rather than making it dynamic, since the
3D layout intentionally controls left-to-right ordering for readability;
noted here so the next network added to `build_neural_network_state()`
doesn't quietly repeat this gap.

---

### 20. `Dockerfile.retraining_worker` never copied `risk/`, so `retraining.worker` could not have started
**Severity:** 7/10 · **Status:** 🟢 `fixed`

Found while auditing `Dockerfile.retraining_worker`'s `COPY` list against
this session's changes (the standing "does any Docker image need
rebuilding" checklist step). `retraining/orchestrator.py` has imported
`from risk.manual_override import write_manual_trade_lock_override` since
the Manual Trade-Lock Override Contract shipped (`promote()` calls it to
auto-clear the trade lock on a successful promotion) — but
`Dockerfile.retraining_worker`'s `COPY` list never included `risk/`, only
`execution/`, `experience/`, `performance/`, `regime/`, `experts/`,
`topology/`, `moe/`, `inference/` and `retraining/`. Since the import is a
top-level `from risk.manual_override import ...` (evaluated at import time,
not lazily), and the image's `CMD` is `python -m retraining.worker` (which
imports `retraining.orchestrator` directly), the container should have
failed immediately with `ModuleNotFoundError: No module named 'risk'` on
every single startup — not a code-path-dependent bug, an always-fires one.
Not independently confirmed against a live container in this session (no
Docker rebuild was run); flagged from static inspection of the `COPY` list
against the actual import graph, same rigor as Problems.md #2's original
`execution/` finding.

**Fix:** added `COPY risk/ ./risk/` to `Dockerfile.retraining_worker`
(confirmed safe and lightweight — `risk/__init__.py` only imports
`.manual_override` and `.position_sizing`, both pure-Python/stdlib, no
torch/pandas/sklearn). Same commit also added `COPY train_multitask.py .`
for this session's new `train_multitask()` retraining stage (see
Changelog's "Multi-task prediction" entry) — `requirements-retraining-worker.txt`
already had every dependency `train_multitask.py` needs (torch/pandas/numpy),
so no requirements changes were needed for that half of the fix.
**The `retraining-worker` image needs a rebuild** (`docker compose build
retraining-worker`) before this fix or the new multitask stage take effect
— not run in this session, since the user runs Docker builds/backtests
themselves.

---

### 21. Per-bar model forward-pass count doubled (5 → 11) — now measured, not currently a problem
**Severity:** 2/10 · **Status:** 🟢 `measured, not currently a problem`

The multitask/sequence pass added 6 more optional model forward passes per
symbol per bar on top of the original 5 (baseline + 4 experts):
`baseline_multitask`, 4 `expert_multitask` heads, and the Phase 2
`sequence` encoder — all still `inference/exported_model.py`'s plain-numpy
interpreters (`run_exported_multitask_model()`/
`run_exported_sequence_multitask_model()`). Correcting one detail from
when this entry was first written: there IS batching within each 4-expert
group by default in `main.py` (`_run_expert_models()`/
`_run_expert_multitask_models()` both call the batched
`run_exported_*_models_batched()` path unconditionally, falling back to
per-expert only on a shape mismatch — see entries #31/#32) — so `main.py`
actually makes 5 top-level calls per symbol per bar (baseline, sequence,
one batched call for the 4 experts, multitask, one batched call for the 4
expert-multitask heads), which collectively perform 11 individual model
forward passes. There is still no shared computation between a flat model
and its multitask sibling (`baseline`/`baseline_multitask` each still run
an independent forward pass over the same input).

**Now measured** using the harness this exact situation calls for
(`scripts/profile_inference.py`, wrapped by `aq profile`, already built for
entries #31/#32/#36/#37 — its `run_workload()` already simulates this
precise 5-call/11-forward-pass bundle with real exported weights from
`ml/`, no Lean/Docker required): two 10,000-iteration runs, matching
`main.py`'s real production path (`--batched`, since that's the always-on
default there) plus the unbatched comparison point:

| | p50 | p95 | p99 | max | mean |
|---|---|---|---|---|---|
| `aq profile --batched --iterations 10000` (matches `main.py`) | 7.03ms | 35.55ms | 106.01ms | 587.40ms | 12.00ms |
| `aq profile --iterations 10000` (unbatched comparison) | 7.19ms | 19.78ms | 41.02ms | 212.67ms | 8.72ms |

Both single runs, not the paired-run methodology entries #32/#37 used —
the batched run's noticeably worse tail (p99/max) versus the unbatched
run is consistent with those entries' own documented finding that this
harness's wall-clock tail is materially affected by concurrent machine
load, not just code path (this session ran other background work
concurrently); p50, the least load-sensitive statistic, is consistent
across both runs at ~7ms. cProfile's own breakdown shows
`run_exported_sequence_multitask_model()` as the single largest
contributor (~48-58% of total profiled time across both runs) — the
sequence encoder, still a real, previously-flagged optimization
opportunity (entries #31/#32 already improved its causal-convolution loop
once; further gains would need a second pass) — plus a large
`numpy.asarray` call count (890,000 calls in the batched run) suggesting
repeated small-array construction inside its per-timestep loop.

**Verdict: not currently a problem.** Judged against the only real,
enforced constraint anywhere in this codebase — Lean's 90-second
`initialize()` isolator timeout (entry #16), which is unrelated to
per-bar `on_data()` cost — a ~12ms mean per symbol per bar is negligible;
there is still no established per-bar time budget this violates, and nothing
in this pass changed that. Left as a documented future optimization target
(the sequence encoder specifically), not a fix — matching this entry's own
original framing: revisit with the existing `lean backtest .` +
side-channel-log method (entries #16/#17) only if `initialize()` timing
regresses or backtest wall-clock time becomes a real iteration-speed
obstacle.

---

### 22. `tests/test_retraining_worker.py` silently ran real training (subprocess-level hang, up to ~30 minutes per test)
**Severity:** 6/10 · **Status:** 🟢 `fixed`

`retraining/worker.py::run_once()` calls `train_multitask(...)` and
`train_sequence(...)` (added when the multitask/sequence trainers were
wired into the retraining pipeline) right after `train_topology(...)`/
`train_gating(...)`. 7 of `tests/test_retraining_worker.py`'s 10 tests
patch `plan`/`train`/`train_topology`/`train_gating`/`validate`/
`backtest`/`commit`/`promote`/`status` but were never updated to also
patch `train_multitask`/`train_sequence` when those two stages were added
— so in any environment where the real dataset/scaler artifacts exist
(true here, and true for any real dev checkout), `worker.run_once()` fell
through to the genuine `retraining.orchestrator.train_multitask()`/
`train_sequence()` functions, which shell out to real
`train_multitask.py`/`train_sequence.py` subprocesses with
`timeout_seconds` of 900/1800 (`config.json`'s
`phase_v2.retraining.multitask_training`/`sequence_training`). A bare
`pytest tests/` run would silently sit for up to ~30 minutes on a single
test with no output, easily misread as a hang/crash rather than a missing
mock — found while running the full suite for the first time after this
session's other changes (unrelated to those changes; this gap predates
them).

**Fixed**: added `patch("retraining.worker.train_multitask")` and
`patch("retraining.worker.train_sequence")` to all 7 affected tests
(`test_run_once_auto_promote_false_stops_after_commit`,
`_true_calls_promote`, `_forced_off_when_runtime_mode_is_live`,
`_proceeds_when_runtime_mode_is_not_live`,
`_ignores_live_mode_when_guard_disabled`,
`test_run_once_stops_when_validation_fails`,
`test_run_once_calls_train_topology_then_train_gating_between_train_and_validate`),
matching the file's own existing `train_topology`/`train_gating` mock
pattern. Verified: the previously-hanging test now completes in ~1.2s;
the full file (10 tests) now runs in ~1.2s total, down from an unbounded
hang.

---

### 23. BTCUSD volume-feed unit discontinuity blew up the sequence model's RMSE 31x
**Severity:** 7/10 · **Status:** 🟢 `fixed`

A root-cause investigation into why the Phase 2 sequence-encoder's
backtest magnitude RMSE (2.09) was ~31x its own MAE (0.068) — every other
model's ratio sits at ~1.5-3x — found `ml/datasets/full_dataset.csv`'s
raw BTCUSD `volume` column jumping from 1.018e4 to 5.302e9 (~520,000x) on
2018-08-14, a data-feed unit discontinuity (the underlying Coinbase feed
almost certainly switches from raw-BTC-denominated to aggregated
USD-denominated volume right at that date, coincidentally also this
asset's `yfinance` backfill start date — see entry below). The `== 0`-only
guard in `train.py::engineer_features()`'s `volume_change_1d` computation
let the resulting `520874.93` (5.2 million percent) pass straight through
`fit_and_apply_scaler()`'s plain `StandardScaler` (no clipping anywhere),
producing a `28,038`-standard-deviation scaled feature value.
`build_sequence_tensor_dataset()`'s sliding window then replicated that
single poisoned row into the input window of the next 30 rows for that
ticker, so the causal-TCN's unbounded `head_magnitude` output predicted a
"-15,247% return" on those rows — reproduced bit-for-bit; 7 consecutive
BTCUSD rows accounted for 66%+ of the entire backtest sum-of-squared-error.
The flat (non-sequence) multitask model only ever saw the poisoned row
once, diluting its effect across ~16,000 backtest rows (ratio ~2.7x,
"normal"), which is why this bug was invisible in every model except the
sequence encoder specifically.

**Fixed** with three layered defenses (all in `train.py`, mirrored in
`main.py::_build_model_input()` for train/runtime parity): (1)
`volume_change_1d` clamped to `[-1.0, 20.0]` before scaling; (2)
`fit_and_apply_scaler()` winsorizes the train-split columns (quantiles
configurable, default `[0.001, 0.999]`) before fitting the scaler, so a
single extreme value can't distort the fitted mean/std; (3) scaled values
are clipped to `±scaled_feature_clip_sigma` (default 10.0, persisted into
`ml/scaler_stats.json` so `main.py` applies the identical bound at
runtime) — this is the layer that actually kills the poisoned row's
downstream effect, since layer (2) alone can't help a value that lives in
the *backtest* split (which the scaler never fits on). Also added a
regression-quality gate (`assess_regression_quality()`, entry-adjacent)
so a future RMSE/MAE blowup like this is caught automatically instead of
requiring a manual investigation. Verified on the real dataset after the
fix: max absolute scaled value across every column is exactly `10.0`
(the clip firing correctly), and the retrained sequence model's backtest
RMSE/MAE ratio is `1.59x`.

---

### 24. `train.py` never applied Lean's own split/dividend factor files — offline dataset had fake ±74%/+745% "returns" Lean's live/backtest engine never sees
**Severity:** 8/10 · **Status:** 🟢 `fixed`

`train.py::load_lean_bars()` reads each asset's raw daily Lean zip
directly (a from-scratch CSV/zip reader, bypassing Lean's own data engine
entirely), so it never applied the split/dividend adjustment Lean's
`DataNormalizationMode.Adjusted` (the implicit default for
`main.py`'s runtime `self.add_equity(ticker, self.resolution)`
subscription, since no explicit mode is passed) already applies live. The
raw zips store genuinely unadjusted prices — confirmed directly:
AAPL's real 2020-08-31 4-for-1 split shows as close `499.23 -> 129.04`
in the raw data (a real, undivided price on each day, not a bug in the
zip itself), which `engineer_features()`'s `target_return_1d` then turned
into a fake `-74.15%` "next-day return" purely because the offline
pipeline never rescaled pre-split history. Same root cause produced
USO's `+745%` "return" around its real 2020-04-28 1-for-8 reverse split.
This corrupted `target_return_1d`/`target_direction` labels — and every
base return/momentum/volatility *feature* spanning the split boundary —
for every trainer reading `ml/datasets/full_dataset.csv`, for every
equity that ever had a split or meaningful dividend (confirmed: every
configured equity except thin-history `AAA` has a non-trivial Lean
factor file). Lean's own backtest engine was **not** affected by this bug
(it already reads the correct adjusted prices independently via its own
factor-file-aware data reader) — this was purely a train/runtime feature-
parity gap between `train.py`'s offline reconstruction and what
`main.py`'s real backtest already saw correctly.

**Fixed**: new `train.py::apply_split_adjustments()` reads each equity's
Lean factor file (`data/equity/usa/factor_files/<ticker>.csv`, the exact
file Lean's engine itself already reads) and, for each raw bar dated `D`,
finds the factor-file row with the smallest date `>= D`
(`pd.merge_asof(direction="forward")`, Lean's own lookup convention),
multiplying `open/high/low/close` by that row's `price_factor *
split_factor` and dividing `volume` by `split_factor` alone. Called from
`load_lean_bars()` for every equity asset (crypto has no factor-file
concept, skipped). No `main.py` mirror needed — Lean's engine already did
this correctly at runtime; only `train.py`'s independent reader was
missing it. Verified on the real dataset: AAPL's close now goes smoothly
`124.41 -> 128.63` across the split boundary (a normal ~3.4% day, not
-74%), USO goes `17.04 -> 18.00` (~5.6%, not +745%), and
`full_dataset.csv`'s backtest-split `target_return_1d` range is now
`[-0.50, 1.37]` (all real, mostly-crypto moves within the configured
per-security-type bounds) instead of containing `7.45`/`-0.74`.

Also fixed for consistency/future-proofing (not the actual source of the
AAPL/USO corruption, which predates any code touching splits at all):
`data_pipeline/yfinance_backfill.py`'s `fetch_yahoo_ohlcv()` used
`yf.download(..., auto_adjust=False)` — harmless today since only crypto
assets (no splits) use this backfill path, but would reintroduce the same
class of bug if this module or its `aq fetch` sibling is ever pointed at
an equity with an upcoming split. Flipped to `auto_adjust=True`.

Defense-in-depth also added directly in `engineer_features()`: a
per-security-type label-outlier guard (`max_abs_daily_return`, default
`{"equity": 0.5, "crypto": 1.5}`, extended to `max_abs_return_5d`/`_20d`
for the Phase 3 multi-horizon targets) NaNs out any single-day return
outside the configured bound regardless of cause, dropped by the existing
dropna — a safety net for any *future* unadjusted-price scenario this
factor-file fix doesn't anticipate (e.g. a brand-new ticker added via `aq
fetch` before its factor file exists locally).

---

### 25. No quality gate ever existed for regression heads (magnitude/volatility/rank) — only direction MCC was gated
**Severity:** 5/10 · **Status:** 🟢 `fixed`

`train.py::assess_expert_quality()` gates direction models on MCC/balanced-
accuracy/train-backtest-gap, but nothing gated the magnitude/volatility
regression heads (`train_multitask.py`/`train_sequence.py`) at all — which
is exactly how entry #23's 31x RMSE/MAE blowup shipped into the active
`ml/` artifacts silently for an entire session before being noticed.

**Fixed**: new `train.py::assess_regression_quality()`, mirroring
`assess_expert_quality()`'s `failures`/`near_misses`/`quality_status`
shape, gating on `backtest_rmse/backtest_mae` ratio (default max `4.0`)
and `backtest_rmse/train_rmse` ratio (default max `3.0`). Wired into both
`train_multitask.py` and `train_sequence.py`, writing
`magnitude_quality`/`volatility_quality` blocks into each trainer's
`*_training_metrics.json` and now surfaced on the `/neural-network` webui
page (`monitoring/neural_network_state.py`'s `regression_quality` field).

---

### 26. `main.py`'s sequence-model runtime buffer size never read the trained model's own `window_size`
**Severity:** 4/10 · **Status:** 🟢 `fixed`

`main.py` set `self.sequence_window_size` from `config.json`'s
`phase_v2.sequence_model.window_size` alone, never from the already-loaded
`sequence_feature_schema.json`'s own `window_size` field (written by
`train_sequence.py`, read into `self.sequence_feature_schema` but never
consulted for this). A retrained candidate sequence model with a
different `window_size` than `config.json` currently specifies would
silently disable the sequence signal entirely: `main.py` would build its
rolling `symbol_feature_history` buffer at the *old/configured* length,
then feed it into `run_exported_sequence_multitask_model()`'s Conv1d
stack sized for the *new* window — a shape mismatch caught by
`_run_sequence_model()`'s blanket `except Exception`, which silently
returns "no sequence prediction this bar" rather than failing loudly or
auto-adopting the new window size. No version/compat field exists in
`sequence_model.json` to detect this proactively.

**Fixed**: new `inference/exported_model.py::resolve_sequence_window_size()`
(a pure function, extracted there specifically so it's unit-testable
without a Lean `QCAlgorithm` environment, which `main.py` itself can't be
instantiated in for testing) — the trained model's own
`sequence_feature_schema.json` `window_size` now wins over
`config.json`'s value whenever a schema is loaded at all, falling back to
config only when no sequence model is loaded (missing/malformed file).

---

### 27. Phase 2's new `split_into_non_overlapping_eras()`/`purged_embargoed_folds()` crashed on real training runs — assumed datetime input, but the real dataset's `date` column is plain strings
**Severity:** 6/10 · **Status:** 🟢 `fixed`

Found during the combined Phase 1/2/5 retrain (5/10 -> 9/10 roadmap):
`train_multitask.py --version-id ...` failed with `TypeError: can only
concatenate str (not "Timedelta") to str` inside
`split_into_non_overlapping_eras()`. Root cause: both new Phase 2
functions did `dates_array = np.asarray(dates)` and then performed
Timestamp arithmetic (`era_start + era_length`) directly on the result —
correct when `dates` is already `datetime64`/`Timestamp`-typed (as every
unit test for these functions happened to construct it), but every REAL
caller passes `frame["date"]`, and `build_feature_dataset()` stringifies
the date column (`dataset["date"].dt.strftime("%Y-%m-%d")`) before any
trainer ever reads it — so `np.asarray()` on that column produces a plain
numpy `object` array of Python `str`, not `datetime64`. All of this
file's unit tests for the new functions passed because they were built
with `pd.date_range(...).to_numpy()`/`dtype="datetime64[D]"` fixtures,
which don't reproduce the real, string-typed shape at all — a gap between
"unit-tested" and "exercised against the real pipeline."

**Fixed**: both `split_into_non_overlapping_eras()` and
`purged_embargoed_folds()` (plus the caller,
`assess_ranking_quality_from_predictions()`, which had the identical bug
in its own separate `dates_array = np.asarray(dates)` line) now coerce via
`pd.to_datetime(np.asarray(dates))` instead of a bare `np.asarray(dates)`
— robust to string, `Timestamp`, or `datetime64` input alike, matching
every other date-accepting function in `train.py` (e.g. `assign_split()`'s
own `pd.Timestamp(date_value)` coercion). New regression tests added using
plain string dates and a real `np.asarray(pd.Series([...]))` object array
(the exact real shape) — not just `datetime64`-typed synthetic fixtures —
in `tests/test_train_ranking_validation.py`, so this class of "passes
every unit test, fails on first real run" gap can't silently recur.

---

### 28. Portfolio book's `"short"` signal silently zeroed to no position in `main.py::_build_dynamic_sizing_payload()`
**Severity:** 4/10 · **Status:** 🟢 `fixed`

Found while rewriting `_build_dynamic_sizing_payload()` to route through the
new `risk/asset_class_router.py` for multi-asset-class support.
`portfolio/book_construction.py`'s long/short book (Phase 3 of the 5/10 ->
9/10 roadmap) sets `signal_name = "short"` for its short-role symbols
(`main.py::on_data()`, Pass 2), but `_build_dynamic_sizing_payload()`'s
guard clause read `if signal_name not in {"buy", "sell"}: base_target_weight
= 0.0` — never updated when `"short"` was introduced as a third valid
signal name alongside buy/sell/hold. Every book-selected short position
would have been sized to exactly zero, silently defeating the book's
entire short-selling role. Never observed in practice because
`phase_v2.portfolio_book.enabled` defaults to `false`.

**Fixed**: the guard now reads `{"buy", "sell", "short"}`. No new test
added specifically for this line (the existing portfolio-book test suite
in `tests/test_portfolio_book_construction.py` covers the book's own
role-selection logic; this fix is at the sizing-payload call site one
layer up, exercised implicitly by any future end-to-end backtest run with
the book enabled).

---

### 29. Multi-asset-class support (bonds/futures/options + IB) — explicit non-goals
**Severity:** n/a (scope note, not a bug) · **Status:** 🟢 `fixed` (core multi-asset-class trading is fully implemented; the remaining IB-dependent gaps below are permanent non-goals, not open work — tracked in the root README's Known Limitations section, not as pending items here)

Full session summaries are in `development/Changelog.md`. A first pass added
bonds/futures/options architecturally; a second pass closed the gaps that
blocked futures/options from actually trading. **Resolved in the second
pass** (previously listed here as deferred):

- ~~Options order placement against a specific resolved contract~~ — now
  implemented. `main.py::_build_options_chains_payload()` resolves
  `slice.option_chains` into a real `available_chain` every bar (preferring
  Lean/IB's own greeks, falling back to `features/options_greeks.py`'s
  Black-Scholes solver), and `_apply_signal()`'s `"option"` branch places a
  real `MarketOrder()` against the selected contract's own `Symbol` — plus
  contract-symbol tracking so the position can be found again and correctly
  closed / counted toward exposure caps.
- ~~Real futures term-structure / options put-call-ratio / IV-skew data~~ —
  now computed for real, both live (`main.py::_build_derivatives_macro_payload()`)
  and offline (`train.py::build_derivatives_macro_features_by_date()`),
  whenever the configured universe has the matching future/option assets
  (`family_ticker`-grouped futures, `strike`/`expiry`/`right`-tagged
  options — see `aq fetch futures --contract-month`/`aq fetch options
  --family-ticker`). Still resolves to the neutral default (0.0) when no
  such assets are configured — the honest "no data" case, not a bug.

**Resolved this pass:**

- ~~Per-asset-class top-N/bottom-N book-slot caps~~ — now implemented.
  `portfolio/book_construction.py::build_rank_based_book()` gained an
  optional `per_asset_class_slots: dict[str, tuple[int, int]] | None`
  parameter (default `None` — pooled combined-universe ranking, byte-
  identical to this function's original and only behavior; see the shared
  `_select_book_group()` helper the pooled and per-class paths now both
  call). When configured, each asset class is ranked and slotted
  independently instead of one class potentially dominating a side of the
  book (e.g. equities and crypto each get their own long/short slot
  budget). `min_rank_confidence_spread` applies independently per class.
  Wired into `main.py` via `phase_v2.portfolio_book.per_asset_class_slots`
  (absent by default, so `portfolio_book_per_asset_class_slots` stays
  `None` and behavior is unchanged) and a new `asset_class` field on each
  `book_candidates` entry (same `asset.get("asset_class") or
  asset.get("security_type")` fallback every other asset-class-aware call
  site in `main.py` already uses). 7 new tests in
  `tests/test_portfolio_book_construction.py` (per-class ranking, class
  exclusion when not listed, one thin class not blocking others, per-class
  confidence-spread gating, `top_n`/`bottom_n` correctly ignored once
  `per_asset_class_slots` is set, and an explicit `None`-matches-omitted
  backward-compatibility check).

Re-reviewed the remaining items this pass — still genuinely out of scope,
none newly addressable without external dependencies this repo doesn't
control:

- **Automatic multi-leg options spread selection via ML** (verticals,
  straddles, iron condors). `portfolio/options_strategy.py` is single-leg
  only (long calls or long puts, greeks-sized via a target delta scaled by
  the existing direction+confidence prediction) — a genuinely new spread-
  selection model architecture is future work, not a data/plumbing gap.
- **IBC-based headless/automated TWS/Gateway login.** IB's API requires an
  already-logged-in TWS/Gateway session; `data_pipeline/ib_backfill.py`
  connects to that session but does not manage its login lifecycle. The
  live connection itself has also never been tested against a real
  Gateway — everything is verified via unit tests and Lean's own type
  stubs only. Blocked on IB's own product design, not something this
  codebase can route around.
- **Live IB margin replacing `data/reference/futures_contract_specs.json`'s**
  static reference numbers. The static file is the sizing source of truth
  even when IB is connected; live margin queries are a documented future
  enhancement. Blocked on wiring a live IB session end-to-end (untested,
  see above) before this would even be safe to build against.
- **Real historical derivatives training data acquisition is manual.** IB's
  historical API is per-contract and rate-limited, so building a rich
  training-window dataset means repeated `aq fetch futures --contract-month
  <YYYYMM> --apply` / `aq fetch options --strike ... --expiry ... --right
  ... --apply` calls, one contract at a time — not a single bulk-fetch
  button. Inherent to IB's API shape, not a shortcut taken here.

---

### 30. `Dockerfile.retraining_worker` missing `data_pipeline/` (and pre-existing: `liquidity/`) copy
**Severity:** 7/10 · **Status:** 🟢 `fixed`

Same class of bug as #1/#2 (found by tracing the import chain before any
rebuild was attempted, not by a failed deploy). This session's `train.py`
gained a new top-level `from data_pipeline.fred_backfill import
bond_reference_series, load_cached_fred_series` (for real bond yield-
curve features) — `Dockerfile.retraining_worker` copies `features/` and
`risk/` (both of which `train.py` needs) but never copied `data_pipeline/`
at all, so the retraining-worker container would have crashed with
`ModuleNotFoundError: No module named 'data_pipeline'` the moment
`retraining.worker` tried to invoke `train.py`.

While tracing this, found a second, **pre-existing** gap unrelated to this
session's changes: `train.py` already imported `from liquidity import
estimate_high_low_spread` / `from liquidity.market_liquidity import
TYPICAL_SPREAD_BY_TYPE` (liquidity-aware feature engineering, an earlier
phase) and `Dockerfile.retraining_worker` never copied `liquidity/`
either — same latent crash-on-first-real-retrain risk, just never
triggered because nobody had rebuilt this image since that feature
shipped. Fixed alongside the `data_pipeline/` gap since it's the exact
same root cause in the exact same file, rather than left for a second,
separate fix.

**Fixed:** added `COPY data_pipeline/ ./data_pipeline/` and `COPY
liquidity/ ./liquidity/` to `Dockerfile.retraining_worker`. Not yet
rebuilt/deployed this session — see `development/Changelog.md`'s multi-
asset-class entry for the rebuild command to run before this worker is
next restarted.

---

### 31. Infrastructure/latency pass — `aq test` silently ran a real Lean backtest, per-bar inference hot path never profiled, CI Docker builds never cached
**Severity:** 8/10 (the `aq test` one) / 6/10 (inference latency) / 4/10 (CI cache) · **Status:** 🟢 `fixed`

Four separate findings from a research pass (3 parallel Explore agents)
before any code changed, per the user's explicit "profile before
optimizing blindly" instruction:

**`aq test` was silently running a real `lean backtest .`.**
`tests/test_lean_backtest_ml_coverage.py`'s `skipif` only checked whether
the Lean CLI binary was *installed* (`.venv/Scripts/lean.exe` — present
in this repo), never whether the caller actually wanted to pay the cost of
a real backtest (documented in that file's own comment as "over an hour
wall-clock"). Every `aq test` run silently included it. **Fixed:** added a
`lean_backtest` pytest marker (registered in `pyproject.toml`), applied to
that file, excluded by default (`-m "not lean_backtest"`); `aq test
--lean`/`--full` opts back in. Confirmed via `pytest --collect-only`:
1132/1143 collected, 11 correctly deselected. A full non-lean run now
takes ~73s-4min (machine-load-dependent) instead of over an hour.
`aq test` also gained per-subsystem flags (`--cli`, `--risk`, `--portfolio`,
`--features`, `--data-pipeline`, `--webui`, `--ml`, `--retraining`,
`--notifications`, `--storage`, `--live`, combinable) and an opt-in
`--parallel` (`pytest-xdist -n auto`, off by default — multiple workers
each importing PyTorch is a real OOM risk on this session's ~4GB-RAM dev
machine, confirmed by an earlier incident this same session). The README
badge/test-count only updates on a full, unfiltered default run — a
subsystem-filtered partial count is never written into it.

**Per-bar inference hot path had never been profiled.** No profiling
harness existed anywhere in this repo. Built
`scripts/profile_inference.py` (cProfile against real exported weights
already on disk under `ml/` — never synthetic ones, so results mean
something — since a real Lean backtest is off the table for repeated
profiling runs on this machine). First run (10,000 synthetic symbol-bar
iterations, matching `main.py::on_data()`'s real call pattern) measured
**448.4s total**. Two real costs found, both fixed:

- `inference/exported_model.py::_conv1d_causal()` (the sequence model's
  causal TCN) had a `for timestep in range(window):` Python loop calling
  its own `einsum` every iteration — this was the **single largest cost
  in the entire hot path**, bigger than the 4-expert loop below. Rewritten
  to gather every timestep's dilated taps in one fancy-index op and run
  ONE batched `einsum` instead. Self-time (`tottime`) for this function
  dropped from 48.4s to 4.7s across an identical 20,000 calls (~90%
  reduction) — verified bit-identical against the original loop-based
  logic across 200 random-parameter fuzz trials (varying window/channels/
  kernel size/dilation), not just the pre-existing fixed test cases.
- `main.py::_run_expert_models()`/`_run_expert_multitask_models()` called
  `run_exported_model()`/`run_exported_multitask_model()` once per expert
  — 4 separate small NumPy dispatch calls on models confirmed (checked
  real `ml/expert_models/*/model_weights.json` and
  `multitask_model.json` — not assumed) to share byte-identical
  architecture and weight shapes. New
  `run_exported_models_batched()`/`run_exported_multitask_models_batched()`
  stack all present experts into one leading batch axis and run one
  `_linear_batched()`/`_layernorm_batched()` call per layer instead of 4 —
  falling back to the original per-model loop (same per-expert graceful-
  degradation contract: one bad expert never takes the others down)
  whenever fewer than 2 experts are present, their architectures don't
  match, or the batched computation itself fails for any reason.

**Net measured result: 448.4s → 290.6s, -35.2%**, same 10,000-iteration
workload, both fixes applied. An isolated mid-point measurement (conv1d
fix only) showed a *higher* total than the unoptimized baseline despite
that function's own self-time provably dropping — traced to heavy
concurrent system load during that specific run (multiple VS Code
windows + antivirus scanning, confirmed via `Get-Process`, not a real
regression); reported here for transparency rather than silently
discarded, and is why the headline number above compares the two cleanest
available runs rather than every intermediate one. Parity-tested:
`tests/test_exported_model.py` gained batched-vs-individual-call parity
tests using both synthetic multi-model fixtures and the real
`ml/expert_models/*` exports (skipped gracefully in CI, where those
gitignored generated files don't exist).

**Numba JIT — evaluated, not added.** The user's decision was to evaluate
Numba if profiling showed per-call dispatch overhead wasn't fully solved
by batching/vectorization alone. Post-fix profiling shows the remaining
costs (`numpy.asarray` conversions, elementwise ops) are already
vectorized NumPy calls operating on real array data, not Python-loop-
driven dispatch overhead — the two costs that pattern actually described
(the conv1d loop and the 4-expert loop) are exactly what got fixed. Adding
Numba now would mean a new compiled-dependency build step (Docker image
size, wheel compatibility, first-call JIT-compilation overhead) for a
marginal remaining win, evaluated against real data rather than skipped
outright. Revisit if a future, quieter profiling run (or a real Lean
backtest, once one completes) shows otherwise.

**Rust/C++ extension rewrite: explicitly out of scope this pass** — a
real scope increase (PyO3/build toolchain/wheel packaging), appropriate
for a dedicated future HFT-fork effort, not bundled into an infra pass.

**Docker build caching.** The user's premise ("it reloads every library
on every build") didn't hold — all 3 Dockerfiles (`Dockerfile`,
`Dockerfile.workers`, `Dockerfile.retraining_worker`) already install
dependencies before copying source, the correct layer order. The real gap
was `.github/workflows/release.yml`'s `docker/build-push-action@v6` step
having no `cache-from`/`cache-to` configured, so every CI release build
started cold. **Fixed:** added `cache-from: type=gha` /
`cache-to: type=gha,mode=max`.

**Found and fixed while auditing documentation for this pass:**
`README.md`'s Project Structure tree and Module Documentation table were
both missing `features/`, `portfolio/`, and `backtests/` (all three had
real, substantive `README.md` files already, just never linked) — and
`scripts/` (the new home for `profile_inference.py`) had no `README.md`
at all. All four fixed. The `<!-- AQ:TEST_COUNT_START -->828<!--
AQ:TEST_COUNT_END -->`-style marker now wraps both prose "N tests"
mentions (Test Suite section, `tests/` row in the Module Documentation
table) so `aq test`'s badge-update logic keeps them in sync with the real
collected-test count too, not just the shields.io badge.

---

### 32. Latency deep-dive follow-up — weight-array/stack caching, `aq profile`, opt-in per-symbol multiprocessing, C++ extension attempt
**Severity:** n/a (optimization pass) · **Status:** 🟢 `fixed` (weight caching, harness, `aq profile`, multiprocessing, AND the C++ extension — built, compiled, verified importable, measured, tested; corrected from an earlier stale "in progress" badge, confirmed by re-checking this session: `cpp_inference_ext/cpp_inference.cp314-win_amd64.pyd` exists and `hasattr(cpp_inference, "linear_batched")` is `True` in `.venv` right now)

Direct follow-up to #31, after re-profiling the already-batched/vectorized
hot path and finding `numpy.asarray()` conversions were now the single
largest remaining cost (116.9s of a 290.6s total) — every inference call
was re-converting the SAME static, JSON-loaded model weights from Python
lists into NumPy arrays on **every single bar**, and
`run_exported_models_batched()`/`run_exported_multitask_models_batched()`
were rebuilding their stacked weight/bias arrays via `np.stack()` fresh
on every call too, despite the participating experts never changing after
load.

**Weight-array + batched-stack caching.** New
`inference/exported_model.py::convert_state_dict_arrays(export)` converts
every `state_dict` value from a list to a `np.float64` ndarray once, in
place — every existing `np.asarray()` call downstream becomes a no-op
(NumPy returns the same object unchanged when the input already matches
dtype), so this is a zero-API-change, zero-behavior-change speed fix.
Called once at each of `main.py`'s ~5 model-load sites. New
`build_layer_stacks()`/`BatchedLayerStackCache`/`build_models_batched_cache()`
(and multitask siblings) precompute the batched weight/bias stacks once
in `_ensure_ready()`, threaded through an optional `stack_cache` parameter
on the batched functions — default `None` reproduces the exact original
behavior, so every existing caller/test is unaffected.

**Measured result (scripts/profile_inference.py, 10,000-iteration
synthetic workload, real exported weights): 448.4s → 48.4s, -89.2%** —
far beyond #31's already-shipped -35.2%. Broken down: array-caching alone
(unbatched) got to 107.0s (-76.1%); adding batched-stack caching + the
batched expert path on top got to 48.4s. Mean per-symbol-bar latency
dropped from ~44.8ms to 4.83ms (p50 3.68ms). 14 new parity tests in
`tests/test_exported_model.py` (synthetic + real `ml/expert_models/*`
exports) prove the cached path is bit-identical to the uncached one.

**Profiling harness rebuilt.** The original harness measured its own
`random.uniform` input-generation cost as if it were inference cost
(~150s of the original 448s baseline was this, not real work). Inputs are
now pre-generated once, outside the profiled region. Also added
independent wall-clock per-iteration timing (p50/p95/p99/max/mean) — the
first tail-latency visibility this repo has had for this hot path,
separate from cProfile's own aggregate stats (which include cProfile's
own instrumentation overhead). 13 new tests in `tests/test_profile_inference.py`
for the extracted pure helpers (`percentile`, `summarize_durations`,
`pregenerate_inputs`).

**`aq profile`** — new CLI command (`aq_cli.py::cmd_profile()`, same
subprocess-wrapper convention as `cmd_backtest`/`cmd_report`) wrapping
`scripts/profile_inference.py`, so profiling this hot path no longer
requires knowing the script exists. 6 new dispatch tests.

**Opt-in per-symbol multiprocessing (`phase_v2.inference_parallelism.enabled`,
default `false`).** `main.py::on_data()`'s Pass 1 was restructured into
three phases: 1a (feature build, cheap, stays sequential — depends on
ordered, append-only mutation of several per-symbol history buffers),
1b (the actual profiled inference cluster — baseline/sequence/experts/
multitask/expert-multitask — now optionally parallelizable across
symbols), 1c (gating + signal derivation, cheap, stays sequential). New
`inference/parallel_inference.py::run_symbol_inference()` bundles the
inference cluster into one picklable, Lean-independent function; workers
load their own copy of every model export ONCE via
`ProcessPoolExecutor`'s `initializer` (never re-sent per call — sending
now-real NumPy arrays through IPC every bar would defeat the whole
point).

**Honest framing, not oversold:** per-symbol inference is now ~4.8ms
mean, specifically *because* the weight-caching/batching fix above
already closed the dominant cost — without multiprocessing. IPC/pickling
overhead may easily exceed any parallel win at this universe's size
(~30 symbols). Windows' `ProcessPoolExecutor` uses the `spawn` start
method, which re-bootstraps a fresh interpreter per worker; this has
never run inside Lean's own embedded-Python runtime (confirmed via
`python -c "import main"` failing outside Lean entirely — `main.py` has
no `__main__` guard and depends on Lean's own `AlgorithmImports` bridge,
so it was never designed to be a standalone `python.exe` process spawn
target). Pool creation and every pooled call are wrapped in their own
try/except with a 30s timeout; ANY failure permanently disables the pool
for the rest of the run and falls back to
`_run_inference_cluster_sequential()` — the exact same sequential
behavior/order/results as before this restructuring, byte-identical when
the flag stays at its default `false`. 9 new tests in
`tests/test_parallel_inference.py`, including a real
`ProcessPoolExecutor` round-trip (not just an in-process call) proving
the exports dict and the function are actually picklable across a real
OS process boundary. The real judge of whether this feature helps or
hurts is a real `lean backtest .` run — not attempted with this flag
enabled this pass (see the final backtest verification, which runs with
it at its default `false`).

**C++/pybind11 extension** (switched from an initially-proposed Rust/PyO3
approach per direct request) — built and verified working, with a real
(if modest) measured speedup:

- `rustc`/`cargo`/`cl.exe`/`g++` were ALL absent from this machine at the
  start of this pass (confirmed via `where`/`vswhere.exe`, not assumed).
  Installed the Microsoft C++ Build Tools (MSVC v14.51, via `winget`) since
  `pybind11` itself was already present (a sibling-project dependency,
  `pybind11==3.0.4`) — only the compiler needed installing. A trivial
  pybind11 "hello world" extension was compiled and imported successfully
  before writing any real code (`2+3=5` round-trip through a real `.pyd`),
  confirming the toolchain actually works end-to-end.
- New `cpp_inference_ext/` package (`setup.py` + `pyproject.toml` +
  `src/linear_batched.cpp`) builds an importable `cpp_inference` module
  accelerating `_linear_batched()`.
- **A real bug found and fixed during this build**: the source directory
  was originally named `cpp_inference/` (matching the module it builds) —
  `import cpp_inference` from the repo root resolved to that EMPTY source
  directory as a Python namespace package, silently shadowing the real
  installed extension (`sys.path[0] == ''`, i.e. cwd, is checked before
  site-packages). No error, no warning — `hasattr(cpp_inference,
  "linear_batched")` was simply `False`, `_linear_batched()`'s own
  try/except silently degraded to the NumPy path, and nothing looked
  broken from the outside. Fixed by renaming the source directory to
  `cpp_inference_ext/` (the module it *builds* stays named
  `cpp_inference` — only the folder name changed) — a real, generalizable
  lesson for any Python C-extension project: never name the source
  directory identically to the module it builds.
- **A second real gap found while verifying**: the extension was first
  `pip install`ed into system Python, not this project's actual `.venv`
  (confirmed by every other command this session needing
  `.venv/Scripts/aq.exe`, not the global `aq`) — so an early profiling
  comparison silently measured the NumPy fallback path both times and
  looked like "no difference." Installed into `.venv` specifically;
  confirmed via `hasattr(cpp_inference, "linear_batched")` there too
  before trusting any further numbers.
- **Measured result** (two back-to-back paired comparisons, same
  10,000-iteration `--batched` workload, C++ vs. NumPy-only immediately
  before/after each other to control for this machine's known load
  variance): **Pair 1: 111.5s → 92.8s (-16.7%). Pair 2: 135.1s → 79.8s
  (-40.9%).** Direction is consistent across both pairs (C++ always
  faster), magnitude is noisy (this machine's load swings 2x+ run to run,
  confirmed repeatedly this session) — a real, modest additional win on
  top of the weight-caching pass's -89.2%, not the dramatic kind. Matches
  the expectation already written into `cpp_inference_ext/README.md`
  before this was measured: the win, if any, is in per-call dispatch
  overhead for this project's genuinely small matrices (85→24→1-shaped
  experts), not raw FLOPs. 4 new tests in `tests/test_exported_model.py`
  (skip-guarded on the extension being built/importable), including one
  that simulates the C++ call itself raising to prove the NumPy fallback
  still activates correctly, not just the "extension absent" case.

### 33. Execution/risk realism pass — real `SlippageModel` wired to fills (spread + impact estimate previously computed and discarded)
**Severity:** 7/10 · **Status:** 🟢 `fixed`

`liquidity/market_liquidity.py::build_liquidity_decision()` computed
`estimated_round_trip_cost` (participation-based price impact + a real
Corwin & Schultz high-low spread estimate) every bar for every symbol, but
this codebase's own HFT-gap analysis (`development/v2_architecture.md`)
had already documented that the number went nowhere useful: no Lean
security ever had a `SlippageModel` attached (backtests got Lean's default
zero-slippage fill), and `execution/order_gate.py::simulate_fill()` — the
fill math behind every observation-mode simulated trade — always ran with
a hardcoded `slippage_bps=0.0`. Every historical backtest/observation-mode
run to date has therefore reported systematically-too-good fills,
regardless of order size or how thin the estimated liquidity actually was.

**Fixed** by threading the existing estimate into both fill paths instead
of building new estimation logic:

- New pure functions in `execution/order_gate.py`: `slippage_amount(
  reference_price, slippage_bps)` (bps -> absolute price delta, the one
  formula both paths now share), `resolve_slippage_bps(symbol_key,
  slippage_bps_by_symbol)` (lookup + clamp to `MAX_LIQUIDITY_SLIPPAGE_BPS`
  = 500bps/5%, a guard against a degenerate estimate rather than a
  normal-path limiter — `build_liquidity_decision()` already blocks orders
  at 5% participation long before the estimate could reach anywhere near
  this), and `resolve_fill_slippage(...)` composing both for the real-fill
  path. `simulate_fill()` itself is an unchanged-output refactor (`close_price
  + slippage_amount(...)` instead of an inlined `close_price * (1 +
  bps/10000)` — same math, single source of truth).
- `main.py::_LiquidityAwareSlippageModel` (new, Lean-dependent, lives in
  main.py per this repo's "only main.py touches AlgorithmImports"
  convention) — a thin `GetSlippageApproximation(asset, order)` adapter,
  duck-typed against Lean's `ISlippageModel`, delegating to
  `resolve_fill_slippage()`. Attached to every security in `_add_asset()`
  via `security.SetSlippageModel(...)` (refactored from 4 early-return
  branches to if/elif so the attachment happens once, not duplicated per
  asset type). Reads `self.latest_liquidity_slippage_bps`, a
  `dict[str, float]` keyed by `str(symbol)` refreshed every bar in Pass 2
  right after `build_liquidity_decision()` already runs — no new
  per-bar computation, just capturing a value that used to be discarded.
- `experience/simulated_portfolio.py::enter_long()` gained an optional
  `slippage_bps: float = 0.0` parameter; all ~5 `main.py` call sites now
  pass `resolve_slippage_bps(symbol_key, self.latest_liquidity_slippage_bps)`
  instead of relying on the old implicit zero.
- **Design decision, documented in `execution/README.md`**:
  `estimated_round_trip_cost` (spread + impact combined) was used rather
  than `estimated_slippage` alone, because Lean's fill model has no
  bid-ask awareness at all — this is the only place spread cost ever
  reaches an actual fill price in this codebase, not a double-count
  against a bid-ask model that doesn't exist.
- 12 new tests (`tests/test_order_gate.py`: `slippage_amount`,
  `resolve_slippage_bps`'s clamp/lookup/default behavior,
  `resolve_fill_slippage`; `tests/test_simulated_portfolio.py`:
  `enter_long()`'s new parameter, plus a parity test confirming the
  default (no `slippage_bps` passed) is byte-identical to explicit
  `slippage_bps=0.0`). `_LiquidityAwareSlippageModel` itself is not
  unit-testable in isolation — same constraint as every other Lean-typed
  piece of `main.py` (cannot import `main` outside Lean's runtime) — so
  all of its actual logic was extracted into the pure, unit-tested
  `execution/order_gate.py` functions above; the class itself is a
  2-line adapter with nothing left to test independently.

**Follow-up: both judgment calls above are now config flags, not hardcoded.**
The initial pass made two defensible-but-unreviewed decisions: which
`LiquidityDecision` field feeds the estimate (`estimated_round_trip_cost`
vs. `estimated_slippage`), and where the safety clamp sits (500bps). Both
are now `phase_v2.liquidity.fill_slippage.{source,max_bps}`, read once in
`_ensure_ready()`, settable via `aq config set` with no code change:
`resolve_slippage_bps()`/`resolve_fill_slippage()` gained an optional
`max_bps` parameter (default `MAX_LIQUIDITY_SLIPPAGE_BPS`), and new
`liquidity_cost_fraction(liquidity_payload, source)` +
`resolve_fill_slippage_source(raw_source)` (fail-safe normalize, same
pattern as `resolve_runtime_mode()`) pick the estimate field. 13 more
tests (10 in `test_order_gate.py` for the new params/functions, 3 in
`test_aq_cli.py` proving both keys are reachable via the existing generic
`aq config get`/`set` — no new CLI code needed, since `aq config` already
operates on arbitrary dotted paths into `config.json`).

### 34. Real limit-order support — every tradable asset class, config-gated (part 2 of the execution/risk realism pass)
**Severity:** 6/10 · **Status:** 🟢 `fixed` (config-gated, default off; Lean API casing/dispatch assumptions remain unverified until a real backtest — see below, not blocking)

Entry #33 closed half of `development/v2_architecture.md`'s documented
HFT-gap item 3 (real fill slippage). The other half was still open: *"no
limit-order/queue-position-aware execution exists — fills are still
all-or-nothing market fills."* Every real order in `main.py` was a
`MarketOrder()`/`SetHoldings()` market fill across all 5 call sites (option
buy, future buy/short, equity-crypto-bond buy/short) with no alternative.

**Fixed**: real `LimitOrder()` support, config-gated (`phase_v2.limit_orders`,
default off), for every asset class the project trades:

- New pure functions in `execution/order_gate.py`: `resolve_limit_price(
  reference_price, spread_fraction, is_buy, offset_multiplier=1.0)` (buy
  limits below reference, sell/short above, offset by half the already-
  computed `liquidity_payload["spread_proxy"]` — no new estimate
  invented) and `classify_order_status(status_name)` (pure string
  classification into pending/filled/canceled/unknown, isolating the one
  place this pass has to guess at Lean's real `OrderStatus` enum spelling
  into a single function).
- `main.py::_try_submit_limit_order()` — the shared helper wired into all
  5 existing real-order branches. Returns `False` immediately when
  disabled/asset-class-excluded (the only possible behavior in that
  case), so every caller's existing market-order call is what actually
  runs when the feature is off. Quantity reuses whatever the caller
  already computed for future/option (used exactly as-is — see the sign
  bug caught and fixed below) or Lean's own
  `self.CalculateOrderQuantity(symbol, target_weight)` for
  equity/crypto/bond, instead of writing new custom sizing math.
- `main.py::on_order_event()` (new) — Lean's real order-fill callback,
  snake_case override matching `initialize()`/`on_data()`'s proven
  naming. Stamps `last_trade_bar_by_symbol` at confirmed-fill time
  (instead of the old order-*placement*-time stamp) so a signal that
  flips while an order sits unfilled isn't blocked by a cooldown for a
  trade that never happened — feature-off behavior is unchanged.
- `main.py::_process_pending_limit_order_timeouts()` (new) — runs once
  per bar right after `_refresh_risk_state()` (the same "resolve stale
  state before this bar's fresh signal computation" anchor point that
  method's own drawdown-breach `Liquidate()` already uses). Cancels
  anything past `unfilled_timeout_bars` and, per a **per-asset-class**
  fallback flag (not a single global bool — equity/crypto/bond default
  `true`, future/option default `false`, since a silent fallback fill
  there is a real position the model didn't choose at that price under
  margin/expiry mechanics), optionally places a real `MarketOrder()` for
  the remainder.
- `phase_v2.limit_orders`: `enabled` (default `false`), `asset_classes`
  (default all 5), `offset_multiplier` (default `1.0`),
  `unfilled_timeout_bars` (default `3`), `fallback_to_market_on_timeout`
  (per-asset-class dict, mirrors the existing
  `exposure_caps_by_asset_class` shape) — all settable via the existing
  generic `aq config set`, no new CLI code.

**A real sign bug caught and fixed during implementation, not after**: the
initial draft applied a uniform `abs(contract_quantity) if is_buy else
-abs(contract_quantity)` transform to the already-computed quantity
passed in for futures/options. This is wrong for futures —
`_futures_contract_count_for_weight()` already returns a
target-weight-signed count (matching `MarketOrder(symbol, contract_count)`'s
existing convention exactly), so re-deriving the sign from `is_buy` would
have silently flipped correctly-negative short-futures quantities. Fixed
by using `contract_quantity` exactly as submitted by the caller for
future/option, and deriving `is_buy` only for `resolve_limit_price()`'s
price-side direction (a separate concern from quantity sign) — never for
quantity sign itself. A second bug of the same flavor: option orders'
pending-order entries were initially recording the CONTRACT symbol under
the key `last_trade_bar_by_symbol` reads from, but that dict is keyed by
the CHAIN symbol everywhere else in this codebase — fixed by adding a
`chain_symbol` field to the pending-order entry, distinct from the
order-target `symbol` (which legitimately is the contract symbol for
options).

**Known, real, unverified-until-a-real-backtest risk (stated up front, not
buried)**: this codebase's proven-working code calls the Lean API with
PascalCase (`self.MarketOrder`, `self.SetHoldings`, `self.SetSlippageModel`)
but overrides Lean's callbacks with snake_case (`initialize`, `on_data`) —
not PascalCase. The locally installed `quantconnect-stubs` package
declares the entire API in snake_case only and disagrees with this
codebase's own working precedent, so it isn't authoritative. This pass
matches the proven mixed convention (PascalCase calls, snake_case
`on_order_event` override) throughout — but `OrderStatus` enum member
casing specifically, whether `on_order_event` dispatches at all, and
whether it fires with the contract vs. chain symbol for options are all
genuinely unverifiable without a real Lean run. See
`execution/README.md`'s "Real limit orders" section for the full
prioritized verification list — this is the single biggest open risk in
the feature and deliberately not glossed over.

**Testing**: 12 new pure-function tests in `tests/test_order_gate.py`
(`resolve_limit_price`'s buy-below/sell-above/offset-scaling/fail-safe
behavior, `classify_order_status`'s full status-name coverage), 4 new CLI
reachability tests in `tests/test_aq_cli.py` (including one proving the
per-asset-class `fallback_to_market_on_timeout` dict's partial-override
shape works through the existing generic `aq config get/set` with zero
new CLI code). `_try_submit_limit_order`/`on_order_event`/
`_process_pending_limit_order_timeouts` and the 5 modified call sites are
not unit-tested in isolation — same `main.py`-cannot-be-imported-outside-
Lean's-runtime constraint `_LiquidityAwareSlippageModel` hit in entry #33;
all real logic lives in the pure, tested functions above.

### 35. Disabling an asset class never liquidated already-open positions (Section 0: also fixed 2 stale doc comments)
**Severity:** 6/10 · **Status:** 🟢 `fixed`

Two stale documentation bugs fixed alongside this entry, found while
researching it: `main.py`'s comment on the option `_add_asset()` branch
still claimed greeks "only populate once IB supplies real chain bid/ask
data" and that order placement "is a documented non-goal" — both false
(chain data is Lean's own local backtest feed, no IB key needed; real
order placement was closed in entry #34). `portfolio/README.md` had the
identical stale "does not call SetHoldings()/MarketOrder()" claim. Both
rewritten to match reality.

**The real gap**: `phase_v2.futures_risk.enabled`/`phase_v2.options_risk.enabled`
flipping to `False` mid-run correctly zeroed a position's *sizing*
(`_build_dynamic_sizing_payload()` forces the sizing kwargs to 0, which
`route_position_sizing()`'s future/option branches turn into
`contract_count=0`/no usable option decision) — but never touched a
position already open from *before* the flag flipped off.
`_derive_signal()` (driven purely by `probability_up`) has no idea these
flags exist, so `signal_name` stays `"buy"`/`"short"` and never becomes
`"hold"` — the only existing liquidation trigger
(`if signal_name == "hold" and previous_signal != "hold" and
self._is_invested(...)`) was never reached. `_apply_signal()`'s
future/option branches just kept returning
`"futures_zero_contract_count"`/`"options_no_usable_contract"` forever,
silently, every bar, with the stale position sitting untouched.
Equity/crypto/bond have no enable/disable flag anywhere in this codebase
— confirmed via a full scan of every `phase_v2.*.enabled` key in
`config.json` — so this only ever applied to futures/options.

**Fixed**:
- `risk/asset_class_router.py::resolve_asset_class_enabled(asset_class,
  futures_risk_enabled, options_risk_enabled)` and
  `should_liquidate_disabled_asset_class_position(asset_class_enabled,
  is_invested)` — two pure functions, extending this module's existing
  dispatch-logic ownership rather than a new module for two 3-line
  functions.
- `experience/simulated_portfolio.py::SimulatedPortfolioState.exit_using_last_known_price(symbol_key, bar_index)`
  — sibling of `exit()`/`liquidate_all()`, resolving the missing
  close-price argument the same way `liquidate_all()` already does
  (`self._last_prices.get(symbol_key, holding["avg_price"])`), delegating
  to `exit()` for the actual cash/pnl/trade_log math — no duplicated
  logic.
- `main.py::_liquidate_positions_for_disabled_asset_classes()` — new
  per-bar sweep, called immediately after `_refresh_risk_state()` and
  before `_process_pending_limit_order_timeouts()` — the same "resolve
  stale state before this bar's fresh Pass 1/Pass 2 signal computation"
  anchor point that method already established, for the identical
  reason. Thin adapter: iterates `self.symbols`, resolves `asset_class`
  via the existing `asset.get("asset_class") or asset.get("security_type")`
  idiom, calls the two pure functions above, liquidates on a hit
  (`_liquidate_position()` real / `exit_using_last_known_price()`
  simulated), stamps `last_trade_bar_by_symbol` (matching every other
  liquidation branch), sets `latest_signal_state[symbol_key] = "hold"`
  for downstream consistency, logs via `self.Debug()` only (no
  `signals` dict write — Pass 2 still runs this bar and records an
  accurate, still-true execution note, matching
  `_process_pending_limit_order_timeouts()`'s own precedent for not
  double-writing state).
- A genuine no-op for equity/crypto/bond always, by construction
  (`resolve_asset_class_enabled()` never returns `False` for them).

**Testing**: full truth-table tests for both new pure functions in
`tests/test_asset_class_router.py`; no-op/last-price-fallback/parity
tests for `exit_using_last_known_price()` in
`tests/test_simulated_portfolio.py` (parity test confirms it produces an
identical result to calling `exit()` directly with the same resolved
price). `_liquidate_positions_for_disabled_asset_classes()` itself is not
unit-testable in isolation — same `main.py`-cannot-be-imported-outside-
Lean's-runtime constraint every prior Lean-adapter method this session
hit. One real-backtest-only item: `self.Portfolio[...].Invested` is now
read at a new, earlier point in `on_data()`'s execution order than
before — should be fine since `Portfolio` state doesn't depend on
anything computed later in the bar, but flagged as unverified until a
real backtest confirms it.

### 36. Latency profiling extended beyond inference — build_market_topology() found to be a much larger per-bar cost than the entire inference step
**Severity:** 6/10 · **Status:** 🟢 `fixed` (new `profile_subsystems.py` harness + `aq profile --<subsystem>` flags shipped and tested; the real ~500-600ms/bar `build_market_topology()` cost this found now has a real, shipped, tested, config-gated-off fix — see "Follow-up: caching fix implemented" below — not yet validated against a real Lean backtest, which is scoped to a later dedicated session)

`scripts/profile_inference.py` only ever profiled
`inference/exported_model.py`'s forward-pass functions (entries #31/#32).
Every other per-bar subsystem `main.py::on_data()` calls — feature
engineering's underlying indicator primitives, regime detection,
deterministic + learned topology, liquidity, gating, signal
derivation/analysis — had never been measured at all.

**Fixed**: new sibling harness `scripts/profile_subsystems.py` (a
sibling of `profile_inference.py`, not an extension of it — different
input shapes per subsystem, same "new function alongside, not a
generalization" precedent this codebase already uses elsewhere).
Reuses `percentile()`/`summarize_durations()` from `profile_inference.py`
rather than duplicating. Covers `regime`
(`regime/market_regime.py::build_market_regime_vector()`), `topology`
(`topology/market_topology.py::build_market_topology()`),
`learned_topology` (`topology/learned_topology.py::apply_learned_topology()`,
graceful-degrade path only — no trained model assumed present on disk),
`liquidity` (`liquidity/market_liquidity.py::build_liquidity_decision()`),
`gating` (`moe/gating.py::build_gating_decision()`), `analyzer`
(`analyzer/market_analyzer.py::build_market_analysis_decision()`), and
`indicators` (the 7 pure functions in `features/technical_indicators.py`,
each timed **independently**, not summed, so a dominant one is visible
rather than averaged away). Exposed via new `aq profile --<subsystem>`
flags (`--regime`/`--topology`/`--learned-topology`/`--liquidity`/
`--gating`/`--analyzer`/`--indicators`, combinable), following the exact
same loop-generated-flags convention `aq test --cli --risk` already
established (`_PROFILE_SUBSYSTEM_FLAGS` mirrors `_SUBSYSTEM_TEST_FILES`).
`--batched` + any subsystem flag is rejected (exit 1, not silently
ignored) — batching has no meaning for these pure functions.

**Deliberate, documented scope decision**: `main.py::_build_model_input()`
itself is NOT profiled — it's a bound method reading ~15 pieces of
`self.*` state (symbol_windows, scaler_stats, latest_macro_payload,
etc.), not cleanly synthesizable the way inference's exported model
weights were. `--indicators` profiles its underlying pure primitives
instead — a partial-coverage choice, not silent scope-narrowing. The
README's "Latency profiling only covers inference" bullet is narrowed to
reflect this remaining, still-real gap rather than removed outright.

**A real, substantial, previously-invisible finding**: `build_market_topology()`
costs **~500-600ms per call** at this project's real ~30-symbol universe
size (measured: p50=559.99ms, mean=615.69ms, p99=1616.27ms,
max=1786.90ms across 200 iterations on this dev machine) — likely its
`O(n^2)`-ish correlation-matrix + embedding math (default
`embedding_iterations=100`). Topology is called **once per bar** (not
per-symbol, unlike inference), so this single call's cost is comparable
to or larger than the *entire* per-symbol inference total across the
whole universe (~30 symbols × ~5ms/symbol ≈ 150ms/bar, post the
weight-caching optimization in #32). This had never been measured before
this pass — inference was optimized aggressively (entries #31/#32) while
a genuinely larger cost sat completely unmeasured next to it. **This
also forced a real design change to the harness itself**: `--iterations`
defaults to **200** for `profile_subsystems.py` (not `profile_inference.py`'s
10,000) — 10,000 iterations of `build_market_topology()` alone would
take over an hour. `aq_cli.py`'s `--iterations` flag now defaults to
`None` at the CLI layer specifically so each script's own default
applies when the user doesn't pass one explicitly — hardcoding either
number at the CLI layer would have silently overridden the other
whenever a `--<subsystem>` flag routed to the other script.

No code fix is proposed for `build_market_topology()`'s cost in this
pass — that's a real optimization opportunity for a future pass
(candidate: `embedding_iterations` reduction, or skipping recomputation
when the correlation structure hasn't materially changed bar-to-bar),
flagged here as a finding, not silently left unmentioned.

**Testing**: 7 new tests in `tests/test_profile_subsystems.py` (shape/
non-negativity, tiny iteration counts — matching
`test_profile_inference.py`'s own scope, not a real profiling run), 7 new
CLI reachability tests in `tests/test_aq_cli.py` (subsystem routing,
multiple-flags-combinable, explicit-vs-omitted `--iterations`, the
`--learned-topology` hyphen-to-underscore CLI mapping, the
`--batched`+subsystem rejection). One pre-existing test
(`test_profile_wraps_profile_inference_script_with_defaults`) updated to
match the new `--iterations`-omitted-by-default behavior — a real,
intentional behavior change to `aq profile`'s default invocation, not a
regression.

---

**Follow-up: caching fix implemented (correlation-stability embedding
cache).** The "skipping recomputation when correlation structure hasn't
materially changed bar-to-bar" candidate above is now real, shipped code
— `build_market_topology()` gained `previous_correlations`/
`correlation_stability_tolerance` parameters: when both are given and
every pairwise correlation moved by no more than the tolerance since the
prior bar (and the eligible-symbol universe is unchanged — a new/dropped
symbol always forces a full recompute), the expensive SMACOF embedding
call is skipped entirely and the prior bar's already-converged positions
are reused directly. Everything else per node (`correlation_strength`,
`market_distance`, `volatility_pressure`, `topology_risk`, `regime_label`,
`top_peers`/`top_peer_returns`, `cluster_id`) is still recomputed fresh
every bar regardless — none of those depend on the embedding. Gated by
`phase_v2.topology.cache_enabled` (default `false`) and
`phase_v2.topology.correlation_stability_tolerance` (default `0.02`) —
disabled reproduces today's exact behavior byte-identical, same rollback
contract `warm_start_enabled: false` already guarantees.

**Correctness is directly proven** (not just inferred from output shape):
a new `tests/test_market_topology.py` case feeds `_stress_majorize_2d`
through `unittest.mock`/`monkeypatch` and asserts it is called **zero**
times when correlations are genuinely unchanged, plus cases covering
tolerance-exceeded, universe-changed, and missing-state fallback to full
recompute, and a disabled-matches-omitted byte-identical parity test
(same pattern `test_warm_start_disabled_matches_omitting_previous_positions`
already established).

**Honest finding, not yet a demonstrated real-world speedup:** validating
the *benefit* (not just correctness) needed a new `aq profile
--topology-cached` workload (`scripts/profile_subsystems.py`'s existing
`--topology` workload draws fully independent random returns every
iteration by construction and can never show any benefit from a
bar-to-bar staleness cache). Building that workload surfaced a real,
useful, previously-unknown constraint: at this project's real universe
size (~30 symbols → 435 unique pairs) with a 25-observation rolling
correlation window, **the skip essentially never fires at the shipped
0.02 tolerance** — not because the mechanism is broken (proven correct
above), but because sample Pearson correlation over just 25 observations
has enough inherent small-sample noise that *some* pair among 435 almost
always moves by more than 2 percentage points bar-to-bar, even under a
genuinely stable, slowly-drifting single-factor synthetic model (measured
typical max-pair-change ≈0.15-0.30 per bar across 100+ synthetic bars,
well above 0.02, at `loading_drift` values an order of magnitude smaller
than would be visually detectable as "drift" at all). An earlier version
of this workload generator random-walked each raw return value directly
bar-to-bar instead of using a factor model — that silently produced
near-constant, numerically-degenerate per-symbol variance after enough
steps (the same *class* of ill-conditioned-correlation issue
`features/bond_features.py::empirical_duration_beta()` hit in production
code, entry #10, just caught here in synthetic test data instead), and
was replaced before this finding could even be trusted.

**What this means, honestly:** the fix is real, shipped, and provably
correct when its precondition holds — but whether that precondition
(correlation stability within 0.02) holds often enough on **real**
historical market data to be worth enabling is genuinely unknown from
synthetic data alone, and is exactly the kind of question this project's
own established methodology (a real `lean backtest .` run, entries #16/
#17) is for, not more synthetic profiling. Left config-gated off
specifically because of this — enabling it and tuning
`correlation_stability_tolerance` against real historical correlation
behavior is scoped to a later dedicated Lean-backtest health-check
session, not this pass.

**Testing (this follow-up)**: 7 new tests in `tests/test_market_topology.py`
(disabled-matches-omitted parity, stable-correlations reuse + reasons
marker, the mock-proof zero-SMACOF-calls case, tolerance-exceeded,
universe-changed, missing-state fallback, `correlations` field
presence/emptiness on ready vs. insufficient_data), 2 new workload-shape
tests plus 1 sliding-window-not-resampling test in
`tests/test_profile_subsystems.py`, 5 new CLI/config reachability tests
in `tests/test_aq_cli.py` (`--topology-cached` hyphen mapping,
`phase_v2.topology.cache_enabled`/`correlation_stability_tolerance` get/
set). Full suite: `aq test` → 1318 passed, 0 failed, 11 deselected
(`lean_backtest`, expected), 1 pre-existing warning.

### 37. Inference tail latency (p99 3-5x p50) — investigated: real GC-pause contribution to worst-case latency confirmed, root cause of the old `scripts/profile_inference_output.txt` discrepancy resolved as machine load, not a regression
**Severity:** 4/10 · **Status:** 🟢 `fixed` (investigation complete, `--bucket-report`/`--no-gc` harness additions shipped and tested; `gc.freeze()` production tuning is now real, shipped, config-gated-off code — see "Follow-up: gc.freeze() implemented" below — not yet validated against a real Lean backtest, which is scoped to a later dedicated session)

Nothing in this repo had ever investigated *why* `scripts/profile_inference.py`'s
p99 routinely ran 3-5x the p50 — only the visibility that it does existed
(entry #32). This entry closes that gap with real diagnostic work, not
just new code.

**Step 1 — resolved a real discrepancy found while starting this work.**
The on-disk (git-ignored, never committed, not tied to any revision)
`scripts/profile_inference_output.txt` showed dramatically worse numbers
(p99=104.30ms, mean=13.40ms, `numpy.asarray` costing 30.4s of 135.1s
total) than the canonical "AFTER" snapshot #32 cites (p99=15.73ms).
Reran `aq profile --batched --iterations 10000` 3 times back-to-back
(matching #32's own paired-run methodology): **total function call count
was perfectly identical across all 3 fresh runs (6,460,385) while wall
time varied 2x (69.3s → 46.0s → 35.9s)** — call count is load-independent
and stable, wall time is not, which is exactly the signature of machine
load variance rather than a code-path regression. None of the 3 fresh
runs showed `numpy.asarray` anywhere near the stale file's dominant
30.4s cost — `convert_state_dict_arrays()` (entry #32) is working
correctly on current code. The stale file's differing call count
(6,820,002 vs. 6,460,385 now) confirms it predates later changes in this
session (fewer calls now) rather than reflecting current code at all.
**Conclusion: hypothesis (a) — a stale/unrelated local run, not a
regression.** No fix needed; the file is regenerated by every `aq
profile` run and was never meant to be authoritative between runs.

**Step 2 — iteration-index bucketing** (new
`scripts/profile_inference.py::bucket_durations_by_iteration_index(durations,
n_buckets=10)`, pure, plus a new `--bucket-report` flag, print-only, zero
effect on the existing tail-latency/pstats numbers). Real result: p50 was
stable across all 10 buckets (2.48-3.16ms range) — **no warmup effect**.
Tail spikes (elevated p99/max) appeared scattered across *multiple*
buckets (0, 5, 6, 9), not concentrated in bucket 0 alone — this pattern
rules out a cold-start/warmup explanation and points toward GC pauses or
OS scheduler preemption instead, motivating Step 3.

**Step 3 — GC-pause isolation** (new `--no-gc` flag, wraps the existing
`run_workload()` call in `gc.disable()`/`gc.enable()`, inference-profiling
only). Two paired before/after runs, back-to-back:
- Pair 1: max 121.56ms (GC on) → 40.89ms (GC off), -66.4%. p50 3.31ms → 3.10ms (flat, within noise).
- Pair 2: max 262.72ms (GC on) → 14.02ms (GC off), -94.7%. p50 2.73ms → 3.05ms (flat, within noise).

**Real, reproduced finding: GC pauses are a material contributor to this
hot path's worst-case (max) tail latency specifically** — p50 is
unaffected either way (confirming this isn't a general speedup, just a
tail-specific effect), and the *max* value dropped dramatically and
consistently across both independent pairs. p99 improvement was present
but noisier/less dramatic than max's.

**Not implemented that pass, by design**: `gc.freeze()` after model load
in `main.py::_ensure_ready()` (the model weight arrays are large,
long-lived, and never mutated after load — a textbook `gc.freeze()`
candidate to keep them out of every future generational GC scan) was
documented as a candidate future production tuning knob, not shipped —
genuinely riskier than anything else in that pass, needing real-backtest
validation of its interaction with Lean's own .NET/Python interop GC
boundary that a synthetic harness cannot exercise.

**Fixed** (the harness itself):
- `scripts/profile_inference.py::bucket_durations_by_iteration_index()`
  (pure) + `--bucket-report` flag.
- `--no-gc` flag (`gc.disable()`/`gc.enable()` around the profiled
  region only).
- `aq profile --no-gc`/`--bucket-report` (inference-profiling only,
  rejected loudly in combination with any `--<subsystem>` flag from
  entry #36, same posture as `--batched`).

**Testing**: 6 new pure-function tests for
`bucket_durations_by_iteration_index()` in `tests/test_profile_inference.py`
(empty input, uniform bucketing, a synthetic "first-10-iterations-10x-
slower" case correctly surfacing in bucket 0 only, call-order-not-sorted-
order preservation, default bucket count, non-positive bucket count).
4 new CLI reachability tests in `tests/test_aq_cli.py`.

---

**Follow-up: `gc.freeze()` implemented, config-gated off.** The candidate
above is now real, shipped code: `main.py::_ensure_ready()` calls
`gc.freeze()` once, right after the last model/weight-array load
(`self.symbol_feature_history` construction — the same point every
model, expert, gating, multitask, and batched-stack-cache array is
guaranteed already loaded) and strictly before the
`inference_parallelism` process-pool spawn. Gated by
`phase_v2.gc_tuning.freeze_after_load_enabled` (new top-level `phase_v2`
section, default `false`) — disabled means the new `import gc` line and
one `if` check are the only change to the hot path, zero behavior
difference from before this follow-up. The real production-safety
concern that kept this unshipped originally is **unchanged by this
follow-up** — it's still true that this needs real-backtest validation
of the .NET/Python interop GC boundary that no synthetic harness can
provide. What changed is the sequencing: rather than waiting for that
validation before writing any code, the code now exists, tested, and
inert by default, ready to flip on and validate in a later dedicated
Lean-backtest health-check session without needing another coding round
first.

**Testing**: `main.py` itself remains untestable outside Lean's runtime
(confirmed again this pass — no `__main__` guard, requires
`AlgorithmImports`, same constraint every prior `main.py`-touching entry
this session hit). The only testable surface is the config plumbing: 2
new reachability tests in `tests/test_aq_cli.py`
(`phase_v2.gc_tuning.freeze_after_load_enabled` get/set via the existing
generic `aq config get`/`set`, `_config_fixture()` extended with the new
key). Full suite: `aq test` → 1318 passed, 0 failed, 11 deselected
(`lean_backtest`, expected), 1 pre-existing warning.

### 38. 2-leg vertical spread selection for options — explicit scope-in of a previously-non-goal feature
**Severity:** n/a (feature scope-in) · **Status:** 🟢 `fixed` (implementation complete and tested; verification against a real Lean backtest is the largest open item this session produced, see below — not an incomplete implementation)

Entry #29 explicitly scoped multi-leg options spread selection out:
*"a genuinely new spread-selection model architecture is future work."*
No partial design existed anywhere in the repo beyond that one-line
mention. This entry closes the minimal, most conservative slice of that
gap — **only** the 2-leg vertical spread case — explicitly, not silently.

**Scope decision, stated prominently, not silently narrowed**: only call
verticals (`bull_call_spread`) and put verticals (`bear_put_spread`) are
implemented — the minimal extension of "long calls or long puts."
Straddles, strangles, iron condors, and butterflies remain out of scope,
narrowing (not removing) entry #29's non-goal note. Default is
`"single_leg"` (today's exact existing behavior) — vertical spreads are
opt-in via `phase_v2.options_risk.spread_strategy: "vertical"`.

**Research finding: chain data needs no IB key.** `slice.option_chains`
is Lean's own local backtest data feed (`lean.json`'s
`data-provider: DefaultDataProvider`), and this repo already bundles real
sample options chain data (`data/option/usa/{daily,hour,minute}/`). IB is
only relevant for live margin/broker connectivity, never for backtest
chain data. `features/options_greeks.py` (pure Black-Scholes-Merton) is
already leg-agnostic — no changes needed there.

**A genuinely novel discovery: `QuantConnect.Securities.Option.OptionStrategies`
(named factories: `bull_call_spread`, `bear_put_spread`, `butterfly_call/put`,
`iron_condor`, `straddle`, `strangle`) and `QCAlgorithm.Buy(strategy, quantity)`
already exist in this project's installed Lean stubs and were completely
unused anywhere in this codebase before this pass** (confirmed via grep —
zero hits). This is the correct atomic multi-leg placement primitive,
avoiding the partial-fill/leg-slippage risk of hand-rolled sequential
single-leg orders.

**Fixed**:
- `portfolio/options_strategy.py`: new `OptionsSpreadLeg`/
  `OptionsSpreadPositionDecision` dataclasses (parallel additions -
  `OptionsPositionDecision`/`select_single_leg_contract()`/
  `build_options_position_sizing()` stay byte-identical, matching this
  codebase's "new function alongside, not a generalization" precedent).
  `select_vertical_spread_legs()` reuses `select_single_leg_contract()`
  unchanged for the long leg; the short leg is the nearest-delta match to
  `target_delta - short_leg_delta_offset` among same-expiry rows filtered
  to the risk-capping side (strike direction enforced explicitly on
  strike, never inferred from delta ordering).
  `build_vertical_spread_position_sizing()` sizes by **net vega** (long
  minus short), the spread's defining risk reduction versus a single leg.
- `risk/asset_class_router.py`'s option branch gains a `spread_strategy`
  dispatch (default `"single_leg"`, unreachable-otherwise by construction)
  and a new `_options_spread_decision_to_position_sizing()` adapter,
  parallel to the existing single-leg adapter.
- `main.py::_apply_option_order()` now checks `hasattr(options_decision,
  "legs")` **before** touching `contract_symbol` (a real bug caught during
  implementation: `OptionsSpreadPositionDecision` has no `contract_symbol`
  field, so the old unconditional `getattr(options_decision,
  "contract_symbol", None)` would have silently rejected every spread
  decision as "no usable contract" had the check order not been fixed).
  Delegates to new `_apply_option_spread_order()`, which places the spread
  atomically via `OptionStrategies.bull_call_spread()`/`bear_put_spread()`
  + `self.Buy(strategy, quantity)`.
- **New, additive** `self.option_contract_symbols_by_symbol: dict[str, list]`
  (plural) alongside the existing singular dict — deliberately not a
  repurpose of the existing dict's value type, which would have forced
  every one of its ~6 existing read sites to branch even on the default
  single-leg path. New `_order_target_symbols(symbol) -> list` sibling of
  `_order_target_symbol()`, provably byte-identical to
  `[_order_target_symbol(symbol)]` for every non-spread position by
  construction (the plural dict is only ever populated by
  `_apply_option_spread_order()`). `_is_invested()`/`_liquidate_position()`
  updated to iterate it; `_asset_class_exposure()` needed no change
  (already leg-count-agnostic — iterates real `Portfolio.Values` and maps
  each back to its chain symbol_key independently, a 2-leg spread just
  contributes two entries instead of one, both correctly attributed).
- **A second real bug caught during implementation**: an early draft
  wrote `getattr(options_decision, "contract_symbol", None)` unconditionally
  as the very first line, which would have broken option orders entirely
  for the spread case (see above) — caught and fixed by re-reading the
  method before considering it done, not left for a test to find (no test
  could have found it anyway, given the untestable-in-isolation
  constraint below).
- **Deliberate scope trade-off, documented not hidden**: closing a spread
  liquidates each leg independently (two separate `Liquidate()` calls),
  not an atomic combo unwind. An already-open, already-hedged position
  unwinding leg-by-leg is a materially smaller risk than the entry side
  (which needed atomicity to avoid an unhedged half-fill). Reconstructing
  the exact `OptionStrategy` at close time would need persisting
  `strategy_name` + both strikes + expiration per open spread position -
  real bookkeeping this pass doesn't add.
- **A known, minor, conservative-direction side effect, not fixed this
  pass**: `_active_position_count()` counts `Portfolio.Values` entries
  directly and doesn't know about spreads - a single 2-leg vertical
  position counts as 2 toward `max_active_positions`, not 1. This errs
  conservative (using more of the position-count budget than strictly
  necessary), not incorrect in a risk-increasing direction, so it was
  left as-is rather than expanding this pass's scope further.
- **Config**: `phase_v2.options_risk.spread_strategy` (default
  `"single_leg"`), `phase_v2.options_risk.short_leg_delta_offset`
  (default `0.20`). `config.json`'s `phase1.universe.assets` still has no
  option/future entries at all — exercising this via a real backtest
  needs config additions too, out of scope for this implementation pass.

**Testing**: 20 new tests in `tests/test_options_strategy.py` (leg
selection, strike-direction enforcement, net-vega sizing, every
degrade-to-`None` condition, `to_dict()` JSON-safety), 5 new tests in
`tests/test_asset_class_router.py` (dispatch, **the critical
zero-behavior-change parity test**: `options_kwargs` entirely absent
produces a byte-identical result to `options_kwargs={"spread_strategy":
"single_leg", ...}` explicitly, plus the stray-`short_leg_delta_offset`-
doesn't-raise regression guard for the bug class described above). The
`main.py` spread-placement/tracking-dict changes are not unit-testable in
isolation — same `main.py`-cannot-be-imported-outside-Lean constraint
every prior Lean-adapter this session hit; the zero-behavior-change claim
for `_is_invested()`/`_liquidate_position()` rests on direct re-reading
(list-of-1 is byte-identical to the prior scalar for every non-spread
position), not a runnable test.

**Verification — only a real Lean backtest can confirm these, the
largest such list this session** (zero prior combo-order usage in this
codebase before this pass): whether `OptionStrategies.*` actually accepts
the canonical chain Symbol this codebase already holds; whether
`self.Buy(strategy, quantity)` returns one `OrderTicket` per leg in a
matchable order; whether leg-by-leg `Liquidate()` behaves sanely against
a combo-opened position, or whether Lean's margin/position-netting model
needs an `OptionStrategy`-aware unwind path this pass isn't using;
general real fill/margin behavior for a debit spread. See
`risk/README.md`'s "Multi-asset-class risk dispatch" section for the
same list, mirroring entry #34's format.

---

### 39. Final pre-backtest bug sweep — 4 fixes found and fixed before this project's first real `lean backtest .` run
**Severity:** 6/10 (the test-harness bug) / 5/10 (liquidity threshold collision) / 3/10 (limit-order timeout) / 2/10 (book-slot crash risk) · **Status:** 🟢 `fixed`

A dedicated bug sweep of the trading-critical path (`main.py`'s per-bar loop, recent order-placement code, `risk/`/`portfolio/`/`liquidity/` config wiring) done specifically to de-risk this project's first-ever real `lean backtest .` run. Four real, confirmed issues found and fixed; several other candidate areas (topology cache, `gc.freeze()`, book-slot asset_class threading, option/spread order sign/state logic) were reviewed and found correct, matching their own already-documented "needs real-backtest validation" caveats rather than being new bugs.

1. **`tests/test_lean_backtest_ml_coverage.py` lines 235/245/274 — wrong key path, would have silently failed 3 of the suite's 11 assertions on the very first real `aq test --lean` run.** `state_after_backtest.get("config", {}).get("model", {})` — `main.py::_write_state()` never writes a top-level `"config"` key; `"model"` is itself top-level. This always evaluated to `{}` regardless of what the backtest actually did, so `test_model_input_dimensionality_is_59`, `test_baseline_multitask_model_ran`, and `test_sequence_model_ran` would have failed even on a perfectly correct backtest — a test-harness bug, not evidence those subsystems didn't run. Never caught before now because the `lean_backtest` marker has kept this whole file excluded from every routine `aq test` run since it was written. **Fixed**: all three now read `state_after_backtest.get("model", {})` directly.

2. **`config.json`'s `phase_v2.liquidity.thin_participation_threshold` and `high_impact_participation_threshold` had both drifted to the same value (`0.01`), silently collapsing a two-tier system to one.** `liquidity/market_liquidity.py::build_liquidity_decision()` checks `high_impact_participation_threshold` before `thin_participation_threshold` — with equal values, anything clearing the thin bar always clears high-impact first, so `analyzer/market_analyzer.py`'s Priority-6 "thin market, simulate instead" gate could never fire for this config. Traced to an unintended side effect of the earlier trade-count-loosening pass (entry #18), which raised `thin_participation_threshold` from `0.002` to `0.01` without also raising `high_impact_participation_threshold`. **Fixed**: `aq config set phase_v2.liquidity.thin_participation_threshold 0.005` — restores `thin < high_impact` (between the original `0.002` and the current `0.01` high-impact value) without undoing most of #18's trade-count-loosening intent.

3. **`main.py::_process_pending_limit_order_timeouts()` contradicted its own dependency's documented contract.** `execution/order_gate.py::classify_order_status()`'s docstring says an unrecognized ("unknown") status must be "treated as still-pending (conservative: never mistakes an unrecognized status for a fill)" — but the caller did `if status != "pending": pop-without-cancel`, which silently abandons tracking of a possibly-still-open order (never calling `ticket.Cancel()`) whenever Lean reports a status name this codebase doesn't yet recognize. Confirmed against the installed Lean stubs (`.venv/Lib/site-packages/QuantConnect/Orders/__init__.pyi`) that real `OrderStatus` has members (`CancelPending`, `None`) `classify_order_status()` would legitimately return `"unknown"` for. Currently dormant (`phase_v2.limit_orders.enabled: false`), part of entry #34's still-unverified surface, but a real latent bug worth fixing now while in context. **Fixed**: the condition is now `if status in ("filled", "canceled"): pop-without-cancel`; everything else (`"pending"` or `"unknown"`) falls through to the existing `ticket.Cancel()` path, matching the documented intent.

4. **`portfolio/book_construction.py::build_rank_based_book()`'s `per_asset_class_slots` parameter had no shape validation** — a malformed entry (e.g. `"equity": [3]`, wrong length) would unpack-crash (`ValueError`) every bar instead of degrading gracefully, this codebase's established convention for every other optional config-driven feature. Currently dormant (the key is absent from `config.json` today). **Fixed**: new pure `portfolio/book_construction.py::normalize_per_asset_class_slots(raw)` — validates each value is a 2-element sequence, returns `(valid_slots, skipped_asset_classes)`; `main.py` now calls it and logs any skipped entries via `self.Debug()` instead of letting them reach `build_rank_based_book()` unvalidated.

**Reviewed, found correct (not new bugs)**: the topology correlation-stability cache's skip-decision logic (entry #36); `gc.freeze()`'s placement in `_ensure_ready()` (entry #37); the per-asset-class book-slot `asset_class` threading from `main.py` into `book_candidates`; `_apply_option_order()`/`_apply_option_spread_order()`'s contract-vs-chain-symbol bookkeeping and spread-leg tuple ordering (entry #38's remaining risk is genuinely Lean-API-casing, not a logic bug found here); no orphaned `phase_v2.*` config keys (every block checked has a corresponding read site with a safe default); `_liquidate_positions_for_disabled_asset_classes()` (entry #35) is confirmed a structural no-op within a single fresh backtest run (its flags are read once at `_ensure_ready()` time, never re-read per bar) — not a gap, matches its own documented intent.

**Testing**: fix #1 verified by direct code inspection (can't be exercised without a real `lean backtest .` run — that's the whole point of this entry). Fix #2 verified via `aq config get`. Fix #3's underlying `classify_order_status()` contract was already fully tested (`tests/test_order_gate.py`, unrecognized strings already correctly return `"unknown"`); the bug was entirely in `main.py`'s caller logic, which — like every other `main.py`-only fix this project has made — can't be unit-tested outside Lean's runtime; verified via direct code review only. Fix #4: 6 new tests for `normalize_per_asset_class_slots()` in `tests/test_portfolio_book_construction.py` (none/empty input, well-formed pass-through, wrong-length skipped, wrong-type skipped, partial validity keeps the good entries). Full suite: `aq test` green after all four fixes.

---

### 40. `aq backtest` silently re-pulled the ~42.5GB Lean engine image on every run — `lean backtest .` resolves the mutable `:latest` tag with no pin
**Severity:** 5/10 · **Status:** 🟢 `fixed`

Found live, the hard way: running `aq backtest` for the first real backtest attempt appeared to hang with no visible progress. Root cause: `lean backtest .` resolves the QuantConnect engine image via the mutable `quantconnect/lean:latest` tag whenever no `--image` is given, and `aq_cli.py::cmd_backtest()` never passed one. Docker Hub's `latest` tag for `quantconnect/lean` gets re-pushed by QuantConnect periodically (confirmed via the Docker Hub API: the locally-cached image was engine build `17900`, but `latest` had already moved to build `17924` by the time this was investigated) — so even a machine with the **entire 42.5GB image already fully cached** re-triggers a real re-pull of whatever layers changed, every single time `latest` moves, with no way to opt out short of pinning explicitly. Had to be killed mid-pull (`lean.exe`/`docker.exe` processes stopped, then Docker Desktop itself restarted to guarantee the daemon-side pull actually stopped — killing just the client processes was not sufficient, the pull continued server-side).

This isn't just a one-machine annoyance: with no pin, **every clone of this repo** re-derives the same problem on its very first `aq backtest` run (unavoidable — everyone needs the ~40GB+ image at least once) and, worse, on **every subsequent run too**, indefinitely, any time QuantConnect happens to move `latest` between runs — an ongoing, avoidable tax on anyone using this repo, not a one-time cost.

**Fixed**: `aq_cli.py` gained `PINNED_LEAN_ENGINE_IMAGE = "quantconnect/lean:17900"` (confirmed to exist as a real, immutable, numbered QuantConnect build tag via the Docker Hub API — QuantConnect publishes these alongside the mutable `latest`) and `cmd_backtest()` now always passes `--image <pinned-or-overridden>` explicitly to `lean backtest .`, never leaving it to resolve `latest` implicitly. New `aq backtest --image <other>` flag lets anyone deliberately opt into a newer engine build without editing code; the pin itself is a one-line constant with an inline comment explaining how to bump it deliberately (`docker pull` the new tag by hand first, confirm it works, then update the constant — never let it drift back to `latest`).

**Documented**: root README's `aq backtest` CLI reference and Getting Started section both now state the pin explicitly and set expectations for the one-time ~40GB+ first download.

**Testing**: `tests/test_aq_cli.py` — `test_backtest_wraps_lean_backtest_dot_with_pinned_image_by_default` (renamed/updated from the old unpinned-invocation test) and new `test_backtest_image_flag_overrides_the_pinned_default`. Full suite: `aq test` green.

---

### 41. First real backtest: only 14 trades, none ever closed — root cause is buy/sell thresholds miscalibrated against the model's actual output distribution
**Severity:** 6/10 (blocks a statistically meaningful backtest) · **Status:** 🟠 `diagnosed, fix not yet applied`

The first real `lean backtest .` (2019-01-01 → 2021-03-31, 29 tradable assets, `bypass_safety_gates: true`) completed successfully but produced only **14 orders, all position-openings, zero closings** (Win Rate / Loss Rate / Avg Win / Avg Loss all 0% because there are no closed round-trips; the +20.36% net profit is entirely unrealized on the 14 still-open positions, mostly bond ETFs). This is far below the ~200-trade target from entry #18 and is not statistically meaningful. Investigated to root cause against the real output files (`visualization/state.json`, order-events, logs):

**Root cause — threshold/output-distribution mismatch, NOT the drawdown traps (those are bypassed) and NOT missing data.** All 29 assets loaded fine (the "38% failed data requests" in the log are only harmless missing crypto `_quote.zip` files; every `_trade.zip` that daily bars actually use loaded successfully). The real mechanism:
- `main.py::_derive_signal()` emits `buy` when `probability_up >= buy_threshold`, `sell` when `probability_up <= sell_threshold`, else `hold`.
- The model's `decision_threshold` is **0.46**, so `buy_threshold = 0.46 + 0.04 = 0.50` and `sell_threshold = 0.46 - 0.04 = 0.42`.
- But the model's actual `probability_up` outputs cluster **very tightly around 0.46-0.49** (measured directly in `state.json`'s final bar: BTCUSD 0.4836, ETHUSD 0.4906, LTCUSD 0.4869, XRPUSD 0.4907, ADAUSD 0.4907 — all `hold`).
- Consequence: the buy line at 0.50 is barely ever reached (only 14 of 29 assets ever crossed it → the rest, including *all* crypto and SPY/QQQ/AAPL, never bought), and the sell line at 0.42 is essentially never reached (so open positions almost never get a `sell`). The 14 that did open then stayed at/above 0.50 for the trending 2019-2021 bond rally and never dropped into the hold-liquidate zone either — hence zero closes.

**The lever (not yet applied — needs user decision):** tighten the offsets so the model's clustered 0.46-0.49 outputs actually produce both buy AND sell crossings — e.g. `phase5.backtest.buy_threshold_offset` 0.04 → ~0.01-0.02 (buy at ~0.47-0.48, more entries) and `sell_threshold_offset` 0.04 → ~0.01-0.02 (sell at ~0.44-0.45, real exits/churn). This directly raises trade count toward the ~200 target. **Deeper caveat, stated honestly:** the tight clustering of `probability_up` around 0.46-0.49 means the model itself has weak signal separation / low conviction — tightening thresholds buys more trades but on thinner edge; it does not fix underlying model quality, only makes the backtest statistically exercisable. A genuinely better fix long-term is improving the model's probability calibration/separation, but that is out of scope for "get enough trades to have a meaningful backtest."

**Secondary finding — `max_active_positions` is a soft cap.** The run held 14 concurrent positions despite `phase9.portfolio.max_active_positions: 12`. `main.py::_active_position_count()` counts only *already-filled* `Portfolio.Values` positions, and Lean fills submitted orders on the next bar's open — so when several symbols cross the buy line on the same bar, each sees the same pre-fill count (< 12) and all submit, overshooting the cap by however many simultaneous buys land that bar. Not a crash and not a large effect, but the cap is "soft" (can overshoot within one bar), not hard. Documented here; no fix applied (a hard cap would need to also count same-bar pending orders).

**No code changed yet** — this entry is the diagnosis. The threshold-calibration change is a strategy-behavior decision left to the user (which offsets, whether to also revisit the model), consistent with this project's convention of not silently changing trading behavior.

### 42. Pre-live security review — broker/API credentials could be published via `lean.json` or baked into the Docker image; DB exposed to the LAN behind a repo-published password
**Severity:** 7/10 · **Status:** 🟢 `fixed` (one item deliberately deferred, see below)

A dedicated security pass requested before any live-capital / multi-asset-class
(V3) step, on the reasoning that credential handling, broker API-key storage and
audit logging all matter far more once real money is in play. **No secret was
ever actually leaked** — every finding below was prospective, caught before the
first real credential existed. Findings, in severity order:

**1. `lean.json` credentials would have been committed (the main one).**
`lean.json` is tracked in git deliberately — everyone who clones needs the
working config structure. It ships as the stock Lean template with every
brokerage/API secret field empty (`ib-password`, `polygon-api-key`, all the
`*-api-secret`, …). But this file's own V2-22 runbook (`infrastructure.md`)
instructed hand-editing **real IB credentials directly into it** — one `git add`
away from publishing a live broker password to a public repo. The obvious fix
("use `${ENV_VAR}` in the field") **does not work**: Lean does not expand
environment variables inside `lean.json` — verified directly against the Lean
CLI's own `components/config/lean_config_manager.py`, which reads every value
literally, so the literal string `${ENV_VAR}` would be handed to the brokerage.
Fixed with a **render step** instead: `execution/lean_config_render.py` +
`scripts/render_lean_credentials.py` (`aq render-lean-config`) overlay the
`AETHER_*` values from the gitignored `.env.live` onto the empty tracked
template and write a **gitignored `lean.live.json`**; live/paper deploys point
Lean at that via `--lean-config`. The tracked `lean.json` stays all-empty and
shareable. Only field *names* are ever printed, never values. `aq backtest` is
untouched — backtests need no credentials and keep using the plain `lean.json`.

**2. Secrets would have been baked into the published Docker image.** The
Docker consolidation (see Changelog, same date) made the engine image
`COPY . .` the whole source tree, and that same fat image is what gets published
to ghcr. `.dockerignore` excluded `.venv/`/`data/`/… but **not** `lean.json`,
`.env*`, or `ib_config.py` — so a locally-populated credential file would have
been baked permanently into a public registry image layer, extractable via
`docker history`/`docker save` even if a later commit removed it. Note
`.gitignore` does not protect against this: it is a *separate* mechanism, and
`lean.json` is git-tracked anyway. Fixed by mirroring the secret list into
`.dockerignore`. **The verification pass then caught a second instance of this
exact bug in the fix itself**: `lean.live.json` — the rendered file that holds
the *real* credentials — was gitignored but not dockerignored, so
`aq render-lean-config` followed by `aq docker build` would have embedded a live
broker password in the published image. Now excluded and pinned by
`tests/test_dockerignore_secrets.py`, which evaluates real Docker pattern
semantics (a literal line-grep misses this class: `.env.*` covers `.env.live`
without an exact line) and cross-checks that no secret filename in
`.gitignore`'s block is missing from `.dockerignore`.

**3. Postgres was reachable from the LAN behind a password published in this
repo.** `docker-compose.yml` published `${POSTGRES_PORT:-5433}:5432`, and Docker
publishes to `0.0.0.0` by default — so on any untrusted network (café/hotel
wifi) another device could reach the DB and authenticate with
`aether_dev_password`, which is in the public repo and therefore not a password
at all. Fixed by binding the published DB/Redis ports to `127.0.0.1` (host-only;
the internal `redis:6379`/`postgres:5432` container paths are unaffected), plus
a **fail-closed live guard**: `execution/live_credentials.py::postgres_dsn_is_live_safe()`
refuses live mode while the DSN still carries the default password (or is
unset), surfaced through `evaluate_live_broker_config()` as
`live_broker_config_unsafe_db_password`. Local dev/backtest behavior is
unchanged.

**4. Nothing structurally prevented a future secret commit.** Added
`aq secrets-check` (`execution/secret_scan.py`) — fails if `lean.json` has a
populated secret-looking field or a real (non-`*.example`) `.env` is tracked —
and an opt-in `.githooks/pre-commit` that runs it (`git config core.hooksPath
.githooks`, documented in `infrastructure.md`/`README.md`). No new dependency,
works on Windows.

**Checked and found clean, no action needed:** no deserialization-RCE surface
(no `torch.load`/`pickle.load`/`joblib.load` anywhere — models load from plain
JSON `ml/model_weights.json`/`ml/scaler_stats.json`); the FastAPI monitoring
server is read-only/GET-only with CORS restricted to localhost and serves no
secrets; Telegram bot token/chat id were already env-var-only and never in
`config.json`; no secret exists in git history (every `lean.json` secret field
has always been empty).

**Deliberately deferred — 🟡 `pending`: no dedicated audit logging.** Order
placement, credential loads and live-mode transitions currently go through
ordinary application logging, not a tamper-evident audit trail. Acceptable for
backtest/paper; **should be built before real capital**. Larger scope than this
pass and flagged for its own review as V3 approaches — this is the one known
open security item.
