"""The README's test badge, from CI's JUnit report (V6.6.6, #358).

    python scripts/test_badge.py junit.xml                                  # print the summary line
    python scripts/test_badge.py junit.xml --badge site/badges/tests.json

pages.yml publishes the badge beside the coverage badge after each green CI on main, so the count can't lag the suite. The badge
file is a shields.io endpoint document, the same shape as scripts/coverage_badge.py writes.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET  # nosec B405: parses the JUnit file this repository's own CI run wrote
from pathlib import Path


def counts(path: Path) -> dict[str, int]:
    """Totals over every <testsuite> in a pytest JUnit file: tests, failed (failures + errors), skipped and passed."""
    root = ET.parse(path).getroot()  # nosec B314: see the import
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites:
        raise ValueError(f"no <testsuite> in {path}")
    tests = sum(int(suite.get("tests", 0)) for suite in suites)
    failed = sum(int(suite.get("failures", 0)) + int(suite.get("errors", 0)) for suite in suites)
    skipped = sum(int(suite.get("skipped", 0)) for suite in suites)
    return {"tests": tests, "failed": failed, "skipped": skipped, "passed": tests - failed - skipped}


def badge(figures: dict[str, int], label: str = "tests") -> dict[str, object]:
    ran = figures["passed"] + figures["failed"]
    color = "brightgreen" if figures["failed"] == 0 and ran > 0 else "red"
    return {"schemaVersion": 1, "label": label, "message": f"{figures['passed']}/{ran} passing", "color": color}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("junit_xml")
    parser.add_argument("--badge", default=None, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        figures = counts(Path(args.junit_xml))
    except (OSError, ET.ParseError, ValueError) as error:
        print(f"no test figures: {error}", file=sys.stderr)
        return 1
    print(f"## tests: {figures['passed']} passed, {figures['failed']} failed, {figures['skipped']} skipped")
    if args.badge:
        target = Path(args.badge)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(badge(figures)) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
