"""Signal tables of V6.6.4's round 4E: session x name, higher is better, each known at that session's close.

Every event (a filing, an announcement, an insider purchase) becomes visible at the first session strictly after its date, so a filing made during a session never informs
that session. `known` rows already hold the bar from before the session, as everywhere in the research pipeline. Nothing here is fitted, and a name without the history a signal
needs is NaN, never a number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any


def _dates(values) -> pd.Series:
    return pd.to_datetime(pd.Series(values), errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()


def _positions(index: pd.Index, dates: pd.Series, *, side: str) -> np.ndarray:
    """Row of each date among the (ISO-string) session index; `right` is the first session strictly after the date, `left` the first on or after it."""
    sessions = pd.to_datetime(pd.Index(index)).tz_localize(None) if not isinstance(index, pd.DatetimeIndex) else index
    return sessions.searchsorted(pd.DatetimeIndex(dates), side=side)


def events_to_sessions(events: pd.DataFrame, index: pd.Index, columns: pd.Index, *, date: str, value: str, limit: int | None) -> pd.DataFrame:
    """The newest `value` per name as of each session, from rows with a `date` and a `ticker`. Visible from the first session strictly after `date`; a later event
    at the same row wins; carried forward at most `limit` rows."""
    table = pd.DataFrame(np.nan, index=index, columns=columns)
    if events is None or len(events) == 0:
        return table
    frame = pd.DataFrame({"ticker": events["ticker"].to_numpy(), "date": _dates(events[date]).to_numpy(), "value": pd.to_numeric(events[value], errors="coerce").to_numpy()})
    frame = frame[frame["date"].notna() & frame["value"].notna() & frame["ticker"].isin(columns)].sort_values("date", kind="stable")
    if frame.empty:
        return table
    rows = _positions(index, frame["date"], side="right")
    keep = rows < len(index)
    columns_at = {name: position for position, name in enumerate(columns)}
    values = table.to_numpy(dtype=float, copy=True)
    for row, ticker, number in zip(rows[keep], frame["ticker"].to_numpy()[keep], frame["value"].to_numpy()[keep]):
        values[row, columns_at[ticker]] = number
    return pd.DataFrame(values, index=index, columns=columns).ffill(limit=limit)


def similarity_table(rows: pd.DataFrame, index: pd.Index, columns: pd.Index, *, max_age: int = 130) -> pd.DataFrame:
    """The newest 10-K or 10-Q's similarity to the same form a year earlier (Cohen, Malloy, Nguyen): high means the filing is unchanged. Blank after `max_age` sessions without a newer one."""
    return events_to_sessions(rows, index, columns, date="filed", value="similarity", limit=max_age)


def announcement_proximity(rows: pd.DataFrame, index: pd.Index, columns: pd.Index, *, window_days: int = 14) -> pd.DataFrame:
    """1.0 during the `window_days` calendar days before a name's expected announcement (about ten sessions), 0.0 otherwise, NaN for a name with no earlier announcement.
    The expected date is an announcement 52 weeks earlier (Frazzini and Lamont's announcement premium), so no filing at or after the session is read. An expected date beyond the last
    session flags only the sessions that really lie inside its window."""
    table = pd.DataFrame(np.nan, index=index, columns=columns)
    if rows is None or len(rows) == 0:
        return table
    frame = pd.DataFrame({"ticker": rows["ticker"].to_numpy(), "date": _dates(rows["accepted"]).to_numpy()})
    frame = frame[frame["date"].notna() & frame["ticker"].isin(columns)]
    expected = frame["date"] + pd.Timedelta(days=364)
    values = table.to_numpy(dtype=float, copy=True)
    columns_at = {name: position for position, name in enumerate(columns)}
    first_seen: dict[str, int] = {}
    for date, ticker in zip(_positions(index, frame["date"], side="right"), frame["ticker"]):
        first_seen[ticker] = min(first_seen.get(ticker, len(index)), int(date))
    for ticker, first in first_seen.items():
        values[first:, columns_at[ticker]] = 0.0  # a name with an announcement on record is measurable from the session after it
    ends = _positions(index, expected, side="left")
    starts = _positions(index, expected - pd.Timedelta(days=window_days), side="left")
    for low, end, ticker in zip(starts, ends, frame["ticker"]):
        if low < end:
            values[int(low):int(end), columns_at[ticker]] = 1.0
    return pd.DataFrame(values, index=index, columns=columns)


def announcement_return(rows: pd.DataFrame, known: pd.DataFrame, *, days: int = 3, decay: int = 60, bench: str = "SPY") -> pd.DataFrame:
    """The abnormal return over `days` rows from the announcement (Brandt, Kishore, Santa-Clara and Venkatachalam), held for `decay` rows once it is complete.
    Row `start` holds the close before the announcement day, row `start + days` the close of its last reaction day. Blank until those days have passed, and for `bench` itself."""
    table = pd.DataFrame(np.nan, index=known.index, columns=known.columns)
    if rows is None or len(rows) == 0 or bench not in known.columns:
        return table
    frame = pd.DataFrame({"ticker": rows["ticker"].to_numpy(), "date": _dates(rows["accepted"]).to_numpy()})
    frame = frame[frame["date"].notna() & frame["ticker"].isin(known.columns) & (frame["ticker"] != bench)].sort_values("date", kind="stable")
    starts = _positions(known.index, frame["date"], side="left")
    prices = known.to_numpy(dtype=float)
    benchmark = known[bench].to_numpy(dtype=float)
    columns_at = {name: position for position, name in enumerate(known.columns)}
    values = table.to_numpy(dtype=float, copy=True)
    for start, ticker in zip(starts, frame["ticker"]):
        end = int(start) + days
        if start < 1 or end >= len(known.index):
            continue
        column = columns_at[ticker]
        before, after = prices[start, column], prices[end, column]
        bench_before, bench_after = benchmark[start], benchmark[end]
        if not (np.isfinite(before) and np.isfinite(after) and np.isfinite(bench_before) and np.isfinite(bench_after) and before > 0.0 and bench_before > 0.0):
            continue
        values[end:min(len(known.index), end + decay), column] = after / before - bench_after / bench_before
    return pd.DataFrame(values, index=known.index, columns=known.columns)


def same_month_seasonality(known: pd.DataFrame, *, years: int = 7, min_years: int = 5) -> pd.DataFrame:
    """The mean return of this calendar month over the previous `years` years (Heston and Sadka), needing `min_years` of them. Only completed months of earlier years are read."""
    dates = pd.to_datetime(pd.Index(known.index)).tz_localize(None)
    month = dates.to_period("M")
    last = known.groupby(month).last()
    full = pd.period_range(last.index.min(), last.index.max(), freq="M")
    monthly = last.reindex(full).pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    stack = np.stack([monthly.shift(12 * k).to_numpy(dtype=float) for k in range(1, years + 1)])
    count = np.isfinite(stack).sum(axis=0)
    mean = np.where(count >= min_years, np.nansum(stack, axis=0) / np.where(count > 0, count, 1), np.nan)
    seasonal = pd.DataFrame(mean, index=full, columns=known.columns)
    table = seasonal.reindex(month)
    table.index = known.index
    return table.where(known.notna())


def opportunistic_buying(trades: pd.DataFrame, index: pd.Index, columns: pd.Index, *, routine_years: int = 3, window: int = 63) -> pd.DataFrame:
    """Open-market purchases (code P) by owners who weren't routine buyers (Cohen, Malloy, Pomorski): an owner who bought in the same calendar month in each of the previous
    `routine_years` years is routine and left out. The value over the last `window` rows, logged. Dated by `filed`; 0.0 means no such purchase."""
    table = pd.DataFrame(0.0, index=index, columns=columns)
    if trades is None or len(trades) == 0:
        return table
    frame = pd.DataFrame({
        "ticker": trades["ticker"].to_numpy(), "owner": trades["owner"].to_numpy(), "code": trades["code"].to_numpy(),
        "filed": _dates(trades["filed"]).to_numpy(), "value": pd.to_numeric(trades["value"], errors="coerce").to_numpy(),
    })
    frame = frame[(frame["code"] == "P") & frame["filed"].notna() & frame["value"].notna() & (frame["value"] > 0.0) & frame["ticker"].isin(columns)]
    if frame.empty:
        return table
    stamp = pd.DatetimeIndex(frame["filed"])
    frame = frame.assign(year=stamp.year, month=stamp.month)
    seen = set(zip(frame["ticker"], frame["owner"], frame["year"], frame["month"]))
    routine = np.array([
        all((ticker, owner, year - gap, month) in seen for gap in range(1, routine_years + 1))
        for ticker, owner, year, month in zip(frame["ticker"], frame["owner"], frame["year"], frame["month"])
    ])
    kept = frame[~routine]
    if kept.empty:
        return table
    daily = pd.DataFrame(0.0, index=index, columns=columns)
    rows = _positions(index, kept["filed"], side="right")
    values = daily.to_numpy(dtype=float, copy=True)
    columns_at = {name: position for position, name in enumerate(columns)}
    for row, ticker, value in zip(rows, kept["ticker"], kept["value"]):
        if row < len(index):
            values[row, columns_at[ticker]] += float(value)
    daily = pd.DataFrame(values, index=index, columns=columns)
    return np.log1p(daily.rolling(window, min_periods=1).sum())


def cash_profitability(fundamentals: pd.DataFrame, index: pd.Index, columns: pd.Index, *, max_age: int = 400) -> pd.DataFrame:
    """Trailing operating cash flow over assets (Ball et al.), each as last filed before the session."""
    flow = events_to_sessions(fundamentals[fundamentals["field"] == "ttm_operating_cash_flow"], index, columns, date="filed", value="value", limit=max_age)
    assets = events_to_sessions(fundamentals[fundamentals["field"] == "assets"], index, columns, date="filed", value="value", limit=max_age)
    return (flow / assets.where(assets > 0.0)).replace([np.inf, -np.inf], np.nan)


def fred_as_known(series: dict[str, Any], index: pd.Index, *, keys: tuple[str, ...] = ("treasury_10yr", "treasury_3mo", "credit_spread_baa10y"), lag_sessions: int = 1) -> pd.DataFrame:
    """FRED series (`{key: Series by date}`) as the session knows them: carried across days with no mark, then read `lag_sessions` late, since FRED's daily marks post after the equity close."""
    columns = {}
    for key in keys:
        values = series.get(key)
        if values is None or len(values) == 0:
            columns[key] = pd.Series(np.nan, index=index)
            continue
        values = values.sort_index()
        columns[key] = values.reindex(values.index.union(index)).ffill().reindex(index).shift(lag_sessions)
    return pd.DataFrame(columns, index=index)


def term_credit_timing(fred_table: pd.DataFrame, known: pd.DataFrame, *, ticker: str = "SPY", window: int = 252) -> pd.DataFrame:
    """1.0 on `ticker` while the term spread (10 years less 3 months) is positive and the Baa credit spread is at or below its own trailing median, else 0.0. NaN when a rate is missing."""
    table = pd.DataFrame(np.nan, index=known.index, columns=known.columns)
    needed = ("treasury_10yr", "treasury_3mo", "credit_spread_baa10y")
    if ticker not in table.columns or any(name not in fred_table for name in needed):
        return table
    rates = pd.DataFrame({name: fred_table[name] for name in needed}).reindex(known.index)  # a FRED mapping {key: series}, or a frame with those columns
    term = rates["treasury_10yr"] - rates["treasury_3mo"]
    credit = rates["credit_spread_baa10y"]
    median = credit.rolling(window, min_periods=window // 2).median()
    measurable = term.notna() & credit.notna() & median.notna() & known[ticker].notna()
    table[ticker] = ((term > 0.0) & (credit <= median)).astype(float).where(measurable)
    return table


def cross_asset_trend(known: pd.DataFrame, tickers: tuple[str, ...] | list[str], *, long: int = 252, skip: int = 21) -> pd.DataFrame:
    """1.0 where the 12-1 month return (`long` rows back to `skip` rows back) is positive, else 0.0; NaN without that history. Only the named assets."""
    table = pd.DataFrame(np.nan, index=known.index, columns=known.columns)
    for ticker in tickers:
        if ticker in table.columns:
            ratio = known[ticker].shift(skip) / known[ticker].shift(long) - 1.0
            table[ticker] = (ratio > 0.0).astype(float).where(ratio.notna())
    return table
