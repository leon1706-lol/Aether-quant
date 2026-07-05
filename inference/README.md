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

## Testing

`tests/test_exported_model.py` is the parity net for the numpy
vectorization: hand-computed `_linear`/`_layernorm`/`_sigmoid` assertions
at tight tolerance, plus a full-stack forward pass checked against an
independently hand-transcribed reference implementation. See
`development/Changelog.md`'s latency-optimization entry and
`development/v2_architecture.md`'s per-bar hot-path table for the fuller
extraction story.
