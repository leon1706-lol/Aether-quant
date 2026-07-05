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
