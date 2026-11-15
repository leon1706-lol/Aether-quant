"""The ruff configuration behind OpenSSF `warnings_strict` (V6.6.8, #379): the rule sets CI's python-lint enforces, the
interpreter floor they target, and a written reason above every exclusion."""

from __future__ import annotations

import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
RULE_SETS = ("E", "F", "W", "PLE", "PIE", "SIM", "PERF", "N", "UP", "PLW", "C4", "I", "B", "RUF")


def _config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _section(text: str, header: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(header) + 1
    end = next((index for index in range(start, len(lines)) if lines[index].startswith("[")), len(lines))
    return lines[start:end]


def test_every_rule_set_is_selected():
    assert set(RULE_SETS) <= set(_config()["tool"]["ruff"]["lint"]["select"])


def test_ruff_targets_the_oldest_supported_python():
    config = _config()
    floor = re.fullmatch(r">=3\.(\d+)", config["project"]["requires-python"])
    assert floor and config["tool"]["ruff"]["target-version"] == f"py3{floor.group(1)}"


def test_every_ignored_rule_has_its_reason_on_the_line_above():
    text = PYPROJECT.read_text(encoding="utf-8")
    lint = _section(text, "[tool.ruff.lint]")
    start = lint.index("ignore = [")
    body = lint[start + 1:lint.index("]", start)]
    ignored = [index for index, line in enumerate(body) if line.strip().startswith('"')]
    assert len(ignored) == len(_config()["tool"]["ruff"]["lint"]["ignore"])
    for index in ignored:
        assert index > 0 and body[index - 1].strip().startswith("# "), f"no reason above {body[index].strip()}"


def test_every_per_file_ignore_has_its_reason_on_the_line_above():
    lines = _section(PYPROJECT.read_text(encoding="utf-8"), "[tool.ruff.lint.per-file-ignores]")
    entries = [index for index, line in enumerate(lines) if line.startswith('"')]
    assert len(entries) == len(_config()["tool"]["ruff"]["lint"]["per-file-ignores"])
    for index in entries:
        assert index > 0 and lines[index - 1].startswith("# "), f"no reason above {lines[index]}"


def test_main_py_imports_are_never_re_sorted():
    # AGENTS rule 10: Lean's star import must come before the builtins and time re-imports
    assert "I001" in _config()["tool"]["ruff"]["lint"]["per-file-ignores"]["main.py"]
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert source.index("from AlgorithmImports import *") < source.index("from builtins import Exception")


def test_the_lint_job_runs_the_configured_sets():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Ruff check (rule sets in pyproject.toml)" in workflow and "run: ruff check ." in workflow
