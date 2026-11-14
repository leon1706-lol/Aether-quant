"""scripts/mutation_check.py: the operators change exactly one thing, the sample is repeatable, and a file is always put back (V6.6.4)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mutation_check as mc  # noqa: E402

SNIPPET = '''
def gate(x, y, flag):
    """a docstring with 3 and True in it"""
    if x > 5 and y == 2:
        return x + 7
    if not flag:
        return True
    return False
'''


def test_every_kind_of_site_is_found_and_the_docstring_is_not_one():
    kinds = sorted({site.kind for site in mc.sites(SNIPPET)})
    assert kinds == ["arithmetic", "bool", "boolop", "compare", "int", "not"]
    assert sum(1 for site in mc.sites(SNIPPET) if site.kind == "int") == 3, "5, 2 and 7 (0 and 1 are left alone); the docstring's 3 is a string, not a site"


def test_each_mutation_changes_exactly_one_site_and_still_parses():
    for site in mc.sites(SNIPPET):
        mutated = mc.mutate(SNIPPET, site)
        ast.parse(mutated)
        assert ast.unparse(ast.parse(mutated)) != ast.unparse(ast.parse(SNIPPET)), site
    comparison = next(site for site in mc.sites(SNIPPET) if site.kind == "compare")
    assert ">=" in mc.mutate(SNIPPET, comparison)
    boolop = next(site for site in mc.sites(SNIPPET) if site.kind == "boolop")
    assert " or " in mc.mutate(SNIPPET, boolop)
    negation = next(site for site in mc.sites(SNIPPET) if site.kind == "not")
    assert "not flag" not in mc.mutate(SNIPPET, negation)


def test_the_sample_is_fixed_by_the_seed_and_in_source_order():
    found = mc.sites(SNIPPET * 1)
    first, second = mc.sample(found, 3, 664), mc.sample(found, 3, 664)
    assert first == second and first == sorted(first, key=lambda site: site.index) and len(first) == 3
    assert mc.sample(found, 100, 1) == found


def test_a_file_is_restored_even_when_the_run_is_interrupted(tmp_path, monkeypatch):
    target = ROOT / "tests" / "_mutation_scratch_module.py"
    target.write_text("def f(x):\n    return x > 1\n", encoding="utf-8")
    monkeypatch.setattr(mc, "ROOT", ROOT)
    calls = {"count": 0}

    def fake_tests(tests, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            return True  # the unmutated run passes
        raise KeyboardInterrupt  # the first mutant is interrupted

    monkeypatch.setattr(mc, "run_tests", fake_tests)
    try:
        try:
            mc.check_file("tests/_mutation_scratch_module.py", ("tests/test_mutation_check.py",), limit=5, seed=1, timeout=1.0, emit=lambda line: None)
        except KeyboardInterrupt:
            pass
        assert target.read_text(encoding="utf-8") == "def f(x):\n    return x > 1\n"
    finally:
        target.unlink()


def test_a_survivor_is_reported_with_its_line_and_a_killed_mutant_is_not(monkeypatch):
    target = ROOT / "tests" / "_mutation_scratch_two.py"
    target.write_text("def f(x):\n    return x > 1 and x < 9\n", encoding="utf-8")
    outcomes = iter([True, False, True, False, False])
    monkeypatch.setattr(mc, "run_tests", lambda tests, timeout: next(outcomes))
    try:
        report = mc.check_file("tests/_mutation_scratch_two.py", ("tests/test_mutation_check.py",), limit=5, seed=1, timeout=1.0, emit=lambda line: None)
    finally:
        target.unlink()
    assert report["tried"] == 4 and report["killed"] == 3 and report["survived"] == 1 and report["survivors"][0]["line"] == 2 and report["kill_rate"] == 0.75


def test_every_target_names_a_module_that_exists():
    for relative in mc.TARGETS:
        assert (ROOT / relative).exists(), relative


def test_run_tests_counts_a_pass_a_failure_and_a_timeout(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    codes = iter([0, 1])
    monkeypatch.setattr(mc.subprocess, "run", lambda command, **kwargs: SimpleNamespace(returncode=next(codes)))
    assert mc.run_tests(("tests/test_mutation_check.py", "tests/none.py"), 1.0) is True
    assert mc.run_tests(("tests/test_mutation_check.py",), 1.0) is False

    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1.0)

    monkeypatch.setattr(mc.subprocess, "run", slow)
    assert mc.run_tests(("tests/test_mutation_check.py",), 1.0) is False


def test_a_red_baseline_measures_nothing_and_an_unrestored_file_stops(monkeypatch, tmp_path):
    monkeypatch.setattr(mc, "ROOT", tmp_path)
    (tmp_path / "m.py").write_text("def f(x):\n    return x > 1\n", encoding="utf-8")
    monkeypatch.setattr(mc, "run_tests", lambda tests, timeout: False)
    assert mc.check_file("m.py", ("t.py",), limit=2, seed=1, timeout=1.0)["error"].startswith("the tests do not pass")

    import pathlib
    import pytest

    real_write = pathlib.Path.write_text
    writes = {"count": 0}

    def write_text(self, text, *args, **kwargs):
        writes["count"] += 1
        return real_write(self, text + ("# drift\n" if writes["count"] > 1 else ""), *args, **kwargs)

    monkeypatch.setattr(mc, "run_tests", lambda tests, timeout: True)
    monkeypatch.setattr(pathlib.Path, "write_text", write_text)
    with pytest.raises(SystemExit, match="was not restored"):
        mc.check_file("m.py", ("t.py",), limit=1, seed=1, timeout=1.0, emit=lambda line: None)


def test_main_reports_each_target(tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.setattr(mc, "TARGETS", {"a.py": ("t.py",), "b.py": ("t.py",)})
    monkeypatch.setattr(mc, "check_file", lambda relative, tests, limit, seed, timeout: {"file": relative, "tried": 2, "killed": 2, "survived": 0, "kill_rate": 1.0})
    out = tmp_path / "report" / "mutation.json"
    assert mc.main(["--out", str(out), "--only", "a.py"]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [row["file"] for row in report["files"]] == ["a.py"] and '"kill_rate": 1.0' in capsys.readouterr().out
