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

## Testing

`tests/test_exported_model.py` is the parity net for the numpy
vectorization: hand-computed `_linear`/`_layernorm`/`_sigmoid`/`_softplus`
assertions at tight tolerance, plus full-stack forward-pass tests (both
`run_exported_model()` and `run_exported_multitask_model()`) checked
against independently hand-transcribed reference implementations. See
`development/Changelog.md`'s latency-optimization entry and
`development/v2_architecture.md`'s per-bar hot-path table for the fuller
extraction story.
