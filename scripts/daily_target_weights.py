"""The next row of a target-weights run (V6.5.0), for paper or live: what the research file holds, computed from today's data.

A Lean backtest reads a whole weight file. Paper or live needs the same row written before each open, from the same functions,
so this appends one row to the file `phase_v2.target_weights.weights_path` names, and rewrites its `.sha256` sidecar, which a run
with `live_reload` checks at each reload. A date is written once, and the row must be finite. A date with no data, or a class
whose last bar is too old, exits non-zero: "not a rebalance day" must never hide a broken data feed.

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
    from portfolio.target_weights import write_weights_sidecar

    write_weights_sidecar(path)
    return True


# The oldest a class's last bar may be, in calendar days before the decision: a weekend plus a holiday for equities' sessions, and
# crypto trades daily and its bar is read a day late.
MAX_STALE_DAYS = {"equity": 5, "bond": 5, "forex": 5, "crypto": 2}


def data_problems(context, date: str) -> list[str]:
    """Why `date` can't be decided: no such session, or a class holding this candidate's names has stopped updating."""
    import pandas as pd

    known = context.panel.known
    if date not in known.index:
        return [f"{date} is not a session in the data (last is {known.index[-1]})"]
    problems = []
    closes = pd.DataFrame(context.market.closes, index=context.market.dates, columns=context.market.tickers)
    closes = closes[closes.index <= date]
    today = pd.Timestamp(date)
    for asset_class, limit in MAX_STALE_DAYS.items():
        members = [ticker for ticker, name in context.market.asset_class.items() if name == asset_class and ticker in closes.columns]
        rows = closes[members].dropna(how="all") if members else None
        if rows is None or rows.empty:
            continue
        age = (today - pd.Timestamp(rows.index[-1])).days
        if age > limit:
            problems.append(f"{asset_class} data is {age} days old on {date} (limit {limit})")
    return problems


def blended_rows(ledger: Path) -> dict[str, dict[str, float]]:
    """{session: blended row} from the generations' ledger (`scripts/cycle_daily.py`). Stops at a broken chain: a row that can't be trusted must not reach an order."""
    from evaluation.forward_ledger import read_ledger
    from evaluation.generation_ledger import ALLOCATION_ID, judge_generations

    rows = read_ledger(ledger)
    if not judge_generations(rows)["chain_valid"]:
        raise ValueError(f"{ledger.name}: the chain is broken")
    return {
        row["payload"]["session"]: dict(row["payload"]["blended"])
        for row in rows
        if row["payload"].get("candidate") == ALLOCATION_ID and row["payload"].get("blended") is not None
    }


def write_blended(ledger: Path, out: Path) -> list[str]:
    """Appends each blended row the file doesn't hold yet, in order, and returns their dates. A paper run with `live_reload` trades this file."""
    written = []
    for date, row in sorted(blended_rows(ledger).items()):
        if append_row(out, date, row):
            written.append(date)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", default=None, help="one frozen rule's definition")
    parser.add_argument("--generations", default=None, help="instead of --candidate: the generations' ledger, forward/generations.jsonl")
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", default=None, help="the session to decide for (default: the last session in the data)")
    args = parser.parse_args()
    if bool(args.candidate) == bool(args.generations):
        parser.error("name exactly one of --candidate and --generations")
    if args.generations:
        for date in write_blended(Path(args.generations), Path(args.out)):
            print(f"{date}: wrote the blended row")
        return 0

    from v650_lean import candidate_rows
    from v650_research import load_context

    definition = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    context = load_context()
    date = args.date or str(context.panel.known.index[-1])
    problems = data_problems(context, date)
    if problems:
        for problem in problems:
            print(f"refusing to decide: {problem}", file=sys.stderr)
        return 1
    row = row_for_date(definition, context, date, candidate_rows=candidate_rows, history_start=str(definition.get("history_start", "2014-12-01")))
    if row is None:
        print(f"{date}: not a rebalance day, nothing to write")
        return 0
    written = append_row(Path(args.out), date, row)
    print(f"{date}: {'wrote' if written else 'already held'} {len(row)} weights")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
