"""Daily bars from Coinbase's public candles, with no key, no account and no extra package (V6.6.5, #343).

The endpoint returns at most 300 rows per call, newest first, each `[time, low, high, open, close, volume]`. A coin is fetched
one window at a time and one coin at a time; a coin whose fetch fails is named and left out, so one delisted product never
voids the rest. Only closed bars are kept: a bar dated today (UTC) is still forming. Results are cached as CSV so a second
run is offline. The parsing and windowing are pure; the network is an injected `get_json`.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400&start={start}&end={end}"
USER_AGENT = "AetherQuantResearch/6.6 (github.com/leon1706-lol/Aether-quant)"
MAX_ROWS = 300
COLUMNS = ("date", "open", "high", "low", "close", "volume")
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "aether-quant" / "candles"

GetJson = Callable[[str], object]


def coinbase_product(ticker: str) -> str:
    """`BTCUSD` -> `BTC-USD`; a ticker that already has a dash is returned as it is."""
    text = str(ticker).upper()
    return text if "-" in text else f"{text[:-3]}-{text[-3:]}"


def candle_windows(start: date, end: date, max_rows: int = MAX_ROWS) -> list[tuple[date, date]]:
    """Inclusive [start, end] cut into windows of at most `max_rows - 1` days, oldest first (one spare row of headroom)."""
    if end < start:
        return []
    span = max(int(max_rows) - 1, 1)
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=span - 1), end)
        windows.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return windows


def candles_url(product: str, start: date, end: date) -> str:
    """The Coinbase public candles URL for one product and an inclusive day window, daily granularity."""
    return COINBASE_CANDLES_URL.format(product=product, start=f"{start.isoformat()}T00:00:00Z", end=f"{end.isoformat()}T23:59:59Z")


def parse_candles(rows: object) -> pd.DataFrame:
    """Rows to a frame with columns `date, open, high, low, close, volume`, ascending by date. Drops malformed, non-finite,
    non-positive-price and duplicate rows (the first of a duplicated date is kept)."""
    records: list[dict[str, object]] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                stamp = int(float(row[0]))
                low, high, open_, close, volume = (float(value) for value in row[1:6])
            except (TypeError, ValueError, OverflowError):
                continue
            prices = (open_, high, low, close)
            if not all(np.isfinite(value) and value > 0.0 for value in prices) or not np.isfinite(volume):
                continue
            day = datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d")
            records.append({"date": day, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
    frame = pd.DataFrame(records, columns=list(COLUMNS))
    if frame.empty:
        return frame
    return frame.drop_duplicates("date", keep="first").sort_values("date").reset_index(drop=True)


def default_get_json(url: str, *, timeout: float = 20.0, retries: int = 3, backoff: float = 1.5) -> object:
    """GET a JSON document with the standard library. Retries a transient failure with exponential backoff."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    error: Exception | None = None
    for attempt in range(max(int(retries), 1)):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https host)
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            error = exc
            if attempt + 1 < retries:
                time.sleep(backoff ** attempt)
    raise ConnectionError(f"public candles fetch failed: {error}")


def _read_cache(cache_dir: Path, ticker: str) -> tuple[pd.DataFrame, dict[str, str]] | None:
    data, meta = cache_dir / f"{ticker}.csv", cache_dir / f"{ticker}.json"
    if not data.is_file() or not meta.is_file():
        return None
    try:
        frame = pd.read_csv(data, dtype={"date": str})
        info = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if list(frame.columns) != list(COLUMNS) or not isinstance(info, dict):
        return None
    return frame, {str(key): str(value) for key, value in info.items()}


def _write_cache(cache_dir: Path, ticker: str, frame: pd.DataFrame, start: date, end: date) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        frame.to_csv(cache_dir / f"{ticker}.csv", index=False, quoting=csv.QUOTE_MINIMAL)
        (cache_dir / f"{ticker}.json").write_text(json.dumps({"start": start.isoformat(), "end": end.isoformat()}), encoding="utf-8")
    except OSError:
        pass  # a read-only home only costs the next run a download


def fetch_daily_bars(
    tickers: Sequence[str], start: date, end: date, *, get_json: GetJson = default_get_json, cache_dir: Path | None = DEFAULT_CACHE_DIR,
    today: date | None = None,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """({ticker: bars}, failed tickers). Bars cover [start, min(end, yesterday)] and never include today's forming bar.
    A cache written for an earlier-or-equal start and a later-or-equal end is reused without a call."""
    today = today or datetime.now(timezone.utc).date()
    last_closed = min(end, today - timedelta(days=1))
    bars: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    for ticker in tickers:
        if cache_dir is not None:
            cached = _read_cache(Path(cache_dir), ticker)
            if cached is not None:
                frame, info = cached
                if info.get("start", "9999") <= start.isoformat() and info.get("end", "") >= last_closed.isoformat():
                    bars[ticker] = frame[(frame["date"] >= start.isoformat()) & (frame["date"] <= last_closed.isoformat())].reset_index(drop=True)
                    continue
        try:
            parts = [parse_candles(get_json(candles_url(coinbase_product(ticker), lo, hi))) for lo, hi in candle_windows(start, last_closed)]
        except Exception:  # noqa: BLE001 - any failure of one coin is named, never fatal
            failed.append(ticker)
            continue
        frame = pd.concat([part for part in parts if not part.empty], ignore_index=True) if any(not part.empty for part in parts) else parse_candles([])
        if not frame.empty:
            frame = frame.drop_duplicates("date", keep="first").sort_values("date")
            frame = frame[(frame["date"] >= start.isoformat()) & (frame["date"] <= last_closed.isoformat())].reset_index(drop=True)
        if frame.empty:
            failed.append(ticker)
            continue
        bars[ticker] = frame
        if cache_dir is not None:
            _write_cache(Path(cache_dir), ticker, frame, start, last_closed)
    return bars, failed


def bars_to_panel(bars: dict[str, pd.DataFrame], field: str = "close") -> pd.DataFrame:
    """{ticker: bars} to a dates x tickers frame of one field, indexed by `YYYY-MM-DD` strings, NaN where a coin has no bar."""
    if field not in COLUMNS[1:]:
        raise ValueError(f"field must be one of {COLUMNS[1:]}")
    columns = {ticker: frame.set_index("date")[field].astype(float) for ticker, frame in bars.items() if not frame.empty}
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(columns).sort_index()
