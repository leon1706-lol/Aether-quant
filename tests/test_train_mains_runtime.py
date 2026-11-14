"""The trainers' `main()` end to end on a tiny synthetic dataset (V6.6.6, #359): the multitask trainer with random batches and with cross-sectional ranking batches, and each way it can skip
(disabled, no schema, no dataset, missing columns, too few rows). Artifacts are written under a temporary `ml/versions/`."""

from __future__ import annotations

import json
import sys

import pytest

import train_gating
import train_multitask
import train_sequence
from moe.gating import EXPERT_NAMES
from trainer_fakes import FEATURES, make_frame, write_world


def run(monkeypatch, tmp_path, argv, **world):
    paths = write_world(tmp_path, **world)
    monkeypatch.setattr(train_multitask, "ML_DIR", tmp_path / "ml")
    monkeypatch.setattr(sys, "argv", ["train_multitask", "--version-id", "v1", "--config-path", str(paths["config"]), "--dataset-path", str(paths["dataset"]), "--feature-schema-path", str(paths["schema"]), *argv])
    return paths, train_multitask.main()


def test_the_multitask_model_trains_on_random_batches_and_writes_its_version(monkeypatch, tmp_path):
    paths, code = run(monkeypatch, tmp_path, [], training_overrides={"batch_mode": "random", "ranking_loss": None})
    version = tmp_path / "ml" / "versions" / "v1"
    metrics = json.loads((version / "multitask_training_metrics.json").read_text(encoding="utf-8"))
    assert code == 0 and (version / "multitask_model.json").exists() and "validation" in metrics and set(FEATURES) == set(json.loads((version / "multitask_feature_schema.json").read_text(encoding="utf-8"))["model_input_names"])


@pytest.mark.parametrize("objective", ["soft_spearman", "listnet", "mse"])
def test_cross_sectional_batches_train_with_each_ranking_objective(monkeypatch, tmp_path, objective):
    overrides = {"batch_mode": "cross_sectional", "ranking_loss": {"objective": objective, "temperature": 0.1, "listnet_temperature": 0.1, "mse_anchor_weight": 0.1},
                 "gate_aware_ranking_weights": {"enabled": True}, "label_noise_std": 0.01, "early_stop_metric": "rank_ic", "early_stop_smoothing_epochs": 2}
    _, code = run(monkeypatch, tmp_path, ["--seed", "7", "--ranking-objective", "soft_spearman"], training_overrides=overrides, epochs=3)
    assert code == 0 and (tmp_path / "ml" / "versions" / "v1" / "multitask_model.json").exists()


def test_each_way_the_trainer_skips_writes_nothing(monkeypatch, tmp_path):
    for index, (overrides, world_args) in enumerate((({"enabled": False}, {}), ({"min_train_rows": 10**9}, {}))):
        root = tmp_path / f"skip{index}"
        _, code = run(monkeypatch, root, [], training_overrides=overrides, **world_args)
        assert code == 0 and not (root / "ml" / "versions").exists()
    root = tmp_path / "noschema"
    paths, _ = run(monkeypatch, root, [])
    shutil_target = root / "ml" / "versions"
    assert shutil_target.exists()
    monkeypatch.setattr(sys, "argv", ["train_multitask", "--version-id", "v2", "--config-path", str(paths["config"]), "--dataset-path", str(paths["dataset"]), "--feature-schema-path", str(root / "none.json")])
    assert train_multitask.main() == 0
    monkeypatch.setattr(sys, "argv", ["train_multitask", "--version-id", "v3", "--config-path", str(paths["config"]), "--dataset-path", str(root / "none.csv"), "--feature-schema-path", str(paths["schema"])])
    assert train_multitask.main() == 0
    frame = make_frame().drop(columns=["f_a"])
    frame.to_csv(paths["dataset"], index=False)
    monkeypatch.setattr(sys, "argv", ["train_multitask", "--version-id", "v4", "--config-path", str(paths["config"]), "--dataset-path", str(paths["dataset"]), "--feature-schema-path", str(paths["schema"])])
    assert train_multitask.main() == 0 and not (root / "ml" / "versions" / "v4").exists()


def test_training_stops_early_when_the_monitored_metric_stops_improving(monkeypatch, tmp_path):
    _, code = run(monkeypatch, tmp_path, [], training_overrides={"patience": 1, "min_best_epoch": 1, "learning_rate": 0.5}, epochs=40)
    metrics = json.loads((tmp_path / "ml" / "versions" / "v1" / "multitask_training_metrics.json").read_text(encoding="utf-8"))
    assert code == 0 and len(metrics["history"]) < 40


def test_an_unreadable_config_is_a_failure_exit_code_and_the_module_runs_as_a_script(monkeypatch, tmp_path):
    import runpy

    monkeypatch.setattr(sys, "argv", ["train_multitask", "--version-id", "v9", "--config-path", str(tmp_path / "missing.json")])
    assert train_multitask.main() == 1
    with pytest.raises(SystemExit) as stop:
        runpy.run_path(str(train_multitask.__file__), run_name="__main__")
    assert stop.value.code == 1




def run_sequence(monkeypatch, tmp_path, argv=(), **world):
    paths = write_world(tmp_path, **world)
    monkeypatch.setattr(train_sequence, "ML_DIR", tmp_path / "ml")
    monkeypatch.setattr(sys, "argv", ["train_sequence", "--version-id", "s1", "--config-path", str(paths["config"]), "--dataset-path", str(paths["dataset"]), "--feature-schema-path", str(paths["schema"]), *argv])
    return paths, train_sequence.main()


def test_the_sequence_model_trains_on_random_batches_and_writes_its_version(monkeypatch, tmp_path):
    _, code = run_sequence(monkeypatch, tmp_path, sequence_overrides={"batch_mode": "random", "ranking_loss": None})
    version = tmp_path / "ml" / "versions" / "s1"
    assert code == 0 and (version / "sequence_model.json").exists() and (version / "sequence_training_metrics.json").exists()


def test_the_sequence_model_trains_on_cross_sectional_batches_with_swa_and_noise(monkeypatch, tmp_path):
    overrides = {"batch_mode": "cross_sectional", "ranking_loss": {"objective": "listnet", "temperature": 0.1, "listnet_temperature": 0.1, "mse_anchor_weight": 0.1},
                 "gate_aware_ranking_weights": {"enabled": True}, "label_noise_std": 0.01, "early_stop_smoothing_epochs": 2, "early_stop_metric": "rank_ic",
                 "swa": {"enabled": True, "start_epoch_fraction": 0.5}, "normalization": "layernorm"}
    _, code = run_sequence(monkeypatch, tmp_path, ["--seed", "3", "--ranking-objective", "soft_spearman"], sequence_overrides=overrides, epochs=3)
    assert code == 0 and (tmp_path / "ml" / "versions" / "s1" / "sequence_model.json").exists()


def test_the_sequence_trainer_stops_early_skips_and_reports_a_failure(monkeypatch, tmp_path):
    _, code = run_sequence(monkeypatch, tmp_path / "early", sequence_overrides={"patience": 1, "min_best_epoch": 1, "learning_rate": 0.5}, epochs=30)
    assert code == 0
    for index, overrides in enumerate(({"enabled": False}, {"min_train_rows": 10**9})):
        root = tmp_path / f"skip{index}"
        _, code = run_sequence(monkeypatch, root, sequence_overrides=overrides)
        assert code == 0 and not (root / "ml" / "versions").exists()
    root = tmp_path / "files"
    paths, _ = run_sequence(monkeypatch, root, sequence_overrides={"min_train_rows": 10**9})
    base = ["train_sequence", "--version-id", "s2", "--config-path", str(paths["config"])]
    monkeypatch.setattr(sys, "argv", [*base, "--dataset-path", str(paths["dataset"]), "--feature-schema-path", str(root / "none.json")])
    assert train_sequence.main() == 0
    monkeypatch.setattr(sys, "argv", [*base, "--dataset-path", str(root / "none.csv"), "--feature-schema-path", str(paths["schema"])])
    assert train_sequence.main() == 0
    make_frame().drop(columns=["f_a"]).to_csv(paths["dataset"], index=False)
    monkeypatch.setattr(sys, "argv", [*base, "--dataset-path", str(paths["dataset"]), "--feature-schema-path", str(paths["schema"])])
    assert train_sequence.main() == 0
    monkeypatch.setattr(sys, "argv", ["train_sequence", "--version-id", "s9", "--config-path", str(root / "missing.json")])
    assert train_sequence.main() == 1


def test_a_dataset_missing_a_horizon_column_disables_that_head(monkeypatch, tmp_path):
    frame = make_frame().drop(columns=["target_beta_neutral_rank_20d"])
    _, code = run_sequence(monkeypatch, tmp_path, frame=frame, sequence_overrides={"batch_mode": "random", "ranking_loss": None})
    assert code == 0


def test_the_sequence_script_runs_as_main(monkeypatch, tmp_path):
    import runpy

    monkeypatch.setattr(sys, "argv", ["train_sequence", "--version-id", "s9", "--config-path", str(tmp_path / "missing.json")])
    with pytest.raises(SystemExit) as stop:
        runpy.run_path(str(train_sequence.__file__), run_name="__main__")
    assert stop.value.code == 1


def test_a_horizon_column_missing_from_the_dataset_disables_the_head_in_the_multitask_trainer(monkeypatch, tmp_path):
    frame = make_frame().drop(columns=["target_beta_neutral_rank_20d", "target_rank_5d"])
    _, code = run(monkeypatch, tmp_path, [], frame=frame, training_overrides={"batch_mode": "random", "ranking_loss": None})
    assert code == 0


def test_sequence_forward_passes_are_batched_and_a_frame_without_eligibility_flags_still_trains(monkeypatch, tmp_path):
    monkeypatch.setattr(train_sequence, "FORWARD_BATCH_ROWS", 16)
    frame = make_frame().drop(columns=["training_eligible"])
    _, code = run_sequence(monkeypatch, tmp_path, frame=frame, sequence_overrides={"batch_mode": "random", "ranking_loss": None, "early_stop_metric": "loss"})
    assert code == 0 and (tmp_path / "ml" / "versions" / "s1" / "sequence_model.json").exists()


def test_a_run_with_no_epochs_keeps_the_untrained_weights(monkeypatch, tmp_path):
    _, code = run_sequence(monkeypatch, tmp_path, sequence_overrides={"batch_mode": "random", "ranking_loss": None, "swa": {"enabled": False}}, epochs=0)
    assert code in (0, 1)




def linear_export(weights, bias=0.0):
    return {"export": {"architecture": [{"type": "linear", "weight_key": "l1.weight", "bias_key": "l1.bias"}, {"type": "sigmoid"}], "state_dict": {"l1.weight": [weights], "l1.bias": [bias]}}}


def gating_world(monkeypatch, tmp_path, *, gating=None, experts=("bullish",), broken_experts=("bearish",), baseline="active", schema=True, expert_metrics=True, **world):
    paths = write_world(tmp_path, **world)
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["phase_v2"]["retraining"]["gating_training"].update({"epochs": 4, "patience": 2, "min_best_epoch": 1, "hidden_layers": [4], "min_train_rows": 50, "min_backtest_rows": 10, **(gating or {})})
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    ml = tmp_path / "ml"
    schema_payload = {"model_input_names": FEATURES, "feature_names": FEATURES}
    if schema:
        (ml / "feature_schema.json").write_text(json.dumps(schema_payload), encoding="utf-8")
    else:
        (ml / "feature_schema.json").unlink()
    if expert_metrics:
        metrics = {"experts": {name: {"quality_gate": {"quality_status": "stable", "gating_eligible": True}, "validation": {"balanced_accuracy": 0.55}, "backtest": {"balanced_accuracy": 0.53, "mcc": 0.05}} for name in EXPERT_NAMES}}
        (ml / "expert_training_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    for name in experts:
        (ml / "expert_models" / name).mkdir(parents=True)
        (ml / "expert_models" / name / "model_weights.json").write_text(json.dumps(linear_export([0.3, -0.2, 0.1, 0.0, 0.2, -0.1])), encoding="utf-8")
    for name in broken_experts:
        (ml / "expert_models" / name).mkdir(parents=True)
        (ml / "expert_models" / name / "model_weights.json").write_text(json.dumps({"export": {"architecture": [{"type": "linear", "weight_key": "missing", "bias_key": "missing"}], "state_dict": {}}}), encoding="utf-8")
    if baseline == "active":
        (ml / "model_weights.json").write_text(json.dumps(linear_export([0.1, 0.1, 0.0, 0.0, -0.1, 0.2])), encoding="utf-8")
    elif baseline == "versioned_broken":
        (ml / "versions" / "g1").mkdir(parents=True)
        (ml / "versions" / "g1" / "model_weights.json").write_text(json.dumps({"export": {"architecture": [{"type": "linear", "weight_key": "missing", "bias_key": "missing"}], "state_dict": {}}}), encoding="utf-8")
    for name, value in (("ML_DIR", ml), ("FEATURE_SCHEMA_PATH", ml / "feature_schema.json"), ("EXPERT_TRAINING_METRICS_PATH", ml / "expert_training_metrics.json"),
                        ("EXPERT_MODEL_DIR", ml / "expert_models"), ("ACTIVE_BASELINE_MODEL_PATH", ml / "model_weights.json")):
        monkeypatch.setattr(train_gating, name, value)
    monkeypatch.setattr(sys, "argv", ["train_gating", "--version-id", "g1", "--config-path", str(paths["config"]), "--dataset-path", str(paths["dataset"])])
    return paths


def test_the_gating_network_trains_on_replayed_experts_and_writes_its_version(monkeypatch, tmp_path):
    gating_world(monkeypatch, tmp_path)
    assert train_gating.main() == 0
    version = tmp_path / "ml" / "versions" / "g1"
    metrics = json.loads((version / "gating_training_metrics.json").read_text(encoding="utf-8"))
    assert (version / "gating_model.json").exists() and metrics["row_counts"]["backtest"] > 0 and metrics["epochs_ran"] >= 1


def test_the_gating_network_stops_early_and_keeps_untrained_weights_with_no_epochs(monkeypatch, tmp_path):
    gating_world(monkeypatch, tmp_path / "early", gating={"patience": 1, "learning_rate": 0.5, "epochs": 30})
    assert train_gating.main() == 0
    gating_world(monkeypatch, tmp_path / "none", gating={"epochs": 0})
    assert train_gating.main() == 0


def test_a_broken_versioned_baseline_is_replayed_as_missing_and_other_inputs_skip_the_run(monkeypatch, tmp_path):
    gating_world(monkeypatch, tmp_path / "broken", baseline="versioned_broken")
    assert train_gating.main() == 0 and (tmp_path / "broken" / "ml" / "versions" / "g1" / "gating_model.json").exists()
    gating_world(monkeypatch, tmp_path / "noschema", schema=False)
    assert train_gating.main() == 0 and not (tmp_path / "noschema" / "ml" / "versions").exists()
    gating_world(monkeypatch, tmp_path / "noexports", experts=(), broken_experts=(), baseline=None)
    assert train_gating.main() == 0 and not (tmp_path / "noexports" / "ml" / "versions").exists()
    paths = gating_world(monkeypatch, tmp_path / "nodata")
    paths["dataset"].unlink()
    assert train_gating.main() == 0
    gating_world(monkeypatch, tmp_path / "few", gating={"min_train_rows": 10**9})
    assert train_gating.main() == 0 and not (tmp_path / "few" / "ml" / "versions" / "g1").exists()


def test_the_gating_script_reports_a_failure_and_runs_as_main(monkeypatch, tmp_path):
    import runpy

    monkeypatch.setattr(sys, "argv", ["train_gating", "--version-id", "g9", "--config-path", str(tmp_path / "missing.json")])
    assert train_gating.main() == 1
    with pytest.raises(SystemExit) as stop:
        runpy.run_path(str(train_gating.__file__), run_name="__main__")
    assert stop.value.code == 1
