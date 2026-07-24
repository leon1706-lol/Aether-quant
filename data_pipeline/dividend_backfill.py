"""Dividend ex-date/amount history backfill + forward cadence-based
projection - powers portfolio/options_assignment_risk.py's early-
call-assignment signal (development/Problems.md - early-assignment
probability/pricing modeling).

No dividend $ amounts/ex-div dates/schedule exist anywhere else in this
codebase - data_pipeline/fred_backfill.py only pulls Treasury yield/credit-
spread series, and data_pipeline/yfinance_backfill.py's auto_adjust=True
OHLCV downloads discard raw dividend events before they ever reach a Lean
zip. This module fetches actual historical ex-dividend dates/amounts via
yfinance (dev-only dependency, deferred import - mirrors
yfinance_backfill.py's own convention) and derives a best-effort FORWARD
projection from historical cadence - NOT yfinance's own forward
Ticker.calendar/get_earnings_dates fields, which are scraped from Yahoo's
UI and empirically unreliable/frequently stale or absent for less-followed
tickers. This is a deliberate accuracy-over-completeness choice; every
consumer must treat the projection as a best-effort estimate, never a
confirmed date (see estimate_next_ex_dividend_date()'s own
"confidence"/"method" fields).

Same two-safety-boundary shape as fred_backfill.py/yfinance_backfill.py:
1. Writing the local cache is gated by --apply (default: dry run only).
2. Never touches config.json - this module's only output is
   data/reference/dividend_schedule/*.json, read back once at main.py
   init (Lean backtests are date-bounded and must never make a live HTTP
   call mid-run) - refreshed by re-running this module with --apply, not
   intraday.

Usage:
    python -m data_pipeline.dividend_backfill [--tickers AAPL MSFT] [--apply]
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
DIVIDEND_SCHEDULE_CACHE_DIR = ROOT / "data" / "reference" / "dividend_schedule"

MIN_HISTORY_EVENTS_FOR_ESTIMATE = 2
CADENCE_LOOKBACK_EVENTS = 8


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def estimate_next_ex_dividend_date(history: list[dict], as_of: date) -> dict:
    """Pure. Projects the next ex-div date from historical CADENCE (median
    days between consecutive ex_dates over the trailing
    CADENCE_LOOKBACK_EVENTS events), rolled forward from the most recent
    ex_date <= as_of - NOT a yfinance forward-calendar call (see module
    docstring). Returns {"estimated_next_ex_date": iso-date | None,
    "estimated_amount": float | None, "cadence_days": int | None,
    "confidence": "low"|"medium"|"none", "method": str}.

    "none" confidence (every numeric field None) when fewer than
    MIN_HISTORY_EVENTS_FOR_ESTIMATE events are available as-of as_of - an
    unknown schedule must never be indistinguishable from a genuinely "no
    dividend expected" signal, the same None-vs-neutral-default
    distinction every other pure signal function in this codebase draws.
    "medium" only with a reasonably regular cadence over enough lookback
    events; "low" otherwise. Never raises."""
    past_events = sorted(
        (event for event in history if event.get("ex_date") is not None and event["ex_date"] <= as_of),
        key=lambda event: event["ex_date"],
    )
    if len(past_events) < MIN_HISTORY_EVENTS_FOR_ESTIMATE:
        return {
            "estimated_next_ex_date": None,
            "estimated_amount": None,
            "cadence_days": None,
            "confidence": "none",
            "method": "insufficient_history",
        }

    lookback = past_events[-CADENCE_LOOKBACK_EVENTS:]
    gaps = [(lookback[i]["ex_date"] - lookback[i - 1]["ex_date"]).days for i in range(1, len(lookback))]
    cadence_days = max(round(statistics.median(gaps)), 1)
    most_recent = lookback[-1]
    estimated_next = most_recent["ex_date"]
    # Roll forward past `as_of` by whole cadence steps - handles a stale
    # cache (as_of well past the last known event) without ever guessing a
    # date already in the past.
    while estimated_next <= as_of:
        estimated_next = date.fromordinal(estimated_next.toordinal() + cadence_days)

    spread = (max(gaps) - min(gaps)) if len(gaps) > 1 else 0
    confidence = "medium" if len(gaps) >= 3 and spread <= 15 else "low"

    return {
        "estimated_next_ex_date": estimated_next.isoformat(),
        "estimated_amount": most_recent["amount"],
        "cadence_days": cadence_days,
        "confidence": confidence,
        "method": "historical_cadence_projection - not a confirmed forward date",
    }


def dividend_schedule_payload(ticker: str, history: list[dict], as_of: date) -> dict:
    """Composes fetch_dividend_history()'s raw history +
    estimate_next_ex_dividend_date()'s projection into the exact shape
    write_dividend_schedule() persists / main.py reads back."""
    estimate = estimate_next_ex_dividend_date(history, as_of)
    return {
        "ticker": ticker,
        "fetched_at": as_of.isoformat(),
        "history": [{"ex_date": event["ex_date"].isoformat(), "amount": event["amount"]} for event in history],
        "next_ex_dividend_estimate": estimate,
    }


def option_underlying_tickers(config: dict) -> list[str]:
    """Every ticker this module is actually useful for: an option asset's
    underlying_ticker, or an equity asset's own ticker directly. Pure,
    de-duplicated, order-preserving, never raises on a malformed asset
    entry (missing keys just get skipped)."""
    tickers: list[str] = []
    seen: set[str] = set()
    for asset in config.get("phase1", {}).get("universe", {}).get("assets", []):
        security_type = asset.get("security_type")
        ticker = asset.get("underlying_ticker") if security_type == "option" else asset.get("ticker")
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


# ---------------------------------------------------------------------------
# The only function that imports yfinance - deferred, mirrors
# yfinance_backfill.py's own convention.
# ---------------------------------------------------------------------------


def fetch_dividend_history(yahoo_symbol: str) -> list[dict]:
    """Real historical ex-dividend dates + per-share amounts via
    yfinance.Ticker(yahoo_symbol).dividends. Returns [] on any fetch
    failure (network, delisted, no dividend history) - never raises, same
    fail-open convention as yfinance_backfill.fetch_yahoo_ohlcv()."""
    try:
        import yfinance as yf  # deferred - dev-only dependency, never in requirements.txt

        series = yf.Ticker(yahoo_symbol).dividends
    except Exception as exc:
        logger.warning("fetch_dividend_history(%s): fetch failed — %s", yahoo_symbol, exc)
        return []

    if series is None or series.empty:
        logger.warning("fetch_dividend_history(%s): no dividend history returned", yahoo_symbol)
        return []

    rows = []
    for index, amount in series.items():
        row_date = index.date() if hasattr(index, "date") else index
        rows.append({"ex_date": row_date, "amount": float(amount)})
    return sorted(rows, key=lambda row: row["ex_date"])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def write_dividend_schedule(cache_dir: Path, ticker: str, history: list[dict], as_of: date) -> dict:
    """Writes data/reference/dividend_schedule/<ticker>.json. Returns the
    payload written (for CLI reporting)."""
    payload = dividend_schedule_payload(ticker, history, as_of)
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir / f"{ticker}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_cached_dividend_schedule(ticker: str, cache_dir: Path = DIVIDEND_SCHEDULE_CACHE_DIR) -> dict:
    """Reads back data/reference/dividend_schedule/<ticker>.json. Returns
    {} when missing/unreadable (fresh clone, backfill never run for this
    ticker) - callers (main.py) must treat an empty dict as "no dividend
    schedule known", never a crash, same convention as
    fred_backfill.load_cached_fred_series()."""
    path = cache_dir / f"{ticker}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        logger.warning("load_cached_dividend_schedule(%s): unreadable cache file — %s", ticker, exc)
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    parser = argparse.ArgumentParser(
        description="Aether Quant dividend history backfill - offline/manual only, "
        "no API key required, never run inside Lean or a Docker worker."
    )
    parser.add_argument(
        "--tickers", nargs="*", default=None, help="Restrict to these tickers (default: every option underlying/equity in phase1.universe.assets)"
    )
    parser.add_argument("--apply", action="store_true", help="Actually write the local cache (default: dry run, report only)")
    parser.add_argument("--config-path", type=Path, default=CONFIG_PATH)
    parser.add_argument("--cache-dir", type=Path, default=DIVIDEND_SCHEDULE_CACHE_DIR)
    args = parser.parse_args()

    with args.config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    tickers = args.tickers if args.tickers else option_underlying_tickers(config)
    as_of = date.today()

    print(f"{'APPLY' if args.apply else 'DRY RUN'} — fetching dividend history for {len(tickers)} ticker(s):\n")
    for ticker in tickers:
        history = fetch_dividend_history(ticker)
        if not history:
            print(f"- {ticker}: no_data_returned, events_fetched=0")
            continue
        payload = dividend_schedule_payload(ticker, history, as_of)
        if args.apply:
            write_dividend_schedule(args.cache_dir, ticker, history, as_of)
            action = "written"
        else:
            action = "dry_run"
        print(f"- {ticker}: {action}, events_fetched={len(history)}, next_ex_estimate={payload['next_ex_dividend_estimate']}")

    if not args.apply:
        print("\nDry run only — no cache files were written. Re-run with --apply to write the cache.")


if __name__ == "__main__":
    main()
