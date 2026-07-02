"""Tests for performance.postgres_triggers — V2-16.

Conventions: no test classes, module-level helpers, MagicMock injection for
the psycopg3 connection/cursor (mirrors tests/test_postgres_worker.py).
"""

import json
from unittest.mock import MagicMock

from performance.postgres_triggers import (
    ensure_schema,
    fetch_events_since,
    fetch_latest_trigger,
    get_watermark,
    insert_triggers,
    set_watermark,
    trigger_to_row,
)


def _sample_trigger(**overrides) -> dict:
    defaults = {
        "trigger_id": "00000000-0000-0000-0000-0000000000aa",
        "created_at": "2026-07-02T12:00:00+00:00",
        "trigger_type": "drawdown_trigger",
        "severity": "critical",
        "mode": "observation",
        "scope": "portfolio",
        "metric_value": -0.22,
        "threshold": -0.10,
        "message": "simulated drawdown reached -22.00% (threshold -10.00%).",
        "recommended_action": "reduce_exposure",
        "retrain_candidate": True,
    }
    defaults.update(overrides)
    return defaults


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def test_trigger_to_row_extracts_scalar_fields():
    trigger = _sample_trigger()

    row = trigger_to_row(trigger)

    assert row["trigger_id"] == trigger["trigger_id"]
    assert row["trigger_type"] == "drawdown_trigger"
    assert row["severity"] == "critical"
    assert row["scope"] == "portfolio"
    assert row["metric_value"] == -0.22
    assert row["retrain_candidate"] is True


def test_trigger_to_row_details_contains_full_trigger_dict():
    trigger = _sample_trigger()

    row = trigger_to_row(trigger)
    details = json.loads(row["details"])

    for key in trigger:
        assert key in details


def test_ensure_schema_creates_table_and_indexes():
    conn_mock, cur_mock = _make_conn_mock()

    ensure_schema(conn_mock)

    executed_sql = [call.args[0] for call in cur_mock.execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS performance_triggers" in sql for sql in executed_sql)
    assert any("CREATE TABLE IF NOT EXISTS performance_trigger_watermark" in sql for sql in executed_sql)
    assert any("ix_trig_created_at" in sql for sql in executed_sql)
    assert any("USING GIN" in sql for sql in executed_sql)
    conn_mock.commit.assert_called_once()


def test_insert_triggers_persists_new_rows():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = None  # no existing suppression-window row

    inserted = insert_triggers(conn_mock, [_sample_trigger()], suppression_minutes=60)

    assert inserted == 1
    insert_calls = [call for call in cur_mock.execute.call_args_list if "INSERT INTO performance_triggers" in call.args[0]]
    assert len(insert_calls) == 1


def test_insert_triggers_skips_when_suppression_window_active():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = (1,)  # a recent matching trigger already exists

    inserted = insert_triggers(conn_mock, [_sample_trigger()], suppression_minutes=60)

    assert inserted == 0
    insert_calls = [call for call in cur_mock.execute.call_args_list if "INSERT INTO performance_triggers" in call.args[0]]
    assert len(insert_calls) == 0


def test_fetch_events_since_returns_decoded_payload_dicts():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [({"signal": "buy"},), ({"signal": "hold"},)]

    events = fetch_events_since(conn_mock, since=None)

    assert events == [{"signal": "buy"}, {"signal": "hold"}]


def test_fetch_events_since_falls_back_to_json_loads_for_string_payload():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [(json.dumps({"signal": "sell"}),)]

    events = fetch_events_since(conn_mock, since=None)

    assert events == [{"signal": "sell"}]


def test_fetch_events_since_defaults_to_epoch_when_since_is_none():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = []

    fetch_events_since(conn_mock, since=None)

    params = cur_mock.execute.call_args.args[1]
    assert params["since"].year == 1970


def test_watermark_round_trip():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = None

    assert get_watermark(conn_mock) is None

    set_watermark(conn_mock, "2026-07-02T12:00:00+00:00")
    conn_mock.commit.assert_called_once()


def test_fetch_latest_trigger_returns_none_when_empty():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = None

    assert fetch_latest_trigger(conn_mock) is None


def test_fetch_latest_trigger_returns_dict_shape():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = (
        "00000000-0000-0000-0000-0000000000aa",
        "2026-07-02T12:00:00+00:00",
        "drawdown_trigger",
        "critical",
        "observation",
        "portfolio",
        -0.22,
        -0.10,
        "message",
        "reduce_exposure",
        True,
    )

    result = fetch_latest_trigger(conn_mock)

    assert result["trigger_type"] == "drawdown_trigger"
    assert result["retrain_candidate"] is True
