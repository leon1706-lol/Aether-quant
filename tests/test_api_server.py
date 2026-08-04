"""Tests for monitoring/api_server.py's /api/audit-log route (development/
Problems.md #42). Calls the FastAPI route function directly (no httpx/
TestClient dependency, matching this repo's convention of keeping the API
layer as thin, directly-callable functions over already-tested build/read
helpers - see tests/test_assets_status.py and tests/test_neural_network_state.py,
which test the underlying build functions the same way).
"""

import json

import pytest
from fastapi import HTTPException

import monitoring.api_server as api_server
import monitoring.evaluation_state as evaluation_state


def test_get_audit_log_reads_grafana_dir_file(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "GRAFANA_DIR", tmp_path)
    payload = {
        "generated_at": "2026-07-18T00:00:00Z",
        "total_entries": 2,
        "chain_valid": True,
        "chain_broken_at_event_id": None,
        "recent_events": [{"event_id": "id-1", "event_type": "order_placement"}],
    }
    (tmp_path / "audit_log.json").write_text(json.dumps(payload), encoding="utf-8")

    result = api_server.get_audit_log()

    assert result == payload


def test_get_audit_log_404s_when_export_not_written_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "GRAFANA_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        api_server.get_audit_log()

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# /api/state + /api/grafana/retraining-status - V5.1 Phase 6 (production
# safety) passthrough of kill_switch/reconciliation (written into
# state.json by main.py's own Phase 6 wiring) and auto_rollback (written
# into retraining_status.json by retraining/status_export.py's own Phase 6
# wiring). Both routes are thin JSON-file readers with no route-level
# shaping, so this is a regression guard that neither route's own file
# read silently drops or reshapes these new top-level keys, not a test of
# the underlying build logic (already covered by test_status_export.py).
# ---------------------------------------------------------------------------


def test_get_state_passes_through_kill_switch_and_reconciliation(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "VISUALIZATION_DIR", tmp_path)
    monkeypatch.setattr(api_server, "GRAFANA_DIR", tmp_path / "grafana")
    state_payload = {
        "project": "Aether Quant",
        "kill_switch": {"tripped": True, "severity": "critical", "triggers": ["rolling_sharpe_below_floor"]},
        "reconciliation": {"status": "not_applicable", "reason": "portfolio_book_neutrality_or_reconciliation_disabled"},
    }
    (tmp_path / "state.json").write_text(json.dumps(state_payload), encoding="utf-8")

    result = api_server.get_state()

    assert result["kill_switch"]["tripped"] is True
    assert result["kill_switch"]["triggers"] == ["rolling_sharpe_below_floor"]
    assert result["reconciliation"]["status"] == "not_applicable"


def test_get_retraining_status_passes_through_auto_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "GRAFANA_DIR", tmp_path)
    payload = {
        "active_model": None,
        "auto_rollback": {
            "config": {"enabled": True},
            "degradation_signals": {"kill_switch_tripped": False},
            "decision": {"should_rollback": False, "reason": "no_configured_trigger_fired"},
        },
    }
    (tmp_path / "retraining_status.json").write_text(json.dumps(payload), encoding="utf-8")

    result = api_server.get_retraining_status()

    assert result["auto_rollback"]["decision"]["reason"] == "no_configured_trigger_fired"
    assert result["auto_rollback"]["config"]["enabled"] is True


# ---------------------------------------------------------------------------
# SpaStaticFiles - client-side-routing fallback (found during V4-W1 manual
# verification: every webui tab except / 404'd on a direct load or hard
# refresh whenever the SPA was served from FastAPI, i.e. the Docker image
# and any bare-uvicorn run. `StaticFiles(html=True)` only maps *directory*
# paths to index.html; it is not a catch-all. The vite dev server has its
# own fallback, which is why local development never surfaced this.)
#
# Driven through the ASGI app rather than by calling a route function,
# because the behavior under test lives in the mount, not in a route.
# ---------------------------------------------------------------------------


def _get(path: str):
    """Minimal ASGI GET driver - keeps this file's no-TestClient/no-httpx
    convention (see this module's docstring) while still exercising the
    real mount."""
    import asyncio

    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(api_server.app(scope, receive, send))
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    return status


@pytest.mark.skipif(not api_server.WEBUI_DIST.exists(), reason="webui/dist not built")
@pytest.mark.parametrize("route", ["/", "/operations", "/risk", "/topology", "/neural-network", "/tracing"])
def test_client_side_routes_serve_the_spa_shell(route):
    """Every React-router-owned tab must resolve on a direct load, not just
    when navigated to from within the app."""
    assert _get(route) == 200


@pytest.mark.skipif(not api_server.WEBUI_DIST.exists(), reason="webui/dist not built")
def test_missing_asset_still_404s_rather_than_returning_index_html():
    """The fallback is deliberately limited to extensionless paths. Serving
    index.html for a missing bundle would turn a broken build into a blank
    page with no error to trace."""
    assert _get("/assets/does-not-exist.js") == 404


@pytest.mark.skipif(not api_server.WEBUI_DIST.exists(), reason="webui/dist not built")
def test_api_routes_are_not_shadowed_by_the_spa_catch_all(tmp_path, monkeypatch):
    """The mount is registered last precisely so /api/* wins. The 404 here
    (rather than the SPA fallback's 200) is what proves the API layer still
    owns its namespace even for a missing export. GRAFANA_DIR is pointed at
    an empty tmp_path so this does not depend on whether the real
    audit_log.json happens to exist on this machine."""
    monkeypatch.setattr(api_server, "GRAFANA_DIR", tmp_path)

    assert _get("/api/health") == 200
    assert _get("/api/audit-log") == 404


def test_get_evaluation_delegates_to_build_evaluation_state(tmp_path, monkeypatch):
    """V5.1 Phase 0: /api/evaluation is a thin delegate to
    monitoring/evaluation_state.py::build_evaluation_state() - the actual
    not_evaluated/section-shape logic is tested in
    tests/test_evaluation_state.py, mirroring test_neural_network_state.py's
    own split (build_* logic tested standalone, the route only tested for
    correct delegation + the SPA-shadowing contract above)."""
    monkeypatch.setattr(evaluation_state, "DEFAULT_ML_DIR", tmp_path)

    result = api_server.get_evaluation()

    assert result["rank_book"]["status"] == "not_evaluated"
    assert result["capacity"]["status"] == "not_evaluated"
    assert result["stress"]["status"] == "not_evaluated"
    assert result["ablation"]["status"] == "not_evaluated"
    assert result["walk_forward"]["status"] == "not_evaluated"
