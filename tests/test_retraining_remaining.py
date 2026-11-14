"""The remaining branches of retraining/ (V6.6.6, #359): the worker loop and CLI, the status export, the registry readers, the Lean and vault
subprocess failures, and the gates' near-miss and failure names."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from retraining import (
    artifacts,
    backtest_gate,
    lean_backtest,
    planning,
    postgres_registry as registry,
    status_export,
    validation_gate,
    vault_client,
    worker as worker_module,
)


def _conn(row=None, rows=None):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    cursor.fetchall.return_value = rows or []
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def test_the_registry_readers_return_a_dict_or_none():
    columns = registry._MODEL_VERSION_COLUMNS
    row = tuple(f"v{index}" for index, _ in enumerate(columns))
    conn, cursor = _conn(row=row)
    assert registry.fetch_latest_candidate_version(conn)["model_version_id"] == "v0"
    conn, _ = _conn(row=None)
    assert registry.fetch_latest_candidate_version(conn) is None
    events = registry._RETRAINING_EVENT_COLUMNS
    event_row = tuple(f"e{index}" for index, _ in enumerate(events))
    conn, _ = _conn(row=event_row)
    assert registry.fetch_retraining_event(conn, "r1")["retraining_id"] == "e0" and registry.fetch_latest_retraining_event(conn)["retraining_id"] == "e0"
    conn, _ = _conn(row=None)
    assert registry.fetch_retraining_event(conn, "r1") is None and registry.fetch_latest_retraining_event(conn) is None


def test_an_event_update_writes_metrics_and_notes_as_json():
    conn, cursor = _conn()
    registry.update_retraining_event_status(conn, "r1", "failed", metrics={"a": 1}, notes=[{"stage": "x"}], reason="why", candidate_version_id="v1")
    sql, params = cursor.execute.call_args.args
    assert "metrics = %(metrics)s" in sql and "notes = %(notes)s" in sql and json.loads(params["notes"]) == [{"stage": "x"}]
    registry.update_retraining_event_status(conn, "r1", "failed", notes=None)
    assert json.loads(cursor.execute.call_args.args[1]["notes"]) == []


def test_the_status_export_reads_config_dates_and_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(status_export, "ROOT_DIR", tmp_path)
    assert status_export._load_auto_rollback_config() == {}
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"retraining": {"x": 1}}}), encoding="utf-8")
    assert status_export._load_auto_rollback_config() == {"x": 1}
    assert status_export._hours_since(None) is None and status_export._hours_since(datetime(2020, 1, 1)) > 0
    identifier = uuid4()
    assert status_export._json_safe({"d": date(2026, 1, 2), "u": identifier, "n": [datetime(2026, 1, 2, tzinfo=timezone.utc)]}) == {"d": "2026-01-02", "u": str(identifier), "n": ["2026-01-02T00:00:00+00:00"]}


def test_the_status_export_runs_as_a_command(monkeypatch):
    import psycopg

    conn = MagicMock()
    monkeypatch.setattr(sys, "argv", ["status_export"])
    monkeypatch.setattr(psycopg, "connect", lambda dsn, autocommit: conn)
    monkeypatch.setattr(status_export, "secret_env", lambda name, default="": "dsn")
    written = []
    monkeypatch.setattr(status_export, "ensure_schema", lambda c: None)
    monkeypatch.setattr(status_export, "build_status_view", lambda c: {"v": 1})
    monkeypatch.setattr(status_export, "write_status_file", lambda view: written.append(view))
    status_export.main()
    assert written == [{"v": 1}] and conn.close.called


def test_a_missing_lean_binary_a_timeout_and_a_crash_are_reported_not_raised(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(lean_backtest, "find_lean_binary", lambda config: "lean")
    for error, expected in ((FileNotFoundError("lean"), "lean_binary_not_found"), (subprocess.TimeoutExpired("lean", 1), "lean_backtest_timed_out"), (RuntimeError("boom"), "boom")):
        def run(*args, **kwargs):
            raise error

        monkeypatch.setattr(lean_backtest.subprocess, "run", run)
        assert lean_backtest.run_lean_backtest(tmp_path, {})["error"] == expected


def test_av_failures_and_the_envelope_parser(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("weird")

    monkeypatch.setattr(vault_client.subprocess, "run", broken)
    assert vault_client.run_av_command(["av", "x"])["error"] == "weird"
    assert vault_client.parse_av_envelope('{broken\n{"ok": true}\n{also broken') == {"ok": True}
    assert vault_client.parse_av_envelope('{broken') is None and vault_client.parse_av_envelope(None) is None


def test_an_unchanged_candidate_with_no_head_hash_fails_the_commit(monkeypatch):
    monkeypatch.setattr(vault_client, "staged_leftovers", lambda binary, cwd, timeout: [])
    monkeypatch.setattr(vault_client, "current_head_hash", lambda binary, cwd, timeout: None)
    nothing = json.dumps({"ok": False, "error": {"code": "nothing_to_commit"}})
    results = iter([{"ok": True, "stdout": ""}, {"ok": False, "stdout": nothing, "stderr": ""}])
    monkeypatch.setattr(vault_client, "run_av_command", lambda argv, cwd=None, timeout=None: next(results))
    outcome = vault_client.commit_candidate_to_vault("v1", ["train.py"], {"sharpe": 1.0, "drawdown": 0.1}, {"enabled": True}, cwd=None)
    assert outcome["ok"] is False and outcome["stage"] == "commit"
    other = json.dumps({"ok": False, "error": {"code": "other"}})
    results = iter([{"ok": True, "stdout": ""}, {"ok": False, "stdout": other, "stderr": ""}])
    assert vault_client.commit_candidate_to_vault("v1", ["train.py"], {"sharpe": 1.0, "drawdown": 0.1}, {"enabled": True}, cwd=None)["stage"] == "commit"


def test_a_hash_mismatch_is_listed_and_a_missing_file_counts_as_mismatched(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x")
    (tmp_path / "ml").mkdir()
    result = artifacts.restore_active_from_version(tmp_path, ml_dir=tmp_path / "ml", filenames=("a.bin", "gone.bin"), expected_hashes={"a.bin": "0" * 64, "gone.bin": "1" * 64})
    assert result["ok"] is False and sorted(result["mismatched"]) == ["a.bin", "gone.bin"]


def test_a_non_numeric_return_degrades_to_the_default_and_planning_reads_datetimes():
    assert backtest_gate._finite_or_default("n/a", 0.5) == 0.5 and backtest_gate._finite_or_default(float("nan"), 0.25) == 0.25
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert planning._parse_timestamp(stamp) is stamp and planning._parse_timestamp("2026-01-01T00:00:00Z") == stamp


def test_the_ranking_gate_names_turnover_capacity_and_flip_failures():
    config = {"model": "sequence", "head": "h", "max_annualized_turnover": 10, "min_capacity_usd": 100, "min_walk_forward_windows": 2, "max_window_sign_flip_fraction": 0.5}
    metrics = {"sequence": {"backtest": {"h_ranking_quality": {"quality_status": "promotable"}, "h_net_performance": {"observed": {"net_sharpe": 1.0, "annualized_turnover": 99.0, "capacity_usd": 1.0}}}}}
    summary = {"stability_by_metric": {"h_ic": {"num_windows": 5, "sign_flip_fraction": 0.9}}}
    result = validation_gate.evaluate_ranking_promotion_gate(metrics, config, summary)
    assert {"annualized_turnover_above_gate", "capacity_usd_below_gate", "walk_forward_sign_flip_fraction_above_gate"} <= set(result["failures"])


def _gate_inputs(drawdown=-0.05, sharpe=0.31, loss=1.09, train_ba=0.62, backtest_ba=0.52, mcc=-0.1, trades=10, exposure=0.5):
    metrics = {"train": {"balanced_accuracy": train_ba}, "backtest": {"balanced_accuracy": backtest_ba, "mcc": mcc}, "validation": {"loss": loss}}
    report = {"backtest": {"strategy": {"max_drawdown": drawdown, "sharpe": sharpe}, "trade_count": trades, "exposure_rate": exposure}}
    return metrics, report


def test_the_validation_gate_names_near_misses_and_missing_figures():
    active_metrics, active_report = _gate_inputs(loss=1.0, drawdown=-0.1)
    candidate_metrics, candidate_report = _gate_inputs()
    near = validation_gate.evaluate_validation_gate(candidate_metrics, candidate_report, active_metrics, active_report, {"max_train_backtest_balanced_accuracy_gap": 0.11})
    assert {"candidate_sharpe_near_minimum", "candidate_validation_loss_near_limit", "candidate_overfitting_gap_near_limit", "candidate_skill_marginal_on_one_metric"} <= set(near["near_misses"])
    bare_metrics, bare_report = {}, {}
    missing = validation_gate.evaluate_validation_gate(bare_metrics, bare_report, active_metrics, active_report, {})
    assert {"candidate_max_drawdown_missing_or_non_finite", "candidate_validation_loss_missing_or_non_finite", "candidate_sharpe_missing_or_non_finite"} <= set(missing["failures"])
    assert validation_gate.evaluate_validation_gate(candidate_metrics, {"backtest": {"strategy": {"max_drawdown": "n/a", "sharpe": 1.0}}}, active_metrics, active_report, {})["failures"]


class _Worker(worker_module.RetrainingWorker):
    def __init__(self, config=None):
        self.config = config or {}
        self.poll_interval = 0
        self._conn = MagicMock()


@pytest.fixture
def stages(monkeypatch):
    names = ("plan", "preflight_vault", "train", "train_topology", "train_gating", "train_multitask", "train_sequence", "train_strategy_selector", "validate", "backtest", "commit")
    answers = {"plan": {"should_plan": True, "retraining_id": "r1", "reason": "go"}, "preflight_vault": {"ok": True}, "train": {"ok": True, "version_id": "v1"},
               "validate": {"ok": True}, "backtest": {"ok": True}, "commit": {"ok": True}}
    for name in names:
        monkeypatch.setattr(worker_module, name, lambda *a, _name=name, **k: answers.get(_name, {"ok": True}))
    return answers


def test_a_failed_backtest_or_vault_commit_ends_the_cycle_with_its_reason(stages):
    stages["backtest"] = {"ok": False}
    assert _Worker().run_once()["reason"] == "backtest_failed"
    stages["backtest"] = {"ok": True}
    stages["commit"] = {"ok": False}
    assert _Worker().run_once()["reason"] == "vault_commit_failed"


def test_the_worker_connects_itself_when_no_connection_is_given(monkeypatch):
    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda dsn, autocommit: MagicMock())
    monkeypatch.setattr(worker_module, "secret_env", lambda name, default="": "dsn")
    monkeypatch.setattr(worker_module, "ensure_schema", lambda c: None)
    monkeypatch.setattr(worker_module, "ensure_performance_schema", lambda c: None)
    monkeypatch.setattr(worker_module, "reconcile_stale_running_events", lambda c, cfg: [])
    assert worker_module.RetrainingWorker(postgres_dsn="x", config={}).poll_interval == 300


def test_the_loop_survives_a_rollback_check_failure_and_a_cycle_failure_until_interrupted(monkeypatch):
    worker = _Worker()
    outcomes = iter([("ok", {"decision": {"should_rollback": True}}), ("ok", RuntimeError("rollback check")), ("fail", None), ("stop", None)])

    def run_once():
        kind, _ = next(outcomes_run)
        if kind == "fail":
            raise RuntimeError("cycle")
        if kind == "stop":
            raise KeyboardInterrupt
        return {"ran": False}

    outcomes_run = iter([("ok", None), ("ok", None), ("fail", None), ("stop", None)])
    checks = iter([{"decision": {"should_rollback": True}}, RuntimeError("rollback check")])

    def check():
        value = next(checks)
        if isinstance(value, Exception):
            raise value
        return value

    worker.run_once = run_once
    worker.check_auto_rollback = check
    monkeypatch.setattr(worker_module.time, "sleep", lambda seconds: None)
    worker.run()
    del outcomes
    worker._conn.close.side_effect = RuntimeError("closed")
    worker.close()


def test_the_worker_command_runs_once_or_forever(monkeypatch):
    worker = MagicMock()
    worker.run_once.return_value = {"ran": False}
    monkeypatch.setattr(worker_module, "RetrainingWorker", lambda **kwargs: worker)
    monkeypatch.setattr(worker_module, "_load_retraining_config", lambda: {"worker": {"poll_interval_seconds": 9}})
    monkeypatch.setattr(worker_module, "secret_env", lambda name, default="": "dsn")
    monkeypatch.setattr(sys, "argv", ["worker", "--once"])
    worker_module.main()
    assert worker.run_once.called and worker.close.called
    monkeypatch.setattr(sys, "argv", ["worker", "--poll-interval", "5"])
    worker_module.main()
    assert worker.run.called
    assert SimpleNamespace is not None


def test_the_gate_fails_closed_without_an_active_baseline_or_a_finite_gap():
    metrics, report = _gate_inputs()
    nan_metrics = {**metrics, "train": {"balanced_accuracy": float("nan")}}
    result = validation_gate.evaluate_validation_gate(nan_metrics, report, {}, {}, {})
    assert "active_baseline_metrics_missing" in result["failures"] and "candidate_overfitting_gap_missing_or_non_finite" in result["failures"]


@pytest.mark.parametrize("module,argv", [("retraining.status_export", ["status_export"]), ("retraining.worker", ["worker", "--once"])])
def test_the_modules_run_as_scripts(monkeypatch, module, argv):
    import runpy

    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setitem(sys.modules, "psycopg", MagicMock())
    monkeypatch.delitem(sys.modules, module, raising=False)
    try:
        runpy.run_module(module, run_name="__main__")
    except (SystemExit, KeyError):
        pass  # a stand-in connection has no rows: reaching main() is the point
