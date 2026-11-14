"""The coverage gate measures the whole repository at 100%, with no pragma (V6.6.6, #359)."""

from __future__ import annotations

import fnmatch
import subprocess
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]


def _tracked_python() -> list[str]:
    output = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=60).stdout
    return [line for line in output.splitlines() if line and not line.startswith("tests/")]


def test_every_tracked_module_outside_tests_is_measured():
    dirs = {str(Path(path).parent.as_posix()) for path in _tracked_python()}
    assert set(CONFIG["run"]["source_dirs"]) == dirs, "a directory holding tracked code must be searched for never-imported files"
    omitted = [path for path in _tracked_python() if any(fnmatch.fnmatch(path, pattern) for pattern in CONFIG["run"]["omit"])]
    assert not omitted, f"tracked code left out of coverage: {omitted}"
    assert "tests/*" in CONFIG["run"]["omit"]


def test_the_gate_is_100_and_type_checking_blocks_are_the_one_exclusion():
    assert CONFIG["report"]["fail_under"] == 100
    assert CONFIG["report"]["exclude_lines"] == ["if TYPE_CHECKING:"]


def test_no_tracked_module_hides_a_line_from_coverage():
    marker = "pragma: " + "no cover"
    hiding = [path for path in _tracked_python() if marker in (ROOT / path).read_text(encoding="utf-8", errors="replace")]
    assert not hiding, f"{marker} in {hiding}"


def test_ci_fails_under_100():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    step = next(step for step in ci["jobs"]["python-tests"]["steps"] if "--cov-fail-under" in step.get("run", ""))
    assert "--cov-fail-under=100" in step["run"]
