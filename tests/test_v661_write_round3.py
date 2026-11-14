"""scripts/v661_write_round3.py (V6.6.6): round 3's rule file cites its parent and, if asked, the audit, by hash."""

from __future__ import annotations

import hashlib
import json

from script_loader import load_script, run_script


def _v660(tmp_path):
    folder = tmp_path / "v660"
    folder.mkdir()
    (folder / "rules.json").write_text(json.dumps({"rules": {"R-SLEEVE3": "bar", "PBO": "pbo"}, "trials": {"pbo_columns": ["a", "b"]}}), encoding="utf-8")
    (folder / "rules_r2.json").write_text(json.dumps({"trials": {"c": {}, "d": {}}}), encoding="utf-8")
    return folder


def test_the_payload_names_its_parent_and_the_cited_audit(tmp_path, monkeypatch):
    module = load_script("v661_write_round3")
    folder = _v660(tmp_path)
    monkeypatch.setattr(module, "V660", folder)
    audit = tmp_path / "model_audit.json"
    audit.write_text("{}", encoding="utf-8")
    written = module.payload(cite=audit)
    assert written["bar"] == "bar" and written["prior_columns"] == ["a", "b", "c", "d"] and len(written["trials"]) == 10
    assert written["parent"]["sha256"] == hashlib.sha256((folder / "rules.json").read_bytes()).hexdigest()
    assert written["audit_cited"] == {"file": "model_audit.json", "sha256": hashlib.sha256(b"{}").hexdigest()}
    assert "audit_cited" not in module.payload()


def test_main_writes_through_write_rules(tmp_path, monkeypatch, capsys):
    module = load_script("v661_write_round3")
    monkeypatch.setattr(module, "V660", _v660(tmp_path))
    seen = {}
    monkeypatch.setattr(module, "write_rules", lambda payload, path: seen.update(payload=payload, path=path) or "digest")
    assert module.main([]) == 0 and capsys.readouterr().out.strip() == "digest"
    assert seen["path"] == module.ROUND_FILE and seen["payload"]["name"] == "round3"


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("v661_write_round3", ["--help"], monkeypatch) == 0
    assert "--cite" in capsys.readouterr().out
