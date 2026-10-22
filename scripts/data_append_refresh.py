"""Append the latest daily bars to the shipped data without touching a stored row (V6.4.0, Problems.md #215).

V5.8.0 rewrote `data/` in full from ONE Yahoo vintage (`auto_adjust=True`), because adjusted bars appended to rows adjusted
as of an earlier date put a step at every later dividend or split. This refresh keeps that vintage: for each asset it
fetches a little before the last stored date, computes the factor that puts today's vintage back on the stored rows' basis
(old close / new close at the latest common date; 1.0 unless a dividend or split happened since), scales ONLY the new rows
by it, and merges them behind the existing rows (the writers' "existing rows win" merge). FRED caches are appended the same
way. `scripts/data_append_guard.py` proves afterwards that no row up to the cutoff changed.

    python scripts/data_append_refresh.py [--end 2026-10-17] [--cutoff 2026-09-30] [--tickers AAPL ...] [--apply]

Dry run by default (fetches and reports the factor and the new rows per asset, writes nothing).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_holdout_data import CLASS_KEY_BY_SECURITY_TYPE, yahoo_symbol  # noqa: E402
from data_append_guard import merge_csv_append_only, scale_new_rows, splice_ratio  # noqa: E402

from data_pipeline.fetch import ASSET_CLASS_CONFIG  # noqa: E402
from data_pipeline.fred_backfill import fetch_fred_series, reference_series, rows_to_cache_csv  # noqa: E402
from data_pipeline.yfinance_backfill import (  # noqa: E402
    _read_existing_lean_forex_rows,
    _read_existing_lean_rows,
    apply_price_overrides,
    fetch_yahoo_ohlcv,
    sanitize_ohlc,
    scale_for_lean,
    write_lean_crypto_quote_zip,
    write_lean_zip,
)

OVERLAP_DAYS = 14
EXTRA_EQUITY = {"BIL": "data/equity/usa/daily/bil.zip", "SPY": "data/equity/usa/daily/spy.zip"}  # outside the universe
SUSPICIOUS_RATIO = 0.05  # a splice factor further from 1 than this is a split or a bad print: reported, not hidden


def stored_closes(path: Path, security_type: str) -> tuple[dict[str, float], date | None]:
    """({date: close in real units}, newest stored date) of one Lean zip."""
    if security_type == "forex":
        rows = _read_existing_lean_forex_rows(path)
        closes = {row["date"].isoformat(): float(row["bid_close"]) for row in rows}
    else:
        rows = _read_existing_lean_rows(path)
        scale = 10000.0 if security_type == "equity" else 1.0
        closes = {row["date"].isoformat(): float(row["close"]) / scale for row in rows}
    return closes, (max(row["date"] for row in rows) if rows else None)


def refresh_asset(asset: dict, root: Path, end: str, overrides: dict, *, apply: bool) -> dict:
    ticker, security_type = asset["ticker"], asset["security_type"]
    path = root / asset["data_path"]
    if not path.exists():
        return {"status": "no_stored_file"}
    old_close, last_stored = stored_closes(path, security_type)
    if last_stored is None:
        return {"status": "empty_stored_file"}
    symbol = yahoo_symbol(asset)
    start = (last_stored - timedelta(days=OVERLAP_DAYS)).isoformat()
    rows, _overridden = apply_price_overrides(fetch_yahoo_ohlcv(symbol, start, end), overrides.get(ticker))
    rows, _widened = sanitize_ohlc(rows)
    if not rows:
        return {"status": "no_data", "yahoo_symbol": symbol}
    new_close = {row["date"].isoformat(): float(row["close"]) for row in rows}
    ratio, anchor = splice_ratio(old_close, new_close)
    fresh = scale_new_rows(rows, ratio, last_stored.isoformat())
    report = {"status": "ok", "yahoo_symbol": symbol, "last_stored": last_stored.isoformat(), "ratio": ratio, "ratio_anchor": anchor,
              "new_rows": len(fresh), "last_new": fresh[-1]["date"].isoformat() if fresh else None,
              "suspicious_ratio": abs(ratio - 1.0) > SUSPICIOUS_RATIO, "no_overlap": anchor is None}
    if apply and fresh:
        write_fn = ASSET_CLASS_CONFIG[CLASS_KEY_BY_SECURITY_TYPE[security_type]].get("write_fn", write_lean_zip)
        write_fn(path, ticker, scale_for_lean(fresh, security_type), merge_with_existing=True)
        if security_type == "crypto" and path.name.endswith("_trade.zip"):
            write_lean_crypto_quote_zip(path, path.with_name(path.name.replace("_trade.zip", "_quote.zip")), ticker, merge_with_existing=True)
    return report


def refresh_fred(config: dict, root: Path, end: str, cutoff: str, *, apply: bool) -> dict[str, dict]:
    report = {}
    cache = root / "data" / "reference" / "fred_series"
    for key, series_id in reference_series(config, "all").items():
        path = cache / f"{key}.csv"
        if not path.exists():
            report[key] = {"status": "no_stored_file"}
            continue
        rows = fetch_fred_series(series_id, "1990-01-01", end)
        if not rows:
            report[key] = {"status": "no_data"}
            continue
        merged = merge_csv_append_only(path.read_text(encoding="utf-8"), rows_to_cache_csv(rows), cutoff)
        added = merged.count("\n") - path.read_text(encoding="utf-8").count("\n")
        report[key] = {"status": "ok", "rows_added": added}
        if apply:
            path.write_text(merged, encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", default=(date.today() + timedelta(days=1)).isoformat(), help="Yahoo end date (exclusive)")
    parser.add_argument("--cutoff", default="2026-09-30", help="rows up to this date must stay byte-identical (FRED rule)")
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--skip-fred", action="store_true")
    parser.add_argument("--report", default=str(ROOT_DIR / "ml" / "evaluation" / "v640" / "data_refresh.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    overrides_path = ROOT_DIR / "data_pipeline" / "price_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    assets = list(config["phase1"]["universe"]["assets"])
    known = {asset["ticker"] for asset in assets}
    assets += [{"ticker": ticker, "security_type": "equity", "data_path": path} for ticker, path in EXTRA_EQUITY.items() if ticker not in known]
    report: dict[str, dict] = {}
    for asset in assets:
        if args.tickers and asset["ticker"] not in args.tickers:
            continue
        if asset["security_type"] not in CLASS_KEY_BY_SECURITY_TYPE:
            continue
        report[asset["ticker"]] = refresh_asset(asset, ROOT_DIR, args.end, overrides, apply=args.apply)
        entry = report[asset["ticker"]]
        print(f"{asset['ticker']:10s} {entry['status']:8s} " + (
            f"+{entry['new_rows']:3d} rows to {entry['last_new']} ratio {entry['ratio']:.6f}" + ("  SUSPICIOUS" if entry["suspicious_ratio"] else "")
            if entry["status"] == "ok" else ""), flush=True)
    fred = {} if args.skip_fred else refresh_fred(config, ROOT_DIR, args.end, args.cutoff, apply=args.apply)
    flagged = sorted(t for t, e in report.items() if e["status"] != "ok" or e.get("suspicious_ratio") or e.get("no_overlap"))
    print(f"{len(report)} assets, {len(flagged)} flagged: {flagged}; FRED: {sum(1 for e in fred.values() if e['status'] == 'ok')} series")
    if args.apply:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps({"end": args.end, "assets": report, "fred": fred}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
