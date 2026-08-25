# inference

Pure, Lean-free forward-pass interpreter for the JSON-exported neural
network models (`ml/model_weights.json` and each
`ml/expert_models/<name>/model_weights.json`). No `AlgorithmImports`/
`QCAlgorithm` dependency and no `self.*` state — free functions only,
fully unit-testable without a Lean runtime. `main.py`'s `_run_model()`/
`_run_expert_models()`/`_run_multitask_model()`/`_run_sequence_model()` are
thin call sites over this package.

## Modules

- `exported_model.py` — the interpreter core (all entry points below).
- `parallel_inference.py` — opt-in per-symbol multiprocessing for
  `main.py::on_data()`'s Pass 1 inference cluster
  (`phase_v2.inference_parallelism.enabled`, default `false`). Measured
  dramatically slower than sequential at real universe scale on Windows'
  `spawn` start method (see `aq profile --parallel`); kept as an opt-in
  for hosts where that tradeoff differs.
- `strategy_selector_inference.py` — torch-free scoring for the learned
  options **strategy-selector model** (`ml/strategy_selector_model.json`
  once `train_strategy_selector.py` has produced one):
  `build_strategy_selector_features()` assembles the per-symbol feature
  row and `score_strategies()` ranks the 43 registered option strategies.
  Consumed by `main.py` and surfaced on the webui's Options & Strategy
  page; realistically dormant until real option positions trade (see
  `train_strategy_selector.py`'s module docstring).

## Entry points (exported_model.py)

- `run_exported_model(model_export, inputs)` — walks a flat
  `{"architecture": [...], "state_dict": {...}}` layer list (`linear`,
  `layernorm`, `relu`, `dropout`, `sigmoid`) and returns one scalar.
  Fully vectorized numpy.
- `run_exported_multitask_model(model_export, inputs) -> dict[str, float]`
  — for the joint direction+magnitude+volatility model
  (`ml/multitask_model.json`). Consumes the branching
  `{"trunk": [...], "heads": {"direction": [...], "magnitude": [...],
  "volatility": [...]}}` export (NOT interchangeable with the flat
  export); runs the trunk once, each head independently. `_softplus`
  guarantees the volatility head is `>= 0`; the direction head ends in
  `_sigmoid`; magnitude is raw regression.
- `run_exported_sequence_multitask_model(model_export, sequence) ->
  dict[str, float]` — the causal-TCN sequence encoder
  (`ml/sequence_model.json`). Takes a `(window, features)` matrix
  (`sequence[-1]` = current bar); trunk layers are
  `conv1d_causal`/`relu`/`dropout`, pooled at the most-recent (causal)
  timestep before the same 3-head shape. Backed by `_softmax`,
  `_layernorm_axis`, `_conv1d_causal` and `_multihead_attention` — each
  cross-checked against the real PyTorch module to well under float32
  tolerance (`_multihead_attention` is infrastructure for a future
  attention-based model, not wired to a trained export).

All trunks/heads are limited to `linear`/`layernorm`/`relu`/`dropout`/
`sigmoid`/`softplus` (+`conv1d_causal` for sequence models) — never
`gelu`/`silu`/`batchnorm1d`, which this interpreter cannot run; the
trainers default their architectures accordingly.

## Batched inference & caching (the production path)

`main.py` never calls the single-model entry points in loops; it uses the
batched, cached forms built once in `_ensure_ready()`:

- `run_exported_models_batched()` / `run_exported_multitask_models_batched()`
  — stack the 4 experts' weights into one leading batch axis and run one
  `_linear_batched()`/`_layernorm_batched()` call per layer. Falls back to
  the per-model loop (one bad expert never takes the others down) when
  fewer than 2 experts are present or shapes don't match.
- `run_exported_sequence_multitask_model_batched(model_export, sequences)`
  — the opposite batching shape: ONE shared sequence model across `N`
  symbols' `(window, features)` inputs via `_conv1d_causal_batched()` and
  `_linear_shared_batched()`. `None` entries (unwarmed symbol buffers)
  are preserved at their index; falls back to per-symbol calls on ragged
  input. Gated by
  `phase_v2.sequence_model.batched_across_symbols_enabled` (default
  `false`), and only when multiprocess parallelism is off — the two are
  alternatives, not combinable.
- `convert_state_dict_arrays(export)` — converts `state_dict` lists to
  numpy arrays once at load time so per-bar `np.asarray()` calls become
  no-ops. `build_layer_stacks()`/`BatchedLayerStackCache`/
  `build_models_batched_cache()` (+ multitask siblings) precompute the
  per-layer weight/bias stacks via an optional `stack_cache` parameter
  (default `None` = original behavior).
- **`cpp_inference_ext/`** — optional C++/pybind11 accelerator for
  `_linear_batched()` (builds an importable module named `cpp_inference`;
  the folder name deliberately differs from the module name to avoid
  namespace-package shadowing). `exported_model.py` attempts the import
  and falls back to the numpy path on any failure. Build with
  `pip install -e cpp_inference_ext/` (needs a C++ compiler; never a hard
  dependency).

The cumulative effect of batching + caching (+ the optional C++ path) was
a measured ~-89% profiled hot-path cost reduction; full before/after
methodology in `development/Problems.md` #31/#32, harness in
`scripts/profile_inference.py` (`aq profile`).

## Testing

`tests/test_exported_model.py` is the parity net: hand-computed
`_linear`/`_layernorm`/`_sigmoid`/`_softplus` assertions at tight
tolerance, full-stack forward-pass tests against independently
hand-transcribed reference implementations, and batched-vs-individual
parity tests using both synthetic multi-model fixtures and the real
`ml/expert_models/*` exports. See `development/architecture.md`'s per-bar
hot-path table for where this package sits in the latency budget.
