"""The next row of a target-weights run (V6.5.0), for paper or live: what the research file holds, computed from today's data.

A Lean backtest reads a whole weight file. Paper or live needs the same row written before each open, from the same functions,
so this appends one row to the file `phase_v2.target_weights.weights_path` names. Its sha256 changes with each row, so a live run
leaves `weights_sha256` empty and relies on this script's own checks: a date is written once, and the row must be finite.

    python scripts/daily_target_weights.py --candidate ml/evaluation/v650/installed_candidate.json --out ml/evaluation/v650/weights/live.csv [--date 2026-11-04]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def row_for_date(definition: dict, context, date: str, *, candidate_rows, history_start: str = "2014-12-01") -> dict[str, float] | None:
    """The candidate's row dated `date`, or None when `date` is not one of its rebalance days. Computed on data cut at `date`,
    so it cannot depend on anything later, and rebalance days counted from the same `history_start` as the research file."""
    cut = context.panel.truncated(date)
    original = context.panel
    context.panel = cut
    try:
        rows = candidate_rows(definition, context, start=history_start, end=date, phase_index=int(definition.get("phase_index", 0)))
    finally:
        context.panel = original
    return rows.get(date)


def append_row(path: Path, date: str, row: dict[str, float]) -> bool:
    """Appends the row; False when the file already holds this date. Raises ValueError on a non-finite weight, so a damaged
    row never reaches an order."""
    for ticker, weight in row.items():
        if not math.isfinite(float(weight)):
            raise ValueError(f"non-finite weight for {ticker} on {date}")
    exists = path.exists()
    if exists:
        with path.open(newline="", encoding="utf-8") as handle:
            if any(existing["date"][:10] == date for existing in csv.DictReader(handle)):
                return False
    from portfolio.target_weights import FLAT_TICKER

    with path.open("a", newline="\n", encoding="utf-8") as handle:
        if not exists:
            handle.write("date,ticker,weight\n")
        if not row:
            handle.write(f"{date},{FLAT_TICKER},0\n")
        for ticker in sorted(row):
            handle.write(f"{date},{ticker},{float(row[ticker]):.8f}\n")
    return True


def main() -> int:
    from v650_lean import candidate_rows
    from v650_research import load_context

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", default=None, help="the session to decide for (default: the last session in the data)")
    args = parser.parse_args()
    definition = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    context = load_context()
    date = args.date or str(context.panel.known.index[-1])
    row = row_for_date(definition, context, date, candidate_rows=candidate_rows, history_start=str(definition.get("history_start", "2014-12-01")))
    if row is None:
        print(f"{date}: not a rebalance day, nothing to write")
        return 0
    written = append_row(Path(args.out), date, row)
    print(f"{date}: {'wrote' if written else 'already held'} {len(row)} weights")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
