"""Fetch Yahoo-adjusted bars for every universe asset into a staging root (V5.7.0 holdout fetcher, V5.8.0 data refresh).

Every trained model and every lever was tuned on 2014-12..2021-03; only the 2018 validation year is independent, and it
is thin. This fetches Yahoo (already split/dividend-adjusted) daily bars for every universe asset from `--start` to
`--end` (default 2014-06-01..2025-06-30), writes them as Lean-format zips at the same relative paths under
`--root`, and re-fetches every FRED series the features read (bond, alt-data, FX rates) through the same end date
into `<root>/reference/fred_series/`. Nothing under `data/` is touched, so the trained models, the dataset and
Lean backtests stay exactly as they were; the holdout is evaluation-only (`scripts/build_holdout_dataset.py`).

Assets Yahoo cannot serve (delisted, renamed) are skipped and listed - the holdout universe is whatever survives.

    python scripts/build_holdout_data.py [--start 2014-06-01] [--end 2025-06-30] [--root data_v6_staging] [--apply]

V6.0.0: `data_holdout/` was deleted (the holdout lives inside `data/` since V5.8.0); the default root is a staging folder
that `aq evaluate --audit-data --data-root` checks before anything is copied over `data/`.

Dry run by default (fetches and reports, writes nothing).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from data_pipeline.fetch import ASSET_CLASS_CONFIG  # noqa: E402
from data_pipeline.fred_backfill import fetch_fred_series, reference_series, write_fred_series_cache  # noqa: E402
from data_pipeline.yfinance_backfill import (  # noqa: E402
    apply_price_overrides,
    fetch_yahoo_ohlcv,
    sanitize_ohlc,
    scale_for_lean,
    write_lean_crypto_quote_zip,
    write_lean_zip,
)


def holdout_zip_path(root: Path, asset: dict) -> Path:
    relative = Path(asset["data_path"])
    return root / Path(*relative.parts[1:])


# data_pipeline.fetch names its asset classes differently from Lean security types
CLASS_KEY_BY_SECURITY_TYPE = {"equity": "stock", "crypto": "crypto", "forex": "forex"}


# Lean symbols whose Yahoo ticker changed after the model's window (FB -> META in 2022; a bare "FB" on Yahoo is another stock)
YAHOO_RENAMES = {"FB": "META"}


def yahoo_symbol(asset: dict) -> str:
    explicit = (asset.get("backfill") or {}).get("symbol")
    if explicit:
        return str(explicit)
    if asset["ticker"] in YAHOO_RENAMES:
        return YAHOO_RENAMES[asset["ticker"]]
    return ASSET_CLASS_CONFIG[CLASS_KEY_BY_SECURITY_TYPE[asset["security_type"]]]["yahoo_symbol_fn"](asset["ticker"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2014-06-01")
    parser.add_argument("--end", default="2025-06-30")
    parser.add_argument("--root", default="data_v6_staging")
    parser.add_argument("--apply", action="store_true", help="write the zips and FRED cache (default: dry run)")
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument(
        "--report-name", default="holdout_report.json",
        help="V5.8.0: report file written under --root (the V5.8.0 window extension writes refresh_report.json)",
    )
    parser.add_argument("--skip-fred", action="store_true", help="V5.8.0: zips only (FRED handled by `aq backfill fred`)")
    args = parser.parse_args()

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    root = ROOT_DIR / args.root
    overrides_path = ROOT_DIR / "data_pipeline" / "price_overrides.json"
    price_overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    report: dict[str, dict] = {}
    for asset in config["phase1"]["universe"]["assets"]:
        ticker, security_type = asset["ticker"], asset["security_type"]
        if args.tickers and ticker not in args.tickers:
            continue
        if security_type not in CLASS_KEY_BY_SECURITY_TYPE:
            report[ticker] = {"status": "skipped_security_type", "security_type": security_type}
            continue
        symbol = yahoo_symbol(asset)
        rows, overridden = apply_price_overrides(fetch_yahoo_ohlcv(symbol, args.start, args.end), price_overrides.get(ticker))
        rows, ohlc_fixed = sanitize_ohlc(rows)
        if not rows:
            report[ticker] = {"status": "no_data", "yahoo_symbol": symbol}
            print(f"{ticker:10s} {symbol:10s} NO DATA")
            continue
        report[ticker] = {
            "status": "ok", "yahoo_symbol": symbol, "rows": len(rows), "ohlc_rows_widened": ohlc_fixed,
            "price_overrides_applied": overridden,
            "first": rows[0]["date"].isoformat(), "last": rows[-1]["date"].isoformat(),
        }
        print(f"{ticker:10s} {symbol:10s} {len(rows):5d} rows {report[ticker]['first']}..{report[ticker]['last']}")
        if args.apply:
            write_fn = ASSET_CLASS_CONFIG[CLASS_KEY_BY_SECURITY_TYPE[security_type]].get("write_fn", write_lean_zip)
            target = holdout_zip_path(root, asset)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_fn(target, ticker, scale_for_lean(rows, security_type), merge_with_existing=False)
            if security_type == "crypto" and target.name.endswith("_trade.zip"):
                # V5.8.0: Lean requests a crypto quote feed too; derive it from the fresh trade zip (zero-spread rows)
                write_lean_crypto_quote_zip(
                    target, target.with_name(target.name.replace("_trade.zip", "_quote.zip")), ticker,
                    merge_with_existing=False,
                )

    fred_report: dict[str, int] = {}
    for key, series_id in ({} if args.skip_fred else reference_series(config, "all")).items():
        rows = fetch_fred_series(series_id, "1990-01-01", args.end)
        fred_report[key] = len(rows)
        if args.apply and rows:
            write_fred_series_cache(root / "reference" / "fred_series", key, rows)
    print("FRED rows:", fred_report)

    failures = sorted(ticker for ticker, entry in report.items() if entry["status"] != "ok")
    print(f"{len(report) - len(failures)} assets ok, {len(failures)} without holdout data: {failures}")
    if args.apply:
        root.mkdir(parents=True, exist_ok=True)
        (root / args.report_name).write_text(json.dumps({"assets": report, "fred_rows": fred_report}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
