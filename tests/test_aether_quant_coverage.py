"""The library gate (V6.6.4): `aether_quant` is updated by any change that adds a public function, or the change says why it stays out.

It reads the source with `ast` and imports nothing, so it runs in the fast guards and in the pre-commit hook. `scripts/library_gate.py` holds the logic; this file proves the logic catches what
it should, on small trees, and runs it on the real one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_gate as gate  # noqa: E402


def _tree(tmp_path: Path, *, exports: str = "", extra_module: str = "", facade_module: str = "risk") -> Path:
    """A miniature repo: one shipped package `pkg` with `pure.py`, a facade, and the two lists the gate cross-checks."""
    (tmp_path / "pyproject.toml").write_text('[tool.setuptools]\npy-modules = ["top"]\npackages = ["pkg", "aether_quant"]\n', encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "pure.py").write_text("def kept():\n    pass\n\n\ndef _private():\n    pass\n\n\nclass Thing:\n    pass\n" + extra_module, encoding="utf-8")
    (tmp_path / "top.py").write_text("def top_level():\n    pass\n", encoding="utf-8")
    (tmp_path / "aether_quant").mkdir()
    (tmp_path / "aether_quant" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "aether_quant" / f"{facade_module}.py").write_text(exports, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "data").mkdir()
    return tmp_path


def test_a_new_public_function_that_no_facade_exports_is_a_violation(tmp_path):
    root = _tree(tmp_path, exports="from pkg.pure import kept, Thing\nfrom top import top_level\n__all__ = ['kept', 'Thing', 'top_level']\n")
    assert gate.check(root, {"modules": {}, "unexported": {}, "legacy_names": []}, ceiling=0) == []
    (root / "pkg" / "pure.py").write_text((root / "pkg" / "pure.py").read_text(encoding="utf-8") + "\n\ndef added_today():\n    pass\n", encoding="utf-8")
    problems = gate.check(root, {"modules": {}, "unexported": {}, "legacy_names": []}, ceiling=0)
    assert len(problems) == 1 and "pkg.pure:added_today" in problems[0] and "export it" in problems[0]


def test_an_alias_counts_as_the_name_it_re_exports(tmp_path):
    root = _tree(tmp_path, exports="from pkg.pure import kept as renamed, Thing\nfrom top import top_level\n__all__ = ['renamed', 'Thing', 'top_level']\n")
    assert gate.check(root, {"modules": {}, "unexported": {}, "legacy_names": []}, ceiling=0) == []


def test_a_listed_name_with_a_reason_passes_and_a_stale_entry_fails(tmp_path):
    root = _tree(tmp_path, exports="from pkg.pure import Thing\nfrom top import top_level\n__all__ = ['Thing', 'top_level']\n")
    allow = {"modules": {}, "unexported": {"pkg.pure:kept": "an internal helper"}, "legacy_names": []}
    assert gate.check(root, allow, ceiling=0) == []
    stale = {"modules": {}, "unexported": {"pkg.pure:kept": "x", "pkg.pure:Thing": "now exported, entry should go"}, "legacy_names": []}
    problems = gate.check(root, stale, ceiling=0)
    assert len(problems) == 1 and "pkg.pure:Thing" in problems[0] and "remove the entry" in problems[0]
    assert any("without a reason" in line for line in gate.check(root, {"modules": {}, "unexported": {"pkg.pure:kept": " "}, "legacy_names": []}, ceiling=0))


def test_the_legacy_list_can_only_shrink(tmp_path):
    root = _tree(tmp_path, exports="from top import top_level\n__all__ = ['top_level']\n")
    legacy = {"modules": {}, "unexported": {}, "legacy_names": ["pkg.pure:Thing", "pkg.pure:kept"]}
    assert gate.check(root, legacy, ceiling=2) == []
    over = gate.check(root, legacy, ceiling=1)
    assert len(over) == 1 and "ceiling 1" in over[0]
    fixed = {"modules": {}, "unexported": {}, "legacy_names": ["pkg.pure:Thing", "pkg.pure:kept", "pkg.pure:gone"]}
    assert any("pkg.pure:gone" in line and "remove the entry" in line for line in gate.check(root, fixed, ceiling=3))


def test_a_module_exclusion_covers_a_whole_module_by_pattern(tmp_path):
    root = _tree(tmp_path, exports="from top import top_level\n__all__ = ['top_level']\n")
    allow = {"modules": {"pkg.*": "not library material"}, "unexported": {}, "legacy_names": []}
    assert gate.check(root, allow, ceiling=0) == []


def test_a_facade_the_other_lists_do_not_know_is_a_violation(tmp_path):
    root = _tree(tmp_path, exports="from top import top_level\n__all__ = ['top_level']\n", facade_module="newfacade")
    allow = {"modules": {"pkg.*": "x"}, "unexported": {}, "legacy_names": []}
    problems = gate.check(root, allow, ceiling=0, listed_modules=["risk"], wheel_modules=["newfacade"])
    assert len(problems) == 1 and "tests/test_aether_quant_api.py MODULES" in problems[0] and "newfacade" in problems[0]


def test_the_real_tree_passes_the_gate():
    allow = gate.load_allowlist()
    problems = gate.check(ROOT, allow, listed_modules=gate.api_test_modules(), wheel_modules=gate.wheel_check_modules())
    assert problems == [], "\n".join(problems)


def test_the_real_ceiling_matches_the_list_and_every_reason_is_written():
    allow = gate.load_allowlist()
    assert len(allow["legacy_names"]) <= gate.LEGACY_CEILING
    assert all(str(reason).strip() for reason in allow["modules"].values())
    assert allow["legacy_names"] == sorted(set(allow["legacy_names"])), "the legacy list is sorted and has no duplicates"


def test_the_gate_imports_nothing_heavy():
    code = "import sys; sys.path.insert(0, 'scripts'); import library_gate; library_gate.check(); print(sorted(m for m in ('torch', 'pandas', 'numpy', 'sklearn') if m in sys.modules))"
    import subprocess

    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_the_real_allowlist_is_valid_json_with_the_expected_keys():
    allow = json.loads((ROOT / "tests" / "data" / "aether_quant_unexported.json").read_text(encoding="utf-8"))
    assert {"modules", "unexported", "legacy_names"} <= set(allow)


@pytest.mark.parametrize("name", ["aq_cli", "monitoring.api_server", "experience.redis_queue"])
def test_the_modules_that_are_not_library_material_are_excluded_with_a_reason(name):
    assert gate.load_allowlist()["modules"][name].strip()
