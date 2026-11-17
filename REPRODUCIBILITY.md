# Reproducibility

How to reproduce every number in the README. The tables there are generated, so this page lists the commands, not the values.

## What each number means

- **Lean numbers** are the ground truth for a backtest. They include fees, slippage and fill timing.
- **Offline numbers** come from the torch-free simulators. They are estimates, not substitutes.
- **Forward numbers** (`aq cycle status`) are the only ones nothing has been fitted on.

## Environment

- **Python:** <!--fact:python.ci-->3.11<!--/fact--> on CI. The dev PC runs 3.14, and the Codespaces run pandas 3.
- **OS:** Windows (dev), Ubuntu (CI).
- **Packages:** CI and the images install from the hash-locked files in `requirements/lock/`, one per job, for example `pip install --require-hashes -r requirements/lock/ci.txt`. [`requirements/README.md`](requirements/README.md) lists the profiles.

## Backtest Statistics

From a finished Lean run folder alone, with no model or dataset:

```powershell
aq evaluate --lean-report --backtest-dir backtests/<pinned run>
```

The pinned run is <!--fact:lean.pin_run-->2026-11-16_16-25-28<!--/fact-->.

- **Frozen config:** `ml/evaluation/run_configs/<pinned run>.json`.
- **Weights:** `ml/target_weights.csv`, pinned by `phase_v2.target_weights.weights_sha256`.
- **Long-window row:** `aq evaluate --alpha-proof --backtest-dir backtests/2026-11-16_19-39-10`, named as `long_run` in `ml/evaluation/readme_lean_run.json`.

To rerun the Lean engine itself, use `aq backtest` on a machine with Docker, or see [`development/infrastructure.md`](development/infrastructure.md) ("Lean on a DinD Codespace").

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

- **Where a round lives:** its rules, scores and verdict stay in `ml/evaluation/<phase>/`.
- **The trial ledger** is the list of every trial ever scored. Each round's rule file is hashed into it before the first score, which is what the deflated Sharpe's trial count is read from.
- **Rerun a round:** `aq cycle research`.
