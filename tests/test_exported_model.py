import math

import pytest

from inference.exported_model import (
    _layernorm,
    _linear,
    _sigmoid,
    _softplus,
    run_exported_model,
    run_exported_multitask_model,
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
