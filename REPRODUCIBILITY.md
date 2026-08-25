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
aq evaluate --rank-book --model multitask   # net Sharpe ~1.68
aq evaluate --rank-book --model sequence    # net Sharpe ~1.00
aq evaluate --rank-book --monte-carlo       # 1000-run bootstrap
aq evaluate --benchmarks                    # strategy + SPY/60-40 baselines
aq evaluate --all                           # capacity/stress/calibrate-edge/benchmarks
```

## Lean backtest

```powershell
aq backtest    # requires Docker Desktop + local Lean data folder
```

---

## Claimed numbers (as of V5.4.4)

| Source | Metric | Value | Commit |
|---|---|---|---|
| Offline rank-book (multitask) | Net Sharpe | **1.681** | `6e89379` (V5.4.4) |
| Offline rank-book (sequence) | Net Sharpe | 0.997 | same |
| Monte Carlo bootstrap | p5/p95 total return | −2.00% / +21.45% | same |
| Benchmark: SPY buy-and-hold | Net Sharpe | 1.214 | same |
| Benchmark: 60/40 SPY-TLT | Net Sharpe | 1.624 | same |
| Walk-forward (out-of-sample) | Mean per-window net Sharpe | ~0.65 | V5.2.9 retrain |

These are **offline** numbers using the torch-free simulator — not a substitute for a real Lean backtest, which includes slippage, entry lag, and execution realism the offline model approximates but does not replicate exactly. The README's evaluation sections are regenerated from `ml/evaluation/*.json` on every `aq evaluate` run, so they always reflect the latest local run rather than this table.
