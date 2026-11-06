"""Signal tables of V6.6.0's wide trials: session x ticker, higher is better, each known at that session's close.

They reach `portfolio.premia_signals` through its `external_score` family, so they run the same weight pipeline, placebos and engine as
every earlier sleeve. A signal is masked to members, and a name with no sector is never ranked.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

# Signal per trial, a feature's name with its sign. Composites are the equal mean of cross-sectional ranks; nothing here is fitted.
SINGLE = {
    "w01": ("gp_assets", 1.0), "w02": ("net_issuance", -1.0), "w03": ("asset_growth", -1.0), "w04": ("accruals", -1.0), "w07": ("sue", 1.0),
    "w08": ("insider_net_180", 1.0), "w09": ("resmom_252", 1.0), "w10": ("overnight_ret_252", 1.0), "w11": ("dist_52w_high", 1.0), "w12": ("beta_252", -1.0),
    "w13": ("short_ratio_20", -1.0), "w14": ("resrev_5", 1.0),
}
COMPOSITES = {
    "w05": (("earnings_yield", 1.0), ("book_to_market", 1.0)),
    "w06": (("gp_assets", 1.0), ("leverage", -1.0), ("accruals", -1.0), ("cfo_assets", 1.0)),
}
W15_PARTS = ("w01", "w02", "w04", "w05", "w07", "w09")
MIN_COMPOSITE_PARTS = {"w05": 1, "w06": 2, "w15": 3}


def cross_sectional_rank(table: pd.DataFrame) -> pd.DataFrame:
    return table.rank(axis=1, pct=True)


def rank_mean(tables: list[pd.DataFrame], *, minimum: int) -> pd.DataFrame:
    """The mean of each table's cross-sectional rank, where at least `minimum` of them have a value."""
    ranks = [cross_sectional_rank(table) for table in tables]
    total = sum(rank.fillna(0.0) for rank in ranks)
    count = sum(rank.notna().astype(float) for rank in ranks)
    return (total / count.where(count > 0.0)).where(count >= float(minimum))


def wide_tables(features: Mapping[str, pd.DataFrame], member: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Every w-trial's table that its features allow. A feature all NaN (no data for this window) leaves its trial with an empty book,
    which the minimum-names check reports rather than reading as no skill."""
    tables: dict[str, pd.DataFrame] = {}
    for trial, (name, sign) in SINGLE.items():
        if name in features:
            tables[trial] = features[name] * sign
    for trial, parts in COMPOSITES.items():
        present = [features[name] * sign for name, sign in parts if name in features]
        if present:
            tables[trial] = rank_mean(present, minimum=MIN_COMPOSITE_PARTS[trial])
    parts = [tables[trial] for trial in W15_PARTS if trial in tables]
    if parts:
        tables["w15"] = rank_mean(parts, minimum=MIN_COMPOSITE_PARTS["w15"])
    return {trial: table.where(member.reindex(index=table.index, columns=table.columns, fill_value=False)) for trial, table in tables.items()}


def crypto_tables(known: pd.DataFrame, funding: pd.DataFrame | None, liquid: pd.DataFrame, btc: str = "BTCUSD") -> dict[str, pd.DataFrame]:
    """c1-c4, session x coin, masked to the liquid set. `known` already holds each coin's bar from before the session, and funding is
    shifted the same way: a day's settlements aren't all known at that day's equity close."""
    daily = known.pct_change(fill_method=None)
    bench = daily[btc]
    beta = daily.rolling(60, min_periods=60).cov(bench).div(bench.rolling(60, min_periods=60).var(), axis=0).shift(1)
    residual = daily.sub(beta.mul(bench, axis=0))
    tables = {"c1": known / known.shift(28) - 1.0, "c2": residual.rolling(60, min_periods=60).sum()}
    if funding is not None and not funding.empty:
        cost = funding.reindex(columns=known.columns).sort_index()
        seven_days = cost.rolling(7, min_periods=3).mean().shift(1)
        crowding = -seven_days.reindex(seven_days.index.union(known.index)).ffill().reindex(known.index)
        tables["c3"] = crowding
        tables["c4"] = rank_mean([tables["c1"], crowding], minimum=2)
    return {trial: table.where(liquid.reindex(index=table.index, columns=table.columns, fill_value=False)) for trial, table in tables.items()}


def live_names_per_rebalance(table: pd.DataFrame, rebalance_every: int) -> dict[str, float]:
    """How many names a signal can rank, on the days it decides: an empty book must not read as a sleeve with no skill."""
    counts = table.notna().sum(axis=1).to_numpy(dtype=float)[::max(1, rebalance_every)]
    if counts.size == 0:
        return {"median": 0.0, "minimum": 0.0}
    return {"median": float(np.median(counts)), "minimum": float(counts.min())}
