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
