"""Probability calibration for the direction heads (V6.4.0, lead L2). numpy only, pure.

The multitask / sequence `direction_*` heads emit sigmoid probabilities at ~57-58% accuracy with a weak log-loss. This module
measures how honest those probabilities are (reliability curve, ECE, Brier, log-loss) and fits the two classic post-hoc maps
on a validation split only: temperature scaling (one parameter on the logit) and isotonic regression (pool adjacent
violators). `best_threshold_by_class` picks a per-class decision threshold by balanced accuracy.
"""

from __future__ import annotations

import math

import numpy as np

EPS = 1e-12


def _clean(probability, outcome) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(probability, dtype=float)
    y = np.asarray(outcome, dtype=float)
    keep = np.isfinite(p) & np.isfinite(y)
    return np.clip(p[keep], EPS, 1.0 - EPS), y[keep]


def log_loss(probability, outcome) -> float | None:
    p, y = _clean(probability, outcome)
    if len(p) == 0:
        return None
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def brier_score(probability, outcome) -> float | None:
    p, y = _clean(probability, outcome)
    return float(np.mean((p - y) ** 2)) if len(p) else None


def reliability_curve(probability, outcome, bins: int = 10) -> list[dict]:
    """Equal-width bins on [0, 1]: {"low", "high", "n", "mean_probability", "observed_rate"} for each non-empty bin."""
    p, y = _clean(probability, outcome)
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.minimum(np.digitize(p, edges[1:-1], right=False), bins - 1)
    rows = []
    for position in range(bins):
        mask = index == position
        if mask.any():
            rows.append({"low": float(edges[position]), "high": float(edges[position + 1]), "n": int(mask.sum()),
                         "mean_probability": float(p[mask].mean()), "observed_rate": float(y[mask].mean())})
    return rows


def expected_calibration_error(probability, outcome, bins: int = 10) -> float | None:
    """Sample-weighted mean |observed rate - mean probability| over the reliability bins."""
    rows = reliability_curve(probability, outcome, bins)
    total = sum(row["n"] for row in rows)
    if not total:
        return None
    return float(sum(row["n"] * abs(row["observed_rate"] - row["mean_probability"]) for row in rows) / total)


def _logit(p: np.ndarray) -> np.ndarray:
    return np.log(p / (1.0 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def apply_temperature(probability, temperature: float) -> np.ndarray:
    """sigmoid(logit(p) / T): T > 1 softens an over-confident head, T < 1 sharpens it, T = 1 is the identity."""
    p = np.clip(np.asarray(probability, dtype=float), EPS, 1.0 - EPS)
    return _sigmoid(_logit(p) / float(temperature))


def fit_temperature(probability, outcome, low: float = 0.05, high: float = 20.0, iterations: int = 80) -> float | None:
    """The temperature minimising log-loss: a golden-section search on log T (the loss is unimodal in it)."""
    p, y = _clean(probability, outcome)
    if len(p) < 10 or len(np.unique(y)) < 2:
        return None
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = math.log(low), math.log(high)
    c, d = b - ratio * (b - a), a + ratio * (b - a)

    def loss(log_t: float) -> float:
        return float(log_loss(apply_temperature(p, math.exp(log_t)), y))

    fc, fd = loss(c), loss(d)
    for _ in range(iterations):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = loss(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = loss(d)
    return float(math.exp((a + b) / 2.0))


def fit_isotonic(probability, outcome) -> dict | None:
    """Pool-adjacent-violators on outcomes sorted by probability: {"x": block means of p, "y": calibrated rates} (both
    non-decreasing). None for fewer than 10 usable rows or a single class."""
    p, y = _clean(probability, outcome)
    if len(p) < 10 or len(np.unique(y)) < 2:
        return None
    order = np.argsort(p, kind="mergesort")
    p, y = p[order], y[order]
    blocks = [[float(y[i]), 1.0, float(p[i])] for i in range(len(p))]  # [sum of y, count, sum of p]
    merged: list[list[float]] = []
    for block in blocks:
        merged.append(block)
        while len(merged) > 1 and merged[-2][0] / merged[-2][1] > merged[-1][0] / merged[-1][1]:
            top = merged.pop()
            merged[-1] = [merged[-1][0] + top[0], merged[-1][1] + top[1], merged[-1][2] + top[2]]
    return {"x": [block[2] / block[1] for block in merged], "y": [block[0] / block[1] for block in merged]}


def apply_isotonic(probability, fit: dict) -> np.ndarray:
    """Piecewise-linear interpolation through the fitted block means, flat outside the fitted range."""
    p = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    return np.interp(p, fit["x"], fit["y"])


def best_threshold_by_class(probability, outcome, classes, grid=None) -> dict[str, dict]:
    """{class: {"threshold", "balanced_accuracy", "n"}}: the threshold on `grid` (default 0.30..0.70 step 0.05) maximising
    balanced accuracy among that class's rows. A class lacking both outcomes, or with fewer than 20 rows, gets 0.5."""
    p = np.asarray(probability, dtype=float)
    y = np.asarray(outcome, dtype=float)
    labels = np.asarray([str(value) for value in classes])
    grid = np.arange(0.30, 0.701, 0.05) if grid is None else np.asarray(grid, dtype=float)
    out = {}
    for name in sorted(set(labels)):
        mask = (labels == name) & np.isfinite(p) & np.isfinite(y)
        pp, yy = p[mask], y[mask]
        if len(pp) < 20 or len(np.unique(yy)) < 2:
            out[name] = {"threshold": 0.5, "balanced_accuracy": None, "n": int(len(pp))}
            continue
        best = (-1.0, 0.5)
        for threshold in grid:
            call = pp >= threshold
            tpr = float(call[yy == 1].mean())
            tnr = float((~call)[yy == 0].mean())
            score = (tpr + tnr) / 2.0
            if score > best[0] + 1e-12:
                best = (score, float(threshold))
        out[name] = {"threshold": best[1], "balanced_accuracy": best[0], "n": int(len(pp))}
    return out


def balanced_accuracy(probability, outcome, threshold: float = 0.5) -> float | None:
    p, y = _clean(probability, outcome)
    if len(p) == 0 or len(np.unique(y)) < 2:
        return None
    call = p >= threshold
    return float((call[y == 1].mean() + (~call)[y == 0].mean()) / 2.0)


def cross_fitted_log_loss(probability, outcome, method: str) -> float | None:
    """Honest validation log-loss of a calibration method: fit on the first half (time order) and score the second, then
    swap, and average the two. `method` in {"raw", "temperature", "isotonic"}."""
    p, y = _clean(probability, outcome)
    half = len(p) // 2
    if half < 10:
        return None
    losses = []
    for fit_part, score_part in ((slice(0, half), slice(half, None)), (slice(half, None), slice(0, half))):
        scored = p[score_part]
        if method == "raw":
            calibrated = scored
        elif method == "temperature":
            temperature = fit_temperature(p[fit_part], y[fit_part])
            if temperature is None:
                return None
            calibrated = apply_temperature(scored, temperature)
        elif method == "isotonic":
            fit = fit_isotonic(p[fit_part], y[fit_part])
            if fit is None:
                return None
            calibrated = np.clip(apply_isotonic(scored, fit), 1e-6, 1.0 - 1e-6)
        else:
            raise ValueError(f"unknown calibration method {method!r}")
        losses.append(log_loss(calibrated, y[score_part]))
    return float(np.mean(losses))


def calibration_report(probability, outcome, classes=None, bins: int = 10) -> dict:
    """Everything the L2 decision needs for one head on one split: the raw measures, a reliability curve, both fitted maps
    with their cross-fitted log-loss, and the per-class thresholds."""
    p, y = _clean(probability, outcome)
    report = {
        "n": int(len(p)), "positive_rate": float(y.mean()) if len(y) else None,
        "log_loss": log_loss(p, y), "brier": brier_score(p, y), "ece": expected_calibration_error(p, y, bins),
        "reliability": reliability_curve(p, y, bins),
        "cross_fitted_log_loss": {method: cross_fitted_log_loss(p, y, method) for method in ("raw", "temperature", "isotonic")},
        "temperature": fit_temperature(p, y), "isotonic": fit_isotonic(p, y),
    }
    if classes is not None:
        keep = np.isfinite(np.asarray(probability, dtype=float)) & np.isfinite(np.asarray(outcome, dtype=float))
        report["thresholds_by_class"] = best_threshold_by_class(np.asarray(probability)[keep], np.asarray(outcome)[keep],
                                                                np.asarray(list(classes))[keep])
    return report
