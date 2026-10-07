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

    # Alpha = the part of the book's return the factors do NOT explain: the
    # regression INTERCEPT plus the residuals. V5.5.0 (found when the first
    # caller shipped): this used mean(residuals) alone, which is identically ~0
    # for an OLS fit that includes an intercept, so alpha_sharpe and
    # alpha_annualized_return_pct were always 0.0 whatever the book earned.
    alpha_series = residuals + betas[0]
    resid_std = np.std(alpha_series, ddof=1) if len(alpha_series) > 1 else 1e-12
    alpha_sharpe = float(np.mean(alpha_series) / max(resid_std, 1e-12) * np.sqrt(252))
    total_sharpe = float(np.mean(y) / max(np.std(y, ddof=1), 1e-12) * np.sqrt(252))

    # Factor contribution: variance explained by each factor alone
    contributions = {}
    for i, name in enumerate(names):
        col = X[:, i + 1]
        ss_factor = float(np.sum((col - col.mean()) ** 2))
        beta_i = betas[i + 1]
        contribution = beta_i ** 2 * ss_factor
        contributions[name] = round(float(contribution / ss_total * 100), 2) if ss_total > 0 else 0.0

    return {
        "alpha_sharpe": round(alpha_sharpe, 4),
        "total_sharpe": round(total_sharpe, 4),
        "r_squared": round(r_squared, 4),
        "loadings": {name: round(float(betas[i + 1]), 6) for i, name in enumerate(names)},
        "alpha_annualized_return_pct": round(float(np.mean(alpha_series) * 252 * 100), 4),
        "factor_contribution_pct": contributions,
        "n_obs": n,
    }


def _align(series: pd.Series) -> np.ndarray:
    values = pd.Series(series).ffill().dropna().to_numpy(dtype=float)
    return values


# ---------------------------------------------------------------------------
# V5.5.0 - the missing caller. compute_factor_exposure() shipped in V5.4.3 but
# nothing produced its inputs, so "how much of the book's Sharpe is market or
# momentum exposure rather than ranking skill" was never answered. These
# helpers build the factor series from the dataset's own close pivot, on the
# SAME dating convention rank_book_simulator uses: a return booked on date d is
# the FORWARD return d -> d+1 of weights decided with information up to d.
# ---------------------------------------------------------------------------


def _forward_returns(close_pivot: pd.DataFrame) -> pd.DataFrame:
    return close_pivot.shift(-1) / close_pivot - 1.0


def market_forward_returns(close_pivot: pd.DataFrame, market_ticker: str = "SPY") -> pd.Series:
    """Forward 1-day return of `market_ticker`, indexed by decision date.
    Empty series when the ticker is absent (callers report SKIPPED)."""
    if market_ticker not in close_pivot.columns:
        return pd.Series(dtype=float)
    return _forward_returns(close_pivot)[market_ticker]


def momentum_factor_forward_returns(
    close_pivot: pd.DataFrame, *, lookback: int = 20, quantile: float = 0.2
) -> pd.Series:
    """Long-short momentum factor: per date, the mean forward return of the
    top `quantile` of names by trailing `lookback`-day return minus the
    bottom `quantile`'s. The signal at d uses closes up to d only, so the
    factor has no lookahead against the book it is regressed on."""
    momentum = close_pivot / close_pivot.shift(lookback) - 1.0
    forward = _forward_returns(close_pivot)
    values: dict = {}
    for date in close_pivot.index:
        signal = momentum.loc[date].dropna()
        outcome = forward.loc[date]
        bucket = max(1, int(len(signal) * quantile))
        if len(signal) < 2 * bucket:
            continue
        ranked = signal.sort_values()
        short_leg = outcome.reindex(ranked.index[:bucket]).dropna()
        long_leg = outcome.reindex(ranked.index[-bucket:]).dropna()
        if short_leg.empty or long_leg.empty:
            continue
        values[date] = float(long_leg.mean() - short_leg.mean())
    return pd.Series(values, dtype=float)


def compute_book_factor_exposure(
    per_date: list[str],
    per_date_net_return: list[float],
    close_pivot: pd.DataFrame,
    *,
    market_ticker: str = "SPY",
    momentum_lookback: int = 20,
) -> dict:
    """Regress a simulated book's daily net returns on the market and
    momentum factors. Dates are inner-joined first so the positional OLS in
    compute_factor_exposure() sees aligned, NaN-free series."""
    if close_pivot.empty:
        return {"status": "SKIPPED", "reason": "no close column in dataset"}
    book = pd.Series(per_date_net_return, index=[str(date) for date in per_date], dtype=float)
    market = market_forward_returns(close_pivot, market_ticker)
    if market.empty:
        return {"status": "SKIPPED", "reason": f"{market_ticker} not in dataset"}
    market.index = [str(date) for date in market.index]
    momentum = momentum_factor_forward_returns(close_pivot, lookback=momentum_lookback)
    momentum.index = [str(date) for date in momentum.index]
    joined = pd.concat({"book": book, "market": market, "momentum": momentum}, axis=1, join="inner").dropna()
    if len(joined) < 30:
        return {"status": "SKIPPED", "reason": f"only {len(joined)} aligned dates (need >= 30)"}
    result = compute_factor_exposure(joined["book"], joined["market"], momentum_factor=joined["momentum"])
    result["status"] = "OK"
    result["market_ticker"] = market_ticker
    return result
