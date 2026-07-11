"""Tests for train_multitask.py — the offline trainer for the joint
direction+magnitude+volatility model (AetherNetMultiTask, train.py).

Conventions match tests/test_train_gating.py: no test classes, module-level
helpers, plain dicts/frames. Only the pure config/path/tensor-building
functions are exercised here - main()'s file I/O and the torch training
loop are left untested at the unit level (smoke-tested end-to-end against
the real dataset manually instead, see development/Changelog.md).
"""

import json

import numpy as np
import pandas as pd
import pytest
import torch
import torch.nn as nn

from train import (
    HORIZON_HEAD_SPECS,
    AetherNetMultiTask,
    AetherNetMultiTaskHorizons,
    compute_combined_multitask_loss,
    find_optimal_masked_threshold,
    resolve_horizon_head_config,
)
from train_multitask import (
    frame_to_multitask_tensors,
    load_multitask_training_config,
    multitask_candidate_output_paths,
)


def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "f1": 0.1, "f2": -0.2, "target_direction": 1, "target_return_1d": 0.01,
                "target_volatility_next_day": 0.02, "target_direction_5d": 1.0, "target_direction_20d": 0.0,
                "target_rank_5d": 0.8, "target_rank_20d": np.nan,
            },
            {
                "f1": -0.1, "f2": 0.2, "target_direction": 0, "target_return_1d": -0.01,
                "target_volatility_next_day": 0.03, "target_direction_5d": 0.0, "target_direction_20d": np.nan,
                "target_rank_5d": 0.2, "target_rank_20d": 0.5,
            },
            {
                "f1": 0.0, "f2": 0.0, "target_direction": 1, "target_return_1d": 0.0,
                "target_volatility_next_day": 0.01, "target_direction_5d": np.nan, "target_direction_20d": 1.0,
                "target_rank_5d": 0.5, "target_rank_20d": 0.9,
            },
        ]
    )


# ---------------------------------------------------------------------------
# frame_to_multitask_tensors
# ---------------------------------------------------------------------------


def test_frame_to_multitask_tensors_shapes_and_values():
    frame = _sample_frame()

    features, targets = frame_to_multitask_tensors(frame, ["f1", "f2"])

    assert features.shape == (3, 2)
    assert targets["direction"].tolist() == [1.0, 0.0, 1.0]
    assert targets["magnitude"].tolist() == pytest.approx([0.01, -0.01, 0.0], abs=1e-6)
    assert targets["volatility"].tolist() == pytest.approx([0.02, 0.03, 0.01], abs=1e-6)


def test_frame_to_multitask_tensors_includes_all_horizon_heads_with_nan_preserved():
    frame = _sample_frame()

    _, targets = frame_to_multitask_tensors(frame, ["f1", "f2"])

    for head_name in HORIZON_HEAD_SPECS:
        assert head_name in targets
    assert torch.isnan(targets["direction_20d"][1])
    assert torch.isnan(targets["direction_5d"][2])
    assert torch.isnan(targets["rank_20d"][0])
    assert targets["rank_5d"].tolist() == pytest.approx([0.8, 0.2, 0.5], abs=1e-6)


def test_frame_to_multitask_tensors_matches_row_order():
    frame = _sample_frame()

    features, _ = frame_to_multitask_tensors(frame, ["f1", "f2"])

    assert features[0].tolist() == pytest.approx([0.1, -0.2], abs=1e-6)
    assert features[1].tolist() == pytest.approx([-0.1, 0.2], abs=1e-6)
    assert features[2].tolist() == pytest.approx([0.0, 0.0], abs=1e-6)


# ---------------------------------------------------------------------------
# AetherNetMultiTask forward shape (still used by train.py's per-expert
# multitask heads - deliberately unchanged, see AetherNetMultiTaskHorizons's
# docstring for why a new sibling class exists instead)
# ---------------------------------------------------------------------------


def test_aether_net_multitask_forward_returns_three_scalars_per_row():
    model = AetherNetMultiTask(input_dim=2, hidden_layers=[4], dropout=0.0, activation="relu", normalization="none")
    model.eval()

    with torch.no_grad():
        direction_logits, magnitude, volatility = model(torch.zeros((3, 2), dtype=torch.float32))

    assert direction_logits.shape == (3,)
    assert magnitude.shape == (3,)
    assert volatility.shape == (3,)
    assert torch.all(volatility >= 0.0)


# ---------------------------------------------------------------------------
# AetherNetMultiTaskHorizons forward shape
# ---------------------------------------------------------------------------


def test_aether_net_multitask_horizons_forward_returns_seven_heads():
    model = AetherNetMultiTaskHorizons(input_dim=2, hidden_layers=[4], dropout=0.0, activation="relu", normalization="none")
    model.eval()

    with torch.no_grad():
        outputs = model(torch.zeros((3, 2), dtype=torch.float32))

    expected_heads = {"direction", "magnitude", "volatility", "direction_5d", "direction_20d", "rank_5d", "rank_20d"}
    assert set(outputs.keys()) == expected_heads
    for head_name, tensor in outputs.items():
        assert tensor.shape == (3,)
    assert torch.all(outputs["volatility"] >= 0.0)


# ---------------------------------------------------------------------------
# resolve_horizon_head_config
# ---------------------------------------------------------------------------


def test_resolve_horizon_head_config_uses_defaults_when_absent():
    resolved = resolve_horizon_head_config({})

    assert resolved["direction_5d"] == {"enabled": True, "loss_weight": 1.0}
    assert resolved["direction_20d"] == {"enabled": True, "loss_weight": 0.5}
    assert resolved["rank_5d"] == {"enabled": True, "loss_weight": 1.0}
    assert resolved["rank_20d"] == {"enabled": True, "loss_weight": 0.5}


def test_resolve_horizon_head_config_merges_partial_override():
    resolved = resolve_horizon_head_config({"horizon_heads": {"direction_5d": {"enabled": False}}})

    # loss_weight default preserved even though only "enabled" was overridden.
    assert resolved["direction_5d"] == {"enabled": False, "loss_weight": 1.0}
    assert resolved["direction_20d"] == {"enabled": True, "loss_weight": 0.5}


# ---------------------------------------------------------------------------
# find_optimal_masked_threshold
# ---------------------------------------------------------------------------


def test_find_optimal_masked_threshold_ignores_nan_rows():
    logits = torch.tensor([5.0, -5.0, 5.0, -5.0], dtype=torch.float32)
    targets = torch.tensor([1.0, 0.0, float("nan"), float("nan")], dtype=torch.float32)
    criterion = nn.BCEWithLogitsLoss()

    threshold, metrics = find_optimal_masked_threshold(logits, targets, criterion, "mcc", 0.35, 0.65, 7)

    assert threshold is not None
    assert metrics["mcc"] == pytest.approx(1.0)


def test_find_optimal_masked_threshold_returns_none_when_all_nan():
    logits = torch.tensor([5.0, -5.0], dtype=torch.float32)
    targets = torch.tensor([float("nan"), float("nan")], dtype=torch.float32)
    criterion = nn.BCEWithLogitsLoss()

    threshold, metrics = find_optimal_masked_threshold(logits, targets, criterion, "mcc", 0.35, 0.65, 7)

    assert threshold is None
    assert metrics is None


# ---------------------------------------------------------------------------
# compute_combined_loss
# ---------------------------------------------------------------------------


def test_compute_combined_loss_is_zero_contribution_from_disabled_heads():
    torch.manual_seed(0)
    outputs = {
        "direction": torch.zeros(4), "magnitude": torch.zeros(4), "volatility": torch.zeros(4).abs(),
        "direction_5d": torch.randn(4), "direction_20d": torch.randn(4),
        "rank_5d": torch.rand(4), "rank_20d": torch.rand(4),
    }
    targets = {
        "direction": torch.zeros(4), "magnitude": torch.zeros(4), "volatility": torch.zeros(4),
        "direction_5d": torch.full((4,), float("nan")), "direction_20d": torch.full((4,), float("nan")),
        "rank_5d": torch.full((4,), float("nan")), "rank_20d": torch.full((4,), float("nan")),
    }
    criterion = nn.BCEWithLogitsLoss()
    horizon_head_config = {name: {"enabled": False, "loss_weight": 1.0} for name in HORIZON_HEAD_SPECS}

    loss_disabled = compute_combined_multitask_loss(outputs, targets, criterion, 1.0, 1.0, horizon_head_config)

    horizon_head_config_all_nan_but_enabled = {name: {"enabled": True, "loss_weight": 1.0} for name in HORIZON_HEAD_SPECS}
    loss_enabled_but_all_nan = compute_combined_multitask_loss(
        outputs, targets, criterion, 1.0, 1.0, horizon_head_config_all_nan_but_enabled
    )

    # Disabled heads and all-NaN-target enabled heads must both add zero -
    # the two should be identical since the mask is empty either way.
    assert torch.isclose(loss_disabled, loss_enabled_but_all_nan)


# ---------------------------------------------------------------------------
# multitask_candidate_output_paths / load_multitask_training_config
# ---------------------------------------------------------------------------


def test_multitask_candidate_output_paths_shape():
    paths = multitask_candidate_output_paths("abc-123")

    assert paths["multitask_model"].name == "multitask_model.json"
    assert paths["multitask_feature_schema"].name == "multitask_feature_schema.json"
    assert paths["multitask_training_metrics"].name == "multitask_training_metrics.json"
    assert paths["version_dir"].name == "abc-123"
    for key in ("multitask_model", "multitask_feature_schema", "multitask_training_metrics"):
        assert paths[key].parent == paths["version_dir"]


def test_load_multitask_training_config_reads_nested_block(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"phase_v2": {"retraining": {"multitask_training": {"enabled": True, "epochs": 5}}}}),
        encoding="utf-8",
    )

    config = load_multitask_training_config(config_path)

    assert config == {"enabled": True, "epochs": 5}


def test_load_multitask_training_config_defaults_to_empty_dict_when_missing(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"phase_v2": {}}), encoding="utf-8")

    config = load_multitask_training_config(config_path)

    assert config == {}
