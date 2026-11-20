"""Every public function the trading path and the research path compute with, and how each is proved (V6.6.10). Imports nothing; reads the code with ast.

    python scripts/formal_inventory.py            # fails on an unclassified function, a spec that does not exist, or a backlog above its ceiling
    python scripts/formal_inventory.py --report   # the counts per status and per package

`formal/inventory.json` classifies each function (`module:name`), or a whole module (`module`), as one of:

- `spec:<Target>`: modelled in `formal/AetherFormal/<Target>.lean`, with theorems and a differential test;
- `excluded:<reason>`: no arithmetic to prove: `io`, `orchestration`, `cli`, `plotting`, `torch-only`, `non-numeric`;
- `backlog`: a pure numeric function without a spec yet.

The backlog may only shrink: `BACKLOG_CEILING` is the count when it was last lowered, and a new pure numeric function has to come
with its spec or be counted against it. A function entry wins over its module's.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "formal" / "inventory.json"
SCOPE = ("risk", "portfolio", "execution", "features", "evaluation", "retraining", "inference", "moe", "regime", "topology", "json_safety.py", "risk_controls.py")
REASONS = frozenset({"io", "orchestration", "cli", "plotting", "torch-only", "non-numeric"})
BACKLOG_CEILING = 881  # V6.6.10: the first inventory had 889 (1,252 functions, 48 with a spec); the phase's specs took it to 881


def scope_files(root: Path = ROOT) -> list[str]:
    # tracked and new (not yet added) files: a module written in this change is classified before its first commit
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", *SCOPE], cwd=root, capture_output=True, text=True, check=True).stdout.split()
    return sorted(path for path in listed if path.endswith(".py") and not path.endswith("__init__.py"))


def module_name(path: str) -> str:
    return path[:-3].replace("/", ".")


def public_defs(root: Path = ROOT, files: list[str] | None = None) -> dict[str, list[str]]:
    """{module: [public top-level function and class names]} for every file in scope."""
    out = {}
    for path in files if files is not None else scope_files(root):
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        names = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_")]
        if names:
            out[module_name(path)] = names
    return out


def load_inventory(path: Path = INVENTORY) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"modules": {}, "functions": {}}


def status_of(module: str, name: str, inventory: dict) -> str | None:
    return inventory.get("functions", {}).get(f"{module}:{name}") or inventory.get("modules", {}).get(module)


def problems(defs: dict[str, list[str]], inventory: dict, *, specs: set[str], ceiling: int = BACKLOG_CEILING) -> list[str]:
    """Everything wrong with the inventory: an unclassified function, an unknown status or reason, a spec file that does not exist,
    an entry for a function that is gone, and a backlog above its ceiling."""
    found: list[str] = []
    backlog = 0
    known = {f"{module}:{name}" for module, names in defs.items() for name in names}
    for module, names in defs.items():
        for name in names:
            status = status_of(module, name, inventory)
            if status is None:
                found.append(f"{module}:{name} is not classified in formal/inventory.json")
            elif status == "backlog":
                backlog += 1
            elif status.startswith("spec:"):
                if status[5:] not in specs:
                    found.append(f"{module}:{name}: formal/AetherFormal/{status[5:]}.lean does not exist")
            elif not (status.startswith("excluded:") and status[9:] in REASONS):
                found.append(f"{module}:{name}: unknown status {status!r}")
    found.extend(f"{entry} is in formal/inventory.json but no longer exists" for entry in sorted(set(inventory.get("functions", {})) - known))
    found.extend(f"module {entry} is in formal/inventory.json but has no public function in scope" for entry in sorted(set(inventory.get("modules", {})) - set(defs)))
    if backlog > ceiling:
        found.append(f"the backlog is {backlog}, above its ceiling {ceiling}: write the spec, or classify the function")
    return found


def report(defs: dict[str, list[str]], inventory: dict) -> dict:
    by_status: Counter = Counter()
    by_package: dict[str, Counter] = {}
    for module, names in defs.items():
        for name in names:
            status = status_of(module, name, inventory) or "unclassified"
            kind = status.split(":")[0]
            by_status[kind] += 1
            by_package.setdefault(module.split(".")[0], Counter())[kind] += 1
    return {"total": sum(by_status.values()), "by_status": dict(by_status), "by_package": {name: dict(counts) for name, counts in sorted(by_package.items())}}


def spec_targets(root: Path = ROOT) -> set[str]:
    return {path.stem for path in (root / "formal" / "AetherFormal").glob("*.lean")} - {"GenCases", "Real"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    defs, inventory = public_defs(), load_inventory()
    if args.report:
        print(json.dumps(report(defs, inventory), indent=1))
        return 0
    found = problems(defs, inventory, specs=spec_targets())
    for line in found:
        print(f"formal inventory: {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
