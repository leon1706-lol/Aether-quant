"""Binance's public archive, data.binance.vision (V6.6.0, free, no account): every USDT spot pair, delisted ones included.

The project's 12 coins are survivors, so nothing yet says what a crypto rule does on coins that later died. The archive keeps
LUNA and FTT, so it can. Spot daily klines from 2017-08, perpetual funding rates from 2019-09.

This is research data on a venue the book doesn't trade: blocking costs stay Coinbase's.
"""

from __future__ import annotations

import csv
import io
import math
import re
import xml.etree.ElementTree as ElementTree
import zipfile
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

LISTING_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
ARCHIVE_URL = "https://data.binance.vision"
KLINE_PREFIX = "data/spot/monthly/klines/"
FUNDING_PREFIX = "data/futures/um/monthly/fundingRate/"
STABLE_BASES = frozenset({
    "USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD", "USDS", "USDSB", "SUSD", "GUSD", "EUR", "GBP", "AUD", "BRL", "TRY", "USDD",
    "EURI", "AEUR", "UST", "USTC", "XUSD", "RLUSD", "PYUSD", "USD1", "BFUSD", "UUSD", "USDE", "IDRT", "BIDR", "BVND",
})
LEVERAGED_TOKEN = re.compile(r"(UP|DOWN|BULL|BEAR)$")
S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def list_symbols(get_text: Callable[[str], str], prefix: str = KLINE_PREFIX) -> list[str]:
    """Every folder under `prefix`, following the listing's pages: it returns 1,000 entries at a time, and stopping at the first
    page would silently lose most of the alphabet."""
    symbols: list[str] = []
    marker = ""
    while True:
        url = f"{LISTING_URL}?delimiter=/&prefix={prefix}" + (f"&marker={marker}" if marker else "")
        root = ElementTree.fromstring(get_text(url))
        names = [
            element.findtext(f"{S3_NAMESPACE}Prefix") or ""
            for element in root.findall(f"{S3_NAMESPACE}CommonPrefixes")
        ]
        symbols.extend(name[len(prefix):].rstrip("/") for name in names if name != prefix)
        truncated = (root.findtext(f"{S3_NAMESPACE}IsTruncated") or "false").lower() == "true"
        if not truncated:
            return sorted(set(symbols))
        marker = root.findtext(f"{S3_NAMESPACE}NextMarker") or (names[-1] if names else "")
        if not marker:
            return sorted(set(symbols))


def base_asset(symbol: str) -> str | None:
    """LUNAUSDT -> LUNA. None for a pair this phase doesn't use: not quoted in USDT, a stablecoin, a leveraged token."""
    if not symbol.endswith("USDT"):
        return None
    base = symbol[:-4]
    if not base or base in STABLE_BASES or LEVERAGED_TOKEN.search(base):
        return None
    return base


def _timestamp_date(value: str) -> str:
    """Binance moved spot files from milliseconds to microseconds in 2025. Telling them apart by size keeps both right."""
    number = int(value)
    while number > 10**13:
        number //= 1000
    return datetime.fromtimestamp(number / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def parse_kline_zip(payload: bytes) -> list[dict]:
    """{date, open, high, low, close, volume, quote_volume} from one monthly file. Some files have a header row and some don't."""
    rows: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            with archive.open(name) as handle:
                for record in csv.reader(io.TextIOWrapper(handle, encoding="utf-8")):
                    if not record or not record[0].strip().isdigit():
                        continue
                    close, volume, quote_volume = float(record[4]), float(record[5]), float(record[7])
                    if close <= 0.0:
                        continue
                    rows.append({
                        "date": _timestamp_date(record[0]), "open": float(record[1]), "high": float(record[2]), "low": float(record[3]),
                        "close": close, "volume": volume, "quote_volume": quote_volume,
                    })
    return rows


def parse_funding_zip(payload: bytes) -> list[tuple[str, float]]:
    """(date, rate) per settlement from one monthly file: calc_time,funding_interval_hours,last_funding_rate."""
    out: list[tuple[str, float]] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            with archive.open(name) as handle:
                for record in csv.reader(io.TextIOWrapper(handle, encoding="utf-8")):
                    if not record or not record[0].strip().isdigit():
                        continue
                    out.append((_timestamp_date(record[0]), float(record[-1])))
    return out


def daily_funding(settlements: list[tuple[str, float]]) -> dict[str, float]:
    """A day's funding is the sum of its settlements: what a long position pays that day."""
    totals: dict[str, float] = {}
    for date, rate in settlements:
        totals[date] = totals.get(date, 0.0) + rate
    return totals


def months_between(start: str, end: str) -> list[str]:
    """YYYY-MM from `start` to `end`, inclusive."""
    months = pd.period_range(start[:7], end[:7], freq="M")
    return [str(month) for month in months]


def kline_url(symbol: str, month: str) -> str:
    return f"{ARCHIVE_URL}/{KLINE_PREFIX}{symbol}/1d/{symbol}-1d-{month}.zip"


def funding_url(symbol: str, month: str) -> str:
    return f"{ARCHIVE_URL}/{FUNDING_PREFIX}{symbol}/{symbol}-fundingRate-{month}.zip"


def listed_months(get_text: Callable[[str], str], prefix: str) -> list[str] | None:
    """The YYYY-MM of every file under `prefix`, or None if the listing holds none: then the caller tries every month. A pair has files only for
    the months it traded, so asking first saves most of the requests."""
    root = ElementTree.fromstring(get_text(f"{LISTING_URL}?prefix={prefix}&max-keys=1000"))
    keys = [element.findtext(f"{S3_NAMESPACE}Key") or "" for element in root.findall(f"{S3_NAMESPACE}Contents")]
    months = sorted({match.group(1) for key in keys if key.endswith(".zip") and (match := re.search(r"-(\d{4}-\d{2})\.zip$", key))})
    return months or None


def fetch_series(
    url_for: Callable[[str, str], str], parse: Callable[[bytes], list], symbol: str, start: str, end: str,
    get_bytes: Callable[[str], bytes | None], *, months: list[str] | None = None, workers: int = 8,
) -> list:
    """Every month's rows, in month order, fetched by a few threads: the archive is a static CDN, and one at a time takes hours. A missing month is
    normal (a pair lists late, or has died), so `get_bytes` returns None for a 404."""
    from concurrent.futures import ThreadPoolExecutor

    wanted = [month for month in (months if months is not None else months_between(start, end)) if start[:7] <= month <= end[:7]]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        payloads = list(pool.map(lambda month: get_bytes(url_for(symbol, month)), wanted))
    rows: list = []
    for payload in payloads:
        if payload:
            rows.extend(parse(payload))
    return rows


def price_breaks(closes: Mapping[str, float], *, ratio: float = 10.0) -> list[dict]:
    """Consecutive closes `ratio` times apart or more, across any gap in the dates: a redenomination or token swap spliced into one pair
    (COCOS went from 0.0003 to 0.7 over a three-week gap in 2021), which reads as a return nobody could earn. A listing's first days can
    do this honestly too, so a break is a thing to look at, not proof."""
    found, previous_date, previous = [], None, None
    for date in sorted(closes):
        close = float(closes[date])
        if not math.isfinite(close) or close <= 0.0:
            continue
        if previous is not None:
            move = close / previous
            if move >= ratio or move <= 1.0 / ratio:
                found.append({"from": previous_date, "to": date, "ratio": move})
        previous_date, previous = date, close
    return found


def truncate_at_swap(rows: list[dict], *, ratio: float = 10.0, min_gap_days: int = 2) -> tuple[list[dict], dict | None]:
    """A pair's bars up to its first break across a gap of `min_gap_days` or more: what follows is another instrument under the same name. A collapse with
    no gap (LUNA on 2022-05-11) is a real loss and stays."""
    closes = {row["date"]: row["close"] for row in rows}
    for found in price_breaks(closes, ratio=ratio):
        gap = (datetime.fromisoformat(found["to"]) - datetime.fromisoformat(found["from"])).days
        if gap >= min_gap_days:
            return [row for row in rows if row["date"] <= found["from"]], found
    return rows, None


def liquid_universe(quote_volume: pd.DataFrame, *, top_n: int = 30, window: int = 60) -> pd.DataFrame:
    """Date x coin, True where the coin is among the `top_n` by trailing dollar volume. Trailing and shifted a row: a day's own
    volume isn't known until it ends. Only a coin with a full window qualifies."""
    trailing = quote_volume.rolling(window, min_periods=window).mean().shift(1)
    ranks = trailing.rank(axis=1, ascending=False, method="first")
    return ranks.le(top_n) & trailing.notna()


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.astype("float64").to_parquet(path)
