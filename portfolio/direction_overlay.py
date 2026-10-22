"""Direction-probability overlay on the cross-sectional rank (V6.4.0, lead L2; default off).

The rank heads alone drive the book. If a head's direction probability is calibrated well enough to add information, it is
applied here to the percentile ranks the book is built from, in one of two ways, both within each rank group:

    blend         rank + weight * z(calibrated probability - 0.5), re-ranked to a percentile
    agree_filter  a long candidate (rank >= the group median) needs p >= 0.5 - margin, a short candidate (below it)
                  needs p <= 0.5 + margin; a name that disagrees is moved to the group median rank, i.e. out of the book

Pure Python (no numpy), so `main.py` and the offline simulator call the same function. `calibration` is the fitted map
from `evaluation.probability_calibration` ({"method": "temperature", "temperature": T} or {"method": "isotonic", "x": [...],
"y": [...]}); none = the raw probability.
"""

from __future__ import annotations

import math
from bisect import bisect_right

from portfolio.rank_signal import MAIN_RANK_GROUP, cross_sectional_rank_scores

MODES = ("blend", "agree_filter")


def resolve_direction_overlay(raw: dict | None) -> dict | None:
    """`phase_v2.rank_signal.direction_overlay` -> params, or None when absent / disabled / malformed (the shipped book)."""
    if not isinstance(raw, dict) or not bool(raw.get("enabled", False)) or str(raw.get("mode", "")) not in MODES:
        return None
    return {"mode": str(raw["mode"]), "weight": float(raw.get("weight", 0.0)), "margin": float(raw.get("margin", 0.0)),
            "calibration": raw.get("calibration") if isinstance(raw.get("calibration"), dict) else None}


def calibrate_probability(probability: float, calibration: dict | None) -> float:
    """The fitted map applied to one probability; unknown or missing maps leave it unchanged."""
    p = min(max(float(probability), 1e-12), 1.0 - 1e-12)
    if not calibration:
        return p
    method = calibration.get("method")
    if method == "temperature":
        temperature = float(calibration.get("temperature", 1.0))
        return 1.0 / (1.0 + math.exp(-math.log(p / (1.0 - p)) / temperature)) if temperature > 0.0 else p
    if method == "isotonic":
        xs, ys = calibration.get("x") or [], calibration.get("y") or []
        if len(xs) != len(ys) or not xs:
            return p
        if p <= xs[0]:
            return float(ys[0])
        if p >= xs[-1]:
            return float(ys[-1])
        right = bisect_right(xs, p)
        x0, x1, y0, y1 = xs[right - 1], xs[right], ys[right - 1], ys[right]
        return float(y0 + (y1 - y0) * (p - x0) / (x1 - x0)) if x1 > x0 else float(y1)
    return p


def _z_scores(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 2:
        return dict.fromkeys(values, 0.0)
    mean = sum(values.values()) / len(values)
    variance = sum((value - mean) ** 2 for value in values.values()) / (len(values) - 1)
    std = math.sqrt(variance)
    return dict.fromkeys(values, 0.0) if std <= 1e-12 else {symbol: (value - mean) / std for symbol, value in values.items()}


def apply_direction_overlay(
    ranks: dict[str, float], probabilities: dict[str, float | None], params: dict | None,
    group_by_symbol: dict[str, str] | None = None,
) -> dict[str, float]:
    """The overlay on one bar's percentile `ranks` ({symbol: rank}); `params` from `resolve_direction_overlay` (None or an
    empty rank dict returns `ranks` untouched). Symbols without a probability keep their rank (z = 0 / no filter)."""
    if not params or not ranks:
        return dict(ranks)
    groups: dict[str, dict[str, float]] = {}
    for symbol, rank in ranks.items():
        groups.setdefault((group_by_symbol or {}).get(str(symbol), MAIN_RANK_GROUP), {})[symbol] = rank
    result: dict[str, float] = {}
    for group in groups.values():
        centred = {
            symbol: calibrate_probability(probabilities[symbol], params["calibration"]) - 0.5
            for symbol in group if probabilities.get(symbol) is not None and math.isfinite(float(probabilities[symbol]))
        }
        if params["mode"] == "blend":
            z = _z_scores(centred)
            combined = {symbol: rank + params["weight"] * z.get(symbol, 0.0) for symbol, rank in group.items()}
            result.update(cross_sectional_rank_scores(combined) or group)
        else:
            ordered = sorted(group.values())
            middle = len(ordered) // 2
            median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
            margin = params["margin"]
            for symbol, rank in group.items():
                p = centred.get(symbol)
                if p is not None and ((rank >= median and p < -margin) or (rank < median and p > margin)):
                    result[symbol] = median
                else:
                    result[symbol] = rank
    return result
