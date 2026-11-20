"""Tests for train_sequence.py - the offline trainer for the Phase 2
causal-TCN sequence-encoder multitask model (AetherNetSequenceMultiTaskHorizons,
train.py).

Conventions match tests/test_train_multitask.py: no test classes,
module-level helpers, plain dicts/frames. Only the pure config/path/
tensor-building functions are exercised here - main()'s file I/O and the
torch training loop are left untested at the unit level (smoke-tested
end-to-end against the real dataset manually instead, see
development/Changelog.md). The shared horizon-head machinery
(HORIZON_HEAD_SPECS, resolve_horizon_head_config, etc.) is train.py's own
and is tested in tests/test_train_multitask.py - not repeated here.
"""

import json

import numpy as np
import pandas as pd
import pytest
import torch

from train import AetherNetSequenceMultiTaskHorizons
from train_sequence import (
    _split_sequence_tensors,
    compute_sequence_multitask_metrics,
    load_sequence_training_config,
    sequence_candidate_output_paths,
)


def _sample_dataset() -> pd.DataFrame:
    rows = []
    for ticker, split in (("A", "train"), ("B", "validation")):
        for day in range(3):
            rows.append(
                {
                    "ticker": ticker,
                    "split": split,
                    "date": f"2020-01-{day + 1:02d}",
                    "target_direction": float(day % 2),
                    "target_return_1d": 0.01 * day,
                    "target_volatility_next_day": 0.02,
                    "target_direction_5d": float(day % 2) if day < 2 else np.nan,
                    "target_direction_20d": np.nan,
                    "target_rank_5d": 0.5,
                    "target_rank_20d": np.nan,
                    "target_sector_neutral_rank_20d": 0.5,
                    "target_residual_rank_5d": 0.5,
                    "target_residual_rank_20d": np.nan,
                    "target_beta_neutral_rank_20d": 0.5,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# sequence_candidate_output_paths / load_sequence_training_config
# ---------------------------------------------------------------------------


def test_sequence_candidate_output_paths_shape():
    paths = sequence_candidate_output_paths("abc-123")

    assert paths["sequence_model"].name == "sequence_model.json"
    assert paths["sequence_feature_schema"].name == "sequence_feature_schema.json"
    assert paths["sequence_training_metrics"].name == "sequence_training_metrics.json"
    assert paths["version_dir"].name == "abc-123"
    for key in ("sequence_model", "sequence_feature_schema", "sequence_training_metrics"):
        assert paths[key].parent == paths["version_dir"]


def test_load_sequence_training_config_reads_nested_block(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"phase_v2": {"retraining": {"sequence_training": {"enabled": True, "epochs": 5}}}}),
        encoding="utf-8",
    )

    config = load_sequence_training_config(config_path)

    assert config == {"enabled": True, "epochs": 5}


def test_load_sequence_training_config_defaults_to_empty_dict_when_missing(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"phase_v2": {}}), encoding="utf-8")

    config = load_sequence_training_config(config_path)

    assert config == {}


# ---------------------------------------------------------------------------
# _split_sequence_tensors
# ---------------------------------------------------------------------------


def test_split_sequence_tensors_filters_by_split_and_includes_all_heads():
    dataset = _sample_dataset()
    sequences = np.zeros((len(dataset), 2, 3), dtype=np.float32)

    features, targets, dates = _split_sequence_tensors(dataset, sequences, "train")

    assert features.shape == (3, 2, 3)  # only ticker A's 3 rows are "train"
    assert len(dates) == 3
    for head_name in ("direction", "magnitude", "volatility", "direction_5d", "direction_20d", "rank_5d", "rank_20d"):
        assert head_name in targets
        assert targets[head_name].shape == (3,)


def test_split_sequence_tensors_preserves_nan_in_horizon_targets():
    dataset = _sample_dataset()
    sequences = np.zeros((len(dataset), 2, 3), dtype=np.float32)

    _, targets, _ = _split_sequence_tensors(dataset, sequences, "train")

    # target_direction_20d is NaN for every row in the fixture.
    assert torch.isnan(targets["direction_20d"]).all()
    # target_direction_5d is NaN only on the last row (day=2).
    assert torch.isnan(targets["direction_5d"])[-1]
    assert not torch.isnan(targets["direction_5d"])[:-1].any()


# ---------------------------------------------------------------------------
# compute_sequence_multitask_metrics
# ---------------------------------------------------------------------------


def test_compute_sequence_multitask_metrics_reports_none_for_disabled_heads():
    model = AetherNetSequenceMultiTaskHorizons(input_dim=3, channels=[4], kernel_size=2, dropout=0.0)
    features = torch.randn(4, 2, 3)
    targets = {
        "direction": torch.tensor([1.0, 0.0, 1.0, 0.0]),
        "magnitude": torch.zeros(4),
        "volatility": torch.zeros(4),
        "direction_5d": torch.zeros(4),
        "direction_20d": torch.zeros(4),
        "rank_5d": torch.full((4,), 0.5),
        "rank_20d": torch.full((4,), 0.5),
        "sector_neutral_rank_20d": torch.full((4,), 0.5),
        "residual_rank_5d": torch.full((4,), 0.5),
        "residual_rank_20d": torch.full((4,), 0.5),
        "beta_neutral_rank_20d": torch.full((4,), 0.5),
    }
    dates = pd.Series(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"])
    criterion = torch.nn.BCEWithLogitsLoss()
    horizon_head_config = {
        "direction_5d": {"enabled": False, "loss_weight": 1.0},
        "direction_20d": {"enabled": False, "loss_weight": 0.5},
        "rank_5d": {"enabled": False, "loss_weight": 1.0},
        "rank_20d": {"enabled": False, "loss_weight": 0.5},
        "sector_neutral_rank_20d": {"enabled": False, "loss_weight": 0.3},
        "residual_rank_5d": {"enabled": False, "loss_weight": 0.5},
        "residual_rank_20d": {"enabled": False, "loss_weight": 1.0},
        "beta_neutral_rank_20d": {"enabled": False, "loss_weight": 0.0},
    }

    metrics = compute_sequence_multitask_metrics(
        model, features, targets, dates, criterion, 0.5, {"direction": 0.5}, horizon_head_config
    )

    assert metrics["direction_5d"] is None
    assert metrics["rank_5d"] is None
    assert "rank_5d_ic" not in metrics
    assert metrics["direction"] is not None
    assert metrics["magnitude"] is not None


def test_compute_sequence_multitask_metrics_includes_rank_ic_for_enabled_rank_head():
    model = AetherNetSequenceMultiTaskHorizons(input_dim=3, channels=[4], kernel_size=2, dropout=0.0)
    features = torch.randn(4, 2, 3)
    targets = {
        "direction": torch.tensor([1.0, 0.0, 1.0, 0.0]),
        "magnitude": torch.zeros(4),
        "volatility": torch.zeros(4),
        "direction_5d": torch.zeros(4),
        "direction_20d": torch.zeros(4),
        "rank_5d": torch.tensor([0.9, 0.1, 0.9, 0.1]),
        "rank_20d": torch.full((4,), float("nan")),
        "sector_neutral_rank_20d": torch.full((4,), float("nan")),
        "residual_rank_5d": torch.full((4,), float("nan")),
        "residual_rank_20d": torch.full((4,), float("nan")),
        "beta_neutral_rank_20d": torch.full((4,), float("nan")),
    }
    dates = pd.Series(["2020-01-01", "2020-01-01", "2020-01-02", "2020-01-02"])
    criterion = torch.nn.BCEWithLogitsLoss()
    horizon_head_config = {
        "direction_5d": {"enabled": False, "loss_weight": 1.0},
        "direction_20d": {"enabled": False, "loss_weight": 0.5},
        "rank_5d": {"enabled": True, "loss_weight": 1.0},
        "rank_20d": {"enabled": True, "loss_weight": 0.5},
        "sector_neutral_rank_20d": {"enabled": False, "loss_weight": 0.3},
        "residual_rank_5d": {"enabled": False, "loss_weight": 0.5},
        "residual_rank_20d": {"enabled": False, "loss_weight": 1.0},
        "beta_neutral_rank_20d": {"enabled": False, "loss_weight": 0.0},
    }

    metrics = compute_sequence_multitask_metrics(
        model, features, targets, dates, criterion, 0.5, {"direction": 0.5}, horizon_head_config
    )

    assert metrics["rank_5d"] is not None
    assert "rank_5d_ic" in metrics
    assert "rank_5d_ic_non_overlapping" in metrics
    # rank_20d is enabled but every target is NaN - metrics still computed
    # (masked to empty), IC degrades to the "no valid dates" zero-result.
    assert metrics["rank_20d"] is None
    assert metrics["rank_20d_ic"]["num_dates"] == 0


# V6.6.10: the low memory profile trains the same model, checkpoints every epoch and resumes where it stopped


def _run_low(monkeypatch, root, argv=(), **world):
    import sys

    import train_sequence
    from trainer_fakes import write_world

    paths = write_world(root, **world)
    monkeypatch.setattr(train_sequence, "ML_DIR", root / "ml")
    monkeypatch.setattr(sys, "argv", ["train_sequence", "--version-id", "s1", "--config-path", str(paths["config"]), "--dataset-path", str(paths["dataset"]),
                                      "--feature-schema-path", str(paths["schema"]), *argv])
    code = train_sequence.main()
    model = root / "ml" / "versions" / "s1" / "sequence_model.json"
    return code, (json.loads(model.read_text(encoding="utf-8"))["export"] if model.exists() else None)


@pytest.mark.parametrize("batch_mode", ["cross_sectional", "random"])
def test_the_low_profile_trains_the_same_model(monkeypatch, tmp_path, batch_mode):
    overrides = {"batch_mode": batch_mode} if batch_mode == "cross_sectional" else {"batch_mode": "random", "ranking_loss": None}
    code, standard = _run_low(monkeypatch, tmp_path / "standard", ["--seed", "5"], sequence_overrides=overrides, epochs=3)
    peaks = tmp_path / "peaks.jsonl"
    code_low, low = _run_low(monkeypatch, tmp_path / "low", ["--seed", "5", "--memory-profile", "low", "--log-peak-memory", str(peaks)], sequence_overrides=overrides, epochs=3)
    assert code == code_low == 0 and standard == low, "lazy windows are the dense windows: the same batches, the same weights"
    assert json.loads(peaks.read_text(encoding="utf-8").splitlines()[0])["stage"] == "sequence"
    assert not (tmp_path / "low" / "ml" / "versions" / "s1" / "checkpoint.pt").exists(), "a finished run leaves no checkpoint"


def test_an_interrupted_low_run_resumes_to_the_same_model(monkeypatch, tmp_path):
    import train_sequence

    overrides = {"batch_mode": "cross_sectional", "label_noise_std": 0.01}
    _, whole = _run_low(monkeypatch, tmp_path / "whole", ["--memory-profile", "low"], sequence_overrides=overrides, epochs=4)
    real_save = train_sequence.save_checkpoint

    def save_then_stop(path, state):
        real_save(path, state)
        if state["epoch"] == 2:
            raise RuntimeError("power cut")

    monkeypatch.setattr(train_sequence, "save_checkpoint", save_then_stop)
    code, _ = _run_low(monkeypatch, tmp_path / "cut", ["--memory-profile", "low"], sequence_overrides=overrides, epochs=4)
    assert code == 1 and (tmp_path / "cut" / "ml" / "versions" / "s1" / "checkpoint.pt").exists()
    monkeypatch.setattr(train_sequence, "save_checkpoint", real_save)
    code, resumed = _run_low(monkeypatch, tmp_path / "cut", ["--memory-profile", "low", "--resume"], sequence_overrides=overrides, epochs=4)
    assert code == 0 and resumed == whole


def test_a_run_that_had_already_stopped_resumes_straight_to_its_artifacts(monkeypatch, tmp_path):
    import train_sequence

    overrides = {"patience": 1, "min_best_epoch": 1, "learning_rate": 0.5, "lr_schedule": "none"}
    real_threshold = train_sequence.find_optimal_threshold
    monkeypatch.setattr(train_sequence, "find_optimal_threshold", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("after the loop")))
    code, _ = _run_low(monkeypatch, tmp_path, ["--memory-profile", "low"], sequence_overrides=overrides, epochs=30)
    checkpoint = tmp_path / "ml" / "versions" / "s1" / "checkpoint.pt"
    assert code == 1 and torch.load(checkpoint, weights_only=False)["stopped"]
    monkeypatch.setattr(train_sequence, "find_optimal_threshold", real_threshold)
    code, export = _run_low(monkeypatch, tmp_path, ["--memory-profile", "low", "--resume"], sequence_overrides=overrides, epochs=30)
    assert code == 0 and export is not None and not checkpoint.exists()


def test_a_lazy_split_indexes_like_a_tensor():
    from train_sequence import LazySequenceWindows, forward_in_batches

    matrix = np.arange(12, dtype=np.float32).reshape(6, 2)
    windows = LazySequenceWindows(matrix, np.array([[-1, 0], [0, 1], [1, 2]], dtype=np.int32))
    assert len(windows) == 3 and windows.to("cpu") is windows
    assert torch.equal(windows[torch.tensor([2])], torch.tensor([[[2.0, 3.0], [4.0, 5.0]]]))
    assert torch.equal(windows[0:1], torch.tensor([[[0.0, 0.0], [0.0, 1.0]]]))
    model = lambda features: {"sum": features.sum(dim=(1, 2))}  # noqa: E731
    assert torch.equal(forward_in_batches(model, windows, batch_rows=2)["sum"], forward_in_batches(model, windows)["sum"])


@pytest.mark.parametrize("objective", ["ic_pearson", "ls_sharpe", "class_balanced", "cost_aware"])
def test_each_r_loss1_objective_trains_the_sequence_model(monkeypatch, tmp_path, objective):
    """V6.6.10: the context objectives get their per-row classes, tickers and returns through the batches."""
    from trainer_fakes import make_frame

    frame = make_frame()
    frame["asset_class_equity"] = [1.0 if int(t[1:]) % 2 else 0.0 for t in frame["ticker"]]
    frame["asset_class_crypto"] = 1.0 - frame["asset_class_equity"]
    frame["target_return_20d"] = frame["target_rank_20d"] * 0.1 - 0.05
    overrides = {"batch_mode": "cross_sectional"}
    code, export = _run_low(monkeypatch, tmp_path, ["--ranking-objective", objective, "--memory-profile", "low"], frame=frame, sequence_overrides=overrides, epochs=2)
    assert code == 0 and export is not None
