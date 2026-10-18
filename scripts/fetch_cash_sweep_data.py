"""Fetch the cash-sweep ETF's daily bars (V6.2.0; `phase_v2.cash_sweep.ticker`, BIL by default) into its Lean zip.

The sweep ticker is not a universe asset (never scored, ranked or capped), so `scripts/build_holdout_data.py` does not
fetch it; this uses the same Yahoo pipeline (split/dividend-adjusted, so distributions accrue in the price, x10000 Lean
equity format, OHLC sanitised) and the same window end as every other zip.

    python scripts/fetch_cash_sweep_data.py [--start 2013-01-01] [--end 2026-09-30] [--apply]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


def main() -> int:
    from data_pipeline.yfinance_backfill import fetch_yahoo_ohlcv, sanitize_ohlc, scale_for_lean, write_lean_zip
    from portfolio.cash_sweep import resolve_cash_sweep_config

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2013-01-01")
    parser.add_argument("--end", default="2026-09-30", help="last date kept (inclusive)")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    sweep = resolve_cash_sweep_config(config.get("phase_v2", {}).get("cash_sweep"))
    ticker = sweep["ticker"]
    last = date.fromisoformat(args.end)
    # yfinance's end is exclusive: ask for the next day and trim, so the zip ends where the universe zips end
    rows = fetch_yahoo_ohlcv(ticker, args.start, date.fromordinal(last.toordinal() + 1).isoformat())
    rows = [row for row in rows if row["date"] <= last]
    rows, widened = sanitize_ohlc(rows)
    if not rows:
        print(f"{ticker}: Yahoo returned nothing")
        return 1
    closes = [float(row["close"]) for row in rows]
    worst = max(abs(after / before - 1.0) for before, after in zip(closes, closes[1:]))
    print(f"{ticker}: {len(rows)} rows {rows[0]['date']}..{rows[-1]['date']}, {widened} OHLC rows widened, "
          f"largest daily move {worst:.4%}")
    target = ROOT_DIR / sweep["data_path"]
    if not args.apply:
        print(f"dry run (pass --apply to write {target})")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    write_lean_zip(target, ticker, scale_for_lean(rows, "equity"), merge_with_existing=False)
    print(f"written {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
