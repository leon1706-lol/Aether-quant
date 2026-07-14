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

### 10. `ci.yml`'s `test` job fails on GitHub's Linux runner — root cause still unknown
**Severity:** 3/10 · **Status:** 🟠 `open`

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
3. **Still open** — after both fixes above, dependency install and test
   *collection* both succeed in CI, but the actual `pytest` run itself still
   fails (`exit code 1`) on GitHub's `ubuntu-latest` + Python 3.11 runner.
   All 488 tests pass cleanly and repeatedly on the local Windows + Python
   3.14 dev environment (`.venv/Scripts/pytest.exe`, the exact same bare
   invocation style as CI). Root cause not yet identified.
   - Confirmed via the public unauthenticated GitHub API
     (`GET /repos/leon1706-lol/Aether-quant/actions/runs/<id>/jobs`) that the
     `test` job's "Run tests" step is specifically what fails — every other
     step (checkout, setup-python, install dependencies) succeeds. The raw
     log itself (`GET /actions/jobs/<id>/logs`) returns HTTP 403 without an
     authenticated token, confirmed directly; an unauthenticated web-page
     fetch of the job's Actions UI also only shows the same generic "1
     error" annotation, not the pytest traceback.
   - Attempted a local repro during V2-21/V2-22 planning
     (2026-07-04/05): `docker run --rm -v <repo>:/repo -w /repo
     python:3.11-slim bash -c "pip install -r requirements/requirements.txt
     -r requirements/requirements-dev.txt && pytest"`, to match CI's exact
     OS/Python combination without needing `gh` auth. **Inconclusive** — the
     container made effectively zero installation progress after 30+
     minutes (still only base `pip`/`setuptools`/`wheel`, none of this
     repo's dependencies), and a direct network check from inside the
     container timed a single PyPI simple-index fetch (`pypi.org/simple/torch/`)
     at ~10.5 seconds. This points to severe network-bandwidth/latency
     constraints in the local sandbox this session ran in, not a
     dependency-resolution bug — the repro was stopped rather than left
     running indefinitely. Worth retrying from an environment with normal
     PyPI throughput before concluding anything from it either way.
   - **Next step, still open:** either (a) retry the same Docker repro
     command above from a machine/network with normal PyPI download speeds,
     or (b) install/authenticate the `gh` CLI (`winget install GitHub.cli`,
     then `gh auth login`) and run `gh run view <run-id> --log --job <job-id>`
     to get the actual pytest failure text — this remains the fastest path
     if (a) isn't convenient. Suspected root causes, unchanged from before:
     a Linux BLAS numeric-precision difference affecting a sklearn/topology
     test, or a Python 3.11-vs-3.14 stdlib behavior difference.

**Not currently blocking releases**: `release.yml`'s `publish-pypi`/
`publish-docker` jobs no longer depend on a test job at all (removed at the
user's explicit request, in favor of testing locally before tagging) — see
`v2_architecture.md`/git history around the `v0.2.0` release. `ci.yml`'s
`test` job still runs (and still fails) on every push/PR to `main`, so it
remains a visible red check, just not a release gate.

**Next step, when revisited:** grab the actual failing test's output from
the Actions UI (expand the "Run tests" step) or via `gh run view --log
--job <id>` with an authenticated `gh` CLI, since likely candidates
(platform-specific path/locale assumptions, a numeric-precision difference
in a Linux BLAS backend affecting one of the sklearn/topology tests, a
Python 3.11-vs-3.14 stdlib behavior difference) can't be distinguished
without the real error text.

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

### 21. Per-bar model forward-pass count doubled (5 → 11) — not yet a measured problem
**Severity:** 2/10 · **Status:** 🟡 `documented, not measured`

The multitask/sequence pass added 6 more optional model forward passes per
symbol per bar on top of the original 5 (baseline + 4 experts):
`baseline_multitask`, 4 `expert_multitask` heads, and the Phase 2
`sequence` encoder — all still `inference/exported_model.py`'s plain-numpy
interpreters (`run_exported_multitask_model()`/
`run_exported_sequence_multitask_model()`), no batching across the 11
calls, no shared computation between a flat model and its multitask
sibling (e.g. `baseline` and `baseline_multitask` each run their own
independent forward pass over the same 48-dim input, rather than one
model with two exit points).

**Not independently measured this pass** — no `lean backtest .` timing run
was taken, deliberately, for two reasons: (1) both new model families are
either informational-only (`sequence`, per the Phase 2 Sequence Encoder
Contract) or feed only a config-gated, off-by-default optional path
(`predicted_volatility` → `risk/position_sizing.py`,
`phase_v2.dynamic_risk.use_predicted_volatility`) — nothing yet trades on
their output by default, so there is no live-decision urgency to profile
them; (2) the only hard, actually-enforced latency constraint anywhere in
this codebase is Lean's 90-second `initialize()` isolator timeout
(entry #16), which is unrelated to per-bar `on_data()` cost — there is no
established per-bar time budget to compare against.

**If this ever becomes a real observed problem** (e.g. `initialize()`
timing regresses, or a full backtest's wall-clock time becomes a practical
obstacle to iteration speed), the method this codebase already uses is a
real `lean backtest .` run plus temporary side-channel disk logging (never
a persisted timer/profiler class) — see entries #16 and #17 for the exact
pattern and precedent before building anything new.

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
**Severity:** n/a (scope note, not a bug) · **Status:** 🟡 `deferred` (narrowed — see resolved items below)

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

Still deliberately out of scope:

- **Automatic multi-leg options spread selection via ML** (verticals,
  straddles, iron condors). `portfolio/options_strategy.py` is single-leg
  only (long calls or long puts, greeks-sized via a target delta scaled by
  the existing direction+confidence prediction) — a genuinely new spread-
  selection model architecture is future work.
- **IBC-based headless/automated TWS/Gateway login.** IB's API requires an
  already-logged-in TWS/Gateway session; `data_pipeline/ib_backfill.py`
  connects to that session but does not manage its login lifecycle. The
  live connection itself has also never been tested against a real
  Gateway — everything is verified via unit tests and Lean's own type
  stubs only.
- **Per-asset-class top-N/bottom-N book-slot caps.**
  `portfolio/book_construction.py::build_rank_based_book()` ships with one
  combined-universe ranking across all enabled asset classes, not a slot
  budget per class.
- **Live IB margin replacing `data/reference/futures_contract_specs.json`'s**
  static reference numbers. The static file is the sizing source of truth
  even when IB is connected; live margin queries are a documented future
  enhancement.
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
**Severity:** n/a (optimization pass) · **Status:** 🟢 `fixed` (weight caching, harness, `aq profile`, multiprocessing) / 🟡 in progress (C++ extension - toolchain install + compile checkpoint, see below)

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
