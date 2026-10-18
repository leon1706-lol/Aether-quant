"""Bring Lean's risk-free file up to date from FRED DPCREDIT (V6.2.0).

Lean's Sharpe subtracts the mean of `data/alternative/interest-rate/usa/interest-rate.csv` (the Fed's primary credit
rate, percent, one row per change) over the equity curve and fills its last row forward. The file shipped with the Lean
sample data ended at 2023-07-27 (5.5%), so every run since was charged 5.5% through 2026 although the rate was cut from
September 2024 on. This appends FRED's change points after the file's last row, after checking that the history both
sources share agrees (a disagreement stops the script; nothing is overwritten).

    python scripts/refresh_lean_interest_rate.py [--end 2026-09-30] [--apply]

Dry run by default (prints the new change points). `--apply` writes the file atomically.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

RATE_FILE = ROOT_DIR / "data" / "alternative" / "interest-rate" / "usa" / "interest-rate.csv"
SERIES_ID = "DPCREDIT"
TOLERANCE = 1e-9
# The shipped file dates pre-2009 changes a day after FRED's effective date (its source's convention); from 2009 on both
# agree to the day, which is what the shared-history check compares.
CHECK_FROM = date(2009, 1, 1)


def change_points(observations: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Daily observations -> the days the value changed (the first observation included)."""
    points: list[tuple[date, float]] = []
    for day, value in sorted(observations):
        if not points or abs(points[-1][1] - value) > TOLERANCE:
            points.append((day, value))
    return points


def merge_rate_changes(
    existing: list[tuple[date, float]], fred: list[tuple[date, float]], *, check_from: date = CHECK_FROM
) -> list[tuple[date, float]]:
    """New change points to append after `existing`'s last row. Raises ValueError when FRED's daily value disagrees with
    the file's filled-forward value on any shared day from `check_from` on: the file would then not be the series this
    script assumes."""
    if not existing:
        raise ValueError("the existing rate file is empty")
    existing = sorted(existing)
    last_day = existing[-1][0]
    keys = [day for day, _rate in existing]
    for day, value in fred:
        if day > last_day or day < max(keys[0], check_from):
            continue
        in_force = existing[max(0, _bisect_right(keys, day) - 1)][1]
        if abs(in_force - value) > TOLERANCE:
            raise ValueError(f"{day}: the file holds {in_force} but FRED {SERIES_ID} says {value}")
    in_force = existing[-1][1]
    appended = []
    for day, value in change_points([(day, value) for day, value in fred if day > last_day]):
        if abs(value - in_force) > TOLERANCE:
            appended.append((day, value))
            in_force = value
    return appended


def _bisect_right(keys: list[date], day: date) -> int:
    import bisect

    return bisect.bisect_right(keys, day)


def read_rate_file(path: Path) -> tuple[str, list[tuple[date, float]], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0] if lines and not lines[0][:1].isdigit() else ""
    rows, raw = [], []
    for line in lines[1 if header else 0:]:
        if not line.strip():
            continue
        day, value = line.split(",")[:2]
        rows.append((date.fromisoformat(day.strip()), float(value)))
        raw.append(line.rstrip())
    return header, rows, raw


def main() -> int:
    from data_pipeline.fred_backfill import fetch_fred_series
    from json_safety import atomic_write_text

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--file", default=str(RATE_FILE))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    header, existing, raw = read_rate_file(path)
    fred = [(row["date"], float(row["value"])) for row in fetch_fred_series(SERIES_ID, "2003-01-01", args.end)]
    if not fred:
        print(f"FRED {SERIES_ID} returned nothing; file unchanged")
        return 1
    appended = merge_rate_changes(existing, fred)
    print(f"{path}: last row {existing[-1][0]} {existing[-1][1]}; FRED to {fred[-1][0]} ({len(fred)} observations)")
    for day, value in appended:
        print(f"  + {day.isoformat()},{value:.2f}")
    if not appended:
        print("  nothing to append")
        return 0
    if not args.apply:
        print("dry run (pass --apply to write)")
        return 0
    lines = ([header] if header else []) + raw + [f"{day.isoformat()},{value:.2f}" for day, value in appended]
    atomic_write_text(path, "\n".join(lines) + "\n")
    print(f"written {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
