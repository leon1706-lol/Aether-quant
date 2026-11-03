"""Probability of backtest overfitting by combinatorially symmetric cross-validation (V6.4.3; Bailey, Borwein,
López de Prado and Zhu, "The Probability of Backtest Overfitting", J. Computational Finance 2017).

`returns` is T x N: the daily returns of N trials (variants scored on the same dates). The rows are cut into `blocks`
contiguous blocks; for every way to pick half of them as in-sample, the trial with the best in-sample Sharpe is taken
and its out-of-sample rank among the N trials recorded. PBO is the share of splits where that trial lands in the bottom
half out of sample (logit of its relative rank <= 0). A selection process with real skill gives PBO well below 0.5;
picking the best of N noise variants gives about 0.5. Pure numpy.
"""

from __future__ import annotations

import itertools
import math

import numpy as np


def _sharpe(block_sums: np.ndarray, block_sq: np.ndarray, block_n: np.ndarray, mask: np.ndarray, periods: int) -> np.ndarray:
    n = block_n[mask].sum()
    total = block_sums[mask].sum(axis=0)
    total_sq = block_sq[mask].sum(axis=0)
    mean = total / n
    variance = np.maximum(total_sq / n - mean**2, 0.0) * n / max(n - 1, 1)
    std = np.sqrt(variance)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(std > 0, mean / std * math.sqrt(periods), 0.0)
    return sharpe


def probability_of_backtest_overfitting(returns, *, blocks: int = 16, periods_per_year: int = 252) -> dict:
    """{"pbo", "num_combinations", "num_trials", "lambda_quantiles", "degradation_slope", "degradation_intercept",
    "prob_oos_loss"}; `pbo` is None when there are fewer than 2 trials or fewer rows than blocks."""
    matrix = np.asarray(returns, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2 or matrix.shape[0] < blocks or blocks < 2 or blocks % 2:
        return {"pbo": None, "num_combinations": 0, "num_trials": int(matrix.shape[1]) if matrix.ndim == 2 else 0}
    matrix = np.nan_to_num(matrix, nan=0.0)
    num_rows, num_trials = matrix.shape
    edges = np.linspace(0, num_rows, blocks + 1).astype(int)
    block_sums = np.array([matrix[a:b].sum(axis=0) for a, b in zip(edges[:-1], edges[1:])])
    block_sq = np.array([(matrix[a:b] ** 2).sum(axis=0) for a, b in zip(edges[:-1], edges[1:])])
    block_n = np.array([b - a for a, b in zip(edges[:-1], edges[1:])], dtype=float)

    lambdas, is_best, oos_of_best = [], [], []
    for chosen in itertools.combinations(range(blocks), blocks // 2):
        mask = np.zeros(blocks, dtype=bool)
        mask[list(chosen)] = True
        in_sample = _sharpe(block_sums, block_sq, block_n, mask, periods_per_year)
        out_sample = _sharpe(block_sums, block_sq, block_n, ~mask, periods_per_year)
        best = int(np.argmax(in_sample))
        rank = float((out_sample < out_sample[best]).sum() + 0.5 * ((out_sample == out_sample[best]).sum() - 1) + 1)
        omega = rank / (num_trials + 1)
        lambdas.append(math.log(omega / (1.0 - omega)))
        is_best.append(float(in_sample[best]))
        oos_of_best.append(float(out_sample[best]))
    lambdas_array = np.array(lambdas)
    slope, intercept = (np.polyfit(is_best, oos_of_best, 1) if np.ptp(is_best) > 0 else (0.0, float(np.mean(oos_of_best))))
    return {
        "pbo": float((lambdas_array <= 0.0).mean()),
        "num_combinations": len(lambdas),
        "num_trials": num_trials,
        "num_rows": num_rows,
        "blocks": blocks,
        "lambda_quantiles": {str(q): float(np.quantile(lambdas_array, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
        "degradation_slope": float(slope),
        "degradation_intercept": float(intercept),
        "prob_oos_loss": float((np.array(oos_of_best) < 0.0).mean()),
    }
