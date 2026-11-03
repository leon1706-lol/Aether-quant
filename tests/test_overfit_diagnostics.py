"""evaluation/overfit_diagnostics.py (V6.4.3)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from evaluation.overfit_diagnostics import head_ic, learning_curve, training_gap_report


def test_head_ic_prefers_the_non_overlapping_series():
    metrics = {"validation": {"rank_20d_ic": {"mean_ic": 0.05}, "rank_20d_ic_non_overlapping": {"mean_ic": 0.02}}}
    assert head_ic(metrics, "validation", "rank_20d") == 0.02
    assert head_ic({"validation": {"rank_20d_ic": {"mean_ic": 0.05}}}, "validation", "rank_20d") == 0.05
    assert head_ic({}, "validation", "rank_20d") is None


def test_gap_report_from_a_metrics_file(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({
        "train": {"rank_20d_ic_non_overlapping": {"mean_ic": 0.30}},
        "validation": {"rank_20d_ic_non_overlapping": {"mean_ic": -0.02}},
        "backtest": {"rank_20d_ic_non_overlapping": {"mean_ic": 0.05}},
    }), encoding="utf-8")
    report = training_gap_report({"sequence": path, "missing": tmp_path / "nope.json"})
    row = report["sequence"]["rank_20d"]
    assert row["train_minus_validation"] == pytest.approx(0.32)
    assert row["retained"] == pytest.approx(-0.02 / 0.30)
    assert "rank_5d" not in report["sequence"]
    assert "error" in report["missing"]


def test_learning_curve_trains_on_growing_windows():
    dates = pd.date_range("2014-01-01", "2022-12-31", freq="MS")
    frame = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "split": np.where(dates.year <= 2021, "train", "validation")})
    curve = learning_curve(lambda train, evaluation: float(len(train)), frame, train_years=(1, 4))
    assert [row["train_years"] for row in curve] == [1, 4]
    assert curve[0]["score"] == 12 and curve[1]["score"] == 48
