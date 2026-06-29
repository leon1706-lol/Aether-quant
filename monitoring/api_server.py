"""FastAPI server exposing Aether Quant runtime visualization state as a JSON API.

Reads the same files the legacy HTML dashboards read (visualization/state.json,
visualization/scene.json, visualization/grafana/*) and serves them over HTTP so
the React webui (localhost:3000) can consume them instead of fetching files
directly off disk. No new computation happens here - this is a read-only
reshape/serve layer over the existing runtime exports.
"""

import csv
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parent.parent
VISUALIZATION_DIR = ROOT_DIR / "visualization"
GRAFANA_DIR = VISUALIZATION_DIR / "grafana"

app = FastAPI(title="Aether Quant Monitoring API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
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
    return _read_json(VISUALIZATION_DIR / "state.json")


@app.get("/api/scene")
def get_scene() -> dict:
    return _read_json(VISUALIZATION_DIR / "scene.json")


@app.get("/api/grafana/metrics-snapshot")
def get_metrics_snapshot() -> dict:
    return _read_json(GRAFANA_DIR / "runtime_metrics_snapshot.json")


@app.get("/api/grafana/equity-curves")
def get_equity_curves() -> list[dict]:
    return _read_csv_as_rows(GRAFANA_DIR / "equity_curves.csv")


@app.get("/api/grafana/asset-performance")
def get_asset_performance() -> list[dict]:
    return _read_csv_as_rows(GRAFANA_DIR / "asset_performance.csv")
