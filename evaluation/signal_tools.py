"""From prices to the inputs `evaluation.research_harness.evaluate_signal` reads, plus two quick looks at any signal
(V6.6.5, #345): returns by score quantile and the information coefficient by horizon.

A score dated D may use what was known at D's close; its targets are the returns from D's close to D+h's close.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

__all__ = ["forward_returns", "forward_rank_targets", "quantile_returns", "ic_decay"]


def forward_returns(prices: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """`price[t + h] / price[t] - 1` (dates x tickers), NaN where either price is missing or non-positive."""
    clean = prices.astype(float).where(lambda frame: frame > 0.0)
    return clean.shift(-int(horizon)) / clean - 1.0


def forward_rank_targets(prices: pd.DataFrame, horizons: Sequence[int] = (5, 20), *, split: str = "validation") -> pd.DataFrame:
    """Long format with `date, ticker, split, target_return_1d` and, per horizon, `target_return_{h}d` and
    `target_rank_{h}d` (the cross-sectional percentile of the forward return on that date). Rows without a 1-day target drop."""
    pieces = {"target_return_1d": forward_returns(prices, 1)}
    for horizon in horizons:
        future = forward_returns(prices, int(horizon))
        pieces[f"target_return_{int(horizon)}d"] = future
        pieces[f"target_rank_{int(horizon)}d"] = future.rank(axis=1, pct=True)
    parts = [
        frame.rename_axis(index="date", columns="ticker").reset_index().melt(id_vars="date", var_name="ticker", value_name=name)
        for name, frame in pieces.items()
    ]
    long = parts[0]
    for part in parts[1:]:
        long = long.merge(part, on=["date", "ticker"], how="outer")
    long["date"] = long["date"].astype(str)
    long["ticker"] = long["ticker"].astype(str)
    long.insert(2, "split", split)
    return long.dropna(subset=["target_return_1d"]).sort_values(["date", "ticker"]).reset_index(drop=True)


def quantile_returns(scores: pd.DataFrame, forward_returns_frame: pd.DataFrame, *, n_quantiles: int = 5) -> pd.DataFrame:
    """Per date, the mean forward return of each score quantile (columns 1..n, 1 = lowest scores). Dates with fewer names
    than quantiles are skipped."""
    rows: dict[str, dict[int, float]] = {}
    aligned = forward_returns_frame.reindex(index=scores.index, columns=scores.columns)
    for day in scores.index:
        pair = pd.DataFrame({"s": scores.loc[day], "r": aligned.loc[day]}).replace([np.inf, -np.inf], np.nan).dropna()
        if len(pair) < int(n_quantiles):
            continue
        buckets = pd.qcut(pair["s"].rank(method="first"), int(n_quantiles), labels=False) + 1
        rows[str(day)] = pair.groupby(buckets)["r"].mean().to_dict()
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=range(1, int(n_quantiles) + 1))


def ic_decay(scores: pd.DataFrame, prices: pd.DataFrame, horizons: Sequence[int] = (1, 5, 10, 20, 60), *, min_names: int = 3) -> pd.Series:
    """Mean daily Spearman correlation between the scores and each horizon's forward return; NaN when no date has
    `min_names` names with both."""
    out: dict[int, float] = {}
    for horizon in horizons:
        future = forward_returns(prices, int(horizon)).reindex(index=scores.index, columns=scores.columns)
        values = []
        for day in scores.index:
            pair = pd.DataFrame({"s": scores.loc[day], "r": future.loc[day]}).replace([np.inf, -np.inf], np.nan).dropna()
            if len(pair) < int(min_names) or pair["s"].nunique() < 2 or pair["r"].nunique() < 2:
                continue
            values.append(float(pair["s"].rank().corr(pair["r"].rank())))
        out[int(horizon)] = float(np.mean(values)) if values else float("nan")
    return pd.Series(out, name="mean_ic", dtype=float)
