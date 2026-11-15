"""scripts/README.md names every script, as a tool or a record (V6.6.7, todo.md backlog C)."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "scripts" / "README.md"


def _patterns() -> set[str]:
    out: set[str] = set()
    for token in re.findall(r"`([^`]+)`", README.read_text(encoding="utf-8")):
        for part in re.split(r"[ ,]+", token):
            part = part.strip("()")
            if part:
                out.add(part)
    return out


def _scripts() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "scripts"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=60).stdout
    return sorted(path[len("scripts/"):] for path in listed.split() if path.count("/") == 1 and path != "scripts/README.md")


def test_every_script_is_named_as_a_tool_or_a_record():
    patterns = _patterns()
    unnamed = [name for name in _scripts()
               if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
               and not re.match(r"v6\d\d", name) and not name.endswith("_research.py")]
    assert not unnamed, f"name these in scripts/README.md (a tool, or a record of a past phase): {unnamed}"


def test_the_readme_says_what_a_record_is():
    text = README.read_text(encoding="utf-8")
    assert "**Record or tool" in text and "*(record)*" in text and "Past research chains" in text
