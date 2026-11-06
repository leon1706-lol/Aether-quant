"""The wide crypto root of V6.6.0: every USDT spot pair Binance's archive holds, delisted ones included, as a Lean data root.

Pairs are written under Lean's Coinbase market so a run uses the project's fee model (the blocking cost) and symbol properties are
added for coins Lean doesn't know. The root also holds SPY, AGG, BIL and BTCUSD: with no equity bars the target path has no sessions,
and nothing trades. A rerun resumes. The script records only row counts, spans and hashes.

    python scripts/build_crypto_wide_root.py --out data_crypto_wide
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
import time as _time
import zipfile
from collections.abc import Callable
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_pipeline import net_retry  # noqa: E402
from data_pipeline.binance_archive import (  # noqa: E402
    FUNDING_PREFIX,
    KLINE_PREFIX,
    base_asset,
    daily_funding,
    fetch_series,
    funding_url,
    kline_url,
    list_symbols,
    listed_months,
    parse_funding_zip,
    parse_kline_zip,
    truncate_at_swap,
    write_frame,
)
from data_pipeline.yfinance_backfill import write_lean_crypto_quote_zip, write_lean_zip  # noqa: E402

MANIFEST = "crypto_wide_manifest.json"
PROJECT_COINS_FIRST = ("BTC", "ETH")
START, END = "2017-08-01", "2026-11-02"
COPIED_DIRS = ("market-hours", "symbol-properties", Path("alternative") / "interest-rate")
FROM_WIDE = ("spy", "agg", "bil")


def add_symbol_properties(database: Path, coins: list[str]) -> list[str]:
    """Rows for coins Lean's table lacks under Coinbase. Returns those added. Lot and tick follow Lean's Coinbase rows: an order is
    sized to these, and no real order ever uses them."""
    lines = database.read_text(encoding="utf-8").splitlines()
    existing = {line.split(",")[1].upper() for line in lines if line.startswith("coinbase,")}
    added = [coin for coin in coins if f"{coin}USD" not in existing]
    rows = [f"coinbase,{coin}USD,crypto,{coin}-US Dollar,USD,1,0.00000001,0.00000001,{coin}-USD,0.00000001" for coin in added]
    database.write_text("\n".join(lines + rows) + "\n", encoding="utf-8", newline="\n")
    return added


def cut_swaps(out: Path) -> dict:
    """The same cut on a root built before `truncate_at_swap` existed. Bars only: volume and funding past a cut are never reached."""
    manifest_path = out / "crypto_wide_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    daily = out / "crypto" / "coinbase" / "daily"
    for coin, entry in manifest["coins"].items():
        ticker = entry["ticker"]
        trade = daily / f"{ticker.lower()}_trade.zip"
        with zipfile.ZipFile(trade) as archive, archive.open(archive.namelist()[0]) as handle:
            lines = list(csv.reader(io.TextIOWrapper(handle, encoding="utf-8")))
        rows = [{
            "date": f"{line[0][:4]}-{line[0][4:6]}-{line[0][6:8]}", "open": float(line[1]), "high": float(line[2]), "low": float(line[3]),
            "close": float(line[4]), "volume": float(line[5]),
        } for line in lines]
        kept, swap = truncate_at_swap(rows)
        if not swap:
            continue
        bars = lean_rows(kept)
        write_lean_zip(trade, ticker, bars, merge_with_existing=False)
        write_lean_crypto_quote_zip(trade, trade.with_name(f"{ticker.lower()}_quote.zip"), ticker, merge_with_existing=False)
        entry.update({"rows": len(bars), "last": bars[-1]["date"].isoformat(), "sha256": hashlib.sha256(trade.read_bytes()).hexdigest()})
        manifest.setdefault("cut_at_a_swap", {})[coin] = swap
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest.get("cut_at_a_swap", {})


def lean_rows(rows: list[dict]) -> list[dict]:
    """Bars as `write_lean_zip` takes them, one per date, the last file's row winning. Crypto isn't price-scaled."""
    import datetime

    by_date = {row["date"]: row for row in rows}
    return [{
        "date": datetime.date.fromisoformat(date), "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
        "volume": row["volume"],
    } for date, row in sorted(by_date.items())]


def build_root(
    out: Path, *, get_text: Callable[[str], str], get_bytes: Callable[[str], bytes | None], source: Path = ROOT / "data",
    wide_root: Path = ROOT / "data_wide", start: str = START, end: str = END, pause_seconds: float = 0.2,
) -> dict:
    out = Path(out)
    for relative in COPIED_DIRS:
        if (source / relative).exists():
            (out / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source / relative, out / relative, dirs_exist_ok=True)
    (out / "equity" / "usa" / "daily").mkdir(parents=True, exist_ok=True)
    for name in FROM_WIDE:
        shutil.copy2(Path(wide_root) / "equity" / "usa" / "daily" / f"{name}.zip", out / "equity" / "usa" / "daily" / f"{name}.zip")
    (out / "equity" / "usa" / "map_files").mkdir(parents=True, exist_ok=True)
    (out / "equity" / "usa" / "factor_files").mkdir(parents=True, exist_ok=True)

    manifest_path = out / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"start": start, "end": end, "coins": {}, "left_out": {}}
    symbols = [symbol for symbol in list_symbols(get_text) if base_asset(symbol)]
    manifest["pairs_listed"] = len(symbols)
    quote_volume: dict[str, dict[str, float]] = {}
    funding: dict[str, dict[str, float]] = {}
    volume_path, funding_path = out / "reference" / "quote_volume.parquet", out / "reference" / "funding.parquet"
    if volume_path.exists():
        quote_volume = {column: series.dropna().to_dict() for column, series in pd.read_parquet(volume_path).items()}
    if funding_path.exists():
        funding = {column: series.dropna().to_dict() for column, series in pd.read_parquet(funding_path).items()}

    for count, symbol in enumerate(symbols, start=1):
        coin = base_asset(symbol)
        if coin in manifest["coins"] or coin in manifest["left_out"]:
            continue
        rows = fetch_series(kline_url, parse_kline_zip, symbol, start, end, get_bytes, months=listed_months(get_text, f"{KLINE_PREFIX}{symbol}/1d/"))
        if not rows:
            manifest["left_out"][coin] = "no bars"
            continue
        rows, swap = truncate_at_swap(rows)
        if swap:
            manifest.setdefault("cut_at_a_swap", {})[coin] = swap
        bars = lean_rows(rows)
        ticker = f"{coin}USD"
        trade = out / "crypto" / "coinbase" / "daily" / f"{ticker.lower()}_trade.zip"
        trade.parent.mkdir(parents=True, exist_ok=True)
        write_lean_zip(trade, ticker, bars, merge_with_existing=False)
        write_lean_crypto_quote_zip(trade, trade.with_name(f"{ticker.lower()}_quote.zip"), ticker, merge_with_existing=False)
        quote_volume[ticker] = {row["date"]: row["quote_volume"] for row in rows}
        settlements = fetch_series(
            funding_url, parse_funding_zip, symbol, "2019-09-01", end, get_bytes, months=listed_months(get_text, f"{FUNDING_PREFIX}{symbol}/") or [],
        )
        if settlements:
            funding[ticker] = daily_funding(settlements)
        manifest["coins"][coin] = {
            "ticker": ticker, "rows": len(bars), "first": bars[0]["date"].isoformat(), "last": bars[-1]["date"].isoformat(),
            "sha256": hashlib.sha256(trade.read_bytes()).hexdigest(), "funding": bool(settlements),
        }
        if count % 5 == 0:
            _save(manifest_path, manifest, volume_path, quote_volume, funding_path, funding)
            print(f"{count} of {len(symbols)}: {len(manifest['coins'])} coins", flush=True)
        if pause_seconds:
            _time.sleep(pause_seconds)
    _save(manifest_path, manifest, volume_path, quote_volume, funding_path, funding)
    database = out / "symbol-properties" / "symbol-properties-database.csv"
    if database.exists():
        manifest["symbol_properties_added"] = len(add_symbol_properties(database, sorted(manifest["coins"])))
        manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest


def _save(manifest_path, manifest, volume_path, quote_volume, funding_path, funding) -> None:
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    write_frame(volume_path, pd.DataFrame(quote_volume).sort_index())
    write_frame(funding_path, pd.DataFrame(funding).sort_index())


def write_coverage(path: Path, manifest: dict, *, delisted_after: str = "2026-09-01") -> dict:
    """Coins whose bars stopped before the end: how the root differs from today's survivors. Holds no price or return."""
    stopped = {coin: entry["last"] for coin, entry in manifest["coins"].items() if entry["last"] < delisted_after}
    report = {"coins": len(manifest["coins"]), "stopped_before_the_end": len(stopped), "last_bar": dict(sorted(stopped.items())), "left_out": manifest["left_out"]}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return report


def main() -> int:
    import requests

    session = requests.Session()
    session.headers["User-Agent"] = "AetherQuantResearch/6.6 (github.com/leon1706-lol/Aether-quant)"

    def get_text(url: str) -> str:
        response = net_retry.fetch(url, get=session.get, timeout=60.0)
        if response is None:
            raise SystemExit(f"{url}: the listing itself is gone")
        return response.text

    def get_bytes(url: str) -> bytes | None:
        response = net_retry.fetch(url, get=session.get, timeout=60.0)
        return None if response is None else response.content

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="data_crypto_wide")
    parser.add_argument("--cut-swaps", action="store_true", help="cut the pairs of an existing root at a token swap; downloads nothing")
    args = parser.parse_args()
    if args.cut_swaps:
        print(json.dumps(cut_swaps(ROOT / args.out), indent=1))
        return 0
    try:
        manifest = build_root(ROOT / args.out, get_text=get_text, get_bytes=get_bytes)
    except net_retry.NetworkOutage as error:
        print(f"stopped by a network outage, rerun to resume: {error}", file=sys.stderr, flush=True)
        return 3
    report = write_coverage(ROOT / "ml" / "evaluation" / "v660" / "crypto_wide_coverage.json", manifest)
    print(f"{report['coins']} coins, {report['stopped_before_the_end']} stopped before the end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
