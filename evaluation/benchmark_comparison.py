"""V5.4.3 - benchmark comparison: computes naive baseline strategies
(momentum, mean-reversion, random-entry) on the same dataset/window as the
rank-book simulation, so the model's edge can be stated relative to simple
benchmarks rather than in isolation.

V5.4.4 - `run_all_baselines()` aggregates these with
`public_benchmarks.py`'s SP500/60-40 baselines into the single report dict
`aq evaluate --benchmarks` persists (and the README section + webui panel
render). Pure: pandas/numpy only."""

from __future__ import annotations

import numpy as np
import pandas as pd


def momentum_baseline(
    close_pivot: pd.DataFrame,
    *,
    lookback: int = 20,
    top_n: int = 6,
    bottom_n: int = 6,
    forward_return_column: str = "target_return_1d",
    rebalance_every: int = 10,
) -> dict:
    """Buy the `top_n` assets with the HIGHEST past `lookback`-day return;
    sell short the `bottom_n` with the LOWEST. Rebalances every
    `rebalance_every` unique dates. Equal-weight within each leg."""
    mom = close_pivot / close_pivot.shift(lookback) - 1.0
    dates = close_pivot.index.tolist()
    rebalance_indices = list(range(0, len(dates), rebalance_every))

    daily_returns = []
    held_weights = {}
    for di, date in enumerate(dates):
        if di in rebalance_indices and di >= lookback:
            row = mom.loc[date].dropna()
            if len(row) < top_n + bottom_n:
                held_weights = {}
            else:
                sorted_vals = row.sort_values(ascending=False)
                longs = sorted_vals.head(top_n).index.tolist()
                shorts = sorted_vals.tail(bottom_n).index.tolist()
                w = 1.0 / max(top_n, 1)
                held_weights = {t: w for t in longs}
                for t in shorts:
                    held_weights[t] = -w

        # Compute portfolio return from next day's close-to-close
        if di + 1 < len(dates):
            port_ret = 0.0
            for ticker, weight in held_weights.items():
                if ticker in close_pivot.columns and date in close_pivot.index:
                    cur_idx = close_pivot.index.get_loc(date)
                    nxt_idx = cur_idx + 1
                    if nxt_idx < len(close_pivot.index):
                        nxt = close_pivot.index[nxt_idx]
                        c0 = close_pivot.loc[date, ticker] if date in close_pivot.index and not pd.isna(close_pivot.loc[date, ticker]) else np.nan
                        c1 = close_pivot.loc[nxt, ticker] if nxt in close_pivot.index and not pd.isna(close_pivot.loc[nxt, ticker]) else np.nan
                        if not (pd.isna(c0) or pd.isna(c1) or c0 == 0):
                            port_ret += weight * (c1 / c0 - 1.0)
            daily_returns.append(port_ret)
        else:
            daily_returns.append(0.0)

    arr = np.array(daily_returns)
    sharpe = float(arr.mean() / max(np.std(arr, ddof=1), 1e-12) * np.sqrt(252)) if len(arr) > 1 else 0.0
    total_return = float(np.prod(1 + arr) - 1)
    return {"strategy": "momentum", "net_sharpe": round(sharpe, 4), "total_return_pct": round(total_return * 100, 2)}


def mean_reversion_baseline(
    close_pivot: pd.DataFrame,
    *,
    lookback: int = 5,
    top_n: int = 6,
    bottom_n: int = 6,
    rebalance_every: int = 10,
) -> dict:
    """Buy bottom-N by recent `lookback`-day return (mean-reversion);
    sell short the top-N. Rebalances every `rebalance_every` unique dates.
    Equal-weight within each leg. Same next-day close-to-close return
    accrual as momentum_baseline above - V5.4.4 fix: this baseline
    previously accrued a hardcoded placeholder (`weight_sum * 0.001`)
    instead of realized returns, so its Sharpe was structurally 0.0 and
    the "benchmark" row it contributed to the comparison table was
    meaningless."""
    ret = close_pivot.pct_change(periods=lookback, fill_method=None)
    dates = close_pivot.index.tolist()
    rebalance_indices = set(range(lookback, len(dates), rebalance_every))

    daily_returns = []
    held_weights = {}
    for di, date in enumerate(dates):
        if di in rebalance_indices:
            row = ret.loc[date].dropna() if date in ret.index else pd.Series(dtype=float)
            if len(row) >= top_n + bottom_n:
                sorted_vals = row.sort_values(ascending=True)
                longs = sorted_vals.head(top_n).index.tolist()
                shorts = sorted_vals.tail(bottom_n).index.tolist()
                w = 1.0 / max(top_n, 1)
                held_weights = {t: w for t in longs}
                for t in shorts:
                    held_weights[t] = -w
        # Accrue NEXT day's close-to-close return on the held book (same
        # convention as momentum_baseline: decide on today's close, earn
        # today-close -> next-close).
        if di + 1 < len(dates):
            next_date = dates[di + 1]
            port_ret = 0.0
            for ticker, weight in held_weights.items():
                if ticker in close_pivot.columns:
                    c0 = close_pivot.loc[date, ticker] if date in close_pivot.index else np.nan
                    c1 = close_pivot.loc[next_date, ticker] if next_date in close_pivot.index else np.nan
                    if not (pd.isna(c0) or pd.isna(c1) or c0 == 0):
                        port_ret += weight * (c1 / c0 - 1.0)
            daily_returns.append(port_ret)
        else:
            daily_returns.append(0.0)

    arr = np.array(daily_returns)
    sharpe = float(arr.mean() / max(np.std(arr, ddof=1), 1e-12) * np.sqrt(252)) if len(arr) > 1 else 0.0
    total_return = float(np.prod(1 + arr) - 1)
    return {"strategy": "mean_reversion", "net_sharpe": round(sharpe, 4), "total_return_pct": round(total_return * 100, 2)}


def random_entry_baseline(
    tickers: list[str],
    *,
    n_days: int = 500,
    top_n: int = 6,
    bottom_n: int = 6,
    seed: int = 42,
    daily_vol: float = 0.01,
) -> dict:
    """Random entry/exit on the same universe with the same book shape.
    Expected Sharpe ≈ 0; serves as a statistical floor."""
    rng = np.random.default_rng(seed)
    n_names = max(top_n + bottom_n, 1)
    daily_vol_per_name = daily_vol / np.sqrt(n_names)
    daily_port_vol = daily_vol_per_name * np.sqrt(n_names)
    returns = rng.normal(0, daily_port_vol, n_days)
    arr = np.asarray(returns)
    sharpe = float(arr.mean() / max(np.std(arr, ddof=1), 1e-12) * np.sqrt(252)) if len(arr) > 1 else 0.0
    total_return = float(np.prod(1 + arr) - 1)
    return {"strategy": "random_entry", "net_sharpe": round(sharpe, 4), "total_return_pct": round(total_return * 100, 2)}


def close_pivot_from_frame(
    frame: pd.DataFrame,
    *,
    date_column: str = "date",
    ticker_column: str = "ticker",
    close_column: str = "close",
) -> pd.DataFrame:
    """(dates × tickers) close-price pivot from the long-format
    full_dataset frame - the single input every baseline (strategy and
    public) consumes. Empty pivot when the frame has no `close` column
    (callers then get per-baseline SKIPPED results, never a crash).
    `aggfunc="last"` keeps a (rare) duplicated (date, ticker) row from
    raising - same degrade-don't-raise convention as the rest of this
    package; dates sorted ascending so every baseline's window logic sees
    chronological order regardless of the CSV's row order."""
    if close_column not in frame.columns:
        return pd.DataFrame()
    pivot = frame.pivot_table(index=date_column, columns=ticker_column, values=close_column, aggfunc="last")
    return pivot.sort_index()


def run_all_baselines(
    close_pivot: pd.DataFrame,
    *,
    n_days: int = 500,
    seed: int = 42,
) -> dict:
    """Runs ALL five baselines over one close pivot - the three strategy
    baselines above plus public_benchmarks' SP500 buy-and-hold and
    daily-rebalanced 60-40 - into the report dict `aq evaluate
    --benchmarks` persists. Every entry carries the same
    strategy/net_sharpe/total_return_pct keys (public ones add `status`),
    so the README table and webui panel can render them uniformly; a
    baseline that can't compute (missing SPY/TLT, thin universe) degrades
    to SKIPPED/None metrics inside its own entry without affecting the
    others."""
    from evaluation.public_benchmarks import compute_60_40_baseline, compute_sp500_baseline

    tickers = list(close_pivot.columns)
    baselines = [
        momentum_baseline(close_pivot),
        mean_reversion_baseline(close_pivot),
        random_entry_baseline(tickers, n_days=n_days, seed=seed),
        compute_sp500_baseline(close_pivot),
        compute_60_40_baseline(close_pivot),
    ]
    return {"baselines": baselines}
