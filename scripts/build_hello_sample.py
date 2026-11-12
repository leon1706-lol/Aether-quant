"""Build the sample `aq hello --offline` and the notebooks read (V6.6.5, #343): the shipped book's 11 coins, daily open and
close from Coinbase's public candles, 2021-06-01 to 2026-10-31, gzip with a zero mtime so a rebuild is byte-identical.

    python scripts/build_hello_sample.py            # fetch and write aether_quant/_sample/
    python scripts/build_hello_sample.py --check    # verify the tracked file against its README sha256
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_pipeline.public_candles import fetch_daily_bars  # noqa: E402

SAMPLE_DIR = ROOT / "aether_quant" / "_sample"
SAMPLE = SAMPLE_DIR / "coinbase_daily.csv.gz"
README = SAMPLE_DIR / "README.md"
TICKERS = ("ADAUSD", "BCHUSD", "BTCUSD", "DOGEUSD", "ETCUSD", "ETHUSD", "LINKUSD", "LTCUSD", "XLMUSD", "XRPUSD", "ZECUSD")
START, END = date(2021, 6, 1), date(2026, 10, 31)


def _fmt(value: float) -> str:
    return f"{float(value):.8g}"


def sample_bytes(bars: dict) -> bytes:
    lines = ["date,ticker,open,close"]
    rows = sorted((row.date, ticker, row.open, row.close) for ticker, frame in bars.items() for row in frame.itertuples(index=False))
    lines += [f"{day},{ticker},{_fmt(open_)},{_fmt(close)}" for day, ticker, open_, close in rows]
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as handle:
        handle.write(("\n".join(lines) + "\n").encode("utf-8"))
    return buffer.getvalue()


def readme_text(digest: str, rows: int) -> str:
    return (
        "# Sample data for `aq hello` and the notebooks\n\n"
        f"- **File:** `coinbase_daily.csv.gz`, {rows} rows, columns `date,ticker,open,close` (8 significant figures).\n"
        f"- **Coins:** {', '.join(TICKERS)}: the shipped book's universe.\n"
        f"- **Window:** {START.isoformat()} to {END.isoformat()}, daily bars in UTC. XRP-USD trades on Coinbase only from 2023-07-13.\n"
        "- **Source:** Coinbase Exchange public candles (`api.exchange.coinbase.com/products/<id>/candles`), no key. Prices are factual market data, "
        "kept here only so the demo runs offline.\n"
        "- **Rebuild:** `python scripts/build_hello_sample.py` (byte-identical for the same data); `--check` verifies the digest.\n"
        f"- **sha256:** `{digest}`\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        digest = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
        ok = f"`{digest}`" in README.read_text(encoding="utf-8")
        print(f"sample sha256 {digest}: {'matches' if ok else 'DIFFERS from'} README")
        return 0 if ok else 1
    bars, failed = fetch_daily_bars(TICKERS, START, END, cache_dir=None, today=date(2026, 11, 8))
    if failed:
        print(f"failed coins: {failed}", file=sys.stderr)
        return 1
    payload = sample_bytes(bars)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_bytes(payload)
    rows = sum(len(frame) for frame in bars.values())
    README.write_text(readme_text(hashlib.sha256(payload).hexdigest(), rows), encoding="utf-8", newline="\n")
    print(f"wrote {SAMPLE.relative_to(ROOT)}: {rows} rows, {len(payload) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
