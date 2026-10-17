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

## Lean backtest

```powershell
aq backtest    # requires Docker Desktop + local Lean data folder
```

---

## Claimed numbers (as of V6.1.0, 2026-10-16)

| Source | Metric | Value | Where it is written |
|---|---|---|---|
| Offline rank-book, ungated (multitask) | Net Sharpe, backtest split | −0.252 | `ml/evaluation/rank_book_simulation_multitask.json` |
| Offline rank-book, ungated (sequence) | Net Sharpe, backtest split | −0.866 | `ml/evaluation/rank_book_simulation_sequence.json` |
| Offline rank-book, as live (validation / backtest) | Net Sharpe | +1.171 / +1.004 | `rank_book_simulation_as_live_*.json` |
| One-look holdout (2025-07..2026-09) | as-live / idealized net Sharpe | −0.071 / −0.226 | `holdout_report.json` |
| Monte Carlo of the offline idealized book (sequence) | p5 / p50 / p95 total return | −17.97% / −7.66% / +2.61% | `monte_carlo.json` |
| Monte Carlo of the Lean run's own equity curve | p5 / p50 / p95 total return | −5.59% / +5.43% / +17.37% | `monte_carlo_lean.json` |
| Benchmark: SPY buy-and-hold / 60/40 SPY-TLT | Net Sharpe, backtest split | 0.882 / 0.895 | `benchmark_comparison.json` |
| Walk-forward (out-of-sample) | Mean per-window net Sharpe | −0.158 (4 of 12 windows positive) | `ml/versions/walk-forward-633816f4-*/` |
| Lean backtest 2023-07..2026-09 (V6.1.0 BT1 = V6 BT2) | Net profit / Sharpe (risk-free) / drawdown | +5.277% / −1.673 / 5.50% | `backtests/2026-10-16_18-23-01/` |

These are **offline** numbers using the torch-free simulator — not a substitute for a real Lean backtest, which includes slippage, entry lag, and execution realism the offline model approximates but does not replicate exactly. The README's evaluation sections are regenerated from `ml/evaluation/*.json` on every `aq evaluate` run, so they always reflect the latest local run rather than this table.
