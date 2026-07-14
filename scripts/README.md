# scripts

Standalone developer tooling that isn't part of the runtime (`main.py`),
the training pipeline (`train.py` and friends), or the `aq` CLI
(`aq_cli.py`) — things you run by hand, occasionally, while working on the
codebase.

- `profile_inference.py` — cProfile harness for `main.py`'s per-bar
  inference hot path (`inference/exported_model.py`). Loads the real
  exported model weights already on disk under `ml/` (baseline, all 4
  experts, multitask, expert-multitask, sequence — never synthetic/random
  weights, since the point is realistic layer shapes and call volume, not
  realistic predictions), feeds them synthetic-but-correctly-shaped input
  vectors, and runs them in a loop sized to approximate a real backtest's
  call volume. Writes a `pstats` dump and prints the top lines by
  cumulative time.

  ```powershell
  python scripts/profile_inference.py --iterations 10000
  python scripts/profile_inference.py --iterations 10000 --batched   # use the batched expert functions
  ```

  A real `lean backtest .` run is off the table for repeated profiling on
  a normal dev machine (well over an hour wall-clock) — this harness
  exists so the hot path can be profiled in seconds/minutes instead, using
  real weights so the result still means something. See
  `development/Problems.md` for what this found (a Python per-timestep
  loop in the sequence model's causal convolution, and per-expert dispatch
  overhead in the 4-expert loop — both fixed, see `inference/README.md`).

  Output files (`profile_inference_output*.txt`) are gitignored —
  regenerable, not source.
