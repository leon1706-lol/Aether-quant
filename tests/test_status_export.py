"""Tests for retraining.status_export — V2-17.

Conventions: no test classes, module-level helpers, MagicMock injection for
the psycopg3 connection and monkeypatched fetch_* helpers so this stays a
pure unit test of build_status_view()'s shaping logic.
"""

import json
from unittest.mock import patch

from retraining.status_export import build_status_view, write_status_file


def test_build_status_view_shape_with_no_data(tmp_path):
    with patch("retraining.status_export.fetch_active_model_version", return_value=None), patch(
        "retraining.status_export.fetch_latest_candidate_version", return_value=None
    ), patch("retraining.status_export.fetch_latest_trigger", return_value=None), patch(
        "retraining.status_export.fetch_latest_retraining_event", return_value=None
    ), patch("retraining.status_export.fetch_rollback_candidates", return_value=[]):
        status = build_status_view(conn=None)

    assert status["active_model"] is None
    assert status["latest_candidate"] is None
    assert status["last_trigger"] is None
    assert status["latest_retraining_event"] is None
    assert status["validation_status"] == "none"
    assert status["rollback_available"] is False
    assert status["rollback_candidates"] == []


def test_build_status_view_reflects_active_and_candidate():
    active = {"model_version_id": "v1", "status": "active", "created_at": "2026-07-02T12:00:00+00:00", "metrics": {}, "aether_vault_commit": "abc123"}
    candidate = {"model_version_id": "v2", "status": "candidate", "created_at": "2026-07-02T13:00:00+00:00", "metrics": {}, "aether_vault_commit": None}
    event = {"retraining_id": "e1", "status": "validated", "created_at": "2026-07-02T13:00:00+00:00", "reason": "ok", "source_trigger_id": None, "candidate_version_id": "v2"}

    with patch("retraining.status_export.fetch_active_model_version", return_value=active), patch(
        "retraining.status_export.fetch_latest_candidate_version", return_value=candidate
    ), patch("retraining.status_export.fetch_latest_trigger", return_value=None), patch(
        "retraining.status_export.fetch_latest_retraining_event", return_value=event
    ), patch("retraining.status_export.fetch_rollback_candidates", return_value=[]):
        status = build_status_view(conn=None)

    assert status["active_model"]["model_version_id"] == "v1"
    assert status["latest_candidate"]["model_version_id"] == "v2"
    assert status["validation_status"] == "validated"


def test_build_status_view_rollback_available_when_candidates_exist():
    rollback_candidates = [{"model_version_id": "v0", "created_at": "2026-07-01T12:00:00+00:00", "status": "archived"}]

    with patch("retraining.status_export.fetch_active_model_version", return_value=None), patch(
        "retraining.status_export.fetch_latest_candidate_version", return_value=None
    ), patch("retraining.status_export.fetch_latest_trigger", return_value=None), patch(
        "retraining.status_export.fetch_latest_retraining_event", return_value=None
    ), patch("retraining.status_export.fetch_rollback_candidates", return_value=rollback_candidates):
        status = build_status_view(conn=None)

    assert status["rollback_available"] is True
    assert status["rollback_candidates"] == [{"model_version_id": "v0", "created_at": "2026-07-01T12:00:00+00:00"}]


def test_write_status_file_writes_valid_json(tmp_path):
    path = tmp_path / "grafana" / "retraining_status.json"

    write_status_file({"active_model": None}, path=path)

    assert json.loads(path.read_text(encoding="utf-8")) == {"active_model": None}
