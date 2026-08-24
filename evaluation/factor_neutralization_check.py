"""V5.4.3 - factor-neutralization check: decomposes the offline rank book's
realized returns into systematic (market/sector/momentum) and residual
(pure alpha) components, answering "how much of the claimed Sharpe is
actually skill vs. factor exposure?"

Pure: numpy/pandas only, no I/O, no torch."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_factor_exposure(
    book_returns: pd.Series,
    market_returns: pd.Series,
    *,
    momentum_factor: pd.Series | None = None,
    sector_returns: dict[str, pd.Series] | None = None,
) -> dict:
    """Regresses book returns onto factor columns and reports loadings,
    R², residual Sharpe, and % of variance explained by each factor.

    All input series must be aligned by date (same index or positional).
    Missing values are forward-filled then dropped.

    Returns:
        {"alpha_sharpe": float, "total_sharpe": float, "r_squared": float,
         "loadings": {factor: beta}, "alpha_annualized_return_pct": float,
         "factor_contribution_pct": {factor: pct_of_variance},
         "n_obs": int}
    """
    book = _align(book_returns)
    market = _align(market_returns)
    n = min(len(book), len(market))
    book, market = book[:n], market[:n]

    factors = {"market": market}
    if momentum_factor is not None:
        mom = _align(momentum_factor)[:n]
        if len(mom) == n:
            factors["momentum"] = mom
    if sector_returns:
        for name, series in sector_returns.items():
            s = _align(series)
            if len(s) >= n:
                factors[f"sector_{name}"] = s[:n]

    # Build design matrix [1, factor_1, ..., factor_k]
    names = list(factors.keys())
    X = np.column_stack([np.ones(n)] + [factors[name] for name in names])
    y = book

    # OLS: beta = (X'X)^-1 X'y
    XtX = X.T @ X
    Xty = X.T @ y
    try:
        betas = np.linalg.solve(XtX, Xty)
    except np.linalg.LinAlgError:
        return {"error": "singular design matrix", "n_obs": n}

    residuals = y - X @ betas
    ss_total = float(np.sum((y - y.mean()) ** 2))
    ss_resid = float(np.sum(residuals ** 2))
    r_squared = 1.0 - ss_resid / ss_total if ss_total > 0 else 0.0

    # Residual alpha Sharpe (annualized with sqrt(252))
    resid_std = np.std(residuals, ddof=1) if len(residuals) > 1 else 1e-12
    alpha_sharpe = float(np.mean(residuals) / max(resid_std, 1e-12) * np.sqrt(252))
    total_sharpe = float(np.mean(y) / max(np.std(y, ddof=1), 1e-12) * np.sqrt(252))

    # Factor contribution: variance explained by each factor alone
    contributions = {}
    for i, name in enumerate(names):
        col = X[:, i + 1]
        ss_factor = float(np.sum((col - col.mean()) ** 2))
        beta_i = betas[i + 1]
        contribution = beta_i ** 2 * ss_factor
        contributions[name] = round(contribution / ss_total * 100, 2) if ss_total > 0 else 0.0

    return {
        "alpha_sharpe": round(alpha_sharpe, 4),
        "total_sharpe": round(total_sharpe, 4),
        "r_squared": round(r_squared, 4),
        "loadings": {name: round(float(betas[i + 1]), 6) for i, name in enumerate(names)},
        "alpha_annualized_return_pct": round(float(np.mean(residuals) * 252 * 100), 4),
        "factor_contribution_pct": contributions,
        "n_obs": n,
    }


def _align(series: pd.Series) -> np.ndarray:
    values = pd.Series(series).ffill().dropna().to_numpy(dtype=float)
    return values
