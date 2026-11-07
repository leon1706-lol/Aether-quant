"""A walk-forward linear model of the characteristics (V6.6.1): Fama-MacBeth slopes, ridge-shrunk and held to a sign fixed in advance.

The neural and tree models read near-constant fundamentals in their early years (filings: 19 names in 2009, 292 in 2010, 466 in 2011), so they
behaved like price models. A monthly cross-sectional slope has no such problem, and with so few effective degrees of freedom it can barely
overfit. It starts as an equal-weight composite of the signs and leans on its own slopes only as labels arrive.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

MIN_SLOPE_MONTHS = 12
MIN_SLOPE_NAMES = 30


def _rank_matrix(features: Mapping[str, pd.DataFrame], names: list[str], index, columns) -> np.ndarray:
    """dates x tickers x features, each a cross-sectional rank centred at zero; a missing value reads as the middle."""
    layers = [features[name].reindex(index=index, columns=columns).rank(axis=1, pct=True).sub(0.5).to_numpy(dtype=float) for name in names]
    return np.stack(layers, axis=2)


def monthly_slope(ranks: np.ndarray, label: np.ndarray, *, ridge: float) -> np.ndarray | None:
    """One date's ridge slope of the label on the ranked features, on names with a label and at least one feature."""
    keep = np.isfinite(label) & np.isfinite(ranks).any(axis=1)
    if keep.sum() < MIN_SLOPE_NAMES:
        return None
    matrix = np.nan_to_num(ranks[keep], nan=0.0)
    target = label[keep] - np.mean(label[keep])
    return np.linalg.solve(matrix.T @ matrix + float(ridge) * np.eye(matrix.shape[1]), matrix.T @ target)


def fama_macbeth_ridge(
    features: Mapping[str, pd.DataFrame], label: pd.DataFrame, *, signs: Mapping[str, float], kappa: int = 36, ridge: float = 1.0, horizon: int = 21,
    purge_sessions: int = 21, every: int = 21, start: str,
) -> pd.DataFrame:
    """Session x ticker scores from `start`. The score at D is the features at D times the mean of the last `kappa` monthly slopes whose label had
    fully ended by D - `purge_sessions`. A mean slope whose sign disagrees with `signs` counts as zero, so noise can't flip a published premium, and
    with every slope at zero the row is NaN. With fewer than `MIN_SLOPE_MONTHS` slopes it uses the signs as equal weights."""
    names = sorted(signs)
    missing = [name for name in names if name not in features]
    if missing:
        raise KeyError(f"features {missing} are not in this cell")
    index, columns = list(label.index), list(label.columns)
    ranks = _rank_matrix(features, names, index, columns)
    prior = np.array([float(signs[name]) for name in names])
    labels = label.to_numpy(dtype=float)
    position = {date: row for row, date in enumerate(index)}
    if start not in position:
        later = [row for row, date in enumerate(index) if date >= start]
        if not later:
            return pd.DataFrame(np.nan, index=index, columns=columns, dtype=float)
        first = later[0]
    else:
        first = position[start]
    slope_rows = list(range(0, len(index), max(1, int(every))))
    slopes: dict[int, np.ndarray] = {}
    out = np.full(labels.shape, np.nan)
    for row in range(first, len(index)):
        usable = [slope_row for slope_row in slope_rows if slope_row + int(horizon) + int(purge_sessions) <= row]
        for slope_row in usable[-int(kappa):]:
            if slope_row not in slopes:
                value = monthly_slope(ranks[slope_row], labels[slope_row], ridge=ridge)
                slopes[slope_row] = np.full(len(names), np.nan) if value is None else value
        recent = [slopes[slope_row] for slope_row in usable[-int(kappa):] if np.isfinite(slopes[slope_row]).all()]
        if len(recent) < MIN_SLOPE_MONTHS:
            weights = prior
        else:
            mean = np.mean(recent, axis=0)
            weights = np.where(np.sign(mean) == np.sign(prior), mean, 0.0)
            if not np.any(weights):
                continue  # every slope disagrees with its prior: no view today, not a bet against the evidence
        present = np.isfinite(ranks[row]).any(axis=1)
        scored = np.nan_to_num(ranks[row], nan=0.0) @ weights
        out[row, present] = scored[present]
    return pd.DataFrame(out, index=index, columns=columns)
