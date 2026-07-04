"""Tests for notifications.postgres_telegram — V2-19.

Conventions: no test classes, module-level helpers, MagicMock injection for
the psycopg3 connection/cursor (mirrors tests/test_postgres_triggers.py).
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from notifications.postgres_telegram import (
    ensure_schema,
    fetch_session_summaries_since,
    get_watermark,
    set_watermark,
)


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def _sample_session_summary_event(**overrides) -> dict:
    defaults = {
        "event_id": "33333333-3333-3333-3333-333333333333",
        "event_type": "session_summary",
        "created_at": "2026-07-02T00:00:00Z",
        "mode": "observation",
        "session_date": "2026-07-01",
        "session_start_equity": 100_000.0,
        "session_end_equity": 101_500.0,
        "session_return": 0.015,
        "observation_summary": {"count_observations": 42},
    }
    defaults.update(overrides)
    return defaults


def test_ensure_schema_creates_watermark_table():
    conn_mock, cur_mock = _make_conn_mock()
    ensure_schema(conn_mock)
    executed_sql = [call.args[0] for call in cur_mock.execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS telegram_alert_watermark" in sql for sql in executed_sql)
    conn_mock.commit.assert_called()


def test_get_watermark_returns_none_when_missing():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = None
    assert get_watermark(conn_mock, "triggers") is None


def test_get_watermark_returns_stored_value():
    conn_mock, cur_mock = _make_conn_mock()
    ts = datetime(2026, 7, 2, tzinfo=timezone.utc)
    cur_mock.fetchone.return_value = (ts,)
    assert get_watermark(conn_mock, "triggers") == ts


def test_set_watermark_upserts_by_channel():
    conn_mock, cur_mock = _make_conn_mock()
    ts = datetime(2026, 7, 2, tzinfo=timezone.utc)
    set_watermark(conn_mock, "session_summary", ts)
    executed_sql, params = cur_mock.execute.call_args.args
    assert "ON CONFLICT (channel) DO UPDATE" in executed_sql
    assert params == {"channel": "session_summary", "ts": ts}
    conn_mock.commit.assert_called()


def test_fetch_session_summaries_since_decodes_json_string_payloads():
    conn_mock, cur_mock = _make_conn_mock()
    event = _sample_session_summary_event()
    cur_mock.fetchall.return_value = [(json.dumps(event),)]

    results = fetch_session_summaries_since(conn_mock, since=None)

    assert results == [event]


def test_fetch_session_summaries_since_accepts_already_decoded_dicts():
    conn_mock, cur_mock = _make_conn_mock()
    event = _sample_session_summary_event()
    cur_mock.fetchall.return_value = [(event,)]

    results = fetch_session_summaries_since(conn_mock, since=None)

    assert results == [event]


def test_fetch_session_summaries_since_never_raises_when_table_missing():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.execute.side_effect = Exception("relation \"experience_events\" does not exist")

    results = fetch_session_summaries_since(conn_mock, since=None)

    assert results == []
    conn_mock.rollback.assert_called()
