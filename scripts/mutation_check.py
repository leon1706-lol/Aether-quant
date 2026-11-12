"""A small mutation check for the safety, admission and ledger modules (V6.6.4).

A test suite that passes proves little if it would also pass with the code broken. This changes one thing at a time in a module (a comparison flipped, `and` swapped for `or`, a `not` removed,
a constant moved by one, `+` swapped for `-`), runs that module's tests, and counts a change the tests did not notice as a survivor. A survivor in a safety or admission path needs a test that
kills it, or a written reason it changes nothing (an equivalent mutant). It samples a fixed number of sites per file with a fixed seed, so a run is repeatable.

It edits the real file in place and restores it in a `finally` (and checks the restore), so run it on a Codespace or a throwaway checkout, never on a tree with uncommitted work in those files.

    python scripts/mutation_check.py --out ml/evaluation/v664/mutation.json [--max-per-file 40] [--only evaluation/generation_registry.py]
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS: dict[str, tuple[str, ...]] = {
    "evaluation/generation_registry.py": ("tests/test_generation_registry.py", "tests/test_v664_mutation_ledgers.py", "tests/test_formal_differential_admission.py"),
    "evaluation/forward_ledger.py": ("tests/test_forward_ledger.py", "tests/test_v664_mutation_ledgers.py", "tests/test_v664_late_session.py", "tests/test_formal_differential_session_resolve.py"),
    "evaluation/research_cells.py": ("tests/test_research_cells.py", "tests/test_v664_mutation_ledgers.py", "tests/test_formal_differential_holdout_once.py"),
    "portfolio/generation_blend.py": ("tests/test_generation_blend.py", "tests/test_v664_mutation_ledgers.py", "tests/test_formal_differential_generation_blend.py", "tests/test_formal_differential_generation_glide.py"),
    "execution/order_gate.py": ("tests/test_order_gate.py", "tests/test_v664_mutation_safety.py", "tests/test_formal_differential_order_gate.py"),
    "risk_controls.py": ("tests/test_risk_controls.py", "tests/test_v664_mutation_safety.py", "tests/test_v664_mutation_ledgers.py", "tests/test_formal_differential_risk_controls.py"),
    "risk/kill_switch.py": ("tests/test_kill_switch.py", "tests/test_v664_mutation_safety.py", "tests/test_v664_mutation_ledgers.py", "tests/test_formal_differential_kill_switch.py"),
    # V6.6.5: accounts that only tighten, who may lock, secrets that never show, the live gate, the field test's gate
    "execution/accounts.py": ("tests/test_accounts.py", "tests/test_accounts_parity.py", "tests/test_formal_differential_account_overrides.py"),
    "monitoring/auth.py": ("tests/test_auth.py", "tests/test_formal_differential_authorize.py"),
    "execution/secrets.py": ("tests/test_secrets.py", "tests/test_secrets_property.py"),
    "execution/live_readiness.py": ("tests/test_live_readiness.py",),
    "execution/field_test.py": ("tests/test_field_test.py",),
}
COMPARE = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
ARITHMETIC = {ast.Add: ast.Sub, ast.Sub: ast.Add}
BOOLEAN = {ast.And: ast.Or, ast.Or: ast.And}


@dataclass(frozen=True)
class Site:
    index: int  # position among the tree's nodes in ast.walk order
    line: int
    kind: str


def sites(source: str) -> list[Site]:
    """Every place the operators can change something, in a stable order. Docstrings and annotations are left alone."""
    tree = ast.parse(source)
    found: list[Site] = []
    for index, node in enumerate(ast.walk(tree)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Compare) and any(type(op) in COMPARE for op in node.ops):
            found.append(Site(index, line, "compare"))
        elif isinstance(node, ast.BoolOp):
            found.append(Site(index, line, "boolop"))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            found.append(Site(index, line, "not"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            found.append(Site(index, line, "bool"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool) and node.value not in (0, 1):
            found.append(Site(index, line, "int"))
        elif isinstance(node, ast.BinOp) and type(node.op) in ARITHMETIC:
            found.append(Site(index, line, "arithmetic"))
    return found


def mutate(source: str, site: Site) -> str:
    """The source with one change at `site`."""
    tree = ast.parse(source)
    target = list(ast.walk(tree))[site.index]
    if isinstance(target, ast.Compare):
        target.ops = [COMPARE.get(type(op), type(op))() if position == 0 else op for position, op in enumerate(target.ops)]
    elif isinstance(target, ast.BoolOp):
        target.op = BOOLEAN[type(target.op)]()
    elif isinstance(target, ast.UnaryOp):
        replacement = target.operand
        for parent in ast.walk(tree):
            for name, value in ast.iter_fields(parent):
                if value is target:
                    setattr(parent, name, replacement)
                elif isinstance(value, list):
                    setattr(parent, name, [replacement if item is target else item for item in value])
    elif isinstance(target, ast.Constant):
        target.value = (not target.value) if isinstance(target.value, bool) else target.value + 1
    elif isinstance(target, ast.BinOp):
        target.op = ARITHMETIC[type(target.op)]()
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def sample(found: list[Site], limit: int, seed: int) -> list[Site]:
    """A fixed sample, in source order, so two runs test the same changes."""
    if len(found) <= limit:
        return list(found)
    rng = random.Random(seed)
    return sorted(rng.sample(found, limit), key=lambda site: site.index)


def run_tests(tests: tuple[str, ...], timeout: float) -> bool:
    """True when the tests pass (the change went unnoticed). A timeout or a crash counts as noticed."""
    command = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "--no-header", *[t for t in tests if (ROOT / t).exists()]]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def check_file(relative: str, tests: tuple[str, ...], *, limit: int, seed: int, timeout: float, emit=print) -> dict:
    path = ROOT / relative
    original = path.read_text(encoding="utf-8")
    if not run_tests(tests, timeout * 3):
        return {"file": relative, "error": "the tests do not pass unmutated: nothing to measure"}
    chosen = sample(sites(original), limit, seed)
    survivors, killed = [], 0
    try:
        for site in chosen:
            path.write_text(mutate(original, site), encoding="utf-8", newline="\n")
            if run_tests(tests, timeout):
                survivors.append({"line": site.line, "kind": site.kind})
                emit(f"{relative}:{site.line} {site.kind} survived")
            else:
                killed += 1
    finally:
        path.write_text(original, encoding="utf-8", newline="\n")
    if path.read_text(encoding="utf-8") != original:
        raise SystemExit(f"{relative} was not restored")
    total = len(chosen)
    return {
        "file": relative, "sites": len(sites(original)), "tried": total, "killed": killed, "survived": len(survivors), "kill_rate": (killed / total) if total else None, "survivors": survivors,
        "tests": [t for t in tests if (ROOT / t).exists()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-per-file", type=int, default=40)
    parser.add_argument("--seed", type=int, default=664)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args(argv)
    started = time.time()
    report = {"seed": args.seed, "max_per_file": args.max_per_file, "files": []}
    for relative, tests in TARGETS.items():
        if args.only and relative not in args.only:
            continue
        result = check_file(relative, tests, limit=args.max_per_file, seed=args.seed, timeout=args.timeout)
        report["files"].append(result)
        print(json.dumps({key: result.get(key) for key in ("file", "tried", "killed", "survived", "kill_rate", "error")}), flush=True)
    report["seconds"] = round(time.time() - started)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

