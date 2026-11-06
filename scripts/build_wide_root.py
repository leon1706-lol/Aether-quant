"""The wide equity root of V6.6.0: a separate Lean data root with every S&P 500 member since 2003, Yahoo daily bars.

Never a change to `data/`, which stays one fixed vintage (AGENTS.md rule 12). Only names with bars are here; Yahoo has no delisted
ones, and `ml/evaluation/v660/wide_coverage.json` measures that gap. A rerun resumes: a ticker already in the manifest is skipped.

The script records only row counts, spans and hashes. Nothing here computes a return.

    python scripts/build_wide_root.py --start 2003-06-01 --end 2026-11-03 --out data_wide
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import time as _time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_pipeline.sp500_membership import (  # noqa: E402
    fetch_membership,
    load_membership,
    suspect_interval,
    tickers_touching,
    write_coverage,
    yahoo_symbol_for_member,
)
from data_pipeline.yfinance_backfill import sanitize_ohlc, scale_for_lean, write_lean_zip  # noqa: E402

MANIFEST = "wide_manifest.json"
RAW_DIR = "reference/raw_closes"
COPIED_DIRS = ("market-hours", "symbol-properties", "reference", Path("alternative") / "interest-rate", Path("crypto") / "coinbase" / "daily")
EMPTY_DIRS = (Path("equity") / "usa" / "map_files", Path("equity") / "usa" / "factor_files")
SECTOR_ETFS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLC", "XLRE")
BENCHMARKS = ("SPY", "AGG", "BIL")


def fetch_adjusted_and_raw(symbol: str, start: str, end: str) -> tuple[list[dict], dict[str, float]]:
    """(rows as `fetch_yahoo_ohlcv` gives them, split-adjusted closes without dividends). Yahoo's `Adj Close` / `Close` ratio is what
    `auto_adjust=True` applies, so one download serves both. Market cap needs the second: an adjusted close embeds later dividends."""
    import pandas as pd
    import yfinance as yf

    frame = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False, threads=False)
    if frame is None or frame.empty:
        return [], {}
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    rows, raw = [], {}
    for stamp, row in frame.iterrows():
        close, adjusted = float(row["Close"]), float(row["Adj Close"])
        if not (close > 0.0 and adjusted > 0.0):
            continue
        ratio = adjusted / close
        day = stamp.date()
        rows.append({
            "date": day, "open": float(row["Open"]) * ratio, "high": float(row["High"]) * ratio, "low": float(row["Low"]) * ratio,
            "close": adjusted, "volume": float(row["Volume"]) if row["Volume"] == row["Volume"] else 0.0,
        })
        raw[day.isoformat()] = close
    return rows, raw


def build_root(
    out: Path, *, start: str, end: str, config: dict, source: Path = ROOT / "data",
    fetch_fn: Callable[[str, str, str], tuple[list[dict], dict[str, float]]] = fetch_adjusted_and_raw, pause_seconds: float = 0.2,
    get_membership: Callable[[str], str] | None = None, coverage_path: Path | None = None, retries: int = 2,
) -> dict:
    """Writes the root and returns its manifest. A failed name is left out and reported, never guessed."""
    out = Path(out)
    for relative in COPIED_DIRS:
        if (source / relative).exists():
            (out / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source / relative, out / relative, dirs_exist_ok=True)
    for relative in EMPTY_DIRS:
        (out / relative).mkdir(parents=True, exist_ok=True)
    (out / RAW_DIR).mkdir(parents=True, exist_ok=True)

    manifest_path = out / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"start": start, "end": end, "tickers": {}, "left_out": {}}
    manifest["membership"] = fetch_membership(out / "reference", get=get_membership)
    table = load_membership(out / "reference" / "sp500_ticker_start_end.csv")
    members = set(tickers_touching(table, start, end))
    project = {str(asset["ticker"]) for asset in config["phase1"]["universe"]["assets"] if asset["security_type"] == "equity"}
    wanted = sorted(members | project | set(SECTOR_ETFS) | set(BENCHMARKS))

    for count, ticker in enumerate(wanted, start=1):
        if ticker in manifest["tickers"] or manifest["left_out"].get(ticker, "").startswith("suspect"):
            continue
        rows, raw = [], {}
        for attempt in range(retries + 1):
            try:
                rows, raw = fetch_fn(yahoo_symbol_for_member(ticker), start, end)
            except Exception as error:  # one bad ticker must not lose the others
                manifest["left_out"][ticker] = f"fetch failed: {type(error).__name__}"
                rows = []
            if rows:
                break
            if pause_seconds and attempt < retries:
                _time.sleep(pause_seconds * 5)
        rows, _ = sanitize_ohlc(rows)
        rows = [row for row in rows if row["date"].isoformat() < end]
        if not rows:
            manifest["left_out"].setdefault(ticker, "no bars")
            continue
        first = rows[0]["date"].isoformat()
        if ticker in table and suspect_interval(table[ticker], first, window_start=start):
            manifest["left_out"][ticker] = f"suspect: bars begin {first}, after its membership began"
            continue
        path = out / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_lean_zip(path, ticker, scale_for_lean(rows, "equity"), merge_with_existing=False)
        (out / RAW_DIR / f"{ticker.lower()}.json").write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8", newline="\n")
        manifest["left_out"].pop(ticker, None)
        manifest["tickers"][ticker] = {
            "rows": len(rows), "first": first, "last": rows[-1]["date"].isoformat(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "member": ticker in table,
        }
        if count % 25 == 0:
            manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
            print(f"{count} of {len(wanted)}: {len(manifest['tickers'])} written, {len(manifest['left_out'])} left out", flush=True)
        if pause_seconds:
            _time.sleep(pause_seconds)
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    if coverage_path is not None:
        write_coverage(coverage_path, table, set(manifest["tickers"]), manifest["left_out"])
    return manifest


def wide_config(base: dict, manifest: dict, *, keep_project_crypto: bool = True, tickers: set[str] | None = None) -> dict:
    """A run config on this root: every name with bars (or `tickers`), plus the benchmarks and the project's crypto. An asset's
    `data_path` keeps the `data/` prefix: `asset_zip_paths` and a Codespace run's `.dataroot` swap the root under it."""
    config = copy.deepcopy(base)
    assets = []
    for ticker, entry in sorted(manifest["tickers"].items()):
        if ticker == "BIL" or (tickers is not None and ticker not in tickers and ticker not in BENCHMARKS):
            continue  # BIL is the sweep, outside the universe
        assets.append({
            "ticker": ticker, "security_type": "equity", "market": "usa", "data_path": f"data/equity/usa/daily/{ticker.lower()}.zip",
            "available_from": entry["first"], "available_to": entry["last"],
        })
    if keep_project_crypto:
        assets += [asset for asset in base["phase1"]["universe"]["assets"] if asset["security_type"] == "crypto"]
    config["phase1"]["universe"]["assets"] = assets
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2003-06-01")
    parser.add_argument("--end", default="2026-11-03")
    parser.add_argument("--out", default="data_wide")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    manifest = build_root(ROOT / args.out, start=args.start, end=args.end, config=config, coverage_path=ROOT / "ml" / "evaluation" / "v660" / "wide_coverage.json")
    print(f"{len(manifest['tickers'])} tickers written, {len(manifest['left_out'])} left out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
