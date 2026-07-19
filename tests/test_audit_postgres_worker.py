"""Tests for audit.postgres_worker — the Redis-Stream-to-Postgres audit
persistence worker (development/Problems.md #42). Mirrors
tests/test_postgres_worker.py's conventions exactly.
"""

import json
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from audit.hash_chain import GENESIS_HASH, compute_entry_hash
from audit.postgres_worker import PostgresWorker, event_to_row, fetch_latest_hash

# run_once() best-effort-refreshes the webui dashboard snapshot
# (audit/status_export.py) after every real persist - patched to a no-op
# for the whole module so these tests never write to the real repo-relative
# visualization/grafana/audit_log.json path (the mocked cursor's unconfigured
# fetchall() would make build_audit_status_view() see an empty table anyway,
# but writing ANYTHING to a real path from a test run is exactly the kind of
# leak this patch exists to prevent).
pytestmark = pytest.mark.usefixtures("_patch_status_export")


@pytest.fixture
def _patch_status_export():
    with patch("audit.postgres_worker.write_status_file") as mock_write:
        yield mock_write

_STREAM = "aether:audit"
_GROUP = "test-audit-group"
_CONSUMER = "test-consumer"
_DEADLETTER = "aether:audit:deadletter"


def _sample_event(**overrides) -> dict:
    defaults = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "event_type": "order_placement",
        "created_at": "2026-07-17T12:00:00Z",
        "actor": "system",
        "payload": {"symbol": "AAPL", "signal": "buy", "target_weight": 0.12},
    }
    defaults.update(overrides)
    return defaults


def _make_conn_mock(latest_hash: str | None = GENESIS_HASH):
    """latest_hash=None simulates an empty table (fetchone returns None);
    any string simulates the current chain tail."""
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    cur_mock.fetchone.return_value = (latest_hash,) if latest_hash is not None else None
    return conn_mock, cur_mock


def _fake_worker(events=None, latest_hash: str | None = GENESIS_HASH):
    client = fakeredis.FakeRedis()
    conn_mock, cur_mock = _make_conn_mock(latest_hash)
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
# event_to_row / fetch_latest_hash — pure-ish helpers
# ---------------------------------------------------------------------------


def test_event_to_row_computes_expected_hash():
    event = _sample_event()
    row = event_to_row(event, GENESIS_HASH)

    expected_hash = compute_entry_hash(GENESIS_HASH, "order_placement", "2026-07-17T12:00:00Z", event["payload"])
    assert row["hash"] == expected_hash
    assert row["prev_hash"] == GENESIS_HASH
    assert row["event_id"] == "00000000-0000-0000-0000-000000000001"
    assert row["actor"] == "system"
    assert json.loads(row["payload"]) == event["payload"]


def test_event_to_row_chains_to_given_prev_hash():
    event = _sample_event()
    row = event_to_row(event, "a" * 64)
    assert row["prev_hash"] == "a" * 64
    assert row["hash"] != GENESIS_HASH


def test_fetch_latest_hash_returns_genesis_on_empty_table():
    conn_mock, cur_mock = _make_conn_mock(latest_hash=None)
    assert fetch_latest_hash(conn_mock) == GENESIS_HASH


def test_fetch_latest_hash_returns_tail_hash():
    conn_mock, cur_mock = _make_conn_mock(latest_hash="b" * 64)
    assert fetch_latest_hash(conn_mock) == "b" * 64


# ---------------------------------------------------------------------------
# PostgresWorker.run_once
# ---------------------------------------------------------------------------


def test_run_once_persists_batch_and_chains_correctly():
    events = [
        _sample_event(event_id=f"00000000-0000-0000-0000-00000000000{i}", payload={"symbol": f"T{i}"})
        for i in range(1, 4)
    ]
    worker, client, conn_mock, cur_mock = _fake_worker(events=events, latest_hash=GENESIS_HASH)

    count = worker.run_once()

    assert count == 3
    cur_mock.executemany.assert_called_once()
    inserted_rows = cur_mock.executemany.call_args[0][1]
    # Each row's prev_hash must equal the PRIOR row's hash (chain integrity
    # within a single batch, before any of them are committed).
    assert inserted_rows[0]["prev_hash"] == GENESIS_HASH
    assert inserted_rows[1]["prev_hash"] == inserted_rows[0]["hash"]
    assert inserted_rows[2]["prev_hash"] == inserted_rows[1]["hash"]
    conn_mock.commit.assert_called()
    assert client.xpending(_STREAM, _GROUP)["pending"] == 0


def test_run_once_continues_existing_chain():
    events = [_sample_event()]
    worker, client, conn_mock, cur_mock = _fake_worker(events=events, latest_hash="c" * 64)

    worker.run_once()

    inserted_rows = cur_mock.executemany.call_args[0][1]
    assert inserted_rows[0]["prev_hash"] == "c" * 64


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
