"""Volatility targeting (V6.6.5, #345): scale a book to an ex-ante annual volatility, never beyond a leverage cap.

The trend sleeve's own per-coin targeting is `portfolio.trend_sleeve.annualised_vol`; this is the general, whole-book version.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

__all__ = ["realized_vol", "volatility_target_weights"]


def realized_vol(returns: pd.Series, *, window: int = 20, annualization: int = 252) -> pd.Series:
    """Rolling sample standard deviation of `returns` times `sqrt(annualization)`; NaN until `window` finite values."""
    clean = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return clean.rolling(int(window), min_periods=int(window)).std(ddof=1) * math.sqrt(float(annualization))


def volatility_target_weights(weights: Mapping[str, float], cov: pd.DataFrame, *, target_annual_vol: float, max_leverage: float = 1.0,
                              annualization: int = 252) -> dict[str, float]:
    """Scale `weights` so that `sqrt(w' cov w * annualization)` equals `target_annual_vol` (`cov` is of per-period returns),
    then cap gross exposure at `max_leverage`. A name missing from `cov` is dropped; a non-finite or zero risk returns the
    weights capped but unscaled."""
    names = [name for name in weights if name in cov.index and name in cov.columns]
    w = np.array([float(weights[name]) for name in names], dtype=float)
    w = np.where(np.isfinite(w), w, 0.0)
    cap = abs(float(max_leverage))
    if not names or not math.isfinite(cap):
        return {name: 0.0 for name in names}
    matrix = cov.loc[names, names].to_numpy(float)
    variance = float(w @ matrix @ w) * float(annualization) if np.all(np.isfinite(matrix)) else float("nan")
    target = float(target_annual_vol)
    scale = target / math.sqrt(variance) if math.isfinite(variance) and variance > 0.0 and math.isfinite(target) and target > 0.0 else 1.0
    scaled = w * scale
    gross = float(np.abs(scaled).sum())
    if gross > cap and gross > 0.0:
        scaled = scaled * (cap / gross)
    return {name: float(value) for name, value in zip(names, scaled)}
