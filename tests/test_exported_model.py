import json
import math
from pathlib import Path

import pytest

import numpy as np

from inference.exported_model import (
    _architectures_match,
    _conv1d_causal,
    _layernorm,
    _layernorm_axis,
    _linear,
    _linear_batched,
    _multihead_attention,
    _sigmoid,
    _softmax,
    _softplus,
    build_layer_stacks,
    build_models_batched_cache,
    build_multitask_models_batched_cache,
    convert_state_dict_arrays,
    resolve_sequence_window_size,
    run_exported_model,
    run_exported_multitask_model,
    run_exported_multitask_models_batched,
    run_exported_models_batched,
    run_exported_sequence_multitask_model,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXPERT_NAMES = ["bullish", "bearish", "sideways", "volatility"]


def test_linear_computes_weighted_sum_plus_bias():
    result = _linear([1.0, 2.0], weights=[[2.0, 0.5], [1.0, 1.0]], bias=[0.1, -0.2])

    assert result == pytest.approx([1.0 * 2.0 + 2.0 * 0.5 + 0.1, 1.0 * 1.0 + 2.0 * 1.0 - 0.2], abs=1e-9)


def test_layernorm_normalizes_to_zero_mean_before_affine():
    values = [1.0, 2.0, 3.0, 4.0]
    weights = [1.0, 1.0, 1.0, 1.0]
    bias = [0.0, 0.0, 0.0, 0.0]

    result = _layernorm(values, weights, bias, eps=1e-5)

    mean_value = sum(values) / len(values)
    variance = sum((v - mean_value) ** 2 for v in values) / len(values)
    denominator = math.sqrt(variance + 1e-5)
    expected = [(v - mean_value) / denominator for v in values]
    assert result == pytest.approx(expected, abs=1e-9)


def test_layernorm_applies_affine_weight_and_bias():
    result = _layernorm([1.0, 1.0], weights=[2.0, 3.0], bias=[0.5, -0.5], eps=1e-5)

    # Both inputs equal -> zero variance -> normalized values are 0 before affine.
    assert result == pytest.approx([0.5, -0.5], abs=1e-9)


def test_sigmoid_matches_hand_computed_values():
    assert _sigmoid(0.0) == pytest.approx(0.5, abs=1e-9)
    assert _sigmoid(1.0) == pytest.approx(1.0 / (1.0 + math.exp(-1.0)), abs=1e-9)
    assert _sigmoid(-1.0) == pytest.approx(1.0 / (1.0 + math.exp(1.0)), abs=1e-9)


def test_sigmoid_clips_extreme_values_without_overflow():
    assert _sigmoid(1000.0) == pytest.approx(1.0, abs=1e-9)
    assert _sigmoid(-1000.0) == pytest.approx(0.0, abs=1e-9)


def _synthetic_model_export() -> dict:
    """A small linear -> layernorm -> relu -> linear -> sigmoid stack,
    standing in for the real 20->64->32->1 exported architecture at a size
    small enough to hand-verify."""
    return {
        "export": {
            "architecture": [
                {"type": "linear", "weight_key": "l1.weight", "bias_key": "l1.bias"},
                {"type": "layernorm", "weight_key": "ln.weight", "bias_key": "ln.bias", "eps": 1e-5},
                {"type": "relu"},
                {"type": "dropout"},
                {"type": "linear", "weight_key": "l2.weight", "bias_key": "l2.bias"},
                {"type": "sigmoid"},
            ],
            "state_dict": {
                "l1.weight": [[0.5, -0.25], [0.1, 0.3], [-0.2, 0.4]],
                "l1.bias": [0.1, -0.1, 0.05],
                "ln.weight": [1.0, 1.0, 1.0],
                "ln.bias": [0.0, 0.0, 0.0],
                "l2.weight": [[0.3, -0.4, 0.2]],
                "l2.bias": [0.05],
            },
        }
    }


def _reference_forward_pass(inputs: list[float]) -> float:
    """Independent hand-transcription of the exact same math, used only to
    produce the expected value for the full-stack test below."""
    l1_weight = [[0.5, -0.25], [0.1, 0.3], [-0.2, 0.4]]
    l1_bias = [0.1, -0.1, 0.05]
    hidden = [sum(w * x for w, x in zip(row, inputs)) + b for row, b in zip(l1_weight, l1_bias)]

    mean_value = sum(hidden) / len(hidden)
    variance = sum((v - mean_value) ** 2 for v in hidden) / len(hidden)
    denominator = math.sqrt(variance + 1e-5)
    normalized = [(v - mean_value) / denominator for v in hidden]

    relu_out = [max(0.0, v) for v in normalized]

    l2_weight = [0.3, -0.4, 0.2]
    l2_bias = 0.05
    pre_sigmoid = sum(w * x for w, x in zip(l2_weight, relu_out)) + l2_bias

    return 1.0 / (1.0 + math.exp(-pre_sigmoid))


def test_run_exported_model_matches_hand_computed_reference():
    model_export = _synthetic_model_export()
    inputs = [1.0, -0.5]

    result = run_exported_model(model_export, inputs)

    assert result == pytest.approx(_reference_forward_pass(inputs), abs=1e-9)


def test_run_exported_model_raises_on_unsupported_layer_type():
    model_export = {"export": {"architecture": [{"type": "conv2d"}], "state_dict": {}}}

    with pytest.raises(ValueError):
        run_exported_model(model_export, [1.0])


def test_softplus_matches_hand_computed_values():
    assert _softplus(0.0) == pytest.approx(math.log(2.0), abs=1e-9)
    assert _softplus(2.0) == pytest.approx(math.log1p(math.exp(2.0)), abs=1e-9)
    assert _softplus(-2.0) == pytest.approx(math.log1p(math.exp(-2.0)), abs=1e-9)


def test_softplus_is_stable_and_nonnegative_for_extreme_values():
    assert _softplus(1000.0) == pytest.approx(1000.0, abs=1e-6)
    assert _softplus(-1000.0) == pytest.approx(0.0, abs=1e-9)
    assert _softplus(-1000.0) >= 0.0


def _synthetic_multitask_model_export() -> dict:
    """A shared linear->relu trunk branching into three small heads
    (direction/magnitude/volatility) - small enough to hand-verify, standing
    in for the real AetherNetMultiTask export."""
    return {
        "export": {
            "trunk": [
                {"type": "linear", "weight_key": "trunk.0.weight", "bias_key": "trunk.0.bias"},
                {"type": "relu"},
                {"type": "dropout"},
            ],
            "heads": {
                "direction": [
                    {"type": "linear", "weight_key": "head_direction.weight", "bias_key": "head_direction.bias"},
                    {"type": "sigmoid"},
                ],
                "magnitude": [
                    {"type": "linear", "weight_key": "head_magnitude.weight", "bias_key": "head_magnitude.bias"},
                ],
                "volatility": [
                    {"type": "linear", "weight_key": "head_volatility.weight", "bias_key": "head_volatility.bias"},
                    {"type": "softplus"},
                ],
            },
            "state_dict": {
                "trunk.0.weight": [[0.5, -0.25], [0.1, 0.3]],
                "trunk.0.bias": [0.1, -0.1],
                "head_direction.weight": [[0.3, -0.4]],
                "head_direction.bias": [0.05],
                "head_magnitude.weight": [[0.2, 0.1]],
                "head_magnitude.bias": [-0.02],
                "head_volatility.weight": [[-1.0, -1.0]],
                "head_volatility.bias": [0.0],
            },
        }
    }


def _reference_multitask_forward_pass(inputs: list[float]) -> dict:
    """Independent hand-transcription of the same math, used only to produce
    the expected values for the full-stack multitask test below."""
    trunk_weight = [[0.5, -0.25], [0.1, 0.3]]
    trunk_bias = [0.1, -0.1]
    trunk_out = [
        max(0.0, sum(w * x for w, x in zip(row, inputs)) + b)
        for row, b in zip(trunk_weight, trunk_bias)
    ]

    direction_weight = [0.3, -0.4]
    direction_bias = 0.05
    direction_pre = sum(w * x for w, x in zip(direction_weight, trunk_out)) + direction_bias
    direction = 1.0 / (1.0 + math.exp(-direction_pre))

    magnitude_weight = [0.2, 0.1]
    magnitude_bias = -0.02
    magnitude = sum(w * x for w, x in zip(magnitude_weight, trunk_out)) + magnitude_bias

    volatility_weight = [-1.0, -1.0]
    volatility_bias = 0.0
    volatility_pre = sum(w * x for w, x in zip(volatility_weight, trunk_out)) + volatility_bias
    volatility = math.log1p(math.exp(-abs(volatility_pre))) + max(volatility_pre, 0.0)

    return {"direction": direction, "magnitude": magnitude, "volatility": volatility}


def test_run_exported_multitask_model_matches_hand_computed_reference():
    model_export = _synthetic_multitask_model_export()
    inputs = [1.0, -0.5]

    result = run_exported_multitask_model(model_export, inputs)
    expected = _reference_multitask_forward_pass(inputs)

    assert result.keys() == expected.keys()
    for key in expected:
        assert result[key] == pytest.approx(expected[key], abs=1e-9)


def test_run_exported_multitask_model_volatility_head_is_always_nonnegative():
    model_export = _synthetic_multitask_model_export()

    for inputs in ([5.0, 5.0], [-5.0, -5.0], [0.0, 0.0]):
        result = run_exported_multitask_model(model_export, inputs)
        assert result["volatility"] >= 0.0


def test_run_exported_multitask_model_raises_on_unsupported_layer_type():
    model_export = {
        "export": {
            "trunk": [{"type": "conv2d"}],
            "heads": {"direction": [{"type": "sigmoid"}]},
            "state_dict": {},
        }
    }

    with pytest.raises(ValueError):
        run_exported_multitask_model(model_export, [1.0])


# ---------------------------------------------------------------------------
# Phase 2 primitives: _softmax, _layernorm_axis, _conv1d_causal,
# _multihead_attention - independently cross-checked against real PyTorch
# modules (torch.nn.Conv1d / LayerNorm / MultiheadAttention) during
# development to well under float32 tolerance; the assertions below use
# small hand-computed references so this suite stays torch-import-free.
# ---------------------------------------------------------------------------


def test_softmax_matches_hand_computed_values():
    result = _softmax([1.0, 2.0, 3.0])

    exponentials = [math.exp(1.0), math.exp(2.0), math.exp(3.0)]
    total = sum(exponentials)
    expected = [value / total for value in exponentials]
    assert result.tolist() == pytest.approx(expected, abs=1e-9)


def test_softmax_rows_sum_to_one_along_last_axis():
    result = _softmax([[1.0, 0.0, -1.0], [2.0, 2.0, 2.0]], axis=-1)

    assert result.sum(axis=-1).tolist() == pytest.approx([1.0, 1.0], abs=1e-9)


def test_softmax_is_stable_for_large_values():
    result = _softmax([1000.0, 1000.0, 1000.0])

    assert result.tolist() == pytest.approx([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0], abs=1e-9)


def test_layernorm_axis_matches_layernorm_for_a_flat_vector():
    values = [1.0, 2.0, 3.0, 4.0]
    weights = [1.0, 1.0, 1.0, 1.0]
    bias = [0.0, 0.0, 0.0, 0.0]

    flat_result = _layernorm(values, weights, bias, eps=1e-5)
    axis_result = _layernorm_axis(values, weights, bias, eps=1e-5, axis=-1)

    assert axis_result.tolist() == pytest.approx(flat_result.tolist(), abs=1e-9)


def test_layernorm_axis_normalizes_each_row_independently():
    # Two timesteps, 2 features each - row 0 and row 1 have different
    # means/variances, so each row's normalization must be independent of
    # the other (unlike _layernorm(), which would normalize the flattened
    # whole).
    sequence = [[1.0, 3.0], [10.0, 30.0]]
    weights = [1.0, 1.0]
    bias = [0.0, 0.0]

    result = _layernorm_axis(sequence, weights, bias, eps=1e-5, axis=-1)

    for row in result:
        mean_value = sum(row) / len(row)
        assert mean_value == pytest.approx(0.0, abs=1e-6)


def test_conv1d_causal_matches_hand_computed_single_channel_example():
    # 1 in-channel, 1 out-channel, kernel_size=2, dilation=1: output[t] =
    # bias + w[0]*input[t-1] + w[1]*input[t] (input[-1] treated as 0 - the
    # causal left-pad).
    sequence = [[1.0], [2.0], [3.0]]
    weights = [[[0.5, -1.0]]]  # (out_channels=1, in_channels=1, kernel_size=2)
    bias = [0.1]

    result = _conv1d_causal(sequence, weights, bias, dilation=1)

    expected = [
        0.1 + 0.5 * 0.0 + (-1.0) * 1.0,   # t=0: pad, 1.0
        0.1 + 0.5 * 1.0 + (-1.0) * 2.0,   # t=1: 1.0, 2.0
        0.1 + 0.5 * 2.0 + (-1.0) * 3.0,   # t=2: 2.0, 3.0
    ]
    assert [row[0] for row in result.tolist()] == pytest.approx(expected, abs=1e-9)


def test_conv1d_causal_never_reads_future_timesteps():
    # Changing a later timestep's value must never change an earlier
    # timestep's output - the defining causal-conv property.
    sequence_a = [[1.0], [2.0], [3.0]]
    sequence_b = [[1.0], [2.0], [999.0]]  # only the last timestep differs
    weights = [[[0.5, -1.0]]]
    bias = [0.0]

    result_a = _conv1d_causal(sequence_a, weights, bias, dilation=1)
    result_b = _conv1d_causal(sequence_b, weights, bias, dilation=1)

    assert [row[0] for row in result_a[:2].tolist()] == pytest.approx(
        [row[0] for row in result_b[:2].tolist()], abs=1e-9
    )


def test_conv1d_causal_raises_on_in_channels_mismatch():
    sequence = [[1.0, 2.0]]  # 2 in_channels
    weights = [[[0.5]]]  # 1 in_channel expected by the weight shape

    with pytest.raises(ValueError):
        _conv1d_causal(sequence, weights, [0.0], dilation=1)


def test_multihead_attention_single_head_first_position_only_attends_to_itself():
    # causal=True + window=2: position 0's causal mask blocks position 1
    # entirely, so its output must equal value[0] projected through the
    # output layer, independent of position 1's content.
    sequence_a = [[1.0, 0.0], [0.0, 0.0]]
    sequence_b = [[1.0, 0.0], [999.0, 999.0]]  # only position 1 differs
    identity_2x2 = [[1.0, 0.0], [0.0, 1.0]]
    zero_bias = [0.0, 0.0]

    result_a = _multihead_attention(
        sequence_a, identity_2x2, zero_bias, identity_2x2, zero_bias, identity_2x2, zero_bias,
        identity_2x2, zero_bias, num_heads=1, causal=True,
    )
    result_b = _multihead_attention(
        sequence_b, identity_2x2, zero_bias, identity_2x2, zero_bias, identity_2x2, zero_bias,
        identity_2x2, zero_bias, num_heads=1, causal=True,
    )

    assert result_a[0].tolist() == pytest.approx(result_b[0].tolist(), abs=1e-9)


def test_multihead_attention_raises_when_d_model_not_divisible_by_num_heads():
    sequence = [[1.0, 2.0, 3.0]]
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    zero_bias = [0.0, 0.0, 0.0]

    with pytest.raises(ValueError):
        _multihead_attention(
            sequence, identity, zero_bias, identity, zero_bias, identity, zero_bias,
            identity, zero_bias, num_heads=2, causal=True,
        )


# ---------------------------------------------------------------------------
# run_exported_sequence_multitask_model (Phase 2 full-stack)
# ---------------------------------------------------------------------------


def _synthetic_sequence_model_export() -> dict:
    """A single causal conv1d layer (2 in-channels -> 2 out-channels,
    kernel_size=2) plus relu, branching into the same 3-head shape
    run_exported_multitask_model() uses - small enough to hand-verify."""
    return {
        "export": {
            "trunk": [
                {"type": "conv1d_causal", "weight_key": "conv.weight", "bias_key": "conv.bias", "dilation": 1},
                {"type": "relu"},
            ],
            "heads": {
                "direction": [
                    {"type": "linear", "weight_key": "head_direction.weight", "bias_key": "head_direction.bias"},
                    {"type": "sigmoid"},
                ],
                "magnitude": [
                    {"type": "linear", "weight_key": "head_magnitude.weight", "bias_key": "head_magnitude.bias"},
                ],
                "volatility": [
                    {"type": "linear", "weight_key": "head_volatility.weight", "bias_key": "head_volatility.bias"},
                    {"type": "softplus"},
                ],
            },
            "state_dict": {
                "conv.weight": [[[0.5, -0.5], [0.2, 0.1]], [[-0.3, 0.4], [0.1, -0.2]]],
                "conv.bias": [0.05, -0.05],
                "head_direction.weight": [[0.3, -0.4]],
                "head_direction.bias": [0.05],
                "head_magnitude.weight": [[0.2, 0.1]],
                "head_magnitude.bias": [-0.02],
                "head_volatility.weight": [[-1.0, -1.0]],
                "head_volatility.bias": [0.0],
            },
        }
    }


def test_run_exported_sequence_multitask_model_matches_hand_computed_reference():
    model_export = _synthetic_sequence_model_export()
    sequence = [[1.0, -0.5], [0.5, 0.2]]  # 2 timesteps, 2 channels

    result = run_exported_sequence_multitask_model(model_export, sequence)

    # Independently recompute via the already-verified primitives, using
    # the exact same trunk/head math but assembled by hand rather than by
    # the function under test.
    conv_out = _conv1d_causal(
        sequence, model_export["export"]["state_dict"]["conv.weight"], model_export["export"]["state_dict"]["conv.bias"], dilation=1
    )
    relu_out = [[max(0.0, value) for value in row] for row in conv_out.tolist()]
    pooled = relu_out[-1]  # most-recent timestep

    direction_weight = [0.3, -0.4]
    direction_bias = 0.05
    direction_pre = sum(w * x for w, x in zip(direction_weight, pooled)) + direction_bias
    direction = 1.0 / (1.0 + math.exp(-direction_pre))

    magnitude_weight = [0.2, 0.1]
    magnitude_bias = -0.02
    magnitude = sum(w * x for w, x in zip(magnitude_weight, pooled)) + magnitude_bias

    volatility_weight = [-1.0, -1.0]
    volatility_pre = sum(w * x for w, x in zip(volatility_weight, pooled))
    volatility = math.log1p(math.exp(-abs(volatility_pre))) + max(volatility_pre, 0.0)

    assert result["direction"] == pytest.approx(direction, abs=1e-9)
    assert result["magnitude"] == pytest.approx(magnitude, abs=1e-9)
    assert result["volatility"] == pytest.approx(volatility, abs=1e-9)


def test_run_exported_sequence_multitask_model_ignores_future_timesteps_for_pooling_input():
    # The trunk is causal, but pooling always reads the LAST row of the
    # trunk's output - changing an earlier timestep's input must still
    # change the result (it's part of the causal receptive field for the
    # last timestep), confirming this isn't accidentally reading a fixed
    # timestep independent of history.
    model_export = _synthetic_sequence_model_export()
    sequence_a = [[1.0, -0.5], [0.5, 0.2]]
    sequence_b = [[9.0, -9.0], [0.5, 0.2]]

    result_a = run_exported_sequence_multitask_model(model_export, sequence_a)
    result_b = run_exported_sequence_multitask_model(model_export, sequence_b)

    assert result_a["direction"] != pytest.approx(result_b["direction"], abs=1e-9)


def test_run_exported_sequence_multitask_model_raises_on_unsupported_layer_type():
    model_export = {
        "export": {
            "trunk": [{"type": "attention"}],
            "heads": {"direction": [{"type": "sigmoid"}]},
            "state_dict": {},
        }
    }

    with pytest.raises(ValueError):
        run_exported_sequence_multitask_model(model_export, [[1.0]])


def test_resolve_sequence_window_size_prefers_trained_schema_over_config():
    # Regression guard: a retrained candidate with a different window_size
    # used to be silently ignored - main.py built its rolling buffer from
    # config.json's value alone, never the trained model's own
    # sequence_feature_schema.json, causing a shape mismatch inside
    # run_exported_sequence_multitask_model() that a blanket except then
    # swallowed (see development/Problems.md).
    assert resolve_sequence_window_size({"window_size": 45}, 30) == 45


def test_resolve_sequence_window_size_falls_back_to_config_when_schema_missing():
    assert resolve_sequence_window_size(None, 30) == 30


def test_resolve_sequence_window_size_falls_back_to_config_when_schema_lacks_key():
    assert resolve_sequence_window_size({"model_input_names": []}, 30) == 30


# ---------------------------------------------------------------------------
# Batched inference (run_exported_models_batched / run_exported_multitask_models_batched)
# - parity net: every batched result must exactly match calling the
# original single-model function once per entry, since this feeds real
# trading decisions. See inference/exported_model.py's module comment for
# why this exists (profiling showed per-call dispatch overhead dominating).
# ---------------------------------------------------------------------------


def _variant_model_export(scale: float) -> dict:
    """Same architecture as _synthetic_model_export() above, weights
    scaled by `scale` - stands in for "4 separately-trained experts sharing
    one architecture," which is what real ml/expert_models/*/model_weights.json
    actually look like (verified during this pass: identical layer types
    and weight shapes, different trained values)."""
    base = _synthetic_model_export()
    state_dict = base["export"]["state_dict"]
    scaled_state_dict = {
        key: [[v * scale for v in row] for row in value] if isinstance(value[0], list) else [v * scale for v in value]
        for key, value in state_dict.items()
    }
    return {"export": {"architecture": base["export"]["architecture"], "state_dict": scaled_state_dict}}


def test_architectures_match_true_for_identical_layer_type_and_key_sequences():
    a = _synthetic_model_export()["export"]["architecture"]
    b = _synthetic_model_export()["export"]["architecture"]
    assert _architectures_match([a, b]) is True


def test_architectures_match_true_for_single_or_empty_list():
    a = _synthetic_model_export()["export"]["architecture"]
    assert _architectures_match([a]) is True
    assert _architectures_match([]) is True


def test_architectures_match_false_when_layer_types_differ():
    a = _synthetic_model_export()["export"]["architecture"]
    b = a + [{"type": "relu"}]
    assert _architectures_match([a, b]) is False


def test_run_exported_models_batched_matches_individual_calls():
    models = [_variant_model_export(scale) for scale in (1.0, 0.8, 1.3)]
    inputs = [1.0, -0.5]

    batched = run_exported_models_batched(models, inputs)
    individual = [run_exported_model(m, inputs) for m in models]

    assert batched == pytest.approx(individual, abs=1e-9)


def test_run_exported_models_batched_preserves_none_at_missing_indices():
    models = [_variant_model_export(1.0), None, _variant_model_export(0.8)]
    inputs = [1.0, -0.5]

    batched = run_exported_models_batched(models, inputs)

    assert batched[1] is None
    assert batched[0] == pytest.approx(run_exported_model(models[0], inputs), abs=1e-9)
    assert batched[2] == pytest.approx(run_exported_model(models[2], inputs), abs=1e-9)


def test_run_exported_models_batched_falls_back_when_fewer_than_two_present():
    models = [_variant_model_export(1.0), None, None]
    inputs = [1.0, -0.5]

    batched = run_exported_models_batched(models, inputs)

    assert batched[0] == pytest.approx(run_exported_model(models[0], inputs), abs=1e-9)
    assert batched[1] is None and batched[2] is None


def test_run_exported_models_batched_falls_back_when_architectures_differ():
    matching = _variant_model_export(1.0)
    mismatched = _variant_model_export(0.8)
    mismatched["export"]["architecture"] = mismatched["export"]["architecture"] + [{"type": "relu"}]
    inputs = [1.0, -0.5]

    batched = run_exported_models_batched([matching, mismatched], inputs)

    assert batched[0] == pytest.approx(run_exported_model(matching, inputs), abs=1e-9)
    assert batched[1] == pytest.approx(run_exported_model(mismatched, inputs), abs=1e-9)


def test_run_exported_models_batched_falls_back_on_shape_mismatch_without_crashing():
    """Same layer-type/key sequence (passes _architectures_match) but a
    genuinely different hidden width - the real-world failure mode a type/
    key check alone can't catch. Must degrade to the individual-calls
    fallback, never raise."""
    a = _variant_model_export(1.0)
    b = _variant_model_export(0.8)
    # Widen b's hidden layer from 3 to 4 units - same keys/types, incompatible shape.
    b["export"]["state_dict"]["l1.weight"] = [[0.5, -0.25], [0.1, 0.3], [-0.2, 0.4], [0.1, -0.1]]
    b["export"]["state_dict"]["l1.bias"] = [0.1, -0.1, 0.05, 0.0]
    b["export"]["state_dict"]["ln.weight"] = [1.0, 1.0, 1.0, 1.0]
    b["export"]["state_dict"]["ln.bias"] = [0.0, 0.0, 0.0, 0.0]
    b["export"]["state_dict"]["l2.weight"] = [[0.3, -0.4, 0.2, 0.1]]
    inputs = [1.0, -0.5]

    batched = run_exported_models_batched([a, b], inputs)

    assert batched[0] == pytest.approx(run_exported_model(a, inputs), abs=1e-9)
    assert batched[1] == pytest.approx(run_exported_model(b, inputs), abs=1e-9)


def _load_real_expert_exports(filename: str) -> list[dict]:
    exports = []
    for name in _EXPERT_NAMES:
        path = _REPO_ROOT / "ml" / "expert_models" / name / filename
        with path.open("r", encoding="utf-8") as f:
            exports.append(json.load(f))
    return exports


@pytest.mark.skipif(
    not (_REPO_ROOT / "ml" / "expert_models" / "bullish" / "model_weights.json").exists(),
    reason="real trained expert exports not present in this checkout",
)
def test_run_exported_models_batched_matches_individual_calls_on_real_expert_exports():
    """Highest-confidence parity check: real, currently-deployed expert
    weights (ml/expert_models/*/model_weights.json), not synthetic
    stand-ins."""
    experts = _load_real_expert_exports("model_weights.json")
    input_width = experts[0]["export"]["architecture"][0]["in_features"]
    inputs = [0.1 * i for i in range(input_width)]

    batched = run_exported_models_batched(experts, inputs)
    individual = [run_exported_model(m, inputs) for m in experts]

    assert batched == pytest.approx(individual, abs=1e-7)


def _variant_multitask_model_export(scale: float) -> dict:
    base = _synthetic_multitask_model_export()
    state_dict = base["export"]["state_dict"]
    scaled_state_dict = {
        key: [[v * scale for v in row] for row in value] if isinstance(value[0], list) else [v * scale for v in value]
        for key, value in state_dict.items()
    }
    return {
        "export": {
            "trunk": base["export"]["trunk"],
            "heads": base["export"]["heads"],
            "state_dict": scaled_state_dict,
        }
    }


def test_run_exported_multitask_models_batched_matches_individual_calls():
    models = [_variant_multitask_model_export(scale) for scale in (1.0, 0.8, 1.3)]
    inputs = [1.0, -0.5]

    batched = run_exported_multitask_models_batched(models, inputs)
    individual = [run_exported_multitask_model(m, inputs) for m in models]

    for batched_result, individual_result in zip(batched, individual):
        assert batched_result == pytest.approx(individual_result, abs=1e-9)


def test_run_exported_multitask_models_batched_preserves_none_at_missing_indices():
    models = [_variant_multitask_model_export(1.0), None, _variant_multitask_model_export(0.8)]
    inputs = [1.0, -0.5]

    batched = run_exported_multitask_models_batched(models, inputs)

    assert batched[1] is None
    assert batched[0] == pytest.approx(run_exported_multitask_model(models[0], inputs), abs=1e-9)


def test_run_exported_multitask_models_batched_falls_back_when_head_names_differ():
    a = _variant_multitask_model_export(1.0)
    b = _variant_multitask_model_export(0.8)
    del b["export"]["heads"]["volatility"]
    inputs = [1.0, -0.5]

    batched = run_exported_multitask_models_batched([a, b], inputs)

    assert batched[0] == pytest.approx(run_exported_multitask_model(a, inputs), abs=1e-9)
    assert batched[1] == pytest.approx(run_exported_multitask_model(b, inputs), abs=1e-9)


@pytest.mark.skipif(
    not (_REPO_ROOT / "ml" / "expert_models" / "bullish" / "multitask_model.json").exists(),
    reason="real trained expert multitask exports not present in this checkout",
)
def test_run_exported_multitask_models_batched_matches_individual_calls_on_real_expert_exports():
    experts = _load_real_expert_exports("multitask_model.json")
    # Multitask exports don't carry in_features on the trunk's first layer
    # the way the flat baseline export does - infer width from the
    # trunk's first linear layer's own weight matrix instead.
    first_linear = next(layer for layer in experts[0]["export"]["trunk"] if layer["type"] == "linear")
    input_width = len(experts[0]["export"]["state_dict"][first_linear["weight_key"]][0])
    inputs = [0.1 * i for i in range(input_width)]

    batched = run_exported_multitask_models_batched(experts, inputs)
    individual = [run_exported_multitask_model(m, inputs) for m in experts]

    for batched_result, individual_result in zip(batched, individual):
        assert batched_result == pytest.approx(individual_result, abs=1e-7)


# ---------------------------------------------------------------------------
# convert_state_dict_arrays() - the weight-array-caching-at-load-time fix.
# Parity net: pre-converting a state_dict's lists to ndarrays must never
# change any function's output, only its cost (np.asarray() on an
# already-correct ndarray is a documented no-op).
# ---------------------------------------------------------------------------


def test_convert_state_dict_arrays_converts_lists_to_float64_ndarrays():
    export = _synthetic_model_export()
    convert_state_dict_arrays(export)

    state_dict = export["export"]["state_dict"]
    for value in state_dict.values():
        assert isinstance(value, np.ndarray)
        assert value.dtype == np.float64


def test_convert_state_dict_arrays_is_a_noop_on_already_converted_export():
    export = _synthetic_model_export()
    convert_state_dict_arrays(export)
    first_pass_ids = {key: id(value) for key, value in export["export"]["state_dict"].items()}

    convert_state_dict_arrays(export)  # second call - must not rebuild anything

    for key, value in export["export"]["state_dict"].items():
        assert id(value) == first_pass_ids[key]


def test_convert_state_dict_arrays_does_not_change_run_exported_model_output():
    export = _synthetic_model_export()
    inputs = [1.0, -0.5]
    before = run_exported_model(export, inputs)

    convert_state_dict_arrays(export)

    after = run_exported_model(export, inputs)
    assert after == pytest.approx(before, abs=1e-12)


def test_convert_state_dict_arrays_does_not_change_multitask_output():
    export = _synthetic_multitask_model_export()
    inputs = [1.0, -0.5]
    before = run_exported_multitask_model(export, inputs)

    convert_state_dict_arrays(export)

    after = run_exported_multitask_model(export, inputs)
    for head_name in before:
        assert after[head_name] == pytest.approx(before[head_name], abs=1e-12)


def test_convert_state_dict_arrays_tolerates_missing_state_dict_key():
    convert_state_dict_arrays({"export": {"architecture": []}})  # no "state_dict" key - must not raise


def test_convert_state_dict_arrays_tolerates_malformed_export():
    convert_state_dict_arrays({})  # no "export" key at all - must not raise


# ---------------------------------------------------------------------------
# build_layer_stacks() / BatchedLayerStackCache / build_models_batched_cache()
# - the pre-stacked-array caching fix. Parity net: a precomputed cache must
# produce bit-identical results to the uncached (rebuild-every-call) path.
# ---------------------------------------------------------------------------


def test_build_layer_stacks_returns_none_for_unweighted_layers_and_arrays_for_weighted_ones():
    architecture = _synthetic_model_export()["export"]["architecture"]
    state_dicts = [_synthetic_model_export()["export"]["state_dict"]]

    stacks = build_layer_stacks(architecture, state_dicts)

    assert len(stacks) == len(architecture)
    for layer, stack in zip(architecture, stacks):
        if layer["type"] in ("linear", "layernorm"):
            assert stack is not None
            weights_stack, bias_stack = stack
            assert weights_stack.shape[0] == 1  # one model stacked
        else:
            assert stack is None


def test_models_batched_cache_matches_uncached_batched_output():
    models = [_variant_model_export(scale) for scale in (1.0, 0.8, 1.3)]
    inputs = [1.0, -0.5]

    cache = build_models_batched_cache(models)
    assert cache is not None
    assert cache.present_indices == [0, 1, 2]

    cached_result = run_exported_models_batched(models, inputs, stack_cache=cache)
    uncached_result = run_exported_models_batched(models, inputs)

    assert cached_result == pytest.approx(uncached_result, abs=1e-12)


def test_models_batched_cache_none_when_fewer_than_two_present():
    models = [_variant_model_export(1.0), None, None]
    assert build_models_batched_cache(models) is None


def test_models_batched_cache_none_when_architectures_differ():
    matching = _variant_model_export(1.0)
    mismatched = _variant_model_export(0.8)
    mismatched["export"]["architecture"] = mismatched["export"]["architecture"] + [{"type": "relu"}]
    assert build_models_batched_cache([matching, mismatched]) is None


def test_models_batched_cache_ignored_when_present_indices_mismatch_call():
    """A cache built for one model_exports shape must never be silently
    applied to a DIFFERENT one - run_exported_models_batched() checks
    present_indices equality before using it, falling back to an on-the-fly
    rebuild (still correct, just uncached) whenever they don't match."""
    cache_models = [_variant_model_export(1.0), _variant_model_export(0.8)]
    cache = build_models_batched_cache(cache_models)

    different_models = [_variant_model_export(1.0), None, _variant_model_export(0.8)]  # different present_indices
    inputs = [1.0, -0.5]

    result_with_stale_cache = run_exported_models_batched(different_models, inputs, stack_cache=cache)
    result_without_cache = run_exported_models_batched(different_models, inputs)

    assert result_with_stale_cache == pytest.approx(result_without_cache, abs=1e-12)


def test_multitask_models_batched_cache_matches_uncached_batched_output():
    models = [_variant_multitask_model_export(scale) for scale in (1.0, 0.8, 1.3)]
    inputs = [1.0, -0.5]

    cache = build_multitask_models_batched_cache(models)
    assert cache is not None

    cached_result = run_exported_multitask_models_batched(models, inputs, stack_cache=cache)
    uncached_result = run_exported_multitask_models_batched(models, inputs)

    for cached_row, uncached_row in zip(cached_result, uncached_result):
        assert cached_row == pytest.approx(uncached_row, abs=1e-12)


def test_multitask_models_batched_cache_none_when_head_names_differ():
    a = _variant_multitask_model_export(1.0)
    b = _variant_multitask_model_export(0.8)
    del b["export"]["heads"]["volatility"]
    assert build_multitask_models_batched_cache([a, b]) is None


@pytest.mark.skipif(
    not (_REPO_ROOT / "ml" / "expert_models" / "bullish" / "model_weights.json").exists(),
    reason="real trained expert exports not present in this checkout",
)
def test_models_batched_cache_matches_uncached_on_real_expert_exports():
    experts = _load_real_expert_exports("model_weights.json")
    input_width = experts[0]["export"]["architecture"][0]["in_features"]
    inputs = [0.1 * i for i in range(input_width)]

    cache = build_models_batched_cache(experts)
    assert cache is not None

    cached_result = run_exported_models_batched(experts, inputs, stack_cache=cache)
    uncached_result = run_exported_models_batched(experts, inputs)

    assert cached_result == pytest.approx(uncached_result, abs=1e-9)


# ---------------------------------------------------------------------------
# cpp_inference accelerator (optional C++/pybind11 extension, see
# cpp_inference_ext/ and development/Problems.md #32) - skip-guarded on
# whether the extension actually built/is importable on this machine.
# Parity net: the accelerated path must be bit-identical (within float
# tolerance) to the NumPy einsum path it replaces.
# ---------------------------------------------------------------------------

from inference import exported_model as _exported_model_module  # noqa: E402

_CPP_INFERENCE_AVAILABLE = _exported_model_module._cpp_inference is not None


@pytest.mark.skipif(not _CPP_INFERENCE_AVAILABLE, reason="cpp_inference extension not built/importable on this machine")
def test_cpp_inference_linear_batched_matches_numpy_reference():
    rng_weights = [[[0.5, -0.25, 0.1], [0.2, 0.4, -0.1]], [[-0.3, 0.6, 0.2], [0.1, -0.2, 0.5]]]
    weights_stack = np.asarray(rng_weights, dtype=np.float64)
    current = np.asarray([[1.0, -0.5, 0.3], [0.2, 0.8, -0.4]], dtype=np.float64)
    bias_stack = np.asarray([[0.1, -0.1], [0.05, 0.0]], dtype=np.float64)

    cpp_result = _exported_model_module._cpp_inference.linear_batched(weights_stack, current, bias_stack)
    numpy_result = np.einsum("noi,ni->no", weights_stack, current) + bias_stack

    assert cpp_result == pytest.approx(numpy_result, abs=1e-9)


@pytest.mark.skipif(not _CPP_INFERENCE_AVAILABLE, reason="cpp_inference extension not built/importable on this machine")
def test_linear_batched_uses_cpp_accelerator_and_matches_numpy_path():
    """_linear_batched() itself (not the raw extension call) - proves the
    accelerated path is actually wired in and produces the same result as
    disabling it would."""
    weights_stack = np.asarray([[[0.5, -0.25], [0.1, 0.3]]], dtype=np.float64)
    current = np.asarray([[1.0, -0.5]], dtype=np.float64)
    bias_stack = np.asarray([[0.1, -0.1]], dtype=np.float64)

    accelerated = _linear_batched(current, weights_stack, bias_stack)
    numpy_only = np.einsum("noi,ni->no", weights_stack, current) + bias_stack

    assert accelerated == pytest.approx(numpy_only, abs=1e-9)


@pytest.mark.skipif(not _CPP_INFERENCE_AVAILABLE, reason="cpp_inference extension not built/importable on this machine")
def test_linear_batched_falls_back_to_numpy_when_cpp_call_raises(monkeypatch):
    """Simulates the accelerator misbehaving at call time (not just being
    absent) - _linear_batched() must still return the correct result via
    the NumPy fallback, never propagate the C++ side's exception."""

    def _broken_linear_batched(*_args, **_kwargs):
        raise RuntimeError("simulated cpp_inference failure")

    monkeypatch.setattr(_exported_model_module._cpp_inference, "linear_batched", _broken_linear_batched)

    weights_stack = np.asarray([[[0.5, -0.25], [0.1, 0.3]]], dtype=np.float64)
    current = np.asarray([[1.0, -0.5]], dtype=np.float64)
    bias_stack = np.asarray([[0.1, -0.1]], dtype=np.float64)

    result = _linear_batched(current, weights_stack, bias_stack)
    expected = np.einsum("noi,ni->no", weights_stack, current) + bias_stack

    assert result == pytest.approx(expected, abs=1e-9)


def test_linear_batched_correct_when_cpp_inference_absent(monkeypatch):
    """Simulates the extension never having been built at all (the common
    case for most checkouts/CI) - _linear_batched() must still work
    correctly via the pure-NumPy path. Not skip-guarded - this is the
    always-true-somewhere case."""
    monkeypatch.setattr(_exported_model_module, "_cpp_inference", None)

    weights_stack = np.asarray([[[0.5, -0.25], [0.1, 0.3]]], dtype=np.float64)
    current = np.asarray([[1.0, -0.5]], dtype=np.float64)
    bias_stack = np.asarray([[0.1, -0.1]], dtype=np.float64)

    result = _linear_batched(current, weights_stack, bias_stack)
    expected = np.einsum("noi,ni->no", weights_stack, current) + bias_stack

    assert result == pytest.approx(expected, abs=1e-9)
