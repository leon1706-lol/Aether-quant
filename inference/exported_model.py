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

# Optional C++/pybind11 accelerator for _linear_batched() below (see
# cpp_inference/README.md and development/Problems.md #32) - never a hard
# dependency. Deferred import, same convention as ib_insync
# (data_pipeline/ib_backfill.py): absent/unbuilt on most machines, and
# _linear_batched() falls back to the NumPy einsum path on any
# import/call failure below, not just at this import site.
try:
    import cpp_inference as _cpp_inference
except ImportError:
    _cpp_inference = None


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


def convert_state_dict_arrays(export: dict) -> None:
    """Converts every value in export["export"]["state_dict"] from a plain
    Python list to a np.float64 ndarray, IN PLACE - call this ONCE, right
    after a model export is loaded from JSON (see main.py's various
    `_load_*` methods), not on every inference call.

    Every `_linear`/`_layernorm`/`_layernorm_axis`/`_conv1d_causal`/
    `_run_batched_layer_stack` call below still runs `np.asarray(value,
    dtype=np.float64)` on state_dict values - that line is NOT removed,
    since `tests/test_exported_model.py` passes raw Python lists directly
    and must keep working. What changes is the cost: `np.asarray()` on an
    ndarray that already has the right dtype is a documented no-op (same
    object returned, no copy) - so calling this once at load time turns
    every later `np.asarray()` call on that export's weights into a cheap
    identity check instead of a real list-to-array conversion, which
    profiling (`scripts/profile_inference.py`) found was the single
    largest remaining cost in the per-bar inference hot path after the
    expert-batching/conv1d-vectorization pass (116.9s of 290.6s - see
    development/Problems.md).

    Safe to call on any export shape this module consumes: flat
    (`{"architecture": [...], "state_dict": {...}}`), branching multitask
    (`{"trunk": [...], "heads": {...}, "state_dict": {...}}`), and
    sequence (same branching shape, `state_dict` may hold conv1d weight
    tensors - `np.asarray` on those still round-trips through the same
    no-op-when-already-array path). Never raises on a missing/malformed
    "state_dict" key - degrades to a no-op, since main.py's loaders
    already handle malformed exports via their own try/except."""
    state_dict = export.get("export", {}).get("state_dict")
    if not isinstance(state_dict, dict):
        return
    for key, value in state_dict.items():
        if not isinstance(value, np.ndarray):
            state_dict[key] = np.asarray(value, dtype=np.float64)


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


# ---------------------------------------------------------------------------
# Batched inference across multiple SAME-ARCHITECTURE models sharing one
# input (main.py's 4-expert loop / 4-multitask-expert loop) - one NumPy call
# per layer across all N stacked models instead of N separate
# run_exported_model()/run_exported_multitask_model() calls. Added after
# scripts/profile_inference.py's cProfile run showed Python/NumPy per-call
# dispatch overhead dominating this hot path's cost, not FLOPs (see
# development/Problems.md) - the models involved (85->24->1, 4 of them) are
# too small for raw matmul throughput to matter; call-count is what matters.
# ---------------------------------------------------------------------------


def _architectures_match(architectures: list[list[dict]]) -> bool:
    """True iff every model's layer-type-and-key sequence is identical -
    the precondition for batching. Compares type/weight_key/bias_key per
    layer, not weight shapes - a shape mismatch despite matching keys would
    be a genuinely corrupt export and is left to surface as a numpy error,
    caught by run_exported_models_batched()'s own try/except fallback."""
    if len(architectures) < 2:
        return True
    first = [(layer["type"], layer.get("weight_key"), layer.get("bias_key")) for layer in architectures[0]]
    return all(
        [(layer["type"], layer.get("weight_key"), layer.get("bias_key")) for layer in arch] == first
        for arch in architectures[1:]
    )


def _linear_batched(current: np.ndarray, weights_stack: np.ndarray, bias_stack: np.ndarray) -> np.ndarray:
    """Batched sibling of _linear() - one einsum across all N stacked
    models instead of N separate `weights @ input + bias` calls.
    current: (N, in_features); weights_stack: (N, out_features,
    in_features); bias_stack: (N, out_features).

    Uses the optional cpp_inference accelerator (see module-level import
    above) when it's built and importable - falls back to the always-
    correct NumPy einsum path on ANY failure (missing extension, a call
    raising for any reason), never a hard dependency and never a crash
    risk. This is the hottest, most call-heavy primitive in the batched
    inference path (see development/Problems.md #32's profiling), which
    is why it's the one primitive this pass wired an accelerator for."""
    if _cpp_inference is not None:
        try:
            return _cpp_inference.linear_batched(weights_stack, current, bias_stack)
        except Exception:
            pass  # fall through to the NumPy path below
    return np.einsum("noi,ni->no", weights_stack, current) + bias_stack


def _layernorm_batched(current: np.ndarray, weights_stack: np.ndarray, bias_stack: np.ndarray, eps: float) -> np.ndarray:
    """Batched sibling of _layernorm() - each row (model) normalized
    independently using its OWN mean/variance along the feature axis, then
    scaled/shifted by that row's own separately-trained weight/bias.
    Unlike _layernorm_axis() (one shared weight/bias broadcast across every
    row, used by the sequence encoder's single-model timestep axis), every
    stacked model here has its own weights - genuinely different from a
    plain broadcast."""
    mean_value = current.mean(axis=-1, keepdims=True)
    variance = current.var(axis=-1, keepdims=True)
    normalized = (current - mean_value) / np.sqrt(variance + eps)
    return normalized * weights_stack + bias_stack


def build_layer_stacks(layers: list[dict], state_dicts: list[dict]) -> list[tuple[np.ndarray, np.ndarray] | None]:
    """Precomputes each linear/layernorm layer's weights_stack/bias_stack
    ONCE - the same np.stack([...]) construction _run_batched_layer_stack()
    below otherwise rebuilds from scratch on every single call, even though
    the underlying weights never change once a model's loaded (this was
    profiling's second-largest finding after the raw asarray cost -
    stacking itself still copies data into a new array every call). None
    for layer types that carry no weights (relu/dropout/sigmoid/softplus) -
    kept as an explicit placeholder so the returned list stays index-
    aligned with `layers`, letting _run_batched_layer_stack() zip them
    together directly."""
    stacks: list[tuple[np.ndarray, np.ndarray] | None] = []
    for layer in layers:
        if layer["type"] in ("linear", "layernorm"):
            weights_stack = np.stack([np.asarray(sd[layer["weight_key"]], dtype=np.float64) for sd in state_dicts])
            bias_stack = np.stack([np.asarray(sd[layer["bias_key"]], dtype=np.float64) for sd in state_dicts])
            stacks.append((weights_stack, bias_stack))
        else:
            stacks.append(None)
    return stacks


def _run_batched_layer_stack(
    layers: list[dict],
    state_dicts: list[dict],
    current: np.ndarray,
    precomputed_stacks: list[tuple[np.ndarray, np.ndarray] | None] | None = None,
) -> np.ndarray:
    """Batched sibling of _run_layer_stack() - current starts as (N,
    features) instead of (features,), one row per stacked model, and each
    linear/layernorm layer pulls that layer's weights from every model's
    own state_dict rather than one shared state_dict.

    `precomputed_stacks`, when given (see build_layer_stacks() above), is
    used instead of rebuilding weights_stack/bias_stack via np.stack() on
    this call - callers with a stable model set (main.py, once experts are
    loaded) should build this once and reuse it every bar. None (the
    default) reproduces the exact original behavior - every existing
    caller/test that doesn't pass it is unaffected."""
    for index, layer in enumerate(layers):
        layer_type = layer["type"]
        cached = precomputed_stacks[index] if precomputed_stacks is not None else None
        if layer_type == "linear":
            if cached is not None:
                weights_stack, bias_stack = cached
            else:
                weights_stack = np.stack([np.asarray(sd[layer["weight_key"]], dtype=np.float64) for sd in state_dicts])
                bias_stack = np.stack([np.asarray(sd[layer["bias_key"]], dtype=np.float64) for sd in state_dicts])
            current = _linear_batched(current, weights_stack, bias_stack)
        elif layer_type == "layernorm":
            if cached is not None:
                weights_stack, bias_stack = cached
            else:
                weights_stack = np.stack([np.asarray(sd[layer["weight_key"]], dtype=np.float64) for sd in state_dicts])
                bias_stack = np.stack([np.asarray(sd[layer["bias_key"]], dtype=np.float64) for sd in state_dicts])
            current = _layernorm_batched(current, weights_stack, bias_stack, float(layer.get("eps", 1e-5)))
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


def _run_models_individually_with_fallback(model_exports: list[dict | None], inputs: list[float]) -> list[float | None]:
    """Exactly today's pre-batching behavior: one run_exported_model() call
    per present entry, None preserved for missing entries, one failed
    model degrading to None WITHOUT taking any other entry down with it -
    the same per-expert graceful-degradation contract
    main.py::_run_expert_models() has always had. Used as the batching
    functions' fallback whenever batching isn't safe/possible, so that
    fallback path is never a behavior change, only a performance one."""
    results: list[float | None] = []
    for export in model_exports:
        if not export:
            results.append(None)
            continue
        try:
            results.append(run_exported_model(export, inputs))
        except Exception:
            results.append(None)
    return results


class BatchedLayerStackCache:
    """Precomputed run_exported_models_batched() weight/bias stacks for a
    FIXED set of models sharing one architecture - build once (e.g. in
    main.py::_ensure_ready(), right after experts are loaded) via
    build_models_batched_cache() below, then pass into every bar's
    run_exported_models_batched() call instead of letting it rebuild the
    stacks from scratch every time. `present_indices` records exactly
    which model_exports slots this cache applies to; the caller
    (run_exported_models_batched()) verifies its own freshly computed
    present_indices matches before using it - a mismatch (which should
    never happen in practice, since main.py's expert exports are loaded
    once and never change mid-run) just means falling back to an on-the-
    fly rebuild, always safe."""

    def __init__(self, present_indices: list[int], layer_stacks: list[tuple[np.ndarray, np.ndarray] | None]):
        self.present_indices = present_indices
        self.layer_stacks = layer_stacks


def build_models_batched_cache(model_exports: list[dict | None]) -> BatchedLayerStackCache | None:
    """Precomputes run_exported_models_batched()'s per-layer weight/bias
    stacks once, returning None whenever batching wouldn't apply anyway
    (fewer than 2 present, architectures don't match) - the exact same
    applicability check run_exported_models_batched() runs itself every
    call, so a non-None cache this returns is always exactly the one that
    call would build on its own, just computed once instead of every bar."""
    present_indices = [i for i, export in enumerate(model_exports) if export]
    if len(present_indices) < 2:
        return None
    architectures = [model_exports[i]["export"]["architecture"] for i in present_indices]
    if not _architectures_match(architectures):
        return None
    try:
        state_dicts = [model_exports[i]["export"]["state_dict"] for i in present_indices]
        layer_stacks = build_layer_stacks(architectures[0], state_dicts)
    except Exception:
        return None
    return BatchedLayerStackCache(present_indices, layer_stacks)


def run_exported_models_batched(
    model_exports: list[dict | None],
    inputs: list[float],
    stack_cache: BatchedLayerStackCache | None = None,
) -> list[float | None]:
    """Batched sibling of calling run_exported_model() once per entry in a
    loop (main.py::_run_expert_models()'s previous shape, still available
    via _run_models_individually_with_fallback() above). Stacks every
    PRESENT model's per-layer weights into one leading batch axis and runs
    one _linear_batched()/_layernorm_batched() call per layer instead of N
    separate run_exported_model() calls.

    `stack_cache` (see BatchedLayerStackCache/build_models_batched_cache()
    above), when given AND its present_indices matches this call's own,
    skips rebuilding the weight/bias stacks from scratch - the default
    None reproduces the exact original behavior, so every existing caller/
    test that doesn't pass it is unaffected.

    Falls back to the individually-with-fallback path - never raises,
    never silently produces a wrong answer - whenever fewer than 2 models
    are present, their architectures don't match closely enough to batch,
    or the batched computation itself raises for any reason (e.g. a shape
    mismatch a type/key match didn't catch - a real safety net, not just a
    defensive habit: a retrained single expert with a different hidden
    width would otherwise silently corrupt every other expert's output via
    a numpy broadcast if this fell through to batching anyway).

    Returns one float per entry in model_exports, None preserved at any
    index whose export was None/falsy - same shape contract
    main.py::_run_expert_models() already depends on."""
    present_indices = [i for i, export in enumerate(model_exports) if export]
    if len(present_indices) < 2:
        return _run_models_individually_with_fallback(model_exports, inputs)

    architectures = [model_exports[i]["export"]["architecture"] for i in present_indices]
    if not _architectures_match(architectures):
        return _run_models_individually_with_fallback(model_exports, inputs)

    try:
        state_dicts = [model_exports[i]["export"]["state_dict"] for i in present_indices]
        current = np.tile(np.asarray(inputs, dtype=np.float64), (len(present_indices), 1))
        precomputed_stacks = (
            stack_cache.layer_stacks if stack_cache is not None and stack_cache.present_indices == present_indices else None
        )
        current = _run_batched_layer_stack(architectures[0], state_dicts, current, precomputed_stacks=precomputed_stacks)
    except Exception:
        return _run_models_individually_with_fallback(model_exports, inputs)

    results: list[float | None] = [None] * len(model_exports)
    for row, original_index in enumerate(present_indices):
        results[original_index] = float(current[row, 0])
    return results


def _run_multitask_models_individually_with_fallback(
    model_exports: list[dict | None], inputs: list[float]
) -> list[dict[str, float] | None]:
    """Multitask sibling of _run_models_individually_with_fallback() -
    same per-expert graceful-degradation contract
    main.py::_run_expert_multitask_models() has always had."""
    results: list[dict[str, float] | None] = []
    for export in model_exports:
        if not export:
            results.append(None)
            continue
        try:
            results.append(run_exported_multitask_model(export, inputs))
        except Exception:
            results.append(None)
    return results


class BatchedMultitaskLayerStackCache:
    """Multitask sibling of BatchedLayerStackCache - one precomputed stack
    set for the shared trunk plus one per head, all tied to the same
    `present_indices`. Build once via build_multitask_models_batched_cache()
    below."""

    def __init__(
        self,
        present_indices: list[int],
        trunk_stacks: list[tuple[np.ndarray, np.ndarray] | None],
        head_stacks_by_name: dict[str, list[tuple[np.ndarray, np.ndarray] | None]],
    ):
        self.present_indices = present_indices
        self.trunk_stacks = trunk_stacks
        self.head_stacks_by_name = head_stacks_by_name


def build_multitask_models_batched_cache(
    model_exports: list[dict | None],
) -> BatchedMultitaskLayerStackCache | None:
    """Multitask sibling of build_models_batched_cache() - same
    applicability check run_exported_multitask_models_batched() runs
    itself every call (trunk architectures match, head name sets match,
    every head's own architecture matches), returning None whenever that
    check would fail anyway."""
    present_indices = [i for i, export in enumerate(model_exports) if export]
    if len(present_indices) < 2:
        return None

    exports = [model_exports[i]["export"] for i in present_indices]
    trunk_architectures = [export["trunk"] for export in exports]
    head_name_sets = [tuple(sorted(export["heads"].keys())) for export in exports]
    if not _architectures_match(trunk_architectures) or len(set(head_name_sets)) != 1:
        return None

    head_names = head_name_sets[0]
    head_architectures_by_name = {name: [export["heads"][name] for export in exports] for name in head_names}
    if any(not _architectures_match(archs) for archs in head_architectures_by_name.values()):
        return None

    try:
        state_dicts = [export["state_dict"] for export in exports]
        trunk_stacks = build_layer_stacks(trunk_architectures[0], state_dicts)
        head_stacks_by_name = {
            name: build_layer_stacks(head_architectures_by_name[name][0], state_dicts) for name in head_names
        }
    except Exception:
        return None
    return BatchedMultitaskLayerStackCache(present_indices, trunk_stacks, head_stacks_by_name)


def run_exported_multitask_models_batched(
    model_exports: list[dict | None],
    inputs: list[float],
    stack_cache: BatchedMultitaskLayerStackCache | None = None,
) -> list[dict[str, float] | None]:
    """Batched sibling of run_exported_multitask_model(), for
    main.py::_run_expert_multitask_models()'s per-expert loop. Batches the
    shared trunk across all N present models first, then batches each head
    (direction/magnitude/volatility) across the same N models starting
    from the trunk's own per-model output - correct only when every
    present model shares the same trunk AND the same head names/
    architectures, checked the same way run_exported_models_batched()
    checks its flat models. Same graceful-degradation contract and
    same-shape fallback safety net as run_exported_models_batched().

    `stack_cache` (see BatchedMultitaskLayerStackCache/
    build_multitask_models_batched_cache() above), when given AND its
    present_indices matches this call's own, skips rebuilding every
    weight/bias stack from scratch - default None reproduces the exact
    original behavior."""
    present_indices = [i for i, export in enumerate(model_exports) if export]
    if len(present_indices) < 2:
        return _run_multitask_models_individually_with_fallback(model_exports, inputs)

    exports = [model_exports[i]["export"] for i in present_indices]
    trunk_architectures = [export["trunk"] for export in exports]
    head_name_sets = [tuple(sorted(export["heads"].keys())) for export in exports]
    if not _architectures_match(trunk_architectures) or len(set(head_name_sets)) != 1:
        return _run_multitask_models_individually_with_fallback(model_exports, inputs)

    head_names = head_name_sets[0]
    head_architectures_by_name = {
        name: [export["heads"][name] for export in exports] for name in head_names
    }
    if any(not _architectures_match(archs) for archs in head_architectures_by_name.values()):
        return _run_multitask_models_individually_with_fallback(model_exports, inputs)

    cache_applies = stack_cache is not None and stack_cache.present_indices == present_indices

    try:
        state_dicts = [export["state_dict"] for export in exports]
        trunk_current = np.tile(np.asarray(inputs, dtype=np.float64), (len(present_indices), 1))
        trunk_output = _run_batched_layer_stack(
            trunk_architectures[0], state_dicts, trunk_current,
            precomputed_stacks=stack_cache.trunk_stacks if cache_applies else None,
        )

        head_outputs: dict[str, np.ndarray] = {}
        for head_name in head_names:
            head_outputs[head_name] = _run_batched_layer_stack(
                head_architectures_by_name[head_name][0], state_dicts, trunk_output.copy(),
                precomputed_stacks=stack_cache.head_stacks_by_name.get(head_name) if cache_applies else None,
            )
    except Exception:
        return _run_multitask_models_individually_with_fallback(model_exports, inputs)

    results: list[dict[str, float] | None] = [None] * len(model_exports)
    for row, original_index in enumerate(present_indices):
        results[original_index] = {head_name: float(head_outputs[head_name][row, 0]) for head_name in head_names}
    return results


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

    # Vectorized sibling of the original `for timestep in range(window):`
    # loop below (kept only as a reference in git history) - profiling this
    # hot path (scripts/profile_inference.py) showed this Python loop,
    # 30 iterations here to match the trained sequence model's window_size
    # but re-run once per symbol per bar, was the single largest cost in
    # main.py's entire per-bar inference path (bigger than the 4-expert
    # loop this same pass also batched - see run_exported_models_batched()
    # above). Builds every timestep's kernel_size dilated tap indices at
    # once (tap_indices: (window, kernel_size)), gathers them in one fancy-
    # index op (window_slices: (window, kernel_size, in_channels)), then
    # runs ONE einsum across every timestep instead of `window` separate
    # ones. Same math, same output - tests/test_exported_model.py's
    # existing hand-computed/causality/mismatch tests are the parity net,
    # unchanged by this rewrite (same function signature and output
    # contract, no new call sites needed).
    offsets = np.arange(kernel_size - 1, -1, -1) * dilation  # (kernel_size,)
    tap_indices = np.arange(window)[:, None] + pad_left - offsets[None, :]  # (window, kernel_size)
    window_slices = padded[tap_indices, :]  # (window, kernel_size, in_channels)
    return np.einsum("oik,tki->to", weights_array, window_slices) + bias_array


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
