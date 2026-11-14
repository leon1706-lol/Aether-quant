# Reproducibility

How to reproduce every number in the README. The tables there are generated, so this page lists the commands, not the values.

## Environment

- **Python:** <!--fact:python.ci-->3.11<!--/fact--> on CI; the dev PC also runs newer versions.
- **OS:** Windows (dev), Ubuntu (CI).
- **Packages:** `requirements/requirements.txt`.

## Backtest Statistics

From a finished Lean run folder alone, with no model or dataset:

```powershell
aq evaluate --lean-report --backtest-dir backtests/<pinned run>
```

The pinned run is <!--fact:lean.pin_run-->2026-11-07_17-54-01<!--/fact-->.

- **Frozen config:** `ml/evaluation/run_configs/<pinned run>.json`.
- **Weights:** `ml/target_weights.csv`, pinned by `phase_v2.target_weights.weights_sha256`.
- **Long-window row:** `aq evaluate --alpha-proof --backtest-dir backtests/2026-11-07_17-56-48`, named as `long_run` in `ml/evaluation/readme_lean_run.json`.

To rerun the Lean engine itself, see [`development/infrastructure.md`](development/infrastructure.md) ("Lean on a DinD Codespace"), or `aq backtest` on a machine with Docker.

## Data

```powershell
python scripts/data_append_guard.py snapshot --out before.json   # before a refresh
python scripts/data_append_refresh.py --apply                    # append only
python scripts/data_append_guard.py verify --before before.json  # no stored row may change
python train.py --dataset-only                                   # ml/datasets/full_dataset.csv
```

## Models

```powershell
aq train                     # baseline, experts, gating, multitask, sequence
aq train --walk-forward      # out-of-sample windows
aq cycle retrain --host local --procedure k06   # a research-cycle retrain (14 GB of RAM)
```

## Research results

[`development/research_results.md`](development/research_results.md) is generated from `ml/evaluation/`:

```powershell
aq evaluate --all                                     # rank book, capacity, stress, benchmarks, Monte Carlo, classification
aq evaluate --rank-book --as-live --split validation  # the live path's decisions
aq evaluate --rank-book --as-live --split backtest
```

Each research round's rules, scores and verdict stay in `ml/evaluation/<phase>/`, and its hash is in the trial ledger. `aq cycle research` reruns a round.

## What each number means

- **Lean numbers** are the ground truth for a backtest, and include fees, slippage and fill timing.
- **Offline numbers** come from the torch-free simulators, and are estimates, not substitutes.
- **Forward numbers** (`aq cycle status`) are the only ones nothing has been fitted on.
