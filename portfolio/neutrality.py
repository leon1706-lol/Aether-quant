"""Beta and factor neutrality for any book (V6.6.5, #345). Dollar and sector neutrality are `portfolio.book_neutrality`.

`beta_neutralize` either projects the book onto the space with zero net beta or, given a hedge instrument, adds a hedge
leg; `factor_neutralize` projects out any set of exposures by least squares. Names without a beta or exposure are left as
they are and count as zero exposure, never as a guessed one.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

__all__ = ["estimate_betas", "beta_neutralize", "factor_neutralize", "net_beta"]


def estimate_betas(returns: pd.DataFrame, market: pd.Series, *, window: int = 120, min_obs: int = 60) -> pd.Series:
    """Each column's OLS beta to `market` over the last `window` rows where both are finite; NaN with fewer than `min_obs`."""
    aligned_market = pd.to_numeric(market, errors="coerce").reindex(returns.index)
    out: dict[str, float] = {}
    for column in returns.columns:
        pair = pd.DataFrame({"r": pd.to_numeric(returns[column], errors="coerce"), "m": aligned_market}).replace([np.inf, -np.inf], np.nan).dropna()
        pair = pair.iloc[-int(window):]
        if len(pair) < int(min_obs):
            out[str(column)] = float("nan")
            continue
        variance = float(pair["m"].var(ddof=1))
        out[str(column)] = float(pair["r"].cov(pair["m"]) / variance) if variance > 0.0 else float("nan")
    return pd.Series(out, dtype=float)


def net_beta(weights: Mapping[str, float], betas: Mapping[str, float]) -> float:
    """`sum(w_i * beta_i)` over names with a finite beta."""
    total = 0.0
    for name, weight in weights.items():
        beta = betas.get(name)
        if beta is not None and math.isfinite(float(beta)) and math.isfinite(float(weight)):
            total += float(weight) * float(beta)
    return total


def beta_neutralize(weights: Mapping[str, float], betas: Mapping[str, float], *, hedge: str | None = None) -> dict[str, float]:
    """A book with zero net beta. With `hedge` (an instrument whose beta is in `betas`), its weight absorbs the net beta;
    without it, `w - (w.b / b.b) * b` over the names with a finite beta, the smallest change that does it."""
    book = {name: float(weight) if math.isfinite(float(weight)) else 0.0 for name, weight in weights.items()}
    exposure = net_beta(book, betas)
    if hedge is not None:
        hedge_beta = float(betas.get(hedge, float("nan")))
        if not math.isfinite(hedge_beta) or hedge_beta == 0.0:
            raise ValueError(f"hedge {hedge!r} needs a finite, non-zero beta")
        rest = exposure - book.get(hedge, 0.0) * hedge_beta
        book[hedge] = -rest / hedge_beta
        return book
    known = {name: float(betas[name]) for name in book if name in betas and math.isfinite(float(betas[name]))}
    norm = sum(beta * beta for beta in known.values())
    if norm <= 0.0:
        return book
    scale = exposure / norm
    return {name: weight - scale * known.get(name, 0.0) for name, weight in book.items()}


def factor_neutralize(weights: pd.Series, exposures: pd.DataFrame, *, ridge: float = 1e-8) -> pd.Series:
    """`w - X (X'X + ridge*I)^-1 X'w` on the names `weights` and `exposures` (names x factors) share; other names unchanged.
    Rows of `exposures` with a non-finite value are left out of the projection."""
    out = pd.to_numeric(weights, errors="coerce").fillna(0.0).astype(float).copy()
    frame = exposures.reindex(out.index).replace([np.inf, -np.inf], np.nan).dropna()
    if frame.empty:
        return out
    x = frame.to_numpy(float)
    w = out.loc[frame.index].to_numpy(float)
    gram = x.T @ x + max(float(ridge), 0.0) * np.eye(x.shape[1])
    try:
        coefficients = np.linalg.solve(gram, x.T @ w)
    except np.linalg.LinAlgError:
        return out
    out.loc[frame.index] = w - x @ coefficients
    return out
