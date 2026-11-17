"""V5.4.3 - Hierarchical Risk Parity (HRP) allocation.

Implements López de Prado (2016)'s HRP algorithm as an alternative to the
current equal-rank long/short allocation. Builds a correlation-distance
dendrogram via scipy's linkage, then allocates by inverse-variance within
each cluster using a top-down recursive bisection.

Config-gated: `phase_v2.portfolio_book.allocation_method: "hrp"` (default
`"rank"` = byte-identical equal-rank behavior). Pure numpy/scipy — no I/O,
no torch."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

LINKAGE_METHODS = ("ward", "single", "average", "complete")


def compute_hrp_weights(returns: pd.DataFrame, linkage_method: str = "ward") -> pd.Series:
    """Computes HRP weights from a (dates × tickers) returns DataFrame.

    Steps:
    1. Correlation distance matrix: d = sqrt(0.5 * (1 - corr))
    2. Hierarchical clustering (`linkage_method` on the condensed distance; López de Prado uses "single")
    3. Quasi-diagonal ordering via dendrogram leaf order
    4. Top-down recursive bisection: split each cluster by inverse-variance

    A column with no variance (a flat or empty series) has no inverse variance, so it is left out: the result holds the
    other tickers only, summing to 1.0 (V6.6.9, #383: it used to turn every weight into NaN). Raises ValueError on an
    unknown linkage method."""
    if linkage_method not in LINKAGE_METHODS:
        raise ValueError(f"unknown linkage method {linkage_method!r}; expected one of {LINKAGE_METHODS}")
    variances = returns.var()
    tickers = [ticker for ticker in returns.columns if math.isfinite(float(variances[ticker])) and float(variances[ticker]) > 0.0]
    returns = returns[tickers]
    n = len(tickers)
    if n < 2:
        return pd.Series({t: 1.0 / max(n, 1) for t in tickers}, dtype=float)
    from scipy.cluster.hierarchy import leaves_list, linkage  # lazy: the library facade imports this module and scipy is optional
    from scipy.spatial.distance import squareform

    corr = returns.corr().fillna(0.0)
    covariance = returns.cov()

    # Correlation distance
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr.values), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)

    link = linkage(condensed, method=linkage_method)

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

            left_var = _cluster_var(covariance, [tickers[i] for i in left])
            right_var = _cluster_var(covariance, [tickers[i] for i in right])
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


def _cluster_var(covariance: pd.DataFrame, tickers_subset: list[str]) -> float:
    """Inverse-variance of a cluster = variance of the cluster's own
    inverse-variance-weighted portfolio."""
    block = covariance.loc[tickers_subset, tickers_subset].values
    ivp = 1.0 / np.diag(block)
    ivp /= ivp.sum()
    return float(ivp @ block @ ivp)


def aligned_returns(returns_by_ticker: dict[str, list[float]], tickers: list[str]) -> pd.DataFrame:
    """The frame HRP estimates on (V6.6.9, #383). The lists are return histories sampled on ONE calendar, newest last, so
    they are aligned at their END: the old positional alignment from the start put a different date in each column
    whenever the lengths differed. A list shorter than half the longest one (or under 2 returns) is left out rather than
    cutting every other history down to it; the caller gives such a name its leg's mean weight."""
    histories = {ticker: list(returns_by_ticker[ticker]) for ticker in tickers if ticker in returns_by_ticker}
    longest = max((len(values) for values in histories.values()), default=0)
    floor = max(2, math.ceil(longest / 2.0))
    usable = {ticker: values for ticker, values in histories.items() if len(values) >= floor}
    if not usable:
        return pd.DataFrame()
    length = min(len(values) for values in usable.values())
    return pd.DataFrame({ticker: values[-length:] for ticker, values in usable.items()}, dtype=float)


def _leg_weights(tickers: list[str], estimated: pd.Series, total: float) -> dict[str, float]:
    """One leg, summing to `total`: HRP proportions for the names it estimated, the mean of those for a name it could not
    (no history, no variance), equal weight when it estimated none."""
    if not tickers:
        return {}
    raw = {ticker: float(estimated[ticker]) for ticker in tickers if ticker in estimated.index and math.isfinite(float(estimated[ticker])) and float(estimated[ticker]) > 0.0}
    if not raw:
        return dict.fromkeys(tickers, total / len(tickers))
    mean = sum(raw.values()) / len(raw)
    filled = {ticker: raw.get(ticker, mean) for ticker in tickers}
    scale = total / sum(filled.values())
    return {ticker: value * scale for ticker, value in filled.items()}


def build_hrp_allocation(
    returns_by_ticker: dict[str, list[float]],
    *,
    selected_tickers_long: list[str],
    selected_tickers_short: list[str],
    gross_exposure: float = 1.0,
    linkage_method: str = "ward",
) -> dict[str, float]:
    """Builds an HRP-weighted allocation dict for the current book's long and
    short legs. With BOTH legs populated, longs get positive HRP weights ×
    gross/2 and shorts negative × gross/2 (dollar-neutral book). A
    SINGLE-SIDED book (one leg empty - e.g. the long-only book
    `phase5.backtest.strategy_mode: "long_flat"` produces, the shipped
    default) gives the present leg the FULL gross - V5.4.4 fix: the
    original unconditional gross/2 split silently halved a long-only
    book's exposure. Falls back to equal weight within each leg when HRP
    can't converge.

    `returns_by_ticker` must hold returns sampled on one calendar (`aligned_returns`). The result always covers exactly the
    selected names (V6.6.9, #383): a name HRP could not estimate gets the mean weight of its leg's estimated names
    instead of a silent zero."""
    all_selected = selected_tickers_long + selected_tickers_short
    if not all_selected:
        return {}

    # V5.4.4's single-sided/two-sided gross split, shared by the HRP path
    # below and the fallback here so they can never disagree.
    long_weight_total = gross_exposure / 2.0 if selected_tickers_short else gross_exposure
    short_weight_total = -(gross_exposure / 2.0 if selected_tickers_long else gross_exposure)

    def _equal_weight_fallback() -> dict[str, float]:
        # Equal weight WITHIN EACH LEG - each leg sums exactly to its own
        # leg total above. V5.4.5 (development/Problems.md #118): the
        # original fallback divided gross across BOTH legs combined
        # (`gross / len(longs + shorts)`), so an asymmetric two-sided book
        # (e.g. 6 longs / 2 shorts) came out with net exposure
        # +/-0.5*gross instead of dollar-neutral.
        return {**_leg_weights(selected_tickers_long, pd.Series(dtype=float), long_weight_total),
                **_leg_weights(selected_tickers_short, pd.Series(dtype=float), short_weight_total)}

    returns_df = aligned_returns(returns_by_ticker, all_selected)
    if returns_df.shape[1] < 2 or returns_df.empty:
        return _equal_weight_fallback()

    try:
        hrp_all = compute_hrp_weights(returns_df, linkage_method)
    except Exception:
        return _equal_weight_fallback()

    return {**_leg_weights(selected_tickers_long, hrp_all, long_weight_total),
            **_leg_weights(selected_tickers_short, hrp_all, short_weight_total)}
