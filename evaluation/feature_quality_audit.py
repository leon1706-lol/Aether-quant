"""Model-input feature quality audit (V5.8.0).

Two V5.7/V5.8 findings were feature defects no metric surfaced: `bond_empirical_duration_beta` was one OLS slope over
the whole 2014-2021 history broadcast to every row (a leak that also acts as a ticker ID), and the volume/spread family
is constant for forex (Yahoo forex volume is 0), so the model had nothing forex-specific to rank on. This audit flags
both classes mechanically, per feature:

  * `ticker_constant_share` - share of tickers whose value never changes across their rows (ticker-ID / leak suspect),
  * `class_constant` - per asset class, whether the feature has (near) zero cross-sectional variance on most dates,
  * `daily_ic` - mean univariate daily rank IC against the target, per split (sign stability across splits matters more
    than size for a single feature),
  * `permutation_drop` (optional) - validation IC drop of the model when the feature is shuffled within dates.

Pure pandas/numpy; the model is passed in as a callable so this stays torch-free.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def _daily_ic(frame: pd.DataFrame, column: str, target: str, date_column: str, min_names: int) -> float | None:
    values = []
    for _date, day in frame[[date_column, column, target]].dropna().groupby(date_column):
        if len(day) < min_names:
            continue
        x = day[column].rank().to_numpy()
        y = day[target].rank().to_numpy()
        if np.ptp(x) == 0.0 or np.ptp(y) == 0.0:
            continue
        value = float(np.corrcoef(x, y)[0, 1])
        if np.isfinite(value):
            values.append(value)
    return float(np.mean(values)) if values else None


def feature_quality(
    frame: pd.DataFrame,
    features: list[str],
    *,
    target: str = "target_rank_20d",
    split_column: str = "split",
    class_column: str = "asset_class",
    ticker_column: str = "ticker",
    date_column: str = "date",
    min_names: int = 10,
    constant_tolerance: float = 1e-12,
    constant_date_share: float = 0.9,
) -> dict:
    """Per-feature diagnostics over `frame` (rows of every split). Returns {feature: {...}} plus a `flags` summary."""
    report: dict[str, dict] = {}
    splits = [split for split in ("train", "validation", "backtest") if split in set(frame[split_column].unique())]
    for feature in features:
        if feature not in frame.columns:
            continue
        column = pd.to_numeric(frame[feature], errors="coerce")
        data = frame[[ticker_column, date_column, class_column, split_column, target]].assign(value=column)
        per_ticker_unique = data.groupby(ticker_column)["value"].nunique(dropna=True)
        ticker_constant_share = float((per_ticker_unique <= 1).mean()) if len(per_ticker_unique) else 0.0
        class_constant = {}
        for kind, group in data.groupby(class_column):
            per_date_std = group.groupby(date_column)["value"].std(ddof=0).dropna()
            if len(per_date_std):
                class_constant[str(kind)] = bool((per_date_std <= constant_tolerance).mean() >= constant_date_share)
        daily_ic = {
            split: _daily_ic(data[data[split_column] == split], "value", target, date_column, min_names) for split in splits
        }
        signs = {np.sign(value) for value in daily_ic.values() if value is not None and abs(value) > 1e-4}
        report[feature] = {
            "missing_share": float(column.isna().mean()),
            "ticker_constant_share": round(ticker_constant_share, 4),
            "class_constant": class_constant,
            "daily_ic": daily_ic,
            "ic_sign_stable": len(signs) <= 1,
        }
    flags = {
        "ticker_id_suspects": sorted(f for f, r in report.items() if r["ticker_constant_share"] >= 0.5),
        "constant_for_class": {
            kind: sorted(f for f, r in report.items() if r["class_constant"].get(kind))
            for kind in sorted({k for r in report.values() for k in r["class_constant"]})
        },
        "ic_sign_unstable": sorted(f for f, r in report.items() if not r["ic_sign_stable"]),
    }
    return {"features": report, "flags": flags}


def permutation_ic_drop(
    frame: pd.DataFrame,
    features: list[str],
    predict: Callable[[pd.DataFrame], np.ndarray],
    *,
    target: str = "target_rank_20d",
    date_column: str = "date",
    min_names: int = 10,
    seed: int = 7,
) -> dict[str, float | None]:
    """Mean daily IC of `predict(frame)` minus the IC after shuffling one feature WITHIN each date (keeps the per-date
    distribution, breaks the link to the row). Positive = the model uses the feature."""
    rng = np.random.default_rng(seed)
    base_scores = frame.assign(_score=predict(frame))
    base = _daily_ic(base_scores, "_score", target, date_column, min_names)
    drops: dict[str, float | None] = {}
    for feature in features:
        if feature not in frame.columns or base is None:
            drops[feature] = None
            continue
        shuffled = frame.copy()
        shuffled[feature] = shuffled.groupby(date_column)[feature].transform(
            lambda values: values.to_numpy()[rng.permutation(len(values))]
        )
        scored = shuffled.assign(_score=predict(shuffled))
        value = _daily_ic(scored, "_score", target, date_column, min_names)
        drops[feature] = None if value is None else float(base - value)
    return drops


def select_feature_subset(
    features: list[str],
    *,
    permutation_drop: dict[str, float | None],
    early_ic: dict[str, float | None],
    late_ic: dict[str, float | None],
    ticker_id_suspects: list[str],
    min_abs_ic: float = 0.002,
) -> dict:
    """V6.2.0 smaller input set, chosen on the TRAIN split only (validation stays the judge). A feature is kept when the
    installed model uses it (permutation drop > 0 on the late train window), its own daily IC has the same sign and at
    least `min_abs_ic` size in both train halves (an in-sample drop alone keeps almost everything an overfit model
    touches), and it is not a ticker-ID suspect. Order follows `features` (the live vector's)."""
    kept, reasons = [], {}
    suspects = set(ticker_id_suspects)
    for feature in features:
        drop, early, late = permutation_drop.get(feature), early_ic.get(feature), late_ic.get(feature)
        if feature in suspects:
            reasons[feature] = "ticker_id_suspect"
        elif drop is None or drop <= 0.0:
            reasons[feature] = "unused_by_model"
        elif early is None or late is None or abs(early) < min_abs_ic or abs(late) < min_abs_ic or np.sign(early) != np.sign(late):
            reasons[feature] = "unstable_train_ic"
        else:
            kept.append(feature)
    return {"kept": kept, "dropped": reasons}
