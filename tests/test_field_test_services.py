"""scripts/field_test_services.py (V6.6.6): the scenario logic against stand-in Redis, Postgres and service commands.

The real-server run is `scripts/field_services.sh`; here the queue, the worker, the database and the stop/start commands are
fakes, so each scenario's pass and fail paths are exercised without either service."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

from script_loader import load_script


class _State:
    def __init__(self):
        self.redis_up = True
        self.postgres_up = True
        self.tampered = False
        self.pending = 0
        self.rows = 0


def _setup(monkeypatch, state, *, tamper_row=True, recover_fails=False):
    module = load_script("field_test_services")
    monkeypatch.setattr(module, "secret_env", lambda name, default: f"{name.lower()}://x")
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    class Queue:
        def __init__(self, redis_url, stream_name):
            self._client = object() if state.redis_up else None

        def push(self, event):
            if not state.redis_up:
                return False
            state.pending += 1
            return True

    class Worker:
        def __init__(self, **kwargs):
            self.reconnected = False

        def run_once(self):
            if not state.postgres_up:
                raise ConnectionError("postgres down")
            written, state.pending = state.pending, 0
            state.rows += written
            return written

        def _reconnect_pg(self, dsn):
            if recover_fails:
                raise OSError("still down")

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            if sql.startswith("UPDATE"):
                state.tampered = "tampered" in sql
            return SimpleNamespace(fetchone=lambda: ("event-1", {"n": 1}) if tamper_row else None)

    monkeypatch.setattr(module, "AuditQueue", Queue)
    monkeypatch.setattr(module, "build_audit_event", lambda kind, payload: payload)
    monkeypatch.setattr(module, "fetch_all_events_ordered", lambda conn: list(range(state.rows)))
    monkeypatch.setattr(module, "verify_chain", lambda rows: (not state.tampered, 0 if state.tampered else None))
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda dsn, autocommit=False: Connection()
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    import audit.postgres_worker as worker_module

    monkeypatch.setattr(worker_module, "PostgresWorker", Worker)

    def service(command, name):
        if not command:
            return False
        up = "start" in command
        if name == "redis":
            state.redis_up = up
        else:
            state.postgres_up = up
        return True

    monkeypatch.setattr(module, "service", service)
    return module


def test_every_scenario_passes_when_the_plumbing_holds(tmp_path, monkeypatch, capsys):
    state = _State()
    module = _setup(monkeypatch, state)
    report_path = tmp_path / "out" / "report.json"
    code = module.main(["--report", str(report_path), "--events", "5", "--stop-cmd", "stop {service}", "--start-cmd", "start {service}"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    scenarios = report["scenarios"]
    assert scenarios["flow"]["passed"] and scenarios["tamper"]["detected"] and scenarios["postgres_outage"]["worker_raised_during_outage"]
    assert scenarios["postgres_outage"]["rows_written_after_restart"] == 20 and scenarios["redis_outage"]["pushes_accepted_while_down"] == 0
    assert code == 0 and report["all_passed"] is True and '"flow": true' in capsys.readouterr().out


def test_a_failed_recovery_and_no_outage_commands_are_reported_not_faked(tmp_path, monkeypatch):
    state = _State()
    module = _setup(monkeypatch, state, tamper_row=False, recover_fails=True)
    assert module.main(["--report", str(tmp_path / "a.json"), "--events", "3", "--stop-cmd", "stop {service}", "--start-cmd", "start {service}"]) == 1
    report = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert "tamper" not in report["scenarios"] and report["scenarios"]["postgres_outage"]["recover_error"] == "OSError: still down"

    state = _State()
    module = _setup(monkeypatch, state)
    assert module.main(["--report", str(tmp_path / "b.json"), "--events", "3"]) == 1
    report = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert report["scenarios"]["redis_outage"] == {"passed": None, "reason": "not run: no --stop-cmd and --start-cmd"}


def test_it_needs_both_services_configured(monkeypatch, capsys):
    module = load_script("field_test_services")
    monkeypatch.setattr(module, "secret_env", lambda name, default: "")
    assert module.main(["--report", "unused.json"]) == 2 and "AETHER_REDIS_URL" in capsys.readouterr().err


def test_drain_chain_report_and_service_helpers(monkeypatch):
    module = load_script("field_test_services")
    counts = iter([3, 2, 0, 9])
    assert module.drain(SimpleNamespace(run_once=lambda: next(counts))) == 5
    endless = SimpleNamespace(run_once=lambda: 1)
    assert module.drain(endless, limit=4) == 4
    monkeypatch.setattr(module, "fetch_all_events_ordered", lambda conn: [1, 2])
    monkeypatch.setattr(module, "verify_chain", lambda rows: (True, None))
    assert module.chain_report(None) == {"rows": 2, "valid": True, "first_broken": None}
    assert module.service(None, "redis") is False
    commands = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0))
    assert module.service("docker compose stop {service}", "redis") is True and commands == ["docker compose stop redis"]


@pytest.fixture(autouse=True)
def _restore_modules():
    yield
    sys.modules.pop("_script_field_test_services", None)
