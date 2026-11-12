"""Crypto signal tables of V6.6.4's round 4C: session x coin, higher is better, each known at that session's close.

Every function reads `known`, whose row for a session already holds only the bar from before it (`portfolio.premia_signals.known_closes`), so none of them shifts again. A
volume or funding table is passed in the same way: lagged and forward-filled onto `known`'s rows by the cell that builds it. Nothing here is fitted, and a window that isn't full
gives NaN, never a number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

BTC = "BTCUSD"
CORE = ("BTCUSD", "ETHUSD")


def _finite(table: pd.DataFrame) -> pd.DataFrame:
    """An infinite price or volume is a missing one, so it can't turn a ratio or a rolling extreme into a number."""
    return table.replace([np.inf, -np.inf], np.nan)


def _returns(known: pd.DataFrame) -> pd.DataFrame:
    return _finite(_finite(known).pct_change(fill_method=None))


def _align(table: pd.DataFrame, known: pd.DataFrame) -> pd.DataFrame:
    return table.reindex(index=known.index, columns=known.columns)


def low_vol(known: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """The calmer coin ranks higher: minus the trailing standard deviation of daily returns."""
    return -_returns(known).rolling(window, min_periods=window).std()


def lottery_max(known: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """The coin with the smaller best day ranks higher: minus the trailing maximum daily return (Bali, Cakici, Whitelaw's MAX effect)."""
    return -_returns(known).rolling(window, min_periods=window).max()


def amihud(known: pd.DataFrame, quote_volume: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Illiquidity: the trailing mean of |return| per unit of quote volume. A zero or missing volume leaves that day out; half a window is the minimum."""
    volume = _finite(_align(quote_volume, known))
    ratio = _returns(known).abs() / volume.where(volume > 0.0)
    return ratio.replace([np.inf, -np.inf], np.nan).rolling(window, min_periods=max(2, window // 2)).mean()


def volume_trend(quote_volume: pd.DataFrame, short: int = 7, long: int = 28) -> pd.DataFrame:
    """Log of the short mean volume over the long mean: rising attention ranks higher."""
    positive = _finite(quote_volume).where(lambda frame: frame > 0.0)
    fast = positive.rolling(short, min_periods=max(2, short // 2)).mean()
    slow = positive.rolling(long, min_periods=long // 2).mean()
    return np.log(fast / slow).replace([np.inf, -np.inf], np.nan)


def high_proximity(known: pd.DataFrame, window: int = 365, min_periods: int = 180) -> pd.DataFrame:
    """Close over its trailing high (George and Hwang): 1.0 at the high."""
    known = _finite(known)
    return known / known.rolling(window, min_periods=min_periods).max()


def short_reversal(known: pd.DataFrame, window: int = 7) -> pd.DataFrame:
    """Minus the trailing return: last week's losers rank higher."""
    known = _finite(known)
    return -_finite(known / known.shift(window) - 1.0)


def _beta_and_residual(known: pd.DataFrame, btc: str, window: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = _returns(known)
    bench = daily[btc]
    variance = bench.rolling(window, min_periods=window).var()
    beta = daily.rolling(window, min_periods=window).cov(bench).div(variance.where(variance > 0.0), axis=0)
    return beta, daily.sub(beta.mul(bench, axis=0))


def low_beta(known: pd.DataFrame, btc: str = BTC, window: int = 60) -> pd.DataFrame:
    """Minus the trailing beta to BTC."""
    return -_beta_and_residual(known, btc, window)[0]


def idio_vol(known: pd.DataFrame, btc: str = BTC, window: int = 60) -> pd.DataFrame:
    """Minus the standard deviation of the return left after BTC."""
    return -_beta_and_residual(known, btc, window)[1].rolling(window, min_periods=window).std()


def trend_votes(known: pd.DataFrame, lookbacks: tuple[int, ...] = (20, 60, 120)) -> pd.DataFrame:
    """The installed rule's votes: the share of lookbacks over which the trailing return is positive. NaN until the longest has a price."""
    known = _finite(known)
    votes = [(known / known.shift(lookback) - 1.0 > 0.0).astype(float).where(known.shift(lookback).notna()) for lookback in lookbacks]
    return sum(votes) / len(votes)  # NaN propagates: a coin short of the longest history has no vote


def funding_filtered_trend(known: pd.DataFrame, funding: pd.DataFrame | None, window: int = 14, rank_window: int = 180, cut: float = 0.8) -> pd.DataFrame:
    """The trend votes, set to 0 (flat) where a coin's mean funding sits above its own trailing `cut` quantile, since crowded longs paid to stay long. Missing funding leaves the vote alone."""
    votes = trend_votes(known)
    if funding is None or funding.empty:
        return votes
    cost = _finite(_align(funding, known))
    mean = cost.rolling(window, min_periods=max(3, window // 2)).mean()
    threshold = mean.rolling(rank_window, min_periods=rank_window // 2).quantile(cut)
    hot = (mean > threshold).fillna(False)
    return votes.mask(hot & votes.notna(), 0.0)


def breadth_timing(known: pd.DataFrame, liquid: pd.DataFrame, window: int = 50, floor: float = 0.5, core: tuple[str, ...] = CORE) -> pd.DataFrame:
    """1.0 on the core coins while at least `floor` of the liquid coins trade above their own `window`-session average, else 0.0. NaN elsewhere and while breadth can't be measured."""
    known = _finite(known)
    average = known.rolling(window, min_periods=window).mean()
    measurable = (known.notna() & average.notna()) & _align(liquid, known).fillna(False).astype(bool)
    above = (known > average) & measurable
    count = measurable.sum(axis=1)
    share = above.sum(axis=1).div(count.where(count >= 10))
    table = pd.DataFrame(np.nan, index=known.index, columns=known.columns)
    for coin in core:
        if coin in table.columns:
            table[coin] = (share >= floor).astype(float).where(share.notna() & known[coin].notna())
    return table


def core_constant(known: pd.DataFrame, core: tuple[str, ...] = CORE) -> pd.DataFrame:
    """1.0 on the core coins wherever they have a price: a volatility-managed hold, whose size the weight pipeline sets."""
    table = pd.DataFrame(np.nan, index=known.index, columns=known.columns)
    for coin in core:
        if coin in table.columns:
            table[coin] = known[coin].notna().astype(float).where(known[coin].notna())
    return table


FORWARD_BUILDERS = ("low_vol", "lottery_max", "high_proximity", "short_reversal", "low_beta", "idio_vol", "trend_votes", "breadth_timing", "core_constant")


def forward_table(spec: Mapping[str, Any], known: pd.DataFrame) -> pd.DataFrame:
    """A round-4C trial as the forward feed can compute it, from the marks alone (no volume, no funding): `{"builder": name, "params": {...}, "gate": "regime"}` for one signal, or
    `{"rank_mean": [spec, ...], "minimum": n, "gate": "regime"}` for a composite. The builder comes from a closed set. `breadth_timing` counts every coin in `known` as liquid, since the feed
    holds only the coins the definition lists."""
    from portfolio.wide_signals import rank_mean

    if "rank_mean" in spec:
        parts = [forward_table(part, known) for part in spec["rank_mean"]]
        table = rank_mean(parts, minimum=int(spec.get("minimum", len(parts))))
    else:
        name = str(spec["builder"])
        if name not in FORWARD_BUILDERS:
            raise KeyError(f"unknown forward builder {name!r}; expected one of {sorted(FORWARD_BUILDERS)}")
        params = dict(spec.get("params") or {})
        if name == "breadth_timing":
            table = breadth_timing(known, pd.DataFrame(True, index=known.index, columns=known.columns), **params)
        else:
            table = globals()[name](known, **params)
    return regime_gate(table, known) if spec.get("gate") == "regime" else table


def regime_gate(table: pd.DataFrame, known: pd.DataFrame, btc: str = BTC, window: int = 120) -> pd.DataFrame:
    """The table on sessions when BTC trades above its `window`-session average; no signal at all (a flat book) otherwise, and while BTC's average can't be measured."""
    known = _finite(known)
    average = known[btc].rolling(window, min_periods=window).mean()
    on = (known[btc] > average) & average.notna()
    return table.where(on, np.nan)
