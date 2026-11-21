"""scripts/install_hooks.py: the wrapper goes into .git/hooks, never over someone else's hook, and the hook it calls runs the library gate (V6.6.4)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install_hooks as hooks  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_install_writes_the_wrapper_once_and_reports_it_installed(tmp_path):
    repo = _repo(tmp_path)
    assert not hooks.installed(repo)
    assert hooks.install(repo).startswith("installed")
    assert hooks.installed(repo)
    text = (hooks.hooks_directory(repo) / "pre-commit").read_text(encoding="utf-8")
    assert hooks.MARKER in text and ".githooks/pre-commit" in text
    assert hooks.install(repo).startswith("installed"), "a second install is the same file"


def test_a_hook_that_is_not_ours_is_left_alone(tmp_path):
    repo = _repo(tmp_path)
    foreign = hooks.hooks_directory(repo) / "pre-commit"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("#!/bin/sh\necho someone else's hook\n", encoding="utf-8")
    assert "left alone" in hooks.install(repo)
    assert "someone else's hook" in foreign.read_text(encoding="utf-8") and not hooks.installed(repo)


def test_the_hook_the_wrapper_calls_runs_the_secret_check_and_the_library_gate():
    text = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "secrets-check" in text and "scripts/library_gate.py" in text
    assert text.index("secrets-check") < text.index("library_gate"), "secrets are checked first"
    # V6.6.7 (#361, #367): the pins and the coverage of the changed modules, the slow one last and skippable by name only
    assert text.index("library_gate") < text.index("scripts/scorecard_pins.py") < text.index("ruff check $staged") < text.index("test --coverage --changed")
    # V6.7.1: `aq commit --skip-coverage` sets the variable for one commit; `aq hooks coverage off [--once]` leaves the marker
    assert '"${AQ_SKIP_COVERAGE_HOOK:-0}" = "1"' in text and "git rev-parse --git-path aq-skip-coverage" in text


def _hook_repo(tmp_path):
    """A git repo holding the real hook, stub gate scripts and a fake `aq` on PATH that logs its arguments."""
    import shutil
    import subprocess

    repo = tmp_path / "repo"
    (repo / ".githooks").mkdir(parents=True)
    shutil.copy(ROOT / ".githooks" / "pre-commit", repo / ".githooks" / "pre-commit")
    (repo / "scripts").mkdir()
    for name in ("library_gate.py", "formal_inventory.py", "scorecard_pins.py"):
        (repo / "scripts" / name).write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "aq.log"
    fake = bin_dir / "aq"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log.as_posix()}"\n', encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo, bin_dir, log


def test_the_hook_runs_skips_once_or_stays_off_as_its_switch_says(tmp_path):
    import os
    import shutil
    import subprocess

    sh = shutil.which("sh")
    if sh is None:
        import pytest

        pytest.skip("no sh on this machine")
    repo, bin_dir, log = _hook_repo(tmp_path)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env.pop("AQ_SKIP_COVERAGE_HOOK", None)

    def hook(extra=None):
        result = subprocess.run([sh, ".githooks/pre-commit"], cwd=repo, env={**env, **(extra or {})}, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    marker = repo / ".git" / "aq-skip-coverage"
    assert "coverage of the changed modules checked" in hook() and "test --coverage --changed" in log.read_text(encoding="utf-8")
    assert "skipped (AQ_SKIP_COVERAGE_HOOK=1)" in hook({"AQ_SKIP_COVERAGE_HOOK": "1"})
    marker.write_text("once", encoding="utf-8")
    assert "skipped (once" in hook() and not marker.exists(), "once clears itself"
    marker.write_text("persistent", encoding="utf-8")
    assert "skipped (persistent" in hook() and "skipped (persistent" in hook() and marker.exists()


def test_the_wrapper_does_nothing_where_the_script_it_calls_does_not_exist():
    from scripts.install_hooks import WRAPPER

    assert '[ -f "$repo_root/.githooks/pre-commit" ] || exit 0' in WRAPPER and WRAPPER.index("|| exit 0") < WRAPPER.index("exec sh")


def test_main_installs_and_checks(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    monkeypatch.setattr(hooks, "ROOT", repo)
    monkeypatch.setattr(hooks, "installed", lambda root=repo: (repo / ".git" / "hooks" / "pre-commit").exists())
    monkeypatch.setattr(hooks, "install", lambda root=repo: (repo / ".git" / "hooks" / "pre-commit").write_text("x") and "installed here")
    assert hooks.main(["--check"]) == 1 and "not installed" in capsys.readouterr().out
    assert hooks.main([]) == 0 and "installed here" in capsys.readouterr().out
    assert hooks.main(["--check"]) == 0


def test_a_hook_that_cannot_be_made_executable_is_still_installed(tmp_path, monkeypatch):
    repo = _repo(tmp_path)

    def refuse(self, mode):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "chmod", refuse)
    assert hooks.install(repo).startswith("installed ") and hooks.installed(repo)


def test_the_check_runs_as_a_script(monkeypatch, capsys):
    from script_loader import run_script

    assert run_script("install_hooks", ["--check"], monkeypatch) in (0, 1)
    assert "installed" in capsys.readouterr().out
