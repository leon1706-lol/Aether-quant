"""What a finished Lean run earned against what a reader could have held instead: the README's Benchmarks table.

Every series is compounded onto the US equity session calendar and scored by one formula (no risk-free rate), so a book
that also trades at weekends is compared on the same intervals as SPY."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

PERIODS_PER_YEAR = 252.0
STOCK_WEIGHT = 0.6


def series_row(name: str, returns: pd.Series, *, periods_per_year: float = PERIODS_PER_YEAR) -> dict:
    """Total and annual return, volatility, Sharpe and maximum drawdown of one return series."""
    values = np.asarray(returns.dropna(), dtype=float)
    if values.size < 2:
        return {"series": name, "total_return": None, "annual_return": None, "volatility": None, "sharpe": None, "max_drawdown": None}
    equity = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    deviation = float(values.std(ddof=1))
    total = float(equity[-1] - 1.0)
    return {
        "series": name,
        "total_return": total,
        "annual_return": float((1.0 + total) ** (periods_per_year / values.size) - 1.0) if total > -1.0 else None,
        "volatility": deviation * math.sqrt(periods_per_year),
        "sharpe": float(values.mean()) / deviation * math.sqrt(periods_per_year) if deviation > 0 else None,
        "max_drawdown": float(np.max(1.0 - equity / peaks)),
    }


def benchmark_rows(portfolio: pd.Series, strategy: pd.Series, benchmarks: pd.DataFrame, crypto: list[str]) -> list[dict]:
    """The run and its alternatives over the same sessions. `benchmarks` holds session returns; `crypto` names the coins the
    run traded, held equally weighted and rebalanced daily with no fees."""
    sessions = portfolio.index.intersection(benchmarks.index)
    if not len(sessions):
        return []
    table = benchmarks.loc[sessions]
    rows = [series_row("**Portfolio** (with the T-bill sweep)", portfolio.loc[sessions])]
    if not strategy.empty:
        rows.append(series_row("**Strategy** (without the sweep)", strategy.reindex(sessions).fillna(0.0)))
    if "SPY" in table:
        rows.append(series_row("SPY", table["SPY"]))
    if "SPY" in table and "AGG" in table:
        rows.append(series_row("60/40 SPY/AGG, rebalanced daily", STOCK_WEIGHT * table["SPY"] + (1.0 - STOCK_WEIGHT) * table["AGG"]))
    if "BTCUSD" in table:
        rows.append(series_row("Bitcoin, buy and hold", table["BTCUSD"]))
    coins = [coin for coin in crypto if coin in table]
    if len(coins) > 1:
        rows.append(series_row(f"The book's {len(coins)} coins, equal weight", table[coins].mean(axis=1)))
    return rows
