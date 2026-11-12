"""execution/live_readiness_io.py (V6.6.5, #352): evidence from the project's own files, unknown where a file is missing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from execution.live_readiness_io import READINESS_FILE, gather_evidence, readiness_scorecard, write_scorecard

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "config.json").write_text(json.dumps({"phase_v2": {
        "risk": {"kill_switch": {"enabled": True}}, "reconciliation": {"trips_kill_switch": False}, "live": {"max_allowed_total_drawdown_pct": 0.15},
    }}), encoding="utf-8")
    return root


def test_an_empty_repo_reads_as_unknown_not_as_a_pass(tmp_path, monkeypatch):
    monkeypatch.delenv("AQ_ACCOUNTS_FILE", raising=False)
    monkeypatch.delenv("AETHER_POSTGRES_DSN", raising=False)
    monkeypatch.setattr("execution.secrets_io.keyring_get", lambda service, user: None)
    root = _repo(tmp_path)
    evidence = gather_evidence(root, forward_rows=[])
    assert evidence["kill_switch_enabled"] is True and evidence["reconciliation_trips_kill_switch"] is False
    assert evidence["accounts_valid"] is True and evidence["live_account_ok"] is False and evidence["postgres_dsn_safe"] is None
    assert "book_dsr" in evidence and evidence["book_dsr"] is None
    card = readiness_scorecard(root, forward_rows=[], now=datetime(2026, 11, 8, tzinfo=timezone.utc))
    statuses = {metric.key: metric.status for metric in card.metrics}
    assert not card.ready and statuses["kill_switch_enabled"] == "pass" and statuses["reconciliation_trips"] == "fail" and statuses["field_test"] == "unknown"
    path = write_scorecard(root, card)
    assert path == root / READINESS_FILE and json.loads(path.read_text(encoding="utf-8"))["ready"] is False


def test_evidence_files_are_read(tmp_path, monkeypatch):
    monkeypatch.delenv("AQ_ACCOUNTS_FILE", raising=False)
    monkeypatch.setattr("execution.secrets_io.keyring_get", lambda service, user: None)
    root = _repo(tmp_path)
    (root / "ml" / "evaluation" / "field_test" / "2026-11-08").mkdir(parents=True)
    (root / "ml" / "evaluation" / "field_test" / "2026-11-08" / "report.json").write_text(json.dumps(
        {"date": "2026-11-08", "judged": {"all_passed": True, "passed": 9, "total": 9}}), encoding="utf-8")
    (root / "ml" / "evaluation" / "alpha_proof.json").write_text(json.dumps({"run": "r", "periods": {"full": {"dsr": 0.05}}}), encoding="utf-8")
    (root / "ml" / "evaluation" / "v665").mkdir(parents=True)
    (root / "ml" / "evaluation" / "v665" / "mutation_summary.json").write_text(json.dumps(
        {"seed_1_after_tests": {"overall": [0.97, 1, 1]}, "seed_2_after_tests": {"overall": [0.93, 1, 1]}, "before": {"overall": [0.5, 1, 1]}}), encoding="utf-8")
    (root / "ml" / "evaluation" / "v665" / "verification.json").write_text(json.dumps({"date": "2026-11-08", "rows": [{"result": "pass"}, {"result": "skip"}]}), encoding="utf-8")
    (root / "ml" / "evaluation" / "v665" / "r_round5.json").write_text(json.dumps({"rounds": {"5A": {"pbo": 0.31}}}), encoding="utf-8")
    (root / "state" / "backups").mkdir(parents=True)
    (root / "state" / "backups" / "last_backup.json").write_text(json.dumps({"date": "2026-11-07"}), encoding="utf-8")
    evidence = gather_evidence(root, forward_rows=[])
    assert evidence["field_test"]["all_passed"] and evidence["book_dsr"] == 0.05 and evidence["mutation_score"] == 0.93
    assert evidence["verification"]["all_passed"] and evidence["round_pbo"] == 0.31 and evidence["backup_date"] == "2026-11-07"


def test_an_invalid_registry_fails_the_accounts_check(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    (root / "accounts.json").write_text(json.dumps({"accounts": [{"id": "x", "risk_overrides": {"dynamic_risk.max_leverage": 5}}]}), encoding="utf-8")
    monkeypatch.setenv("AQ_ACCOUNTS_FILE", str(root / "accounts.json"))
    (root / "config.json").write_text(json.dumps({"phase_v2": {"dynamic_risk": {"max_leverage": 1.0}}}), encoding="utf-8")
    evidence = gather_evidence(root, forward_rows=[])
    assert evidence["accounts_valid"] is False and "looser" in evidence["accounts_error"]


def test_the_real_repo_is_not_ready():
    card = readiness_scorecard(ROOT, forward_rows=[])
    assert not card.ready  # no forward record, no paper period, no broker: the scorecard says so with numbers
