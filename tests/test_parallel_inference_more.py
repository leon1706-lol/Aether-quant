"""inference/parallel_inference.py's swallowed failures (V6.6.6, #359): a broken export never raises out of the worker."""

from __future__ import annotations

from inference import parallel_inference as pool
from test_exported_model_fallbacks import INPUTS, SEQUENCE, _broken
from test_exported_model import _synthetic_model_export, _synthetic_multitask_model_export, _synthetic_sequence_model_export


def test_a_worker_with_broken_exports_returns_empty_results():
    pool.init_worker({
        "baseline": _broken(_synthetic_model_export()), "sequence": _broken(_synthetic_sequence_model_export()),
        "multitask": _broken(_synthetic_multitask_model_export()), "expert_names": ["bullish"], "experts": {}, "expert_multitask": {},
    })
    result = pool.run_symbol_inference(INPUTS, SEQUENCE, 3)
    assert result["baseline_probability"] is None and result["sequence_result"] is None and result["multitask_result"] is None
    assert pool._padded_sequence([], 3) == []
    pool.init_worker({})
