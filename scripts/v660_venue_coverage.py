"""Which public, no-account sources serve daily bars for the sleeve's 12 coins, and how far back (V6.6.0, Problems.md #192).

IB's crypto contracts and TradeStation's crypto can't be read here: both need an account this project doesn't have (lean.json holds none for IB, Kraken,
Coinbase or Alpaca). This checks only what answers without one: Coinbase, Kraken and Binance public endpoints. Writes ml/evaluation/v660/venue_data_coverage.json.

    python scripts/v660_venue_coverage.py
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ml" / "evaluation" / "v660" / "venue_data_coverage.json"
COINS = ("BTC", "ETH", "LTC", "XRP", "ADA", "BCH", "LINK", "DOGE", "XLM", "EOS", "ETC", "ZEC")
KRAKEN_NAME = {"BTC": "XBT"}
HEADERS = {"User-Agent": "AetherQuantResearch/6.6 (github.com/leon1706-lol/Aether-quant)"}


def get(url: str, **params):
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=30)
        except requests.RequestException:
            time.sleep(2.0)
            continue
        if response.status_code == 429:
            time.sleep(3.0 * (attempt + 1))
            continue
        return response
    return None


def day(stamp) -> str:
    return datetime.datetime.fromtimestamp(int(stamp), datetime.timezone.utc).strftime("%Y-%m-%d")


def coinbase(coin: str) -> dict:
    response = get(f"https://api.exchange.coinbase.com/products/{coin}-USD/candles", granularity=86400)
    if response is None or response.status_code != 200:
        return {"status": None if response is None else response.status_code}
    rows = response.json()
    return {"status": 200, "bars": len(rows), "first": day(rows[-1][0]) if rows else None, "last": day(rows[0][0]) if rows else None, "per_call_limit": 300}


def kraken(coin: str) -> dict:
    pair = f"{KRAKEN_NAME.get(coin, coin)}USD"
    response = get("https://api.kraken.com/0/public/OHLC", pair=pair, interval=1440)
    if response is None or response.status_code != 200:
        return {"status": None if response is None else response.status_code}
    body = response.json()
    if body.get("error"):
        return {"status": 200, "error": body["error"][0]}
    rows = next(value for key, value in body["result"].items() if key != "last")
    return {"status": 200, "bars": len(rows), "first": day(rows[0][0]), "last": day(rows[-1][0]), "per_call_limit": 720}


def binance(coin: str) -> dict:
    listing = get("https://data-api.binance.vision/api/v3/klines", symbol=f"{coin}USDT", interval="1d", startTime=1502928000000, limit=1000)
    if listing is None or listing.status_code != 200:
        return {"status": None if listing is None else listing.status_code}
    rows = listing.json()
    return {"status": 200, "first": day(rows[0][0] / 1000) if rows else None, "per_call_limit": 1000, "archive": "data.binance.vision, monthly zips back to the listing"}


def main() -> int:
    report = {"checked": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "coins": {}}
    for coin in COINS:
        report["coins"][coin] = {"coinbase": coinbase(coin), "kraken": kraken(coin), "binance": binance(coin)}
        print(coin, {venue: (entry.get("first") or entry.get("error") or entry.get("status")) for venue, entry in report["coins"][coin].items()}, flush=True)
        time.sleep(0.5)
    report["note"] = (
        "Coinbase serves 300 daily bars a call (paged by start/end), Kraken 720 of the newest, Binance's archive everything since listing. "
        "None needs an account. Not tested: IB (needs a paper account and a running Gateway), TradeStation (its API documents stocks, options and futures only)."
    )
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
