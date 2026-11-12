"""Kelly sizing (V6.6.5, #345): the growth-optimal fraction, shrunk by `fraction` (half Kelly by default) and capped.

Full Kelly is `mean / variance` for one bet and `inv(cov) @ mu` for many. Estimation error makes full Kelly far too large in
practice, so the default is half Kelly with a cap; a non-finite or degenerate input sizes to zero, never to a guess.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = ["kelly_fraction", "kelly_weights"]


def kelly_fraction(mean: float, variance: float, *, fraction: float = 0.5, cap: float = 1.0) -> float:
    """`fraction * mean / variance`, clipped to [-cap, cap]. Zero for a non-positive or non-finite variance or input."""
    try:
        mu, var, share, limit = float(mean), float(variance), float(fraction), abs(float(cap))
    except (TypeError, ValueError):
        return 0.0
    if not all(math.isfinite(value) for value in (mu, var, share, limit)) or var <= 0.0 or share <= 0.0:
        return 0.0
    return float(min(max(share * mu / var, -limit), limit))


def kelly_weights(mu: np.ndarray, cov: np.ndarray, *, fraction: float = 0.5, gross_cap: float = 1.0, ridge: float = 1e-8) -> np.ndarray:
    """`fraction * solve(cov + ridge*I, mu)`, scaled down (never up) so that `sum(|w|) <= gross_cap`. Zeros when an input
    is non-finite, the shapes disagree, or the system is singular."""
    mean = np.asarray(mu, dtype=float).ravel()
    matrix = np.asarray(cov, dtype=float)
    zeros = np.zeros_like(mean)
    if matrix.shape != (mean.size, mean.size) or not np.all(np.isfinite(mean)) or not np.all(np.isfinite(matrix)):
        return zeros
    share, cap = float(fraction), abs(float(gross_cap))
    if not math.isfinite(share) or share <= 0.0 or not math.isfinite(cap):
        return zeros
    try:
        raw = np.linalg.solve(matrix + max(float(ridge), 0.0) * np.eye(mean.size), mean)
    except np.linalg.LinAlgError:
        return zeros
    weights = share * raw
    if not np.all(np.isfinite(weights)):
        return zeros
    gross = float(np.abs(weights).sum())
    return weights * (cap / gross) if gross > cap and gross > 0.0 else weights
