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

- `codespace_sync.ps1` (V5.6.0) — push/pull/status/stop for the training Codespace over `ssh`/`scp`
  with the `gh codespace ssh --config` route (`gh codespace cp` upload is broken). One tarball each
  way, remote commands single-quoted, sha256 of key artifacts verified on both ends.
- `codespace_retrain_a.sh` / `codespace_retrain_b.sh` — the V5.6.0 retrain on the Codespace: stage A
  regenerates the dataset and trains the multitask control (2 seeds) plus four single-change variants;
  stage B installs the winner and trains sequence, gating, RL sizing (penalty sweep) and the resumable
  walk-forward.
- `as_live_levers.py` - one-lever-at-a-time attribution of the as-live book (`--split`, `--only`); writes
  `ml/evaluation/as_live_levers[_split].json`. V5.7.0: scoring is cached per split and model fingerprint
  (`ml/evaluation/cache/`), the rolling-IC state is computed once per score set (seconds per variant), and the
  `AsLiveHarness` class is reusable.
- `lean_calibration.py` (V6.0.0, rule R-CAL) — the offline simulator against a Lean run's main-book component, rung by rung
  (cadence, next-open fills, IB floor, live's resize / cooldown / trailing stop, topology sizing, replayed gate decisions);
  `--predict` writes the calibrated prediction before a run -> `ml/evaluation/v600/calibration.json`, `bt1_prediction.json`.
- `book_variant_research.py` (V6.0.0, rule R-BOOK), `crypto_fee_research.py` (R-CRYPTO), `forex_keep_or_drop.py` (R-FX6) —
  the three pre-registered decisions of V6.0.0 on the calibrated simulator (heavy: run them on the Codespace through
  `codespace_research_v600.sh`; `codespace_calibration_v600.sh` and `codespace_predict_v600.sh` do the same for R-CAL).
- `v610_research.py` (V6.1.0) — the pre-registered rule chain R-MODEL9 -> R-HEAD2 -> R-BOOK2 -> R-LEGACY -> R-GATE on the V6.1.0
- `v620_research.py` (V6.2.0) — the rule chain R-DEDUPE -> R-STAGGER -> R-MODEL10 on the V6.1 scoring (every phase, both splits), with an informational with / without T-bill sweep report; `codespace_session_v620.sh` (retrain: label noise, the train-chosen feature subset) and `codespace_research_v620.sh` (yardstick, candidates, chain) run it on the Codespace. Also V6.2.0: `select_feature_subset.py` (train split only), `fetch_cash_sweep_data.py` (BIL zip), `refresh_lean_interest_rate.py` (Lean's risk-free file from FRED DPCREDIT), `predict_sweep_bt1.py` (a run with the sweep predicted from a run without it), `clean_checkout_test.ps1` (CI's checkout locally), `codespace_keepalive.sh`.
  simulator: every variant is one change, scored on **every rebalance phase** (median Sharpe, share of phases that beat the
  incumbent) over both splits, then reported once on the holdout; resumable -> `ml/evaluation/v610/research.json`.
  `lean_calibration.py --rcal2` (R-CAL2) scores the `v610` rung against the V6 BT2 stretches and the V5.8.0 BT2 stretch;
  `build_legacy_probability.py` writes the legacy signal's `final_probability_up` per row; `model_candidate_research.py` scores
  every retrained candidate, seed ensembles included (rank IC, HAC t, per-head); `prepare_v610_candidates.py` turns that into
  scoreable candidate dirs, R-HEAD per candidate and the inference-latency ratio; `compare_datasets.py` diffs two dataset builds.
- `v630_research.py` (V6.3.0) — the pre-registered chain R-KILL (kill-switch window / release band, lock-path stability under
  0.5 bp noise) -> R-STAGGER2 (S2's second look, interquartile range and worst phase in place of the max-min range) -> R-GATE3
  (only on R-CAL3 branch A); writes `ml/evaluation/v630/research.json` and `adopted_changes.json`. `lean_calibration.py --rcal3`
  is R-CAL2's clauses on V6.2.0's BT2. `codespace_session_v630.sh` runs R-CAL3, the chain, applies the adopted changes and
  recomputes every offline README block in ONE Codespace lifetime. `build_trial_registry.py` collects every scored variant
  into `ml/evaluation/trial_registry.json` (the deflated Sharpe's N and Sharpe variance).
- `codespace_lean_run.ps1` + `codespace_lean_dind.sh` (V6.3.0) — Lean backtests on a temporary Docker-in-Docker Codespace:
  create, push, run frozen configs in order, poll, pull, delete (`development/infrastructure.md` "Lean on a DinD Codespace").
  `codespace_engine_check.sh` builds the engine image there and checks `GET /api/assets-status`;
  `codespace_clean_checkout_test.sh` runs CI's pytest on a tarball of exactly the files a commit would hold (the PC cannot
  hold the suite; `clean_checkout_test.ps1` is the local equivalent). `readme_freshness.py` lists every Backtest Statistics
  block with its date and source run and fails on a stale one (`--since`, `--allow`).
- `codespace_session_v610.sh` (S1: datasets with Lean's forex holidays, multitask x5 / sequence x3 for the control and three
  variants, candidate IC, the suite), `codespace_research_v610.sh` (S2: legacy probability, R-CAL2, candidates, the rule chain)
  and `codespace_readme_v610.sh` (S3: the offline blocks of the README performance section): resumable (`RESUME=1`).
  The Codespace stops on its idle timeout while a job runs: keep one `gh codespace ssh` session open for the whole job.
- `profile_main_tick.py` (V6.0.0) — times the real `main.py` per-tick feature path outside Lean (`--repeat`, `--scalar-beta`
  A/B switch, `--cprofile`).
- `refresh_universe_availability.py` (V6.0.0) — sets each asset's `available_from/available_to` from its zip.
- `lean_teardown_smoke/` (V6.0.0) — the 15-line Lean algorithm of Problems.md #104; `lean backtest scripts/lean_teardown_smoke --image <image>`.
- `codespace_session_v600.sh` (V6.0.0) — the resumable S1 session: four-split dataset with the active scaler, the 60-day variant, the test suite.
- `gate_research.py` (V5.7.0) — every gate / lever decision of todo.md findings 1-6 on BOTH splits with the full
  as-live simulator, plus the R-GATE verdict per experiment -> `ml/evaluation/v570_gate_research.json`.
- `build_holdout_data.py` / `build_holdout_dataset.py` (V5.7.0) — Yahoo bars for every universe asset into a staging
  root (`--root`, default `data_v6_staging`; audited before it is copied over `data/`), then a dataset scaled with the
  ACTIVE scaler (never refit). The dataset build runs on the Codespace. `data_holdout/` was deleted in V6.0.0: the
  holdout is `phase1.windows.holdout` inside `data/` since V5.8.0.
- `make_variant_configs.py` / `compare_training_variants.py` — write the per-variant configs and pick
  the winner on VALIDATION IC against the control's seed spread (never the backtest split).
- `overlap_vs_sharpe_analysis.py` — pairs each reconciled book-history run with the Lean Sharpe of the
  matching backtest (ordinal; runs sharing a window stay separate points since V5.6.0).

## V5.8.0 additions

- Research (each writes `ml/evaluation/*.json` and refreshes the README research block): `class_sleeve_research.py` (forex / bond sleeves, rule R-SLEEVE), `rl_sizing_research.py`, `topology_sizing_research.py` (rule R-TOPO), `crypto_graduation_research.py`, `gate_research.py`, `holdout_report.py` (the one-look holdout), `active_baseline.py` (the shipped models on the new splits, for R-MODEL8).
- `coinbase_listing_dates.py` — derives each crypto pair's listing date and suspensions from Coinbase's own daily candles into `data/reference/crypto_listing_dates.json`.
- `ml_manifest.py` — SHA-256 manifest of the installed model files; diff the local and Codespace output before trusting an evaluation that ran on the other side, and before a Lean run to prove the models are frozen.
- `codespace_*.sh` — the Codespace helpers (`codespace_retrain_v580.sh` stage A/B retrain, `codespace_start_bg.sh` / `codespace_stop_jobs.sh` relaunch and stop resumable jobs, `codespace_final_session.sh` the last code push + test run, `codespace_status.sh` / `codespace_wf_progress.sh` progress). Always push with `-CodeOnly` after a retrain: a full push overwrites the remote `ml/`.
