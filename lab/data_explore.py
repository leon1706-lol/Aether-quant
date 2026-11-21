"""A first look at a price table (`aq data info`, `aq data explore`): coverage and gaps per ticker, and a one-file HTML page
with return distributions, correlations, drawdowns, the gap map and rolling volatility.

Input is a dates x tickers close table (a wide CSV: a date column, then one column per ticker), or a long one
(date, ticker, close), which is pivoted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lab import report_html as rh


def read_closes(path: Path) -> pd.DataFrame:
    """A dates x tickers float table from a wide or long CSV (or parquet), indexed by ISO date strings."""
    path = Path(path)
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
        if not isinstance(frame.index, pd.RangeIndex):
            frame = frame.reset_index()
    else:
        frame = pd.read_csv(path)
    lowered = {column.lower(): column for column in frame.columns}
    if {"date", "ticker", "close"} <= set(lowered):
        frame = frame.pivot(index=lowered["date"], columns=lowered["ticker"], values=lowered["close"])
    else:
        frame = frame.set_index(frame.columns[0])
    frame.index = pd.to_datetime(frame.index).strftime("%Y-%m-%d")
    frame.columns = [str(column) for column in frame.columns]
    return frame.sort_index().apply(pd.to_numeric, errors="coerce").astype(float)


def calendar_kind(index: pd.Index) -> str:
    """'7-day' when weekends carry rows (crypto), else 'weekdays'."""
    days = pd.to_datetime(index).day_of_week
    return "7-day" if (days >= 5).any() else "weekdays"


def longest_gaps(series: pd.Series) -> int:
    """The longest run of missing values after the ticker's first value."""
    values = series.loc[series.first_valid_index():] if series.first_valid_index() is not None else series.iloc[0:0]
    missing = values.isna().to_numpy()
    best = current = 0
    for flag in missing:
        current = current + 1 if flag else 0
        best = max(best, current)
    return int(best)


def info(closes: pd.DataFrame) -> dict[str, Any]:
    """Shape, date range, calendar, and per ticker: first and last date, missing share and longest gap after its start."""
    tickers = {}
    for ticker in closes.columns:
        series = closes[ticker]
        first, last = series.first_valid_index(), series.last_valid_index()
        live = series.loc[first:last] if first is not None else series.iloc[0:0]
        tickers[ticker] = {"first": first, "last": last, "missing": round(float(live.isna().mean()), 4) if len(live) else 1.0, "longest_gap": longest_gaps(series)}
    return {"rows": int(len(closes)), "tickers": int(closes.shape[1]), "start": str(closes.index.min()) if len(closes) else None,
            "end": str(closes.index.max()) if len(closes) else None, "calendar": calendar_kind(closes.index) if len(closes) else None,
            "gaps_over_3": sorted(ticker for ticker, row in tickers.items() if row["longest_gap"] > 3), "per_ticker": tickers}


def render_info(data: dict[str, Any]) -> str:
    """`aq data info`'s text: shape, window, calendar, coverage and gaps."""
    lines = [f"{data['rows']} dates x {data['tickers']} tickers, {data['start']} to {data['end']} ({data['calendar']} calendar)"]
    for ticker, row in data["per_ticker"].items():
        lines.append(f"  {ticker:<10} {row['first']} .. {row['last']}  missing {row['missing']:.1%}  longest gap {row['longest_gap']}")
    if data["gaps_over_3"]:
        lines.append(f"gaps over 3 rows: {', '.join(data['gaps_over_3'])}")
    return "\n".join(lines)


def explore(closes: pd.DataFrame, *, title: str = "Data") -> dict[str, Any]:
    """The numbers behind the page: return moments, the correlation matrix, drawdowns, rolling volatility."""
    returns = closes.pct_change(fill_method=None)
    periods = 365.0 if calendar_kind(closes.index) == "7-day" else 252.0
    moments = {}
    for ticker in closes.columns:
        values = returns[ticker].dropna()
        if len(values) < 3:
            continue
        moments[ticker] = {"mean_annual": float(values.mean() * periods), "vol_annual": float(values.std() * np.sqrt(periods)),
                           "skew": float(values.skew()), "kurtosis": float(values.kurt()), "p01": float(values.quantile(0.01)), "p99": float(values.quantile(0.99))}
    drawdown = closes / closes.cummax() - 1.0
    return {"title": title, "periods": periods, "moments": moments, "correlation": returns.corr(min_periods=20),
            "max_drawdown": {ticker: float(drawdown[ticker].min()) for ticker in closes.columns if drawdown[ticker].notna().any()},
            "rolling_vol": returns.rolling(60, min_periods=40).std() * np.sqrt(periods), "returns": returns, "closes": closes}


def render_explore_html(data: dict[str, Any]) -> str:
    """The exploration report as one self-contained HTML page."""
    moments = [[ticker, row["mean_annual"], row["vol_annual"], row["skew"], row["kurtosis"], row["p01"], row["p99"], data["max_drawdown"].get(ticker)]
               for ticker, row in data["moments"].items()]
    closes = data["closes"]
    normalised = [series / series.dropna().iloc[0] for _, series in closes.items() if series.notna().any()]
    vol = data["rolling_vol"]
    gaps = {ticker: float(closes[ticker].loc[closes[ticker].first_valid_index():].isna().mean()) for ticker in closes.columns if closes[ticker].notna().any()}
    pooled = data["returns"].stack().to_numpy()
    sections = [
        ("Growth of 1", rh.svg_lines(normalised, label="Growth of 1") + rh.legend(list(closes.columns))),
        ("Returns", rh.table(moments, ["ticker", "mean/yr", "vol/yr", "skew", "kurtosis", "1st pct", "99th pct", "max drawdown"])),
        ("Pooled daily returns", rh.svg_histogram(pooled, label="Pooled daily returns")),
        ("Correlation of daily returns", rh.svg_heatmap(data["correlation"].fillna(0.0))),
        ("Rolling 60-row volatility (annualised)", rh.svg_lines([vol[column] for column in vol.columns], label="Rolling volatility") + rh.legend(list(vol.columns))),
        ("Missing share after each ticker's start", rh.svg_bars(gaps, label="Missing share")),
    ]
    return rh.page(data["title"], sections, subtitle=f"{closes.shape[0]} dates x {closes.shape[1]} tickers, {closes.index.min()} to {closes.index.max()}")
