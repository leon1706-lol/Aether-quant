# scripts

Standalone developer tooling that isn't part of the runtime (`main.py`),
the training pipeline (`train.py` and friends), or the `aq` CLI
(`aq_cli.py`) — things you run by hand, occasionally, while working on the
codebase.

- `run_lean_cli_windows.py` — Windows-only compatibility launcher used
  internally by `aq backtest`. It patches Lean CLI's temporary-directory
  creation before the CLI imports so Docker Desktop can read Lean's generated
  startup/config files on affected Windows hosts. Invoke `aq backtest`, not
  this script directly.

- `profile_inference.py` — cProfile + wall-clock harness for `main.py`'s
  per-bar inference hot path (`inference/exported_model.py`), also
  exposed as `aq profile` (see the main README's CLI Reference). Loads
  the real exported model weights already on disk under `ml/` (never
  synthetic weights — realistic layer shapes and call volume), feeds
  correctly-shaped synthetic inputs generated outside the profiled region,
  and writes a `pstats` dump plus independent wall-clock tail-latency
  percentiles.

  ```powershell
  aq profile --iterations 10000
  aq profile --iterations 10000 --batched   # batched + stack-cached expert path + sequence-batching comparison
  aq profile --parallel --pool-workers 4    # ProcessPoolExecutor IPC-overhead benchmark vs. sequential
  ```

  Output files (`profile_inference_output*.txt`) are gitignored —
  regenerable, not source. See `development/Problems.md` #31/#32 for what
  profiling found and fixed, and `inference/README.md` for the writeup.

- `profile_subsystems.py` — wall-clock breakdown of every per-bar
  subsystem (features, inference, topology, regime, liquidity, analyzer)
  against the real exported artifacts; the broader sibling of
  `profile_inference.py`. Run via `aq profile --subsystems` if exposed, or
  directly: `python scripts/profile_subsystems.py`.

- `feature_parity_audit.py` (V5.3.6) — audits that every feature computed
  offline by `train.py` has a runtime twin in `main.py`'s feature build
  (the train/inference parity contract), reporting per-feature match
  status.

- `gate_sweep.py` / `gate_sweep_score_stage.py` (V5.3.6) — sweep the
  rank-book engagement gates (`min_rank_confidence_spread` x
  `hysteresis_rank_margin` grids) over the dataset, then score the swept
  configurations; writes `ml/evaluation/gate_sweep_results.json` +
  `gate_sweep_scored.csv`.

- `overlap_vs_sharpe_analysis.py` (V5.3.6) — correlates live-vs-offline
  book-selection overlap fractions against realized offline net Sharpe,
  quantifying how much selection divergence costs.

- `promotion_gate_null_calibration.py` (V5.3.6) /
  `promotion_gate_null_gate_scheme.py` (V5.3.7) — calibrate the promotion
  gate's null distribution (shuffle-based) and evaluate alternative
  gate schemes against it, so promotion thresholds are derived from real
  data instead of guessed.

- `order_events_audit.py` (V5.3.1) — parses real Lean `order-events.json`
  exports into fill-rate/slippage/casing statistics; the evidence base
  behind the limit-order work in `execution/README.md`.

- `render_lean_credentials.py` — renders Lean's credential
  configuration from local env/secret state (used by the `aq backtest`
  flow on hosts where Lean needs explicit credentials).

- `wheel_smoke.py` (V5.5.0) — smoke test of an **installed wheel**, run from
  outside the checkout (CI `wheel-smoke`): imports every module of every shipped
  package (a missing first-party module is a packaging bug; a missing
  third-party extra is only noted) and runs every `aq <subcommand> --help` in a
  fresh interpreter. `pip install -e .` hides this class entirely; the first run
  found `risk_controls` missing from `py-modules`.

- `check_test_count_drift.py` (V5.5.0) — compares the README test-count badge
  with `pytest --collect-only`; warn-only by default (`::warning::`), `--strict`
  exits 1. The badge is only refreshed by an unfiltered local `aq test`.

- `feature_parity_audit.py --synthetic-only` (V5.5.0) — runs just check 1
  (replicas vs `train.py` on synthetic data), needs no dataset files and exits
  non-zero when the check did not actually run. It had been silently dead (a
  swallowed `ValueError`/`TypeError` reported as `SKIPPED`) until this round.
