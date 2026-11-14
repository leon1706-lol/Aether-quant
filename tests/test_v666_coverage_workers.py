"""The Redis-to-Postgres workers: last unreached paths (V6.6.6, #359): real connections, reconnects, partial batches, the loop and the CLI.

experience.postgres_worker and audit.postgres_worker are two copies of one design, so each test runs against both."""

from __future__ import annotations

import json
import runpy
import sys
import types
from unittest.mock import MagicMock

import fakeredis
import pytest

import audit.postgres_worker as audit_worker
import experience.postgres_worker as experience_worker

MODULES = [pytest.param(experience_worker, id="experience"), pytest.param(audit_worker, id="audit")]


def _event(module, number: int) -> dict:
    base = {"event_id": f"00000000-0000-0000-0000-{number:012d}", "created_at": f"2026-07-17T12:00:0{number}Z"}
    if module is audit_worker:
        return {**base, "event_type": "order_placement", "actor": "system", "payload": {"n": number}}
    return {**base, "event_type": "market_decision", "mode": "backtest", "symbol": "AAPL X", "ticker": "AAPL", "signal": "buy", "action": "trade", "portfolio": {}}


def _conn(latest="0" * 64):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    cursor.fetchone.return_value = (latest,)
    return conn, cursor


def _build(module, monkeypatch, events=(), **kwargs):
    monkeypatch.setattr(module, "ensure_schema", lambda conn: None)
    if module is audit_worker:
        monkeypatch.setattr(module, "write_status_file", lambda view: None)
        monkeypatch.setattr(module, "build_audit_status_view", lambda conn: {})
    client = fakeredis.FakeRedis()
    conn, cursor = _conn()
    client.xgroup_create("s", "g", id="0", mkstream=True)
    for event in events:
        client.xadd("s", {"payload": json.dumps(event)})
    worker = module.PostgresWorker(postgres_dsn="dsn", stream_name="s", group_name="g", deadletter_stream="s:dead", _redis_client=client, _pg_conn=conn, **kwargs)
    return worker, client, conn, cursor


@pytest.mark.parametrize("module", MODULES)
def test_the_real_clients_are_built_from_the_stored_urls_and_an_unreachable_redis_is_a_warning(module, monkeypatch):
    seen = {}
    redis_lib = types.ModuleType("redis")
    client = MagicMock()
    client.ping.side_effect = ConnectionError("not yet")
    redis_lib.from_url = lambda url, socket_connect_timeout, socket_timeout: seen.update(url=url) or client
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda dsn, autocommit: seen.update(dsn=dsn) or _conn()[0]
    monkeypatch.setitem(sys.modules, "redis", redis_lib)
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setattr(module, "secret_env", lambda name, default: f"stored-{name}")
    monkeypatch.setattr(module, "ensure_schema", lambda conn: None)
    module.PostgresWorker(postgres_dsn="dsn")
    assert seen == {"url": "stored-REDIS_URL", "dsn": "stored-POSTGRES_DSN"}
    client.ping.side_effect = None
    module.PostgresWorker(postgres_dsn="dsn")


@pytest.mark.parametrize("module", MODULES)
def test_an_existing_consumer_group_is_fine_and_any_other_error_is_not(module, monkeypatch):
    worker, _client, _conn_mock, _cursor = _build(module, monkeypatch)
    worker._ensure_consumer_group()  # BUSYGROUP: already there
    worker._redis = MagicMock()
    worker._redis.xgroup_create.side_effect = RuntimeError("NOAUTH")
    with pytest.raises(RuntimeError, match="NOAUTH"):
        worker._ensure_consumer_group()


@pytest.mark.parametrize("module", MODULES)
def test_a_reconnect_replaces_the_connection(module, monkeypatch):
    worker, _client, conn, _cursor = _build(module, monkeypatch)
    conn.close.side_effect = OSError("already closed")
    fresh = _conn()[0]
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda dsn, autocommit: fresh
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setattr(module, "secret_env", lambda name, default: default)
    worker._reconnect_pg("dsn")
    assert worker._conn is fresh


@pytest.mark.parametrize("module", MODULES)
def test_a_failing_head_row_raises_and_a_failing_later_row_is_dead_lettered(module, monkeypatch):
    events = [_event(module, number) for number in (1, 2, 3)]
    worker, client, conn, cursor = _build(module, monkeypatch, events)
    cursor.executemany.side_effect = RuntimeError("batch failed")
    def refuse(sql, row=None):
        if "INSERT" in str(sql):
            raise RuntimeError("head failed")

    cursor.execute.side_effect = refuse
    with pytest.raises(RuntimeError, match="head failed"):
        worker.run_once()
    conn.rollback.assert_called()

    worker, client, conn, cursor = _build(module, monkeypatch, events)
    cursor.executemany.side_effect = RuntimeError("batch failed")
    calls = {"count": 0}

    def execute(sql, row=None):
        if "INSERT" not in str(sql):
            return
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("poison")

    cursor.execute.side_effect = execute
    persisted = worker.run_once()
    dead = client.xrange("s:dead")
    assert persisted == (1 if module is audit_worker else 2) and len(dead) == (2 if module is audit_worker else 1)


@pytest.mark.parametrize("module", MODULES)
def test_a_later_row_that_inserts_is_acknowledged(module, monkeypatch):
    events = [_event(module, number) for number in (1, 2, 3)]
    worker, client, conn, cursor = _build(module, monkeypatch, events)
    cursor.executemany.side_effect = RuntimeError("batch failed")
    assert worker.run_once() == 3 and not client.xrange("s:dead")


@pytest.mark.parametrize("module", MODULES)
def test_the_loop_idles_backs_off_reconnects_and_stops_on_interrupt(module, monkeypatch):
    worker, _client, _conn_mock, _cursor = _build(module, monkeypatch, backoff_max=4)
    outcomes = iter([0, 3, RuntimeError("connection lost"), RuntimeError("other"), RuntimeError("connection lost"), KeyboardInterrupt()])

    def run_once():
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    sleeps, reconnects = [], []

    def reconnect(dsn):
        reconnects.append(dsn)
        if len(reconnects) == 2:
            raise OSError("still down")

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(worker, "_reconnect_pg", reconnect)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    worker.run(postgres_dsn="dsn")
    assert sleeps == [1, 1, 2, 4] and reconnects == ["dsn", "dsn"]
    worker._redis, worker._conn = MagicMock(), MagicMock()
    worker._redis.close.side_effect = OSError("x")
    worker._conn.close.side_effect = OSError("x")
    worker.close()


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("once", [True, False])
def test_the_command_line_reads_the_stored_urls_and_runs_once_or_forever(module, monkeypatch, once):
    created = {}

    class Fake:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def run_once(self):
            created["ran"] = "once"
            return 2

        def run(self, postgres_dsn):
            created["ran"] = "loop"

        def close(self):
            created["closed"] = True

    monkeypatch.setattr(module, "PostgresWorker", Fake)
    monkeypatch.setattr(module, "secret_env", lambda name, default: f"stored-{name}")
    monkeypatch.setattr(sys, "argv", ["worker", *(["--once"] if once else []), "--batch-size", "7", "--stream", "x", "--group", "y"])
    module.main()
    assert created["ran"] == ("once" if once else "loop") and created["closed"] and created["batch_size"] == 7 and created["redis_url"] == "stored-REDIS_URL"


@pytest.mark.parametrize("module", MODULES)
def test_run_as_a_module_it_answers_help(module, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["worker", "--help"])
    saved = sys.modules.pop(module.__name__)
    try:
        with pytest.raises(SystemExit) as caught:
            runpy.run_module(module.__name__, run_name="__main__")
        assert caught.value.code == 0 and "--once" in capsys.readouterr().out
    finally:
        sys.modules[module.__name__] = saved


def test_only_failures_of_the_link_count_as_connection_errors():
    assert audit_worker._is_connection_error(ValueError("bad payload")) is False
    assert audit_worker._is_connection_error(ConnectionResetError()) is True
