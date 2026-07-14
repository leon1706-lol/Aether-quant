# scripts

Standalone developer tooling that isn't part of the runtime (`main.py`),
the training pipeline (`train.py` and friends), or the `aq` CLI
(`aq_cli.py`) — things you run by hand, occasionally, while working on the
codebase.

- `profile_inference.py` — cProfile + wall-clock harness for `main.py`'s
  per-bar inference hot path (`inference/exported_model.py`), also
  exposed as `aq profile` (see the main README's CLI Reference). Loads
  the real exported model weights already on disk under `ml/` (baseline,
  all 4 experts, multitask, expert-multitask, sequence — never
  synthetic/random weights, since the point is realistic layer shapes and
  call volume, not realistic predictions) and applies the same
  `convert_state_dict_arrays()` load-time optimization `main.py` uses,
  feeds them pre-generated (outside the profiled region, so measurement
  overhead never gets counted as inference cost) synthetic-but-correctly-
  shaped input vectors, and runs them in a loop sized to approximate a
  real backtest's call volume. Writes a `pstats` dump AND independent
  wall-clock tail-latency percentiles (p50/p95/p99/max/mean) - the two
  together are more trustworthy than either alone (cProfile's own
  instrumentation adds overhead; wall-clock alone says nothing about
  where the time goes).

  ```powershell
  aq profile --iterations 10000
  aq profile --iterations 10000 --batched   # use the batched + precomputed-stack-cached expert path
  ```

  A real `lean backtest .` run is off the table for repeated profiling on
  a normal dev machine (well over an hour wall-clock) — this harness
  exists so the hot path can be profiled in seconds/minutes instead, using
  real weights so the result still means something. See
  `development/Problems.md` #31/#32 for what this found and fixed across
  two passes: a Python per-timestep loop in the sequence model's causal
  convolution, per-expert dispatch overhead in the 4-expert loop, and (the
  biggest single win) redundant weight-array/stack rebuilding on every
  single call — a combined -89.2% reduction in profiled cost. See
  `inference/README.md` for the full technical writeup.

  Output files (`profile_inference_output*.txt`) are gitignored —
  regenerable, not source.
