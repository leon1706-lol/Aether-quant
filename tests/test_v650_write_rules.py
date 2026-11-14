"""scripts/v650_write_rules.py (V6.6.6): writes the V6.5.0 rules and their hash once, and refuses a second write."""

from __future__ import annotations

import hashlib
import json

from script_loader import block_path_writes, load_script, run_script


def test_the_rules_are_written_once_with_their_hash(tmp_path, monkeypatch, capsys):
    module = load_script("v650_write_rules")
    monkeypatch.setattr(module, "OUT", tmp_path / "v650")
    assert module.main() == 0
    text = (tmp_path / "v650" / "rules.json").read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert (tmp_path / "v650" / "rules.sha256").read_text(encoding="utf-8").strip() == digest == capsys.readouterr().out.strip()
    rules = json.loads(text)
    assert rules["trial_budget"] == 60 and rules["trials"]["sleeves"] and "R-EDGE1" in rules

    assert module.main() == 1
    assert "written once" in capsys.readouterr().err


def test_run_as_a_script_it_changes_nothing_here(monkeypatch):
    writes = block_path_writes(monkeypatch)
    assert run_script("v650_write_rules", [], monkeypatch) in (0, 1)
    assert all(path.name in ("v650", "rules.json", "rules.sha256") for _method, path, _args in writes)
