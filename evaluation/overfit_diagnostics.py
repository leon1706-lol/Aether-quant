"""Overfitting diagnostics (V6.4.3): how much of a model's in-sample rank IC survives out of sample, and how the
out-of-sample IC moves with the length of the training window. Pure; reads only the JSON files it is given."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

RANK_HEADS = ("rank_5d", "rank_20d", "sector_neutral_rank_20d", "residual_rank_5d", "residual_rank_20d")


def head_ic(metrics: dict[str, Any], split: str, head: str) -> float | None:
    """`<split>.<head>_ic_non_overlapping.mean_ic` of a training-metrics file (the daily `<head>_ic` as a fallback)."""
    node = metrics.get(split) or {}
    for key in (f"{head}_ic_non_overlapping", f"{head}_ic"):
        value = (node.get(key) or {}).get("mean_ic")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def training_gap_report(metrics_paths: dict[str, Path], heads: Sequence[str]=RANK_HEADS, splits: Sequence[str]=("train", "validation", "backtest")) -> dict[str, Any]:
    """{model: {head: {split: ic, "train_minus_validation": gap, "retained": validation / train}}} from
    ml/<model>_training_metrics.json files."""
    report: dict = {}
    for model, path in metrics_paths.items():
        try:
            metrics = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report[model] = {"error": f"unreadable {path}"}
            continue
        entry: dict = {}
        for head in heads:
            values: dict = {split: head_ic(metrics, split, head) for split in splits}
            if all(value is None for value in values.values()):
                continue
            train, validation = values.get("train"), values.get("validation")
            if train is not None and validation is not None:
                values["train_minus_validation"] = train - validation
                values["retained"] = validation / train if train else None
            entry[head] = values
        report[model] = entry
    return report


def learning_curve(fit_and_score: Callable[[pd.DataFrame, pd.DataFrame], float], frame: pd.DataFrame, *, train_years: Sequence[int]=(1, 2, 4, 7),
                   train_end: str = "2021-12-31", eval_split: str = "validation", date_column: str = "date",
                   split_column: str = "split") -> list[dict]:
    """Out-of-sample score for training windows of `train_years` years ending at `train_end`; `fit_and_score(train,
    evaluation)` fits on the first frame and returns a score (e.g. mean rank IC) on the second."""
    dates = pd.to_datetime(frame[date_column])
    evaluation = frame[frame[split_column] == eval_split]
    end = pd.Timestamp(train_end)
    curve = []
    for years in train_years:
        start = end - pd.DateOffset(years=int(years))
        train = frame[(frame[split_column] == "train") & (dates > start) & (dates <= end)]
        if train.empty:
            continue
        curve.append({"train_years": int(years), "train_rows": int(len(train)), "score": float(fit_and_score(train, evaluation))})
    return curve
