"""scripts/coverage_misses.py (V6.6.7, #367): the worklist a coverage run leaves."""

from __future__ import annotations

import json

from script_loader import load_script, run_script

cm = load_script("coverage_misses")

SOURCE = "import os\n\n\nclass A:\n    def f(self):\n        return 1\n\n    def g(self):\n        if os:\n            return 2\n        return 3\n\n\nx = 1\n"


def _tree(tmp_path, missing):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(SOURCE, encoding="utf-8")
    data = {"files": {"pkg\\mod.py": {"missing_lines": missing}, "pkg/clean.py": {"missing_lines": []}, "gone.py": {"missing_lines": [3]}}}
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_misses_filters_and_skips_clean_files(tmp_path):
    data = cm.load(_tree(tmp_path, [11, 6]))
    assert cm.misses(data) == {"pkg/mod.py": [6, 11], "gone.py": [3]}
    assert cm.misses(data, ["pkg/*"]) == {"pkg/mod.py": [6, 11]}
    assert cm.misses({}) == {}


def test_by_function_names_the_innermost_owner():
    assert cm.by_function(SOURCE, [6, 11, 14, 1]) == {"A.f": [6], "A.g": [11], "<module>": [14, 1]}


def test_context_marks_misses_and_gaps():
    text = cm.context(SOURCE, [6, 14], radius=1)
    assert ">>     6          return 1" in text and "    ..." in text and text.splitlines()[-1].startswith(">>    14")


def test_main_prints_the_worklist(tmp_path, capsys):
    path = _tree(tmp_path, [6, 11])
    assert cm.main(["--json", str(path), "--by-function", "--context", "0"], root=tmp_path) == 1
    out = capsys.readouterr().out
    assert "pkg/mod.py: 2 missing" in out and "A.g: [11]" in out and "gone.py: 1 missing" in out and "3 missing line(s) in 2 file(s)" in out
    assert cm.main(["--json", str(path), "--include", "pkg/mod.py"], root=tmp_path) == 1
    assert "A.g" not in capsys.readouterr().out
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps({"files": {}}), encoding="utf-8")
    assert cm.main(["--json", str(clean)], root=tmp_path) == 0
    assert cm.main(["--json", str(tmp_path / "none.json")], root=tmp_path) == 2
    assert "run `aq test --coverage` first" in capsys.readouterr().err


def test_runs_as_main(monkeypatch, tmp_path, capsys):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"files": {}}), encoding="utf-8")
    assert run_script("coverage_misses", ["--json", str(path)], monkeypatch) == 0
    assert "0 missing line(s)" in capsys.readouterr().out
