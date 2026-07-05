"""Forward-pass inference over a JSON-exported model architecture.

Extracted from `main.py`'s `_run_exported_model()`/`_linear()`/
`_layernorm()`/`_sigmoid()` methods (Part C of the latency-optimization
pass) - those were already pure (no `self.*` state, only calling sibling
methods), just not free functions yet. Mirrors the existing pure-module
pattern in `risk/position_sizing.py`/`regime/market_regime.py`: free
functions, no class, package `__init__.py` re-export.

Vectorized with numpy (the extraction was step 1; this is step 2) - this
ran once per symbol per bar, 5x (baseline + 4 experts), in plain Python
nested loops. `tests/test_exported_model.py` is the parity net: the same
hand-computed reference values from the pure-Python version must still
match within tolerance.

Consumes the same `{"architecture": [...], "state_dict": {...}}` shape that
`monitoring/neural_network_state.py` independently parses for a different
purpose (layer/node/edge counts vs. an actual forward pass here).
"""

from __future__ import annotations

import numpy as np


def run_exported_model(model_export: dict, inputs: list[float]) -> float:
    current = np.asarray(inputs, dtype=np.float64)
    for layer in model_export["export"]["architecture"]:
        layer_type = layer["type"]
        if layer_type == "linear":
            weights = model_export["export"]["state_dict"][layer["weight_key"]]
            bias = model_export["export"]["state_dict"][layer["bias_key"]]
            current = _linear(current, weights, bias)
        elif layer_type == "layernorm":
            weights = model_export["export"]["state_dict"][layer["weight_key"]]
            bias = model_export["export"]["state_dict"][layer["bias_key"]]
            current = _layernorm(current, weights, bias, float(layer.get("eps", 1e-5)))
        elif layer_type == "relu":
            current = np.maximum(current, 0.0)
        elif layer_type == "dropout":
            continue
        elif layer_type == "sigmoid":
            current = _sigmoid(current)
        else:
            raise ValueError(f"Unsupported layer type in export: {layer_type}")

    return float(current[0])


def _linear(inputs, weights: list[list[float]], bias: list[float]) -> np.ndarray:
    inputs_array = np.asarray(inputs, dtype=np.float64)
    weights_array = np.asarray(weights, dtype=np.float64)
    bias_array = np.asarray(bias, dtype=np.float64)
    return weights_array @ inputs_array + bias_array


def _layernorm(values, weights: list[float], bias: list[float], eps: float) -> np.ndarray:
    values_array = np.asarray(values, dtype=np.float64)
    mean_value = values_array.mean()
    variance = values_array.var()
    denominator = np.sqrt(variance + eps)
    normalized = (values_array - mean_value) / denominator
    return normalized * np.asarray(weights, dtype=np.float64) + np.asarray(bias, dtype=np.float64)


def _sigmoid(value):
    clipped = np.clip(value, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-clipped))
