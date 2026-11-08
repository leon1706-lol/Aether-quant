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
    # V5.4.7 (#120): a real outage fails EVERY statement - the batch insert
    # AND the first-row probe must both raise for the worker to keep the
    # messages pending (the poison-row fallback only engages when the head
    # of the batch inserts fine). Set AFTER construction so ensure_schema's
    # DDL isn't affected.
    cur_mock.execute.side_effect = Exception("connection terminated")
    with pytest.raises(Exception, match="connection terminated"):
        worker.run_once()
    assert client.xpending(_STREAM, _GROUP)["pending"] == 1


def test_worker_returns_zero_when_stream_empty():
    worker, client, conn_mock, cur_mock = _fake_worker(events=[])
    count = worker.run_once()
    assert count == 0
    cur_mock.executemany.assert_not_called()


def test_poison_row_deadletters_itself_and_later_chained_rows():
    """V5.4.7 (Problems.md #120): the hash chain means a failed middle row
    invalidates every LATER row in the batch (their hashes chain off a
    parent that never landed). The per-row fallback therefore persists the
    clean prefix, dead-letters the poison row AND everything after it, and
    leaves nothing pending - the pipeline cannot wedge on one bad payload,
    and the tamper-evident chain never forks."""
    events = [
        _sample_event(event_id=f"00000000-0000-0000-0000-{i:012x}") for i in range(1, 4)
    ]
    client = fakeredis.FakeRedis()
    conn_mock, cur_mock = _make_conn_mock()
    client.xgroup_create(_STREAM, _GROUP, id="0", mkstream=True)
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
    # Batch insert fails; per-row probe of row[0] succeeds; row[1] is
    # poison; row[2] must NOT be attempted (chained off the poison hash).
    # NOTE: run_once's fetch_latest_hash() consumes the FIRST execute call.
    cur_mock.executemany.side_effect = Exception("invalid input syntax for type json")
    cur_mock.execute.side_effect = [
        "hash-row",                              # fetch_latest_hash probe
        None,                                    # first-row probe (poison vs down)
        Exception("Token 'NaN' is invalid"),     # row[1] - the poison row
        None,                                    # never reached (chained stop)
    ]

    persisted = worker.run_once()

    assert persisted == 1
    deadletter = client.xrange(_DEADLETTER)
    assert len(deadletter) == 2  # poison + its chained successor
    for _, fields in deadletter:
        field_map = {k if isinstance(k, str) else k.decode(): v for k, v in fields.items()}
        assert "chained after poison row" in str(field_map.get("error", "")) or "NaN" in str(field_map.get("error", ""))
        assert "original_id" in field_map
    assert client.xpending(_STREAM, _GROUP)["pending"] == 0


def test_first_row_failure_still_raises_leaving_everything_pending():
    """V5.4.7 (#120): first-row failure = postgres down, not poison data -
    re-raise so all messages stay pending (pre-existing contract)."""
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
    cur_mock.execute.side_effect = Exception("connection terminated")
    with pytest.raises(Exception, match="connection terminated"):
        worker.run_once()


# --- V6.6.4 (Problems #339): a chain read back from a real Postgres must verify -----------------------------------------------------

def test_a_row_read_back_with_a_datetime_timestamp_verifies_like_the_row_that_was_hashed():
    import datetime

    from audit.hash_chain import GENESIS_HASH, canonical_timestamp, verify_chain
    from audit.postgres_audit import _row_to_dict
    from audit.postgres_worker import event_to_row

    rows, previous = [], GENESIS_HASH
    for index in range(4):
        event = {"event_id": f"id-{index}", "created_at": f"2026-11-07T10:00:0{index}Z", "event_type": "order_placement", "actor": "system", "payload": {"n": index, "symbol": "BTCUSD"}}
        stored = event_to_row(event, previous)
        previous = stored["hash"]
        # what psycopg returns for TIMESTAMPTZ and JSONB
        rows.append(_row_to_dict((
            stored["event_id"], datetime.datetime.fromisoformat(stored["created_at"].replace("Z", "+00:00")), stored["event_type"], stored["actor"],
            stored["prev_hash"], stored["hash"], event["payload"],
        )))
    assert verify_chain(rows) == (True, None)
    rows[2] = {**rows[2], "payload": {"n": 99}}
    assert verify_chain(rows)[0] is False
    assert canonical_timestamp(datetime.datetime(2026, 11, 7, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))) == "2026-11-07T10:00:00Z"


def test_canonical_timestamp_leaves_what_it_cannot_parse_alone_and_keeps_the_producers_own_form():
    import datetime

    from audit.hash_chain import canonical_timestamp

    assert canonical_timestamp("2026-07-17T12:00:00Z") == "2026-07-17T12:00:00Z", "build_audit_event's form is unchanged, so rows hashed before this verify as they did"
    assert canonical_timestamp("2026-07-17T12:00:00+00:00") == "2026-07-17T12:00:00Z"
    assert canonical_timestamp("t0") == "t0" and canonical_timestamp("not a date") == "not a date"
    assert canonical_timestamp(datetime.datetime(2026, 7, 17, 12, 0, 0, 250000)) == "2026-07-17T12:00:00.250000Z"


# --- V6.6.4 (Problems #340): events read during a Postgres outage are written once it is back -----------------------------------------------------

def _events(count: int):
    return [_sample_event(event_id=f"00000000-0000-0000-0000-0000000000{index:02d}", payload={"symbol": f"T{index}"}) for index in range(1, count + 1)]


def test_messages_read_during_an_outage_are_replayed_after_it():
    worker, client, conn_mock, cur_mock = _fake_worker(events=_events(4))
    cur_mock.executemany.side_effect = RuntimeError("server closed the connection unexpectedly")
    cur_mock.execute.side_effect = RuntimeError("server closed the connection unexpectedly")
    with pytest.raises(RuntimeError):
        worker.run_once()
    assert client.xpending(_STREAM, _GROUP)["pending"] == 4, "read and not acknowledged"

    cur_mock.executemany.side_effect = None
    cur_mock.execute.side_effect = None
    assert worker.run_once() == 4, "the same four are read again and written"
    assert client.xpending(_STREAM, _GROUP)["pending"] == 0
    rows = cur_mock.executemany.call_args[0][1]
    assert [row["event_id"] for row in rows] == [event["event_id"] for event in _events(4)]
    assert rows[1]["prev_hash"] == rows[0]["hash"], "the chain continues from the database's tail, unforked"
    assert worker.run_once() == 0 and worker._replay_pending is False, "nothing left to replay"


def test_a_new_worker_with_the_same_consumer_name_picks_up_what_a_dead_one_left():
    worker, client, conn_mock, cur_mock = _fake_worker(events=_events(3))
    cur_mock.executemany.side_effect = RuntimeError("connection reset")
    cur_mock.execute.side_effect = RuntimeError("connection reset")
    with pytest.raises(RuntimeError):
        worker.run_once()
    cur_mock.executemany.side_effect = None
    cur_mock.execute.side_effect = None
    revived = PostgresWorker(
        redis_url="redis://localhost:6379/0", postgres_dsn="x", stream_name=_STREAM, group_name=_GROUP, consumer_name=_CONSUMER, deadletter_stream=_DEADLETTER,
        _redis_client=client, _pg_conn=conn_mock,
    )
    assert revived.run_once() == 3


def test_a_batch_that_keeps_failing_for_a_reason_that_is_not_the_connection_is_dead_lettered_not_retried_forever():
    from audit.postgres_worker import MAX_REPLAY_FAILURES

    worker, client, conn_mock, cur_mock = _fake_worker(events=_events(2))
    cur_mock.executemany.side_effect = ValueError("value too long for type character varying(30)")
    cur_mock.execute.side_effect = ValueError("value too long for type character varying(30)")
    for _ in range(MAX_REPLAY_FAILURES + 1):
        with pytest.raises(ValueError):
            worker.run_once()
    assert client.xlen(_DEADLETTER) == 2 and client.xpending(_STREAM, _GROUP)["pending"] == 0


def test_a_long_outage_never_dead_letters_anything():
    from audit.postgres_worker import MAX_REPLAY_FAILURES

    worker, client, conn_mock, cur_mock = _fake_worker(events=_events(2))
    cur_mock.executemany.side_effect = RuntimeError("terminating connection due to administrator command")
    cur_mock.execute.side_effect = RuntimeError("terminating connection due to administrator command")
    for _ in range(MAX_REPLAY_FAILURES * 4):
        with pytest.raises(RuntimeError):
            worker.run_once()
    assert client.xlen(_DEADLETTER) == 0 and client.xpending(_STREAM, _GROUP)["pending"] == 2
