"""Which bars a cross-asset payload (topology, peer returns, macro proxies,
cross-sectional momentum rank) may see - shared by `main.py` (live windows) and
`train.py` (offline dataset) so the two cannot drift again (Problems.md #135).

Live builds the payload at the START of a tick, before that tick's own bars join
`symbol_windows`, and a daily bar only exists once its period has closed: a US
equity bar of day D at D's close, a crypto/forex bar of day D at the following
midnight. A row therefore sees every bar that became available strictly before
the row's own bar did - never its own tick's bars, and not yet-unclosed
crypto/forex bars on the equity tick (but Sunday's crypto bar on Monday).
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from datetime import date as _date
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path

WINDOW_BARS = 25  # main.py: deque(maxlen=bar_history_size); up to 24 returns
MOMENTUM_LOOKBACK_BARS = 20
_MIDNIGHT_SECURITY_TYPES = frozenset({"crypto", "forex"})
_SATURDAY = 5  # date.weekday(): Monday is 0
_EQUITY_CLOSE_FRACTION = 0.5
_MIDNIGHT_FRACTION = 1.0


def day_ordinal(stamp) -> int:
    """Proleptic ordinal of a pandas Timestamp / datetime / date / ISO date string."""
    if hasattr(stamp, "toordinal"):
        return stamp.toordinal()
    return _date.fromisoformat(str(stamp)[:10]).toordinal()


@lru_cache(maxsize=8)
def lean_market_holidays(market_hours_path: str, entry: str = "Forex-oanda-[*]") -> frozenset[int]:
    """Day ordinals of the full-day holidays Lean's market-hours database lists for `entry`. On such a day Lean delivers
    no bar for the market: the zip's own bar is dropped and the day is not filled forward (V6.1.0: GBPJPY's live
    momentum on 2024-01-22 equals the calendar without the 2023-12-24 / 12-31 Sunday fills). A missing file or entry
    returns an empty set (the pre-V6.1.0 calendar)."""
    path = Path(market_hours_path)
    if not path.exists():
        return frozenset()
    entries = json.loads(path.read_text(encoding="utf-8")).get("entries", {})
    out = set()
    for text in (entries.get(entry) or {}).get("holidays", []):
        month, day, year = (int(part) for part in str(text).split("/"))
        out.add(_date(year, month, day).toordinal())
    return frozenset(out)


def resolve_forex_lean_holidays(config: dict, root: Path | None = None) -> frozenset[int]:
    """Lean's forex market holidays when `phase1.features.forex_lean_holidays` is on (V6.1.0), else an empty set (the
    V6.0.0 calendar: every Sunday-Friday gap filled, every zip bar kept)."""
    if not bool(((config or {}).get("phase1", {}).get("features", {}) or {}).get("forex_lean_holidays", False)):
        return frozenset()
    base = root if root is not None else Path(__file__).resolve().parents[1]
    return lean_market_holidays(str(base / "data" / "market-hours" / "market-hours-database.json"))


def fill_forward_open_forex_days(
    ordinals: Sequence[int], closes: Sequence[float], holidays: frozenset[int] | set[int] = frozenset()
) -> tuple[list[int], list[float]]:
    """Lean fills forward a forex daily bar on every day the market is open without data. The forex market is open
    Sunday evening through Friday, so any Sunday-Friday day that falls between two bars becomes a flat bar at the
    previous close (BT1 probe, Problems.md #135: every pair delivered a Sunday bar live equal to the preceding Friday
    close where the local zip has no Sunday row; the 2019-05-22 weekday missing from the zips moved the live
    correlations for the next 24 bars). Saturdays and Lean's market holidays (`holidays`, lean_market_holidays) stay
    closed; only gaps strictly between two bars are filled; ordinals must be ascending."""
    filled_ordinals: list[int] = []
    filled_closes: list[float] = []
    for index, (ordinal, close) in enumerate(zip(ordinals, closes)):
        filled_ordinals.append(ordinal)
        filled_closes.append(close)
        if index + 1 == len(ordinals):
            continue
        for day in range(ordinal + 1, ordinals[index + 1]):
            if _date.fromordinal(day).weekday() != _SATURDAY and day not in holidays:
                filled_ordinals.append(day)
                filled_closes.append(close)
    return filled_ordinals, filled_closes


def is_late_bar_asset(security_type: str | None) -> bool:
    """Crypto and forex daily bars close at midnight, after the equity session: the equity tick still holds the
    previous day's bar for them."""
    return security_type in _MIDNIGHT_SECURITY_TYPES


class LateBarCrossAssetCache:
    """The cross-asset inputs (topology node, momentum map) a crypto/forex symbol had at ITS OWN tick, for re-use on the
    equity tick that scores the same bar again (V6.0.0, todo lead 5).

    The dataset row of a crypto/forex bar of day D sees the bars that closed before the bar did (key D + 1.0: equity
    through D, crypto/forex through D - 1). Live builds exactly that payload at the symbol's own midnight tick; the next
    equity tick (key D + 1.5) holds one more crypto bar, so re-scoring the symbol there with fresh payloads fed the model
    a correlation window the dataset never has. Re-using the own-tick payloads makes the equity-tick score the dataset's
    row D exactly (`phase1.features.late_bar_cross_asset: "own_tick"`)."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[dict, Mapping[str, float]]] = {}

    def record(self, symbol_key: str, topology_node: dict | None, momentum_by_symbol: Mapping[str, float]) -> None:
        if topology_node is not None:
            self._entries[symbol_key] = (topology_node, momentum_by_symbol)

    def lookup(self, symbol_key: str) -> tuple[dict, Mapping[str, float]] | None:
        return self._entries.get(symbol_key)


def bar_available_at(ordinal: int, security_type: str) -> float:
    return ordinal + (_MIDNIGHT_FRACTION if security_type in _MIDNIGHT_SECURITY_TYPES else _EQUITY_CLOSE_FRACTION)


def momentum_from_closes(closes: Sequence[float]) -> float | None:
    """`closes[-1] / close 20 bars back - 1` over the window; None below two closes or on a zero base."""
    if len(closes) < 2:
        return None
    base = closes[max(0, len(closes) - (MOMENTUM_LOOKBACK_BARS + 1))]
    if not base:
        return None
    momentum = closes[-1] / base - 1.0
    return momentum if math.isfinite(momentum) else None


def returns_from_closes(closes: Sequence[float]) -> list[float]:
    returns = []
    for index in range(1, len(closes)):
        previous = closes[index - 1]
        if previous == 0:
            continue
        value = closes[index] / previous - 1.0
        if math.isfinite(value):
            returns.append(value)
    return returns


def cross_asset_inputs(closes_by_symbol: Mapping[str, Sequence[float]]) -> tuple[dict[str, list[float]], dict[str, float]]:
    """(returns_by_symbol, momentum_by_symbol) from each symbol's trailing close window."""
    returns_by_symbol: dict[str, list[float]] = {}
    momentum_by_symbol: dict[str, float] = {}
    for symbol, closes in closes_by_symbol.items():
        returns = returns_from_closes(closes)
        if returns:
            returns_by_symbol[symbol] = returns
        momentum = momentum_from_closes(closes)
        if momentum is not None:
            momentum_by_symbol[symbol] = momentum
    return returns_by_symbol, momentum_by_symbol


class CrossAssetTimeline:
    """Raw (pre-dropna) close history per ticker, queryable as "what did the live windows hold at this moment"."""

    def __init__(
        self,
        closes_by_ticker: Mapping[str, Sequence[float]],
        day_ordinals_by_ticker: Mapping[str, Sequence[int]],
        security_types: Mapping[str, str] | None = None,
    ):
        security_types = security_types or {}
        self._closes = {ticker: list(closes) for ticker, closes in closes_by_ticker.items()}
        self._security_types = {ticker: security_types.get(ticker, "equity") for ticker in self._closes}
        self._availability = {
            ticker: [bar_available_at(ordinal, self._security_types[ticker]) for ordinal in day_ordinals_by_ticker[ticker]]
            for ticker in self._closes
        }

    @classmethod
    def from_frames(
        cls, frames: Mapping, security_types: Mapping[str, str] | None = None, forex_holidays: frozenset[int] = frozenset()
    ) -> CrossAssetTimeline:
        """`frames`: ticker -> DataFrame with `date` (Timestamp) and `close`, sorted by date. Forex history gets
        Lean's fill-forward bars (see fill_forward_open_forex_days), so its windows are what live holds."""
        security_types = security_types or {}
        closes_by_ticker: dict[str, list[float]] = {}
        ordinals_by_ticker: dict[str, list[int]] = {}
        for ticker, frame in frames.items():
            ordinals = [day_ordinal(stamp) for stamp in frame["date"]]
            closes = frame["close"].tolist()
            if security_types.get(ticker) == "forex":
                ordinals, closes = fill_forward_open_forex_days(ordinals, closes, forex_holidays)
            ordinals_by_ticker[ticker] = ordinals
            closes_by_ticker[ticker] = closes
        return cls(closes_by_ticker, ordinals_by_ticker, security_types)

    def row_availability(self, ticker: str, date) -> float:
        return bar_available_at(day_ordinal(date), self._security_types.get(ticker, "equity"))

    def closes_before(self, availability: float) -> dict[str, list[float]]:
        windows: dict[str, list[float]] = {}
        for ticker, keys in self._availability.items():
            end = bisect_left(keys, availability)
            if end:
                windows[ticker] = self._closes[ticker][max(0, end - WINDOW_BARS) : end]
        return windows

    def inputs_before(self, availability: float) -> tuple[dict[str, list[float]], dict[str, float]]:
        return cross_asset_inputs(self.closes_before(availability))

    def momentum_before(self, availability: float) -> dict[str, float]:
        return {
            symbol: momentum
            for symbol, closes in self.closes_before(availability).items()
            if (momentum := momentum_from_closes(closes)) is not None
        }
