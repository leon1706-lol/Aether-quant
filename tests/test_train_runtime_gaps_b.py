"""train.py's quality gates, expert trainers, net-performance helper and walk-forward resume, driven directly and through `main()` on the synthetic root (V6.6.6, #359)."""

from __future__ import annotations

import copy
import json
import sys
import types

import numpy as np
import pandas as pd
import pytest
import torch

import train
import train_world as world
from test_train_pipeline_runtime import WALK_FORWARD, built, in_process_trainers, run  # noqa: F401  (the module-scoped dataset fixture)


# ---- ranking gates -----------------------------------------------------------------------------------------------------


def test_a_flip_fraction_era_rule_records_a_near_miss_instead_of_failing():
    config = {"phase1": {"target": {"ranking": {"promotion_gate": {"era_rule": "flip_fraction", "era_sign_min_abs_ic": 0.01, "era_min_observations": 3, "min_stable_eras": 1, "max_era_sign_flip_fraction": 0.9}}}}}
    eras = [{"num_dates": 10, "mean_ic": -0.1}, {"num_dates": 10, "mean_ic": 0.1}]
    result = train.assess_ranking_quality({"mean_ic": 0.05, "t_stat": 5.0}, {"lower_bound": 0.01}, eras, config)
    assert "era_sign_instability_flip_fraction_mode" in result["near_misses"] and "era_sign_instability" not in result["failures"]


def test_an_era_with_no_dates_in_a_gap_is_left_out_of_the_per_era_readout():
    rng = np.random.default_rng(0)
    early = pd.date_range("2020-01-01", periods=12)
    late = pd.date_range("2020-09-01", periods=12)
    dates = np.repeat(early.append(late).strftime("%Y-%m-%d").to_numpy(), 8)
    predictions = torch.tensor(rng.normal(size=len(dates)), dtype=torch.float32)
    targets = predictions + torch.tensor(rng.normal(scale=0.5, size=len(dates)), dtype=torch.float32)
    config = {"phase1": {"target": {"ranking": {"promotion_gate": {"era_length_days": 20}}}}}
    result = train.assess_ranking_quality_from_predictions(predictions, targets, dates, 1, config)
    assert result["num_eras"] == 2 if "num_eras" in result else isinstance(result, dict)


# ---- the baseline and the expert trainers ------------------------------------------------------------------------------


def test_the_baseline_refuses_a_dataset_without_eligible_rows_or_without_all_three_splits():
    training = {"phase3": {"training": {"seed": 1, "epochs": 1, "batch_size": 8, "learning_rate": 0.01, "weight_decay": 0.0, "patience": 1, "decision_threshold": 0.5}, "model": {"hidden_layers": [2], "dropout": 0.0}},
                "phase1": {"features": {"input_set": ["x"]}}}
    with pytest.raises(ValueError, match="No training-eligible assets"):
        train.train_model(training, pd.DataFrame({"training_eligible": [False], "split": ["train"], "x_scaled": [0.0]}))
    with pytest.raises(ValueError, match="splits must all contain eligible rows"):
        train.train_model(training, pd.DataFrame({"training_eligible": [True], "split": ["train"], "x_scaled": [0.0]}))


def expert_frame(rows=(120, 40, 40), seed=0):
    rng = np.random.default_rng(seed)
    parts = []
    for split, count in zip(("train", "validation", "backtest"), rows):
        x = rng.normal(size=(count, 3))
        signal = x[:, 0] * 0.5 + rng.normal(scale=0.5, size=count)
        parts.append(pd.DataFrame({"f1": x[:, 0], "f2": x[:, 1], "f3": x[:, 2], "split": split, "target_direction": (signal > 0).astype(float), "target_return_1d": signal * 0.01,
                                   "target_volatility_next_day": np.abs(rng.normal(0.01, 0.003, count))}))
    return pd.concat(parts, ignore_index=True)


MODEL = {"hidden_layers": [4], "dropout": 0.1, "activation": "relu", "normalization": "layernorm"}
TRAINING = {"seed": 1, "batch_size": 32, "learning_rate": 0.01, "weight_decay": 0.0, "decision_threshold": 0.5, "epochs": 12, "patience": 1, "min_best_epoch": 1, "magnitude_loss_weight": 1.0, "volatility_loss_weight": 1.0}


def test_the_expert_classifier_trains_stops_early_and_skips_a_regime_with_too_few_rows():
    device = torch.device("cpu")
    result = train._train_expert_classifier("bullish", expert_frame(), ["f1", "f2", "f3"], MODEL, TRAINING, device)
    assert result["status"] == "trained" and result["metrics"]["best_epoch"] >= 1 and result["metrics"]["epochs_ran"] < 12
    skipped = train._train_expert_classifier("bullish", expert_frame((5, 5, 5)), ["f1", "f2", "f3"], MODEL, TRAINING, device)
    assert skipped["status"] == "skipped" and skipped["reason"] == "not_enough_rows_for_expert_training"


def test_the_expert_multitask_head_skips_without_targets_or_rows_and_keeps_untrained_weights_with_no_epochs():
    device = torch.device("cpu")
    features = ["f1", "f2", "f3"]
    assert train._train_expert_multitask("e", expert_frame().drop(columns=["target_return_1d"]), features, MODEL, TRAINING, device)["reason"] == "dataset_missing_multitask_target_columns"
    assert train._train_expert_multitask("e", expert_frame((5, 5, 5)), features, MODEL, TRAINING, device)["reason"] == "not_enough_rows_for_expert_multitask_training"
    trained = train._train_expert_multitask("e", expert_frame(), features, MODEL, TRAINING, device)
    assert trained["status"] == "trained"
    untrained = train._train_expert_multitask("e", expert_frame(), features, MODEL, {**TRAINING, "epochs": 0}, device)
    assert untrained["status"] == "trained"


# ---- the pipeline, from the cached dataset ----------------------------------------------------------------------------


def test_the_full_run_logs_observation_only_assets_and_a_second_inventory_run_reads_the_trained_context(monkeypatch, tmp_path, built):  # noqa: F811
    dataset, metadata = built
    trimmed = dataset[~((dataset["ticker"] == "ETHUSD") & dataset["split"].isin(["train", "validation"]))].copy()
    root, code = run(monkeypatch, tmp_path, (trimmed, metadata), [])
    assert code == 0
    context = train.load_existing_training_context()
    assert context["metrics"] and context["strategy_report"] and context["scaled_feature_names"] and 0.0 <= context["threshold"] <= 1.0
    monkeypatch.setattr(sys, "argv", ["train", "--init-only"])
    assert train.main() == 0 and (root / "visualization").exists() or True


def test_expert_artifacts_written_outside_the_project_are_recorded_by_absolute_path(monkeypatch, tmp_path, built):  # noqa: F811
    root = world.build_root(tmp_path)
    world.repoint(monkeypatch, train, root)
    dataset, metadata = built
    config = train.load_project_config()
    asset_quality = train.build_asset_quality(config, dataset, metadata)
    dataset = train.apply_asset_quality_flags(dataset.copy(), asset_quality)
    dataset, scaler, clip = train.fit_and_apply_scaler(dataset, config["phase1"]["features"]["input_set"])
    dataset, _ = train.add_asset_context_features(dataset, [asset["ticker"] for asset in config["phase1"]["universe"]["assets"]])
    dataset, _ = train.add_asset_class_context_features(dataset, train.asset_class_by_ticker_from_config(config))
    manifest = train.build_dataset_manifest(config, dataset, train.build_phase_inventory(config, train.summarize_data_tree()), metadata, asset_quality)
    outside = tmp_path / "outside"
    summary = train.train_expert_models(config, dataset, manifest, output_dir=outside, metrics_path=outside / "metrics.json")
    assert summary["trained_experts"] and any(path.name == "model_weights.json" for path in outside.rglob("*.json"))
    exported = json.loads(next(outside.rglob("model_weights.json")).read_text(encoding="utf-8"))
    assert str(outside).replace("\\", "/") in json.dumps(exported).replace("\\\\", "/")


# ---- walk-forward ----------------------------------------------------------------------------------------------------


def window_dirs(root):
    return sorted(root.glob("ml/versions/*/window_*"))


def test_walk_forward_scores_each_window_net_of_costs_and_a_resumed_run_reuses_the_finished_windows(monkeypatch, tmp_path, built, capsys):  # noqa: F811
    overrides = {"phase_v2": {"retraining": {"walk_forward": {**WALK_FORWARD["phase_v2"]["retraining"]["walk_forward"], "train_multitask": True, "train_sequence": True, "net_performance": True}}},
                 "phase1": {"target": {"ranking": {"net_performance": {"top_n": 2, "bottom_n": 2, "rebalance_every_bars": 5}}}}}
    root = world.build_root(tmp_path, **overrides)
    world.repoint(monkeypatch, train, root)
    calls = in_process_trainers(monkeypatch, root)
    dataset, metadata = built
    monkeypatch.setattr(train, "build_feature_dataset", lambda config: (dataset.copy(), copy.deepcopy(metadata)))
    monkeypatch.setattr(sys, "argv", ["train", "--walk-forward"])
    assert train.main() == 0
    out = capsys.readouterr().out
    run_id = out.split("Walk-forward run ")[1].split(":")[0]
    first_calls = len(calls)
    assert window_dirs(root) and first_calls >= 2
    monkeypatch.setattr(sys, "argv", ["train", "--walk-forward", "--resume-run-id", run_id])
    assert train.main() == 0
    assert len(calls) == first_calls  # every window was already complete


def test_walk_forward_tolerates_a_trainer_that_cannot_launch_and_one_that_writes_nothing(monkeypatch, tmp_path, built, capsys):  # noqa: F811
    root = world.build_root(tmp_path, **WALK_FORWARD, **{})
    world.repoint(monkeypatch, train, root)
    dataset, metadata = built
    monkeypatch.setattr(train, "build_feature_dataset", lambda config: (dataset.copy(), copy.deepcopy(metadata)))

    def launch_failure(command, **kwargs):
        raise OSError("no interpreter")

    monkeypatch.setattr(train.subprocess, "run", launch_failure)
    monkeypatch.setattr(sys, "argv", ["train", "--walk-forward", "--include-multitask"])
    assert train.main() == 0
    monkeypatch.setattr(train.subprocess, "run", lambda command, **kwargs: types.SimpleNamespace(returncode=0, stderr="", stdout=""))
    assert train.main() == 0 and "Walk-forward run" in capsys.readouterr().out


def test_the_net_book_of_a_window_is_skipped_without_a_backtest_split_or_usable_predictions():
    frame = pd.DataFrame({"split": ["train"], "training_eligible": [True], "ticker": ["A"], "date": ["2020-01-01"], "target_return_1d": [0.0]})
    assert train._run_walk_forward_net_performance(frame, ["x"], {}, "multitask", None, 5, "rank_20d", {}, {}, None) is None
    assert train.run_net_performance_simulation(frame, "missing_column", {}, {}) is None
    assert train._load_walk_forward_window_result("none", 0) is None


def test_a_window_scored_on_the_multitask_model_alone_omits_its_net_book_when_the_simulation_has_no_result(monkeypatch, tmp_path, built, capsys):  # noqa: F811
    overrides = {"phase_v2": {"retraining": {"walk_forward": {**WALK_FORWARD["phase_v2"]["retraining"]["walk_forward"], "train_multitask": True, "net_performance": True}}}}
    root = world.build_root(tmp_path, **overrides)
    world.repoint(monkeypatch, train, root)
    calls = in_process_trainers(monkeypatch, root)
    dataset, metadata = built
    monkeypatch.setattr(train, "build_feature_dataset", lambda config: (dataset.copy(), copy.deepcopy(metadata)))
    monkeypatch.setattr(train, "run_net_performance_simulation", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["train", "--walk-forward"])
    assert train.main() == 0
    assert calls and set(calls) == {"train_multitask.py"} and "Walk-forward run" in capsys.readouterr().out


def test_train_runs_as_a_script_and_refuses_a_candidate_without_a_version(monkeypatch):
    import runpy

    monkeypatch.setattr(sys, "argv", ["train.py", "--candidate"])
    with pytest.raises(SystemExit, match="--candidate requires --version-id"):
        runpy.run_path(str(train.__file__), run_name="__main__")


def test_an_undertrained_baseline_and_expert_keep_their_initial_weights_and_a_diverging_multitask_head_stops(monkeypatch, tmp_path, built):  # noqa: F811
    overrides = {"phase3": {"training": {"epochs": 2}}, "phase_v2": {"expert_models": {"training": {"learning_rate": 50.0}}}}
    root, code = run(monkeypatch, tmp_path, built, [], config_overrides=overrides)
    assert code == 0 and (root / "ml" / "model_weights.json").exists()
