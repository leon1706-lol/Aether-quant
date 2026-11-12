"""Coverage for the README badge and the CI summary (V6.6.5, #353), from coverage.py's `coverage.json`.

    python scripts/coverage_badge.py coverage.json                          # print the Markdown summary
    python scripts/coverage_badge.py coverage.json --badge site/badges/coverage.json

The badge file is a shields.io endpoint document (`img.shields.io/endpoint?url=...`), published by pages.yml next to the
HTML coverage report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def color_for(percent: float) -> str:
    if percent >= 90:
        return "brightgreen"
    if percent >= 80:
        return "green"
    if percent >= 70:
        return "yellow"
    return "red"


def badge(percent: float, label: str = "coverage") -> dict[str, object]:
    return {"schemaVersion": 1, "label": label, "message": f"{percent:.0f}%", "color": color_for(percent)}


def totals(path: Path) -> dict[str, float]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))["totals"]
    return {"percent": float(data["percent_covered"]), "covered": float(data["covered_lines"]), "statements": float(data["num_statements"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("coverage_json")
    parser.add_argument("--badge", default=None, metavar="FILE")
    parser.add_argument("--label", default="coverage")
    args = parser.parse_args(argv)
    try:
        figures = totals(Path(args.coverage_json))
    except (OSError, KeyError, ValueError) as error:
        print(f"no coverage figures: {error}", file=sys.stderr)
        return 1
    print(f"## {args.label}: {figures['percent']:.1f}% ({figures['covered']:.0f} of {figures['statements']:.0f} lines)")
    if args.badge:
        target = Path(args.badge)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(badge(figures["percent"], args.label)) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
