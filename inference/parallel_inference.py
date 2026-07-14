"""Opt-in per-symbol multiprocessing for main.py::on_data()'s Pass 1 heavy
inference (baseline + experts + multitask + expert-multitask + sequence
model calls) - see main.py's phase_v2.inference_parallelism.enabled flag
(default off).

Honest framing, not oversold: per-symbol inference is now fast (~4.8ms
mean per symbol, post the weight-caching/batching pass - see
development/Problems.md) precisely because the previous, much larger cost
(Python/NumPy per-call dispatch overhead, a Python loop inside
_conv1d_causal) got fixed WITHOUT multiprocessing. IPC/pickling overhead
for submitting work to and receiving results from a separate process may
easily exceed any parallel win at this point, for a universe this size
(~30 symbols). Shipped default-off; the real judge is a real `lean
backtest .` run (Windows' ProcessPoolExecutor uses the `spawn` start
method, which re-bootstraps a new interpreter per worker - untested
territory inside Lean's own embedded-Python runtime, which is not a
standard `python.exe` process tree main.py was ever designed to be
spawned from. main.py's own pool-creation code treats ANY failure here,
including a hang on first use, as a signal to permanently fall back to
the always-correct sequential path for the rest of the run.)

Workers hold their OWN copy of every model export (loaded once via
ProcessPoolExecutor's `initializer`, not re-sent on every call - sending
model weights, now real NumPy arrays post the weight-caching pass,
through IPC on every single bar would defeat the whole purpose). Only
small per-symbol data (a flat feature vector, an optional sequence-window
history) crosses the process boundary per call. Never a bound method on
`self` (the QCAlgorithm instance holds Lean/.NET interop objects that are
almost certainly unpicklable) - this module has zero Lean/main.py
dependency, by design.
"""

from __future__ import annotations

# Populated once per worker process by init_worker() below - never sent
# across the process boundary again after that, and never touched by the
# main process itself.
_worker_model_exports: dict | None = None


def init_worker(model_exports: dict) -> None:
    """ProcessPoolExecutor `initializer` - runs once when each worker
    process starts, storing this run's model exports (baseline, experts,
    multitask, expert-multitask, sequence, plus their precomputed
    BatchedLayerStackCache/BatchedMultitaskLayerStackCache instances) in
    that worker's own global state."""
    global _worker_model_exports
    _worker_model_exports = model_exports


def _padded_sequence(history: list[list[float]], window_size: int) -> list[list[float]]:
    """Same left-zero-padding logic main.py::_run_sequence_model() already
    applies - duplicated here (a handful of lines) rather than shared,
    since this module must have zero main.py/Lean dependency and the
    logic is small enough that a shared-helper extraction isn't worth the
    added indirection."""
    if not history:
        return []
    input_width = len(history[0])
    padding_needed = window_size - len(history)
    return [[0.0] * input_width for _ in range(max(0, padding_needed))] + list(history)


def run_symbol_inference(
    inputs: list[float],
    sequence_history: list[list[float]] | None,
    sequence_window_size: int,
) -> dict:
    """The actual per-symbol work submitted to the pool - reads this
    worker's own _worker_model_exports (set once by init_worker()) and
    runs the exact same 5-call cluster main.py::on_data()'s Pass 1 always
    ran inline: baseline, sequence (if history given), experts (batched
    when possible), multitask, expert-multitask (batched when possible).

    Returns a plain dict of plain values - always picklable back to the
    main process, matching the same graceful-degradation contract
    (missing/failed pieces -> None/empty, never a raised exception
    propagating out) every other inference call site in this codebase
    already has."""
    from inference.exported_model import (
        run_exported_model,
        run_exported_multitask_model,
        run_exported_multitask_models_batched,
        run_exported_models_batched,
        run_exported_sequence_multitask_model,
    )

    exports = _worker_model_exports or {}
    expert_names: list[str] = exports.get("expert_names", [])

    result: dict = {
        "baseline_probability": None,
        "sequence_result": None,
        "expert_probabilities": dict.fromkeys(expert_names),
        "multitask_result": None,
        "expert_multitask_magnitudes": dict.fromkeys(expert_names),
        "expert_multitask_volatilities": dict.fromkeys(expert_names),
    }

    baseline = exports.get("baseline")
    if baseline:
        try:
            result["baseline_probability"] = run_exported_model(baseline, inputs)
        except Exception:
            pass

    sequence = exports.get("sequence")
    if sequence and sequence_history:
        try:
            padded = _padded_sequence(sequence_history, sequence_window_size)
            result["sequence_result"] = run_exported_sequence_multitask_model(sequence, padded)
        except Exception:
            pass

    expert_exports = exports.get("experts", {})
    expert_list = [expert_exports.get(name) for name in expert_names]
    if any(expert_list):
        expert_results = run_exported_models_batched(expert_list, inputs, stack_cache=exports.get("expert_stack_cache"))
        result["expert_probabilities"] = dict(zip(expert_names, expert_results))

    multitask = exports.get("multitask")
    if multitask:
        try:
            result["multitask_result"] = run_exported_multitask_model(multitask, inputs)
        except Exception:
            pass

    expert_multitask_exports = exports.get("expert_multitask", {})
    expert_multitask_list = [expert_multitask_exports.get(name) for name in expert_names]
    if any(expert_multitask_list):
        emt_results = run_exported_multitask_models_batched(
            expert_multitask_list, inputs, stack_cache=exports.get("expert_multitask_stack_cache")
        )
        for name, one_result in zip(expert_names, emt_results):
            result["expert_multitask_magnitudes"][name] = one_result.get("magnitude") if one_result else None
            result["expert_multitask_volatilities"][name] = one_result.get("volatility") if one_result else None

    return result
