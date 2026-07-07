"""Tests for train_gating.py — real learned weights for moe/gating.py.

Conventions match tests/test_train_topology.py: no test classes,
module-level helpers, plain dicts/frames. Only the pure dataset/feature
construction functions are exercised here - main()'s file I/O and the
torch training loop are left untested at the unit level, mirroring how
train_topology.py's own main() is not unit-tested either (train_gating.py
was smoke-tested end-to-end against the real dataset manually instead).
"""

import json

import pandas as pd

from moe.gating import EXPERT_NAMES, GATING_MODEL_FEATURE_KEYS
from train_gating import (
    build_gating_training_rows,
    gating_candidate_output_paths,
    load_gating_training_config,
    rows_to_frame,
    shuffle_split,
)


def _linear_sigmoid_model(weights: list[float], bias: float) -> dict:
    """Minimal hand-verifiable export, same shape train.py::export_architecture()
    always produces - reused here as a stand-in baseline/expert model."""
    return {
        "export": {
            "architecture": [
                {"type": "linear", "weight_key": "l1.weight", "bias_key": "l1.bias"},
                {"type": "sigmoid"},
            ],
            "state_dict": {
                "l1.weight": [weights],
                "l1.bias": [bias],
            },
        }
    }


def _feature_schema() -> dict:
    return {
        "model_input_names": ["momentum_5d", "momentum_20d"],
        "feature_names": ["momentum_5d", "momentum_20d", "rolling_volatility_20d"],
    }


def _expert_training_metrics() -> dict:
    return {
        "experts": {
            expert: {
                "quality_gate": {"quality_status": "stable", "gating_eligible": True},
                "validation": {"balanced_accuracy": 0.55},
                "backtest": {"balanced_accuracy": 0.53, "mcc": 0.05},
            }
            for expert in EXPERT_NAMES
        }
    }


def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"momentum_5d": 0.03, "momentum_20d": 0.05, "rolling_volatility_20d": 0.01, "target_direction": 1},
            {"momentum_5d": -0.03, "momentum_20d": -0.05, "rolling_volatility_20d": 0.02, "target_direction": 0},
            {"momentum_5d": 0.0, "momentum_20d": 0.0, "rolling_volatility_20d": 0.04, "target_direction": 1},
        ]
    )


# ---------------------------------------------------------------------------
# build_gating_training_rows
# ---------------------------------------------------------------------------


def test_build_gating_training_rows_returns_one_row_per_input_row():
    frame = _sample_frame()
    baseline_export = _linear_sigmoid_model([0.5, -0.5], 0.1)
    expert_exports = {expert: _linear_sigmoid_model([0.2, 0.3], 0.0) for expert in EXPERT_NAMES}

    rows, labels = build_gating_training_rows(
        frame, _feature_schema(), _expert_training_metrics(), baseline_export, expert_exports
    )

    assert len(rows) == len(frame) == len(labels)
    assert labels == [1.0, 0.0, 1.0]
    for row in rows:
        assert len(row) == len(GATING_MODEL_FEATURE_KEYS) == 26
        assert all(isinstance(value, float) for value in row)


def test_build_gating_training_rows_defaults_to_half_probability_when_models_missing():
    frame = _sample_frame().iloc[:1]

    rows, _ = build_gating_training_rows(frame, _feature_schema(), _expert_training_metrics(), None, {})

    row = rows[0]
    # every expert's probability_up slot (index 0, 4, 8, 12) and the
    # baseline slot (index 16) default to 0.5 when no model is available
    for index in (0, 4, 8, 12, 16):
        assert row[index] == 0.5


# ---------------------------------------------------------------------------
# rows_to_frame / shuffle_split
# ---------------------------------------------------------------------------


def test_rows_to_frame_shape_and_columns():
    rows = [[0.1] * 26, [0.2] * 26]
    labels = [1.0, 0.0]

    frame = rows_to_frame(rows, labels)

    assert list(frame.columns) == list(GATING_MODEL_FEATURE_KEYS) + ["target_direction"]
    assert len(frame) == 2
    assert frame["target_direction"].tolist() == [1.0, 0.0]


def test_shuffle_split_preserves_row_count_and_is_deterministic():
    rows = [[float(i)] * 26 for i in range(20)]
    labels = [float(i % 2) for i in range(20)]
    frame = rows_to_frame(rows, labels)

    fit_a, holdout_a = shuffle_split(frame, holdout_fraction=0.25, seed=7)
    fit_b, holdout_b = shuffle_split(frame, holdout_fraction=0.25, seed=7)

    assert len(fit_a) + len(holdout_a) == len(frame)
    assert len(holdout_a) == 5
    assert fit_a.equals(fit_b)
    assert holdout_a.equals(holdout_b)


def test_shuffle_split_holdout_always_at_least_one_row():
    rows = [[0.0] * 26, [1.0] * 26]
    frame = rows_to_frame(rows, [0.0, 1.0])

    fit, holdout = shuffle_split(frame, holdout_fraction=0.01, seed=1)

    assert len(holdout) >= 1
    assert len(fit) + len(holdout) == 2


# ---------------------------------------------------------------------------
# gating_candidate_output_paths / load_gating_training_config
# ---------------------------------------------------------------------------


def test_gating_candidate_output_paths_shape():
    paths = gating_candidate_output_paths("abc-123")

    assert paths["gating_model"].name == "gating_model.json"
    assert paths["gating_feature_schema"].name == "gating_feature_schema.json"
    assert paths["gating_training_metrics"].name == "gating_training_metrics.json"
    assert paths["version_dir"].name == "abc-123"
    for key in ("gating_model", "gating_feature_schema", "gating_training_metrics"):
        assert paths[key].parent == paths["version_dir"]


def test_load_gating_training_config_reads_nested_block(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"phase_v2": {"retraining": {"gating_training": {"enabled": True, "epochs": 5}}}}),
        encoding="utf-8",
    )

    config = load_gating_training_config(config_path)

    assert config == {"enabled": True, "epochs": 5}


def test_load_gating_training_config_defaults_to_empty_dict_when_missing(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"phase_v2": {}}), encoding="utf-8")

    config = load_gating_training_config(config_path)

    assert config == {}
