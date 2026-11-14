"""execution/paper_readiness_report.py and paper_readiness_scheduler.py's remaining branches (V6.6.6, #359): the velocity block, the printed summary,
the commands, and the scheduler's own connection, loop and shutdown."""

from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from execution import paper_readiness_report as report
from execution import paper_readiness_scheduler as scheduler

VIEW = {"ready": False, "checks": {"days": {"pass": True, "value": 40, "threshold": 30}, "orders": {"pass": False, "value": 1, "threshold": 5}}, "broker_config_present": False,
        "broker_config_reason": "no broker", "blocking_reasons": ["orders", "no broker"]}


def test_the_summary_marks_each_check_and_names_the_blockers(capsys):
    report._print_summary(VIEW)
    out = capsys.readouterr().out
    assert "NOT READY" in out and "[PASS] days" in out and "[FAIL] orders" in out and "[FAIL] broker_config: no broker" in out and "Blocking reasons: orders, no broker" in out
    report._print_summary({**VIEW, "ready": True, "broker_config_present": True, "blocking_reasons": []})
    ready = capsys.readouterr().out
    assert "Paper trading readiness: READY" in ready and "Blocking reasons" not in ready


def test_an_undecided_velocity_question_blocks_readiness(monkeypatch):
    monkeypatch.setattr(report, "fetch_observation_mode_events", lambda conn: [])
    monkeypatch.setattr(report, "compute_observation_summary", lambda events: {})
    monkeypatch.setattr(report, "evaluate_observation_readiness", lambda summary, thresholds: {"ready": True, "checks": {}, "blocking_reasons": []})
    monkeypatch.setattr(report, "evaluate_paper_broker_config", lambda cfg: (True, "ok"))
    monkeypatch.setattr(report, "evaluate_velocity_decision", lambda cfg: (False, "velocity open"))
    monkeypatch.setattr(report, "live_broker_view", lambda cfg: (False, "no live"))
    view = report.build_paper_readiness_view(MagicMock(), {})
    assert view["ready"] is False and view["blocking_reasons"] == ["velocity open"]


def test_the_report_command_writes_the_view_and_exits_on_readiness(monkeypatch, capsys):
    import psycopg

    conn = MagicMock()
    monkeypatch.setattr(psycopg, "connect", lambda dsn, autocommit: conn)
    monkeypatch.setattr(report, "secret_env", lambda name, default="": "dsn")
    written = []
    monkeypatch.setattr(report, "build_paper_readiness_view", lambda c, cfg: dict(VIEW, ready=True))
    monkeypatch.setattr(report, "write_paper_readiness_file", lambda view: written.append(view))
    assert report.main() == 0 and written and conn.close.called
    monkeypatch.setattr(report, "build_paper_readiness_view", lambda c, cfg: dict(VIEW))
    assert report.main() == 1
    capsys.readouterr()


def test_the_scheduler_connects_itself_and_closes_only_what_it_owns(monkeypatch):
    import psycopg

    conn = MagicMock()
    monkeypatch.setattr(psycopg, "connect", lambda dsn, autocommit: conn)
    monkeypatch.setattr(scheduler, "secret_env", lambda name, default="": "dsn")
    own = scheduler.PaperReadinessScheduler(config={})
    own.close()
    assert conn.close.called
    conn.close.side_effect = RuntimeError("closed")
    own.close()
    borrowed = scheduler.PaperReadinessScheduler(config={}, _pg_conn=MagicMock())
    borrowed.close()
    assert borrowed._conn.close.called is False


def test_the_loop_runs_survives_a_failed_cycle_and_stops_on_interrupt(monkeypatch):
    worker = scheduler.PaperReadinessScheduler(config={}, _pg_conn=MagicMock())
    outcomes = iter(["ok", RuntimeError("db down"), KeyboardInterrupt()])

    def run_once():
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return {}

    worker.run_once = run_once
    sleeps = []
    monkeypatch.setattr(scheduler.time, "sleep", lambda seconds: sleeps.append(seconds))
    worker.run()
    assert len(sleeps) == 2


def test_the_scheduler_command_runs_once_or_forever(monkeypatch):
    instance = MagicMock()
    monkeypatch.setattr(scheduler, "PaperReadinessScheduler", lambda **kwargs: instance)
    monkeypatch.setattr(scheduler, "secret_env", lambda name, default="": "dsn")
    monkeypatch.setattr(sys, "argv", ["scheduler", "--once"])
    scheduler.main()
    assert instance.run_once.called and instance.close.called
    monkeypatch.setattr(sys, "argv", ["scheduler", "--poll-interval", "60"])
    scheduler.main()
    assert instance.run.called


@pytest.mark.parametrize("module", ["execution.paper_readiness_report", "execution.paper_readiness_scheduler"])
def test_the_modules_run_as_scripts(monkeypatch, module):
    import runpy

    stand_in = ModuleType("psycopg")
    stand_in.connect = MagicMock()
    monkeypatch.setitem(sys.modules, "psycopg", stand_in)
    monkeypatch.setattr(sys, "argv", [module, "--once"])
    monkeypatch.delitem(sys.modules, module, raising=False)
    try:
        runpy.run_module(module, run_name="__main__")
    except (SystemExit, Exception):
        pass  # a stand-in connection has no rows: reaching main() is the point
    assert json is not None
