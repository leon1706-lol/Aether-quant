"""evaluation/class_ic_audit.py (V5.8.0): within- vs between-class rank IC."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.class_ic_audit import class_ic_decomposition


def _frame(within_signal: bool, between_signal: bool, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    class_level = {"equity": 0.02, "bond": -0.02, "crypto": 0.05}
    for day in range(60):
        for kind, level in class_level.items():
            for name in range(8):
                noise = rng.normal()
                realized = (level if between_signal else 0.0) + 0.01 * noise
                prediction = (noise if within_signal else rng.normal()) + (level * 100 if between_signal else 0.0)
                rows.append({"date": f"2024-01-{day:02d}", "asset_class": kind, "ticker": f"{kind}{name}",
                             "prediction": prediction, "target": realized})
    return pd.DataFrame(rows)


def test_pure_within_class_skill_shows_in_within_not_between():
    report = class_ic_decomposition(_frame(within_signal=True, between_signal=False), prediction="prediction", target="target")
    assert report["within"]["equity"]["mean_ic"] == pytest.approx(1.0)
    assert report["within_weighted"]["mean_ic"] == pytest.approx(1.0)
    assert report["pooled"]["mean_ic"] > 0.9


def test_pure_class_timing_shows_in_between_and_the_class_share():
    report = class_ic_decomposition(_frame(within_signal=False, between_signal=True), prediction="prediction", target="target")
    assert report["between"]["mean_ic"] == pytest.approx(1.0)
    assert abs(report["within_weighted"]["mean_ic"]) < 0.15
    assert report["class_share_of_pooled"] > 0.7


def test_thin_classes_and_non_finite_rows_are_skipped():
    frame = _frame(True, False)
    frame.loc[frame.index[:5], "prediction"] = np.nan
    report = class_ic_decomposition(frame, prediction="prediction", target="target", min_names_per_class=9)
    assert report["within"] == {}  # 8 names per class < 9
    assert report["pooled"]["num_dates"] == 60
