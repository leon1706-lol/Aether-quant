"""Tests for audit.postgres_audit — the read-only query helpers shared by
`aq audit-log` and the webui's /api/audit-log route (development/Problems.md
#42). Mirrors tests/test_retraining_orchestrator.py's mocked-cursor
conventions.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from audit.postgres_audit import _COLUMNS, fetch_all_events_ordered, fetch_recent_events


def _make_conn_mock(rows: list[tuple]):
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    cur_mock.fetchall.return_value = rows
    return conn_mock, cur_mock


def _sample_row(event_id="00000000-0000-0000-0000-000000000001"):
    return (
        event_id,
        datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc),
        "order_placement",
        "system",
        "0" * 64,
        "a" * 64,
        {"symbol": "AAPL"},
    )


def test_fetch_recent_events_maps_columns_correctly():
    conn_mock, cur_mock = _make_conn_mock([_sample_row()])

    rows = fetch_recent_events(conn_mock)

    assert len(rows) == 1
    assert rows[0]["event_id"] == "00000000-0000-0000-0000-000000000001"
    assert rows[0]["event_type"] == "order_placement"
    assert rows[0]["actor"] == "system"
    assert rows[0]["payload"] == {"symbol": "AAPL"}
    assert set(rows[0].keys()) == set(_COLUMNS)


def test_fetch_recent_events_filters_by_event_type():
    conn_mock, cur_mock = _make_conn_mock([])

    fetch_recent_events(conn_mock, event_type="credential_load")

    executed_sql = cur_mock.execute.call_args[0][0]
    params = cur_mock.execute.call_args[0][1]
    assert "event_type = %(event_type)s" in executed_sql
    assert params["event_type"] == "credential_load"


def test_fetch_recent_events_without_filter_omits_event_type_clause():
    conn_mock, cur_mock = _make_conn_mock([])

    fetch_recent_events(conn_mock)

    executed_sql = cur_mock.execute.call_args[0][0]
    assert "event_type = " not in executed_sql


def test_fetch_recent_events_respects_limit_param():
    conn_mock, cur_mock = _make_conn_mock([])

    fetch_recent_events(conn_mock, limit=25)

    params = cur_mock.execute.call_args[0][1]
    assert params["limit"] == 25


def test_fetch_all_events_ordered_returns_oldest_first_query():
    conn_mock, cur_mock = _make_conn_mock([_sample_row(), _sample_row(event_id="...002")])

    rows = fetch_all_events_ordered(conn_mock)

    executed_sql = cur_mock.execute.call_args[0][0]
    assert "ORDER BY id ASC" in executed_sql
    assert len(rows) == 2
