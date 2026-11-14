"""retraining/orchestrator.py's remaining stages and CLI (V6.6.6, #359): plan, the best-effort trainers' failure paths, validate, backtest,
the vault commit, the CLI dispatch. Postgres, the subprocesses and the vault are stubbed."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from retraining import orchestrator as orch


@pytest.fixture
def db(monkeypatch):
    calls = SimpleNamespace(event=[], version=[])
    monkeypatch.setattr(orch, "update_retraining_event_status", lambda conn, rid, **kw: calls.event.append((rid, kw)))
    monkeypatch.setattr(orch, "update_model_version_status", lambda conn, vid, **kw: calls.version.append((vid, kw)))
    return calls


def test_the_config_and_json_helpers_read_what_is_there(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"phase_v2": {"retraining": {"a": 1}}}), encoding="utf-8")
    assert orch._load_retraining_config(config) == {"a": 1}
    config.write_text("{}", encoding="utf-8")
    assert orch._load_retraining_config(config) == {}
    assert orch._load_json_if_exists(tmp_path / "none.json") == {}
    assert orch._load_json_if_exists(config) == {}


def test_connect_prepares_both_schemas(monkeypatch):
    import psycopg

    conn = MagicMock()
    seen = []
    monkeypatch.setattr(psycopg, "connect", lambda dsn, autocommit: seen.append(dsn) or conn)
    monkeypatch.setattr(orch, "secret_env", lambda name, default="": default or "dsn")
    monkeypatch.setattr(orch, "ensure_schema", lambda c: seen.append("schema"))
    monkeypatch.setattr(orch, "ensure_performance_schema", lambda c: seen.append("performance"))
    assert orch.connect("postgres://x") is conn and seen == ["postgres://x", "schema", "performance"]


def test_plan_records_a_planned_event_only_when_the_rule_says_so(monkeypatch):
    inserted = []
    monkeypatch.setattr(orch, "fetch_candidate_triggers", lambda conn, limit: [{"trigger_id": "t1"}])
    monkeypatch.setattr(orch, "fetch_recent_retraining_events", lambda conn, since, limit: [])
    monkeypatch.setattr(orch, "count_experience_events", lambda conn: 500)
    monkeypatch.setattr(orch, "insert_retraining_event", lambda conn, row: inserted.append(row))
    verdicts = iter([{"should_plan": True, "reason": "go", "selected_trigger": {"trigger_id": "t1"}}, {"should_plan": True, "reason": "go", "selected_trigger": None},
                     {"should_plan": False, "reason": "wait"}])
    monkeypatch.setattr(orch.planning, "evaluate_retraining_plan", lambda *args: next(verdicts))
    now = datetime(2026, 11, 13, tzinfo=timezone.utc) + timedelta(hours=1)
    planned = orch.plan(MagicMock(), {}, now=now)
    assert planned["retraining_id"] and inserted[0]["source_trigger_id"] == "t1" and inserted[0]["status"] == "planned"
    assert orch.plan(MagicMock(), {})["retraining_id"] and inserted[1]["source_trigger_id"] is None
    assert "retraining_id" not in orch.plan(MagicMock(), {}) and len(inserted) == 2


def test_a_training_subprocess_that_cannot_launch_rejects_the_candidate(monkeypatch, db):
    monkeypatch.setattr(orch, "insert_model_version", lambda conn, row: None)
    monkeypatch.setattr(orch.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no python")))
    result = orch.train(MagicMock(), "r1", "v1")
    assert result == {"ok": False, "version_id": "v1", "error": "no python"}
    assert db.event[-1][1]["status"] == "failed" and db.version[-1] == ("v1", {"status": "rejected"})


@pytest.mark.parametrize("stage,key", [("train_topology", "topology_training"), ("train_gating", "gating_training"), ("train_multitask", "multitask_training"),
                                       ("train_sequence", "sequence_training"), ("train_strategy_selector", "strategy_selector_training")])
def test_the_best_effort_trainers_swallow_a_launch_failure_and_a_bad_exit(monkeypatch, db, stage, key):
    run = getattr(orch, stage)
    assert run(MagicMock(), "r1", "v1", {key: {"enabled": False}})["ok"] is False
    monkeypatch.setattr(orch.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert run(MagicMock(), "r1", "v1", {})["error"] == "boom" and db.event[-1][1]["notes"][0]["stage"] == stage
    monkeypatch.setattr(orch.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="bad"))
    assert run(MagicMock(), "r1", "v1", {}, timeout_seconds=5)["error"] == "bad" and db.event[-1][1]["notes"][0]["returncode"] == 2
    monkeypatch.setattr(orch.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="fine", stderr=""))
    assert run(MagicMock(), "r1", "v1", {key: {"timeout_seconds": 7}}) == {"ok": True, "version_id": "v1", "stdout": "fine"}


def test_validate_rejects_a_candidate_without_artifacts_or_one_the_gate_refuses(monkeypatch, db, tmp_path):
    monkeypatch.setattr(orch, "candidate_dir", lambda version_id: tmp_path / version_id)
    monkeypatch.setattr(orch, "ACTIVE_TRAINING_METRICS_PATH", tmp_path / "active_metrics.json")
    monkeypatch.setattr(orch, "ACTIVE_STRATEGY_REPORT_PATH", tmp_path / "active_report.json")
    monkeypatch.setattr(orch, "check_required_artifacts", lambda folder: (False, ["model.json"]))
    missing = orch.validate(MagicMock(), "r1", "v1", {})
    assert missing["ok"] is False and "missing_candidate_artifacts" in missing["reason"] and db.event[-1][1]["status"] == "rejected"
    monkeypatch.setattr(orch, "check_required_artifacts", lambda folder: (True, []))
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "sequence_training_metrics.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
    seen = {}
    monkeypatch.setattr(orch, "evaluate_validation_gate", lambda cm, cr, am, ar, cfg, candidate_ranking_metrics: seen.update(ranking=candidate_ranking_metrics) or {"passed": False, "failures": ["sharpe"]})
    assert orch.validate(MagicMock(), "r1", "v1", {})["ok"] is False and seen["ranking"] == {"sequence": {"x": 1}, "multitask": None}
    assert "validation_gate_failed" in db.event[-1][1]["reason"]
    monkeypatch.setattr(orch, "evaluate_validation_gate", lambda *a, **k: {"passed": True, "failures": []})
    assert orch.validate(MagicMock(), "r1", "v1", {})["ok"] is True and db.version[-1][1]["status"] == "candidate"


def test_backtest_writes_its_report_and_sets_the_status_from_the_comparison(monkeypatch, db, tmp_path):
    monkeypatch.setattr(orch, "candidate_dir", lambda version_id: tmp_path / version_id)
    monkeypatch.setattr(orch, "BACKTESTS_DIR", tmp_path / "backtests")
    monkeypatch.setattr(orch, "ACTIVE_STRATEGY_REPORT_PATH", tmp_path / "none.json")
    monkeypatch.setattr(orch, "run_lean_backtest", lambda folder, cfg: {"ran": True})
    monkeypatch.setattr(orch, "compare_backtests", lambda active, candidate, cfg: {"passed": True, "reasons": []})
    result = orch.backtest(MagicMock(), "r1", "v1", {})
    assert result["ok"] is True and (tmp_path / "backtests" / "candidate_v1_report.json").exists() and db.event[-1][1]["reason"] == "backtest_gate_passed"
    monkeypatch.setattr(orch, "compare_backtests", lambda active, candidate, cfg: {"passed": False, "reasons": ["worse"]})
    assert orch.backtest(MagicMock(), "r1", "v1", {})["ok"] is False and "backtest_gate_failed" in db.event[-1][1]["reason"] and db.version[-1][1]["status"] == "rejected"


def test_the_vault_commit_refuses_a_path_outside_the_vault_and_marks_a_failed_commit(monkeypatch, db, tmp_path):
    version_dir = tmp_path / "elsewhere" / "v1"
    version_dir.mkdir(parents=True)
    monkeypatch.setattr(orch, "candidate_dir", lambda version_id: version_dir)
    monkeypatch.setattr(orch, "ROOT_DIR", tmp_path / "root")
    (tmp_path / "root").mkdir()
    result = orch.commit(MagicMock(), "r1", "v1", {"vault": {"repo_path": "."}})
    assert result["stage"] == "path_outside_vault" and db.event[-1][1]["status"] == "failed"
    monkeypatch.setattr(orch, "ROOT_DIR", tmp_path)
    vault = {"repo_path": ".", "extra_add_paths": ["nothere.md"]}
    monkeypatch.setattr(orch, "commit_candidate_to_vault", lambda *a, **k: {"ok": False, "stage": "push", "steps": {"push": {"ok": False}}})
    assert orch.commit(MagicMock(), "r1", "v1", {"vault": vault})["stage"] == "push" and db.event[-1][1]["notes"][0]["stage"] == "commit"
    monkeypatch.setattr(orch, "compute_artifact_hashes", lambda folder, filenames: {"a": "h"})
    (version_dir / "strategy_report.json").write_text(json.dumps({"backtest": {"strategy": {"sharpe": 1.2, "max_drawdown": 0.1}}}), encoding="utf-8")
    monkeypatch.setattr(orch, "commit_candidate_to_vault", lambda *a, **k: {"ok": True, "stage": "done", "vault_commit": "abc", "push_state": "pushed", "steps": {}})
    assert orch.commit(MagicMock(), "r1", "elsewhere/v1", {"vault": vault})["vault_commit"] == "abc" and db.event[-1][1]["reason"] == "vault_commit_succeeded"
    disabled = orch.commit(MagicMock(), "r1", "v1", {"vault": {"enabled": False, "repo_path": "."}})
    assert disabled["stage"] == "disabled" and db.version[-1][1]["aether_vault_commit"] is None


def test_the_preflight_and_generation_switch(monkeypatch, db, tmp_path):
    monkeypatch.setattr(orch, "vault_preflight", lambda cfg, cwd: {"ok": False, "reason": "dirty"})
    assert orch.preflight_vault(MagicMock(), "r1", {})["ok"] is False and db.event[-1][1]["notes"][0]["reason"] == "dirty"
    monkeypatch.setattr(orch, "ML_DIR", tmp_path)
    assert orch._generations_enabled() is False
    (tmp_path / "generations").mkdir()
    (tmp_path / "generations" / "policy.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    assert orch._generations_enabled() is True


def test_promotion_with_generations_on_or_a_corrupt_candidate_stops(monkeypatch, tmp_path):
    version = {"status": "candidate", "aether_vault_commit": "abc", "artifact_hashes": {}}
    monkeypatch.setattr(orch, "fetch_model_version", lambda conn, vid: None if vid == "none" else version)
    assert orch.promote(MagicMock(), "none")["error"] == "model_version_not_found"
    monkeypatch.setattr(orch, "_generations_enabled", lambda: True)
    assert orch.promote(MagicMock(), "v1")["error"] == "generations_enabled_use_aq_cycle"
    monkeypatch.setattr(orch, "_generations_enabled", lambda: False)
    monkeypatch.setattr(orch, "fetch_active_model_version", lambda conn: None)
    monkeypatch.setattr(orch, "candidate_dir", lambda vid: tmp_path)
    monkeypatch.setattr(orch, "verify_version_artifacts", lambda folder, filenames, expected_hashes: {"missing": [orch.REQUIRED_CANDIDATE_FILES[0]], "mismatched": ["x"]})
    refused = orch.promote(MagicMock(), "v1", config={"promotion": {"active_artifact_files": list(orch.REQUIRED_CANDIDATE_FILES)}})
    assert refused["error"] == "candidate_artifact_verification_failed" and refused["mismatched"] == ["x"]


def test_hours_since_handles_a_missing_and_a_naive_timestamp():
    assert orch._hours_since(None) is None
    assert 0.0 <= orch._hours_since(datetime.utcnow().replace(tzinfo=None) - timedelta(minutes=1)) < 24 * 7


def test_status_and_auto_rollback_assemble_their_inputs(monkeypatch):
    written = []
    monkeypatch.setattr(orch, "build_status_view", lambda conn: {"view": 1})
    monkeypatch.setattr(orch, "write_status_file", lambda view: written.append(view))
    assert orch.status(MagicMock()) == {"view": 1} and written == [{"view": 1}]
    monkeypatch.setattr(orch, "fetch_active_model_version", lambda conn: None)
    monkeypatch.setattr(orch, "fetch_rollback_candidates", lambda conn: [{"status": "rolled_back", "updated_at": datetime.now(timezone.utc) - timedelta(hours=2)}])
    monkeypatch.setattr(orch, "select_rollback_target", lambda active, history, signals, cfg: {"should_rollback": False})
    result = orch.auto_rollback_status(MagicMock(), {}, degradation_overrides={"kill_switch_tripped": True})
    assert result["active_version_id"] is None and result["degradation_signals"]["bars_since_last_rollback"] > 1.9 and result["degradation_signals"]["kill_switch_tripped"] is True


@pytest.mark.parametrize("stage,extra,function", [
    ("plan", [], "plan"), ("train", ["--retraining-id", "r1"], "train"), ("train_topology", ["--retraining-id", "r1", "--version-id", "v1"], "train_topology"),
    ("train_gating", ["--retraining-id", "r1", "--version-id", "v1"], "train_gating"), ("train_multitask", ["--retraining-id", "r1", "--version-id", "v1"], "train_multitask"),
    ("train_sequence", ["--retraining-id", "r1", "--version-id", "v1"], "train_sequence"), ("train_strategy_selector", ["--retraining-id", "r1", "--version-id", "v1"], "train_strategy_selector"),
    ("validate", ["--retraining-id", "r1", "--version-id", "v1"], "validate"), ("backtest", ["--retraining-id", "r1", "--version-id", "v1"], "backtest"),
    ("commit", ["--retraining-id", "r1", "--version-id", "v1"], "commit"), ("promote", ["--version-id", "v1"], "promote"), ("rollback", ["--to-version-id", "v0"], "rollback"),
    ("auto-rollback", ["--status"], "auto_rollback_status"), ("auto-rollback", ["--dry-run"], "auto_rollback_status"), ("status", [], "status"),
])
def test_the_command_line_runs_the_named_stage_and_closes_the_connection(monkeypatch, capsys, stage, extra, function):
    conn = MagicMock()
    monkeypatch.setattr(sys, "argv", ["orchestrator", stage, *extra])
    monkeypatch.setattr(orch, "_load_retraining_config", lambda: {})
    monkeypatch.setattr(orch, "connect", lambda: conn)
    monkeypatch.setattr(orch, function, lambda *a, **k: {"stage": stage})
    orch.main()
    assert json.loads(capsys.readouterr().out)["stage"] == stage and conn.close.called


def test_a_clean_promotion_clears_the_trade_lock_and_the_module_runs_as_a_script(monkeypatch, tmp_path):
    import runpy

    version = {"status": "candidate", "aether_vault_commit": "abc", "artifact_hashes": {}}
    monkeypatch.setattr(orch, "fetch_model_version", lambda conn, vid: version)
    monkeypatch.setattr(orch, "_generations_enabled", lambda: False)
    monkeypatch.setattr(orch, "fetch_active_model_version", lambda conn: {"model_version_id": "old"})
    monkeypatch.setattr(orch, "candidate_dir", lambda vid: tmp_path)
    monkeypatch.setattr(orch, "verify_version_artifacts", lambda folder, filenames, expected_hashes: {"missing": [], "mismatched": []})
    monkeypatch.setattr(orch, "copy_candidate_to_active", lambda folder, ml_dir, filenames: {"a": "h"})
    monkeypatch.setattr(orch, "copy_backtest_report_to_active", lambda folder, backtests: None)
    monkeypatch.setattr(orch, "promote_model_version", lambda conn, old_active_id, new_active_id: None)
    monkeypatch.setattr(orch, "update_model_version_status", lambda *a, **k: None)
    monkeypatch.setattr(orch, "update_retraining_event_status", lambda *a, **k: None)
    monkeypatch.setattr(orch, "build_status_view", lambda conn: {})
    monkeypatch.setattr(orch, "write_status_file", lambda view: None)
    cleared = []
    monkeypatch.setattr(orch, "write_manual_trade_lock_override", lambda flag, path: cleared.append(flag))
    result = orch.promote(MagicMock(), "v1", "r1", {})
    assert result["ok"] is True and cleared == [False]
    monkeypatch.setattr(sys, "argv", ["orchestrator", "status"])
    monkeypatch.setitem(sys.modules, "psycopg", MagicMock())
    with pytest.raises(Exception):
        runpy.run_module("retraining.orchestrator", run_name="__main__")
