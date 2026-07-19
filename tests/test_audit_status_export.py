"""Tests for audit.status_export — the webui/API dashboard snapshot writer
(development/Problems.md #42). Mirrors tests/test_retraining_orchestrator.py's
mocked-cursor conventions for build_audit_status_view(); write_status_file()
is tested against a real tmp_path (no I/O to mock).
"""

import json
from unittest.mock import patch

from audit.status_export import build_audit_status_view, write_status_file


def _sample_event(event_id="id-1"):
    return {
        "event_id": event_id,
        "created_at": "2026-07-18T00:00:00Z",
        "event_type": "order_placement",
        "actor": "system",
        "prev_hash": "0" * 64,
        "hash": "a" * 64,
        "payload": {"symbol": "AAPL"},
    }


def test_build_audit_status_view_reports_valid_chain():
    with patch("audit.status_export.fetch_recent_events", return_value=[_sample_event()]), \
         patch("audit.status_export.fetch_all_events_ordered", return_value=[_sample_event()]), \
         patch("audit.status_export.verify_chain", return_value=(True, None)):
        view = build_audit_status_view(conn=object())

    assert view["chain_valid"] is True
    assert view["chain_broken_at_event_id"] is None
    assert view["total_entries"] == 1
    assert len(view["recent_events"]) == 1
    assert "generated_at" in view


def test_build_audit_status_view_reports_broken_chain_with_event_id():
    events = [_sample_event("id-1"), _sample_event("id-2")]
    with patch("audit.status_export.fetch_recent_events", return_value=events), \
         patch("audit.status_export.fetch_all_events_ordered", return_value=events), \
         patch("audit.status_export.verify_chain", return_value=(False, 1)):
        view = build_audit_status_view(conn=object())

    assert view["chain_valid"] is False
    assert view["chain_broken_at_event_id"] == "id-2"


def test_build_audit_status_view_empty_table():
    with patch("audit.status_export.fetch_recent_events", return_value=[]), \
         patch("audit.status_export.fetch_all_events_ordered", return_value=[]), \
         patch("audit.status_export.verify_chain", return_value=(True, None)):
        view = build_audit_status_view(conn=object())

    assert view["total_entries"] == 0
    assert view["recent_events"] == []


def test_write_status_file_writes_valid_json(tmp_path):
    path = tmp_path / "nested" / "audit_log.json"
    status = {"generated_at": "2026-07-18T00:00:00Z", "total_entries": 0, "chain_valid": True, "recent_events": []}

    write_status_file(status, path=path)

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == status
