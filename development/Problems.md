# Problems

Bugs and infrastructure issues found in this codebase, how they were fixed
(or why they're still open), a severity rating (1 = cosmetic, 10 = critical
data-loss/safety issue), and a status tag. Newest first.

---

### 1. `experience-worker` crash loop — missing `numpy` dependency
**Severity:** 6/10 · **Status:** `fixed`

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
**Severity:** 6/10 · **Status:** `fixed`

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
**Severity:** 5/10 · **Status:** `fixed`

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
**Severity:** 2/10 · **Status:** `fixed`

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
**Severity:** 2/10 · **Status:** `fixed`

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
**Severity:** 3/10 · **Status:** `open`

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

**Fix (not yet applied — awaiting user confirmation):** `docker rm
aether-grafana` to free the name, then `docker compose up -d grafana` will
create the compose-managed one correctly.

---

### 7. ~85GB of orphaned duplicate Lean engine images + stale containers/volumes
**Severity:** 2/10 · **Status:** `open`

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

**Fix (not yet applied — awaiting user confirmation, purely disk-space
hygiene, no functional impact):**
```powershell
docker rm quizzical_maxwell loving_antonelli
docker rmi 650dd8d4063a cb13534ee02c aether-quant:latest redis:latest postgres:latest
docker volume rm lean_cli_python_9c2708201519fa8d08977929a7584533 lean_cli_python_09fe6a52b86d1b5481d303363de59d1a lean_cli_python_2247f36d850e433c9582ac3514c5c1bb lean_cli_python_d4b32878b8dc1a8af8ccd4d44ced374a
```

---

### 8. Bare `pytest` (no path) fails from repo root
**Severity:** 3/10 · **Status:** `open`

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
