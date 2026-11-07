# inference

A pure, Lean-free forward pass over the JSON-exported networks. Free functions, no `self`, fully testable. `main.py` is a thin call site.

**Modules**

- **`exported_model.py`:** the interpreter.
- **`parallel_inference.py`:** opt-in multiprocessing (`phase_v2.inference_parallelism.enabled`, off). Slower than sequential at real scale on Windows; compare with `aq profile --parallel`.
- **`strategy_selector_inference.py`:** torch-free scoring of the registered option strategies. Dormant until options trade.

**Entry points**

- **`run_exported_model(export, inputs)`:** a flat layer list, returning one scalar.
- **`run_exported_multitask_model(export, inputs)`:** a trunk and named heads. Softplus keeps volatility non-negative.
- **`run_exported_sequence_multitask_model(export, sequence)`:** the causal TCN over a `(window, features)` matrix, each primitive cross-checked against PyTorch.
- **`average_head_outputs`:** the one seed-ensemble rule: the mean of each head's raw output.

**The hot path** (built once in `_ensure_ready()`)

- **`run_exported_models_batched()`, `run_exported_multitask_models_batched()`:** stack the experts' weights on one batch axis, falling back to a per-model loop so one bad expert can't take the others down.
- **`run_exported_sequence_multitask_model_batched()`:** one model across N symbols (`phase_v2.sequence_model.batched_across_symbols_enabled`, off, and not combinable with multiprocessing).
- **`convert_state_dict_arrays()`, `build_layer_stacks()`:** load-time caches.
- **`cpp_inference_ext/`:** an optional accelerator.

Batching and caching cut the profiled hot path by about 89% (#31, #32; `aq profile`).

**Tests:** `tests/test_exported_model.py` compares hand-computed layers, full stacks against independent references, and batched against individual results.
