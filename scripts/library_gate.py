"""The library gate (V6.6.4): every public function or class in a shipped package is either in `aether_quant` or listed with a reason.

`aether_quant` is the toolkit people import. It was updated by hand, so a new capability could ship without reaching it. This reads the source with `ast` and imports nothing, so it runs in
a pre-commit hook in about a second, and CI runs the same check. It fails when:

1. `aether_quant/*.py` and the list in `tests/test_aether_quant_api.py` or `scripts/wheel_smoke.py::check_library` disagree about which facade modules exist;
2. a public name in a shipped package is not exported by any facade and not listed in `tests/data/aether_quant_unexported.json`;
3. that file lists a name that is now exported or no longer exists (so the backlog can only shrink), or its legacy list grows past `LEGACY_CEILING`.

A public name is a top-level `def` or `class` without a leading underscore. Names are matched without their module, because the facades import through packages as well as through modules.
Lower `LEGACY_CEILING` whenever the legacy list shrinks; never raise it. A new name that stays out gets an entry under `unexported` with a one-line reason.

    python scripts/library_gate.py            # exit 1 with the violations
    python scripts/library_gate.py --report   # counts only
"""

from __future__ import annotations

import ast
import fnmatch
import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "tests" / "data" / "aether_quant_unexported.json"
LEGACY_CEILING = 288  # the backlog when the gate was added (V6.6.4); only ever lowered


def shipped_roots(root: Path = ROOT) -> tuple[list[str], list[str]]:
    """(packages, top-level modules) from pyproject.toml, as the wheel ships them."""
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    packages = re.search(r"^packages\s*=\s*\[(.*?)\]", text, re.M | re.S)
    modules = re.search(r"^py-modules\s*=\s*\[(.*?)\]", text, re.M | re.S)
    names = lambda match: re.findall(r'"([^"]+)"', match.group(1)) if match else []  # noqa: E731
    return [name for name in names(packages) if name != "aether_quant"], names(modules)


def _public_defs_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_")}


def public_defs(root: Path = ROOT) -> dict[str, set[str]]:
    """{dotted module: its public top-level names}, over every shipped package and top-level module."""
    packages, modules = shipped_roots(root)
    found: dict[str, set[str]] = {}
    for name in modules:
        path = root / f"{name}.py"
        if path.exists():
            found[name] = _public_defs_in(path)
    for package in packages:
        base = root / package
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).with_suffix("")
            dotted = ".".join(relative.parts[:-1] if relative.name == "__init__" else relative.parts)
            names = _public_defs_in(path)
            if names:
                found[dotted] = names
    return found


def facade_modules(root: Path = ROOT) -> set[str]:
    return {path.stem for path in (root / "aether_quant").glob("*.py") if path.stem != "__init__"}


def facade_exports(root: Path = ROOT) -> set[str]:
    """Every name a facade exports: its `__all__` strings and the original names it imports (an alias counts as the name it re-exports)."""
    exported: set[str] = set()
    for path in (root / "aether_quant").glob("*.py"):
        if path.stem == "__init__":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                exported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    exported.update(element.value for element in node.value.elts if isinstance(element, ast.Constant) and isinstance(element.value, str))
    return exported


def api_test_modules(root: Path = ROOT) -> list[str]:
    """The `MODULES` tuple of tests/test_aether_quant_api.py, read without importing it."""
    tree = ast.parse((root / "tests" / "test_aether_quant_api.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MODULES" for target in node.targets):
            return [element.value for element in node.value.elts if isinstance(element, ast.Constant)]
    return []


def wheel_check_modules(root: Path = ROOT) -> list[str]:
    """The keys of the `checks` dict in scripts/wheel_smoke.py::check_library: the modules the built wheel calls once each."""
    tree = ast.parse((root / "scripts" / "wheel_smoke.py").read_text(encoding="utf-8"))
    for function in ast.walk(tree):
        if isinstance(function, ast.FunctionDef) and function.name == "check_library":
            for node in ast.walk(function):
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "checks" for target in node.targets) and isinstance(node.value, ast.Dict):
                    return [key.value for key in node.value.keys if isinstance(key, ast.Constant)]
    return []


def load_allowlist(path: Path = ALLOWLIST) -> dict:
    if not path.exists():
        return {"modules": {}, "unexported": {}, "legacy_names": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _module_excluded(module: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(module, pattern) for pattern in patterns)


def unexported(root: Path = ROOT, allow: Mapping | None = None) -> list[str]:
    """Qualified `module:name` of every public name that no facade exports and no module-level exclusion covers."""
    allow = allow if allow is not None else load_allowlist(root / "tests" / "data" / "aether_quant_unexported.json")
    exported = facade_exports(root)
    out = []
    for module, names in public_defs(root).items():
        if _module_excluded(module, (allow.get("modules") or {}).keys()):
            continue
        out.extend(f"{module}:{name}" for name in sorted(names) if name not in exported)
    return sorted(out)


def check(root: Path = ROOT, allow: Mapping | None = None, *, ceiling: int | None = None, listed_modules: Iterable[str] | None = None, wheel_modules: Iterable[str] | None = None) -> list[str]:
    """The violations, readable. Empty means the library is up to date."""
    allow = allow if allow is not None else load_allowlist(root / "tests" / "data" / "aether_quant_unexported.json")
    ceiling = LEGACY_CEILING if ceiling is None else ceiling
    problems: list[str] = []
    modules = facade_modules(root)
    for label, other in (("tests/test_aether_quant_api.py MODULES", listed_modules), ("scripts/wheel_smoke.py check_library", wheel_modules)):
        if other is not None and set(other) != modules:
            problems.append(f"aether_quant/*.py and {label} disagree: only in files {sorted(modules - set(other))}, only in {label} {sorted(set(other) - modules)}")
    missing = unexported(root, allow)
    known = set((allow.get("unexported") or {})) | set(allow.get("legacy_names") or [])
    for name in missing:
        if name not in known:
            problems.append(f"{name} is public but not in aether_quant: export it from a facade, or add it to tests/data/aether_quant_unexported.json under \"unexported\" with a reason")
    current = set(missing)
    for name in sorted(known - current):
        problems.append(f"{name} is listed in tests/data/aether_quant_unexported.json but is now exported or gone: remove the entry")
    for name, reason in (allow.get("unexported") or {}).items():
        if not str(reason).strip():
            problems.append(f"{name} is listed under \"unexported\" without a reason")
    legacy = list(allow.get("legacy_names") or [])
    if len(legacy) > ceiling:
        problems.append(f"the legacy list holds {len(legacy)} names, above the ceiling {ceiling}: it can only shrink")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    allow = load_allowlist()
    if "--report" in args:
        packages, modules = shipped_roots()
        defs = public_defs()
        count = sum(len(names) for names in defs.values())
        print(json.dumps({
            "facade_modules": len(facade_modules()), "facade_names": len(facade_exports()), "public_defs": count, "unexported_now": len(unexported(ROOT, allow)),
            "legacy_listed": len(allow.get("legacy_names") or []), "deliberate_listed": len(allow.get("unexported") or {}), "module_exclusions": len(allow.get("modules") or {}),
            "packages": len(packages), "top_level_modules": len(modules), "ceiling": LEGACY_CEILING,
        }, indent=1))
        return 0
    problems = check(ROOT, allow, listed_modules=api_test_modules(), wheel_modules=wheel_check_modules())
    for line in problems:
        print(f"library gate: {line}", file=sys.stderr)
    if problems:
        print(f"library gate: {len(problems)} problem(s); aether_quant must be updated with this change", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
