"""Yahoo Finance historical data backfill (Phase V2-19.5).

Manual, offline maintenance script — never runs inside the Lean container or
any always-on Docker worker (mirrors train_topology.py's "never runs in the
Lean container" status, not performance/trigger_worker.py's continuous-worker
one). Fills gaps in thin local Lean zips (e.g. ETHUSD/LTCUSD, which only have
a few scattered days of real Coinbase minute data — see
train.py::ensure_derived_crypto_daily_series() and development/Changelog.md's
Phase-9 entry) using `yfinance`.

Two independent safety boundaries, both requiring an explicit human step:
1. Writing/overwriting zip files is gated by --apply (default: dry run only).
2. config.json's available_from/available_to are NEVER edited by this
   script, --apply or not — train.py::build_asset_quality() only counts rows
   inside those configured windows (config.json phase9.asset_quality), so
   widening the zip alone does nothing until a human widens the window too.
   This script only prints the suggested new values.

Usage:
    python -m data_pipeline.yfinance_backfill [--tickers ETHUSD LTCUSD] [--apply]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from zipfile import ZipFile

import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"

# Internal ticker -> Yahoo symbol, used only when the asset's own
# config.json "backfill" block doesn't set an explicit "symbol".
YAHOO_TICKER_OVERRIDES = {
    "ETHUSD": "ETH-USD",
    "BTCUSD": "BTC-USD",
    "LTCUSD": "LTC-USD",
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def yahoo_symbol_for(ticker: str, backfill_config: dict) -> str:
    """backfill_config["symbol"] wins if present, else YAHOO_TICKER_OVERRIDES,
    else the internal ticker unchanged (equities: AAPL -> AAPL)."""
    explicit = backfill_config.get("symbol")
    if explicit:
        return str(explicit)
    return YAHOO_TICKER_OVERRIDES.get(ticker, ticker)


def detect_gap(asset: dict, existing_rows: list[dict]) -> dict:
    """Pure: compares the asset's configured backfill_from/backfill_to
    against the dates already present in its Lean zip (existing_rows, each a
    dict with a "date" key holding a datetime.date). Returns whether a real
    gap exists and the date range that should actually be fetched.
    """
    backfill_config = asset.get("backfill") or {}
    if not backfill_config:
        return {"needs_backfill": False, "missing_before": None, "missing_after": None, "fetch_start": None, "fetch_end": None}

    fetch_start = date.fromisoformat(backfill_config["backfill_from"])
    fetch_end = date.fromisoformat(backfill_config["backfill_to"])

    existing_dates = [row["date"] for row in existing_rows]
    existing_min = min(existing_dates) if existing_dates else None
    existing_max = max(existing_dates) if existing_dates else None

    missing_before = fetch_start if (existing_min is None or fetch_start < existing_min) else None
    missing_after = fetch_end if (existing_max is None or fetch_end > existing_max) else None

    return {
        "needs_backfill": missing_before is not None or missing_after is not None,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "fetch_start": fetch_start,
        "fetch_end": fetch_end,
    }


def scale_for_lean(rows: list[dict], security_type: str) -> list[dict]:
    """Applies train.py's x10000 integer convention for equities (Lean's
    deflated-price format — see train.py::load_lean_bars()); crypto rows
    pass through unscaled, matching
    train.py::ensure_derived_crypto_daily_series(). Pure — no I/O.
    """
    if security_type != "equity":
        return [dict(row) for row in rows]

    scaled = []
    for row in rows:
        scaled.append(
            {
                "date": row["date"],
                "open": round(row["open"] * 10000),
                "high": round(row["high"] * 10000),
                "low": round(row["low"] * 10000),
                "close": round(row["close"] * 10000),
                "volume": row["volume"],
            }
        )
    return scaled


def rows_to_lean_csv(rows: list[dict]) -> str:
    """Exact row format train.py::ensure_derived_crypto_daily_series() writes:
    f"{date:%Y%m%d} 00:00,{open},{high},{low},{close},{volume}", one row per
    line, sorted by date.
    """
    ordered = sorted(rows, key=lambda row: row["date"])
    lines = [
        f"{row['date'].strftime('%Y%m%d')} 00:00,{row['open']},{row['high']},{row['low']},{row['close']},{row['volume']}"
        for row in ordered
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def _numeric(value: str):
    try:
        return int(value)
    except ValueError:
        return float(value)


def _read_existing_lean_rows(path: Path) -> list[dict]:
    """Reads a Lean daily zip's rows back into the same dict shape
    scale_for_lean()/rows_to_lean_csv() use, preserving whatever numeric
    representation (int or float) is already stored — no rescaling."""
    rows: list[dict] = []
    with ZipFile(path) as archive:
        member = archive.namelist()[0]
        with archive.open(member) as handle:
            text = handle.read().decode("utf-8")

    for line in text.splitlines():
        if not line.strip():
            continue
        date_field, open_v, high_v, low_v, close_v, volume_v = line.split(",")
        row_date = datetime.strptime(date_field.split()[0], "%Y%m%d").date()
        rows.append(
            {
                "date": row_date,
                "open": _numeric(open_v),
                "high": _numeric(high_v),
                "low": _numeric(low_v),
                "close": _numeric(close_v),
                "volume": _numeric(volume_v),
            }
        )
    return rows


def write_lean_zip(output_zip: Path, ticker: str, new_rows: list[dict], *, merge_with_existing: bool = True) -> None:
    """Mirrors train.py::ensure_derived_crypto_daily_series()'s
    ZipFile(output_zip, 'w') pattern, member name f'{ticker.lower()}.csv'.

    When merge_with_existing, reads the existing zip's rows first and keys
    the merge by date — existing (real Lean) rows always win on overlap;
    new_rows only fill dates that were genuinely missing.
    """
    merged_by_date: dict[date, dict] = {}
    if merge_with_existing and output_zip.exists():
        for row in _read_existing_lean_rows(output_zip):
            merged_by_date[row["date"]] = row

    for row in new_rows:
        merged_by_date.setdefault(row["date"], row)

    csv_text = rows_to_lean_csv(list(merged_by_date.values()))

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    member_name = f"{ticker.lower()}.csv"
    with ZipFile(output_zip, "w") as archive:
        archive.writestr(member_name, csv_text)


# ---------------------------------------------------------------------------
# The only function that imports yfinance — deferred, mirrors
# experience/redis_queue.py's deferred `import redis`.
# ---------------------------------------------------------------------------


def fetch_yahoo_ohlcv(symbol: str, start: str, end: str) -> list[dict]:
    """Real dollar/crypto prices, unscaled. Returns [] on any failure or
    empty response — never raises, so one bad symbol never aborts a
    multi-asset run."""
    try:
        import yfinance as yf  # deferred — dev-only dependency, never in requirements.txt

        # auto_adjust=True: Yahoo applies its own split/dividend adjustment
        # before this ever reaches a Lean zip. This module today only ever
        # backfills crypto gaps (no splits/dividends), but train.py reading
        # its own equity Lean zips unadjusted was a real, separate bug (see
        # train.py::apply_split_adjustments()/development/Problems.md) -
        # this flag stays correct here so a future equity backfill (this
        # module's docstring already anticipates non-crypto assets) doesn't
        # reintroduce the same class of unadjusted-price corruption.
        frame = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
    except Exception as exc:
        logger.warning("fetch_yahoo_ohlcv(%s): fetch failed — %s", symbol, exc)
        return []

    if frame is None or frame.empty:
        logger.warning("fetch_yahoo_ohlcv(%s): no data returned for %s..%s", symbol, start, end)
        return []

    # Newer yfinance always returns MultiIndex columns (price field, ticker),
    # even for a single-ticker download — `record["Open"]` on that shape
    # returns a length-1 Series instead of a scalar, and `float(...)` on it
    # only works today via a deprecated pandas fallback (FutureWarning: will
    # raise TypeError in a future pandas). Flattening to the price-field
    # level here keeps `record["Open"]` a plain scalar regardless of which
    # yfinance/pandas version is installed.
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    rows = []
    for index, record in frame.iterrows():
        row_date = index.date() if hasattr(index, "date") else index
        rows.append(
            {
                "date": row_date,
                "open": float(record["Open"]),
                "high": float(record["High"]),
                "low": float(record["Low"]),
                "close": float(record["Close"]),
                "volume": float(record["Volume"]),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def plan_backfill(config: dict, *, tickers: list[str] | None = None) -> list[dict]:
    """Orchestrates over config["phase1"]["universe"]["assets"] entries that
    carry an optional "backfill" sub-block. Reads existing zip rows (if the
    zip already exists) purely to compute the gap — no network I/O here."""
    plans = []
    for asset in config["phase1"]["universe"]["assets"]:
        backfill_config = asset.get("backfill")
        if not backfill_config:
            continue
        if tickers and asset["ticker"] not in tickers:
            continue

        output_zip = ROOT / asset["data_path"]
        existing_rows = _read_existing_lean_rows(output_zip) if output_zip.exists() else []
        gap = detect_gap(asset, existing_rows)

        plans.append(
            {
                "ticker": asset["ticker"],
                "security_type": asset["security_type"],
                "yahoo_symbol": yahoo_symbol_for(asset["ticker"], backfill_config),
                "data_path": str(output_zip),
                "gap": gap,
            }
        )
    return plans


def run_backfill(config: dict, plan: list[dict], *, apply: bool, fetch_fn: Callable = fetch_yahoo_ohlcv) -> dict:
    """apply=False (default): dry run — fetches nothing written to disk.
    apply=True: writes merged zips via write_lean_zip(). fetch_fn is the
    injection point for tests (never real yfinance in tests)."""
    entries = []
    for plan_entry in plan:
        gap = plan_entry["gap"]
        if not gap["needs_backfill"]:
            entries.append({**plan_entry, "action": "skipped_no_gap", "rows_fetched": 0})
            continue

        rows = fetch_fn(plan_entry["yahoo_symbol"], gap["fetch_start"].isoformat(), gap["fetch_end"].isoformat())
        scaled_rows = scale_for_lean(rows, plan_entry["security_type"])

        if not scaled_rows:
            action = "no_data_returned"
        elif apply:
            write_lean_zip(Path(plan_entry["data_path"]), plan_entry["ticker"], scaled_rows, merge_with_existing=True)
            action = "written"
        else:
            action = "dry_run"

        dates = [row["date"] for row in rows]
        entries.append(
            {
                **plan_entry,
                "action": action,
                "rows_fetched": len(rows),
                "suggested_available_from": min(dates) if dates else None,
                "suggested_available_to": max(dates) if dates else None,
            }
        )
    return {"apply": apply, "entries": entries}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    parser = argparse.ArgumentParser(
        description="Aether Quant Yahoo Finance historical data backfill (V2-19.5) — "
        "offline/manual only, never run inside Lean or a Docker worker."
    )
    parser.add_argument("--tickers", nargs="*", default=None, help="Restrict to these tickers (default: all assets with a 'backfill' block)")
    parser.add_argument("--apply", action="store_true", help="Actually write zip files (default: dry run, report only)")
    parser.add_argument("--config-path", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()

    with args.config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    plan = plan_backfill(config, tickers=args.tickers)
    if not plan:
        print("No assets with a 'backfill' config block found (nothing to do).")
        return

    report = run_backfill(config, plan, apply=args.apply)
    print(f"{'APPLY' if args.apply else 'DRY RUN'} — {len(report['entries'])} asset(s) evaluated:\n")
    for entry in report["entries"]:
        print(f"- {entry['ticker']} ({entry['yahoo_symbol']}): {entry['action']}, rows_fetched={entry['rows_fetched']}")
        if entry.get("suggested_available_from"):
            print(
                f"    If this widens coverage, update config.json manually: "
                f"available_from={entry['suggested_available_from'].isoformat()}"
            )

    if not args.apply:
        print("\nDry run only — no files were written. Re-run with --apply to write zip files.")
    print(
        "\nNote: config.json's available_from/available_to are never edited automatically. "
        "Update them by hand for the wider history to actually affect training/backtesting."
    )


if __name__ == "__main__":
    main()
