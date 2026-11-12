"""The dashboard's demo data and AQ_DASHBOARD_ROOT (V6.6.5, #344): a rebuild reproduces the tracked files, and with the
API pointed at them every GET route answers with content."""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "monitoring" / "demo"


def test_a_rebuild_reproduces_the_tracked_demo_files(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_dashboard_demo.py"), "--out", str(tmp_path)], capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stderr[-3000:]
    built = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file())
    tracked = sorted(path.relative_to(DEMO).as_posix() for path in DEMO.rglob("*") if path.is_file())
    assert built == tracked
    for relative in built:
        assert (tmp_path / relative).read_bytes() == (DEMO / relative).read_bytes(), f"{relative}: run python scripts/build_dashboard_demo.py"
    assert sum((DEMO / relative).stat().st_size for relative in tracked) < 500_000


@pytest.fixture
def demo_api(monkeypatch):
    monkeypatch.setenv("AQ_DASHBOARD_ROOT", str(DEMO))
    monkeypatch.setenv("AQ_DASHBOARD_DEMO", "1")
    import monitoring.api_server as api_server

    module = importlib.reload(api_server)
    yield module
    monkeypatch.delenv("AQ_DASHBOARD_ROOT")
    monkeypatch.delenv("AQ_DASHBOARD_DEMO")
    importlib.reload(api_server)


def test_every_get_route_answers_from_the_demo(demo_api, monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AQ_USERS_FILE", str(tmp_path / "no_users.json"))
    monkeypatch.delenv("AQ_AUTH", raising=False)
    client = TestClient(demo_api.app)
    assert client.get("/api/health").json() == {"status": "ok", "demo": True, "auth": "off"}
    routes = [route.path for route in demo_api.app.routes if getattr(route, "methods", None) and "GET" in route.methods and route.path.startswith("/api/")]
    assert len(routes) >= 18
    for path in routes:
        if "{" in path:
            continue
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code, response.text[:200])
        assert response.json(), path
    state = client.get("/api/state").json()
    assert state["mode"] == "demo" and state["observation"]["visually_distinct_banner"].startswith("DEMO DATA")
    assert state["paper_readiness"]["ready"] is False
    assert len(client.get("/api/grafana/equity-curves").json()) > 100
    assert client.post("/api/accounts/default/trade-lock", json={"locked": True}).status_code == 403  # the demo changes nothing


def test_without_the_variable_the_paths_are_the_repos_own():
    import monitoring.api_server as api_server

    module = importlib.reload(api_server)
    assert module.DATA_ROOT == module.ROOT_DIR.resolve() and not module.CUSTOM_ROOT and module.VISUALIZATION_DIR == module.DATA_ROOT / "visualization"
