"""One test file per source module (V6.6.4): the convention in tests/README.md, as a check.

A shipped module needs `tests/test_<module>.py`, or an entry in `tests/data/modules_without_own_test.json` (the modules that were without one when this check was added, each exercised by a
round file). The list can only shrink: a module that has gained its own file must leave it, and the ceiling below is only ever lowered. It reads the source tree with `pathlib` and imports
nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_gate as gate  # noqa: E402

BASELINE = ROOT / "tests" / "data" / "modules_without_own_test.json"
CEILING = 24  # the modules without a test file of their own when the check was added; lower it when one gains one


def modules_without_a_test() -> list[str]:
    packages, top_level = gate.shipped_roots(ROOT)
    tests = {path.stem for path in (ROOT / "tests").glob("test_*.py")}
    missing = [module for module in top_level if f"test_{module}" not in tests]
    for package in packages:
        for path in sorted((ROOT / package).rglob("*.py")):
            if "__pycache__" in path.parts or path.name == "__init__.py":
                continue
            if f"test_{path.stem}" not in tests:
                missing.append(".".join(path.relative_to(ROOT).with_suffix("").parts))
    return sorted(missing)


def test_every_shipped_module_has_a_test_file_or_is_on_the_frozen_list():
    listed = set(json.loads(BASELINE.read_text(encoding="utf-8"))["modules"])
    unlisted = [module for module in modules_without_a_test() if module not in listed]
    assert not unlisted, f"add tests/test_<name>.py for {unlisted} (one test file per source module), or say why in tests/data/modules_without_own_test.json"


def test_the_frozen_list_only_shrinks():
    listed = json.loads(BASELINE.read_text(encoding="utf-8"))["modules"]
    current = set(modules_without_a_test())
    stale = [module for module in listed if module not in current]
    assert not stale, f"{stale} now have a test file or no longer exist: remove them from tests/data/modules_without_own_test.json"
    assert len(listed) <= CEILING, f"the list holds {len(listed)} modules, above the ceiling {CEILING}"
    assert listed == sorted(set(listed))
