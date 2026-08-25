"""V5.4.4 - public benchmark baselines computed from the universe's own
index/bond proxies (SPY, TLT), so the rank book's edge can be stated
against well-known public benchmarks - not just against the naive
strategy baselines in evaluation/benchmark_comparison.py.

No external API and no new data dependencies: both functions accept the
exact same (dates × tickers) close-price pivot that
benchmark_comparison::momentum_baseline() already consumes - SPY/TLT are
ordinary columns of `ml/datasets/full_dataset.csv`'s wide close table.

- compute_sp500_baseline(): buy-and-hold SPY, close-to-close daily
  returns over the pivot's own window.
- compute_60_40_baseline(): the classic 60% SPY / 40% TLT portfolio,
  DAILY rebalanced (weights reset to 60/40 every day, so the portfolio
  return is just the fixed-weight blend of the two legs' daily returns -
  no drift compounding of the weights themselves).

Pure pandas/numpy, no I/O, no torch. Missing tickers degrade to a
SKIPPED status (None metrics) instead of raising - the same
"missing data never changes behavior, never crashes" convention the
rest of this package follows. Output keys mirror the existing baselines'
`{"strategy", "net_sharpe", "total_return_pct"}` shape, plus an
additive `status` field ("OK" / "SKIPPED: <reason>") since - unlike the
strategy baselines, which work on any universe - these two CAN be
uncomputable (a universe without SPY, or without TLT for the 60-40).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SP500_PROXY_TICKER = "SPY"
BOND_PROXY_TICKER = "TLT"
SP500_WEIGHT = 0.60
BOND_WEIGHT = 0.40


def _daily_close_returns(close_pivot: pd.DataFrame, ticker: str) -> pd.Series:
    """Close-to-close daily returns for one ticker, non-finite/zero-close
    rows degraded to NaN and dropped (a 0 close would otherwise produce
    inf via division)."""
    if ticker not in close_pivot.columns:
        return pd.Series(dtype=float)
    closes = pd.to_numeric(close_pivot[ticker], errors="coerce")
    closes = closes.where(closes > 0.0)
    # fill_method=None (never pad): a NaN close must produce NaN returns
    # that drop out below, not silently extend the last real close across
    # a gap (which would fabricate flat 0.0% return days).
    returns = closes.pct_change(fill_method=None)
    return returns.replace([np.inf, -np.inf], np.nan).dropna()


def _sharpe(daily_returns: pd.Series) -> float:
    """Annualized Sharpe of a daily-return series - the identical formula
    every baseline in evaluation/benchmark_comparison.py uses
    (mean / std(ddof=1) * sqrt(252), 0.0 when fewer than 2 observations),
    so benchmark numbers produced by the two modules can never disagree
    on what "Sharpe" means."""
    arr = np.asarray(daily_returns, dtype=float)
    if arr.size < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    if std <= 0.0:
        return 0.0
    return float(np.mean(arr) / std * np.sqrt(252.0))


def _result(strategy: str, daily_returns: pd.Series) -> dict:
    sharpe = _sharpe(daily_returns)
    total_return = float(np.prod(1.0 + np.asarray(daily_returns, dtype=float)) - 1.0) if daily_returns.size else 0.0
    return {
        "strategy": strategy,
        "net_sharpe": round(sharpe, 4),
        "total_return_pct": round(total_return * 100.0, 2),
        "status": "OK",
    }


def _skipped(strategy: str, reason: str) -> dict:
    return {
        "strategy": strategy,
        "net_sharpe": None,
        "total_return_pct": None,
        "status": f"SKIPPED: {reason}",
    }


def compute_sp500_baseline(close_pivot: pd.DataFrame) -> dict:
    """Buy-and-hold SPY over close_pivot's own window: close-to-close
    daily returns, annualized Sharpe + cumulative total return. Same
    window, same Sharpe formula as the strategy baselines - the numbers
    are directly comparable by construction."""
    returns = _daily_close_returns(close_pivot, SP500_PROXY_TICKER)
    if returns.empty:
        return _skipped("sp500", f"no usable {SP500_PROXY_TICKER} closes in close_pivot")
    return _result("sp500", returns)


def compute_60_40_baseline(close_pivot: pd.DataFrame) -> dict:
    """60% SPY + 40% TLT, daily rebalanced: each day's portfolio return is
    `0.6 * spy_ret + 0.4 * tlt_ret` (fixed-weight blend, weights reset
    every day - the textbook daily-rebalanced 60-40). Requires BOTH
    proxies present; either one missing skips the whole benchmark rather
    than silently computing a different allocation."""
    spy_returns = _daily_close_returns(close_pivot, SP500_PROXY_TICKER)
    tlt_returns = _daily_close_returns(close_pivot, BOND_PROXY_TICKER)
    if spy_returns.empty or tlt_returns.empty:
        missing = SP500_PROXY_TICKER if spy_returns.empty else BOND_PROXY_TICKER
        return _skipped("60_40", f"no usable {missing} closes in close_pivot")
    aligned = pd.concat(
        {"spy": spy_returns, "tlt": tlt_returns}, axis=1, join="inner"
    ).dropna()
    if aligned.empty:
        return _skipped("60_40", f"no overlapping {SP500_PROXY_TICKER}/{BOND_PROXY_TICKER} return dates")
    portfolio_returns = SP500_WEIGHT * aligned["spy"] + BOND_WEIGHT * aligned["tlt"]
    return _result("60_40", portfolio_returns)
