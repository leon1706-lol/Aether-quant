"""Derive each crypto pair's Coinbase listing date and trading suspensions from the exchange's own daily candles (V5.8.0).

A backtest that trades a pair before the exchange listed it (or while trading was suspended - Coinbase halted XRP from
January 2021 to July 2023) books returns no live account could have earned. Search engines carry no reliable listing
history, so this reads the public Coinbase Exchange candles endpoint (no key needed): the first daily candle is the
first traded day, and a run of missing days longer than `--min-gap-days` is a suspension. The result feeds
`risk/asset_class_router.py::asset_listed_on_venue` via `data/reference/crypto_listing_dates.json`.

    python scripts/coinbase_listing_dates.py [--start 2014-01-01] [--end 2026-10-01] [--apply]

Dry run by default (prints the table, writes nothing).
"""

from __future__ import annotations

import argparse
import json
import sys
import time as _time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
API = "https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400&start={start}&end={end}"
MAX_CANDLES = 300


def product_id(ticker: str) -> str:
    return f"{ticker[:-3]}-{ticker[-3:]}"


def fetch_candle_days(product: str, start: date, end: date, *, pause: float = 0.35) -> list[date]:
    """Every UTC day with a daily candle in [start, end)."""
    days: set[date] = set()
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=MAX_CANDLES - 1), end)
        url = API.format(product=product, start=cursor.isoformat(), end=chunk_end.isoformat())
        request = urllib.request.Request(url, headers={"User-Agent": "aether-quant-listing-audit"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except Exception:
                if attempt == 3:
                    raise
                _time.sleep(2.0 * (attempt + 1))
        if isinstance(payload, list):
            for candle in payload:
                days.add(datetime.fromtimestamp(int(candle[0]), tz=timezone.utc).date())
        cursor = chunk_end + timedelta(days=1)
        _time.sleep(pause)
    return sorted(days)


def listing_entry(days: list[date], *, min_gap_days: int, end: date | None = None) -> dict:
    """{"listed", "last", "suspended": [[gap_start, gap_end_exclusive], ...], "delisted"} from the traded days. A pair
    whose last candle is more than `min_gap_days` before `end` is delisted from the day after it."""
    if not days:
        return {"listed": None, "last": None, "suspended": [], "delisted": None}
    gaps = []
    for previous, current in zip(days, days[1:]):
        if (current - previous).days > min_gap_days:
            gaps.append([(previous + timedelta(days=1)).isoformat(), current.isoformat()])
    delisted = None
    if end is not None and (end - days[-1]).days > min_gap_days:
        delisted = (days[-1] + timedelta(days=1)).isoformat()
    return {"listed": days[0].isoformat(), "last": days[-1].isoformat(), "suspended": gaps, "delisted": delisted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--end", default="2026-10-01")
    parser.add_argument("--min-gap-days", type=int, default=7)
    parser.add_argument("--output", default=str(ROOT_DIR / "data" / "reference" / "crypto_listing_dates.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    tickers = [a["ticker"] for a in config["phase1"]["universe"]["assets"] if a.get("security_type") == "crypto"]
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    assets = {}
    for ticker in tickers:
        days = fetch_candle_days(product_id(ticker), start, end)
        assets[ticker] = listing_entry(days, min_gap_days=args.min_gap_days, end=end)
        print(f"{ticker:8s} listed {assets[ticker]['listed']} last {assets[ticker]['last']} suspended {assets[ticker]['suspended']} delisted {assets[ticker]['delisted']}")
    if args.apply:
        payload = {
            "source": "Coinbase Exchange public daily candles (api.exchange.coinbase.com/products/<pair>/candles), "
                      f"first candle = listing, gaps > {args.min_gap_days} days = suspension; built by scripts/coinbase_listing_dates.py",
            "built_on": date.today().isoformat(),
            "assets": assets,
        }
        Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"written {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
