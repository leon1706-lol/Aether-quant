"""Lean-format split/dividend factor-file backfill for equity tickers
missing a local factor file (development/Problems.md #91/#97/#99).

train.py::apply_split_adjustments() backward-adjusts each ticker's raw
OHLCV using data/equity/usa/factor_files/<ticker>.csv - the same
adjustment DataNormalizationMode.Adjusted already applies to main.py's
live/backtest data feed at runtime (Lean's default for
self.add_equity(ticker, self.resolution)). When that local file is
missing, load_factor_file() returns None and apply_split_adjustments()
silently no-ops - offline trains on RAW, unadjusted prices while live
never has this problem. Of 104 configured assets (77 equities), only 22
have a local factor file; the other 63 don't - this whole data/ tree is
gitignored, so this is a local/incomplete data pull, not a deliberate
scope decision anywhere in the code.

This module derives real Lean-format factor files for the missing
tickers from yfinance's own dividend/split history (dev-only dependency,
deferred import - mirrors dividend_backfill.py's/yfinance_backfill.py's
own convention), computing each row's CUMULATIVE backward-adjustment
factor the same way Lean's own factor files do (confirmed by reading a
real one, data/equity/usa/factor_files/aapl.csv, directly: earliest row
carries the largest cumulative adjustment, format is
date(YYYYMMDD),price_factor,split_factor,reference_price, no header,
terminal sentinel row 20501231,1,1,0).

No changes to train.py are needed or made here - load_factor_file()/
apply_split_adjustments() already do the right thing the moment a file
exists at the expected path; this module is purely a data-generation
task.

Same two-safety-boundary shape as dividend_backfill.py/fred_backfill.py/
yfinance_backfill.py:
1. Writing factor files is gated by --apply (default: dry run only).
2. Never touches config.json - this module's only output is
   data/equity/usa/factor_files/*.csv, read back by train.py's own
   dataset-build pipeline (`aq train --dataset-only`), not at Lean
   runtime (main.py never reads these).

Usage:
    python -m data_pipeline.factor_file_backfill [--tickers NVDA GE] [--apply]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
FACTOR_FILES_DIR = ROOT / "data" / "equity" / "usa" / "factor_files"

TERMINAL_SENTINEL_ROW = {"factor_date": "20501231", "price_factor": 1.0, "split_factor": 1.0, "reference_price": 0.0}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def configured_equity_tickers(config: dict) -> list[str]:
    """Every phase1.universe.assets entry with security_type == "equity",
    de-duplicated, order-preserving. Deliberately broader than
    dividend_backfill.option_underlying_tickers() (which only resolves
    option underlyings) - factor files are needed for every directly-
    tradeable equity/ETF asset, including bond ETFs (SHY/IEF/TLT/AGG/...),
    which also pay real distributions and are also security_type "equity".
    Never raises on a malformed asset entry - missing keys are skipped."""
    tickers: list[str] = []
    seen: set[str] = set()
    for asset in config.get("phase1", {}).get("universe", {}).get("assets", []):
        if asset.get("security_type") != "equity":
            continue
        ticker = asset.get("ticker")
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def tickers_missing_factor_file(tickers: list[str], factor_files_dir: Path = FACTOR_FILES_DIR) -> list[str]:
    """Filters `tickers` down to those with no local
    data/equity/usa/factor_files/<ticker-lower>.csv yet - the default CLI
    scope, same "no flag = sane default" pattern as dividend_backfill.py's
    --tickers default."""
    return [ticker for ticker in tickers if not (factor_files_dir / f"{ticker.lower()}.csv").exists()]


def compute_lean_factor_rows(history) -> list[dict]:
    """Pure. `history` is a pandas DataFrame with a DatetimeIndex plus
    Close/Dividends/Stock Splits columns - fetch_corporate_actions()'s
    exact return shape (matches yfinance's own Ticker.history(actions=True)
    column names).

    Walks real events (Dividends != 0 or Stock Splits != 0) newest-to-
    oldest, accumulating:
      - price_factor *= (1 - dividend_amount / close_on_prior_session)
        per dividend event (a cash dividend doesn't change share count,
        only the ex-date price drop needs correcting)
      - split_factor *= 1 / split_ratio per split event
    emitting one row per event date carrying the CUMULATIVE factor as of
    that date - Lean's own convention (confirmed against the real
    data/equity/usa/factor_files/aapl.csv: earliest row carries the
    largest cumulative adjustment, converging to ~1.0 near the most
    recent event). `reference_price` is the raw Close on that event's own
    date (matches the real file's 4th column, an audit reference, never
    consumed by the adjustment formula itself).

    Returns [] when `history` has zero real dividend/split events - no
    row is fabricated for a ticker that never needed adjusting.

    Always appends TERMINAL_SENTINEL_ROW last (Lean's own far-future
    sentinel, matching every real factor file's last row) - EXCEPT when
    there are zero real events, in which case [] is returned instead of a
    sentinel-only file (see this module's docstring / write_factor_file()
    callers: a missing file and a sentinel-only file resolve identically
    through train.py's merge_asof(direction="forward") + .fillna(1.0), so
    skipping is lower-risk than writing a file that isn't needed)."""
    events = []
    for event_date, row in history.iterrows():
        dividend = float(row.get("Dividends", 0.0) or 0.0)
        split = float(row.get("Stock Splits", 0.0) or 0.0)
        if dividend == 0.0 and split == 0.0:
            continue
        events.append(
            {
                "date": event_date,
                "dividend": dividend,
                "split_ratio": split,
                "close": float(row["Close"]),
                "prior_close": None,
            }
        )

    if not events:
        return []

    close_series = history["Close"]
    for event in events:
        prior_close = close_series.loc[:event["date"]].iloc[:-1]
        event["prior_close"] = float(prior_close.iloc[-1]) if not prior_close.empty else float(event["close"])

    events.sort(key=lambda event: event["date"], reverse=True)

    # Cumulative factors are computed walking newest-to-oldest (each older
    # event's factor must already include every later event's adjustment),
    # but the OUTPUT is written oldest-first with the terminal sentinel
    # last - matching every real Lean factor file's own on-disk order
    # (confirmed against data/equity/usa/factor_files/aapl.csv). Not
    # strictly required for correctness (train.py::load_factor_file()
    # re-sorts by date on read regardless), but keeps a generated file
    # directly diffable against a real one.
    rows: list[dict] = []
    price_factor = 1.0
    split_factor = 1.0
    for event in events:
        if event["dividend"] != 0.0 and event["prior_close"] > 0.0:
            price_factor *= 1.0 - (event["dividend"] / event["prior_close"])
        if event["split_ratio"] != 0.0:
            split_factor *= 1.0 / event["split_ratio"]
        event_date = event["date"]
        rows.append(
            {
                "factor_date": event_date.strftime("%Y%m%d") if hasattr(event_date, "strftime") else str(event_date),
                "price_factor": price_factor,
                "split_factor": split_factor,
                "reference_price": event["close"],
            }
        )

    rows.reverse()
    rows.append(dict(TERMINAL_SENTINEL_ROW))
    return rows


# ---------------------------------------------------------------------------
# The only function that imports yfinance - deferred, mirrors
# dividend_backfill.py's/yfinance_backfill.py's own convention.
# ---------------------------------------------------------------------------


def fetch_corporate_actions(yahoo_symbol: str):
    """Real historical Close/Dividends/Stock Splits via ONE yfinance call
    (Ticker.history(period="max", auto_adjust=False, actions=True)) - the
    raw close series and the corporate-action events come back aligned by
    date in a single round-trip, so compute_lean_factor_rows() never needs
    a second network call for "close on the session before the ex-date".
    Returns None on any fetch failure (network, delisted, no history) -
    never raises, same fail-open convention as
    dividend_backfill.fetch_dividend_history()."""
    try:
        import yfinance as yf  # deferred - dev-only dependency, never in requirements.txt

        history = yf.Ticker(yahoo_symbol).history(period="max", auto_adjust=False, actions=True)
    except Exception as exc:
        logger.warning("fetch_corporate_actions(%s): fetch failed — %s", yahoo_symbol, exc)
        return None

    if history is None or history.empty:
        logger.warning("fetch_corporate_actions(%s): no history returned", yahoo_symbol)
        return None
    return history


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def write_factor_file(output_dir: Path, ticker: str, rows: list[dict]) -> Path:
    """Writes data/equity/usa/factor_files/<ticker-lower>.csv, no header,
    Lean's exact column order (date,price_factor,split_factor,
    reference_price) - matches train.py::load_factor_file()'s own read
    shape (names=["factor_date", "price_factor", "split_factor",
    "reference_price"]) column-for-column."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{ticker.lower()}.csv"
    lines = [
        f"{row['factor_date']},{row['price_factor']},{row['split_factor']},{row['reference_price']}"
        for row in rows
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    parser = argparse.ArgumentParser(
        description="Aether Quant Lean factor-file backfill - offline/manual only, "
        "no API key required, never run inside Lean or a Docker worker."
    )
    parser.add_argument(
        "--tickers", nargs="*", default=None,
        help="Restrict to these tickers (default: every configured equity ticker missing a local factor file)",
    )
    parser.add_argument("--apply", action="store_true", help="Actually write factor files (default: dry run, report only)")
    parser.add_argument("--config-path", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=FACTOR_FILES_DIR)
    args = parser.parse_args()

    with args.config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    tickers = args.tickers if args.tickers else tickers_missing_factor_file(configured_equity_tickers(config), args.output_dir)

    print(f"{'APPLY' if args.apply else 'DRY RUN'} — checking corporate-action history for {len(tickers)} ticker(s):\n")
    for ticker in tickers:
        history = fetch_corporate_actions(ticker)
        if history is None:
            print(f"- {ticker}: no_data_returned")
            continue
        rows = compute_lean_factor_rows(history)
        if not rows:
            print(f"- {ticker}: skipped_no_corporate_actions (identity fallback is already correct, no file needed)")
            continue
        if args.apply:
            write_factor_file(args.output_dir, ticker, rows)
            action = "written"
        else:
            action = "dry_run"
        print(f"- {ticker}: {action}, factor_rows={len(rows) - 1} (+ terminal sentinel)")

    if not args.apply:
        print("\nDry run only — no factor files were written. Re-run with --apply to write them.")


if __name__ == "__main__":
    main()
