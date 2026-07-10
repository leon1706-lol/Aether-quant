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
