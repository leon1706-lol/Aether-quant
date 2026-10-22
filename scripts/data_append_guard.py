"""Append-only guard for the data refresh (V6.4.0, Problems.md #215). stdlib only.

The shipped data is one consistent Yahoo vintage (`auto_adjust=True`); every trained model and every Lean run read it. A
refresh to a later date must therefore only ADD rows after the cutoff: any change to a row dated on or before it (a
revised dividend adjustment, a corrected print) would move the dataset, the models' inputs and the Lean paths that the
BT5 = BT4 check relies on. This module hashes the rows up to the cutoff before the refresh and verifies them after, and
holds the splice that puts the new rows on the old rows' price basis.

    python scripts/data_append_guard.py snapshot --out ml/evaluation/v640/data_before.json [--cutoff 2026-09-30]
    python scripts/data_append_guard.py verify --before ml/evaluation/v640/data_before.json --out ml/evaluation/v640/data_append_guard.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

# relative to data/: the files the models and Lean read as dated rows
PATTERNS = ("equity/usa/daily/*.zip", "crypto/coinbase/daily/*.zip", "forex/oanda/daily/*.zip", "reference/fred_series/*.csv")
_LEAN_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})[ ,]")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\b")
PRICE_FIELDS = ("open", "high", "low", "close")


def row_date(line: str) -> str | None:
    """YYYY-MM-DD of a Lean row ("20260930 00:00,...") or a FRED cache row ("2026-09-30,2.35"); None for anything else."""
    match = _LEAN_DATE.match(line) or _ISO_DATE.match(line)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else None


def file_lines(path: Path) -> list[str]:
    """The file's data lines (first member of a zip, or the text of a csv), no blank lines, CRs stripped."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            text = archive.read(archive.namelist()[0]).decode("utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    return [line.rstrip("\r") for line in text.split("\n") if line.strip()]


def rows_up_to(lines: list[str], cutoff: str) -> list[str]:
    return [line for line in lines if (row_date(line) or "9999-99-99") <= cutoff]


def digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def snapshot(data_dir: Path, cutoff: str, patterns=PATTERNS) -> dict[str, dict]:
    """{relative path: {"sha256": digest of the rows dated <= cutoff, "rows": their count, "last": newest date}}."""
    out = {}
    for pattern in patterns:
        for path in sorted(Path(data_dir).glob(pattern)):
            lines = file_lines(path)
            kept = rows_up_to(lines, cutoff)
            dates = [row_date(line) for line in lines if row_date(line)]
            out[path.relative_to(data_dir).as_posix()] = {"sha256": digest(kept), "rows": len(kept), "last": max(dates) if dates else None}
    return out


def verify(before: dict[str, dict], after: dict[str, dict]) -> list[dict]:
    """The files whose pre-cutoff rows changed or vanished: [{"path", "reason"}]. A file that is new after the refresh is
    not a violation."""
    problems = []
    for path, entry in before.items():
        now = after.get(path)
        if now is None:
            problems.append({"path": path, "reason": "missing_after_refresh"})
        elif now["sha256"] != entry["sha256"]:
            problems.append({"path": path, "reason": "rows_up_to_the_cutoff_changed", "rows_before": entry["rows"], "rows_after": now["rows"]})
    return problems


# ---------------------------------------------------------------- the splice: new rows on the old rows' basis


def splice_ratio(old_close: dict[str, float], new_close: dict[str, float]) -> tuple[float, str | None]:
    """old / new close at the LATEST date both series have: the factor that puts a fresher Yahoo vintage (adjusted for
    dividends and splits up to today) back on the basis of the rows already stored. (1.0, None) with no common date."""
    common = sorted(set(old_close) & set(new_close))
    for day in reversed(common):
        if new_close[day] > 0.0 and old_close[day] > 0.0:
            ratio = old_close[day] / new_close[day]
            return (1.0 if abs(ratio - 1.0) < 1e-9 else ratio), day
    return 1.0, None


def scale_new_rows(rows: list[dict], ratio: float, after: str, fields=PRICE_FIELDS) -> list[dict]:
    """The rows dated after `after` with their price fields multiplied by `ratio` (volume untouched); older rows dropped."""
    out = []
    for row in rows:
        if str(row["date"])[:10] > after:
            scaled = dict(row)
            for field in fields:
                if field in scaled:
                    scaled[field] = scaled[field] * ratio
            out.append(scaled)
    return out


def merge_csv_append_only(old_text: str, new_text: str, cutoff: str) -> str:
    """A dated csv (FRED cache) where the rows dated <= cutoff are exactly the stored ones (no revision, no late addition)
    and rows after it come from the fresh fetch, sorted by date, header preserved."""
    old_lines = [line.rstrip("\r") for line in old_text.split("\n")]
    header = [line for line in old_lines if line.strip() and row_date(line) is None]
    kept = {row_date(line): line for line in old_lines if row_date(line)}
    merged = {day: line for day, line in kept.items() if day <= cutoff}
    for line in (line.rstrip("\r") for line in new_text.split("\n")):
        day = row_date(line)
        if day and day > cutoff:
            merged[day] = line
        # a date <= cutoff the stored file lacks (a monthly rate published late) stays out: a dataset row of that day
        # never saw it, and adding it would move the feature values read as-of that day
    return "\n".join(header + [merged[day] for day in sorted(merged)]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--data-dir", default=str(ROOT_DIR / "data"))
    snap.add_argument("--cutoff", default="2026-09-30")
    snap.add_argument("--out", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--data-dir", default=str(ROOT_DIR / "data"))
    check.add_argument("--before", required=True)
    check.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.command == "snapshot":
        payload = {"cutoff": args.cutoff, "files": snapshot(Path(args.data_dir), args.cutoff)}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"snapshot of {len(payload['files'])} files up to {args.cutoff} -> {args.out}")
        return 0
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    cutoff = before["cutoff"]
    problems = verify(before["files"], snapshot(Path(args.data_dir), cutoff))
    report = {"cutoff": cutoff, "files_checked": len(before["files"]), "violations": problems}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{report['files_checked']} files checked, {len(problems)} with changed rows up to {cutoff}")
    for problem in problems[:20]:
        print("  ", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
