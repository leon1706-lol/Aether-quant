import math

import pytest

from inference.exported_model import (
    _conv1d_causal,
    _layernorm,
    _layernorm_axis,
    _linear,
    _multihead_attention,
    _sigmoid,
    _softmax,
    _softplus,
    run_exported_model,
    run_exported_multitask_model,
    run_exported_sequence_multitask_model,
)


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
