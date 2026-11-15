"""`aq test --coverage --changed` (V6.6.7, #367): the fast per-commit coverage gate, against a fake git and a fake runner."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

import aq_cli
import pytest


class FakeGit:
    def __init__(self, diff=(), new=(), tests_diff=(), tests_new=(), grep=None):
        self.diff, self.new, self.tests_diff, self.tests_new = list(diff), list(new), list(tests_diff), list(tests_new)
        self.grep = grep or {}
        self.calls: list = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[:2] == ["git", "diff"]:
            out = self.tests_diff if command[-1] == "tests/test_*.py" else self.diff
        elif command[:2] == ["git", "ls-files"]:
            out = self.tests_new if command[-1] == "tests/test_*.py" else self.new
        elif command[:2] == ["git", "grep"]:
            out = [f"tests/{name}" for name in self.grep.get(command[5], [])]
        else:
            return subprocess.CompletedProcess(command, 7)
        return subprocess.CompletedProcess(command, 0, stdout="\n".join(out) + ("\n" if out else ""), stderr="")


def test_changed_files_skip_tests_and_merge_new_ones():
    git = FakeGit(diff=["risk/kelly.py", "tests/test_kelly.py", "aq_cli.py"], new=["fuzz\\targets.py", "risk/kelly.py"])
    assert aq_cli._changed_python_files(git) == ["aq_cli.py", "fuzz/targets.py", "risk/kelly.py"]
    assert aq_cli._changed_test_files(FakeGit(tests_diff=["tests/test_a.py"], tests_new=["tests/test_b.py"])) == ["test_a.py", "test_b.py"]


def test_needles_name_a_module_its_path_and_a_scripts_stem():
    assert aq_cli._module_needles("risk/kelly.py") == ["risk.kelly", "risk/kelly.py"]
    assert aq_cli._module_needles("scripts/lock_requirements.py") == ["scripts.lock_requirements", "scripts/lock_requirements.py", '"lock_requirements"', "lock_requirements"]
    assert aq_cli._module_needles("json_safety.py")[-1] == "json_safety"


def test_tests_for_changed_refuses_an_unregistered_test():
    found = {"risk.kelly": ["test_kelly.py"], "risk/kelly.py": ["test_v665_misc.py"]}
    assert aq_cli._tests_for_changed(["risk/kelly.py"], {"test_kelly.py", "test_v665_misc.py"}, lambda needle: found.get(needle, [])) == ["test_kelly.py", "test_v665_misc.py"]
    with pytest.raises(SystemExit, match="outside _SUBSYSTEM_TEST_FILES"):
        aq_cli._tests_for_changed(["risk/kelly.py"], {"test_kelly.py"}, lambda needle: found.get(needle, []))


def test_git_grep_tests_reads_file_names():
    git = FakeGit(grep={"risk.kelly": ["test_kelly.py"]})
    assert aq_cli._git_grep_tests("risk.kelly", run=git) == ["test_kelly.py"]
    assert "--untracked" in git.calls[0]


def test_coverage_json_covers(tmp_path, monkeypatch):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    (tmp_path / "risk").mkdir()
    module = tmp_path / "risk" / "kelly.py"
    module.write_text("x = 1\n", encoding="utf-8")
    report = tmp_path / "coverage.json"
    assert not aq_cli._coverage_json_covers(report, ["risk/kelly.py"])
    old = time.time() - 100
    os.utime(module, (old, old))
    report.write_text(json.dumps({"files": {"risk\\kelly.py": {"missing_lines": []}}}), encoding="utf-8")
    assert aq_cli._coverage_json_covers(report, ["risk/kelly.py"])
    assert not aq_cli._coverage_json_covers(report, ["risk/kelly.py", "risk/other.py"])
    report.write_text(json.dumps({"files": {"risk/kelly.py": {"missing_lines": [1]}}}), encoding="utf-8")
    assert not aq_cli._coverage_json_covers(report, ["risk/kelly.py"])
    report.write_text("{broken", encoding="utf-8")
    assert not aq_cli._coverage_json_covers(report, ["risk/kelly.py"])
    os.utime(module, None)
    os.utime(report, (old, old))
    assert not aq_cli._coverage_json_covers(report, ["risk/kelly.py"]), "a file changed after the report"


def test_run_changed_coverage_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    assert aq_cli._run_changed_coverage(run=FakeGit()) == 0
    assert "no changed module" in capsys.readouterr().out

    many = FakeGit(diff=[f"pkg/m{i}.py" for i in range(aq_cli._CHANGED_COVERAGE_LIMIT + 1)])
    assert aq_cli._run_changed_coverage(run=many) == 1
    assert "too many for the fast gate" in capsys.readouterr().out

    lonely = FakeGit(diff=["risk/kelly.py"])
    assert aq_cli._run_changed_coverage(run=lonely, grep=lambda needle: []) == 1
    assert "no test names" in capsys.readouterr().out

    registered = next(iter(aq_cli._SUBSYSTEM_TEST_FILES["risk"]))
    commands: list = []
    git = FakeGit(diff=["risk/kelly.py"], tests_diff=[f"tests/{registered}", "tests/test_unregistered_new.py"])
    code = aq_cli._run_changed_coverage(run=git, grep=lambda needle: [registered] if needle == "risk.kelly" else [], runner=lambda cmd: commands.append(cmd) or 0)
    assert code == 0
    pytest_cmd, report_cmd = commands
    assert f"tests/{registered}" in pytest_cmd and "tests/test_unregistered_new.py" not in pytest_cmd and "--cov" in pytest_cmd
    assert "--fail-under=100" in report_cmd and "--include=risk/kelly.py" in report_cmd
    assert aq_cli._run_changed_coverage(run=git, grep=lambda needle: [registered], runner=lambda cmd: 2 if "pytest" in cmd else 0) == 2

    (tmp_path / "coverage.json").write_text(json.dumps({"files": {"risk/kelly.py": {"missing_lines": []}}}), encoding="utf-8")
    assert aq_cli._run_changed_coverage(run=git) == 0
    assert "shows them at 100%" in capsys.readouterr().out


def test_default_runner_uses_the_given_run(tmp_path, monkeypatch):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    registered = next(iter(aq_cli._SUBSYSTEM_TEST_FILES["risk"]))
    git = FakeGit(diff=["risk/kelly.py"], grep={"risk.kelly": [registered]})
    assert aq_cli._run_changed_coverage(run=git) == 7, "the fake answers 7 to anything but git"
    assert any(cmd[1:3] == ["-m", "pytest"] for cmd in git.calls)


def test_aq_test_coverage_changed_routes_to_the_fast_gate(monkeypatch):
    monkeypatch.setattr(aq_cli, "_run_changed_coverage", lambda: 5)
    assert aq_cli._run_coverage(argparse.Namespace(changed=True)) == 5
    parser_help = subprocess.run([aq_cli.sys.executable, str(aq_cli.ROOT_DIR / "aq_cli.py"), "test", "--help"], capture_output=True, text=True, check=False).stdout
    assert "--changed" in parser_help
