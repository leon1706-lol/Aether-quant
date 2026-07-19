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
    compute_horizon_consistency_loss,
    export_multitask_horizons_architecture,
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
                "target_rank_5d": 0.8, "target_rank_20d": np.nan, "target_sector_neutral_rank_20d": 0.7,
            },
            {
                "f1": -0.1, "f2": 0.2, "target_direction": 0, "target_return_1d": -0.01,
                "target_volatility_next_day": 0.03, "target_direction_5d": 0.0, "target_direction_20d": np.nan,
                "target_rank_5d": 0.2, "target_rank_20d": 0.5, "target_sector_neutral_rank_20d": np.nan,
            },
            {
                "f1": 0.0, "f2": 0.0, "target_direction": 1, "target_return_1d": 0.0,
                "target_volatility_next_day": 0.01, "target_direction_5d": np.nan, "target_direction_20d": 1.0,
                "target_rank_5d": 0.5, "target_rank_20d": 0.9, "target_sector_neutral_rank_20d": 0.4,
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


def test_aether_net_multitask_horizons_forward_returns_eight_heads():
    model = AetherNetMultiTaskHorizons(input_dim=2, hidden_layers=[4], dropout=0.0, activation="relu", normalization="none")
    model.eval()

    with torch.no_grad():
        outputs = model(torch.zeros((3, 2), dtype=torch.float32))

    expected_heads = {
        "direction", "magnitude", "volatility", "direction_5d", "direction_20d",
        "rank_5d", "rank_20d", "sector_neutral_rank_20d",
    }
    assert set(outputs.keys()) == expected_heads
    for head_name, tensor in outputs.items():
        assert tensor.shape == (3,)
    assert torch.all(outputs["volatility"] >= 0.0)


def test_export_multitask_horizons_architecture_shape():
    model = AetherNetMultiTaskHorizons(input_dim=4, hidden_layers=[6, 6], dropout=0.1, activation="relu", normalization="none")

    export = export_multitask_horizons_architecture(model)

    assert set(export.keys()) == {"trunk", "heads"}
    assert set(export["heads"].keys()) == {
        "direction", "magnitude", "volatility", "direction_5d", "direction_20d",
        "rank_5d", "rank_20d", "sector_neutral_rank_20d",
    }


def test_export_multitask_horizons_architecture_weight_keys_are_disjoint_per_head():
    model = AetherNetMultiTaskHorizons(input_dim=3, hidden_layers=[4], dropout=0.0, activation="relu", normalization="none")

    export = export_multitask_horizons_architecture(model)

    trunk_weight_keys = [layer["weight_key"] for layer in export["trunk"] if "weight_key" in layer]
    head_weight_keys = [head[0]["weight_key"] for head in export["heads"].values()]
    all_keys = trunk_weight_keys + head_weight_keys
    assert len(all_keys) == len(set(all_keys))


# ---------------------------------------------------------------------------
# resolve_horizon_head_config
# ---------------------------------------------------------------------------


def test_resolve_horizon_head_config_uses_defaults_when_absent():
    resolved = resolve_horizon_head_config({})

    assert resolved["direction_5d"] == {"enabled": True, "loss_weight": 1.0}
    assert resolved["direction_20d"] == {"enabled": True, "loss_weight": 0.5}
    assert resolved["rank_5d"] == {"enabled": True, "loss_weight": 1.0}
    assert resolved["rank_20d"] == {"enabled": True, "loss_weight": 0.5}
    assert resolved["sector_neutral_rank_20d"] == {"enabled": True, "loss_weight": 0.3}


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
        "rank_5d": torch.rand(4), "rank_20d": torch.rand(4), "sector_neutral_rank_20d": torch.rand(4),
    }
    targets = {
        "direction": torch.zeros(4), "magnitude": torch.zeros(4), "volatility": torch.zeros(4),
        "direction_5d": torch.full((4,), float("nan")), "direction_20d": torch.full((4,), float("nan")),
        "rank_5d": torch.full((4,), float("nan")), "rank_20d": torch.full((4,), float("nan")),
        "sector_neutral_rank_20d": torch.full((4,), float("nan")),
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


def _direction_only_loss_inputs():
    """Shared fixture for direction_loss_weight tests below - magnitude/
    volatility weights are zeroed at the call site so only the direction
    term contributes, isolating direction_loss_weight's effect precisely."""
    outputs = {
        "direction": torch.tensor([2.0, -2.0, 2.0, -2.0]),
        "magnitude": torch.zeros(4), "volatility": torch.zeros(4).abs(),
        "direction_5d": torch.randn(4), "direction_20d": torch.randn(4),
        "rank_5d": torch.rand(4), "rank_20d": torch.rand(4), "sector_neutral_rank_20d": torch.rand(4),
    }
    targets = {
        "direction": torch.tensor([1.0, 0.0, 1.0, 0.0]),
        "magnitude": torch.zeros(4), "volatility": torch.zeros(4),
        "direction_5d": torch.full((4,), float("nan")), "direction_20d": torch.full((4,), float("nan")),
        "rank_5d": torch.full((4,), float("nan")), "rank_20d": torch.full((4,), float("nan")),
        "sector_neutral_rank_20d": torch.full((4,), float("nan")),
    }
    horizon_head_config = {name: {"enabled": False, "loss_weight": 1.0} for name in HORIZON_HEAD_SPECS}
    return outputs, targets, horizon_head_config


def test_compute_combined_loss_direction_loss_weight_scales_direction_term():
    outputs, targets, horizon_head_config = _direction_only_loss_inputs()
    criterion = nn.BCEWithLogitsLoss()

    loss_full_weight = compute_combined_multitask_loss(
        outputs, targets, criterion, 0.0, 0.0, horizon_head_config, direction_loss_weight=1.0
    )
    loss_low_weight = compute_combined_multitask_loss(
        outputs, targets, criterion, 0.0, 0.0, horizon_head_config, direction_loss_weight=0.1
    )
    loss_zero_weight = compute_combined_multitask_loss(
        outputs, targets, criterion, 0.0, 0.0, horizon_head_config, direction_loss_weight=0.0
    )

    assert torch.isclose(loss_low_weight, 0.1 * loss_full_weight)
    assert torch.isclose(loss_zero_weight, torch.zeros(()))


def test_compute_combined_loss_direction_loss_weight_defaults_to_one_backward_compatible():
    """Stage 4 of the rank-pivot roadmap added direction_loss_weight as the
    LAST parameter with default 1.0 specifically so every pre-existing
    positional call site (this file's other compute_combined_multitask_loss
    tests, train_multitask.py/train_sequence.py before their own Stage 4
    edits) keeps behaving identically without passing it."""
    outputs, targets, horizon_head_config = _direction_only_loss_inputs()
    criterion = nn.BCEWithLogitsLoss()

    loss_with_default = compute_combined_multitask_loss(outputs, targets, criterion, 1.0, 1.0, horizon_head_config)
    loss_with_explicit_one = compute_combined_multitask_loss(
        outputs, targets, criterion, 1.0, 1.0, horizon_head_config, direction_loss_weight=1.0
    )

    assert torch.isclose(loss_with_default, loss_with_explicit_one)


# ---------------------------------------------------------------------------
# compute_horizon_consistency_loss (Stage 4 of the rank-pivot roadmap: the
# regularization term penalizing 5d/20d heads that disagree with each other)
# ---------------------------------------------------------------------------


def test_compute_horizon_consistency_loss_zero_when_rank_heads_agree():
    # Both above 0.5 (bullish-of-median on both horizons) - agreement,
    # should contribute zero penalty regardless of magnitude.
    outputs = {
        "rank_5d": torch.tensor([0.9, 0.7]), "rank_20d": torch.tensor([0.8, 0.6]),
        "direction_5d": torch.zeros(2), "direction_20d": torch.zeros(2),
    }
    targets = {
        "rank_5d": torch.tensor([0.5, 0.5]), "rank_20d": torch.tensor([0.5, 0.5]),
        "direction_5d": torch.full((2,), float("nan")), "direction_20d": torch.full((2,), float("nan")),
    }

    loss = compute_horizon_consistency_loss(outputs, targets)

    assert torch.isclose(loss, torch.zeros(()))


def test_compute_horizon_consistency_loss_positive_when_rank_heads_disagree():
    # rank_5d says top-of-cross-section (0.9), rank_20d says bottom (0.1) -
    # opposite sides of 0.5, must be penalized.
    outputs = {
        "rank_5d": torch.tensor([0.9]), "rank_20d": torch.tensor([0.1]),
        "direction_5d": torch.zeros(1), "direction_20d": torch.zeros(1),
    }
    targets = {
        "rank_5d": torch.tensor([0.5]), "rank_20d": torch.tensor([0.5]),
        "direction_5d": torch.full((1,), float("nan")), "direction_20d": torch.full((1,), float("nan")),
    }

    loss = compute_horizon_consistency_loss(outputs, targets)

    assert loss.item() > 0.0


def test_compute_horizon_consistency_loss_positive_when_direction_heads_disagree():
    # direction_5d logit strongly positive (sigmoid >> 0.5), direction_20d
    # logit strongly negative (sigmoid << 0.5) - disagreement, penalized.
    outputs = {
        "rank_5d": torch.zeros(1), "rank_20d": torch.zeros(1),
        "direction_5d": torch.tensor([5.0]), "direction_20d": torch.tensor([-5.0]),
    }
    targets = {
        "rank_5d": torch.full((1,), float("nan")), "rank_20d": torch.full((1,), float("nan")),
        "direction_5d": torch.tensor([1.0]), "direction_20d": torch.tensor([0.0]),
    }

    loss = compute_horizon_consistency_loss(outputs, targets)

    assert loss.item() > 0.0


def test_compute_horizon_consistency_loss_zero_when_direction_heads_agree():
    outputs = {
        "rank_5d": torch.zeros(1), "rank_20d": torch.zeros(1),
        "direction_5d": torch.tensor([5.0]), "direction_20d": torch.tensor([5.0]),
    }
    targets = {
        "rank_5d": torch.full((1,), float("nan")), "rank_20d": torch.full((1,), float("nan")),
        "direction_5d": torch.tensor([1.0]), "direction_20d": torch.tensor([1.0]),
    }

    loss = compute_horizon_consistency_loss(outputs, targets)

    assert torch.isclose(loss, torch.zeros(()), atol=1e-6)


def test_compute_horizon_consistency_loss_masks_rows_missing_either_horizon_target():
    # Row 0: both rank_5d/rank_20d targets valid AND heads disagree -> counts.
    # Row 1: rank_20d target is NaN (trailing row, no full 20d forward
    # window yet) -> must be excluded even though the heads ALSO disagree
    # there - "do these two heads agree" is ill-posed without both targets.
    outputs = {
        "rank_5d": torch.tensor([0.9, 0.9]), "rank_20d": torch.tensor([0.1, 0.1]),
        "direction_5d": torch.zeros(2), "direction_20d": torch.zeros(2),
    }
    targets_both_valid = {
        "rank_5d": torch.tensor([0.5, 0.5]), "rank_20d": torch.tensor([0.5, 0.5]),
        "direction_5d": torch.full((2,), float("nan")), "direction_20d": torch.full((2,), float("nan")),
    }
    targets_second_row_nan = {
        "rank_5d": torch.tensor([0.5, 0.5]), "rank_20d": torch.tensor([0.5, float("nan")]),
        "direction_5d": torch.full((2,), float("nan")), "direction_20d": torch.full((2,), float("nan")),
    }

    loss_both_valid = compute_horizon_consistency_loss(outputs, targets_both_valid)
    loss_second_masked = compute_horizon_consistency_loss(outputs, targets_second_row_nan)

    # Both rows are identical disagreements, so masking one out changes
    # nothing about the MEAN penalty (both rows contribute the same value) -
    # this specifically proves the mask is applied (not ignored), since an
    # unmasked call with an all-NaN target would instead propagate NaN.
    assert torch.isclose(loss_both_valid, loss_second_masked)
    assert not torch.isnan(loss_second_masked)


def test_compute_horizon_consistency_loss_zero_when_all_targets_nan():
    outputs = {
        "rank_5d": torch.tensor([0.9]), "rank_20d": torch.tensor([0.1]),
        "direction_5d": torch.tensor([5.0]), "direction_20d": torch.tensor([-5.0]),
    }
    targets = {
        "rank_5d": torch.full((1,), float("nan")), "rank_20d": torch.full((1,), float("nan")),
        "direction_5d": torch.full((1,), float("nan")), "direction_20d": torch.full((1,), float("nan")),
    }

    loss = compute_horizon_consistency_loss(outputs, targets)

    assert torch.isclose(loss, torch.zeros(()))


def test_compute_combined_loss_consistency_loss_weight_defaults_to_zero_backward_compatible():
    """consistency_loss_weight defaults to 0.0 - a disagreeing rank/direction
    pair must add NO extra loss unless a caller explicitly opts in, so every
    pre-Stage-4 positional call site keeps behaving identically."""
    outputs = {
        "direction": torch.tensor([2.0, -2.0]), "magnitude": torch.zeros(2), "volatility": torch.zeros(2).abs(),
        "direction_5d": torch.tensor([5.0, 5.0]), "direction_20d": torch.tensor([-5.0, -5.0]),
        "rank_5d": torch.tensor([0.9, 0.9]), "rank_20d": torch.tensor([0.1, 0.1]),
        "sector_neutral_rank_20d": torch.rand(2),
    }
    targets = {
        "direction": torch.tensor([1.0, 0.0]), "magnitude": torch.zeros(2), "volatility": torch.zeros(2),
        "direction_5d": torch.tensor([1.0, 1.0]), "direction_20d": torch.tensor([0.0, 0.0]),
        "rank_5d": torch.tensor([0.5, 0.5]), "rank_20d": torch.tensor([0.5, 0.5]),
        "sector_neutral_rank_20d": torch.full((2,), float("nan")),
    }
    criterion = nn.BCEWithLogitsLoss()
    horizon_head_config = {name: {"enabled": True, "loss_weight": 1.0} for name in HORIZON_HEAD_SPECS}
    horizon_head_config["sector_neutral_rank_20d"]["enabled"] = False

    loss_no_consistency = compute_combined_multitask_loss(outputs, targets, criterion, 1.0, 1.0, horizon_head_config)
    loss_zero_weight = compute_combined_multitask_loss(
        outputs, targets, criterion, 1.0, 1.0, horizon_head_config, 1.0, consistency_loss_weight=0.0
    )
    loss_with_consistency = compute_combined_multitask_loss(
        outputs, targets, criterion, 1.0, 1.0, horizon_head_config, 1.0, consistency_loss_weight=0.2
    )

    assert torch.isclose(loss_no_consistency, loss_zero_weight)
    # The heads above deliberately disagree on both pairs, so a positive
    # consistency_loss_weight must strictly increase the combined loss.
    assert loss_with_consistency.item() > loss_no_consistency.item()


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
