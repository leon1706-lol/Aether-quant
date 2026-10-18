"""evaluation/feature_quality_audit.py (V5.8.0): ticker-ID / class-constant / sign-unstable features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.feature_quality_audit import feature_quality, permutation_ic_drop, select_feature_subset


def _frame(seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for split, days in (("train", range(0, 40)), ("validation", range(40, 60)), ("backtest", range(60, 80))):
        for day in days:
            for name in range(12):
                kind = "forex" if name < 4 else "equity"
                signal = rng.normal()
                rows.append({
                    "date": day, "ticker": f"T{name}", "asset_class": kind, "split": split,
                    "good": signal, "target_rank_20d": signal + 0.5 * rng.normal(),
                    "ticker_id": float(name),  # constant per ticker
                    "volume_z": 0.0 if kind == "forex" else rng.normal(),
                })
    return pd.DataFrame(rows)


def test_flags_ticker_constant_and_class_constant_features():
    report = feature_quality(_frame(), ["good", "ticker_id", "volume_z", "absent"], min_names=5)
    assert "absent" not in report["features"]
    assert report["flags"]["ticker_id_suspects"] == ["ticker_id"]
    assert report["flags"]["constant_for_class"]["forex"] == ["volume_z"]  # ticker_id varies ACROSS tickers on a date
    assert report["features"]["good"]["daily_ic"]["validation"] > 0.5 and report["features"]["good"]["ic_sign_stable"]


def test_permutation_drop_is_positive_for_a_used_feature_only():
    frame = _frame()
    drops = permutation_ic_drop(frame, ["good", "volume_z"], lambda f: f["good"].to_numpy(), min_names=5)
    assert drops["good"] > 0.5 and abs(drops["volume_z"]) < 1e-12


def test_the_v620_subset_keeps_used_stable_non_id_features_in_the_live_order():
    features = ["a", "b", "c", "d", "e"]
    subset = select_feature_subset(
        features,
        permutation_drop={"a": 0.01, "b": 0.0, "c": 0.02, "d": 0.03, "e": 0.01},
        early_ic={"a": 0.01, "b": 0.01, "c": 0.01, "d": -0.01, "e": 0.01},
        late_ic={"a": 0.02, "b": 0.02, "c": -0.01, "d": -0.02, "e": 0.0005},
        ticker_id_suspects=["a"],
    )
    assert subset["kept"] == ["d"]
    assert subset["dropped"] == {"a": "ticker_id_suspect", "b": "unused_by_model", "c": "unstable_train_ic",
                                 "e": "unstable_train_ic"}
