"""Warn when README's test-count badge no longer matches the collected tests.

The badge (`<!-- AQ:TEST_COUNT_START -->N<!-- AQ:TEST_COUNT_END -->`) is
rewritten only by an unfiltered local `aq test`, so it silently lags whenever
a test is added in a commit that skipped it: V5.4.10 shipped saying 2935
while its own commit message said 2929. CI cannot refresh it (a bot commit on
every push is worse than a stale number), but it can surface the drift:

    python scripts/check_test_count_drift.py            # warn-only, exit 0
    python scripts/check_test_count_drift.py --strict   # exit 1 on drift

Output uses GitHub's `::warning::` annotation so the job summary shows it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_README_RE = re.compile(r"<!--\s*AQ:TEST_COUNT_START\s*-->\s*(\d+)\s*<!--\s*AQ:TEST_COUNT_END\s*-->")
# "2935 tests collected in 3.1s"  |  "2935/2936 tests collected (1 deselected) in 3.1s"
_COLLECTED_RE = re.compile(r"(\d+)(?:/\d+)? tests? collected")


def readme_count(readme_text: str) -> int | None:
    match = _README_RE.search(readme_text)
    return int(match.group(1)) if match else None


def collected_count(pytest_output: str) -> int | None:
    matches = _COLLECTED_RE.findall(pytest_output)
    return int(matches[-1]) if matches else None


def run_collect_only() -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "not lean_backtest", "tests/"],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    return completed.stdout + completed.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit 1 when the badge and the collected count differ")
    args = parser.parse_args(argv)

    badge = readme_count((ROOT / "README.md").read_text(encoding="utf-8"))
    collected = collected_count(run_collect_only())
    if badge is None or collected is None:
        print(f"::warning::could not compare test counts (README badge={badge}, collected={collected})")
        return 1 if args.strict else 0
    if badge == collected:
        print(f"test count OK: README badge and pytest agree on {collected}")
        return 0
    print(
        f"::warning::README test-count badge says {badge} but pytest collects {collected} "
        f"({collected - badge:+d}); run an unfiltered `aq test` locally to refresh it"
    )
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
