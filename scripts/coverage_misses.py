"""The coverage worklist (V6.6.7, #367): which lines a run left uncovered, grouped by function, with their context.

Reads the `coverage-report/coverage.json` that `aq test --coverage` (or `coverage json`) writes. The gate is 100% of every tracked module
(AGENTS.md "Coverage: 100% after every commit"), so a run's misses are the next tests to write.

    python scripts/coverage_misses.py                                  # every file with a miss, by count
    python scripts/coverage_misses.py --include "risk/*" --by-function # per function
    python scripts/coverage_misses.py --include risk/kelly.py --context 2
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def misses(data: dict, include: Sequence[str] | None = None) -> dict[str, list[int]]:
    """{posix path: missing line numbers} for files with at least one miss, optionally only those matching `include`."""
    out: dict[str, list[int]] = {}
    for name, report in (data.get("files") or {}).items():
        path = name.replace("\\", "/")
        if include and not any(fnmatch.fnmatch(path, pattern) for pattern in include):
            continue
        lines = sorted(report.get("missing_lines") or [])
        if lines:
            out[path] = lines
    return out


def by_function(source: str, lines: Sequence[int]) -> dict[str, list[int]]:
    """Missing lines keyed by their innermost enclosing `def`/`class` (dotted), or `<module>`."""
    spans: list[tuple[int, int, str]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                spans.append((child.lineno, child.end_lineno or child.lineno, name))
                walk(child, name + ".")
            else:
                walk(child, prefix)

    walk(ast.parse(source), "")
    out: dict[str, list[int]] = {}
    for line in lines:
        inside = [span for span in spans if span[0] <= line <= span[1]]
        owner = min(inside, key=lambda span: span[1] - span[0])[2] if inside else "<module>"
        out.setdefault(owner, []).append(line)
    return out


def context(source: str, lines: Sequence[int], radius: int = 2) -> str:
    """The missing lines with `radius` lines around each, `>>` marking a miss, gaps shown as `...`."""
    text = source.splitlines()
    wanted = sorted({n for line in lines for n in range(max(1, line - radius), min(len(text), line + radius) + 1)})
    out: list[str] = []
    previous = None
    for number in wanted:
        if previous is not None and number != previous + 1:
            out.append("    ...")
        out.append(f"{'>>' if number in lines else '  '} {number:5d}  {text[number - 1]}")
        previous = number
    return "\n".join(out)


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", default=str(root / "coverage-report" / "coverage.json"), help="coverage.json to read (default: the repo's)")
    parser.add_argument("--include", action="append", help="glob of files to show (repeatable)")
    parser.add_argument("--by-function", action="store_true", help="group each file's misses by function")
    parser.add_argument("--context", type=int, default=None, metavar="N", help="print each miss with N lines around it")
    args = parser.parse_args(argv)
    path = Path(args.json)
    if not path.exists():
        print(f"{path} not found: run `aq test --coverage` first", file=sys.stderr)
        return 2
    found = misses(load(path), args.include)
    for name, lines in sorted(found.items(), key=lambda item: (-len(item[1]), item[0])):
        print(f"{name}: {len(lines)} missing")
        source_path = root / name
        if not source_path.exists() or not (args.by_function or args.context is not None):
            continue
        source = source_path.read_text(encoding="utf-8")
        if args.by_function:
            for owner, owned in by_function(source, lines).items():
                print(f"    {owner}: {owned}")
        if args.context is not None:
            print(context(source, lines, args.context))
    print(f"{sum(len(lines) for lines in found.values())} missing line(s) in {len(found)} file(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
