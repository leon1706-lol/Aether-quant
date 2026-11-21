"""aq_devtools.py: the developer and maintainer commands. Every subprocess goes through `aq_devtools.RUN`, which these tests
replace with a scripted fake, so nothing here calls git, gh, npm or docker."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import aq_devtools as dev


class FakeRun:
    """Answers commands by their first matching prefix; records every call."""

    def __init__(self, answers=None, default=(0, "")):
        self.answers = list(answers or [])
        self.default = default
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append(command)
        text = " ".join(command)
        for prefix, answer in self.answers:
            if text.startswith(prefix) or prefix in text:
                if isinstance(answer, BaseException):
                    raise answer
                code, out = answer
                return subprocess.CompletedProcess(command, code, stdout=out, stderr="")
        return subprocess.CompletedProcess(command, self.default[0], stdout=self.default[1], stderr="")


@pytest.fixture
def run(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(dev, "RUN", fake)
    return fake


def ns(**values):
    return argparse.Namespace(**values)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_run_capture_and_run_live_turn_missing_programs_and_timeouts_into_codes(run, capsys):
    run.answers = [("missing", FileNotFoundError()), ("slow", subprocess.TimeoutExpired("slow", 1)), ("ok", (0, "fine"))]
    assert dev.run_capture(["missing"]) == (127, "missing: not found")
    assert dev.run_capture(["slow"]) == (124, "slow: timed out")
    assert dev.run_capture(["ok"], env={"A": "1"}) == (0, "fine")
    assert dev.run_live(["missing"]) == 127 and "not found on PATH" in capsys.readouterr().err
    assert dev.run_live(["ok"]) == 0


def test_emit_prints_json_safely_or_through_its_renderer(capsys):
    dev.emit({"a": float("nan"), "b": [1]}, True)
    assert json.loads(capsys.readouterr().out) == {"a": None, "b": [1]}
    dev.emit({"a": 1}, False, lambda data: f"a={data['a']}")
    dev.emit("plain", False)
    assert capsys.readouterr().out == "a=1\nplain\n"


def test_confirm_needs_yes_without_a_terminal_and_asks_on_one(capsys):
    assert dev.confirm("go?", assume_yes=True)
    assert not dev.confirm("go?", assume_yes=False, isatty=lambda: False) and "pass --yes" in capsys.readouterr().err
    assert dev.confirm("go?", assume_yes=False, isatty=lambda: True, ask=lambda prompt: "Y")
    assert not dev.confirm("go?", assume_yes=False, isatty=lambda: True, ask=lambda prompt: "")


def test_checkout_detection_colour_and_the_version(tmp_path, monkeypatch, capsys):
    assert dev.source_checkout(dev.ROOT_DIR) and not dev.source_checkout(tmp_path)
    assert dev.needs_checkout(dev.ROOT_DIR) is None
    assert dev.needs_checkout(tmp_path) == 1 and "source checkout" in capsys.readouterr().err
    monkeypatch.setenv("NO_COLOR", "1")
    assert dev.color("x", "31") == "x"
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    assert dev.color("x", "31") == "\x1b[31mx\x1b[0m"
    monkeypatch.setattr(dev, "_package_version", lambda name: (_ for _ in ()).throw(dev.PackageNotFoundError(name)))
    assert dev.installed_version() == "unknown"


# ---------------------------------------------------------------------------
# hooks, commit, check
# ---------------------------------------------------------------------------


def test_the_coverage_marker_turns_off_once_and_back_on(tmp_path):
    marker = tmp_path / "git" / "aq-skip-coverage"
    assert dev.coverage_state(marker) == "on"
    assert dev.set_coverage(marker, "once") == "once" and dev.set_coverage(marker, "off") == "off"
    assert marker.read_text(encoding="utf-8") == "persistent"
    assert dev.set_coverage(marker, "on") == "on" and not marker.exists()


def test_git_path_falls_back_to_dot_git(run, tmp_path):
    run.answers = [("git rev-parse --git-path", (0, ".git/aq-skip-coverage\n"))]
    assert dev.git_path("aq-skip-coverage", tmp_path) == tmp_path / ".git" / "aq-skip-coverage"
    run.answers = [("git rev-parse --git-path", (0, f"{tmp_path.as_posix()}/abs\n"))]
    assert dev.git_path("x", tmp_path) == Path(f"{tmp_path.as_posix()}/abs")
    run.answers = [("git rev-parse --git-path", (1, ""))]
    assert dev.git_path("x", tmp_path) == tmp_path / ".git" / "x"


def test_hooks_install_status_and_the_coverage_switch(run, tmp_path, monkeypatch, capsys):
    marker = tmp_path / "aq-skip-coverage"
    monkeypatch.setattr(dev, "git_path", lambda name, root=dev.ROOT_DIR: marker)
    assert dev.cmd_hooks(ns(hooks_command="install", dry_run=True)) == 0 and "would install" in capsys.readouterr().out
    monkeypatch.syspath_prepend(str(dev.ROOT_DIR / "scripts"))
    import install_hooks

    monkeypatch.setattr(install_hooks, "install", lambda root: "installed here")
    monkeypatch.setattr(install_hooks, "installed", lambda root: True)
    assert dev.cmd_hooks(ns(hooks_command="install", dry_run=False)) == 0 and "installed here" in capsys.readouterr().out
    assert dev.cmd_hooks(ns(hooks_command="status", json=False)) == 0 and "coverage gate: on" in capsys.readouterr().out
    assert dev.cmd_hooks(ns(hooks_command="coverage", coverage_action="off", once=True, dry_run=True, json=False)) == 0 and not marker.exists()
    assert dev.cmd_hooks(ns(hooks_command="coverage", coverage_action="off", once=True, dry_run=False, json=False)) == 0
    out = capsys.readouterr()
    assert marker.read_text(encoding="utf-8") == "once" and "still enforces 100%" in out.err
    assert dev.cmd_hooks(ns(hooks_command="coverage", coverage_action="status", json=True)) == 0 and json.loads(capsys.readouterr().out) == {"coverage": "once"}
    assert dev.cmd_hooks(ns(hooks_command="coverage", coverage_action="on", once=False, dry_run=False, json=False)) == 0 and not marker.exists()
    status = dev.hooks_status(dev.ROOT_DIR)
    assert status["gates"][-1] == "coverage of changed modules"
    assert "missing" in dev._render_hooks_status({**status, "installed": False, "coverage": "off", "coverage_json_age_hours": None})
    monkeypatch.setattr(dev, "needs_checkout", lambda root=dev.ROOT_DIR: 1)
    assert dev.cmd_hooks(ns(hooks_command="status", json=False)) == 1


def test_commit_skips_only_coverage_and_check_runs_the_hook(run, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(dev, "run_live", lambda command, env=None, cwd=None: calls.append((command, env)) or 0)
    assert dev.cmd_commit(ns(message="m", all=True, git_args=["--signoff"], skip_coverage=True, dry_run=False)) == 0
    command, env = calls[-1]
    assert command == ["git", "commit", "-m", "m", "-a", "--signoff"] and env["AQ_SKIP_COVERAGE_HOOK"] == "1" and "--no-verify" not in command
    assert "coverage gate skipped" in capsys.readouterr().err
    assert dev.cmd_commit(ns(message="m", all=False, git_args=None, skip_coverage=False, dry_run=True)) == 0
    assert capsys.readouterr().out.strip() == "git commit -m m"
    assert dev.cmd_check(ns(no_coverage=True)) == 0 and calls[-1][0][-1].endswith("pre-commit") and calls[-1][1]["AQ_SKIP_COVERAGE_HOOK"] == "1"
    monkeypatch.setattr(dev.shutil, "which", lambda name: None)
    assert dev.cmd_check(ns(no_coverage=False)) == 1 and "no sh" in capsys.readouterr().err
    monkeypatch.setattr(dev, "needs_checkout", lambda root=dev.ROOT_DIR: 1)
    assert dev.cmd_check(ns(no_coverage=False)) == 1


# ---------------------------------------------------------------------------
# doctor, version, completion, help
# ---------------------------------------------------------------------------


def _probes(*, which=lambda name: f"/bin/{name}", ram=16.0, disk=100.0, tcp=False, run_code=0):
    return {"which": which, "ram_gb": lambda: ram, "disk_free_gb": lambda root: disk, "tcp_open": lambda host, port: tcp,
            "run": lambda command, **kwargs: (run_code, "")}


def test_the_doctor_reports_each_check_with_its_fix(capsys):
    checks = dev.doctor_checks(dev.ROOT_DIR, _probes())
    names = [check["name"] for check in checks]
    assert {"python", "editable install", "aq on PATH", "git", "gh auth", "docker daemon", "redis", "RAM", "disk", "config.json"} <= set(names)
    low = {check["name"]: check for check in dev.doctor_checks(dev.ROOT_DIR, _probes(which=lambda name: None, ram=4.0, disk=2.0, run_code=1))}
    assert low["git"]["status"] == "fail" and low["gh"]["status"] == "warn" and low["RAM"]["status"] == "warn" and "low" in low["RAM"]["fix"]
    assert "gh auth" not in low and low["disk"]["status"] == "warn"
    assert dev.doctor_checks(dev.ROOT_DIR, _probes(ram=None) | {"ram_gb": lambda: None})[[c["name"] for c in checks].index("RAM")]["status"] == "skip"
    text = dev.render_checks(low.values())
    assert "FAIL" in text and "failures" in text and "-> install git" in text


def test_the_doctor_sees_a_wheel_install_a_broken_config_and_old_pythons(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text("{", encoding="utf-8")
    checks = {check["name"]: check for check in dev.doctor_checks(tmp_path, _probes(tcp=True))}
    assert checks["editable install"]["status"] == "skip" and checks["config.json"]["status"] == "fail" and checks["redis"]["status"] == "ok"
    assert checks["model pins"]["status"] == "skip"
    monkeypatch.setattr(dev.sys, "version_info", (3, 10, 4))
    assert dev.doctor_checks(tmp_path, _probes())[0]["status"] == "warn"
    monkeypatch.setattr(dev.sys, "version_info", (3, 9, 0))
    assert dev.doctor_checks(tmp_path, _probes())[0]["status"] == "fail"


def test_the_editable_check_finds_missing_modules_and_a_foreign_install(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('py-modules = ["aq_cli", "definitely_missing_module"]\n', encoding="utf-8")
    assert dev._editable_check(tmp_path)["status"] == "fail"
    (tmp_path / "pyproject.toml").write_text('py-modules = ["aq_cli"]\n', encoding="utf-8")
    assert dev._editable_check(tmp_path)["status"] == "warn", "aq_cli loads from the real checkout, not tmp_path"
    assert dev._editable_check(dev.ROOT_DIR)["status"] == "ok"


def test_ram_and_ports_are_read_safely(monkeypatch):
    assert dev._total_ram_gb() is None or dev._total_ram_gb() > 0
    assert dev._tcp_open("127.0.0.1", 1, timeout=0.2) is False
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(virtual_memory=lambda: SimpleNamespace(total=8e9)))
    assert dev._total_ram_gb() == 8.0
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(dev.sys, "platform", "linux")
    monkeypatch.setattr(dev.os, "sysconf", lambda name: (_ for _ in ()).throw(ValueError()), raising=False)
    assert dev._total_ram_gb() is None


def test_doctor_exits_one_on_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(dev, "doctor_checks", lambda: [dev._check("x", "fail", "broken", "fix it")])
    assert dev.cmd_doctor(ns(json=False)) == 1 and "fix it" in capsys.readouterr().out
    monkeypatch.setattr(dev, "doctor_checks", lambda: [dev._check("x", "ok", "fine")])
    assert dev.cmd_doctor(ns(json=True)) == 0


def test_version_says_where_it_runs(run, capsys, tmp_path):
    run.answers = [("rev-parse --short", (0, "abc1234\n")), ("status --porcelain", (0, " M x\n"))]
    info = dev.version_info()
    assert info["git"] == "abc1234" and info["dirty"] is True and "with uncommitted changes" in dev._render_version(info)
    assert "wheel install" in dev._render_version(dev.version_info(tmp_path))
    run.answers = [("rev-parse --short", (1, ""))]
    assert dev.version_info()["git"] is None
    assert dev.cmd_version(ns(json=True)) == 0 and "aether_quant" in json.loads(capsys.readouterr().out)


def test_completion_scripts_name_every_command_and_help_walks_the_tree(capsys):
    import aq_cli

    parser = aq_cli.build_parser()
    for shell in ("bash", "zsh", "powershell"):
        script = dev.completion_script(parser, shell)
        assert "hooks" in script and "--skip-coverage" in script and "lab" in script
    assert dev.completion_script(parser, "zsh").startswith("# aq completion for zsh") and "Register-ArgumentCompleter" in dev.completion_script(parser, "powershell")
    assert dev.cmd_completion(ns(shell="bash")) == 0 and "complete -F _aq_complete aq" in capsys.readouterr().out
    assert dev.cmd_help(ns(topic=["hooks", "coverage"])) == 0 and "--once" in capsys.readouterr().out
    assert dev.cmd_help(ns(topic=["hoks"])) == 2 and "did you mean: hooks" in capsys.readouterr().err
    assert dev.cmd_help(ns(topic=["zzzz"])) == 2 and "no command" in capsys.readouterr().err
    assert dev.cmd_help(ns(topic=None)) == 0


# ---------------------------------------------------------------------------
# status and CI
# ---------------------------------------------------------------------------


def _gh_answers(sha="abc", conclusion="success", status="completed", jobs=None):
    jobs = jobs if jobs is not None else [{"name": "tests", "conclusion": conclusion, "databaseId": 9}]
    runs = [{"databaseId": 1, "workflowName": "CI", "status": status, "conclusion": conclusion if status == "completed" else None, "event": "push"}]
    return [
        ("gh run list", (0, json.dumps(runs))), ("gh run view", (0, json.dumps({"jobs": jobs}))),
        ("gh pr list", (0, json.dumps([{"number": 5, "title": "Bump numpy from 2.4.6 to 2.5.5 in /requirements", "headRefName": "x",
                                        "statusCheckRollup": [{"conclusion": "SUCCESS", "status": "COMPLETED"}]}]))),
        ("gh codespace list", (0, json.dumps([{"name": "cs1", "state": "Available", "lastUsedAt": "t"}, {"name": "cs2", "state": "Shutdown"}]))),
        ("gh repo view", (0, json.dumps({"nameWithOwner": "o/r"}))), ("gh api", (0, "2026Z ok\n2026Z FAILED tests/test_x.py::t\n")),
        ("git rev-parse --abbrev-ref", (0, "main\n")), ("git status --porcelain", (0, " M a.py\n")), ("git log -1", (0, "abc fix (2 hours ago)\n")),
        ("git rev-list", (0, "1\t2\n")), ("git rev-parse", (0, f"{sha}\n")),
    ]


def test_runs_are_summarised_green_red_or_running():
    assert dev.summarize_runs([])["verdict"] == "none"
    green = dev.summarize_runs([{"workflowName": "CI", "status": "completed", "conclusion": "success", "jobs": [{"name": "a", "conclusion": "success"}]}])
    assert green["verdict"] == "green"
    red = dev.summarize_runs([{"workflowName": "CI", "status": "completed", "conclusion": "failure", "jobs": [{"name": "a", "conclusion": "failure"}]},
                              {"workflowName": "Docs", "status": "completed", "conclusion": "failure", "jobs": []}])
    assert red["verdict"] == "red" and red["failed"] == ["CI / a", "Docs"]
    running = dev.summarize_runs([{"workflowName": "CI", "status": "in_progress", "conclusion": None, "jobs": []}])
    assert running["verdict"] == "running" and running["running"] == ["CI"]


def test_a_log_is_cut_to_the_lines_that_explain_the_failure():
    log = "\n".join(["2026-11-20T10:00:00.0Z setup"] * 5 + ["2026-11-20T10:00:01.0Z context", "2026-11-20T10:00:02.0Z FAILED tests/a.py::x", "ok"] * 3)
    lines = dev.filter_log(log, before=1, cap=4)
    assert lines[-1] == "FAILED tests/a.py::x" and len(lines) == 4 and not any(line.startswith("2026") for line in lines)


def test_ci_status_logs_and_watch(run, monkeypatch, capsys):
    monkeypatch.setattr(dev.shutil, "which", lambda name: f"/bin/{name}")
    run.answers = _gh_answers()
    assert dev.cmd_ci(ns(ci_command="status", sha="HEAD", branch=None, watch=False, interval=1, json=False)) == 0 and "green" in capsys.readouterr().out
    run.answers = _gh_answers(conclusion="failure")
    assert dev.cmd_ci(ns(ci_command="status", sha="HEAD", branch="main", watch=False, interval=1, json=True)) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "red"
    assert dev.cmd_ci(ns(ci_command="logs", run_id="1", job=None, lines=10)) == 0 and "FAILED tests/test_x.py::t" in capsys.readouterr().out
    assert dev.cmd_ci(ns(ci_command="logs", run_id="1", job="nothing", lines=10)) == 0 and "no failed job matching 'nothing'" in capsys.readouterr().out
    assert dev.cmd_ci(ns(ci_command="logs", run_id="1", job="tests", lines=10, json=True)) == 0
    assert json.loads(capsys.readouterr().out)["tests"][-1] == "FAILED tests/test_x.py::t"
    states = iter(["in_progress", "completed"])
    sleeps = []
    monkeypatch.setattr(dev.time, "sleep", lambda seconds: sleeps.append(seconds))

    def runs_now(sha):
        state = next(states)
        return [{"workflowName": "CI", "status": state, "conclusion": "success" if state == "completed" else None, "jobs": []}]

    monkeypatch.setattr(dev, "ci_runs", runs_now)
    assert dev.cmd_ci(ns(ci_command="status", sha="HEAD", branch=None, watch=True, interval=7, json=False)) == 0 and sleeps == [7]
    monkeypatch.setattr(dev, "ci_runs", lambda sha: None)
    assert dev.cmd_ci(ns(ci_command="status", sha="HEAD", branch=None, watch=False, interval=1, json=False)) == 1
    run.answers = [("gh run view", (1, ""))]
    assert dev.cmd_ci(ns(ci_command="logs", run_id="1", job=None, lines=10)) == 1 and "not found" in capsys.readouterr().err
    monkeypatch.setattr(dev.shutil, "which", lambda name: None)
    assert dev.cmd_ci(ns(ci_command="status")) == 1 and "GitHub CLI" in capsys.readouterr().err


def test_gh_json_and_runs_degrade_when_gh_fails(run):
    run.answers = [("gh run list", (1, "")), ("gh pr list", (0, "not json"))]
    assert dev.ci_runs("abc") is None and dev._gh_json(["pr", "list"]) is None and dev.dependabot_prs() is None


def test_status_reports_branch_hooks_ci_prs_and_codespaces(run, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(dev.shutil, "which", lambda name: f"/bin/{name}")
    run.answers = _gh_answers()
    report = dev.status_report()
    assert report["git"]["branch"] == "main" and report["git"]["dirty"] == 1 and report["git"]["behind"] == "1" and report["ci"]["verdict"] == "green"
    assert report["dependabot_prs"] == 1 and report["codespaces_running"] == ["cs1"]
    text = dev._render_status(report)
    assert "RUNNING (billing): cs1" in text and "CI of HEAD: green" in text
    assert "unknown" in dev._render_status({**report, "ci": "unknown", "codespaces_running": []})
    assert dev.cmd_status(ns(git=False, offline=True, json=True)) == 0 and "ci" not in json.loads(capsys.readouterr().out)
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: 0)
    assert dev.cmd_status(ns(git=True, offline=False, json=False)) == 0
    run.answers = [("git rev-parse --abbrev-ref", (128, ""))]
    assert dev._render_status(dev.status_report(tmp_path)) == "git: not a git checkout"
    (tmp_path / "todo.md").write_text("# Current objective: V9 - something\n", encoding="utf-8")
    assert dev._todo_objective(tmp_path) == "V9 - something" and dev._todo_objective(tmp_path / "none") is None
    (tmp_path / "todo.md").write_text("nothing", encoding="utf-8")
    assert dev._todo_objective(tmp_path) is None
    run.answers = [("git rev-list", (1, "")), ("git rev-parse --abbrev-ref", (0, "main"))]
    monkeypatch.setattr(dev, "ci_runs", lambda sha: None)
    assert dev.status_report()["git"]["ahead"] == "?"


def test_a_ci_job_runs_its_steps_here(run, monkeypatch, capsys, tmp_path):
    workflow = {"jobs": {"lint": {"env": {"A": 1}, "strategy": {"matrix": {"python": ["3.11", "3.12"], "include": []}},
                                  "steps": [{"uses": "actions/checkout@x"}, {"name": "go", "run": "echo ${{ matrix.python }}", "env": {"B": "${{ matrix.python }}"}}]},
                         "docker": {"services": {"db": {}}, "steps": [{"run": "docker build ."}]}}}
    steps = dev.ci_job_steps(workflow, "lint")
    assert steps[0]["uses"] == "actions/checkout@x" and steps[1]["run"] == "echo 3.11" and steps[1]["env"] == {"A": "1", "B": "3.11"}
    assert dev.ci_job_steps(workflow, "lint", {"python": "3.12"})[1]["run"] == "echo 3.12"
    assert dev.ci_job_needs(workflow) == {"lint": ["matrix"], "docker": ["docker", "services"]}
    with pytest.raises(KeyError):
        dev.ci_job_steps(workflow, "nope")
    import yaml

    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "ci.yml").write_text(yaml.safe_dump(workflow), encoding="utf-8")
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: None)
    args = dict(workflow="ci.yml", list=False, matrix=None, dry_run=False)
    assert dev.cmd_ci_local(ns(job=None, **{**args, "list": True})) == 0 and "docker  (needs: docker, services)" in capsys.readouterr().out
    assert dev.cmd_ci_local(ns(job="lnt", **args)) == 2 and "did you mean: lint" in capsys.readouterr().err
    assert dev.cmd_ci_local(ns(job="lint", **{**args, "dry_run": True})) == 0 and "echo 3.11" in capsys.readouterr().out
    codes = iter([0, 3])
    monkeypatch.setattr(dev, "run_live", lambda command, env=None: next(codes))
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/bin/bash")
    assert dev.cmd_ci_local(ns(job="lint", **args)) == 0
    assert dev.cmd_ci_local(ns(job="lint", **args)) == 3 and "failed (exit 3)" in capsys.readouterr().err
    monkeypatch.setattr(dev.shutil, "which", lambda name: None)
    assert dev.cmd_ci_local(ns(job="lint", **args)) == 1
    assert dev.cmd_ci(ns(ci_command="local", job=None, **{**args, "list": True})) == 0


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------


def test_dependabot_titles_parse_and_diffs_lose_their_lock_files():
    assert dev.parse_dependabot_title("Bump numpy from 2.5.4 to 2.5.5 in /requirements") == {
        "package": "numpy", "old": "2.5.4", "new": "2.5.5", "directory": "/requirements", "ecosystem": "pip", "major": False}
    assert dev.parse_dependabot_title("Bump vitest from 4.1.12 to 5.1.0 in /webui")["major"] is True
    assert dev.parse_dependabot_title("Bump actions/x from v4 to v5")["ecosystem"] == "github-actions"
    assert dev.parse_dependabot_title("Update torch requirement from >=2.9.1 to >=2.15.0 in /requirements")["package"] == "torch"
    assert dev.parse_dependabot_title("Bump the minor-and-patch group with 3 updates") is None
    diff = ("diff --git a/requirements/lock/ci.txt b/requirements/lock/ci.txt\n+x\n"
            "diff --git a/requirements/requirements.txt b/requirements/requirements.txt\n+numpy>=2\n")
    assert [path for path, _ in dev.split_diff(diff)] == ["requirements/lock/ci.txt", "requirements/requirements.txt"]
    assert dev.without_lock_files(diff).startswith("diff --git a/requirements/requirements.txt")


def test_lock_via_reads_uv_comments():
    lock = ("certifi==1.0 \\\n    --hash=sha256:a\n    # via\n    #   requests\n    #   httpx\nidna==3 \\\n    --hash=sha256:b\n    # via requests\nsolo==1\n")
    assert dev.lock_via(lock, "certifi") == ["requests", "httpx"] and dev.lock_via(lock, "idna") == ["requests"]
    assert dev.lock_via(lock, "solo") == [] and dev.lock_via(lock, "absent") == []


def test_deps_commands_route_to_their_scripts_and_report(run, monkeypatch, capsys, tmp_path):
    calls = []
    monkeypatch.setattr(dev, "run_live", lambda command, cwd=None, env=None: calls.append(command) or 0)
    base = dict(profile=None, upgrade_package=None, json=False, numbers=[], dry_run=False, package="x")
    assert dev.cmd_deps(ns(deps_command="lock", **{**base, "profile": ["ci"], "upgrade_package": ["numpy"]})) == 0
    assert calls[-1][1:] == ["scripts/lock_requirements.py", "--profile", "ci", "--upgrade-package", "numpy"]
    assert dev.cmd_deps(ns(deps_command="pins", **base)) == 0 and calls[-1][-1] == "scripts/scorecard_pins.py"
    monkeypatch.setattr(dev.shutil, "which", lambda name: None)
    assert dev.cmd_deps(ns(deps_command="audit", **base)) == 1 and "pip-audit not found" in capsys.readouterr().err
    assert dev.cmd_deps(ns(deps_command="prs", **base)) == 1 and "GitHub CLI" in capsys.readouterr().err
    monkeypatch.setattr(dev.shutil, "which", lambda name: f"/bin/{name}")
    assert dev.cmd_deps(ns(deps_command="audit", **base)) == 0 and calls[-1][0] == "pip-audit"
    assert dev.cmd_deps(ns(deps_command="why", **{**base, "package": "numpy", "profile": ["light"]})) == 0 and "light:" in capsys.readouterr().out
    assert dev.cmd_deps(ns(deps_command="why", **{**base, "package": "definitely-not-locked"})) == 1
    run.answers = _gh_answers()
    assert dev.cmd_deps(ns(deps_command="prs", **base)) == 0 and "numpy 2.4.6 -> 2.5.5" in capsys.readouterr().out
    assert "no open Dependabot PRs" in dev._render_prs([])
    assert "Grouped title" in dev._render_prs([{"number": 1, "title": "Grouped title", "checks": "pending", "parsed": None}])
    run.answers = [("gh pr list", (1, ""))]
    assert dev.cmd_deps(ns(deps_command="prs", **base)) == 1
    monkeypatch.setattr(dev, "apply_dependabot_pr", lambda number, dry_run=False: 0)
    assert dev.cmd_deps(ns(deps_command="apply", **{**base, "numbers": ["1"]})) == 0 and "next: aq test --impacted" in capsys.readouterr().out
    monkeypatch.setattr(dev, "needs_checkout", lambda root=dev.ROOT_DIR: 1)
    assert dev.cmd_deps(ns(deps_command="pins", **base)) == 1


def test_a_dependabot_pr_is_applied_the_way_its_ecosystem_needs(run, monkeypatch, capsys):
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, cwd=None, env=None: live.append(command) or 0)
    run.answers = [("gh pr view 1", (0, json.dumps({"title": "Bump numpy from 2.5.4 to 2.5.5 in /requirements"}))),
                   ("gh pr diff 1", (0, "diff --git a/requirements/lock/x.txt b/requirements/lock/x.txt\n+1\ndiff --git a/requirements/x.in b/requirements/x.in\n+2\n")),
                   ("git apply", (0, "")),
                   ("gh pr view 2", (0, json.dumps({"title": "Bump vitest from 4.1.12 to 5.1.0 in /webui"}))), ("npm ls", (0, "invalid: peer")),
                   ("gh pr view 3", (0, json.dumps({"title": "Bump github/codeql-action/init from 3.39.3 to 4.39.3"}))), ("gh pr diff 3", (0, "diff --git a/w b/w\n+x\n")),
                   ("gh pr view 4", (0, json.dumps({"title": "Bump the group"}))), ("gh pr view 5", (0, json.dumps({"title": "Bump a from 1 to 2"}))),
                   ("gh pr diff 5", (1, ""))]
    assert dev.apply_dependabot_pr("1") == 0 and live[-1][-2:] == ["--upgrade-package", "numpy"]
    applied = [call for call in run.calls if call[:2] == ["git", "apply"]]
    assert applied, "the non-lock files are applied with git apply"
    assert dev.apply_dependabot_pr("1", dry_run=True) == 0
    assert dev.apply_dependabot_pr("2") == 0 and live[-1] == ["npm", "install", "vitest@^5.1.0"] and "paired packages" in capsys.readouterr().err
    assert dev.apply_dependabot_pr("2", dry_run=True) == 0
    assert dev.apply_dependabot_pr("3") == 0 and "every github/codeql-action" in capsys.readouterr().err
    assert dev.apply_dependabot_pr("4") == 1 and dev.apply_dependabot_pr("5") == 1
    run.answers = [("gh pr view 6", (0, json.dumps({"title": "Bump b from 1 to 2 in /requirements"}))), ("gh pr diff 6", (0, "diff --git a/r b/r\n+x\n")),
                   ("git apply", (1, ""))]
    assert dev.apply_dependabot_pr("6") == 1 and "git apply failed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# coverage and cleaning
# ---------------------------------------------------------------------------


def test_the_coverage_summary_and_command(tmp_path, monkeypatch, capsys):
    data = {"totals": {"percent_covered": 99.5}, "files": {"a.py": {"missing_lines": [3], "summary": {"percent_covered": 90.0}}, "b.py": {"missing_lines": []}}}
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    summary = dev.coverage_summary(data, json_mtime=0.0, root=tmp_path)
    assert summary["below_100"] == {"a.py": 90.0} and summary["changed_since"] == ["a.py"] and summary["percent"] == 99.5
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path)
    assert dev.cmd_coverage(ns(coverage_command="report", json=False)) == 1 and "no coverage-report" in capsys.readouterr().err
    (tmp_path / "coverage-report").mkdir()
    (tmp_path / "coverage-report" / "coverage.json").write_text(json.dumps(data), encoding="utf-8")
    assert dev.cmd_coverage(ns(coverage_command="report", json=False)) == 3 and "a.py: 90.0%" in capsys.readouterr().out
    data["files"]["a.py"]["missing_lines"] = []
    (tmp_path / "coverage-report" / "coverage.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "a.py").touch()
    assert dev.cmd_coverage(ns(coverage_command="report", json=True)) == 0
    calls = []
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: calls.append(command) or 0)
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: None)
    assert dev.cmd_coverage(ns(coverage_command="misses", include=["risk/*"], by_function=True, context=2)) == 0
    assert calls[-1][-6:] == ["--include", "risk/*", "--by-function", "--context", "2"][-6:] or "--by-function" in calls[-1]
    assert dev.cmd_coverage(ns(coverage_command="clean", apply=False, yes=False, json=False)) == 0
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: 1)
    assert dev.cmd_coverage(ns(coverage_command="misses", include=None, by_function=False, context=None)) == 1


def test_cleaning_lists_by_default_asks_before_deleting_and_never_touches_data(tmp_path, capsys, monkeypatch):
    (tmp_path / "coverage-report").mkdir()
    (tmp_path / "coverage-report" / "c.json").write_text("x" * 10, encoding="utf-8")
    (tmp_path / ".coverage.x").write_text("y", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "lab" / "__pycache__").mkdir(parents=True)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "build").mkdir()
    (tmp_path / "data").mkdir()
    assert {path.name for path in dev.coverage_paths(tmp_path)} == {"coverage-report", ".coverage.x"}
    assert {path.relative_to(tmp_path).as_posix() for path in dev.cache_paths(tmp_path)} == {".pytest_cache", "lab/__pycache__", "__pycache__"}
    assert [path.name for path in dev.build_paths(tmp_path)] == ["build"]
    paths = [*dev.coverage_paths(tmp_path), tmp_path / "data"]
    assert dev.clean_paths(paths, apply=False, assume_yes=False, as_json=False, root=tmp_path) == 0
    assert "would delete" in capsys.readouterr().out and (tmp_path / "coverage-report").exists()
    monkeypatch.setattr(dev, "confirm", lambda prompt, assume_yes: assume_yes)
    assert dev.clean_paths(paths, apply=True, assume_yes=False, as_json=True, root=tmp_path) == 2
    assert dev.clean_paths(paths, apply=True, assume_yes=True, as_json=False, root=tmp_path) == 0
    assert not (tmp_path / "coverage-report").exists() and not (tmp_path / ".coverage.x").exists() and (tmp_path / "data").exists()
    assert dev.clean_paths([], apply=True, assume_yes=True, as_json=False, root=tmp_path) == 0


# ---------------------------------------------------------------------------
# Codespaces, vault, Problems, lint
# ---------------------------------------------------------------------------


def test_codespaces_are_listed_stopped_and_deleted_with_care(run, monkeypatch, capsys):
    monkeypatch.setattr(dev.shutil, "which", lambda name: f"/bin/{name}")
    run.answers = _gh_answers()
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: live.append(command) or 0)
    assert dev.cmd_codespace(ns(codespace_command="list", json=False)) == 0 and "cs1  Available (BILLING)" in capsys.readouterr().out
    assert dev.cmd_codespace(ns(codespace_command="stop", all=True, name=None, dry_run=False)) == 0 and live[-1] == ["gh", "codespace", "stop", "-c", "cs1"]
    assert dev.cmd_codespace(ns(codespace_command="stop", all=False, name="cs2", dry_run=True)) == 0 and len(live) == 1
    assert dev.cmd_codespace(ns(codespace_command="stop", all=False, name=None, dry_run=False)) == 2
    assert dev.cmd_codespace(ns(codespace_command="delete", name="zz", dry_run=False, yes=True)) == 2
    assert dev.cmd_codespace(ns(codespace_command="delete", name="cs2", dry_run=True, yes=False)) == 0 and "would delete cs2" in capsys.readouterr().out
    monkeypatch.setattr(dev, "confirm", lambda prompt, assume_yes: assume_yes)
    assert dev.cmd_codespace(ns(codespace_command="delete", name="cs2", dry_run=False, yes=False)) == 2
    assert dev.cmd_codespace(ns(codespace_command="delete", name="cs2", dry_run=False, yes=True)) == 0 and live[-1][:3] == ["gh", "codespace", "delete"]
    run.answers = [("gh codespace list", (0, "[]"))]
    assert dev.cmd_codespace(ns(codespace_command="list", json=False)) == 0 and "no Codespaces" in capsys.readouterr().out
    assert dev.cmd_codespace(ns(codespace_command="stop", all=True, name=None, dry_run=False)) == 0
    run.answers = [("gh codespace list", (1, ""))]
    assert dev.cmd_codespace(ns(codespace_command="list", json=False)) == 1
    monkeypatch.setattr(dev.shutil, "which", lambda name: None)
    assert dev.cmd_codespace(ns(codespace_command="list", json=False)) == 1


def test_vault_records_and_regenerates_the_graph(monkeypatch, capsys, tmp_path):
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, cwd=None, **kwargs: live.append((command, cwd)) or 0)
    assert dev.cmd_vault(ns(vault_command="record", label="rules", metric=["n=1"], paths=["a.json"], dry_run=True)) == 0
    assert "--label rules --metric n=1 a.json" in capsys.readouterr().out and not live
    assert dev.cmd_vault(ns(vault_command="record", label="rules", metric=None, paths=["a.json"], dry_run=False)) == 0
    vault = tmp_path / "Aether-quant-Obsidian-Vault"
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: None)
    graph = ns(vault_command="graph", summary="s", files=["a.py"], agent="ox", dry_run=False)
    assert dev.cmd_vault(graph) == 1 and "no Aether-quant-Obsidian-Vault" in capsys.readouterr().err
    vault.mkdir()
    assert dev.cmd_vault(graph) == 0 and live[-1][1] == vault and live[-1][0][-3:] == ["s", "--files", "a.py"]
    monkeypatch.setattr(dev, "run_live", lambda command, cwd=None, **kwargs: 5)
    assert dev.cmd_vault(graph) == 5
    assert dev.cmd_vault(ns(**{**vars(graph), "dry_run": True})) == 0


def test_problems_are_parsed_numbered_shown_and_listed(tmp_path, monkeypatch, capsys):
    text = "# P\n\n### 7. Old (V1)\n🟢 `fixed` · 1/10\n\nbody\n\n### 8a. Half (V2)\n🟡 `partial` · 2/10\n\n### 9. Gone\n🔴 `closed`\n\n### 10. Odd\nno marker\n"
    problems = dev.parse_problems(text)
    assert [(p["number"], p["status"]) for p in problems] == [("7", "fixed"), ("8a", "partial"), ("9", "closed"), ("10", "unknown")]
    assert dev.next_problem_number(problems) == 11 and dev.next_problem_number([]) == 1
    (tmp_path / "development").mkdir()
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path)
    assert dev.cmd_problems(ns(problems_command="next", json=False)) == 1
    (tmp_path / "development" / "Problems.md").write_text(text, encoding="utf-8")
    assert dev.cmd_problems(ns(problems_command="next", json=False)) == 0 and "### 11. <Title>" in capsys.readouterr().out
    assert dev.cmd_problems(ns(problems_command="show", number="8a", json=False)) == 0 and "Half" in capsys.readouterr().out
    assert dev.cmd_problems(ns(problems_command="show", number="99", json=False)) == 1
    assert dev.cmd_problems(ns(problems_command="open", json=False)) == 0 and "#8a Half" in capsys.readouterr().out
    (tmp_path / "development" / "Problems.md").write_text("### 1. A\n🟢 x\n", encoding="utf-8")
    assert dev.cmd_problems(ns(problems_command="open", json=False)) == 0 and "no partial" in capsys.readouterr().out


def test_lint_runs_ruff_and_the_type_check(monkeypatch):
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: live.append(command) or 0)
    monkeypatch.setattr(dev.shutil, "which", lambda name: None)
    assert dev.cmd_lint(ns(fix=True, types=True)) == 0
    assert live[0][-3:] == ["check", ".", "--fix"] and live[0][1:3] == ["-m", "ruff"] and live[1][-1] == "scripts/type_completeness.py"
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/bin/ruff")
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: 1)
    assert dev.cmd_lint(ns(fix=False, types=True)) == 1


# ---------------------------------------------------------------------------
# config diffs, the CLI page, links, bug reports, examples, notebooks
# ---------------------------------------------------------------------------


def test_json_leaf_diffs(run, tmp_path, capsys):
    old, new = {"a": {"b": 1, "c": [1]}, "d": 2, "e": {}}, {"a": {"b": 2, "c": [1]}, "f": 3, "e": {}}
    diff = dev.leaf_diff(old, new)
    assert diff == {"added": [["f", 3]], "removed": [["d", 2]], "changed": [["a.b", 1, 2]]}
    assert dev.render_leaf_diff(diff).splitlines() == ["+ f = 3", "- d = 2", "~ a.b: 1 -> 2"]
    assert dev.render_leaf_diff(dev.leaf_diff(old, old)) == "no differences"
    path = tmp_path / "c.json"
    path.write_text(json.dumps(new), encoding="utf-8")
    run.answers = [("git show", (0, json.dumps(old)))]
    assert dev.cmd_json_diff(path, ns(ref="HEAD", json=False), ) == 0 if False else True
    assert dev.json_file_diff(path, "HEAD", tmp_path) == diff
    assert dev.cmd_json_diff(dev.ROOT_DIR / "config.json", ns(ref="HEAD", json=True)) == 0
    run.answers = [("git show", (128, ""))]
    assert dev.json_file_diff(path, "HEAD", tmp_path) is None
    assert dev.cmd_json_diff(dev.ROOT_DIR / "config.json", ns(ref="nope", json=False)) == 1 and "git has no config.json at nope" in capsys.readouterr().err


def test_the_cli_page_is_generated_from_the_parser(tmp_path, monkeypatch, capsys):
    import aq_cli

    page = dev.render_cli_markdown(aq_cli.build_parser())
    assert "#### `aq lab train`" in page or "### `aq lab`" in page
    assert "| `--skip-coverage` |" in page and "| Flag | Meaning |" in page
    (tmp_path / "docs" / "reference").mkdir(parents=True)
    target = tmp_path / "docs" / "reference" / "cli.md"
    target.write_text("intro\n<!-- AQ:CLI_REFERENCE_START -->\nold\n<!-- AQ:CLI_REFERENCE_END -->\n", encoding="utf-8")
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path)
    assert dev.cmd_docs_extra(ns(docs_command="cli", check=True)) == 1 and "stale" in capsys.readouterr().out
    assert dev.cmd_docs_extra(ns(docs_command="cli", check=False)) == 0 and "updated" in capsys.readouterr().out
    assert dev.cmd_docs_extra(ns(docs_command="cli", check=True)) == 0
    assert dev.cmd_docs_extra(ns(docs_command="cli", check=False)) == 0 and "already current" in capsys.readouterr().out


def test_docs_build_and_serve_need_mkdocs(monkeypatch, capsys):
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: live.append(command) or 0)
    monkeypatch.setattr(dev.shutil, "which", lambda name: None)
    assert dev.cmd_docs_extra(ns(docs_command="build", strict=True)) == 1 and "mkdocs not found" in capsys.readouterr().err
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/bin/mkdocs")
    assert dev.cmd_docs_extra(ns(docs_command="build", strict=True)) == 0 and live[-1] == ["mkdocs", "build", "--strict"]
    assert dev.cmd_docs_extra(ns(docs_command="serve", port=8123)) == 0 and live[-1][-1] == "127.0.0.1:8123"
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: 4)
    assert dev.cmd_docs_extra(ns(docs_command="build", strict=False)) == 4


def test_links_and_anchors_are_checked(tmp_path, monkeypatch, capsys):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("# Title Here\n\n## Second, part\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "[ok](docs/a.md#title-here) [bad](docs/missing.md) [anchor](docs/a.md#nope) [self](#top) [web](https://x.y) ![img](pic.png)\n"
        "```\n[ignored](docs/none.md)\n```\n`[code](docs/none.md)`\n# Top\n", encoding="utf-8")
    problems = dev.broken_links([tmp_path / "README.md", tmp_path / "docs" / "a.md"], root=tmp_path)
    assert problems == ["README.md: docs/missing.md", "README.md: docs/a.md#nope (no such heading)"]
    assert dev.markdown_anchors("# A b\n## Second, part ##\n") == {"a-b", "second-part"}
    assert dev.external_links([tmp_path / "README.md"]) == ["https://x.y"]
    assert dev.check_external("http://127.0.0.1:1/", timeout=0.2) is False
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(dev, "check_external", lambda url: False)
    assert {path.name for path in dev.link_docs(tmp_path)} == {"README.md", "a.md"}
    assert dev.cmd_docs_extra(ns(docs_command="links", external=True, json=False)) == 1 and "external: https://x.y" in capsys.readouterr().out
    (tmp_path / "README.md").write_text("[ok](docs/a.md)\n", encoding="utf-8")
    assert dev.cmd_docs_extra(ns(docs_command="links", external=False, json=False)) == 0 and "every relative link resolves" in capsys.readouterr().out


def test_check_external_accepts_a_live_page(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: Response())
    assert dev.check_external("https://example.org") is True


def test_the_bug_report_masks_home_and_user(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(dev, "doctor_checks", lambda root=dev.ROOT_DIR: [dev._check("x", "ok", str(Path.home() / "thing"))])
    monkeypatch.setenv("USERNAME", "someone_unique")
    monkeypatch.setattr(dev, "render_checks", lambda checks: f"someone_unique at {checks[0]['detail']}")
    text = dev.bug_report()
    assert str(Path.home()) not in text and "someone_unique" not in text and "<user>" in text and "## Environment" in text
    out = tmp_path / "issue.md"
    assert dev.cmd_bug_report(ns(out=str(out))) == 0 and out.exists()
    assert dev.cmd_bug_report(ns(out=None)) == 0 and "## aq doctor" in capsys.readouterr().out
    monkeypatch.setattr(dev, "_package_version", lambda name: (_ for _ in ()).throw(dev.PackageNotFoundError(name)))
    monkeypatch.delenv("USERNAME")
    monkeypatch.delenv("USER", raising=False)
    assert "not installed" in dev.bug_report()


def test_examples_and_notebooks_are_listed_and_run(tmp_path, monkeypatch, capsys):
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "demo.py").write_text('"""A demo of things."""\n', encoding="utf-8")
    (tmp_path / "examples" / "bare.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path)
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: live.append(command) or 0)
    assert dev.cmd_examples(ns(examples_command="list", json=False)) == 0 and "demo: A demo of things" in capsys.readouterr().out
    assert dev.cmd_examples(ns(examples_command="run", name="demo")) == 0 and live[-1][-1].endswith("demo.py")
    assert dev.cmd_examples(ns(examples_command="run", name="dem")) == 2 and "did you mean: demo" in capsys.readouterr().err
    (tmp_path / "docs" / "tutorials").mkdir(parents=True)
    book = {"cells": [{"cell_type": "code", "source": ["1"]}, {"cell_type": "markdown", "source": ["# Hello world\n"]}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    (tmp_path / "docs" / "tutorials" / "00_hello.ipynb").write_text(json.dumps(book), encoding="utf-8")
    (tmp_path / "docs" / "tutorials" / "01_plain.ipynb").write_text(json.dumps({**book, "cells": []}), encoding="utf-8")
    assert dev.cmd_notebooks(ns(notebooks_command="list", json=False)) == 0
    out = capsys.readouterr().out
    assert "00_hello: Hello world" in out and "01_plain: 01_plain" in out
    assert dev.cmd_notebooks(ns(notebooks_command="run", name="missing", out=None)) == 2
    monkeypatch.setitem(sys.modules, "nbclient", None)
    assert dev.cmd_notebooks(ns(notebooks_command="run", name="hello", out=None)) == 1 and "notebooks" in capsys.readouterr().err
    executed = []
    monkeypatch.setitem(sys.modules, "nbclient", SimpleNamespace(NotebookClient=lambda book, **kwargs: SimpleNamespace(execute=lambda: executed.append(1))))
    monkeypatch.setitem(sys.modules, "nbformat", SimpleNamespace(read=lambda path, as_version: {"cells": []}, write=lambda book, path: Path(path).write_text("{}")))
    assert dev.cmd_notebooks(ns(notebooks_command="run", name="00_hello", out=str(tmp_path / "o.ipynb"))) == 0 and (tmp_path / "o.ipynb").exists()
    assert dev.cmd_notebooks(ns(notebooks_command="run", name="hello", out=None)) == 0 and executed == [1, 1]
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path / "nowhere")
    assert dev.cmd_examples(ns(examples_command="list", json=False)) == 0 and "no examples/" in capsys.readouterr().out
    assert dev.cmd_notebooks(ns(notebooks_command="list", json=False)) == 0 and "no docs/tutorials" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# phase check and scaffolding
# ---------------------------------------------------------------------------


def test_the_phase_check_marks_what_it_can_check(tmp_path, monkeypatch, run, capsys):
    root = tmp_path
    (root / "development").mkdir()
    (root / "development" / "Changelog.md").write_text("## Phase V9 — x\n", encoding="utf-8")
    (root / "docs" / "about").mkdir(parents=True)
    (root / "docs" / "about" / "changelog.md").write_text("V9 highlights\n", encoding="utf-8")
    (root / "todo.md").write_text("V9\n", encoding="utf-8")
    (root / "scripts").mkdir()
    for name in ("scorecard_pins.py", "library_gate.py"):
        (root / "scripts" / name).write_text("", encoding="utf-8")
    vault = root / "Aether-quant-Obsidian-Vault"
    vault.mkdir()
    import datetime as datetime_module

    (vault / "HANDOFF.md").write_text(datetime_module.date.today().isoformat(), encoding="utf-8")
    run.answers = [("git status --porcelain", (0, "")), ("scripts/library_gate.py", (1, "library gate: 2 problem(s)\n"))]
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/bin/gh")
    monkeypatch.setattr(dev, "ci_runs", lambda sha: [{"workflowName": "CI", "status": "completed", "conclusion": "success", "jobs": []}])
    monkeypatch.setattr(dev, "codespaces", lambda: [{"name": "c", "state": "Available"}])
    checks = {check["name"]: check for check in dev.phase_checks("V9", root)}
    assert checks["Changelog phase"]["status"] == "ok" and checks["todo.md"]["status"] == "ok" and checks["library gate"]["status"] == "fail"
    assert checks["coverage 100%"]["status"] == "fail" and checks["CI of HEAD"]["status"] == "ok" and checks["Codespaces stopped"]["status"] == "fail"
    assert checks["vault handoff"]["status"] == "ok" and checks["clean tree"]["status"] == "ok"
    assert any(check["status"] == "manual" for check in checks.values())
    (root / "coverage-report").mkdir()
    (root / "coverage-report" / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 100}, "files": {}}), encoding="utf-8")
    monkeypatch.setattr(dev, "ci_runs", lambda sha: None)
    checks = {check["name"]: check for check in dev.phase_checks("V8", root)}
    assert checks["coverage 100%"]["status"] == "ok" and checks["Changelog phase"]["status"] == "fail" and checks["CI of HEAD"]["detail"] == "unknown"
    monkeypatch.setattr(dev, "phase_checks", lambda version: [dev._check("a", "fail", "d", "f"), dev._check("b", "manual", "m")])
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: None)
    assert dev.cmd_phase(ns(version="V9", json=False)) == 3 and "✗ a: d  -> f" in capsys.readouterr().out
    monkeypatch.setattr(dev, "phase_checks", lambda version: [dev._check("a", "ok", "d")])
    assert dev.cmd_phase(ns(version="V9", json=True)) == 0
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: 1)
    assert dev.cmd_phase(ns(version="V9", json=False)) == 1


def test_test_files_register_in_their_group_and_modules_scaffold_with_reminders(tmp_path, monkeypatch, capsys):
    text = '_SUBSYSTEM_TEST_FILES: dict[str, list[str]] = {\n    "risk": [\n        "test_a.py",\n    ],\n}\n'
    updated = dev.register_test_file(text, "risk", "test_b.py")
    assert updated.index('"test_b.py"') < updated.index('"test_a.py"') and dev.register_test_file(updated, "risk", "test_b.py") == updated
    assert dev.infer_group("risk/x.py", ["risk", "meta"]) == "risk" and dev.infer_group("data_pipeline/x.py", ["data-pipeline", "meta"]) == "data-pipeline"
    assert dev.infer_group("tool.py", ["meta", "risk"]) == "meta" and dev.infer_group("odd/x.py", ["zeta", "alpha"]) == "alpha"
    pyproject = 'name = "x"\npy-modules = ["b", "a"]\n'
    assert 'py-modules = ["a", "b", "c"]' in dev.add_py_module(pyproject, "c") and dev.add_py_module(pyproject, "a") == pyproject
    with pytest.raises(ValueError, match="py-modules"):
        dev.add_py_module("name = 1\n", "c")
    root = tmp_path
    (root / "tests").mkdir()
    (root / "risk").mkdir()
    import aq_cli

    (root / "aq_cli.py").write_text(Path(aq_cli.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    (root / "pyproject.toml").write_text('py-modules = ["aq_cli"]\n', encoding="utf-8")
    code, actions = dev.scaffold_module("risk/new_rule.py", group=None, root=root, dry_run=True)
    assert code == 0 and not (root / "risk" / "new_rule.py").exists() and any("register it under 'risk'" in action for action in actions)
    code, actions = dev.scaffold_module("risk/new_rule.py", group=None, root=root)
    assert code == 0 and (root / "risk" / "new_rule.py").exists() and '"test_new_rule.py"' in (root / "aq_cli.py").read_text(encoding="utf-8")
    assert "assert False" in (root / "tests" / "test_new_rule.py").read_text(encoding="utf-8")
    assert dev.scaffold_module("risk/new_rule.py", group=None, root=root)[0] == 1
    assert dev.scaffold_module("risk/x.txt", group=None, root=root)[0] == 2
    assert dev.scaffold_module("nowhere/x.py", group=None, root=root)[0] == 2
    assert dev.scaffold_module("top_tool.py", group="meta", root=root)[0] == 0 and '"top_tool"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert dev.scaffold_test("risk/other.py", group="no-such-group", root=root)[0] == 2
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: None)
    monkeypatch.setattr(dev, "scaffold_module", lambda path, group, dry_run: (0, ["create x", "rule 14: y"]))
    assert dev.cmd_scaffold(ns(path="x.py", group=None, dry_run=True)) == 0 and "would create x\nrule 14: y" in capsys.readouterr().out
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: 1)
    assert dev.cmd_scaffold(ns(path="x.py", group=None, dry_run=False)) == 1


def test_register_adds_every_developer_command():
    import aq_cli

    choices = dev._subparsers_of(aq_cli.build_parser())
    for name in ("hooks", "commit", "check", "doctor", "version", "completion", "help", "status", "ci", "deps", "coverage", "codespace", "vault", "problems",
                 "lint", "scaffold", "phase", "bug-report", "examples", "notebooks"):
        assert name in choices and choices[name].epilog.startswith("Examples:")


def test_ram_on_windows_comes_from_global_memory_status(monkeypatch):
    import ctypes

    def fill(reference):
        reference._obj.total = 8_000_000_000
        return 1

    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(dev.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=fill)), raising=False)
    assert dev._total_ram_gb() == 8.0


def test_an_open_port_is_seen(tmp_path):
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        assert dev._tcp_open("127.0.0.1", server.getsockname()[1], timeout=2) is True


def test_red_ci_names_the_logs_command_and_checkout_commands_refuse_a_wheel_install(run, monkeypatch, capsys):
    monkeypatch.setattr(dev.shutil, "which", lambda name: f"/bin/{name}")
    run.answers = _gh_answers(conclusion="failure")
    assert dev.cmd_ci(ns(ci_command="status", sha="HEAD", branch=None, watch=False, interval=1, json=False)) == 1
    assert "details: aq ci logs <run-id>" in capsys.readouterr().out
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: 1)
    assert dev.cmd_ci_local(ns(job="x", workflow="ci.yml", list=False, matrix=None, dry_run=True)) == 1
    assert dev.cmd_vault(ns(vault_command="graph", summary="s", files=["a.py"], agent="ox", dry_run=True)) == 1


def test_coverage_report_says_when_files_changed_after_it(tmp_path, monkeypatch, capsys):
    import os

    (tmp_path / "coverage-report").mkdir()
    (tmp_path / "coverage-report" / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 100.0}, "files": {"a.py": {"missing_lines": []}}}), encoding="utf-8")
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    later = (tmp_path / "coverage-report" / "coverage.json").stat().st_mtime + 60
    os.utime(tmp_path / "a.py", (later, later))
    monkeypatch.setattr(dev, "ROOT_DIR", tmp_path)
    assert dev.cmd_coverage(ns(coverage_command="report", json=False)) == 0
    assert "1 file(s) changed since" in capsys.readouterr().out


def test_a_test_file_is_never_overwritten(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_kelly.py").write_text("", encoding="utf-8")
    code, actions = dev.scaffold_test("risk/kelly.py", group="risk", root=tmp_path)
    assert code == dev.EXIT_FAIL and actions == ["tests/test_kelly.py already exists"]
