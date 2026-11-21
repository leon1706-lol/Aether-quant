"""lab/trainer.py: a lab run trains per seed, scores only out-of-sample rows, records itself and counts its trials."""

from __future__ import annotations

import json
import sys
import types

import numpy as np
import pandas as pd
import pytest

from lab import run_registry, trainer
from lab_world import make_lab


def test_a_linear_run_learns_the_planted_signal_and_records_everything(tmp_path):
    lab = make_lab(tmp_path / "lab")
    lines: list[str] = []
    record = trainer.train_run(lab, "lin", seeds=[1, 2], log=lines.append)
    run = lab / "runs" / record["id"]
    assert record["status"] == "finished" and record["metrics"]["oof_ic_mean"] > 0.05
    assert record["metrics"]["oof_ic_seed_std"] == 0.0, "a ridge fit does not depend on the seed"
    assert record["trials_n"] == 2 and len((lab / "trials.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    scores = pd.read_csv(run / "scores.csv")
    assert set(scores["split"]) == {"validation", "backtest"}, "train rows are never scored"
    assert {"config.json", "scores_seed_1.npy", "linear_split_seed_1.json"} <= set(record["pins"])
    assert json.loads((run / "config.json").read_text(encoding="utf-8"))["model"]["template"] == "linear"
    assert any(line.startswith("seed 1:") for line in lines)


def test_a_stopped_run_resumes_its_finished_seeds_and_a_dry_run_only_plans(tmp_path):
    lab = make_lab(tmp_path / "lab")
    plan = trainer.train_run(lab, "lin", dry_run=True)
    assert plan["dry_run"] and plan["features"] == ["ret_1", "ret_5", "ret_20", "ret_60", "vol_20", "vol_60"] and not list((lab / "runs").iterdir())
    record = trainer.train_run(lab, "lin", seeds=[3], log=lambda line: None)
    run = lab / "runs" / record["id"]
    (run / "resume.json").write_text(json.dumps({**json.loads((run / "resume.json").read_text(encoding="utf-8")), "finished": False}), encoding="utf-8")
    lines: list[str] = []
    again = trainer.train_run(lab, "lin", seeds=[3], resume="latest", log=lines.append)
    assert again["id"] == record["id"] and "seed 3: done earlier, loaded" in lines
    with pytest.raises(FileNotFoundError, match="no stopped lab run"):
        trainer.train_run(lab, "lin", resume="nope")


def test_annual_folds_walk_forward_and_bad_inputs_say_what_to_do(tmp_path):
    lab = make_lab(tmp_path / "lab")
    record = trainer.train_run(lab, "lin", folds="annual", log=lambda line: None)
    assert [row["fold"] for row in record["metrics"]["folds"]] == ["2021"], "the second calendar year is scored by a model fitted before it"
    frame = pd.DataFrame({"date": ["2020-01-01"] * 3, "split": "train"})
    with pytest.raises(ValueError, match="two calendar years"):
        trainer.make_folds(frame, "annual")
    with pytest.raises(ValueError, match="split or annual"):
        trainer.make_folds(frame, "kfold")
    with pytest.raises(FileNotFoundError, match="aq lab new"):
        trainer.train_run(lab, "missing")
    with pytest.raises(ValueError, match="no target_rank_60d"):
        trainer.train_run(lab, "lin", overrides={"data": {"target": "target_rank_60d"}})
    (lab / "data" / "dataset.csv").unlink()
    with pytest.raises(FileNotFoundError, match="aq dataset build"):
        trainer.train_run(lab, "lin")


def test_a_network_run_trains_early_stops_checkpoints_and_resumes(tmp_path):
    pytest.importorskip("torch")
    lab = make_lab(tmp_path / "lab", models={"mt": "multitask"}, epochs=3)
    lines: list[str] = []
    record = trainer.train_run(lab, "mt", overrides={"train": {"patience": 1, "min_best_epoch": 0}}, log=lines.append)
    run = lab / "runs" / record["id"]
    assert record["metrics"]["oof_ic_mean"] is not None and (run / "model_split_seed_7.pt").exists() and (run / "checkpoint_split_seed_7.pt").exists()
    assert any("epoch 1/3" in line for line in lines)
    _model, history = trainer.fit_torch(trainer.load_model_module(lab / "models" / "mt"), *_inputs(lab), spec=_spec(lab, "mt"), seed=7, head="rank_20d", windows=None,
                                       log=lambda line: None, checkpoint=run / "checkpoint_split_seed_7.pt")
    assert history and history[-1]["epoch"] >= 1, "a checkpoint resumes after its last finished epoch"


def _spec(lab, name):
    from lab import spec

    return spec.load_spec(lab / "models" / name, lab_dir=lab, overrides={"train": {"epochs": 3, "patience": 1}})


def _inputs(lab):
    from lab import lab_dataset

    frame = lab_dataset.load_dataset(lab / "data" / "dataset.csv").sort_values(["ticker", "date"]).reset_index(drop=True)
    x = lab_dataset.rank_features(frame, lab_dataset.feature_columns(frame))
    split = frame["split"].to_numpy()
    return x, frame["target_rank_20d"].to_numpy(dtype=float), frame["date"].to_numpy(), split == "train", split == "validation"


def test_without_validation_rows_the_last_epoch_is_kept_and_a_sequence_model_reads_windows(tmp_path):
    pytest.importorskip("torch")
    lab = make_lab(tmp_path / "lab", models={"seq": "tcn"}, epochs=2)
    x, y, dates, fit, _ = _inputs(lab)
    from lab import lab_dataset
    from retraining.slicing import sequence_window_index

    frame = lab_dataset.load_dataset(lab / "data" / "dataset.csv").sort_values(["ticker", "date"]).reset_index(drop=True)
    windows = sequence_window_index(frame["ticker"].to_numpy(), 5)
    model, history = trainer.fit_torch(trainer.load_model_module(lab / "models" / "seq"), x, y, dates, fit, np.zeros(len(y), bool), spec=_spec(lab, "seq"), seed=1,
                                       head="rank_20d", windows=windows, log=lambda line: None)
    assert [row["validation_rank_ic"] for row in history] == [None, None, None], "three epochs, none with a validation IC"
    assert trainer.predict_torch(model, x, np.arange(10), windows, "rank_20d").shape == (10,)
    assert trainer.predict_torch(model, x, np.arange(0), windows, "rank_20d").shape == (0,)


def test_heads_outputs_and_the_torch_error():
    assert trainer.head_of("target_rank_20d") == "rank_20d"
    assert trainer.model_outputs({"rank_20d": 1}, "rank_20d") == 1 and trainer.model_outputs((2, 3), "x") == 2 and trainer.model_outputs(4, "x") == 4
    with pytest.raises(KeyError, match="has no 'rank_5d' head"):
        trainer.model_outputs({"rank_20d": 1}, "rank_5d")
    coefficients = trainer.fit_linear(np.array([[0.0], [1.0], [2.0], [np.nan]]), np.array([1.0, 3.0, 5.0, np.nan]), 0.0)
    assert coefficients == pytest.approx([1.0, 2.0])
    assert trainer.spread_sharpe(pd.Series([1.0]), pd.DataFrame({"date": ["d"], "target_return_1d": [0.1]})) == (None, 0)


def test_a_neural_template_without_torch_names_the_extra(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(trainer.TorchMissing, match=r"aether-quant\[train\]"):
        trainer.require_torch()
    lab = make_lab(tmp_path / "lab", models={"ff": "mlp"})
    with pytest.raises(trainer.TorchMissing):
        trainer.train_run(lab, "ff")
    assert isinstance(types.ModuleType("x"), types.ModuleType)


def test_the_project_ledger_counts_lab_trials_too(tmp_path):
    lab = make_lab(tmp_path / "lab")
    project = tmp_path / "project_ledger.jsonl"
    record = trainer.train_run(lab, "lin", project_ledger=project, log=lambda line: None)
    assert project.exists() and record["trials_n"] == 1 and trainer.ledger_count(lab, project) == 1
    assert run_registry.read_run(lab / "runs" / record["id"])["environment"]["numpy"] == np.__version__


def test_a_flat_network_stops_early_and_follows_its_cosine_schedule(tmp_path):
    pytest.importorskip("torch")
    from lab import spec

    lab = make_lab(tmp_path / "lab", models={"mt": "multitask"}, epochs=3)
    settings = spec.load_spec(lab / "models" / "mt", lab_dir=lab, overrides={"train": {"epochs": 6, "patience": 1, "min_best_epoch": 0, "lr": 1e-12, "lr_schedule": "cosine"}})
    lines: list[str] = []
    _model, history = trainer.fit_torch(trainer.load_model_module(lab / "models" / "mt"), *_inputs(lab), spec=settings, seed=3, head="rank_20d", windows=None, log=lines.append)
    assert len(history) < 6 and any("early stop" in line for line in lines), "an IC that never improves stops after `patience` epochs"


def test_a_model_file_is_required_and_its_own_import_errors_say_what_is_missing(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError, match="aq lab new empty"):
        trainer.load_model_module(tmp_path / "empty")
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "model.py").write_text("import a_module_that_is_not_installed_anywhere\n", encoding="utf-8")
    with pytest.raises(ModuleNotFoundError, match="a_module_that_is_not_installed_anywhere"):
        trainer.load_model_module(folder)
    (folder / "model.py").write_text("import torch\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(trainer.TorchMissing, match=r"aether-quant\[train\]"):
        trainer.load_model_module(folder)
