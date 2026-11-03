"""evaluation/research_probes.py (V6.4.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.research_probes import fit_hgb_rank, fit_ridge_rank, load_research_frame, predict_scores


def test_ridge_recovers_a_linear_signal_and_skips_nan_rows():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(2000, 3))
    y = 0.5 + x @ np.array([0.3, -0.2, 0.0]) + rng.normal(0, 0.01, 2000)
    x[0, 1] = np.nan
    model = fit_ridge_rank(x, y, alpha=1.0, features=["a", "b", "c"])
    assert model["rows"] == 1999
    assert model["coef"] == pytest.approx([0.3, -0.2, 0.0], abs=0.01)
    scores = predict_scores(model, x)
    assert np.isnan(scores[0]) and np.isfinite(scores[1:]).all()


def test_hgb_probe_fits_and_predicts():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(1500, 2)).astype(np.float32)
    y = (x[:, 0] > 0).astype(float)
    model = fit_hgb_rank(x, y, max_depth=2, max_iter=30, early_stopping=False, random_state=0)
    scores = predict_scores(model, x)
    assert np.corrcoef(scores, y)[0, 1] > 0.9


def test_load_research_frame_reads_only_the_wanted_columns(tmp_path):
    path = tmp_path / "d.csv"
    pd.DataFrame({"date": ["2024-01-01 00:00:00", "2024-01-02"], "ticker": ["A", "B"], "split": ["train", "validation"],
                  "x": [1.0, 2.0], "y": [3.0, 4.0], "unused": [0, 0]}).to_csv(path, index=False)
    frame = load_research_frame(path, columns=["x", "missing"], splits=["validation"], chunksize=1)
    assert list(frame.columns) == ["date", "ticker", "split", "x"]
    assert frame["x"].dtype == np.float32
    assert frame["date"].tolist() == ["2024-01-02"]
