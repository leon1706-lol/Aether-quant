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


def _softplus(value):
    """Numerically stable softplus: log(1+e^x) = log1p(e^-|x|) + max(x, 0).
    Used only by the volatility head below - guarantees a strictly
    non-negative volatility prediction without the overflow risk of a
    naive log(1 + exp(x)) for large positive x."""
    array = np.asarray(value, dtype=np.float64)
    return np.log1p(np.exp(-np.abs(array))) + np.maximum(array, 0.0)


def _run_layer_stack(layers: list[dict], state_dict: dict, current: np.ndarray) -> np.ndarray:
    """Shared per-layer forward pass, used only by run_exported_multitask_model()
    below - run_exported_model() above stays untouched (same layer-loop shape,
    duplicated rather than shared, so the original interpreter carries zero
    risk from this addition). Supports the same layer set as run_exported_model()
    plus "softplus" for the volatility head; trunks/heads are deliberately
    restricted to relu/layernorm/dropout/sigmoid/softplus (never gelu/silu/
    batchnorm1d), mirroring train_gating.py's existing restriction for the
    same reason - this interpreter cannot run those layer types."""
    for layer in layers:
        layer_type = layer["type"]
        if layer_type == "linear":
            weights = state_dict[layer["weight_key"]]
            bias = state_dict[layer["bias_key"]]
            current = _linear(current, weights, bias)
        elif layer_type == "layernorm":
            weights = state_dict[layer["weight_key"]]
            bias = state_dict[layer["bias_key"]]
            current = _layernorm(current, weights, bias, float(layer.get("eps", 1e-5)))
        elif layer_type == "relu":
            current = np.maximum(current, 0.0)
        elif layer_type == "dropout":
            continue
        elif layer_type == "sigmoid":
            current = _sigmoid(current)
        elif layer_type == "softplus":
            current = _softplus(current)
        else:
            raise ValueError(f"Unsupported layer type in export: {layer_type}")
    return current


def run_exported_multitask_model(model_export: dict, inputs: list[float]) -> dict[str, float]:
    """Forward pass over a branching {"trunk": [...], "heads": {name: [...]}}
    export (train.py::export_multitask_architecture()/AetherNetMultiTask) -
    the shared trunk runs once, then each head runs independently starting
    from the trunk's output. Returns one scalar per head, e.g.
    {"direction": <sigmoid prob>, "magnitude": <raw regression>,
    "volatility": <softplus, always >= 0>}.

    Deliberately a new function alongside run_exported_model(), not a
    generalization of it - the existing flat-architecture interpreter and
    its 5 call sites (main.py, moe/gating.py, train_gating.py) are untouched,
    zero regression risk to anything already shipped."""
    export = model_export["export"]
    state_dict = export["state_dict"]
    trunk_output = _run_layer_stack(export["trunk"], state_dict, np.asarray(inputs, dtype=np.float64))

    outputs: dict[str, float] = {}
    for head_name, head_layers in export["heads"].items():
        head_output = _run_layer_stack(head_layers, state_dict, trunk_output.copy())
        outputs[head_name] = float(head_output[0])
    return outputs
