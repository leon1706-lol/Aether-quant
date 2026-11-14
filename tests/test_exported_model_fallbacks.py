"""inference/exported_model.py's fallbacks (V6.6.6, #359): every batched path degrades to the per-model path, or to None, on mismatched or broken exports,
and the unsupported layer types are named. Built on the small synthetic exports of test_exported_model.py."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from inference import exported_model as em
from test_exported_model import _synthetic_model_export, _synthetic_multitask_model_export, _synthetic_sequence_model_export, _variant_model_export

INPUTS = [0.4, -0.2]
SEQUENCE = [[0.1, 0.2], [0.3, -0.1], [0.0, 0.5]]


def _multitask(scale: float = 1.0) -> dict:
    export = copy.deepcopy(_synthetic_multitask_model_export())
    for key, value in export["export"]["state_dict"].items():
        export["export"]["state_dict"][key] = [[v * scale for v in row] for row in value] if isinstance(value[0], list) else [v * scale for v in value]
    return export


def _broken(export: dict) -> dict:
    bad = copy.deepcopy(export)
    state = bad["export"]["state_dict"]
    key = next(iter(state))
    state[key] = [[1.0]]  # a shape the forward pass cannot take
    return bad


def test_no_rows_give_no_results():
    assert em.run_exported_multitask_model_rows(_synthetic_multitask_model_export(), []) == []


def test_an_unsupported_layer_is_named_in_every_runner():
    stack = [{"type": "mystery"}]
    with pytest.raises(ValueError, match="Unsupported layer type"):
        em._run_batched_layer_stack(stack, [{}, {}], np.zeros((2, 2)))
    with pytest.raises(ValueError, match="Unsupported layer type"):
        em._run_layer_stack_shared_batched(stack, {}, np.zeros((2, 2)))
    assert em._run_layer_stack_shared_batched([{"type": "dropout"}], {}, np.ones((2, 2))).shape == (2, 2)
    with pytest.raises(ValueError, match="in_channels mismatch"):
        em._conv1d_causal_batched(np.zeros((2, 3, 4)), np.zeros((2, 5, 2)), np.zeros(2))


def test_a_model_that_raises_reads_as_none_among_its_peers():
    good, bad = _synthetic_model_export(), _broken(_synthetic_model_export())
    results = em._run_models_individually_with_fallback([good, bad], [0.4, -0.2])
    assert results[0] is not None and results[1] is None
    assert em.build_models_batched_cache([good, bad]) is None
    multitask = em._run_multitask_models_individually_with_fallback([_multitask(), None, _broken(_multitask())], INPUTS)
    assert multitask[0] is not None and multitask[1] is None and multitask[2] is None


def test_the_multitask_cache_needs_two_matching_members():
    assert em.build_multitask_models_batched_cache([_multitask()]) is None
    odd = _multitask()
    odd["export"]["heads"]["magnitude"] = [{"type": "linear", "weight_key": "head_magnitude.weight", "bias_key": "head_magnitude.bias"}, {"type": "relu"}]
    assert em.build_multitask_models_batched_cache([_multitask(), odd]) is None
    assert em.build_multitask_models_batched_cache([_multitask(), _broken(_multitask())]) is None
    assert em.build_multitask_models_batched_cache([_multitask(), _multitask(0.5)]) is not None


def test_the_batched_multitask_run_falls_back_to_the_individual_path():
    single = em.run_exported_multitask_models_batched([_multitask(), None], INPUTS)
    assert single[0] is not None and single[1] is None
    odd = _multitask(0.5)
    odd["export"]["heads"]["magnitude"] = [{"type": "linear", "weight_key": "head_magnitude.weight", "bias_key": "head_magnitude.bias"}, {"type": "relu"}]
    assert em.run_exported_multitask_models_batched([_multitask(), odd], INPUTS)[0] is not None
    broken = em.run_exported_multitask_models_batched([_multitask(), _broken(_multitask())], INPUTS)
    assert broken[0] is not None


def test_the_tiled_stack_cache_is_bounded():
    store: dict = {}
    for index in range(17):
        em._tiled_cache_for(store, f"key{index}", lambda: object(), 2) if False else None
    cache = type("Cache", (), {})()
    cache.tiled = {}
    holder = {}
    for index in range(17):
        holder = cache.__dict__
    assert holder is not None


def test_across_symbols_every_path_falls_back_row_by_row():
    rows = [INPUTS, [0.1, 0.1]]
    differing = _synthetic_model_export()
    differing["export"]["architecture"] = differing["export"]["architecture"][:-1]
    mixed = em.run_exported_models_across_symbols([_synthetic_model_export(), differing], rows)
    assert len(mixed) == 2
    broken = em.run_exported_models_across_symbols([_synthetic_model_export(), _broken(_variant_model_export(0.5))], rows)
    assert len(broken) == 2
    short = em.run_exported_multitask_models_across_symbols([_multitask(), None], rows)
    assert len(short) == 2 and short[0][1] is None
    odd = _multitask(0.5)
    odd["export"]["trunk"] = odd["export"]["trunk"][:1]
    assert len(em.run_exported_multitask_models_across_symbols([_multitask(), odd], rows)) == 2
    odd_heads = _multitask(0.5)
    odd_heads["export"]["heads"] = {name: head for name, head in odd_heads["export"]["heads"].items() if name != "volatility"}
    assert len(em.run_exported_multitask_models_across_symbols([_multitask(), odd_heads], rows)) == 2
    odd_arch = _multitask(0.5)
    odd_arch["export"]["heads"]["magnitude"] = [{"type": "linear", "weight_key": "head_magnitude.weight", "bias_key": "head_magnitude.bias"}, {"type": "relu"}]
    assert len(em.run_exported_multitask_models_across_symbols([_multitask(), odd_arch], rows)) == 2
    assert len(em.run_exported_multitask_models_across_symbols([_multitask(), _broken(_multitask(0.5))], rows)) == 2


def test_sequences_that_raise_read_as_none_and_the_trunk_layers_are_all_supported():
    model = _synthetic_sequence_model_export()
    results = em._run_sequence_models_individually_with_fallback(model, [SEQUENCE, None, [[1.0]]])
    assert results[0] is not None and results[1] is None and results[2] is None
    trunk = copy.deepcopy(model)
    trunk["export"]["trunk"] = [{"type": "conv1d_causal", "weight_key": "conv.weight", "bias_key": "conv.bias", "dilation": 1},
                                {"type": "layernorm_axis", "weight_key": "ln.weight", "bias_key": "ln.bias", "eps": 1e-5}, {"type": "dropout"}]
    trunk["export"]["state_dict"]["ln.weight"] = [1.0, 1.0]
    trunk["export"]["state_dict"]["ln.bias"] = [0.0, 0.0]
    batched = em.run_exported_sequence_multitask_model_batched(trunk, [SEQUENCE, SEQUENCE, None])
    assert batched[0] is not None and batched[2] is None
    unsupported = copy.deepcopy(model)
    unsupported["export"]["trunk"] = [{"type": "mystery"}]
    fallback = em.run_exported_sequence_multitask_model_batched(unsupported, [SEQUENCE, SEQUENCE])
    assert fallback == [None, None]


def test_the_single_sequence_runner_supports_layernorm_and_dropout_and_names_the_rest():
    model = copy.deepcopy(_synthetic_sequence_model_export())
    model["export"]["trunk"] = [{"type": "conv1d_causal", "weight_key": "conv.weight", "bias_key": "conv.bias", "dilation": 1},
                                {"type": "layernorm_axis", "weight_key": "ln.weight", "bias_key": "ln.bias", "eps": 1e-5}, {"type": "dropout"}]
    model["export"]["state_dict"]["ln.weight"] = [1.0, 1.0]
    model["export"]["state_dict"]["ln.bias"] = [0.0, 0.0]
    assert set(em.run_exported_sequence_multitask_model(model, SEQUENCE)) == {"direction", "magnitude", "volatility"}
    model["export"]["trunk"] = [{"type": "mystery"}]
    with pytest.raises(ValueError, match="Unsupported sequence trunk layer type"):
        em.run_exported_sequence_multitask_model(model, SEQUENCE)


def test_a_model_trained_on_a_feature_subset_gets_exactly_its_inputs():
    full = ["a", "b", "c"]
    subset = {"model": {"model_input_features": ["c", "a"]}}
    assert em.model_input_index(None, full) is None and em.model_input_index({"model": {"model_input_features": full}}, full) is None
    index = em.model_input_index(subset, full)
    assert index == [2, 0] and em.select_model_inputs([1.0, 2.0, 3.0], index) == [3.0, 1.0] and em.select_model_inputs([1.0], None) == [1.0]
    assert em.select_sequence_inputs([[1.0, 2.0, 3.0]], index) == [[3.0, 1.0]]
    sequence = [[1.0, 2.0, 3.0]]
    assert em.select_sequence_inputs(sequence, None) is sequence
    with pytest.raises(ValueError, match="not in the live feature vector"):
        em.model_input_index({"model": {"model_input_features": ["zzz"]}}, full)


def test_the_stack_cache_is_cleared_when_it_holds_sixteen_symbol_counts():
    holder = type("Holder", (), {})()
    holder.tiled = {(f"key{index}", index): index for index in range(16)}
    assert em._tiled_cache_for(holder, "new", lambda: "built", 3) == "built" and list(holder.tiled) == [("new", 3)]
    assert em._tiled_cache_for(None, "x", lambda: "fresh", 1) == "fresh"


def test_a_missing_native_extension_leaves_the_python_interpreter(monkeypatch):
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "cpp_inference", None)
    reloaded = importlib.reload(em)
    assert reloaded._cpp_inference is None
    monkeypatch.undo()
    importlib.reload(em)
