"""scripts/lean_smoke/field_test.py's runtime (V6.6.6, #359): the project copy, the docker helpers, waiting for a bar, the run summary, the audit facts and the
three-run `main()`, with docker, the clock, the worker process and the services replaced by fakes."""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from script_loader import load_script


@pytest.fixture
def module(monkeypatch, tmp_path):
    field_test = load_script("lean_smoke/field_test")
    monkeypatch.setattr(field_test, "ROOT", tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    return field_test


def _done(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_run_captures_text_output(module):
    result = module.run([sys.executable, "-c", "print('hello')"])
    assert result.returncode == 0 and "hello" in result.stdout


def test_the_project_copy_leaves_out_data_state_and_caches(module, tmp_path):
    repo = module.ROOT
    (repo / "data").mkdir()
    (repo / "data" / "big.csv").write_text("x", encoding="utf-8")
    (repo / "risk").mkdir()
    (repo / "risk" / "kill.py").write_text("x", encoding="utf-8")
    (repo / "main.py").write_text("x", encoding="utf-8")
    module.copy_project(tmp_path / "project")
    assert (tmp_path / "project" / "main.py").exists() and (tmp_path / "project" / "risk" / "kill.py").exists() and not (tmp_path / "project" / "data").exists()


def test_the_engine_container_is_started_or_the_failure_is_raised(module, monkeypatch, tmp_path):
    commands = []
    outcomes = iter([_done(), _done(), _done(), _done(), _done(), _done(1, stderr="no image")])
    monkeypatch.setattr(module, "run", lambda command, **kwargs: commands.append(command) or next(outcomes))
    module.engine("aq", tmp_path / "project", tmp_path / "results", tmp_path / "launcher.json", account="paper-a")
    assert commands[0][:3] == ["docker", "rm", "-f"] and "AQ_ACCOUNT=paper-a" in commands[1] and (tmp_path / "results").is_dir()
    commands.clear()
    module.engine("aq", tmp_path / "project", tmp_path / "results", tmp_path / "launcher.json")
    with pytest.raises(SystemExit, match="docker run failed: no image"):
        module.engine("aq", tmp_path / "project", tmp_path / "results", tmp_path / "launcher.json")


def test_logs_and_liveness_come_from_docker(module, monkeypatch):
    monkeypatch.setattr(module, "run", lambda command, **kwargs: _done(stdout="out ", stderr="err") if command[1] == "logs" else _done(stdout="true\n"))
    assert module.logs("aq") == "out err" and module.alive("aq") is True
    monkeypatch.setattr(module, "run", lambda command, **kwargs: _done(stdout="false\n"))
    assert module.alive("aq") is False
    monkeypatch.setattr(module, "run", lambda command, **kwargs: SimpleNamespace(stdout=None, stderr=None))
    assert module.logs("aq") == ""


def _clock(monkeypatch, module, *, step=10.0):
    now = {"t": 0.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now["t"] += seconds

    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: now["t"], sleep=sleep))
    return slept


def test_waiting_for_a_bar_ends_on_the_bar_a_dead_engine_or_the_deadline(module, monkeypatch):
    slept = _clock(monkeypatch, module)
    states = iter([[{"bar": "3"}], [{"bar": "9"}]])
    monkeypatch.setattr(module, "parse_field_test_log", lambda text: next(states))
    monkeypatch.setattr(module, "logs", lambda name: "")
    monkeypatch.setattr(module, "alive", lambda name: True)
    assert module.wait_for_bar("aq", 9, 1000.0) == [{"bar": "9"}] and slept == [20]
    monkeypatch.setattr(module, "parse_field_test_log", lambda text: [{"bar": "1"}])
    monkeypatch.setattr(module, "alive", lambda name: False)
    assert module.wait_for_bar("aq", 9, 1000.0) == [{"bar": "1"}]
    monkeypatch.setattr(module, "alive", lambda name: True)
    assert module.wait_for_bar("aq", 9, 0.0) == [{"bar": "1"}]


def test_stopping_an_engine_saves_its_log_twice_and_removes_it(module, monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(module, "run", lambda command, **kwargs: commands.append(command) or _done())
    texts = iter(["before", "after"])
    monkeypatch.setattr(module, "logs", lambda name: next(texts))
    out = tmp_path / "engine.log"
    assert module.stop("aq", out) == "after" and out.read_text(encoding="utf-8") == "after" and commands[0][:2] == ["docker", "stop"] and commands[1][:3] == ["docker", "rm", "-f"]


def test_a_run_is_summarized_from_its_events(module):
    events = [
        {"event": "order_event", "status": "Submitted"}, {"event": "order_event", "status": "Filled"}, {"event": "order_event", "status": "PartiallyFilled"},
        {"event": "shock", "bar": "12"}, {"event": "kill_switch_tripped", "bar": "14"}, {"event": "first_reconciliation", "breach": "True", "bar": "2"},
        {"event": "reconciliation_breach", "bar": "5"}, {"event": "gross", "bar": "15", "value": "0.9"}, {"event": "gross", "bar": "20", "risk": "0.0", "value": "0.3"},
        {"event": "gross", "bar": "21", "value": "0.1"},
    ]
    summary = module.summarize_run(events)
    assert summary["orders_submitted"] == 1 and summary["orders_filled"] == 1 and summary["shock_bar"] == 12 and summary["kill_switch_trip_bar"] == 14
    assert summary["gross_after_trip"] == 0.1 and summary["reconciliation_breach"] is True and summary["first_reconciliation_breach"] is True and summary["bars_seen"] == 21
    empty = module.summarize_run([])
    assert empty["shock_bar"] is None and empty["kill_switch_trip_bar"] is None and empty["gross_after_trip"] is None and empty["first_reconciliation_breach"] is None and empty["bars_seen"] == 0


def test_the_audit_chain_is_read_from_postgres_and_verified(module, monkeypatch):
    import audit.hash_chain as hash_chain
    import audit.postgres_audit as postgres_audit

    class Connection:
        def __enter__(self):
            return "conn"

        def __exit__(self, *args):
            return False

    stub = types.ModuleType("psycopg")
    stub.connect = lambda dsn: Connection()
    monkeypatch.setitem(sys.modules, "psycopg", stub)
    rows = [
        {"payload": json.dumps({"account_id": "paper-a", "event": "reconciliation_breach"})}, {"payload": {"account_id": "paper-b", "event": "kill_switch_tripped"}},
        {"payload": None}, {"payload": json.dumps(["not", "a", "dict"])},
    ]
    monkeypatch.setattr(postgres_audit, "fetch_all_events_ordered", lambda conn: rows)
    monkeypatch.setattr(hash_chain, "verify_chain", lambda found: (True, None))
    facts = module.audit_facts()
    assert facts["audit_chain_valid"] is True and facts["audit_entries"] == 4 and facts["account_ids_in_audit"] == ["paper-a", "paper-b"]
    assert facts["reconciliation_audit_event"] is True and facts["kill_switch_audit_event"] is True


class _Worker:
    terminated = False

    def terminate(self):
        _Worker.terminated = True


def _main_world(module, monkeypatch, tmp_path, *, make_status=0, audit_raises=False, distinct=True, all_passed=True):
    repo = module.ROOT
    (repo / "accounts.example.json").write_text("{}", encoding="utf-8")
    (repo / "lean.json").write_text("{}", encoding="utf-8")
    calls = []
    clock = {"t": 0.0}
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock["t"], sleep=lambda seconds: None))
    monkeypatch.setattr(module, "run", lambda command, **kwargs: calls.append(command) or _done(make_status, stderr="config failed"))
    monkeypatch.setattr(module.subprocess, "Popen", lambda command, **kwargs: _Worker())
    monkeypatch.setattr(module, "copy_project", lambda target: (target / "visualization").mkdir(parents=True) if False else target.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(module, "engine", lambda *args, **kwargs: calls.append(("engine", args[0])))
    monkeypatch.setattr(module, "wait_for_bar", lambda name, bar, deadline: [{"event": "order_event", "status": "Submitted", "bar": str(bar)}])
    monkeypatch.setattr(module, "alive", lambda name: True)
    monkeypatch.setattr(module, "stop", lambda name, out: calls.append(("stop", name)) or "")
    if distinct:
        original_stop = module.stop

        def stop_and_make(name, out):
            for account in ("paper-a", "paper-b"):
                (tmp_path / "work" / "project" / "state" / "accounts" / account).mkdir(parents=True, exist_ok=True)
            return original_stop(name, out)

        monkeypatch.setattr(module, "stop", stop_and_make)
    if audit_raises:
        monkeypatch.setattr(module, "audit_facts", lambda: (_ for _ in ()).throw(RuntimeError("no postgres")))
    else:
        monkeypatch.setattr(module, "audit_facts", lambda: {"reconciliation_audit_event": True})
    monkeypatch.setattr(module, "judge_field_test", lambda evidence: {"checks": {"plumbing": {"status": "pass"}}, "passed": 1, "total": 1, "all_passed": all_passed})
    return calls


def _args(tmp_path):
    return ["--out-dir", str(tmp_path / "out"), "--work-dir", str(tmp_path / "work"), "--bars", "5", "--minutes-per-run", "1"]


def test_the_three_run_field_test_writes_its_report(module, monkeypatch, tmp_path, capsys):
    calls = _main_world(module, monkeypatch, tmp_path)
    (tmp_path / "work" / "project").mkdir(parents=True)
    assert module.main(_args(tmp_path)) == 0
    report = json.loads(next((tmp_path / "out").rglob("report.json")).read_text(encoding="utf-8"))
    assert report["evidence"]["state_dirs_distinct"] is True and report["evidence"]["runs"][0]["reconciliation_audit_event"] is True and _Worker.terminated is True
    assert ("engine", "aq_field_test_b") in calls and "1/1 checks passed" in capsys.readouterr().out


def test_a_missing_audit_service_is_recorded_and_a_failed_check_exits_one(module, monkeypatch, tmp_path):
    _main_world(module, monkeypatch, tmp_path, audit_raises=True, distinct=False, all_passed=False)
    assert module.main(_args(tmp_path)) == 1
    evidence = json.loads(next((tmp_path / "out").rglob("report.json")).read_text(encoding="utf-8"))["evidence"]
    assert evidence["audit_error"].startswith("RuntimeError") and evidence["state_dirs_distinct"] is False and evidence["state_dirs"] == []


def test_a_config_writer_that_fails_stops_the_field_test(module, monkeypatch, tmp_path):
    _main_world(module, monkeypatch, tmp_path, make_status=1)
    with pytest.raises(SystemExit, match="config failed"):
        module.main(_args(tmp_path))
    assert Path(tmp_path / "out").exists()
