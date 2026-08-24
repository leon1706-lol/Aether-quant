# Reproducibility

How to reproduce every number claimed in this README.

---

## Environment

- **Python:** 3.11 (CI runs on 3.11; local dev on 3.14)
- **OS:** Windows 10/11 (dev), Ubuntu 22.04 (CI)
- **Key packages:** torch 2.13.0+cpu, pandas, scikit-learn (see `requirements/requirements.txt`)

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
aq evaluate --rank-book --model multitask   # net Sharpe ~1.68 (V5.4.2)
aq evaluate --rank-book --model sequence    # net Sharpe ~1.00
aq evaluate --monte-carlo                   # 1000-run bootstrap
aq evaluate --all                           # capacity/stress/calibrate-edge
```

## Lean backtest

```powershell
aq backtest    # requires Docker Desktop + local Lean data folder
```

---

## Claimed numbers (as of V5.4.2)

| Source | Metric | Value | Commit |
|---|---|---|---|
| Offline rank-book (multitask) | Net Sharpe | **1.6805** | `746bfb4` |
| Monte Carlo p5/p95 return | −2.00% / +21.45% | | same |
| Walk-forward net Sharpe mean | ~0.65 | V5.2.9 retrain | |

These are **offline** numbers using the torch-free simulator — not a substitute for a real Lean backtest, which includes slippage, entry lag, and execution realism the offline model approximates but does not replicate exactly.
