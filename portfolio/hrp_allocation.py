"""V5.4.3 - Hierarchical Risk Parity (HRP) allocation.

Implements López de Prado (2016)'s HRP algorithm as an alternative to the
current equal-rank long/short allocation. Builds a correlation-distance
dendrogram via scipy's linkage, then allocates by inverse-variance within
each cluster using a top-down recursive bisection.

Config-gated: `phase_v2.portfolio_book.allocation_method: "hrp"` (default
`"rank"` = byte-identical equal-rank behavior). Pure numpy/scipy — no I/O,
no torch."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform


def compute_hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """Computes HRP weights from a (dates × tickers) returns DataFrame.

    Steps:
    1. Correlation distance matrix: d = sqrt(0.5 * (1 - corr))
    2. Hierarchical clustering (Ward linkage on condensed distance)
    3. Quasi-diagonal ordering via dendrogram leaf order
    4. Top-down recursive bisection: split each cluster by inverse-variance

    Returns per-ticker weights summing to 1.0."""
    tickers = returns.columns.tolist()
    corr = returns.corr().fillna(0.0)
    n = len(tickers)
    if n < 2:
        return pd.Series({t: 1.0 / max(n, 1) for t in tickers})

    # Correlation distance
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr.values), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)

    # Ward linkage
    link = linkage(condensed, method="ward")

    # Quasi-diagonal ordering (dendrogram leaf order)
    ordered = leaves_list(link).tolist()

    # Recursive bisection
    weights = pd.Series(1.0, index=[tickers[i] for i in ordered])
    cluster_items = [ordered]

    while len(cluster_items) > 0:
        next_clusters = []
        for items in cluster_items:
            if len(items) <= 1:
                continue
            half = len(items) // 2
            left, right = items[:half], items[half:]

            left_var = _cluster_var(returns, [tickers[i] for i in left])
            right_var = _cluster_var(returns, [tickers[i] for i in right])
            total = left_var + right_var
            if total <= 0:
                split = 0.5
            else:
                split = 1.0 - left_var / total

            for item in left:
                weights[tickers[item]] *= split
            for item in right:
                weights[tickers[item]] *= (1.0 - split)

            next_clusters.extend([left, right])
        cluster_items = next_clusters

    return weights / weights.sum()


def _cluster_var(returns: pd.DataFrame, tickers_subset: list[str]) -> float:
    """Inverse-variance of a cluster = variance of the cluster's own
    inverse-variance-weighted portfolio."""
    sub = returns[tickers_subset]
    ivp = 1.0 / np.diag(sub.cov().values)
    ivp /= ivp.sum()
    w = pd.Series(ivp, index=tickers_subset)
    return float(w @ sub.cov().values @ w)


def build_hrp_allocation(
    returns_by_ticker: dict[str, list[float]],
    *,
    selected_tickers_long: list[str],
    selected_tickers_short: list[str],
    gross_exposure: float = 1.0,
) -> dict[str, float]:
    """Builds an HRP-weighted allocation dict for the current book's long and
    short legs. With BOTH legs populated, longs get positive HRP weights ×
    gross/2 and shorts negative × gross/2 (dollar-neutral book). A
    SINGLE-SIDED book (one leg empty - e.g. the long-only book
    `phase5.backtest.strategy_mode: "long_flat"` produces, the shipped
    default) gives the present leg the FULL gross - V5.4.4 fix: the
    original unconditional gross/2 split silently halved a long-only
    book's exposure. Falls back to equal weight within each leg when HRP
    can't converge."""
    all_selected = selected_tickers_long + selected_tickers_short
    if not all_selected:
        return {}

    # V5.4.4's single-sided/two-sided gross split, shared by the HRP path
    # below and both fallbacks here so all three can never disagree.
    long_weight_total = gross_exposure / 2.0 if selected_tickers_short else gross_exposure
    short_weight_total = -(gross_exposure / 2.0 if selected_tickers_long else gross_exposure)

    def _equal_weight_fallback() -> dict[str, float]:
        # Equal weight WITHIN EACH LEG - each leg sums exactly to its own
        # leg total above. V5.4.5 (development/Problems.md #118): the
        # original fallback divided gross across BOTH legs combined
        # (`gross / len(longs + shorts)`), so an asymmetric two-sided book
        # (e.g. 6 longs / 2 shorts) came out with net exposure
        # +/-0.5*gross instead of dollar-neutral.
        result = {
            ticker: long_weight_total / max(len(selected_tickers_long), 1)
            for ticker in selected_tickers_long
        }
        for ticker in selected_tickers_short:
            result[ticker] = short_weight_total / max(len(selected_tickers_short), 1)
        return result

    returns_df = pd.DataFrame({
        ticker: pd.Series(returns_by_ticker[ticker])
        for ticker in all_selected
        if ticker in returns_by_ticker and len(returns_by_ticker[ticker]) >= 2
    })
    if returns_df.shape[1] < 2 or returns_df.empty:
        return _equal_weight_fallback()

    try:
        hrp_all = compute_hrp_weights(returns_df)
    except Exception:
        return _equal_weight_fallback()

    long_hrp_sum = sum(hrp_all.get(t, 0.0) for t in selected_tickers_long)
    short_hrp_sum = sum(hrp_all.get(t, 0.0) for t in selected_tickers_short)

    result = {}
    if long_hrp_sum > 0:
        for t in selected_tickers_long:
            result[t] = hrp_all.get(t, 0.0) / long_hrp_sum * long_weight_total
    else:
        for t in selected_tickers_long:
            result[t] = long_weight_total / max(len(selected_tickers_long), 1)

    if short_hrp_sum > 0:
        for t in selected_tickers_short:
            result[t] = -hrp_all.get(t, 0.0) / short_hrp_sum * abs(short_weight_total)
    else:
        for t in selected_tickers_short:
            result[t] = short_weight_total / max(len(selected_tickers_short), 1)

    return result
