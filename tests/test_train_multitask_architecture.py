"""Tests for train.py's multi-task additions: AetherNetMultiTask,
export_multitask_architecture(), compute_regression_metrics(), and the
target_volatility_next_day engineered column - the foundation Phase 1's
multi-task prediction (direction + magnitude + volatility) is built on.

Conventions match the rest of this repo's train.py test coverage: no test
classes, module-level helpers, plain dicts/frames.
"""

import numpy as np
import pandas as pd
import pytest
import torch

from train import (
    AetherNetMultiTask,
    compute_regression_metrics,
    engineer_features,
    export_multitask_architecture,
)


FEATURE_NAMES = [
    "close_to_close_return_1d",
    "close_to_close_return_5d",
    "close_to_close_return_20d",
    "rolling_volatility_5d",
    "rolling_volatility_20d",
    "momentum_5d",
    "momentum_20d",
    "high_low_range_pct",
    "open_close_range_pct",
    "volume_change_1d",
]


# ---------------------------------------------------------------------------
# target_volatility_next_day
# ---------------------------------------------------------------------------


def test_engineer_features_adds_target_volatility_next_day_as_next_rows_range():
    highs = [11.0, 13.0, 13.0, 16.0, 15.0]
    lows = [9.0, 10.0, 11.0, 12.0, 13.0]
    closes = [10.0, 12.0, 11.0, 13.0, 14.0]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=5, freq="D"),
            "open": [10.0, 11.0, 12.0, 13.0, 14.0],
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0, 120.0, 90.0, 150.0, 130.0],
        }
    )
    windows = {
        "training": {"start": "2020-01-01", "end": "2020-01-05"},
        "validation": {"start": "2020-02-01", "end": "2020-02-28"},
        "backtest": {"start": "2020-03-01", "end": "2020-03-31"},
    }

    engineered = engineer_features(frame, FEATURE_NAMES, windows)

    # target_volatility_next_day at each surviving row must equal
    # (high[i+1]-low[i+1])/close[i+1] for that row's original next index -
    # computed independently here from raw high/low/close, not by reading
    # engineered["high_low_range_pct"] back, as a real cross-check.
    def next_day_range(original_index: int) -> float:
        next_index = original_index + 1
        return (highs[next_index] - lows[next_index]) / closes[next_index]

    original_indices = [1, 2, 3]  # index 0 dropped (feature NaN), index 4 dropped (target NaN)
    expected = [next_day_range(index) for index in original_indices]
    assert engineered["target_volatility_next_day"].tolist() == expected
    assert engineered["target_volatility_next_day"].isna().sum() == 0


def test_engineer_features_target_volatility_next_day_never_introduces_extra_dropped_rows():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=4, freq="D"),
            "open": [10.0, 11.0, 12.0, 13.0],
            "high": [11.0, 12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0, 12.0],
            "close": [10.0, 12.0, 11.0, 13.0],
            "volume": [100.0, 120.0, 90.0, 150.0],
        }
    )
    windows = {
        "training": {"start": "2020-01-01", "end": "2020-01-04"},
        "validation": {"start": "2020-02-01", "end": "2020-02-28"},
        "backtest": {"start": "2020-03-01", "end": "2020-03-31"},
    }

    engineered = engineer_features(frame, FEATURE_NAMES, windows)

    # Same row count as before this column existed (see
    # test_train_pipeline.py::test_engineer_features_uses_adaptive_lookbacks_for_short_series) -
    # target_volatility_next_day is NaN only where target_return_1d already
    # was (both are shift(-1) of price-derived data on the same last row).
    assert len(engineered) == 2


# ---------------------------------------------------------------------------
# AetherNetMultiTask
# ---------------------------------------------------------------------------


def test_aether_net_multitask_forward_shapes():
    model = AetherNetMultiTask(input_dim=3, hidden_layers=[8, 4], dropout=0.0, activation="relu", normalization="layernorm")
    model.eval()

    with torch.no_grad():
        direction_logits, magnitude, volatility = model(torch.randn((5, 3), dtype=torch.float32))

    assert direction_logits.shape == (5,)
    assert magnitude.shape == (5,)
    assert volatility.shape == (5,)


def test_aether_net_multitask_volatility_head_is_always_nonnegative():
    model = AetherNetMultiTask(input_dim=2, hidden_layers=[4], dropout=0.0, activation="relu", normalization="none")
    model.eval()

    with torch.no_grad():
        # Large-magnitude inputs to push the volatility head's pre-activation
        # well negative in at least some rows - softplus must still clamp to >= 0.
        _, _, volatility = model(torch.tensor([[100.0, -100.0], [-100.0, 100.0], [0.0, 0.0]], dtype=torch.float32))

    assert torch.all(volatility >= 0.0)


# ---------------------------------------------------------------------------
# export_multitask_architecture
# ---------------------------------------------------------------------------


def test_export_multitask_architecture_shape():
    model = AetherNetMultiTask(input_dim=3, hidden_layers=[4], dropout=0.1, activation="relu", normalization="layernorm")

    export = export_multitask_architecture(model)

    assert set(export.keys()) == {"trunk", "heads"}
    assert set(export["heads"].keys()) == {"direction", "magnitude", "volatility"}
    trunk_types = [layer["type"] for layer in export["trunk"]]
    assert trunk_types == ["linear", "layernorm", "relu", "dropout"]
    assert [layer["type"] for layer in export["heads"]["direction"]] == ["linear", "sigmoid"]
    assert [layer["type"] for layer in export["heads"]["magnitude"]] == ["linear"]
    assert [layer["type"] for layer in export["heads"]["volatility"]] == ["linear", "softplus"]


def test_export_multitask_architecture_weight_keys_are_disjoint_per_head():
    model = AetherNetMultiTask(input_dim=2, hidden_layers=[3], dropout=0.0, activation="relu", normalization="none")

    export = export_multitask_architecture(model)

    weight_keys = [export["trunk"][0]["weight_key"]]
    for head_layers in export["heads"].values():
        weight_keys.append(head_layers[0]["weight_key"])
    assert len(weight_keys) == len(set(weight_keys))
    assert weight_keys == ["trunk.0.weight", "head_direction.weight", "head_magnitude.weight", "head_volatility.weight"]


# ---------------------------------------------------------------------------
# compute_regression_metrics
# ---------------------------------------------------------------------------


def test_compute_regression_metrics_matches_hand_computed_values():
    predictions = torch.tensor([1.0, 2.0, 3.0])
    targets = torch.tensor([1.5, 2.0, 2.5])

    metrics = compute_regression_metrics(predictions, targets)

    errors = np.array([1.0 - 1.5, 2.0 - 2.0, 3.0 - 2.5])
    assert metrics["mae"] == pytest.approx(np.abs(errors).mean(), abs=1e-6)
    assert metrics["rmse"] == pytest.approx(np.sqrt((errors ** 2).mean()), abs=1e-6)
    assert metrics["bias"] == pytest.approx(errors.mean(), abs=1e-6)


def test_compute_regression_metrics_zero_error_when_predictions_match_targets():
    predictions = torch.tensor([0.1, -0.2, 0.3])
    targets = torch.tensor([0.1, -0.2, 0.3])

    metrics = compute_regression_metrics(predictions, targets)

    assert metrics["mae"] == 0.0
    assert metrics["rmse"] == 0.0
    assert metrics["bias"] == 0.0
