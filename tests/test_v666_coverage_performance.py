"""The last unreached lines of performance/ (V6.6.6, #359): the worker's real connection, loop and CLI, and the empty-input guards."""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock

import pytest

import performance.postgres_triggers as postgres_triggers
import performance.trigger_worker as worker_module
from performance import triggers
from performance.trigger_worker import TriggerWorker


def _worker(monkeypatch, **kwargs):
    monkeypatch.setattr(worker_module, "ensure_schema", lambda conn: None)
    return TriggerWorker(config={}, _pg_conn=MagicMock(), **kwargs)


def test_the_config_comes_from_the_performance_triggers_block(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"phase_v2": {"performance_triggers": {"suppression_minutes": 5}}}), encoding="utf-8")
    assert worker_module._load_performance_triggers_config(path) == {"suppression_minutes": 5}
    path.write_text("{}", encoding="utf-8")
    assert worker_module._load_performance_triggers_config(path) == {}


def test_without_an_injected_connection_it_connects_with_the_stored_dsn(monkeypatch):
    seen = {}
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda dsn, autocommit: seen.update(dsn=dsn) or MagicMock()
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setattr(worker_module, "secret_env", lambda name, default: "postgresql://stored")
    monkeypatch.setattr(worker_module, "ensure_schema", lambda conn: None)
    TriggerWorker(config={})
    assert seen == {"dsn": "postgresql://stored"}


def test_the_loop_survives_an_error_stops_on_interrupt_and_close_never_raises(monkeypatch):
    worker = _worker(monkeypatch, poll_interval=3)
    outcomes = iter([0, RuntimeError("db down"), KeyboardInterrupt()])

    def run_once():
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    sleeps = []
    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(worker_module.time, "sleep", sleeps.append)
    worker.run()
    assert sleeps == [3, 3]
    worker._conn.close.side_effect = OSError("closed")
    worker.close()


@pytest.mark.parametrize("argv", [["--once"], []])
def test_the_command_line_runs_once_or_forever(monkeypatch, argv):
    created = {}

    class Fake:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def run_once(self):
            created["ran"] = "once"
            return 4

        def run(self):
            created["ran"] = "loop"

        def close(self):
            created["closed"] = True

    monkeypatch.setattr(worker_module, "TriggerWorker", Fake)
    monkeypatch.setattr(worker_module, "_load_performance_triggers_config", lambda: {"x": 1})
    monkeypatch.setattr(worker_module, "secret_env", lambda name, default: "dsn")
    monkeypatch.setattr(sys, "argv", ["trigger_worker.py", *argv, "--poll-interval", "9"])
    worker_module.main()
    assert created["ran"] == ("once" if argv else "loop") and created["closed"] and created["poll_interval"] == 9 and created["config"] == {"x": 1}


def test_run_as_a_module_it_answers_help(monkeypatch, capsys):
    import runpy

    monkeypatch.setattr(sys, "argv", ["trigger_worker", "--help"])
    monkeypatch.delitem(sys.modules, "performance.trigger_worker", raising=False)
    try:
        with pytest.raises(SystemExit) as caught:
            runpy.run_module("performance.trigger_worker", run_name="__main__")
        assert caught.value.code == 0 and "--once" in capsys.readouterr().out
    finally:
        sys.modules["performance.trigger_worker"] = worker_module


def test_a_failed_rollback_when_no_retraining_table_exists_is_ignored():
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("no such table")
    conn.rollback.side_effect = RuntimeError("closed")
    assert postgres_triggers.fetch_last_retraining_at(conn) is None


def test_candidate_triggers_come_back_newest_first_with_decoded_details():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("id1", "t2", "drawdown_trigger", "critical", "paper", "portfolio", -0.2, -0.1, "m", "reduce", True, '{"k": 1}'),
        ("id2", "t1", "drawdown_trigger", "warning", "paper", "portfolio", -0.2, -0.1, "m", "reduce", True, {"j": 2}),
        ("id3", "t0", "drawdown_trigger", "warning", "paper", "portfolio", -0.2, -0.1, "m", "reduce", True, None),
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    rows = postgres_triggers.fetch_candidate_triggers(conn, limit=3)
    assert [row["details"] for row in rows] == [{"k": 1}, {"j": 2}, {}] and rows[0]["trigger_id"] == "id1"


def test_empty_inputs_fire_no_trigger_and_no_mode_is_unknown():
    assert triggers._latest_mode([{"mode": None}, {}]) == "unknown"
    assert triggers.drawdown_trigger([]) == [] and triggers.risk_lock_trigger([]) == []
    assert triggers.sustained_drawdown_trigger([], consecutive_days=3) == [] and triggers.sustained_drawdown_trigger([{"mode": "live"}], consecutive_days=0) == []
    assert triggers.trigger_frequency_spike([]) == []


def test_a_burst_that_is_no_faster_than_the_day_before_is_not_a_spike():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    steady = [{"created_at": (now - timedelta(minutes=5 * index)).isoformat()} for index in range(200)]
    assert triggers.trigger_frequency_spike(steady) == []
