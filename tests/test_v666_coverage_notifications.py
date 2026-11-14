"""The last unreached lines of notifications/ (V6.6.6, #359): the real connection, the run loop, the CLI and every fail-safe."""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock

import pytest

import notifications.postgres_telegram as postgres_telegram
import notifications.telegram_worker as worker_module
from notifications.telegram_worker import TelegramWorker


def _worker(monkeypatch, client=None, **kwargs):
    monkeypatch.setattr(worker_module, "ensure_schema", lambda conn: None)
    monkeypatch.setattr(worker_module, "ensure_performance_schema", lambda conn: None)
    return TelegramWorker(config={"enabled": True}, _pg_conn=MagicMock(), _telegram_client=client or MagicMock(), **kwargs)


def test_the_config_comes_from_the_phase_v2_telegram_block(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"phase_v2": {"telegram": {"enabled": False}}}), encoding="utf-8")
    assert worker_module._load_telegram_config(path) == {"enabled": False}
    path.write_text("{}", encoding="utf-8")
    assert worker_module._load_telegram_config(path) == {}


def test_without_an_injected_connection_it_connects_with_the_stored_dsn(monkeypatch):
    seen = {}
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda dsn, autocommit: seen.update(dsn=dsn, autocommit=autocommit) or MagicMock()
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setattr(worker_module, "secret_env", lambda name, default: "postgresql://stored")
    monkeypatch.setattr(worker_module, "ensure_schema", lambda conn: None)
    monkeypatch.setattr(worker_module, "ensure_performance_schema", lambda conn: None)
    monkeypatch.setattr(worker_module, "TelegramClient", lambda: MagicMock())
    TelegramWorker(postgres_dsn="ignored", config={})
    assert seen == {"dsn": "postgresql://stored", "autocommit": False}


def test_an_unformattable_or_unsent_summary_is_skipped_but_the_watermark_moves(monkeypatch):
    client = MagicMock()
    client.send_message.side_effect = [False, True]
    worker = _worker(monkeypatch, client)
    summaries = [{"created_at": "t1", "session_date": "d1"}, {"created_at": "t2", "session_date": "d2"}, {"created_at": "t3", "session_date": "d3"}]
    monkeypatch.setattr(worker_module, "get_watermark", lambda conn, name: None)
    monkeypatch.setattr(worker_module, "fetch_session_summaries_since", lambda conn, since, limit: summaries)

    def fmt(event):
        if event["session_date"] == "d1":
            raise ValueError("poison")
        return f"summary {event['session_date']}"

    marks = []
    monkeypatch.setattr(worker_module, "format_session_summary_alert", fmt)
    monkeypatch.setattr(worker_module, "set_watermark", lambda conn, name, value: marks.append((name, value)))
    assert worker._process_session_summaries() == 1 and marks == [("session_summary", "t3")]


def test_the_loop_survives_an_error_stops_on_interrupt_and_close_never_raises(monkeypatch):
    worker = _worker(monkeypatch)
    outcomes = iter([{"trigger_alerts_sent": 1}, RuntimeError("db down"), KeyboardInterrupt()])

    def run_once():
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    sleeps = []
    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(worker_module.time, "sleep", sleeps.append)
    worker.run()
    assert sleeps == [30, 30]
    worker._conn.close.side_effect = OSError("already closed")
    worker.close()


def _main(monkeypatch, *argv, config=None):
    created = {}

    class Fake:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.calls = []

        def run_once(self):
            created["ran"] = "once"
            return {"trigger_alerts_sent": 0}

        def run(self):
            created["ran"] = "loop"

        def close(self):
            created["closed"] = True

    monkeypatch.setattr(worker_module, "TelegramWorker", Fake)
    monkeypatch.setattr(worker_module, "_load_telegram_config", lambda: config or {})
    monkeypatch.setattr(worker_module, "secret_env", lambda name, default: "dsn")
    monkeypatch.setattr(sys, "argv", ["telegram_worker.py", *argv])
    worker_module.main()
    return created


def test_the_command_line_runs_once_or_forever_with_the_configured_pace(monkeypatch):
    once = _main(monkeypatch, "--once", config={"worker": {"poll_interval_seconds": 7, "batch_size": 5}})
    assert once["ran"] == "once" and once["closed"] and once["poll_interval"] == 7 and once["batch_limit"] == 5 and once["postgres_dsn"] == "dsn"
    loop = _main(monkeypatch, "--poll-interval", "2")
    assert loop["ran"] == "loop" and loop["poll_interval"] == 2 and loop["batch_limit"] == 200


def test_a_non_number_alert_value_falls_back_to_the_default():
    from notifications.telegram_alerts import _num

    assert _num("x", 3.0) == 3.0 and _num(None, 3.0) == 3.0 and _num("2.5", 3.0) == 2.5 and _num([], 1.0) == 1.0


def test_a_failed_rollback_after_a_missing_table_is_ignored():
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("relation does not exist")
    conn.rollback.side_effect = RuntimeError("closed")
    assert postgres_telegram.fetch_session_summaries_since(conn, None, limit=5) == []


def test_run_as_a_module_it_answers_help(monkeypatch, capsys):
    import runpy

    monkeypatch.setattr(sys, "argv", ["telegram_worker", "--help"])
    monkeypatch.delitem(sys.modules, "notifications.telegram_worker", raising=False)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("notifications.telegram_worker", run_name="__main__")
    assert caught.value.code == 0 and "--once" in capsys.readouterr().out
    sys.modules["notifications.telegram_worker"] = worker_module
