"""Which coins in data_crypto_wide carry a price break no market move explains (a redenomination or token swap spliced into one Binance pair),
and did a V6.6.0 crypto book hold one across it? Reads prices and the recorded weights' tickers only; scores nothing.

    python scripts/v660_crypto_splices.py
"""

from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_pipeline.binance_archive import price_breaks  # noqa: E402

DAILY = ROOT / "data_crypto_wide" / "crypto" / "coinbase" / "daily"
OUT = ROOT / "ml" / "evaluation" / "v660" / "crypto_price_breaks.json"


def closes_of(path: Path) -> dict[str, float]:
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            rows = list(csv.reader(io.TextIOWrapper(handle, encoding="utf-8")))
    return {f"{row[0][:4]}-{row[0][4:6]}-{row[0][6:8]}": float(row[4]) for row in rows}


def main() -> int:
    breaks = {}
    coins = sorted(DAILY.glob("*_trade.zip"))
    for path in coins:
        found = price_breaks(closes_of(path))
        if found:
            breaks[path.name.split("_")[0].upper()] = found
    report = {"coins": len(coins), "coins_with_a_break": len(breaks), "breaks": breaks}
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({"coins": len(coins), "coins_with_a_break": len(breaks)}))
    for ticker, found in sorted(breaks.items()):
        print(ticker, [(row["from"], row["to"], round(row["ratio"], 4)) for row in found][:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
