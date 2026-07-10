"""Tests for train_multitask.py — the offline trainer for the joint
direction+magnitude+volatility model (AetherNetMultiTask, train.py).

Conventions match tests/test_train_gating.py: no test classes, module-level
helpers, plain dicts/frames. Only the pure config/path/tensor-building
functions are exercised here - main()'s file I/O and the torch training
loop are left untested at the unit level (smoke-tested end-to-end against
the real dataset manually instead, see development/Changelog.md).
"""

import json

import pandas as pd
import pytest
import torch

from train import AetherNetMultiTask
from train_multitask import (
    frame_to_multitask_tensors,
    load_multitask_training_config,
    multitask_candidate_output_paths,
)


def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"f1": 0.1, "f2": -0.2, "target_direction": 1, "target_return_1d": 0.01, "target_volatility_next_day": 0.02},
            {"f1": -0.1, "f2": 0.2, "target_direction": 0, "target_return_1d": -0.01, "target_volatility_next_day": 0.03},
            {"f1": 0.0, "f2": 0.0, "target_direction": 1, "target_return_1d": 0.0, "target_volatility_next_day": 0.01},
        ]
    )


# ---------------------------------------------------------------------------
# frame_to_multitask_tensors
# ---------------------------------------------------------------------------


def test_frame_to_multitask_tensors_shapes_and_values():
    frame = _sample_frame()

    features, direction, magnitude, volatility = frame_to_multitask_tensors(frame, ["f1", "f2"])

    assert features.shape == (3, 2)
    assert direction.tolist() == [1.0, 0.0, 1.0]
    assert magnitude.tolist() == pytest.approx([0.01, -0.01, 0.0], abs=1e-6)
    assert volatility.tolist() == pytest.approx([0.02, 0.03, 0.01], abs=1e-6)


def test_frame_to_multitask_tensors_matches_row_order():
    frame = _sample_frame()

    features, _, _, _ = frame_to_multitask_tensors(frame, ["f1", "f2"])

    assert features[0].tolist() == pytest.approx([0.1, -0.2], abs=1e-6)
    assert features[1].tolist() == pytest.approx([-0.1, 0.2], abs=1e-6)
    assert features[2].tolist() == pytest.approx([0.0, 0.0], abs=1e-6)


# ---------------------------------------------------------------------------
# AetherNetMultiTask forward shape (used directly by the trainer)
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
