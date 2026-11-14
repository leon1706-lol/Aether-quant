"""scripts/v660_write_rules.py (V6.6.6): writes the V6.6.0 rules and their hash once, and refuses a second write."""

from __future__ import annotations

import hashlib

import pytest

from script_loader import block_path_writes, load_script, run_script


def test_the_rules_are_written_once_with_their_hash(tmp_path, monkeypatch, capsys):
    module = load_script("v660_write_rules")
    monkeypatch.setattr(module, "OUT", tmp_path / "v660")
    assert module.main() == 0
    text = (tmp_path / "v660" / "rules.json").read_text(encoding="utf-8")
    assert (tmp_path / "v660" / "rules.sha256").read_text(encoding="utf-8").strip() == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert capsys.readouterr().out.strip() == hashlib.sha256(text.encode("utf-8")).hexdigest()
    with pytest.raises(SystemExit, match="written once"):
        module.main()


def test_run_as_a_script_it_changes_nothing_here(monkeypatch):
    writes = block_path_writes(monkeypatch)
    try:
        code = run_script("v660_write_rules", [], monkeypatch)
    except SystemExit as exit_info:  # the real rules exist on a working tree
        code = exit_info.code
    assert code == 0 or "written once" in str(code)
    assert all(path.name in ("v660", "rules.json", "rules.sha256") for _method, path, _args in writes)
