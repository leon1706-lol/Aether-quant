"""V5.3.8 - Monte Carlo simulation testing layer (pure core).

Resamples the offline rank book's daily NET return series into N
alternative equity histories so risk can be stated as a DISTRIBUTION
instead of a single path: percentile bands for total return / Sharpe /
max drawdown, probability of loss, and the average compounded curve that
the README visual draws as its red center line.

Two resampling methods:
- "block" (default): stationary block bootstrap - contiguous chunks of
  `block_size` days are resampled with replacement, preserving the
  short-horizon autocorrelation/volatility clustering a naive i.i.d.
  shuffle would erase.
- "iid": element-wise resampling - the classical Monte Carlo baseline.

Pure: numpy only, no I/O, no torch, deterministic given (`seed`, inputs).
The heavy per-run curve matrix is returned DOWNSAMPLED (`n_plot_points`)
so callers can persist it without multi-megabyte payloads.
"""

from __future__ import annotations

from typing import Any

import numpy as np

TRADING_DAYS_PER_YEAR = 252


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    drawdown = 1.0 - equity / peak
    return float(drawdown.max()) if drawdown.size else 0.0


def _annualized_sharpe(sampled_returns: np.ndarray) -> float:
    if sampled_returns.size < 2:
        return 0.0
    std = sampled_returns.std(ddof=1)
    if std == 0:
        return 0.0
    return float(sampled_returns.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR))


def _resample_indices(n: int, block_size: int, method: str, rng: np.random.Generator) -> np.ndarray:
    if method == "iid":
        return rng.integers(0, n, n)
    n_blocks = int(np.ceil(n / block_size))
    starts = rng.integers(0, n, size=n_blocks)
    idx = (starts[:, None] + np.arange(block_size)[None, :]).ravel()
    return idx[:n] % n


def _percentiles(values: np.ndarray) -> dict[str, float]:
    pct = np.percentile(values, [5, 25, 50, 75, 95])
    keys = ["p5", "p25", "p50", "p75", "p95"]
    return {k: round(float(v), 6) for k, v in zip(keys, pct)}


def run_monte_carlo(
    per_date_net_returns,
    *,
    n_runs: int = 1000,
    block_size: int = 20,
    seed: int = 42,
    method: str = "block",
    n_plot_points: int = 500,
) -> dict[str, Any]:
    """Runs the bootstrap and returns a self-describing result dict:

    {"config": {...},
     "status": "OK" | "SKIPPED: <reason>",
     "avg_curve": [...],                       # downsampled, red line
     "pct_band": {"p5": [...], "p25": [...], "p75": [...], "p95": [...]},
     "runs_curves": np.ndarray (n_runs x points),   # downsampled, for PNG
     "final_return_pct": {...percentiles}, "sharpe": {...}, "max_drawdown": {...},
     "prob_negative_return": float, "best_run_total_return": ..., "worst_run_total_return": ...}

    Equity curves are compounded from resampled daily returns and start at
    1.0. The average curve is the element-wise MEAN over all runs (the red
    line), NOT the mean of final values.
    """
    config = {
        "n_runs": int(n_runs),
        "block_size": int(block_size),
        "seed": int(seed),
        "method": str(method),
        "trading_days_per_year": TRADING_DAYS_PER_YEAR,
    }
    empty = {
        "config": config,
        "status": "",
        "avg_curve": [],
        "pct_band": {},
        "final_return_pct": {},
        "sharpe": {},
        "max_drawdown": {},
        "prob_negative_return": None,
        "best_run_total_return": None,
        "worst_run_total_return": None,
    }
    returns = np.asarray(list(per_date_net_returns), dtype=float)
    returns = returns[~np.isnan(returns)]
    if returns.size < 30:
        empty["status"] = f"SKIPPED: need >= 30 daily returns, got {returns.size}"
        return empty
    if n_runs < 1:
        empty["status"] = "SKIPPED: n_runs < 1"
        return empty
    if method not in ("block", "iid"):
        empty["status"] = f"SKIPPED: unknown method {method}"
        return empty

    n = returns.size
    rng = np.random.default_rng(seed)

    plot_points = min(n, max(int(n_plot_points), 2))
    plot_idx = np.linspace(0, n - 1, plot_points).astype(int)

    curves = np.empty((int(n_runs), plot_points), dtype=float)
    final_returns = np.empty(int(n_runs))
    sharpes = np.empty(int(n_runs))
    drawdowns = np.empty(int(n_runs))

    for run in range(int(n_runs)):
        sampled = returns[_resample_indices(n, block_size, method, rng)]
        equity = np.cumprod(1.0 + sampled)
        sharpes[run] = _annualized_sharpe(sampled)
        drawdowns[run] = _max_drawdown(equity)
        final_returns[run] = equity[-1] - 1.0
        curves[run] = equity[plot_idx]

    # Normalize every plotted curve to start exactly at 1.0 for readability.
    starts = curves[:, [0]]
    starts[starts == 0] = 1.0
    curves = curves / starts

    avg_curve = curves.mean(axis=0)
    pct_band = {
        "p5": np.percentile(curves, 5, axis=0),
        "p25": np.percentile(curves, 25, axis=0),
        "p75": np.percentile(curves, 75, axis=0),
        "p95": np.percentile(curves, 95, axis=0),
    }

    def _round_list(arr: np.ndarray, digits: int = 6) -> list[float]:
        return [round(float(v), digits) for v in arr]

    return {
        "config": config,
        "status": "OK",
        "avg_curve": _round_list(avg_curve),
        "pct_band": {k: _round_list(v) for k, v in pct_band.items()},
        "runs_curves": curves,
        "final_return_pct": _percentiles(final_returns * 100.0),
        "sharpe": _percentiles(sharpes),
        "max_drawdown": _percentiles(drawdowns * 100.0),
        "prob_negative_return": round(float((final_returns < 0).mean()), 4),
        "best_run_total_return": round(float(final_returns.max()) * 100.0, 4),
        "worst_run_total_return": round(float(final_returns.min()) * 100.0, 4),
    }
