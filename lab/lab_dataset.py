"""The lab's datasets: features, forward rank targets and split labels in the production dataset's column layout, and the
sealed-holdout rule every lab read goes through.

A row of `aq dataset build` is (date, ticker): its features use closes up to that date (`features/feature_registry.py`),
its targets the closes after it (`evaluation/signal_tools.forward_rank_targets`), and its split comes from date windows
with the label horizon purged at each boundary: a train row whose 20-day label reaches into validation is labelled
`purged`, kept for the sequence windows and never fitted or scored.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from evaluation.signal_tools import forward_rank_targets
from features import feature_registry

SPLITS = ("train", "validation", "backtest", "holdout")
PURGED = "purged"
ID_COLUMNS = ("date", "ticker", "close", "split")


class HoldoutSealed(PermissionError):
    """A lab read reached a sealed holdout row."""


def parse_splits(text: str) -> dict[str, tuple[str, str]]:
    """'train:2021-06-01..2023-12-31,validation:2024-01-01..2024-12-31' -> {split: (start, end)} (ISO dates, inclusive)."""
    out: dict[str, tuple[str, str]] = {}
    for part in [item.strip() for item in text.split(",") if item.strip()]:
        name, _, span = part.partition(":")
        start, _, end = span.partition("..")
        if name not in SPLITS or not start or not end:
            raise ValueError(f"bad split {part!r}: write NAME:START..END with NAME in {', '.join(SPLITS)}")
        pd.Timestamp(start), pd.Timestamp(end)
        out[name] = (start, end)
    return out


def default_splits(dates: Sequence[str]) -> dict[str, tuple[str, str]]:
    """60% train, 20% validation, 20% backtest of the dates in order (no holdout)."""
    ordered = sorted(set(dates))
    if len(ordered) < 10:
        raise ValueError("need at least 10 dates to split")
    first, second = int(len(ordered) * 0.6), int(len(ordered) * 0.8)
    return {"train": (ordered[0], ordered[first - 1]), "validation": (ordered[first], ordered[second - 1]), "backtest": (ordered[second], ordered[-1])}


def label_splits(dates: pd.Series, windows: Mapping[str, tuple[str, str]], *, horizon: int, calendar: Sequence[str]) -> pd.Series:
    """Each date's split; `purged` when its `horizon`-session label reaches past its own window's end (kept, so a sequence
    model's window still sees that date as live does, but never fitted or scored); None outside every window."""
    order = {date: index for index, date in enumerate(sorted(set(calendar)))}
    labels = pd.Series([None] * len(dates), index=dates.index, dtype=object)
    positions = dates.map(order)
    for name, (start, end) in windows.items():
        inside = (dates >= start) & (dates <= end)
        ends = [index for date, index in order.items() if date <= end]
        last = max(ends) if ends else -1
        labels[inside] = "purged"
        labels[inside & (positions + horizon <= last)] = name
    return labels


def build_dataset(closes: pd.DataFrame, *, features: str | Sequence[str] = "core", targets: Sequence[int] = (5, 20),
                  splits: Mapping[str, tuple[str, str]] | None = None, min_names: int = 3) -> pd.DataFrame:
    """The long dataset: `date, ticker, close, <features>, target_return_*, target_rank_*d, target_direction_20d, split`."""
    names = feature_registry.resolve(features)
    closes = closes.sort_index()
    closes.index = closes.index.astype(str)
    feats = feature_registry.build_long(closes, names)
    horizons = sorted({int(horizon) for horizon in targets})
    target = forward_rank_targets(closes, horizons).drop(columns=["split"])
    frame = feats.merge(target, on=["date", "ticker"], how="inner")
    price = closes.stack(future_stack=True).rename("close").reset_index()
    price.columns = ["date", "ticker", "close"]
    frame = frame.merge(price.astype({"date": str, "ticker": str}), on=["date", "ticker"], how="left")
    longest = max(horizons)
    frame[f"target_direction_{longest}d"] = (frame[f"target_return_{longest}d"] > 0).astype(float).where(frame[f"target_return_{longest}d"].notna())
    windows = dict(splits or default_splits(list(closes.index)))
    frame["split"] = label_splits(frame["date"], windows, horizon=longest, calendar=list(closes.index))
    frame = frame[frame["split"].notna()]
    counts = frame.groupby("date")["ticker"].transform("count")
    frame = frame[counts >= min_names]
    ordered = ["date", "ticker", "close", *names, *[column for column in frame.columns if column.startswith("target_")], "split"]
    return frame[ordered].sort_values(["date", "ticker"]).reset_index(drop=True)


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """The dataset's feature columns: everything that is not an id, the close, a target or the split."""
    return [column for column in frame.columns if column not in ID_COLUMNS and not column.startswith("target_") and not column.startswith("_")]


def target_columns(frame: pd.DataFrame) -> list[str]:
    """The dataset's target columns (`target_*`)."""
    return [column for column in frame.columns if column.startswith("target_")]


def holdout_window(config: Mapping[str, Any]) -> tuple[str, str] | None:
    """The project config's holdout window, found by key wherever the split windows live."""
    stack: list[Any] = [config]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            holdout = node.get("holdout")
            if isinstance(holdout, Mapping) and "start" in holdout and "end" in holdout and ("validation" in node or "backtest" in node):
                return str(holdout["start"]), str(holdout["end"])
            stack.extend(node.values())
    return None


def seal(frame: pd.DataFrame, *, window: tuple[str, str] | None = None, allow: bool = False) -> pd.DataFrame:
    """`frame` without sealed rows: split == 'holdout', and (for the project's data) any date inside `window`.
    With `allow` the rows stay: only `aq lab eval --holdout --i-understand-this-spends-it`, after recording the spend."""
    if allow:
        return frame
    keep = pd.Series(True, index=frame.index)
    if "split" in frame.columns:
        keep &= frame["split"].astype(str) != "holdout"
    if window is not None and "date" in frame.columns:
        dates = frame["date"].astype(str)
        keep &= ~((dates >= window[0]) & (dates <= window[1]))
    return frame[keep]


def load_dataset(path: Path, *, project_config: Path | None = None, allow_holdout: bool = False) -> pd.DataFrame:
    """Read a dataset CSV with its sealed rows removed. A project dataset (under `ml/datasets/`) also drops the config's
    holdout window, since its rows carry no `holdout` label."""
    frame = pd.read_csv(path, dtype={"date": str, "ticker": str}, low_memory=False)
    window = None
    if project_config is not None and project_config.exists():
        window = holdout_window(json.loads(project_config.read_text(encoding="utf-8")))
    return seal(frame, window=window, allow=allow_holdout)


def dataset_info(frame: pd.DataFrame) -> dict[str, Any]:
    """Rows, dates, tickers, splits with windows, features with their NaN share, targets, label balance, holdout present."""
    splits = {}
    for name, part in frame.groupby("split") if "split" in frame.columns else []:
        splits[str(name)] = {"rows": len(part), "start": str(part["date"].min()), "end": str(part["date"].max())}
    features = feature_columns(frame)
    direction = [column for column in frame.columns if column.startswith("target_direction")]
    return {
        "rows": len(frame), "dates": int(frame["date"].nunique()) if "date" in frame else 0, "tickers": int(frame["ticker"].nunique()) if "ticker" in frame else 0,
        "splits": splits, "features": {name: round(float(frame[name].isna().mean()), 4) for name in features},
        "targets": target_columns(frame),
        "label_balance": {name: round(float(frame[name].mean()), 4) for name in direction},
        "holdout_rows": int((frame["split"] == "holdout").sum()) if "split" in frame.columns else 0,
    }


def leakage_report(frame: pd.DataFrame, *, target: str = "target_rank_20d", horizon: int = 20) -> dict[str, Any]:
    """`evaluation/leakage_audit.audit_leakage` on a lab dataset (tail NaN, label shuffle, single-feature IC, asset prior)."""
    from evaluation.leakage_audit import audit_leakage

    data = frame.copy()
    if "_class" not in data.columns:
        data["_class"] = "all"
    return audit_leakage(data, feature_columns=feature_columns(frame), target_column=target, horizon=horizon, min_names=max(3, min(20, int(data.groupby("date")["ticker"].count().median()))))


def rank_features(frame: pd.DataFrame, names: Sequence[str]) -> np.ndarray:
    """Within-date percentile ranks minus one half (missing = 0), float32: the inputs every lab model reads."""
    data = frame.copy()
    data["_class"] = data.get("_class", "all")
    from features.training_splits import rank_inputs

    return rank_inputs(data, list(names)).to_numpy(dtype=np.float32)
