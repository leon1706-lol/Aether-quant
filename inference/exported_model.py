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


def _softmax(values, axis: int = -1):
    """Numerically stable softmax along `axis` (subtracts the per-axis max
    before exponentiating). Phase 2 primitive - used by
    _multihead_attention() below, and available standalone for any future
    export that needs it."""
    array = np.asarray(values, dtype=np.float64)
    shifted = array - np.max(array, axis=axis, keepdims=True)
    exponentiated = np.exp(shifted)
    return exponentiated / np.sum(exponentiated, axis=axis, keepdims=True)


def _layernorm_axis(values, weights: list[float], bias: list[float], eps: float, axis: int = -1) -> np.ndarray:
    """Axis-aware generalization of _layernorm() above - Phase 2 needs to
    normalize a (window, features) sequence independently per timestep
    (matching PyTorch's nn.LayerNorm(features) applied to a (window,
    features) tensor: mean/variance computed over the feature axis only,
    never across timesteps), where the original _layernorm() normalizes a
    single flat vector as one whole.

    A new function, not a modification of _layernorm() - run_exported_model()
    and run_exported_multitask_model() both call the original with no axis
    concept, and changing its signature would be a needless behavior risk
    to code already shipped. Reduces to the same result as _layernorm()
    when given a 1D array (axis=-1 is the only axis)."""
    values_array = np.asarray(values, dtype=np.float64)
    mean_value = values_array.mean(axis=axis, keepdims=True)
    variance = values_array.var(axis=axis, keepdims=True)
    denominator = np.sqrt(variance + eps)
    normalized = (values_array - mean_value) / denominator
    return normalized * np.asarray(weights, dtype=np.float64) + np.asarray(bias, dtype=np.float64)


def _conv1d_causal(sequence, weights, bias, dilation: int = 1) -> np.ndarray:
    """Causal dilated 1D convolution over a (window, in_channels) sequence,
    matching PyTorch's nn.Conv1d(in_channels, out_channels, kernel_size,
    dilation=dilation) applied to a left-zero-padded input so output[t]
    depends only on input[<=t] (no lookahead - same invariant every other
    feature in this codebase already respects).

    `weights` has PyTorch's own nn.Conv1d.weight shape:
    (out_channels, in_channels, kernel_size). Left-pads with
    (kernel_size-1)*dilation zero timesteps so the output has the same
    number of timesteps as the input (PyTorch's own causal-conv idiom -
    "pad left by the receptive field, then run a valid/no-padding conv").

    Returns a (window, out_channels) array (channels-last, matching every
    other array shape in this module - the transpose to/from PyTorch's own
    channels-first (channels, window) convention happens once, here, not
    scattered across callers).
    """
    sequence_array = np.asarray(sequence, dtype=np.float64)  # (window, in_channels)
    weights_array = np.asarray(weights, dtype=np.float64)  # (out_channels, in_channels, kernel_size)
    bias_array = np.asarray(bias, dtype=np.float64)  # (out_channels,)

    window, in_channels = sequence_array.shape
    out_channels, weight_in_channels, kernel_size = weights_array.shape
    if weight_in_channels != in_channels:
        raise ValueError(f"_conv1d_causal: in_channels mismatch ({in_channels} vs weight's {weight_in_channels})")

    pad_left = (kernel_size - 1) * dilation
    padded = np.zeros((window + pad_left, in_channels), dtype=np.float64)
    padded[pad_left:, :] = sequence_array

    output = np.empty((window, out_channels), dtype=np.float64)
    for timestep in range(window):
        # Gather the kernel_size dilated taps ending at this (padded) timestep.
        tap_indices = timestep + pad_left - np.arange(kernel_size - 1, -1, -1) * dilation
        window_slice = padded[tap_indices, :]  # (kernel_size, in_channels)
        # weights_array is (out_channels, in_channels, kernel_size); align
        # the einsum's k/c axes to window_slice's (kernel_size, in_channels).
        output[timestep, :] = np.einsum("oik,ki->o", weights_array, window_slice) + bias_array
    return output


def _multihead_attention(
    sequence,
    query_weights, query_bias,
    key_weights, key_bias,
    value_weights, value_bias,
    output_weights, output_bias,
    num_heads: int,
    causal: bool = True,
) -> np.ndarray:
    """Standard scaled dot-product multi-head self-attention over a
    (window, d_model) sequence - Phase 2 infrastructure for a future
    attention-based sequence encoder (the first real Phase 2 sequence
    model shipped this pass, AetherNetSequenceEncoder in train.py, uses a
    causal TCN trunk instead - simpler to verify bit-for-bit end-to-end;
    see train.py's module docstring for that scope decision). Hand-
    verified against a small synthetic single-head example
    (tests/test_exported_model.py), not yet exercised by a real trained
    export.

    `causal=True` (default) masks each position from attending to any
    future position - same no-lookahead invariant _conv1d_causal() above
    enforces, since any sequence model in this codebase must never see
    ahead of the bar it's predicting for.

    query/key/value/output weights follow PyTorch's nn.Linear.weight shape
    (out_features, in_features); d_model must be divisible by num_heads.
    """
    sequence_array = np.asarray(sequence, dtype=np.float64)  # (window, d_model)
    window, d_model = sequence_array.shape
    if d_model % num_heads != 0:
        raise ValueError(f"_multihead_attention: d_model={d_model} not divisible by num_heads={num_heads}")
    head_dim = d_model // num_heads

    def project(weights, bias):
        return sequence_array @ np.asarray(weights, dtype=np.float64).T + np.asarray(bias, dtype=np.float64)

    query = project(query_weights, query_bias).reshape(window, num_heads, head_dim).transpose(1, 0, 2)
    key = project(key_weights, key_bias).reshape(window, num_heads, head_dim).transpose(1, 0, 2)
    value = project(value_weights, value_bias).reshape(window, num_heads, head_dim).transpose(1, 0, 2)

    scores = np.matmul(query, key.transpose(0, 2, 1)) / np.sqrt(head_dim)  # (num_heads, window, window)
    if causal:
        causal_mask = np.triu(np.ones((window, window), dtype=bool), k=1)
        scores = np.where(causal_mask[None, :, :], -np.inf, scores)

    attention_weights = _softmax(scores, axis=-1)
    context = np.matmul(attention_weights, value)  # (num_heads, window, head_dim)
    context = context.transpose(1, 0, 2).reshape(window, d_model)

    output_weights_array = np.asarray(output_weights, dtype=np.float64)
    output_bias_array = np.asarray(output_bias, dtype=np.float64)
    return context @ output_weights_array.T + output_bias_array


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


def run_exported_sequence_multitask_model(model_export: dict, sequence: list[list[float]]) -> dict[str, float]:
    """Phase 2: forward pass over a sequence-encoder export - a causal TCN
    trunk (train.py::AetherNetSequenceMultiTask/export_sequence_multitask_architecture())
    consuming a (window, features) matrix instead of run_exported_multitask_model()'s
    flat feature vector, pooled to its last (most-recent, causal) timestep,
    then the same {"direction", "magnitude", "volatility"} head shape
    run_exported_multitask_model() already uses.

    `sequence` must be ordered oldest-to-newest (sequence[-1] is the
    current bar) - main.py's rolling per-symbol buffer of already-computed
    flat model_inputs vectors (see main.py::_build_sequence_model_input())
    is built in that order.

    A new function alongside run_exported_model()/run_exported_multitask_model(),
    not a generalization of either - zero regression risk to the flat-vector
    interpreters both call sites already depend on."""
    export = model_export["export"]
    state_dict = export["state_dict"]
    current = np.asarray(sequence, dtype=np.float64)

    for layer in export["trunk"]:
        layer_type = layer["type"]
        if layer_type == "conv1d_causal":
            weights = state_dict[layer["weight_key"]]
            bias = state_dict[layer["bias_key"]]
            current = _conv1d_causal(current, weights, bias, dilation=int(layer.get("dilation", 1)))
        elif layer_type == "relu":
            current = np.maximum(current, 0.0)
        elif layer_type == "layernorm_axis":
            weights = state_dict[layer["weight_key"]]
            bias = state_dict[layer["bias_key"]]
            current = _layernorm_axis(current, weights, bias, float(layer.get("eps", 1e-5)), axis=-1)
        elif layer_type == "dropout":
            continue
        else:
            raise ValueError(f"Unsupported sequence trunk layer type in export: {layer_type}")

    pooled = current[-1, :]  # most-recent timestep - the causal trunk's "as-of-now" representation

    outputs: dict[str, float] = {}
    for head_name, head_layers in export["heads"].items():
        head_output = _run_layer_stack(head_layers, state_dict, pooled.copy())
        outputs[head_name] = float(head_output[0])
    return outputs


def resolve_sequence_window_size(sequence_feature_schema: dict | None, configured_window_size: int) -> int:
    """The trained model's OWN window_size (sequence_feature_schema.json,
    written by train_sequence.py) wins over config.json's - a retrained
    candidate with a different window_size used to silently disable the
    sequence signal (main.py built a rolling buffer sized for the old/
    configured window, then fed it into run_exported_sequence_multitask_model()'s
    Conv1d stack sized for the new one - a shape mismatch caught by
    main.py::_run_sequence_model()'s blanket except, never surfaced).
    Falls back to configured_window_size only when no schema loaded at all
    (missing/malformed model file - see main.py::_load_sequence_model()'s
    graceful-fallback contract). Lives here (not main.py) so it's
    unit-testable without a Lean QCAlgorithm environment."""
    return int((sequence_feature_schema or {}).get("window_size", configured_window_size))
