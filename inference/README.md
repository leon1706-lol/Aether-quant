# inference

Pure, Lean-free forward-pass interpreter for the JSON-exported neural
network models (`ml/model_weights.json` and each
`ml/expert_models/<name>/model_weights.json`). Extracted out of `main.py`
in the latency-optimization pass (post-V2-23) — this used to be four
private `main.py` methods, run once per symbol per bar, 5x per bar
(baseline model + 4 MoE experts).

- `exported_model.py::run_exported_model(model_export, inputs)` — walks a
  model export's `{"architecture": [...], "state_dict": {...}}` layer list
  (`linear`, `layernorm`, `relu`, `dropout`, `sigmoid`) and returns the
  final scalar output. Private `_linear`/`_layernorm`/`_sigmoid` helpers do
  the per-layer math.
- **Vectorized with numpy.** The original was plain-Python nested loops —
  a genuine CPU bottleneck given how often it runs per bar. Same public
  contract, same numeric behavior (within floating-point tolerance) as the
  pure-Python version it replaced.
- No `AlgorithmImports`/`QCAlgorithm` dependency and no `self.*` state —
  free functions only, matching the rest of the V2 pure-module family
  (`risk/position_sizing.py`, `regime/market_regime.py`,
  `liquidity/market_liquidity.py`). Fully unit-testable without a Lean
  runtime.
- `main.py::_run_model()`/`_run_expert_models()` are now thin call sites:
  `from inference import run_exported_model`, no local reimplementation.

## Multi-task model interpreter (direction + magnitude + volatility)

`exported_model.py::run_exported_multitask_model(model_export, inputs) ->
dict[str, float]` is a second, independent entry point alongside
`run_exported_model()` above — added for the optional multi-task model
(`train.py::AetherNetMultiTask`/`export_multitask_architecture()`,
`train_multitask.py`, `ml/multitask_model.json`) that predicts direction,
next-day return magnitude and next-day volatility jointly from one shared
trunk instead of `run_exported_model()`'s single flat architecture/single
scalar output.

- Consumes a branching `{"trunk": [...], "heads": {"direction": [...],
  "magnitude": [...], "volatility": [...]}}` export (not the flat
  `"architecture"` list `run_exported_model()` expects — the two exports
  are not interchangeable) plus a shared `"state_dict"`. Runs the trunk
  once, then each head independently from a copy of the trunk's output.
- New `_softplus(x)` helper (numerically stable `log1p(exp(-|x|)) +
  max(x, 0)`) guarantees the volatility head's output is always `>= 0`;
  the direction head still ends in the existing `_sigmoid`, and the
  magnitude head has no final activation (raw regression).
- `run_exported_model()` itself is **untouched** — this is a new function
  alongside it, not a generalization, so every existing call site
  (`main.py::_run_model()`/`_run_expert_models()`, `moe/gating.py`,
  `train_gating.py`) carries zero regression risk from this addition.
- Same restriction as `run_exported_model()`: trunks/heads are limited to
  `linear`/`layernorm`/`relu`/`dropout`/`sigmoid`/`softplus` — never
  `gelu`/`silu`/`batchnorm1d`, which this interpreter cannot run (mirrors
  `train_gating.py`'s existing documented restriction for the same
  reason). `train_multitask.py` defaults its trunk to `relu`/`layernorm`
  accordingly.
- `main.py::_run_multitask_model()` is the runtime call site: optional,
  additive, graceful-fallback (missing/malformed export -> `None`,
  same contract as `_load_gating_model()`/`_load_learned_topology_model()`).
  See `moe/README.md` and `risk/README.md` for how `magnitude`/
  `volatility` are threaded downstream.

## Phase 2: sequence-encoder interpreter (causal TCN)

`exported_model.py::run_exported_sequence_multitask_model(model_export,
sequence) -> dict[str, float]` is a third entry point, for the optional
Phase 2 sequence-encoder model (`train.py::AetherNetSequenceMultiTask`/
`export_sequence_multitask_architecture()`, `train_sequence.py`,
`ml/sequence_model.json`) that replaces the flat-MLP trunk with genuine
temporal structure — a causal TCN over a rolling window of bars, instead
of one flat row. Takes a `(window, features)` matrix (`sequence[-1]` is
the current bar) instead of `run_exported_multitask_model()`'s flat
vector; consumes the same branching `{"trunk", "heads"}` shape, but trunk
entries are `"conv1d_causal"`/`"relu"`/`"dropout"` instead of `"linear"`/
`"layernorm"`, and the trunk's most-recent (causal) timestep is pooled
before running the same 3-head shape every multitask export already uses.

Four new primitives back it, each independently cross-checked against
real PyTorch modules during development (not merely hand-computed) to
well under float32 tolerance:

- `_softmax(values, axis=-1)` — numerically stable, arbitrary axis.
- `_layernorm_axis(values, weights, bias, eps, axis=-1)` — generalizes
  `_layernorm()` to normalize along a chosen axis of a multi-dimensional
  array (needed for per-timestep normalization over a `(window,
  features)` sequence — PyTorch's `nn.LayerNorm(features)` applied to
  that shape normalizes each row independently, unlike `_layernorm()`,
  which normalizes a flat vector as one whole). A new function, not a
  modification of `_layernorm()` — `run_exported_model()`/
  `run_exported_multitask_model()` both call the original with no axis
  concept, and changing its signature would be a needless behavior risk
  to code already shipped.
- `_conv1d_causal(sequence, weights, bias, dilation=1)` — causal dilated
  1D convolution matching `torch.nn.Conv1d` under left-zero-padding
  `(kernel_size-1)×dilation` timesteps, so `output[t]` never depends on
  `input[>t]` — verified to `9.1e-8` max abs diff against a real
  `nn.Conv1d`.
- `_multihead_attention(...)` — scaled dot-product multi-head
  self-attention with an optional causal mask — verified to `5.6e-8`
  against real `nn.MultiheadAttention`. **Implemented and tested as
  interpreter infrastructure for a future attention-based sequence model,
  not wired to a trained export in this pass** — the first real Phase 2
  model (`AetherNetSequenceMultiTask`) uses a causal TCN trunk instead,
  chosen specifically because it's simpler to verify bit-for-bit
  end-to-end than a full attention block. See `train.py`'s docstring for
  that scope decision.

`run_exported_model()`/`run_exported_multitask_model()` are completely
untouched by any of this — new functions alongside them, zero regression
risk. `main.py::_run_sequence_model()` is the runtime call site: optional,
additive, graceful-fallback. Its prediction can now optionally blend into
`moe/gating.py::build_gating_decision()`'s `final_probability_up`/
`final_magnitude`/`final_volatility` (`phase_v2.gating_network.sequence_weight`,
default `0.0` — off, byte-identical fallback) — see `moe/README.md`'s
"Phase 2 sequence encoder now optionally blends into the gating decision"
section for why gating was chosen over a direct market-analyzer or
position-sizing wire, and `development/Changelog.md`.

## Infra pass: batched multi-expert inference + vectorized causal conv

`scripts/profile_inference.py` (a new cProfile harness against real
exported weights, no synthetic stand-ins) found two real hot-path costs
this session, closed in the same pass:

- **The 4-expert loop.** `main.py::_run_expert_models()`/
  `_run_expert_multitask_models()` used to call `run_exported_model()`/
  `run_exported_multitask_model()` once per expert (4 separate small
  NumPy dispatch calls, on models confirmed to share byte-identical
  architecture/weight shapes). `run_exported_models_batched()`/
  `run_exported_multitask_models_batched()` stack all present experts'
  weights into one leading batch axis and run ONE
  `_linear_batched()`/`_layernorm_batched()` call per layer instead —
  falling back to the original per-model loop (same graceful
  degradation, one bad expert never takes the others down with it)
  whenever fewer than 2 experts are present or their architectures/
  shapes don't actually match closely enough to batch safely.
- **`_conv1d_causal()`'s per-timestep Python loop** (the sequence
  model's causal TCN) turned out to be the single largest cost in the
  whole hot path — bigger than the expert loop. Rewritten to gather
  every timestep's dilated taps in one fancy-index op and run a single
  batched `einsum` instead of a `for timestep in range(window):` loop
  with its own einsum call each iteration. Same function signature,
  same output (bit-identical, verified against 200 random-parameter
  fuzz trials, not just the existing fixed test cases) — a pure speed
  change, zero behavior change.

Net effect measured by the harness: **-35.2%** total profiled cost
(448.4s → 290.6s across the same 10,000-iteration synthetic workload).
See `development/Problems.md` for the full before/after numbers and why
Numba JIT was evaluated but not added this pass.

## Follow-up: weight-array/stack caching, C++ accelerator, opt-in per-symbol multiprocessing

Re-profiling the batched/vectorized path above found `numpy.asarray()`
conversions were now the single largest remaining cost — every call was
re-converting the SAME static, JSON-loaded model weights from Python
lists into NumPy arrays on every single bar. Full writeup in
`development/Problems.md` #32; summary here:

- **`convert_state_dict_arrays(export)`** converts a model export's
  `state_dict` values from lists to `np.float64` ndarrays once, at
  load time (`main.py`'s ~5 model-load sites) — every downstream
  `np.asarray()` call becomes a no-op. Zero API/behavior change.
- **`build_layer_stacks()`/`BatchedLayerStackCache`/
  `build_models_batched_cache()`** (+ multitask siblings) precompute
  `run_exported_models_batched()`/`run_exported_multitask_models_batched()`'s
  per-layer `weights_stack`/`bias_stack` once too, via an optional
  `stack_cache` parameter (default `None` reproduces the exact original
  behavior). Built once in `main.py::_ensure_ready()`, reused every bar.
- **Measured: 448.4s → 48.4s, -89.2%** total profiled cost on the same
  workload, mean per-symbol-bar latency ~44.8ms → 4.83ms.
- **`cpp_inference_ext/`** (new top-level package, `setup.py` +
  `src/linear_batched.cpp`, builds an importable module named
  `cpp_inference` — deliberately a different folder name from the module
  it builds, since a same-named top-level source directory would shadow
  the installed package as a namespace package whenever the repo root is
  on `sys.path`, which it always is here) — an OPTIONAL C++/pybind11
  accelerator for `_linear_batched()`, the hottest primitive in the
  batched path. `inference/exported_model.py` attempts `import
  cpp_inference` and falls back to the NumPy `einsum` path on any
  import/call failure - same deferred-optional-dependency convention as
  `ib_insync` (`data_pipeline/ib_backfill.py`). Build with `pip install
  -e cpp_inference_ext/` (requires a C++ compiler; never a hard
  dependency of this project). **Measured -16.7% to -40.9%** (two paired
  comparisons, this machine's load varies enough run-to-run that the
  direction is trustworthy but the exact magnitude isn't) — a real but
  modest additional win on top of the weight-caching pass's -89.2%, see
  `development/Problems.md` #32 for the full methodology and two real
  bugs found while verifying it (a namespace-collision from naming the
  source folder the same as the module, and testing against the wrong
  Python environment).
- **`inference/parallel_inference.py`** — opt-in per-symbol
  multiprocessing for `main.py::on_data()`'s Pass 1 inference cluster
  (`phase_v2.inference_parallelism.enabled`, default `false`). See that
  module's own docstring for the full honest tradeoff (per-symbol
  inference is now fast enough, precisely because of the caching fix
  above, that IPC overhead may exceed any parallel win) and
  `development/Problems.md` #32 for why this is genuinely untested
  inside Lean's own runtime (Windows' `ProcessPoolExecutor` uses the
  `spawn` start method, which has never run inside Lean's embedded-
  Python process before this pass). **V4.9 Priority 6**: this break-even
  warning was never actually measured until `scripts/profile_inference.py`
  gained `--parallel` — a real `ProcessPoolExecutor` benchmark of
  `run_symbol_inference()` against an identical sequential baseline (same
  function, only the submission mechanism differs), reported as its own
  p50/p95/p99/max/mean section. On this dev machine's Windows `spawn`
  start method at real universe scale, the pool measured **dramatically
  slower** than sequential (single-digit-ms sequential bars vs. multi-
  second pooled bars) — direct, measured confirmation of the module's own
  long-standing suspicion, not just a suspicion anymore.

## V4.9 Priority 1: sequence-encoder symbol-batching

`run_exported_models_batched()`/`run_exported_multitask_models_batched()`
above batch N *different models* (the 4 experts) sharing ONE input. The
sequence encoder is the opposite shape: there is exactly ONE trained
model, called once per symbol per bar with each symbol's own different
`(window, features)` rolling-buffer input — profiling
(`development/Problems.md` #21) found this call alone was ~48-58% of
total profiled inference time, the single largest remaining cost after
the weight-caching/batching pass above, entirely from Python/NumPy
per-call dispatch overhead repeated once per symbol, not FLOPs (the same
"call-count is what matters" finding that motivated the expert-batching
work).

- **`_conv1d_causal_batched()`** — batched sibling of `_conv1d_causal()`:
  same left-pad-then-gather-then-einsum construction, with a leading `N`
  (symbols) axis carried through the padding/gather and the final einsum.
- **`_linear_shared_batched()`** — batched sibling of `_linear()` for ONE
  shared weight matrix applied to `N` stacked input rows. Deliberately
  distinct from `_linear_batched()` above, which is the opposite shape
  (`N` different models' own weights over one shared input) —
  `_layernorm_axis()` (already axis-aware, Phase 2) is reused as-is for
  the batched layernorm case, no new primitive needed there.
- **`run_exported_sequence_multitask_model_batched(model_export,
  sequences)`** — stacks every present symbol's sequence into one `(N,
  window, features)` batch, runs the causal-conv trunk once, pools each
  symbol's own most-recent timestep, then runs each head once across all
  `N` pooled rows. `None` entries (a symbol whose rolling buffer hasn't
  warmed up yet) are preserved at the same index in the output. Falls
  back to calling the unbatched function once per present symbol — never
  raises — whenever fewer than 2 sequences are present or the batched
  computation itself fails for any reason (e.g. symbols with
  inconsistent window lengths, which `np.asarray()` on a ragged list
  would itself raise on).
- `main.py`'s `on_data()` Phase 1b gained a new branch (gated by
  `phase_v2.sequence_model.batched_across_symbols_enabled`, default
  `false`) that batches the sequence-model call across every pending
  symbol in one bar, only when `self._inference_pool is None` — symbol-
  batching and multiprocess parallelism (above) are alternative
  optimizations this pass, not combined.
- **C++ acceleration deliberately deferred, not part of this pass's first
  cut** — ship the pure-NumPy batched path, re-profile with
  `scripts/profile_inference.py`'s extended `--batched` (which now also
  runs an additive sequence-encoder batched-vs-unbatched comparison
  section), and only then decide whether a `conv1d_causal_batched` C++
  function earns a place in the existing `cpp_inference_ext/` extension
  (same module, new source file — never a second extension folder).

Parity tests in `tests/test_exported_model.py` mirror the exact existing
precedent for the flat/multitask batched functions (matches-individual-
calls, preserves-`None`-at-missing-indices, falls-back-on-ragged-input-
without-crashing), plus hand-computed small-example tests for the two new
pure math primitives.

## Testing

`tests/test_exported_model.py` is the parity net for the numpy
vectorization: hand-computed `_linear`/`_layernorm`/`_sigmoid`/`_softplus`
assertions at tight tolerance, plus full-stack forward-pass tests
(`run_exported_model()`, `run_exported_multitask_model()`, and
`run_exported_sequence_multitask_model()`) checked against independently
hand-transcribed reference implementations, plus (this pass) batched-vs-
individual parity tests for `run_exported_models_batched()`/
`run_exported_multitask_models_batched()` using both synthetic
multi-model fixtures and the real `ml/expert_models/*` exports. See
`development/Changelog.md`'s latency-optimization entry and
`development/v2_architecture.md`'s per-bar hot-path table for the fuller
extraction story.
