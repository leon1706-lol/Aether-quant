"""Tests for experience.postgres_worker — V2-14.

Conventions: no test classes, module-level helpers, fakeredis + MagicMock
injection via _redis_client / _pg_conn constructor parameters.
"""

import json
from unittest.mock import MagicMock

import fakeredis
import pytest

from experience import PostgresWorker, event_to_row

_STREAM = "aether:experience"
_GROUP = "test-group"
_CONSUMER = "test-consumer"
_DEADLETTER = "aether:experience:deadletter"


def _sample_event(**overrides) -> dict:
    defaults = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "event_type": "market_decision",
        "created_at": "2026-07-01T12:00:00Z",
        "mode": "backtest",
        "symbol": "AAPL R735QTJ8XC9X",
        "ticker": "AAPL",
        "signal": "buy",
        "action": "trade",
        "execution_note": "entered_long",
        "probability_up": 0.61,
        "confidence": 0.22,
        "target_weight": 0.12,
        "regime": {},
        "moe_gating": {},
        "topology": {},
        "liquidity": {},
        "market_analysis": {},
        "portfolio": {"total_value": 105000.0, "cash": 50000.0, "current_drawdown": -0.01},
    }
    defaults.update(overrides)
    return defaults


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def _fake_worker(events=None):
    """Wire up PostgresWorker with fakeredis + mock PG; pre-populate stream."""
    client = fakeredis.FakeRedis()
    conn_mock, cur_mock = _make_conn_mock()
    client.xgroup_create(_STREAM, _GROUP, id="0", mkstream=True)
    if events:
        for ev in events:
            client.xadd(_STREAM, {"payload": json.dumps(ev)})
    worker = PostgresWorker(
        redis_url="redis://localhost:6379/0",
        postgres_dsn="postgresql://aether:aether_dev_password@localhost:5432/aether_quant",
        stream_name=_STREAM,
        group_name=_GROUP,
        consumer_name=_CONSUMER,
        deadletter_stream=_DEADLETTER,
        _redis_client=client,
        _pg_conn=conn_mock,
    )
    return worker, client, conn_mock, cur_mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_event_to_row_extracts_scalar_fields():
    event = _sample_event()
    row = event_to_row(event)
    assert row["event_id"] == "00000000-0000-0000-0000-000000000001"
    assert row["ticker"] == "AAPL"
    assert row["signal"] == "buy"
    assert row["action"] == "trade"
    assert row["mode"] == "backtest"
    assert row["symbol"] == "AAPL R735QTJ8XC9X"
    assert row["created_at"] == "2026-07-01T12:00:00Z"
    assert row["confidence"] == pytest.approx(0.22)
    assert row["target_weight"] == pytest.approx(0.12)


def test_event_to_row_payload_contains_full_json():
    event = _sample_event()
    row = event_to_row(event)
    payload = json.loads(row["payload"])
    for key in event:
        assert key in payload
    assert payload["portfolio"]["total_value"] == 105000.0


def _sample_session_summary_event(**overrides) -> dict:
    """A session_summary event (V2-19) carries no ticker/symbol/signal/action —
    event_to_row() must not raise KeyError on this shape."""
    defaults = {
        "event_id": "00000000-0000-0000-0000-000000000099",
        "event_type": "session_summary",
        "created_at": "2026-07-02T00:00:00Z",
        "mode": "observation",
        "session_date": "2026-07-01",
        "session_start_equity": 100000.0,
        "session_end_equity": 101000.0,
        "session_return": 0.01,
        "observation_summary": {"count_observations": 10},
    }
    defaults.update(overrides)
    return defaults


def test_event_to_row_handles_session_summary_event_without_ticker_fields():
    event = _sample_session_summary_event()
    row = event_to_row(event)
    assert row["ticker"] == ""
    assert row["symbol"] == ""
    assert row["signal"] == ""
    assert row["action"] == "session_summary"
    assert row["mode"] == "observation"
    payload = json.loads(row["payload"])
    assert payload["event_type"] == "session_summary"


def test_event_to_row_still_uses_explicit_action_when_present():
    """market_decision events (which always have "action") keep taking
    precedence over the event_type fallback."""
    event = _sample_event(action="trade")
    row = event_to_row(event)
    assert row["action"] == "trade"


def test_run_once_persists_batch():
    events = [
        _sample_event(event_id=f"00000000-0000-0000-0000-00000000000{i}", ticker=f"T{i}")
        for i in range(1, 4)
    ]
    worker, client, conn_mock, cur_mock = _fake_worker(events=events)

    count = worker.run_once()

    assert count == 3
    cur_mock.executemany.assert_called_once()
    conn_mock.commit.assert_called()
    assert client.xpending(_STREAM, _GROUP)["pending"] == 0


def test_duplicate_event_id_does_not_raise():
    """Inserting the same event_id twice calls executemany twice — no Python error.

    ON CONFLICT DO NOTHING is enforced by the SQL, not the worker layer.
    """
    event = _sample_event()
    worker, client, conn_mock, cur_mock = _fake_worker(events=[event])
    worker.run_once()
    client.xadd(_STREAM, {"payload": json.dumps(event)})
    worker.run_once()  # must not raise
    assert cur_mock.executemany.call_count == 2


def test_malformed_event_goes_to_deadletter():
    client = fakeredis.FakeRedis()
    conn_mock, cur_mock = _make_conn_mock()
    client.xgroup_create(_STREAM, _GROUP, id="0", mkstream=True)
    client.xadd(_STREAM, {"payload": b"not valid json {{{"})
    worker = PostgresWorker(
        redis_url="redis://localhost:6379/0",
        postgres_dsn="postgresql://aether:aether_dev_password@localhost:5432/aether_quant",
        stream_name=_STREAM,
        group_name=_GROUP,
        consumer_name=_CONSUMER,
        deadletter_stream=_DEADLETTER,
        _redis_client=client,
        _pg_conn=conn_mock,
    )
    count = worker.run_once()
    assert count == 0
    assert len(client.xrange(_DEADLETTER)) == 1
    assert client.xpending(_STREAM, _GROUP)["pending"] == 0


def test_postgres_failure_leaves_messages_pending():
    event = _sample_event()
    client = fakeredis.FakeRedis()
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.executemany.side_effect = Exception("connection terminated")
    client.xgroup_create(_STREAM, _GROUP, id="0", mkstream=True)
    client.xadd(_STREAM, {"payload": json.dumps(event)})
    worker = PostgresWorker(
        redis_url="redis://localhost:6379/0",
        postgres_dsn="postgresql://aether:aether_dev_password@localhost:5432/aether_quant",
        stream_name=_STREAM,
        group_name=_GROUP,
        consumer_name=_CONSUMER,
        deadletter_stream=_DEADLETTER,
        _redis_client=client,
        _pg_conn=conn_mock,
    )
    with pytest.raises(Exception, match="connection terminated"):
        worker.run_once()
    assert client.xpending(_STREAM, _GROUP)["pending"] == 1


def test_worker_returns_zero_when_stream_empty():
    worker, client, conn_mock, cur_mock = _fake_worker(events=[])
    count = worker.run_once()
    assert count == 0
    cur_mock.executemany.assert_not_called()
