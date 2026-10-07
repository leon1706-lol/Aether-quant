"""Calibrates `phase_v2.topology.elevated_volatility_threshold` per asset class
(V5.5.0, Problems.md #129).

topology/market_topology.py marks a node "elevated" when its annualized
volatility reaches one global cutoff (0.45), and the analyzer's Priority 3
then cancels every directional signal for it. Crypto's annualized volatility
sits structurally above 0.45, so under a single cutoff BTC/LTC were
permanently "elevated": 13 of their 26 book selections in the 2026-08-27
backtest died on `topology_elevated_volatility_pressure_overrides_directional_signal`.
The cutoff exists to flag a name that is unusually volatile FOR ITS OWN
CLASS, so the right level is a per-class percentile of the realized volatility
distribution, measured with the exact statistic the topology computes
(sample std of the last `window` daily returns x sqrt(252)).

Pure pandas/numpy; no I/O.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

ANNUALIZATION_FACTOR = math.sqrt(252)


def rolling_annualized_volatility(
    frame: pd.DataFrame,
    *,
    window: int = 24,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "close",
) -> pd.Series:
    """Per-row annualized volatility of the previous `window` daily returns.
    main.py keeps a 25-close deque per symbol, i.e. 24 returns, which is the
    default here. Aligned to `frame`'s index; NaN until a full window."""
    ordered = frame.sort_values([ticker_column, date_column])
    returns = ordered.groupby(ticker_column)[close_column].pct_change()
    volatility = (
        returns.groupby(ordered[ticker_column]).rolling(window, min_periods=window).std(ddof=1)
        .reset_index(level=0, drop=True)
        * ANNUALIZATION_FACTOR
    )
    return volatility.reindex(frame.index)


def calibrate_elevated_volatility_thresholds(
    frame: pd.DataFrame,
    asset_class_by_ticker: dict[str, str],
    *,
    percentile: float = 0.80,
    window: int = 24,
    current_default: float = 0.45,
    min_samples: int = 60,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "close",
) -> dict:
    """Per-asset-class `percentile` of rolling annualized volatility, plus a
    `suggested_config` holding only classes whose percentile EXCEEDS
    `current_default` (a class already below the global cutoff needs no
    override). Classes with fewer than `min_samples` observations are
    reported but never suggested."""
    if close_column not in frame.columns:
        return {"status": "SKIPPED", "reason": f"no {close_column!r} column in dataset"}
    working = frame[[ticker_column, date_column, close_column]].copy()
    working["_volatility"] = rolling_annualized_volatility(
        frame, window=window, ticker_column=ticker_column, date_column=date_column, close_column=close_column
    )
    working["_asset_class"] = working[ticker_column].astype(str).map(asset_class_by_ticker)
    working = working.dropna(subset=["_volatility", "_asset_class"])

    by_class: dict[str, dict] = {}
    suggested: dict[str, float] = {}
    for asset_class, group in working.groupby("_asset_class"):
        values = group["_volatility"].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        level = float(np.quantile(values, percentile))
        share_above_default = float((values >= current_default).mean())
        by_class[str(asset_class)] = {
            "num_samples": int(values.size),
            f"p{int(round(percentile * 100))}": round(level, 4),
            "median": round(float(np.median(values)), 4),
            "share_at_or_above_current_default": round(share_above_default, 4),
        }
        if values.size >= min_samples and level > current_default:
            suggested[str(asset_class)] = round(level, 4)

    return {
        "status": "OK",
        "percentile": percentile,
        "window_returns": window,
        "current_default": current_default,
        "by_asset_class": by_class,
        "suggested_config": {"default": current_default, **dict(sorted(suggested.items()))},
    }
