"""Within- vs between-asset-class rank-IC decomposition (V5.8.0).

The pooled rank IC of the book's head mixes two different bets: ranking names WITHIN an asset class (what a sector- or
class-neutral book monetises) and ranking the CLASSES against each other (bonds below equities in a sell-off, which is a
market-direction bet in a dollar-neutral book). On the 2021-25 holdout the pooled rank_20d IC was +0.069 while the
within-bond IC was -0.001, so a pooled number alone cannot say whether a sleeve has an edge.

Per date this reports the pooled IC, the within-class IC of every class with enough names, and the between-class IC
(class-mean prediction vs class-mean realized rank, needs >= 3 classes). Each series gets its mean, HAC t and date count.
Pure pandas/numpy, no I/O.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from evaluation.rank_ic_core import newey_west_t_stat


def _spearman(predictions: np.ndarray, targets: np.ndarray) -> float | None:
    if len(predictions) < 2:
        return None
    prediction_rank = pd.Series(predictions).rank().to_numpy()
    target_rank = pd.Series(targets).rank().to_numpy()
    if np.ptp(prediction_rank) == 0.0 or np.ptp(target_rank) == 0.0:
        return None
    value = float(np.corrcoef(prediction_rank, target_rank)[0, 1])
    return value if np.isfinite(value) else None


def _summary(values: list[float], horizon: int) -> dict:
    finite = [value for value in values if value is not None and np.isfinite(value)]
    return {
        "mean_ic": float(np.mean(finite)) if finite else None,
        "hac_t": newey_west_t_stat(finite, max(horizon - 1, 0)) if len(finite) >= 2 else 0.0,
        "num_dates": len(finite),
        "positive_share": float(np.mean([value > 0 for value in finite])) if finite else None,
    }


def class_ic_decomposition(
    frame: pd.DataFrame,
    *,
    prediction: str,
    target: str,
    class_column: str = "asset_class",
    date_column: str = "date",
    horizon: int = 20,
    min_names_per_class: int = 5,
    min_names_pooled: int = 10,
) -> dict:
    """`frame` has one row per ticker-date with a prediction, a realized target (a return or a per-date rank of it) and
    an asset class. Rows with a non-finite prediction or target are dropped. Returns
    {"pooled", "within": {class: summary}, "between", "within_weighted", "class_share_of_pooled"}."""
    columns = [date_column, class_column, prediction, target]
    data = frame[columns].copy()
    data = data[np.isfinite(data[prediction].astype(float)) & np.isfinite(data[target].astype(float))]
    pooled: list[float] = []
    between: list[float] = []
    within: dict[str, list[float]] = defaultdict(list)
    within_weighted: list[float] = []
    for _date, day in data.groupby(date_column, sort=True):
        if len(day) >= min_names_pooled:
            value = _spearman(day[prediction].to_numpy(float), day[target].to_numpy(float))
            if value is not None:
                pooled.append(value)
        weighted_sum, weight_total = 0.0, 0
        class_means = []
        for kind, group in day.groupby(class_column):
            if len(group) >= min_names_per_class:
                value = _spearman(group[prediction].to_numpy(float), group[target].to_numpy(float))
                if value is not None:
                    within[str(kind)].append(value)
                    weighted_sum += value * len(group)
                    weight_total += len(group)
            class_means.append((float(group[prediction].mean()), float(group[target].mean())))
        if weight_total:
            within_weighted.append(weighted_sum / weight_total)
        if len(class_means) >= 3:
            means = np.asarray(class_means)
            value = _spearman(means[:, 0], means[:, 1])
            if value is not None:
                between.append(value)
    pooled_summary = _summary(pooled, horizon)
    within_weighted_summary = _summary(within_weighted, horizon)
    share = None
    if pooled_summary["mean_ic"] and within_weighted_summary["mean_ic"] is not None:
        share = 1.0 - within_weighted_summary["mean_ic"] / pooled_summary["mean_ic"]
    return {
        "prediction": prediction,
        "target": target,
        "pooled": pooled_summary,
        "within": {kind: _summary(values, horizon) for kind, values in sorted(within.items())},
        "within_weighted": within_weighted_summary,
        "between": _summary(between, horizon),
        # 1 - within/pooled: how much of the pooled IC is NOT explained by ranking inside classes (None if pooled ~ 0)
        "class_share_of_pooled": share,
    }
