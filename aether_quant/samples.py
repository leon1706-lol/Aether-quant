"""The sample market data that ships with the library (V6.6.5): the shipped book's 11 coins, daily open and close from
Coinbase's public candles, 2021-06-01 to 2026-10-31. Offline, deterministic, and enough for `aq hello` and the notebooks.

    from aether_quant import samples
    closes = samples.load_sample_prices()          # dates x tickers
    opens = samples.load_sample_prices("open")
"""

from __future__ import annotations

import gzip
import hashlib
import io
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd

SAMPLE_PATH = Path(__file__).resolve().parent / "_sample" / "coinbase_daily.csv.gz"
SAMPLE_README = SAMPLE_PATH.parent / "README.md"

__all__ = ["SAMPLE_PATH", "load_sample_bars", "load_sample_prices", "sample_info"]


@lru_cache(maxsize=1)
def _long_frame() -> pd.DataFrame:
    with gzip.open(SAMPLE_PATH, "rb") as handle:
        return pd.read_csv(io.BytesIO(handle.read()), dtype={"date": str, "ticker": str})


def load_sample_bars() -> pd.DataFrame:
    """The sample in long format: columns `date, ticker, open, close`, sorted by date then ticker. A copy, safe to edit."""
    return _long_frame().copy()


def load_sample_prices(field: Literal["open", "close"] = "close") -> pd.DataFrame:
    """One field as a dates x tickers frame indexed by `YYYY-MM-DD` strings; NaN before a coin's first bar."""
    if field not in ("open", "close"):
        raise ValueError("field must be 'open' or 'close'")
    return _long_frame().pivot(index="date", columns="ticker", values=field).sort_index().astype(float)


def sample_info() -> dict[str, str]:
    """Where the sample came from: path, window, coins, row count and sha256."""
    frame = _long_frame()
    return {
        "path": str(SAMPLE_PATH),
        "source": "Coinbase Exchange public candles (no key)",
        "start": str(frame["date"].min()),
        "end": str(frame["date"].max()),
        "tickers": ",".join(sorted(frame["ticker"].unique())),
        "rows": str(len(frame)),
        "sha256": hashlib.sha256(SAMPLE_PATH.read_bytes()).hexdigest(),
    }
