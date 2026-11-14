"""scripts/library_gate.py (V6.6.6): the readers it builds the gate from, its --report, and a failing gate.
tests/test_aether_quant_coverage.py runs the gate itself on the real tree."""

from __future__ import annotations

import json

from script_loader import load_script


def test_public_defs_skip_a_missing_package_and_the_bytecode_cache(tmp_path, monkeypatch):
    gate = load_script("library_gate")
    (tmp_path / "pkg" / "__pycache__").mkdir(parents=True)
    (tmp_path / "pkg" / "mod.py").write_text("def visible():\n    pass\n", encoding="utf-8")
    (tmp_path / "pkg" / "__pycache__" / "mod.py").write_text("def cached():\n    pass\n", encoding="utf-8")
    (tmp_path / "top.py").write_text("class Top:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(gate, "shipped_roots", lambda root: (["pkg", "gone"], ["top", "absent"]))
    found = gate.public_defs(tmp_path)
    assert found == {"top": {"Top"}, "pkg.mod": {"visible"}}


def test_readers_return_empty_when_their_source_lacks_what_they_read(tmp_path):
    gate = load_script("library_gate")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_aether_quant_api.py").write_text("OTHER = ('x',)\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "wheel_smoke.py").write_text("def something_else():\n    checks = {'a': 1}\n", encoding="utf-8")
    assert gate.api_test_modules(tmp_path) == [] and gate.wheel_check_modules(tmp_path) == []
    assert gate.load_allowlist(tmp_path / "none.json") == {"modules": {}, "unexported": {}, "legacy_names": []}


def test_report_and_a_failing_gate(monkeypatch, capsys):
    gate = load_script("library_gate")
    assert gate.main(["--report"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["facade_modules"] > 20 and report["ceiling"] == gate.LEGACY_CEILING
    monkeypatch.setattr(gate, "check", lambda root, allow, listed_modules, wheel_modules: ["evaluation.x.new_name is public and not exported"])
    assert gate.main([]) == 1
    assert "1 problem(s)" in capsys.readouterr().err
    monkeypatch.setattr(gate, "check", lambda root, allow, listed_modules, wheel_modules: [])
    assert gate.main([]) == 0


def test_the_report_runs_as_a_script(monkeypatch, capsys):
    from script_loader import run_script

    assert run_script("library_gate", ["--report"], monkeypatch) == 0 and '"facade_modules"' in capsys.readouterr().out
