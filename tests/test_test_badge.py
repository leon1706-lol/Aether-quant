"""scripts/test_badge.py: the README's test badge from CI's JUnit report (V6.6.6, #358)."""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "test_badge.py"


@pytest.fixture(scope="module")
def badge_module():
    spec = importlib.util.spec_from_file_location("_test_badge_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _junit(path: Path, *suites: tuple[int, int, int, int], wrapped: bool = True) -> Path:
    body = "".join(f'<testsuite name="pytest" tests="{t}" failures="{f}" errors="{e}" skipped="{s}"/>' for t, f, e, s in suites)
    path.write_text(f"<testsuites>{body}</testsuites>" if wrapped else body, encoding="utf-8")
    return path


def test_counts_sum_every_suite_and_treat_errors_as_failures(badge_module, tmp_path):
    figures = badge_module.counts(_junit(tmp_path / "j.xml", (10, 1, 1, 2), (5, 0, 0, 0)))
    assert figures == {"tests": 15, "failed": 2, "skipped": 2, "passed": 11}


def test_a_bare_testsuite_root_is_read_too(badge_module, tmp_path):
    assert badge_module.counts(_junit(tmp_path / "j.xml", (3, 0, 0, 1), wrapped=False))["passed"] == 2


def test_no_suite_is_an_error(badge_module, tmp_path):
    (tmp_path / "j.xml").write_text("<testsuites/>", encoding="utf-8")
    with pytest.raises(ValueError):
        badge_module.counts(tmp_path / "j.xml")


def test_badge_is_green_only_when_something_ran_and_nothing_failed(badge_module):
    assert badge_module.badge({"passed": 5, "failed": 0}) == {"schemaVersion": 1, "label": "tests", "message": "5/5 passing", "color": "brightgreen"}
    assert badge_module.badge({"passed": 5, "failed": 2})["color"] == "red" and badge_module.badge({"passed": 5, "failed": 2})["message"] == "5/7 passing"
    assert badge_module.badge({"passed": 0, "failed": 0})["color"] == "red"


def test_main_prints_and_writes_the_endpoint_file(badge_module, tmp_path, capsys):
    target = tmp_path / "site" / "badges" / "tests.json"
    assert badge_module.main([str(_junit(tmp_path / "j.xml", (4, 0, 0, 1))), "--badge", str(target)]) == 0
    assert "3 passed, 0 failed, 1 skipped" in capsys.readouterr().out
    assert json.loads(target.read_text(encoding="utf-8"))["message"] == "3/3 passing"
    assert badge_module.main([str(_junit(tmp_path / "k.xml", (1, 0, 0, 0)))]) == 0


def test_main_reports_a_missing_or_broken_file(badge_module, tmp_path, capsys):
    assert badge_module.main([str(tmp_path / "missing.xml")]) == 1
    (tmp_path / "bad.xml").write_text("<testsuites", encoding="utf-8")
    assert badge_module.main([str(tmp_path / "bad.xml")]) == 1
    assert "no test figures" in capsys.readouterr().err


def test_runs_as_a_script(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(_junit(tmp_path / "j.xml", (2, 0, 0, 0)))])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exit_info.value.code == 0 and "2 passed" in capsys.readouterr().out
