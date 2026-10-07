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

V5.5.0 (development/Problems.md #130) - DOUBLE-ADJUSTMENT FIX. The 63 files
this module generated in V5.3.3 were applied on top of zips that
yfinance_backfill.py had ALREADY written with `auto_adjust=True`, i.e. prices
that are split- AND dividend-adjusted as of fetch time. Both train.py and
Lean then multiplied them by the factor file again:
  - prices carried the cumulative split factor a second time (AMZN $84.63 in
    2019 became $4.23, NVDA ~$0.02-0.3), so per-share IB commissions on a
    share count 20-480x too large cost 16-49 bps a side instead of ~1;
  - every ex-dividend date gained an extra +dividend-yield return (the series
    already contained it), flattering dividend payers' longs and penalizing
    their shorts.
Evidence, reproducible with `--audit`: for each generated file the zip's close
on an event date equals reference_price x (the cumulative factor of the events
AFTER that date) - the signature of an already-adjusted series - while the 22
genuine QuantConnect files have zip == reference_price (raw). A second,
independent fingerprint of the writer: yfinance_backfill writes volume as a
float ("98898000.0"), QuantConnect's own zips as an integer.

A zip written by yfinance_backfill needs NO factor adjustment, so
`--repair-adjusted-zips` REMOVES such tickers' files (backing the originals up
first) and generation now skips them. Remove, do not "neutralize": a
sentinel-only identity file (`20501231,1,1,0`) is NOT equivalent to a missing
file for Lean - its zero reference price trips Lean's numerical-precision check
and it logs "data for the following symbols was adjust to a later starting
date: [EMB, 12/30/2050] ...", i.e. the symbol has no data until 2050. That
exact trap sank V5.5.0's first backtest attempt (it was caught in the engine
log of a run that had already crashed for another reason). A missing file is
what every run before #100 used, and works in both Lean and train.py.

Usage:
    python -m data_pipeline.factor_file_backfill [--tickers NVDA GE] [--apply]
    python -m data_pipeline.factor_file_backfill --audit
    python -m data_pipeline.factor_file_backfill --repair-adjusted-zips [--tickers T ...] [--apply]
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import statistics
from pathlib import Path
from zipfile import ZipFile

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
# V5.5.0 - already-adjusted zip detection and repair (see module docstring)
# ---------------------------------------------------------------------------

# Outside factor_files/ on purpose: nothing in the directory Lean reads should be a stray subfolder.
BACKUP_DIR_NAME = "factor_files_backup_pre_v550"


def read_zip_daily_rows(zip_path: Path) -> list[list[str]]:
    """Raw Lean daily CSV rows (`YYYYMMDD 00:00,open,high,low,close,volume`)
    as split string fields. [] for a missing/unreadable zip - never raises."""
    try:
        with ZipFile(zip_path) as archive:
            member = archive.namelist()[0]
            text = archive.read(member).decode("utf-8", errors="replace")
    except (OSError, IndexError, ValueError, KeyError):
        return []
    return [line.split(",") for line in text.splitlines() if line.strip()]


def zip_written_by_yfinance_backfill(rows: list[list[str]], sample_size: int = 50) -> bool:
    """True when the zip's volume column is float-formatted ("98898000.0").
    yfinance_backfill.rows_to_lean_csv() writes a float; QuantConnect's own
    daily zips write an integer ("44109029"). yfinance_backfill fetches with
    auto_adjust=True, so such a zip is split- AND dividend-adjusted already.
    Looks at the first/last `sample_size` rows; any integer-formatted volume
    in the sample means NOT written by the backfill (a merged zip keeps real
    QC rows verbatim - "existing rows always win")."""
    if not rows:
        return False
    sample = rows[:sample_size] + rows[-sample_size:]
    volumes = [row[5] for row in sample if len(row) >= 6]
    return bool(volumes) and all("." in volume for volume in volumes)


def reference_ratio_median(zip_rows: list[list[str]], factor_rows: list[dict], max_events: int = 40) -> float | None:
    """Median of zip_close / reference_price over factor-file event dates that
    exist in the zip. ~1.0 -> the zip is on the factor file's own (raw) scale;
    clearly below 1.0 -> the zip already includes later dividend adjustments.
    None when no event date can be matched."""
    close_by_date = {}
    for row in zip_rows:
        try:
            close_by_date[row[0][:8]] = float(row[4]) / 10000.0
        except (IndexError, ValueError):
            continue
    ratios = []
    for factor_row in factor_rows:
        reference = float(factor_row.get("reference_price") or 0.0)
        close = close_by_date.get(str(factor_row.get("factor_date")))
        if reference > 0.0 and close is not None:
            ratios.append(close / reference)
    return statistics.median(ratios[-max_events:]) if ratios else None


def read_factor_file_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(",")
        if len(parts) < 4:
            continue
        rows.append(
            {
                "factor_date": parts[0],
                "price_factor": float(parts[1]),
                "split_factor": float(parts[2]),
                "reference_price": float(parts[3]),
            }
        )
    return rows


def factor_file_is_identity(factor_rows: list[dict]) -> bool:
    return all(row["price_factor"] == 1.0 and row["split_factor"] == 1.0 for row in factor_rows)


def audit_factor_file(zip_rows: list[list[str]], factor_rows: list[dict]) -> dict:
    """Does a factor file exist for a ticker whose zip is already adjusted?
    ANY such file is wrong: a real one double-adjusts (train.py and Lean both
    re-apply it), and a sentinel-only "identity" one makes Lean start the
    symbol's data in 2050. So `needs_repair` is simply "backfill-written zip
    AND a factor file is present" - the only correct state is no file."""
    from_backfill = zip_written_by_yfinance_backfill(zip_rows)
    event_rows = [row for row in factor_rows if row["factor_date"] != "20501231"]
    identity = factor_file_is_identity(event_rows)
    ratio = reference_ratio_median(zip_rows, event_rows)
    if not from_backfill:
        reason = "zip is not backfill-written (raw QuantConnect data): its factor file is legitimate"
    elif identity and not event_rows:
        reason = "sentinel-only factor file on an adjusted zip: Lean pushes the symbol's data start to 12/30/2050"
    else:
        reason = "yfinance auto_adjust=True zip (already split+dividend adjusted) + a factor file = double adjustment"
    return {
        "zip_written_by_yfinance_backfill": from_backfill,
        "factor_file_is_identity": identity,
        "zip_to_reference_ratio_median": None if ratio is None else round(ratio, 4),
        "needs_repair": bool(from_backfill),
        "reason": reason,
    }


def repair_factor_file(factor_dir: Path, ticker: str, *, apply: bool) -> Path | None:
    """Removes <ticker>.csv after copying it to <factor_dir>/../factor_files_backup_pre_v550/
    (never overwriting an existing backup - the first backup is the true
    original, so repairing an already-neutralized file cannot lose it).
    Returns the backup path when applied, else None."""
    path = factor_dir / f"{ticker.lower()}.csv"
    if not apply:
        return None
    backup_dir = factor_dir.parent / BACKUP_DIR_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / path.name
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
    path.unlink()
    return backup_path


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


def _audit_or_repair(config: dict, args: argparse.Namespace) -> int:
    """--audit / --repair-adjusted-zips, both local-only (no network)."""
    zip_paths = {
        asset["ticker"]: ROOT / asset["data_path"]
        for asset in config.get("phase1", {}).get("universe", {}).get("assets", [])
        if asset.get("security_type") == "equity" and asset.get("data_path")
    }
    tickers = args.tickers if args.tickers else sorted(zip_paths)
    repaired = flagged = 0
    for ticker in tickers:
        factor_path = args.output_dir / f"{ticker.lower()}.csv"
        if not factor_path.exists() or ticker not in zip_paths:
            continue
        verdict = audit_factor_file(read_zip_daily_rows(zip_paths[ticker]), read_factor_file_rows(factor_path))
        if verdict["needs_repair"]:
            flagged += 1
        if args.repair_adjusted_zips and verdict["needs_repair"]:
            backup = repair_factor_file(args.output_dir, ticker, apply=args.apply)
            repaired += 1 if args.apply else 0
            status = f"repaired (backup: {backup})" if args.apply else "would_repair"
        else:
            status = "DOUBLE-ADJUSTED" if verdict["needs_repair"] else "ok"
        print(f"- {ticker}: {status} ratio={verdict['zip_to_reference_ratio_median']} {verdict['reason']}")
    print(f"\n{flagged} double-adjusted factor file(s) found; {repaired} repaired.")
    if args.repair_adjusted_zips and not args.apply and flagged:
        print("Dry run only - re-run with --apply to rewrite them (originals are backed up first).")
    return 0 if (args.repair_adjusted_zips or not flagged) else 1


def main() -> int:
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
    parser.add_argument(
        "--audit", action="store_true",
        help="V5.5.0: report, per configured equity with a factor file, whether it sits on top of an "
        "already-adjusted (yfinance auto_adjust=True) zip - the double-adjustment / 2050-start trap of Problems.md #130. Read-only; exit 1 on a finding.",
    )
    parser.add_argument(
        "--repair-adjusted-zips", action="store_true",
        help="V5.5.0: remove the factor file of every ticker whose zip is already split+dividend adjusted "
        "(originals backed up to <output-dir>/../factor_files_backup_pre_v550/). Dry run unless --apply.",
    )
    args = parser.parse_args()

    with args.config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    if args.audit or args.repair_adjusted_zips:
        return _audit_or_repair(config, args)

    tickers = args.tickers if args.tickers else tickers_missing_factor_file(configured_equity_tickers(config), args.output_dir)

    zip_paths = {
        asset["ticker"]: ROOT / asset["data_path"]
        for asset in config.get("phase1", {}).get("universe", {}).get("assets", [])
        if asset.get("data_path")
    }
    print(f"{'APPLY' if args.apply else 'DRY RUN'} — checking corporate-action history for {len(tickers)} ticker(s):\n")
    for ticker in tickers:
        # V5.5.0: a yfinance_backfill-written zip is already split+dividend adjusted; generating a
        # factor file for it re-applies every correction (Problems.md #130).
        zip_rows = read_zip_daily_rows(zip_paths[ticker]) if ticker in zip_paths else []
        if zip_written_by_yfinance_backfill(zip_rows):
            print(f"- {ticker}: skipped_zip_already_adjusted (yfinance auto_adjust=True zip needs no factor file)")
            continue
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
