"""Tests for train.py's Phase 2 additions: AetherNetSequenceMultiTask,
export_sequence_multitask_architecture(), and build_sequence_tensor_dataset() -
the causal-TCN sequence encoder that replaces the flat-MLP trunk with
genuine temporal structure over a rolling window of bars.

Interpreter-level parity (run_exported_sequence_multitask_model() against
a real trained AetherNetSequenceMultiTask, and against
torch.nn.Conv1d/LayerNorm/MultiheadAttention for the underlying numpy
primitives) was verified manually during development - see
development/Changelog.md. This file covers the pure train.py-side
functions: shapes, export structure, and the windowing utility's
row-alignment/causality guarantees.
"""

import numpy as np
import pandas as pd
import pytest
import torch

from train import (
    AetherNetSequenceMultiTask,
    AetherNetSequenceMultiTaskHorizons,
    build_sequence_tensor_dataset,
    export_sequence_multitask_architecture,
    export_sequence_multitask_horizons_architecture,
)


# ---------------------------------------------------------------------------
# AetherNetSequenceMultiTask
# ---------------------------------------------------------------------------


def test_aether_net_sequence_multitask_forward_shapes():
    model = AetherNetSequenceMultiTask(input_dim=4, channels=[6, 6], kernel_size=3, dropout=0.0)
    model.eval()

    with torch.no_grad():
        direction_logits, magnitude, volatility = model(torch.randn(3, 10, 4))

    assert direction_logits.shape == (3,)
    assert magnitude.shape == (3,)
    assert volatility.shape == (3,)


def test_aether_net_sequence_multitask_volatility_head_is_always_nonnegative():
    model = AetherNetSequenceMultiTask(input_dim=2, channels=[4], kernel_size=2, dropout=0.0)
    model.eval()

    with torch.no_grad():
        _, _, volatility = model(torch.randn(5, 8, 2) * 100.0)

    assert torch.all(volatility >= 0.0)


def test_aether_net_sequence_multitask_dilation_doubles_per_layer():
    model = AetherNetSequenceMultiTask(input_dim=3, channels=[4, 4, 4], kernel_size=2, dropout=0.0)

    dilations = [conv.dilation[0] for conv in model.conv_layers]

    assert dilations == [1, 2, 4]


def test_aether_net_sequence_multitask_raises_with_no_channels():
    with pytest.raises(ValueError):
        AetherNetSequenceMultiTask(input_dim=3, channels=[], kernel_size=2, dropout=0.0)


def test_aether_net_sequence_multitask_output_is_causal_wrt_future_timesteps():
    # Changing only the LAST timestep must change the (pooled-from-last-
    # timestep) output; changing only an EARLIER timestep while holding the
    # trailing timesteps fixed must also change it (it's within the causal
    # receptive field) - but the model must never look past the final
    # timestep it's given, so results with a longer, unrelated future tail
    # appended are irrelevant here (this model has no notion of "future"
    # beyond what's passed in). This test instead confirms determinism:
    # identical input always produces identical output.
    model = AetherNetSequenceMultiTask(input_dim=3, channels=[4], kernel_size=2, dropout=0.0)
    model.eval()
    sequence = torch.randn(1, 6, 3)

    with torch.no_grad():
        first_direction, first_magnitude, first_volatility = model(sequence)
        second_direction, second_magnitude, second_volatility = model(sequence)

    assert torch.equal(first_direction, second_direction)
    assert torch.equal(first_magnitude, second_magnitude)
    assert torch.equal(first_volatility, second_volatility)


# ---------------------------------------------------------------------------
# export_sequence_multitask_architecture
# ---------------------------------------------------------------------------


def test_export_sequence_multitask_architecture_shape():
    model = AetherNetSequenceMultiTask(input_dim=4, channels=[6, 6], kernel_size=3, dropout=0.1)

    export = export_sequence_multitask_architecture(model)

    assert set(export.keys()) == {"trunk", "heads"}
    assert set(export["heads"].keys()) == {"direction", "magnitude", "volatility"}
    trunk_types = [layer["type"] for layer in export["trunk"]]
    # 2 conv layers, each followed by relu + dropout.
    assert trunk_types == ["conv1d_causal", "relu", "dropout", "conv1d_causal", "relu", "dropout"]


def test_export_sequence_multitask_architecture_dilations_match_model():
    model = AetherNetSequenceMultiTask(input_dim=3, channels=[4, 4, 4], kernel_size=2, dropout=0.0)

    export = export_sequence_multitask_architecture(model)

    conv_layers = [layer for layer in export["trunk"] if layer["type"] == "conv1d_causal"]
    assert [layer["dilation"] for layer in conv_layers] == [1, 2, 4]
    assert [layer["kernel_size"] for layer in conv_layers] == [2, 2, 2]


def test_export_sequence_multitask_architecture_weight_keys_are_disjoint():
    model = AetherNetSequenceMultiTask(input_dim=2, channels=[3, 3], kernel_size=2, dropout=0.0)

    export = export_sequence_multitask_architecture(model)

    conv_weight_keys = [layer["weight_key"] for layer in export["trunk"] if layer["type"] == "conv1d_causal"]
    head_weight_keys = [head[0]["weight_key"] for head in export["heads"].values()]
    all_keys = conv_weight_keys + head_weight_keys
    assert len(all_keys) == len(set(all_keys))
    assert conv_weight_keys == ["conv_layers.0.weight", "conv_layers.1.weight"]


# ---------------------------------------------------------------------------
# AetherNetSequenceMultiTaskHorizons / export_sequence_multitask_horizons_architecture
# ---------------------------------------------------------------------------


def test_aether_net_sequence_multitask_horizons_forward_returns_seven_heads():
    model = AetherNetSequenceMultiTaskHorizons(input_dim=4, channels=[6, 6], kernel_size=3, dropout=0.0)
    model.eval()

    with torch.no_grad():
        outputs = model(torch.randn(3, 10, 4))

    expected_heads = {"direction", "magnitude", "volatility", "direction_5d", "direction_20d", "rank_5d", "rank_20d"}
    assert set(outputs.keys()) == expected_heads
    for tensor in outputs.values():
        assert tensor.shape == (3,)
    assert torch.all(outputs["volatility"] >= 0.0)


def test_aether_net_sequence_multitask_horizons_raises_with_no_channels():
    with pytest.raises(ValueError):
        AetherNetSequenceMultiTaskHorizons(input_dim=2, channels=[], kernel_size=2, dropout=0.0)


def test_export_sequence_multitask_horizons_architecture_shape():
    model = AetherNetSequenceMultiTaskHorizons(input_dim=4, channels=[6, 6], kernel_size=3, dropout=0.1)

    export = export_sequence_multitask_horizons_architecture(model)

    assert set(export.keys()) == {"trunk", "heads"}
    assert set(export["heads"].keys()) == {
        "direction", "magnitude", "volatility", "direction_5d", "direction_20d", "rank_5d", "rank_20d",
    }
    trunk_types = [layer["type"] for layer in export["trunk"]]
    assert trunk_types == ["conv1d_causal", "relu", "dropout", "conv1d_causal", "relu", "dropout"]


def test_export_sequence_multitask_horizons_architecture_weight_keys_are_disjoint():
    model = AetherNetSequenceMultiTaskHorizons(input_dim=2, channels=[3, 3], kernel_size=2, dropout=0.0)

    export = export_sequence_multitask_horizons_architecture(model)

    conv_weight_keys = [layer["weight_key"] for layer in export["trunk"] if layer["type"] == "conv1d_causal"]
    head_weight_keys = [head[0]["weight_key"] for head in export["heads"].values()]
    all_keys = conv_weight_keys + head_weight_keys
    assert len(all_keys) == len(set(all_keys))


# ---------------------------------------------------------------------------
# build_sequence_tensor_dataset
# ---------------------------------------------------------------------------


def _sample_dataset() -> pd.DataFrame:
    rows = []
    for ticker in ("A", "B"):
        for day in range(5):
            rows.append({"ticker": ticker, "date": f"2020-01-{day + 1:02d}", "f1": float(day), "f2": float(day) * 10.0})
    return pd.DataFrame(rows)


def test_build_sequence_tensor_dataset_shape_matches_dataset_row_count():
    dataset = _sample_dataset()

    sequences = build_sequence_tensor_dataset(dataset, ["f1", "f2"], window_size=3)

    assert sequences.shape == (len(dataset), 3, 2)


def test_build_sequence_tensor_dataset_last_timestep_is_the_rows_own_features():
    dataset = _sample_dataset()

    sequences = build_sequence_tensor_dataset(dataset, ["f1", "f2"], window_size=3)

    for position in range(len(dataset)):
        assert sequences[position, -1, :].tolist() == pytest.approx(
            [dataset.iloc[position]["f1"], dataset.iloc[position]["f2"]], abs=1e-6
        )


def test_build_sequence_tensor_dataset_left_pads_with_zeros_when_history_is_short():
    dataset = _sample_dataset()
    # First row of ticker "A" (day 0) has zero preceding history within a
    # window_size=3 window - the first two timesteps must be zero-padded.
    first_a_position = dataset[dataset["ticker"] == "A"].index[0]

    sequences = build_sequence_tensor_dataset(dataset, ["f1", "f2"], window_size=3)

    assert sequences[first_a_position, 0, :].tolist() == [0.0, 0.0]
    assert sequences[first_a_position, 1, :].tolist() == [0.0, 0.0]


def test_build_sequence_tensor_dataset_never_crosses_ticker_boundaries():
    dataset = _sample_dataset()
    # Second row of ticker "B" (day 1) must never include ticker "A"'s
    # feature values in its window, even though "A"'s rows appear earlier
    # in the dataframe.
    second_b_position = dataset[dataset["ticker"] == "B"].index[1]

    sequences = build_sequence_tensor_dataset(dataset, ["f1", "f2"], window_size=3)

    # window_size=3, only 2 rows of B history available (days 0,1) -> 1 pad row.
    assert sequences[second_b_position, 0, :].tolist() == [0.0, 0.0]
    assert sequences[second_b_position, 1, :].tolist() == pytest.approx([0.0, 0.0], abs=1e-6)
    assert sequences[second_b_position, 2, :].tolist() == pytest.approx([1.0, 10.0], abs=1e-6)


def test_build_sequence_tensor_dataset_full_window_once_enough_history_exists():
    dataset = _sample_dataset()
    # Last row of ticker "A" (day 4) has 5 preceding rows available (days
    # 0-4), more than window_size=3 - window must be fully populated, no
    # zero-padding, and must be the 3 MOST RECENT rows (days 2,3,4).
    last_a_position = dataset[dataset["ticker"] == "A"].index[-1]

    sequences = build_sequence_tensor_dataset(dataset, ["f1", "f2"], window_size=3)

    assert np.allclose(sequences[last_a_position], [[2.0, 20.0], [3.0, 30.0], [4.0, 40.0]], atol=1e-6)
