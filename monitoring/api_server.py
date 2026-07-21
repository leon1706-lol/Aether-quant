"""FastAPI server exposing Aether Quant runtime visualization state as a JSON API.

Reads the same files the legacy HTML dashboards read (visualization/state.json,
visualization/scene.json, visualization/grafana/*) and serves them over HTTP so
the React webui (localhost:3000/3002) can consume them instead of fetching files
directly off disk. No new computation happens here - this is a read-only
reshape/serve layer over the existing runtime exports.
"""

import csv
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
# StaticFiles raises Starlette's HTTPException, of which fastapi's is a
# *subclass* - catching the fastapi one would miss it entirely.
from starlette.exceptions import HTTPException as StarletteHTTPException

from monitoring.assets_status import build_assets_status_from_disk
from monitoring.neural_network_state import build_neural_network_state

ROOT_DIR = Path(__file__).resolve().parent.parent
VISUALIZATION_DIR = ROOT_DIR / "visualization"
GRAFANA_DIR = VISUALIZATION_DIR / "grafana"
WEBUI_DIST = ROOT_DIR / "webui" / "dist"

app = FastAPI(title="Aether Quant Monitoring API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3002",
        "http://localhost:8000",
        "http://localhost:8001",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} not found")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_csv_as_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} not found")
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/state")
def get_state() -> dict:
    state = _read_json(VISUALIZATION_DIR / "state.json")
    retraining_status_path = GRAFANA_DIR / "retraining_status.json"
    if retraining_status_path.exists():
        with retraining_status_path.open("r", encoding="utf-8") as f:
            state["retraining_status"] = json.load(f)
    paper_readiness_path = GRAFANA_DIR / "paper_readiness_report.json"
    if paper_readiness_path.exists():
        with paper_readiness_path.open("r", encoding="utf-8") as f:
            state["paper_readiness"] = json.load(f)
    return state


@app.get("/api/scene")
def get_scene() -> dict:
    return _read_json(VISUALIZATION_DIR / "scene.json")


@app.get("/api/topology")
def get_topology() -> dict:
    return _read_json(VISUALIZATION_DIR / "topology_state.json")


@app.get("/api/neural-network")
def get_neural_network() -> dict:
    return build_neural_network_state()


@app.get("/api/assets-status")
def get_assets_status() -> dict:
    return build_assets_status_from_disk()


@app.get("/api/grafana/metrics-snapshot")
def get_metrics_snapshot() -> dict:
    return _read_json(GRAFANA_DIR / "runtime_metrics_snapshot.json")


@app.get("/api/grafana/equity-curves")
def get_equity_curves() -> list[dict]:
    return _read_csv_as_rows(GRAFANA_DIR / "equity_curves.csv")


@app.get("/api/grafana/asset-performance")
def get_asset_performance() -> list[dict]:
    return _read_csv_as_rows(GRAFANA_DIR / "asset_performance.csv")


@app.get("/api/grafana/observation-summary")
def get_observation_summary() -> dict:
    return _read_json(GRAFANA_DIR / "observation_summary.json")


@app.get("/api/grafana/observation-equity-curve")
def get_observation_equity_curve() -> list[dict]:
    return _read_csv_as_rows(GRAFANA_DIR / "observation_equity_curve.csv")


@app.get("/api/grafana/performance-triggers")
def get_performance_triggers() -> dict:
    return _read_json(GRAFANA_DIR / "performance_triggers.json")


@app.get("/api/grafana/retraining-status")
def get_retraining_status() -> dict:
    return _read_json(GRAFANA_DIR / "retraining_status.json")


@app.get("/api/audit-log")
def get_audit_log() -> dict:
    """Reads visualization/grafana/audit_log.json - written by
    audit/postgres_worker.py after every batch it persists (development/
    Problems.md #42). Same "main.py can't reach Postgres, so a worker
    exports a JSON snapshot" pattern as /api/grafana/retraining-status
    (see retraining/status_export.py's docstring)."""
    return _read_json(GRAFANA_DIR / "audit_log.json")


@app.get("/api/grafana/paper-readiness")
def get_paper_readiness() -> dict:
    return _read_json(GRAFANA_DIR / "paper_readiness_report.json")


class SpaStaticFiles(StaticFiles):
    """Serves the built webui with a client-side-routing fallback.

    `StaticFiles(html=True)` alone only maps *directory* paths to
    index.html - an unknown path like /risk or /operations still 404s. The
    React router owns those paths, so every tab except / broke on a direct
    load or hard refresh whenever the SPA was served from here (the Docker
    image and any bare-uvicorn run; the vite dev server has its own
    fallback, which is why this never showed up in local development).

    Only extensionless paths fall back. A missing /assets/*.js must keep
    404ing rather than silently returning index.html, which would turn a
    broken build into a blank page with no error.
    """

    async def get_response(self, path: str, scope):
        # Starlette signals a missing file by *raising* HTTPException(404),
        # not by returning a 404 response - catching is the only way to
        # intercept it.
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not Path(path).suffix:
                return await super().get_response("index.html", scope)
            raise


# Mounted last on purpose: "/" is a catch-all, so any route registered
# below it would be shadowed by the SPA.
if WEBUI_DIST.exists():
    app.mount("/", SpaStaticFiles(directory=WEBUI_DIST, html=True), name="static")
