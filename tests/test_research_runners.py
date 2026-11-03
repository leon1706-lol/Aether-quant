"""evaluation/research_runners.py - the V6.4.3 `aq evaluate` research flags and `aq research` (V6.4.3)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from evaluation import research_runners


@pytest.fixture
def dataset(tmp_path):
    rng = np.random.default_rng(0)
    rows = []
    dates = pd.date_range("2022-01-03", periods=120, freq="B").strftime("%Y-%m-%d")
    for t, date in enumerate(dates):
        future = rng.normal(size=25)
        ranks = pd.Series(future).rank(pct=True).to_numpy()
        for i in range(25):
            rows.append({"date": date, "ticker": f"T{i}", "split": "validation" if t < 60 else "backtest",
                         "target_rank_20d": ranks[i], "target_rank_5d": ranks[i], "target_return_1d": future[i] / 100,
                         "close_to_close_return_1d": rng.normal(0, 0.01), "close_to_close_return_5d": rng.normal(0, 0.02),
                         "momentum_20d": rng.normal(0, 0.05), "rolling_volatility_20d": 0.01 + i / 1000, "dist_52w_high": -i / 100})
    frame = pd.DataFrame(rows)
    path = tmp_path / "dataset.csv"
    frame.to_csv(path, index=False)
    signal = frame[["date", "ticker"]].assign(score=frame["target_return_1d"] + rng.normal(0, 0.01, len(frame)))
    signal_path = tmp_path / "signal.csv"
    signal.to_csv(signal_path, index=False)
    return path, signal_path


def test_signal_report_scores_both_splits(dataset):
    path, signal = dataset
    report = research_runners.run_signal_report(signal, path, horizons=(20,))
    assert set(report["splits"]) == {"validation", "backtest"}
    assert report["splits"]["validation"]["h20"]["mean_ic"] > 0.3


def test_factor_spanning_runs_on_a_signal(dataset):
    path, signal = dataset
    report = research_runners.run_factor_spanning(signal, path, split="backtest")
    assert report["num_dates"] > 0
    assert "alpha_t" in report


def test_pbo_reads_a_returns_table(tmp_path):
    table = pd.DataFrame(np.random.default_rng(1).normal(0, 0.01, size=(320, 5)), columns=list("abcde"))
    path = tmp_path / "returns.csv"
    table.to_csv(path)
    report = research_runners.run_pbo(path, blocks=8)
    assert report["trials"] == list("abcde")
    assert 0.0 <= report["pbo"] <= 1.0


def test_sim_lean_gap_reads_a_calibration_report(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({"windows": {"w": {"variants": {"v580": {"daily_correlation": 0.5, "annual_return_gap": 0.1},
                                                                 "calibrated": {"daily_correlation": 0.7, "annual_return_gap": 0.0}}}}}),
                    encoding="utf-8")
    report = research_runners.run_sim_lean_gap(path)
    assert report["windows"]["w"]["best_rung"] == "calibrated"


def test_overfit_report_reads_the_metric_files(tmp_path):
    (tmp_path / "multitask_training_metrics.json").write_text(json.dumps({
        "train": {"rank_20d_ic_non_overlapping": {"mean_ic": 0.3}},
        "validation": {"rank_20d_ic_non_overlapping": {"mean_ic": 0.0}}}), encoding="utf-8")
    report = research_runners.run_overfit_report(tmp_path)
    assert report["models"]["multitask"]["rank_20d"]["train_minus_validation"] == pytest.approx(0.3)
    assert "sequence" not in report["models"]
