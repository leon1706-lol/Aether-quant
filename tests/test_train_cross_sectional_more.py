"""train_cross_sectional.py's remaining branches (V6.6.6, #359): the IC guards, the patience stop of both neural fitters, the dataset loader,
a window with no rows and the dataset command."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import train_cross_sectional as module
from test_train_cross_sectional import _frame


def test_a_date_ic_needs_ten_labelled_names_and_some_spread():
    assert module._date_ic(np.arange(5.0), np.arange(5.0)) is None
    assert module._date_ic(np.ones(12), np.arange(12.0)) is None
    assert module._date_ic(np.arange(12.0), np.ones(12)) is None
    assert module._date_ic(np.arange(12.0), np.arange(12.0)) > 0.99


def test_both_neural_fitters_stop_on_patience(monkeypatch):
    frame, features = _frame(dates=140, assets=12)
    train, test = frame.iloc[:1200].reset_index(drop=True), frame.iloc[1200:1500].reset_index(drop=True)
    monkeypatch.setattr(module, "_date_ic", lambda scores, labels: 0.0)  # never improves after the first epoch
    for fitter in (module.fit_predict_set_transformer, module.fit_predict_mlp_multitask):
        scores = fitter(train, test, features, "a", 1, max_epochs=6, patience=1)
        assert len(scores) == len(test) and np.isfinite(scores).all()


def test_the_dataset_loader_ranks_inputs_and_labels(tmp_path):
    rng = np.random.default_rng(0)
    rows = [{"date": f"2024-01-{day:02d}", "ticker": ticker, module.TARGET: float(rng.normal()), "f0": float(rng.normal()), "f1": float(rng.normal())}
            for day in range(2, 8) for ticker in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")]
    dataset = tmp_path / "full.csv"
    pd.DataFrame(rows).to_csv(dataset, index=False)
    config = {"phase1": {"universe": {"assets": [{"ticker": "AAA", "security_type": "equity"}]}}}
    frame, features = module.load_frame(dataset, config, {"scaled_feature_names": ["f0", "f1"]})
    assert features == ["f0", "f1"] and "_label" in frame.columns and set(frame["_class"]) == {"equity", "unknown"} and frame["date"].is_monotonic_increasing


def test_a_window_without_training_rows_is_skipped(monkeypatch):
    frame, features = _frame(dates=700, assets=6)
    monkeypatch.setattr(module, "annual_windows", lambda dates, first_test_year, purge_days: [{"train_end": "1990-01-01", "test_start": "2019-01-01", "test_end": "2019-12-31"}])
    assert module.walk_forward_scores(frame, features, "gbm", "a", [1], score_end=None).empty


def test_the_command_scores_a_dataset_end_to_end(tmp_path, monkeypatch):
    dataset, config, schema, out = tmp_path / "full.csv", tmp_path / "config.json", tmp_path / "schema.json", tmp_path / "scores.csv"
    pd.DataFrame({"date": ["2024-01-02"], "ticker": ["A"], module.TARGET: [0.1], "f0": [0.2]}).to_csv(dataset, index=False)
    config.write_text(json.dumps({"phase1": {"universe": {"assets": []}}}), encoding="utf-8")
    schema.write_text(json.dumps({"scaled_feature_names": ["f0"]}), encoding="utf-8")
    seen = {}
    monkeypatch.setattr(module, "walk_forward_scores", lambda frame, features, model, variant, seeds, score_end: seen.update(model=model, seeds=seeds) or pd.DataFrame({"date": ["2024-01-02"], "ticker": ["A"], "score": [0.5]}))
    assert module.main(["--dataset", str(dataset), "--config", str(config), "--schema", str(schema), "--model", "gbm", "--variant", "a", "--seeds", "1,2", "--out", str(out)]) == 0
    assert seen == {"model": "gbm", "seeds": [1, 2]} and out.exists()


def test_a_test_window_that_starts_after_the_score_end_stops_the_walk(monkeypatch):
    frame, features = _frame(dates=700, assets=6)
    monkeypatch.setattr(module, "annual_windows", lambda dates, first_test_year, purge_days: [{"train_end": "2018-01-01", "test_start": "2030-01-01", "test_end": "2030-12-31"}])
    assert module.walk_forward_scores(frame, features, "gbm", "a", [1], score_end="2019-01-01").empty


def test_the_command_reads_a_panel_and_a_score_panel(tmp_path, monkeypatch):
    out = tmp_path / "scores.csv"
    panel = pd.DataFrame({"date": ["2024-01-02"], "ticker": ["A"], "score": [0.0]})
    loads = []
    monkeypatch.setattr(module, "load_panel_frame", lambda path, **kwargs: loads.append((str(path), kwargs.get("train_start"))) or (panel, ["f0"]))
    monkeypatch.setattr(module, "walk_forward_scores", lambda *args, **kwargs: pd.DataFrame({"date": ["2024-01-02"], "ticker": ["A"], "score": [0.5]}) if kwargs.get("score_frame") is not None else (_ for _ in ()).throw(AssertionError("no score frame")))
    assert module.main(["--panel", "side.parquet", "--score-panel", "other.parquet", "--model", "gbm", "--variant", "b", "--out", str(out), "--train-start", "2011-01-01"]) == 0
    assert [name for name, _ in loads] == ["side.parquet", "other.parquet"] and out.exists()


def test_the_module_runs_as_a_script(monkeypatch):
    import runpy
    import sys

    import pytest

    monkeypatch.setattr(sys, "argv", ["train_cross_sectional", "--help"])
    monkeypatch.delitem(sys.modules, "train_cross_sectional", raising=False)
    with pytest.raises(SystemExit):
        runpy.run_module("train_cross_sectional", run_name="__main__")
