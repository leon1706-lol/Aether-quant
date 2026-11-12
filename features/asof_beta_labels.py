"""As-of beta for the beta-neutral and residual rank labels (V6.4.3).

train.py's `target_beta_neutral_rank_Nd` / `target_residual_rank_Nd` residualise each forward return against ONE
whole-history beta per asset, an OLS slope fitted on forward returns that include the label's own future (Problems #238).
Here the beta at date t is a trailing OLS slope of the asset's realised daily returns on the market's, over the
`window` days up to and including t, so a label row only depends on what was known at t plus its own forward window.
The rest of each label (market term, sector dummies, cross-sectional size z-score, the min universe floor, the
percentile rank) is train.py's definition unchanged. Pure numpy/pandas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import ArrayLike

DEFAULT_WINDOW = 252
DEFAULT_MIN_PERIODS = 126


def cross_sectional_residualize(returns: np.ndarray, design_matrix: np.ndarray) -> np.ndarray:
    """Residuals of one date's `returns ~ design_matrix` least-squares fit; a degenerate fit (fewer rows than columns, a
    LinAlgError, rank 0, a non-finite residual) returns `returns` unchanged. Never raises. train.py uses this one."""
    n_rows, n_columns = design_matrix.shape
    if n_rows == 0 or n_rows < n_columns:
        return returns
    try:
        coefficients, _residual_sum, rank, _singular_values = np.linalg.lstsq(design_matrix, returns, rcond=None)
    except np.linalg.LinAlgError:
        return returns
    if rank < 1:
        return returns
    residuals = returns - design_matrix @ coefficients
    if not np.all(np.isfinite(residuals)):
        return returns
    return residuals


def asof_rolling_beta(asset_returns: ArrayLike, market_returns: ArrayLike, *, window: int = DEFAULT_WINDOW, min_periods: int = DEFAULT_MIN_PERIODS) -> np.ndarray:
    """Trailing OLS slope of `asset_returns` on `market_returns` (aligned arrays, NaN = missing) over the last `window`
    paired observations up to and including each position; NaN until `min_periods` pairs exist."""
    asset = pd.Series(np.asarray(asset_returns, dtype=float))
    market = pd.Series(np.asarray(market_returns, dtype=float))
    paired = asset.notna() & market.notna()
    asset, market = asset.where(paired), market.where(paired)
    covariance = asset.rolling(window, min_periods=min_periods).cov(market)
    variance = market.rolling(window, min_periods=min_periods).var()
    beta = covariance / variance.where(variance > 0.0)
    return beta.to_numpy()


def asof_residual_forward_return(fwd_asset: ArrayLike, fwd_market: ArrayLike, beta_t: ArrayLike) -> np.ndarray:
    """fwd_asset - beta_t * fwd_market; a missing beta counts as 0 (train.py's fallback for a short history)."""
    beta = np.nan_to_num(np.asarray(beta_t, dtype=float), nan=0.0)
    return np.asarray(fwd_asset, dtype=float) - beta * np.asarray(fwd_market, dtype=float)


def asof_beta_by_row(frame: pd.DataFrame, *, market_ticker: str, return_column: str = "close_to_close_return_1d",
                     window: int = DEFAULT_WINDOW, min_periods: int = DEFAULT_MIN_PERIODS) -> pd.Series:
    """The as-of beta of every row of a long (date, ticker) frame, aligned to `frame.index`. The market's daily return
    is matched by date, so each asset pairs only on the dates both traded."""
    market = frame.loc[frame["ticker"] == market_ticker, ["date", return_column]].drop_duplicates("date")
    market_by_date = dict(zip(market["date"], market[return_column]))
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    for _ticker, rows in frame.sort_values("date").groupby("ticker", sort=False):
        market_returns = rows["date"].map(market_by_date).to_numpy(dtype=float)
        out.loc[rows.index] = asof_rolling_beta(rows[return_column].to_numpy(dtype=float), market_returns, window=window,
                                                min_periods=min_periods)
    return out


def build_asof_rank_labels(frame: pd.DataFrame, *, horizons: Sequence[int]=(5, 20), market_ticker: str = "SPY", window: int = DEFAULT_WINDOW,
                           min_periods: int = DEFAULT_MIN_PERIODS, min_universe_size: int = 20,
                           sector_by_ticker: dict[str, str] | None = None, size_column: str | None = "liquidity_log_dollar_volume",
                           use_market: bool = True, use_sector: bool = True, use_size: bool = True) -> pd.DataFrame:
    """`target_beta_neutral_rank_{h}d_asof` and `target_residual_rank_{h}d_asof` for a long frame holding `date`,
    `ticker`, `close_to_close_return_1d`, `target_return_{h}d` (and `size_column`). Same index as `frame`."""
    beta = asof_beta_by_row(frame, market_ticker=market_ticker, window=window, min_periods=min_periods)
    out = pd.DataFrame(index=frame.index)
    sectors = frame["ticker"].map(sector_by_ticker or {}).fillna("Unknown") if use_sector else None
    for horizon in horizons:
        return_column = f"target_return_{horizon}d"
        market = frame.loc[frame["ticker"] == market_ticker, ["date", return_column]].drop_duplicates("date")
        market_fwd = frame["date"].map(dict(zip(market["date"], market[return_column])))
        valid = frame[return_column].notna() & market_fwd.notna()

        residual = pd.Series(asof_residual_forward_return(frame[return_column], market_fwd, beta), index=frame.index).where(valid)
        size_by_date = residual.groupby(frame["date"]).transform("count")
        eligible = residual.where(size_by_date >= min_universe_size)
        out[f"target_beta_neutral_rank_{horizon}d_asof"] = eligible.groupby(frame["date"]).rank(pct=True)

        ranks = pd.Series(np.nan, index=frame.index, dtype=float)
        has_return = frame[return_column].notna()
        long_frame = frame.loc[has_return, ["date", return_column]].copy()
        long_frame["market_term"] = (np.nan_to_num(beta[has_return].to_numpy(), nan=0.0)
                                     * market_fwd[has_return].fillna(0.0).to_numpy()) if use_market else 0.0
        if use_size and size_column and size_column in frame.columns:
            size = frame.loc[has_return, size_column]
            grouped = size.groupby(long_frame["date"])
            long_frame["size_z"] = ((size - grouped.transform("mean")) / grouped.transform("std").replace(0.0, np.nan)).fillna(0.0)
        for _date, group in long_frame.groupby("date", sort=False):
            if len(group) < min_universe_size:
                continue
            columns = [np.ones(len(group))]
            if use_market:
                columns.append(group["market_term"].to_numpy())
            if use_sector:
                dummies = pd.get_dummies(sectors.loc[group.index], drop_first=True)
                if not dummies.empty:
                    columns.append(dummies.to_numpy(dtype=float))
            if "size_z" in group:
                columns.append(group["size_z"].to_numpy())
            residuals = cross_sectional_residualize(group[return_column].to_numpy(dtype=float), np.column_stack(columns))
            ranks.loc[group.index] = pd.Series(residuals).rank(pct=True).to_numpy()
        out[f"target_residual_rank_{horizon}d_asof"] = ranks
    return out
