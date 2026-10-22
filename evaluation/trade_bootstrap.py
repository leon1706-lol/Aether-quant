"""Is a sleeve's P&L a repeatable effect or a few lucky fills? (V6.4.0, lead L9.) Pure given closed trades; numpy only.

`closedTrades` of a Lean run give one P&L per round trip. This module groups them by name, bootstraps the mean P&L per
trade (resampling trades with replacement), measures how much of the total the best few trades carry, and recomputes the
total with each name left out in turn.
"""

from __future__ import annotations

import numpy as np


def round_trips_from_closed_trades(run: dict, tickers: set[str] | None = None) -> list[dict]:
    """[{"ticker", "pnl" (net of fees), "notional", "entry"}] for the run's closed trades, restricted to `tickers`
    (upper-case) when given. Trades with several symbols (option combos) are skipped."""
    trades = ((run.get("result") or {}).get("totalPerformance") or {}).get("closedTrades") or []
    out = []
    for trade in trades:
        symbols = trade.get("symbols") or []
        if len(symbols) != 1:
            continue
        ticker = str(symbols[0].get("value", "")).upper()
        if tickers is not None and ticker not in tickers:
            continue
        try:
            pnl = float(trade.get("profitLoss", 0.0)) - float(trade.get("totalFees", 0.0))
            notional = abs(float(trade.get("entryPrice", 0.0)) * float(trade.get("quantity", 0.0)))
        except (TypeError, ValueError):
            continue
        out.append({"ticker": ticker, "pnl": pnl, "notional": notional, "entry": str(trade.get("entryTime", ""))[:10]})
    return out


def bootstrap_mean_pnl(pnls, n: int = 10000, seed: int = 7, confidence: float = 0.95) -> dict:
    """Mean P&L per trade with a percentile bootstrap interval; `p_mean_le_0` = the share of resampled means <= 0."""
    values = np.asarray([float(value) for value in pnls if np.isfinite(value)], dtype=float)
    if len(values) < 2:
        return {"n": int(len(values)), "mean": float(values.mean()) if len(values) else None, "ci_low": None, "ci_high": None,
                "p_mean_le_0": None}
    rng = np.random.default_rng(seed)
    means = np.empty(int(n))
    for index in range(int(n)):
        means[index] = values[rng.integers(0, len(values), len(values))].mean()
    tail = (1.0 - confidence) / 2.0
    return {"n": int(len(values)), "mean": float(values.mean()), "ci_low": float(np.quantile(means, tail)),
            "ci_high": float(np.quantile(means, 1.0 - tail)), "p_mean_le_0": float((means <= 0.0).mean())}


def top_k_share(pnls, k: int) -> float | None:
    """The best `k` trades' P&L as a share of the total (None when the total is not positive or there are no trades)."""
    values = sorted((float(value) for value in pnls), reverse=True)
    total = sum(values)
    if not values or total <= 0.0:
        return None
    return float(sum(values[:k]) / total)


def pnl_by_name(trades: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for trade in trades:
        totals[trade["ticker"]] = totals.get(trade["ticker"], 0.0) + trade["pnl"]
    return totals


def leave_one_name_out(totals_by_name: dict[str, float]) -> dict[str, float]:
    """{name: the total P&L without that name}."""
    total = sum(totals_by_name.values())
    return {name: total - value for name, value in totals_by_name.items()}


def repeatable(bootstrap: dict, leave_one_out: dict[str, float]) -> bool:
    """The L9 verdict: the bootstrap interval's lower end is above zero AND every leave-one-name-out total stays positive."""
    low = bootstrap.get("ci_low")
    return low is not None and low > 0.0 and bool(leave_one_out) and all(value > 0.0 for value in leave_one_out.values())
