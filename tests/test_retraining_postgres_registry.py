"""Tests for retraining.postgres_registry — V2-17.

Conventions: no test classes, module-level helpers, MagicMock injection for
the psycopg3 connection/cursor (mirrors tests/test_postgres_triggers.py).
"""

from unittest.mock import MagicMock

from retraining.postgres_registry import (
    count_experience_events,
    ensure_schema,
    fetch_active_model_version,
    fetch_model_version,
    fetch_recent_retraining_events,
    fetch_rollback_candidates,
    fetch_stale_active_events,
    insert_model_version,
    insert_retraining_event,
    model_version_to_row,
    promote_model_version,
    retraining_event_to_row,
    update_model_version_status,
    update_retraining_event_status,
)


def _sample_version(**overrides) -> dict:
    defaults = {
        "model_version_id": "00000000-0000-0000-0000-0000000000aa",
        "status": "candidate",
        "metrics": {"sharpe": 1.2},
    }
    defaults.update(overrides)
    return defaults


def _sample_event(**overrides) -> dict:
    defaults = {
        "retraining_id": "00000000-0000-0000-0000-0000000000bb",
        "source_trigger_id": "00000000-0000-0000-0000-0000000000cc",
        "reason": "eligible_candidate_trigger_selected",
    }
    defaults.update(overrides)
    return defaults


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def test_model_version_to_row_extracts_fields():
    row = model_version_to_row(_sample_version())

    assert row["model_version_id"] == "00000000-0000-0000-0000-0000000000aa"
    assert row["status"] == "candidate"
    assert '"sharpe": 1.2' in row["metrics"]


def test_retraining_event_to_row_extracts_fields():
    row = retraining_event_to_row(_sample_event())

    assert row["retraining_id"] == "00000000-0000-0000-0000-0000000000bb"
    assert row["status"] == "planned"
    assert row["reason"] == "eligible_candidate_trigger_selected"


def test_ensure_schema_creates_both_tables_and_indexes():
    conn_mock, cur_mock = _make_conn_mock()

    ensure_schema(conn_mock)

    executed_sql = [call.args[0] for call in cur_mock.execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS model_versions" in sql for sql in executed_sql)
    assert any("CREATE TABLE IF NOT EXISTS retraining_events" in sql for sql in executed_sql)
    assert any("ux_model_versions_single_active" in sql for sql in executed_sql)
    conn_mock.commit.assert_called_once()


def test_insert_model_version_executes_insert():
    conn_mock, cur_mock = _make_conn_mock()

    insert_model_version(conn_mock, _sample_version())

    insert_calls = [call for call in cur_mock.execute.call_args_list if "INSERT INTO model_versions" in call.args[0]]
    assert len(insert_calls) == 1
    conn_mock.commit.assert_called_once()


def test_fetch_model_version_returns_none_when_absent():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = None

    assert fetch_model_version(conn_mock, "missing-id") is None


def test_fetch_active_model_version_returns_dict_shape():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = (
        "v1", "active", "2026-07-02T12:00:00+00:00", "2026-07-02T12:00:00+00:00",
        None, "abc123", {}, {}, {}, {}, {}, {"sharpe": 1.0},
    )

    result = fetch_active_model_version(conn_mock)

    assert result["model_version_id"] == "v1"
    assert result["status"] == "active"


def test_promote_model_version_archives_old_and_activates_new():
    conn_mock, cur_mock = _make_conn_mock()

    promote_model_version(conn_mock, old_active_id="old-id", new_active_id="new-id")

    executed = [(call.args[0], call.args[1]) for call in cur_mock.execute.call_args_list]
    assert any("archived" in sql and params["id"] == "old-id" for sql, params in executed)
    assert any("'active'" in sql and params["id"] == "new-id" for sql, params in executed)
    conn_mock.commit.assert_called_once()


def test_promote_model_version_skips_archive_when_no_prior_active():
    conn_mock, cur_mock = _make_conn_mock()

    promote_model_version(conn_mock, old_active_id=None, new_active_id="new-id")

    assert cur_mock.execute.call_count == 1


def test_update_model_version_status_updates_jsonb_and_scalar_fields():
    conn_mock, cur_mock = _make_conn_mock()

    update_model_version_status(conn_mock, "v1", "candidate", aether_vault_commit="abc123", metrics={"sharpe": 1.0})

    sql, params = cur_mock.execute.call_args.args
    assert "aether_vault_commit" in sql
    assert "metrics" in sql
    assert params["aether_vault_commit"] == "abc123"


def test_insert_retraining_event_executes_insert():
    conn_mock, cur_mock = _make_conn_mock()

    insert_retraining_event(conn_mock, _sample_event())

    insert_calls = [call for call in cur_mock.execute.call_args_list if "INSERT INTO retraining_events" in call.args[0]]
    assert len(insert_calls) == 1


def test_update_retraining_event_status_updates_fields():
    conn_mock, cur_mock = _make_conn_mock()

    update_retraining_event_status(conn_mock, "evt-1", "promoted", candidate_version_id="v1", reason="done")

    sql, params = cur_mock.execute.call_args.args
    assert params["status"] == "promoted"
    assert params["candidate_version_id"] == "v1"
    assert params["reason"] == "done"


def test_fetch_recent_retraining_events_returns_list():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [
        ("evt-1", None, None, "2026-07-02T12:00:00+00:00", "2026-07-02T12:00:00+00:00", "planned", "reason", {}, [])
    ]

    events = fetch_recent_retraining_events(conn_mock, since=None)

    assert len(events) == 1
    assert events[0]["retraining_id"] == "evt-1"


def test_fetch_rollback_candidates_filters_by_status():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = []

    result = fetch_rollback_candidates(conn_mock)

    assert result == []
    sql = cur_mock.execute.call_args.args[0]
    assert "'archived'" in sql or "archived" in sql


def test_fetch_stale_active_events_returns_list():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [
        ("evt-stale", None, "ver-1", "2026-07-02T12:00:00+00:00", "2026-07-02T12:00:00+00:00", "running", "reason", {}, [])
    ]

    events = fetch_stale_active_events(conn_mock, older_than_seconds=10800)

    assert len(events) == 1
    assert events[0]["retraining_id"] == "evt-stale"
    assert events[0]["status"] == "running"


def test_fetch_stale_active_events_filters_by_status_and_staleness():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = []

    fetch_stale_active_events(conn_mock, older_than_seconds=10800)

    sql = cur_mock.execute.call_args.args[0]
    params = cur_mock.execute.call_args.args[1]
    assert "'planned'" in sql and "'running'" in sql
    assert "updated_at" in sql
    assert params["older_than_seconds"] == 10800


def test_count_experience_events_returns_int():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = (42,)

    assert count_experience_events(conn_mock) == 42
