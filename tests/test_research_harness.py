"""evaluation/research_harness.py (V6.4.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.research_harness import block_bootstrap_mean_ci, evaluate_signal, ic_summary


def _frame(n_dates: int = 300, n_names: int = 30, skill: float = 0.3, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-03", periods=n_dates, freq="B").strftime("%Y-%m-%d")
    rows = []
    for date in dates:
        future = rng.normal(size=n_names)
        score = skill * future + rng.normal(size=n_names)
        ranks = pd.Series(future).rank(pct=True).to_numpy()
        for i in range(n_names):
            rows.append({"date": date, "ticker": f"T{i}", "split": "validation", "score": score[i], "target_rank_20d": ranks[i],
                         "target_rank_5d": ranks[i], "target_return_1d": future[i] * 0.01, "cls": "a" if i % 2 else "b",
                         "regime": float(rng.normal())})
    return pd.DataFrame(rows)


def test_a_skilled_signal_has_positive_significant_ic():
    report = evaluate_signal(_frame(), score_column="score", splits=("validation",), class_column="cls", regime_column="regime")
    h20 = report["splits"]["validation"]["h20"]
    assert h20["mean_ic"] > 0.15
    assert h20["hac_t"] > 3 and h20["nonoverlap_t"] > 2
    assert h20["ci95"][0] > 0
    assert h20["eras"]["stable"] is True
    assert set(report["splits"]["validation"]["by_class"]["h20"]) == {"a", "b"}
    assert set(report["splits"]["validation"]["by_regime"]["h20"]) == {"low", "mid", "high"}
    assert set(report["splits"]["validation"]["decay"]) == {1, 5, 20}


def test_a_noise_signal_has_no_significant_ic():
    h20 = evaluate_signal(_frame(skill=0.0, seed=4), score_column="score", splits=("validation",))["splits"]["validation"]["h20"]
    assert abs(h20["mean_ic"]) < 0.05
    assert h20["ci95"][0] < 0 < h20["ci95"][1]


def test_nonoverlap_uses_every_horizon_th_date():
    ic = {f"2022-01-{day:02d}": 0.1 for day in range(1, 29)}
    summary = ic_summary(ic, horizon=5, bootstrap_draws=50)
    assert summary["num_nonoverlap_dates"] == 6
    assert summary["mean_ic"] == pytest.approx(0.1)


def test_empty_ic_series_reports_zero_dates():
    assert ic_summary({}, horizon=20)["num_dates"] == 0


def test_block_bootstrap_ci_brackets_the_mean():
    values = np.random.default_rng(1).normal(0.05, 0.1, 400)
    low, high = block_bootstrap_mean_ci(values, block=10, draws=500)
    assert low < values.mean() < high
    assert block_bootstrap_mean_ci([1.0], block=5) is None
