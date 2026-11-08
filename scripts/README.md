# scripts

Tools run by hand, outside the runtime and the `aq` CLI. Most Lean-reading work is `aq evaluate` now; these are what remains.

## Verification and packaging

| Script | What it does |
|---|---|
| `clean_checkout_test.ps1`, `codespace_clean_checkout_test.sh` | CI's pytest with no gitignored files |
| `codespace_verify.ps1`, `codespace_verify.sh` | Every CI job on a Codespace |
| `wheel_smoke.py` | Imports every shipped module from an installed wheel, and runs each `aq <command> --help` |
| `check_test_count_drift.py` | The README's test count against `pytest --collect-only` |
| `readme_freshness.py` | Every Backtest Statistics block with its date and run; fails on a stale one |
| `feature_parity_audit.py` | Every offline feature has a runtime twin (`--synthetic-only` needs no data) |
| `library_gate.py`, `install_hooks.py` | Every public name is in `aether_quant` or explained (the pre-commit hook and CI's fast-guards run it); the hook installer |
| `check_axioms.py`, `mutation_check.py` | The Lean theorems rest on the standard axioms only; changed comparisons and constants in seven safety modules, and how many the tests catch |
| `field_test_services.py`, `field_services.sh` | Real Redis and Postgres as plain processes: events flow, a tampered row is found, each service stops and restarts under a running pipeline |

## Codespaces

| Script | What it does |
|---|---|
| `codespace_sync.ps1` | Push, pull, status and stop for the training Codespace, hash-verified |
| `codespace_lean_run.ps1`, `codespace_lean_dind.sh` | Lean on a temporary Docker-in-Docker Codespace: create, push, run, pull, delete |
| `codespace_lean_parallel.sh` | Several Lean runs at once, each in its own project copy |
| `codespace_engine_check.sh` | Builds the engine image and checks `GET /api/assets-status` |
| `codespace_prove.sh` | `aq prove --regen-cases` off a small PC |
| `codespace_keepalive.sh`, `codespace_status.sh`, `codespace_start_bg.sh`, `codespace_stop_jobs.sh` | Hold a session open; check, start and stop jobs |
| `codespace_mem*.sh`, `codespace_diag.sh`, `codespace_wf_*.sh` | Memory, diagnostics and walk-forward progress |
| `codespace_retrain_a.sh`, `codespace_retrain_b.sh` | Retrain: dataset and variants, then the winner's full stack |
| `codespace_session_v*.sh`, `codespace_research_v*.sh`, `codespace_*_v*.sh` | One Codespace lifetime for a past phase's chain, kept as its record |

## Data

| Script | What it does |
|---|---|
| `data_append_refresh.py`, `data_append_guard.py` | Append new bars; prove no stored row moved |
| `build_holdout_data.py`, `build_holdout_dataset.py`, `splice_holdout_dataset.py` | Holdout bars and a memory-bounded dataset splice |
| `build_wide_root.py`, `build_wide_info.py`, `build_crypto_wide_root.py`, `build_pre2013_root.py` | Research-only data roots (`build_wide_info.py` needs `AQ_SEC_CONTACT`) |
| `coinbase_listing_dates.py`, `refresh_universe_availability.py` | Listing dates; each asset's window from its zip |
| `fetch_cash_sweep_data.py`, `refresh_lean_interest_rate.py` | T-bill bars; Lean's risk-free file |
| `compare_datasets.py` | Diffs two dataset builds |

## Research cycle and forward records

| Script | What it does |
|---|---|
| `cycle_daily.py`, `cycle_decide.py`, `cycle_retrain.py`, `cycle_lean.py` | Behind `aq cycle` and its workflow |
| `daily_target_weights.py` | The day's weights for a paper run |
| `forward_ledger.py`, `extend_frozen_weights.py` | The forward ledger; a frozen rule's weights on new sessions |
| `freeze_run_config.py`, `vault_record.py` | Freeze a run's config; record a round in AetherVault |
| `build_trial_registry.py` | Every scored variant, for the deflated Sharpe's trial count |
| `build_filing_signals.py` | Earnings-release dates and year-on-year filing similarity from EDGAR, for the selection names (needs `AQ_SEC_CONTACT`, never stored) |
| `k09_decide.py` | k09's weights for one session (a forward observer); RUNBOOK "Research cycle" |
| `v664_write_rounds.py`, `v664_crypto_gbm.py`, `v664_register_observers.py`, `v664_eos_repin.py` | The V6.6.4 chain: the two pre-registered rounds, the crypto GBM trial, the observers, the EOS re-pin |
| `ml_manifest.py` | SHA-256 of the installed models. Diff it across hosts and before a Lean run |

## Analysis and profiling

| Script | What it does |
|---|---|
| `lean_calibration.py`, `predict_sweep_bt1.py` | The simulator against a Lean run, mechanism by mechanism |
| `order_events_audit.py` | Fill rates and slippage from Lean's order events |
| `as_live_levers.py` | One-lever attribution of the as-live book |
| `gate_sweep.py`, `gate_sweep_score_stage.py`, `gate_research.py`, `gate_value_compare.py` | The rank book's gates |
| `overlap_vs_sharpe_analysis.py`, `promotion_gate_null_calibration.py`, `promotion_gate_null_gate_scheme.py` | What selection divergence costs; the promotion gate's null |
| `make_variant_configs.py`, `compare_training_variants.py`, `model_candidate_research.py` | Retrain variants, picked on validation IC |
| `profile_inference.py`, `profile_subsystems.py` (`aq profile`), `profile_main_tick.py` | Hot-path timing |
| `lean_smoke/`, `lean_teardown_smoke/` | Option, futures and teardown code against Lean's sample data |

## Windows and Lean

- `run_lean_cli_windows.py`: used by `aq backtest` so Docker Desktop can read Lean's generated files. Don't invoke it directly.
- `render_lean_credentials.py`: Lean credentials from local secrets.

## Past research chains

`v610_research.py` through `v661_*.py`, and `*_research.py` for sleeves and crypto, are each phase's pre-registered chain, kept so its result can be rerun. Results are in [`development/research_results.md`](../development/research_results.md), and rules are in each `ml/evaluation/<phase>/`. New rounds go through `aq cycle research`.
