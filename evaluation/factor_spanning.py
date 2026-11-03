"""Factor baselines and spanning regressions (V6.4.3): does a signal add anything over plain, untrained factors?

`build_factor_scores` derives five classic cross-sectional factor scores from columns every dataset row already has
(as of the row's date, no lookahead); `build_factor_returns` turns any score into a daily top-minus-bottom quantile
return; `factor_spanning` regresses a signal's long/short return on the factor returns with Newey-West errors - the
intercept (alpha) is what the signal earns beyond the factors. Pure numpy/pandas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FACTOR_COLUMNS = ("f_mom_12_1", "f_mom_20", "f_rev_5", "f_lowvol", "f_high52")


def build_factor_scores(frame: pd.DataFrame, *, ticker_column: str = "ticker", date_column: str = "date") -> pd.DataFrame:
    """f_mom_12_1 (sum of daily returns from t-252 to t-21), f_mom_20 (momentum_20d), f_rev_5 (-5-day return),
    f_lowvol (-rolling_volatility_20d), f_high52 (dist_52w_high: higher = nearer the 52-week high) and f_composite
    (mean of the per-date ranks of mom_12_1, high52, lowvol and rev_5). Same index as `frame`."""
    out = pd.DataFrame(index=frame.index)
    ordered = frame.sort_values([ticker_column, date_column])
    daily = ordered.groupby(ticker_column)["close_to_close_return_1d"]
    momentum = daily.transform(lambda s: s.shift(21).rolling(231, min_periods=231).sum())
    out["f_mom_12_1"] = momentum.reindex(frame.index)
    out["f_mom_20"] = frame["momentum_20d"] if "momentum_20d" in frame else np.nan
    out["f_rev_5"] = -frame["close_to_close_return_5d"] if "close_to_close_return_5d" in frame else np.nan
    out["f_lowvol"] = -frame["rolling_volatility_20d"] if "rolling_volatility_20d" in frame else np.nan
    out["f_high52"] = frame["dist_52w_high"] if "dist_52w_high" in frame else np.nan
    ranks = out[["f_mom_12_1", "f_high52", "f_lowvol", "f_rev_5"]].groupby(frame[date_column]).rank(pct=True)
    out["f_composite"] = ranks.mean(axis=1, skipna=True)
    return out


def build_factor_returns(frame: pd.DataFrame, factor_columns, *, date_column: str = "date",
                         forward_return_column: str = "target_return_1d", quantile: float = 0.2, min_names: int = 20) -> pd.DataFrame:
    """Daily equal-weight top-quantile minus bottom-quantile return of each score column; NaN on dates with fewer than
    `min_names` scored names. `forward_return_column` at t is the t -> t+1 return (the simulator's convention)."""
    result = {}
    for column in factor_columns:
        data = frame[[date_column, column, forward_return_column]].dropna()
        returns = {}
        for date, day in data.groupby(date_column, sort=True):
            if len(day) < min_names:
                continue
            k = max(1, int(round(len(day) * quantile)))
            ordered = day.sort_values(column)
            returns[date] = float(ordered[forward_return_column].iloc[-k:].mean() - ordered[forward_return_column].iloc[:k].mean())
        result[column] = pd.Series(returns, dtype=float)
    return pd.DataFrame(result).sort_index()


def _newey_west_cov(x: np.ndarray, residuals: np.ndarray, lags: int) -> np.ndarray:
    n = len(residuals)
    scores = x * residuals[:, None]
    meat = scores.T @ scores / n
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)
        gamma = scores[lag:].T @ scores[:-lag] / n
        meat += weight * (gamma + gamma.T)
    bread = np.linalg.pinv(x.T @ x / n)
    return bread @ meat @ bread / n


def factor_spanning(signal_returns: pd.Series, factor_returns: pd.DataFrame, *, hac_lags: int = 19, periods_per_year: int = 252) -> dict:
    """OLS of the signal's daily return on the factors' (dates present in both, rows with a NaN dropped)."""
    joined = pd.concat([signal_returns.rename("_signal"), factor_returns], axis=1, join="inner")
    joined = joined.dropna(axis=1, how="all").dropna()  # a factor with no history at all (e.g. 12-1 momentum) is left out
    factors = [c for c in factor_returns.columns if c in joined.columns]
    if len(joined) <= len(factors) + 2:
        return {"num_dates": int(len(joined)), "alpha_daily": None, "alpha_t": None}
    y = joined["_signal"].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(joined)), joined[factors].to_numpy(dtype=float)])
    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    residuals = y - x @ coefficients
    covariance = _newey_west_cov(x, residuals, hac_lags)
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        t_stats = np.where(standard_errors > 0, coefficients / standard_errors, 0.0)
    total = float(((y - y.mean()) ** 2).sum())
    return {
        "num_dates": int(len(joined)),
        "alpha_daily": float(coefficients[0]),
        "alpha_annual": float(coefficients[0] * periods_per_year),
        "alpha_t": float(t_stats[0]),
        "betas": {name: float(value) for name, value in zip(factors, coefficients[1:])},
        "betas_t": {name: float(value) for name, value in zip(factors, t_stats[1:])},
        "r2": float(1.0 - (residuals**2).sum() / total) if total > 0 else 0.0,
    }
