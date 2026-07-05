import math

import pytest

from inference.exported_model import _layernorm, _linear, _sigmoid, run_exported_model


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
