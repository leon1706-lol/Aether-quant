"""evaluation/feature_quality_audit.py (V5.8.0): ticker-ID / class-constant / sign-unstable features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.feature_quality_audit import feature_quality, permutation_ic_drop


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
