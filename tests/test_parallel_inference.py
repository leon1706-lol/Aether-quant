"""Tests for inference/parallel_inference.py - the opt-in per-symbol
multiprocessing path for main.py::on_data()'s Pass 1 inference cluster.

Parity net: run_symbol_inference() (called directly, worker-global-state
style via init_worker()) must produce identical results to calling the
underlying run_exported_model()/run_exported_models_batched()/etc.
functions directly - and a REAL ProcessPoolExecutor round-trip (not just
a direct call) must produce the same results too, proving the exports
dict and the function itself are actually picklable across a real
process boundary, not just importable in-process.

Local fixtures only (this repo's convention - no shared conftest.py, each
test file self-contained), small versions of the same shapes
tests/test_exported_model.py already hand-verifies.
"""

from concurrent.futures import ProcessPoolExecutor

import pytest

from inference.exported_model import (
    run_exported_model,
    run_exported_models_batched,
    run_exported_multitask_model,
    run_exported_multitask_models_batched,
    run_exported_sequence_multitask_model,
)
from inference.parallel_inference import init_worker, run_symbol_inference

EXPERT_NAMES = ["bullish", "bearish", "sideways", "volatility"]


def _flat_export(scale: float = 1.0) -> dict:
    return {
        "export": {
            "architecture": [
                {"type": "linear", "weight_key": "l1.weight", "bias_key": "l1.bias"},
                {"type": "layernorm", "weight_key": "ln.weight", "bias_key": "ln.bias", "eps": 1e-5},
                {"type": "relu"},
                {"type": "linear", "weight_key": "l2.weight", "bias_key": "l2.bias"},
                {"type": "sigmoid"},
            ],
            "state_dict": {
                "l1.weight": [[0.5 * scale, -0.25], [0.1, 0.3 * scale], [-0.2, 0.4]],
                "l1.bias": [0.1, -0.1, 0.05],
                "ln.weight": [1.0, 1.0, 1.0],
                "ln.bias": [0.0, 0.0, 0.0],
                "l2.weight": [[0.3, -0.4, 0.2]],
                "l2.bias": [0.05],
            },
        }
    }


def _multitask_export(scale: float = 1.0) -> dict:
    return {
        "export": {
            "trunk": [
                {"type": "linear", "weight_key": "trunk.0.weight", "bias_key": "trunk.0.bias"},
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
                "trunk.0.weight": [[0.5 * scale, -0.25], [0.1, 0.3]],
                "trunk.0.bias": [0.1, -0.1],
                "head_direction.weight": [[0.3, -0.4]],
                "head_direction.bias": [0.05],
                "head_magnitude.weight": [[0.2, 0.1]],
                "head_magnitude.bias": [-0.02],
                "head_volatility.weight": [[0.1, 0.2]],
                "head_volatility.bias": [0.0],
            },
        }
    }


def _sequence_export() -> dict:
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
                "head_volatility.weight": [[0.1, 0.1]],
                "head_volatility.bias": [0.0],
            },
        }
    }


def _full_exports() -> dict:
    return {
        "baseline": _flat_export(1.0),
        "experts": {name: _flat_export(1.0 + 0.1 * i) for i, name in enumerate(EXPERT_NAMES)},
        "expert_names": EXPERT_NAMES,
        "expert_stack_cache": None,
        "multitask": _multitask_export(1.0),
        "expert_multitask": {name: _multitask_export(1.0 + 0.1 * i) for i, name in enumerate(EXPERT_NAMES)},
        "expert_multitask_stack_cache": None,
        "sequence": _sequence_export(),
    }


def test_run_symbol_inference_with_no_exports_returns_all_none():
    init_worker({})
    result = run_symbol_inference([1.0, -0.5], None, 30)

    assert result["baseline_probability"] is None
    assert result["sequence_result"] is None
    assert result["multitask_result"] is None
    assert result["expert_probabilities"] == {}
    assert result["expert_multitask_magnitudes"] == {}
    assert result["expert_multitask_volatilities"] == {}


def test_run_symbol_inference_baseline_matches_direct_call():
    exports = _full_exports()
    init_worker(exports)
    inputs = [1.0, -0.5]

    result = run_symbol_inference(inputs, None, 30)

    assert result["baseline_probability"] == pytest.approx(run_exported_model(exports["baseline"], inputs), abs=1e-9)


def test_run_symbol_inference_experts_match_direct_batched_call():
    exports = _full_exports()
    init_worker(exports)
    inputs = [1.0, -0.5]

    result = run_symbol_inference(inputs, None, 30)

    expert_list = [exports["experts"][name] for name in EXPERT_NAMES]
    expected = run_exported_models_batched(expert_list, inputs)
    for name, expected_value in zip(EXPERT_NAMES, expected):
        assert result["expert_probabilities"][name] == pytest.approx(expected_value, abs=1e-9)


def test_run_symbol_inference_multitask_matches_direct_call():
    exports = _full_exports()
    init_worker(exports)
    inputs = [1.0, -0.5]

    result = run_symbol_inference(inputs, None, 30)

    expected = run_exported_multitask_model(exports["multitask"], inputs)
    assert result["multitask_result"]["direction"] == pytest.approx(expected["direction"], abs=1e-9)
    assert result["multitask_result"]["magnitude"] == pytest.approx(expected["magnitude"], abs=1e-9)


def test_run_symbol_inference_expert_multitask_matches_direct_batched_call():
    exports = _full_exports()
    init_worker(exports)
    inputs = [1.0, -0.5]

    result = run_symbol_inference(inputs, None, 30)

    expert_multitask_list = [exports["expert_multitask"][name] for name in EXPERT_NAMES]
    expected = run_exported_multitask_models_batched(expert_multitask_list, inputs)
    for name, expected_value in zip(EXPERT_NAMES, expected):
        assert result["expert_multitask_magnitudes"][name] == pytest.approx(expected_value["magnitude"], abs=1e-9)
        assert result["expert_multitask_volatilities"][name] == pytest.approx(expected_value["volatility"], abs=1e-9)


def test_run_symbol_inference_sequence_result_none_when_no_history():
    exports = _full_exports()
    init_worker(exports)

    result = run_symbol_inference([1.0, -0.5], None, 30)

    assert result["sequence_result"] is None


def test_run_symbol_inference_sequence_matches_direct_call_when_history_given():
    exports = _full_exports()
    init_worker(exports)
    history = [[1.0, -0.5], [0.5, 0.2], [0.1, -0.1]]
    window_size = 5

    result = run_symbol_inference([0.1, -0.1], history, window_size)

    padded = [[0.0, 0.0]] * (window_size - len(history)) + history
    expected = run_exported_sequence_multitask_model(exports["sequence"], padded)
    assert result["sequence_result"]["direction"] == pytest.approx(expected["direction"], abs=1e-9)


def test_run_symbol_inference_missing_optional_pieces_degrade_gracefully():
    """Only a baseline export present - everything else must degrade to
    None/empty, never raise, same graceful-degradation contract every
    other inference call site in this codebase already has."""
    init_worker({"baseline": _flat_export()})
    result = run_symbol_inference([1.0, -0.5], None, 30)

    assert result["baseline_probability"] is not None
    assert result["multitask_result"] is None
    assert result["sequence_result"] is None
    assert result["expert_probabilities"] == {}


def test_run_symbol_inference_via_real_process_pool_matches_direct_call():
    """The real cross-process round-trip - proves the exports dict and
    run_symbol_inference() itself are actually picklable across a real
    OS process boundary (Windows uses `spawn`), not just callable
    in-process. This is the strongest confidence check available without
    a real Lean backtest (see inference/parallel_inference.py's module
    docstring for what remains genuinely unverified beyond this)."""
    exports = _full_exports()
    inputs = [1.0, -0.5]

    init_worker(exports)  # for the direct-call comparison in this same process
    direct_result = run_symbol_inference(inputs, None, 30)

    with ProcessPoolExecutor(max_workers=1, initializer=init_worker, initargs=(exports,)) as pool:
        future = pool.submit(run_symbol_inference, inputs, None, 30)
        pooled_result = future.result(timeout=60)

    assert pooled_result["baseline_probability"] == pytest.approx(direct_result["baseline_probability"], abs=1e-9)
    for name in EXPERT_NAMES:
        assert pooled_result["expert_probabilities"][name] == pytest.approx(
            direct_result["expert_probabilities"][name], abs=1e-9
        )
    assert pooled_result["multitask_result"]["direction"] == pytest.approx(
        direct_result["multitask_result"]["direction"], abs=1e-9
    )
