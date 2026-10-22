# Reproducibility

How to reproduce every number claimed in this README.

---

## Environment

- **Python:** 3.11 (CI runs on 3.11; local dev on 3.14)
- **OS:** Windows 10/11 (dev), Ubuntu 22.04 (CI)
- **Key packages:** torch (>= 2.0.0, CPU build fine), pandas, scikit-learn (see `requirements/requirements.txt` for the full pinned set)

## Data pipeline

```powershell
# 1. Fetch raw data (requires Lean CLI + local data folder OR prior zips in data/)
aq fetch stock --ticker AAPL --start 2014-12-01 --end 2021-03-31 --apply
# (repeat for each ticker, or use the existing data/ folder)

# 2. Build dataset
python train.py --dataset-only

# Output: ml/datasets/full_dataset.csv (~163k rows × 251 columns, cutoff 2021-03-31)
```

## Model training (Codespace recommended)

```powershell
# Full pipeline (~15 min on Codespace)
python train.py                    # baseline + experts
python train_gating.py            # gating network
python train_multitask.py         # multitask heads (incl. rank_5d/rank_20d)
python train_sequence.py          # causal TCN sequence encoder
```

## Offline evaluation

```powershell
aq evaluate --rank-book --model multitask   # net Sharpe -0.25 on the backtest split (V6.1.0)
aq evaluate --rank-book --model sequence    # net Sharpe -0.87 on the backtest split (V6.1.0)
aq evaluate --rank-book --monte-carlo       # 1000-run bootstrap
aq evaluate --benchmarks                    # strategy + SPY/60-40 baselines
aq evaluate --all                           # rank book, Monte Carlo, benchmarks, capacity, stress, calibrate-edge
```

## V6.4.0 research (rules written before any score)

```powershell
python scripts/data_append_guard.py snapshot --out ml/evaluation/v640/data_before.json      # before a refresh
python scripts/data_append_refresh.py --end 2026-10-17 --apply                                # append only, stored vintage
python scripts/data_append_guard.py verify --before ml/evaluation/v640/data_before.json     # 0 changed rows
# on the training Codespace (one lifetime): bash scripts/codespace_session_v640.sh <manifest>   -> ml/evaluation/v640/research.json
python scripts/v640_research.py --smoke ...        # every stage, one variant, two phases, before the real chain
aq evaluate --classification-parity --backtest-dir backtests/<run with include_probabilities>
aq evaluate --paper-check --backtest-dir <run folder> --reference-dir backtests/<pinned run>
python scripts/freeze_run_config.py --base ml/evaluation/run_configs/v640_bt5.json --adopted ml/evaluation/v640/adopted_changes.json --name v640_bt6
```

## Lean backtest

```powershell
aq backtest    # requires Docker Desktop + local Lean data folder
```

---

## Claimed numbers (as of V6.3.0, 2026-10-18)

| Source | Metric | Value | File |
|---|---|---|---|
| Offline rank-book, ungated (multitask) | Net Sharpe, backtest split | −0.252 | `ml/evaluation/rank_book_simulation_multitask.json` |
| Offline rank-book, ungated (sequence) | Net Sharpe, backtest split | −0.866 | `ml/evaluation/rank_book_simulation_sequence.json` |
| Offline rank-book, as live (validation / backtest) | Net Sharpe | −1.056 / +0.937 | `rank_book_simulation_as_live_*.json` |
| Holdout (2025-07..2026-09, already seen) | as-live / idealized net Sharpe | +1.439 / −0.226 | `holdout_report.json` |
| Monte Carlo of the offline idealized book (sequence) | p5 / p50 / p95 total return | −17.97% / −7.66% / +2.61% | `monte_carlo.json` |
| Monte Carlo of the Lean run's own equity curve | p5 / p50 / p95 total return | +3.68% / +16.85% / +30.78% | `monte_carlo_lean.json` |
| Benchmark: SPY buy-and-hold / 60/40 SPY-TLT | Net Sharpe, backtest split | 0.882 / 0.895 | `benchmark_comparison.json` |
| Walk-forward (out-of-sample) | Mean per-window net Sharpe | −0.158 (4 of 12 windows positive) | `ml/versions/walk-forward-633816f4-*/` |
| Lean backtest 2023-07..2026-09 (V6.3.0 BT4 = V6.2.0 BT2) | Net profit / Sharpe (risk-free) / drawdown | +16.848% / +0.082 / 4.30% | `backtests/2026-10-18_12-55-00/` |
| Same run, strategy without the T-bill sweep | PnL / Sharpe (no risk-free) / deflated Sharpe | +$6,148 / +0.544 / 46% (22 trials) | `ml/evaluation/backtest_statistics.json` |

Every Backtest Statistics number is reproduced from the run folder alone with `aq evaluate --lean-report --backtest-dir backtests/2026-10-18_12-55-00` (the frozen config is `ml/evaluation/run_configs/2026-10-18_12-55-00.json`); the offline rows with `scripts/codespace_session_v630.sh` on the training Codespace.

These are **offline** numbers using the torch-free simulator — not a substitute for a real Lean backtest, which includes slippage, entry lag, and execution realism the offline model approximates but does not replicate exactly. The README's evaluation sections are regenerated from `ml/evaluation/*.json` on every `aq evaluate` run, so they always reflect the latest local run rather than this table.
