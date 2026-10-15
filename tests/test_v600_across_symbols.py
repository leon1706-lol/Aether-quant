"""V6.0.0 (latency, rule R-LAT): the experts for every symbol in one pass equal the per-symbol calls."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from inference.exported_model import (
    build_models_batched_cache,
    build_multitask_models_batched_cache,
    run_exported_models_across_symbols,
    run_exported_models_batched,
    run_exported_multitask_models_across_symbols,
    run_exported_multitask_models_batched,
)

ROOT = Path(__file__).resolve().parents[1]
EXPERTS = ("bullish", "bearish", "sideways", "volatility")


def _flat_export(rng, features=6, hidden=5):
    names = {"w0": rng.normal(size=(hidden, features)).tolist(), "b0": rng.normal(size=hidden).tolist(),
             "w1": rng.normal(size=(1, hidden)).tolist(), "b1": rng.normal(size=1).tolist()}
    architecture = [{"type": "linear", "weight_key": "w0", "bias_key": "b0"}, {"type": "relu"},
                    {"type": "linear", "weight_key": "w1", "bias_key": "b1"}, {"type": "sigmoid"}]
    return {"export": {"architecture": architecture, "state_dict": names}}


def _multitask_export(rng, features=6, hidden=5):
    state = {"t_w": rng.normal(size=(hidden, features)).tolist(), "t_b": rng.normal(size=hidden).tolist()}
    heads = {}
    for name in ("direction", "magnitude", "volatility"):
        state[f"{name}_w"], state[f"{name}_b"] = rng.normal(size=(1, hidden)).tolist(), rng.normal(size=1).tolist()
        heads[name] = [{"type": "linear", "weight_key": f"{name}_w", "bias_key": f"{name}_b"}]
    heads["direction"].append({"type": "sigmoid"})
    heads["volatility"].append({"type": "softplus"})
    trunk = [{"type": "linear", "weight_key": "t_w", "bias_key": "t_b"}, {"type": "relu"}]
    return {"export": {"trunk": trunk, "heads": heads, "state_dict": state}}


def _rows(rng, symbols=9, features=6):
    return rng.normal(size=(symbols, features)).tolist()


def test_flat_experts_across_symbols_equal_the_per_symbol_calls():
    rng = np.random.default_rng(1)
    exports = [_flat_export(rng) for _ in EXPERTS]
    cache = build_models_batched_cache(exports)
    rows = _rows(rng)
    batched = run_exported_models_across_symbols(exports, rows, stack_cache=cache)
    for row, result in zip(rows, batched):
        assert result == pytest.approx(run_exported_models_batched(exports, row, stack_cache=cache), rel=0, abs=1e-12)
    no_cache = run_exported_models_across_symbols(exports, rows)  # no cache object
    assert [value for row in no_cache for value in row] == pytest.approx([value for row in batched for value in row], abs=1e-12)
    fewer = run_exported_models_across_symbols(exports, rows[:3], stack_cache=cache)  # a new symbol count builds new stacks
    assert [value for row in fewer for value in row] == pytest.approx([value for row in batched[:3] for value in row], abs=1e-12)


def test_a_missing_expert_stays_none_for_every_symbol():
    rng = np.random.default_rng(2)
    exports = [_flat_export(rng), None, _flat_export(rng), _flat_export(rng)]
    rows = _rows(rng, 4)
    for row, result in zip(rows, run_exported_models_across_symbols(exports, rows, stack_cache=build_models_batched_cache(exports))):
        assert result[1] is None
        assert result == pytest.approx(run_exported_models_batched(exports, row), abs=1e-12)


def test_multitask_experts_across_symbols_equal_the_per_symbol_calls():
    rng = np.random.default_rng(3)
    exports = [_multitask_export(rng) for _ in EXPERTS]
    cache = build_multitask_models_batched_cache(exports)
    rows = _rows(rng)
    batched = run_exported_multitask_models_across_symbols(exports, rows, stack_cache=cache)
    for row, result in zip(rows, batched):
        reference = run_exported_multitask_models_batched(exports, row, stack_cache=cache)
        for got, expected in zip(result, reference):
            assert got == pytest.approx(expected, abs=1e-12)
    again = run_exported_multitask_models_across_symbols(exports, rows)
    for got_row, expected_row in zip(again, batched):
        for got, expected in zip(got_row, expected_row):
            assert got == pytest.approx(expected, abs=1e-12)


def test_fewer_than_two_experts_and_no_rows_fall_back_safely():
    rng = np.random.default_rng(4)
    one = [_flat_export(rng), None, None, None]
    rows = _rows(rng, 3)
    result = run_exported_models_across_symbols(one, rows)
    assert [row[1:] for row in result] == [[None, None, None]] * 3 and all(row[0] is not None for row in result)
    assert run_exported_models_across_symbols(one, []) == [] and run_exported_multitask_models_across_symbols([None] * 4, []) == []


def test_the_installed_experts_agree_on_real_width_inputs():
    exports, multitask_exports = [], []
    for name in EXPERTS:
        path = ROOT / "ml" / "expert_models" / name / "model_weights.json"
        mt_path = ROOT / "ml" / "expert_models" / name / "multitask_model.json"
        if not path.exists() or not mt_path.exists():
            pytest.skip("installed expert models are not present")
        exports.append(json.loads(path.read_text(encoding="utf-8")))
        multitask_exports.append(json.loads(mt_path.read_text(encoding="utf-8")))
    width = len(exports[0]["export"]["architecture"][0:1] and np.asarray(exports[0]["export"]["state_dict"][exports[0]["export"]["architecture"][0]["weight_key"]])[0])
    rng = np.random.default_rng(5)
    rows = rng.normal(size=(12, width)).tolist()
    flat = run_exported_models_across_symbols(exports, rows, stack_cache=build_models_batched_cache(exports))
    multitask = run_exported_multitask_models_across_symbols(multitask_exports, rows, stack_cache=build_multitask_models_batched_cache(multitask_exports))
    for row, flat_row, multitask_row in zip(rows, flat, multitask):
        assert flat_row == pytest.approx(run_exported_models_batched(exports, row), abs=1e-12)
        for got, expected in zip(multitask_row, run_exported_multitask_models_batched(multitask_exports, row)):
            assert got == pytest.approx(expected, abs=1e-12)
