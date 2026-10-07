"""Packaging guard (V5.5.0 CI): every first-party module the INSTALLED `aq`
can import must be shipped in the wheel.

pyproject.toml lists `py-modules` and `packages` by hand, and an editable
install (`pip install -e .`, what every dev and the cli-smoke job use) puts
the whole repo root on sys.path, so a missing entry is invisible there - it
only fails for a real wheel install, as `ModuleNotFoundError` at the user's
first `aq` command. Two such regressions already happened (see the comment
at pyproject.toml's `py-modules`). This closes the loop statically: scan
every shipped file's imports (lazy function-level imports included, which is
how aq_cli.py pulls in nearly everything) and require each first-party root
to be shipped itself.

Conventions match the rest of this repo: no test classes, module-level
helpers. Pure static analysis - nothing is installed or imported."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - CI's 3.10 leg only compiles, but keep the guard importable
    tomllib = pytest.importorskip("tomli")

ROOT = Path(__file__).resolve().parents[1]

# Modules aq_cli.py reaches only through a subprocess / `python -m`, a
# console script of a SEPARATE service, or a deliberately optional import
# guarded by try/except ImportError - never an in-process import of the
# installed `aq`. Each entry needs a reason; an unexplained one is a bug.
INTENTIONALLY_NOT_SHIPPED = {
    "main": "Lean algorithm entry point; runs inside the Lean container, never imported by aq",
    "train": "`aq train` runs `python train.py` as a subprocess against the project checkout",
    "train_gating": "run as a script by retraining/orchestrator via subprocess",
    "train_multitask": "run as a script by retraining/orchestrator via subprocess",
    "train_sequence": "run as a script by retraining/orchestrator via subprocess",
    "train_topology": "run as a script by retraining/orchestrator via subprocess",
    "train_strategy_selector": "run as a script by retraining/orchestrator via subprocess",
    "train_rl_sizing": "run as a script by retraining/orchestrator via subprocess",
}


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _shipped() -> tuple[set[str], set[str]]:
    setuptools_config = _pyproject()["tool"]["setuptools"]
    return set(setuptools_config.get("py-modules", [])), set(setuptools_config.get("packages", []))


def _first_party_roots() -> set[str]:
    """Top-level names that exist in this checkout (a package dir or a root
    .py file) - everything else imported is third-party/stdlib."""
    roots = {path.stem for path in ROOT.glob("*.py")}
    roots |= {path.parent.name for path in ROOT.glob("*/__init__.py")}
    return roots


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _shipped_files() -> list[Path]:
    py_modules, packages = _shipped()
    files = [ROOT / f"{module}.py" for module in py_modules]
    for package in packages:
        files.extend(sorted((ROOT / package).rglob("*.py")))
    return [path for path in files if path.exists()]


def test_pyproject_ships_only_things_that_exist():
    py_modules, packages = _shipped()
    missing = [f"{module}.py" for module in py_modules if not (ROOT / f"{module}.py").exists()]
    missing += [package for package in packages if not (ROOT / package / "__init__.py").exists()]
    assert not missing, f"pyproject.toml ships paths that do not exist: {missing}"


def test_every_first_party_import_inside_the_shipped_set_is_itself_shipped():
    py_modules, packages = _shipped()
    shipped_roots = py_modules | packages
    first_party = _first_party_roots()
    problems: dict[str, set[str]] = {}
    for path in _shipped_files():
        unshipped = {
            root
            for root in _imported_roots(path)
            if root in first_party and root not in shipped_roots and root not in INTENTIONALLY_NOT_SHIPPED
        }
        if unshipped:
            problems[str(path.relative_to(ROOT))] = unshipped
    assert not problems, (
        "these shipped files import first-party modules that pyproject.toml does not ship "
        "(add them to py-modules/packages and `pip install -e .`, or list them in "
        "INTENTIONALLY_NOT_SHIPPED with a reason):\n"
        + "\n".join(f"  {file}: {sorted(roots)}" for file, roots in sorted(problems.items()))
    )


def test_every_intentionally_unshipped_module_really_is_unshipped_and_still_exists():
    py_modules, packages = _shipped()
    stale = [name for name in INTENTIONALLY_NOT_SHIPPED if name in py_modules | packages]
    assert not stale, f"listed as not-shipped but pyproject.toml ships them: {stale} - drop the exemption"
    gone = [name for name in INTENTIONALLY_NOT_SHIPPED if name not in _first_party_roots()]
    assert not gone, f"exempted modules no longer exist: {gone} - drop the exemption"


def test_new_v550_top_level_modules_are_registered():
    py_modules, _ = _shipped()
    assert {"json_safety", "performance_probe", "risk_controls"} <= py_modules
