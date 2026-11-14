"""The last guards of execution/ (V6.6.6, #359): readiness evidence from the forward ledger and the docs block, secrets backends that fail,
the account registry's bad documents, and the state file read by the status rows."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

import pytest

from execution import accounts, accounts_io, live_readiness, live_readiness_io, secrets_io


def test_a_torn_json_file_reads_as_nothing(tmp_path):
    (tmp_path / "x.json").write_text("{torn", encoding="utf-8")
    assert live_readiness_io._json(tmp_path / "x.json") is None and live_readiness_io._json(tmp_path / "none.json") is None


def test_the_forward_ledger_branch_is_read_or_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(live_readiness_io.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    assert live_readiness_io.forward_rows_from_branch(tmp_path) == []
    monkeypatch.setattr(live_readiness_io.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"a": 1}\n\n'))
    assert live_readiness_io.forward_rows_from_branch(tmp_path) == [{"a": 1}]
    monkeypatch.setattr(live_readiness_io.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    assert live_readiness_io.forward_rows_from_branch(tmp_path) == []
    monkeypatch.setattr(live_readiness_io.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("git", 1)))
    assert live_readiness_io.forward_rows_from_branch(tmp_path) == []


def test_the_forward_evidence_reads_a_valid_chain_or_names_why_not(tmp_path, monkeypatch):
    import evaluation.generation_ledger as ledger

    (tmp_path / "ml" / "generations").mkdir(parents=True)
    (tmp_path / "ml" / "generations" / "registry.json").write_text(json.dumps({"generations": [{"name": "g2", "stage": "active"}, {"name": "g1", "stage": "shadow"}]}), encoding="utf-8")
    rows = [{"payload": {}}]
    monkeypatch.setattr(ledger, "judge_generations", lambda rows: {"chain_valid": False, "first_broken_row": 3})
    assert "chain broken at row 3" in live_readiness_io._forward(tmp_path, rows)["forward_source"]
    monkeypatch.setattr(ledger, "judge_generations", lambda rows: {"chain_valid": True, "generations": {}})
    assert "no generation" in live_readiness_io._forward(tmp_path, rows)["forward_source"]
    monkeypatch.setattr(ledger, "judge_generations", lambda rows: {"chain_valid": True, "generations": {"g1": {"sessions": 12, "alpha": {"t_hac": 1.5}}, "g2": {"sessions": 30, "alpha": {"t_hac": 2.5}}}})
    active = live_readiness_io._forward(tmp_path, rows)
    assert active["forward_sessions"] == 30 and active["forward_alpha_t"] == 2.5 and active["forward_source"].endswith("g2")
    (tmp_path / "ml" / "generations" / "registry.json").write_text("{}", encoding="utf-8")
    assert live_readiness_io._forward(tmp_path, rows)["forward_source"].endswith("g1")


def test_the_evidence_takes_the_dsr_value_and_the_paper_check(tmp_path, monkeypatch):
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)
    (tmp_path / "ml" / "evaluation" / "alpha_proof.json").write_text(json.dumps({"run": "r1", "periods": {"full": {"dsr": {"value": 0.97}}}}), encoding="utf-8")
    evidence = live_readiness_io.gather_evidence(tmp_path, forward_rows=[], paper_check={"trading_days": 40, "rebalances": 9, "all_inside": True})
    assert evidence["book_dsr"] == 0.97 and evidence["paper_trading_days"] == 40 and evidence["paper_rebalances"] == 9 and evidence["paper_bands_all_inside"] is True


def test_the_docs_block_is_replaced_between_its_markers(tmp_path):
    start, end = live_readiness_io.DOCS_BLOCK
    page = tmp_path / "page.md"
    page.write_text(f"head\n{start}\nold\n{end}\ntail\n", encoding="utf-8")
    assert live_readiness_io.write_docs_block(page, "| new |  \n") is True
    assert page.read_text(encoding="utf-8") == f"head\n{start}\n| new |\n{end}\ntail\n"
    page.write_text("no markers", encoding="utf-8")
    assert live_readiness_io.write_docs_block(page, "x") is False


def test_the_scorecard_ages_a_bad_date_to_nothing_and_formats_floats_and_pipes():
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    assert live_readiness._age_days("not-a-date", now) is None and live_readiness._age_days(None, now) is None and live_readiness._age_days("2026-11-10", now) == 3.0
    metrics = (
        live_readiness.ReadinessMetric("a", "g", "float", 1.23456, ">= 1", "pass", "e"),
        live_readiness.ReadinessMetric("b", "g", "text", "a|b", "n/a", "unknown", "e"),
        live_readiness.ReadinessMetric("c", "g", "none", None, "n/a", "fail", "e"),
    )
    card = live_readiness.Scorecard(ready=False, account="default", generated_at="2026-11-13T00:00:00Z", metrics=metrics, blocking=("b",))
    text = live_readiness.render_markdown(card)
    assert "| 1.23 |" in text and "| a/b |" in text and "| - |" in text


def test_secrets_backends_that_fail_read_as_nothing(tmp_path, monkeypatch):
    class Unreadable:
        def is_file(self):
            return True

        def read_text(self, encoding):
            raise OSError("locked")

    monkeypatch.setattr(secrets_io, "Path", lambda path: Unreadable())
    assert secrets_io.read_secret_file("x") is None
    monkeypatch.undo()
    broken = ModuleType("keyring")
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert secrets_io._keyring() is None
    monkeypatch.setitem(sys.modules, "keyring", broken)
    assert secrets_io._keyring() is broken
    broken.get_password = lambda service, user: (_ for _ in ()).throw(RuntimeError("locked"))
    assert secrets_io.keyring_get("aether-quant", "IB_ACCOUNT") is None
    broken.delete_password = lambda service, user: (_ for _ in ()).throw(RuntimeError("none stored"))
    assert secrets_io.keyring_delete("IB_ACCOUNT", "desk") is False
    broken.delete_password = lambda service, user: None
    assert secrets_io.keyring_delete("IB_ACCOUNT") is True


def test_dotted_paths_are_read_and_written_through_missing_branches():
    assert accounts._get({"a": {"b": 1}}, "a.b") == 1 and accounts._get({"a": 1}, "a.b") is None and accounts._get({}, "a") is None
    tree = {"a": 1}
    accounts._set(tree, "a.b.c", 5)
    assert tree == {"a": {"b": {"c": 5}}}


def test_the_account_registry_refuses_malformed_documents():
    with pytest.raises(ValueError, match="accounts must be a list"):
        accounts.parse_accounts({"accounts": "x"})
    with pytest.raises(ValueError, match="must be an object"):
        accounts.parse_accounts({"accounts": ["desk"]})
    with pytest.raises(ValueError, match="is not an account override"):
        accounts.apply_risk_overrides({}, SimpleNamespace(is_default=False, id="desk", risk_overrides={"not.a.key": 1}, mode=None))
    assert accounts.resolve_account((), None) is accounts.DEFAULT_ACCOUNT and accounts.resolve_account((), "default") is accounts.DEFAULT_ACCOUNT
    with pytest.raises(ValueError, match="unknown account"):
        accounts.resolve_account((), "desk")


def test_a_torn_state_file_reads_as_no_reconciliation(tmp_path, monkeypatch):
    account = accounts.DEFAULT_ACCOUNT
    state = tmp_path / "state.json"
    state.write_text("{torn", encoding="utf-8")
    monkeypatch.setattr(accounts_io, "account_output_paths", lambda root, acct: {"state_path": state})
    monkeypatch.setattr("execution.secrets_io.all_secret_status", lambda account_id, names: [])
    rows = accounts_io.account_status_rows(tmp_path, (account,))
    assert rows[0]["reconciliation_breach"] is None
