"""scripts/v650_ml_scores.py (V6.6.6): each walk-forward window's model scores on its backtest rows, merged per signal."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from script_loader import load_script


def _window(folder, *, split="backtest", models=("multitask", "sequence")):
    folder.mkdir(parents=True)
    frame = pd.DataFrame({"date": ["2023-01-03", "2023-01-03", "2023-01-04", "2023-01-04"], "ticker": ["A", "B", "A", "B"], "split": split})
    frame.to_csv(folder / "full_dataset.csv", index=False)
    module = load_script("v650_ml_scores")
    for kind in models:
        model_name, schema_name = module.EXPORTS[kind]
        (folder / model_name).write_text("{}", encoding="utf-8")
        (folder / schema_name).write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")


def _heads(frame_or_dataset, *args, **kwargs):
    count = len(frame_or_dataset)
    return {name: np.linspace(0.1, 0.9, count) for name in ("rank_20d", "rank_5d", "sector_neutral_rank_20d")}


def test_a_window_scores_its_backtest_rows_with_each_model_it_has(tmp_path, monkeypatch):
    import evaluation.model_predictions as predictions

    module = load_script("v650_ml_scores")
    monkeypatch.setattr(predictions, "predict_heads", _heads)
    _window(tmp_path / "both")
    tables = module.tables_for_window(tmp_path / "both", end="2023-12-31", sequence_window=5)
    assert set(tables) == {"ml_a1", "ml_a2", "ml_a3"} and len(tables["ml_a1"]) == 4
    _window(tmp_path / "multitask_only", models=("multitask",))
    assert set(module.tables_for_window(tmp_path / "multitask_only", end="2023-12-31", sequence_window=5)) == {"ml_a2"}
    _window(tmp_path / "train_only", split="train")
    assert module.tables_for_window(tmp_path / "train_only", end="2023-12-31", sequence_window=5) == {}


def test_main_merges_the_windows_and_skips_one_without_a_dataset(tmp_path, monkeypatch, capsys):
    module = load_script("v650_ml_scores")
    run = tmp_path / "ml" / "versions" / "run_1"
    (run / "window_10").mkdir(parents=True)
    (run / "window_2").mkdir(parents=True)
    (run / "window_2" / "full_dataset.csv").write_text("x", encoding="utf-8")
    table = pd.DataFrame({"date": ["2023-01-03"], "ticker": ["A"], "score": [0.5]})
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path / "scores")
    monkeypatch.setattr(module, "tables_for_window", lambda window_dir, end, sequence_window: {"ml_a2": table})
    monkeypatch.setattr(module.sys, "argv", ["x", "--run-id", "run_1", "--end", "2023-12-31"])
    assert module.main() == 0
    assert pd.read_csv(tmp_path / "scores" / "ml_a2.csv")["score"].tolist() == [0.5]
    out = capsys.readouterr().out
    assert "window_10: no dataset" in out and "ml_a2: 1 rows" in out
