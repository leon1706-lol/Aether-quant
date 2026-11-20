"""How a signal's alpha behaves (V6.6.10, R-ALPHA1): over which horizon it predicts, how fast that fades, where it lives, what it costs
to trade, and how much of it is a known premium in disguise.

Every input is a wide table (session x ticker): `scores` as known at the session (higher = expected to do better), `closes` the
known closes. A diagnostic selects nothing and counts as no trial; R-ALPHA1 only uses it to write the R-BOOK2 list.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from evaluation.rank_ic_core import newey_west_t_stat

HORIZONS = (1, 5, 10, 20, 40, 60)
MIN_NAMES = 5


def forward_returns(closes: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """The return from each session's close to the close `horizon` sessions later (NaN where that close does not exist)."""
    return closes.shift(-horizon) / closes - 1.0


def session_rank_ic(scores: pd.DataFrame, outcome: pd.DataFrame, *, min_names: int = MIN_NAMES) -> pd.Series:
    """Per session, the Spearman correlation across tickers of the score with the outcome; NaN where fewer than `min_names` names have
    both, or either side has no spread."""
    scores, outcome = scores.align(outcome, join="inner")
    both = scores.notna() & outcome.notna()
    score_rank = scores.where(both).rank(axis=1)
    outcome_rank = outcome.where(both).rank(axis=1)
    sx = score_rank.sub(score_rank.mean(axis=1), axis=0)
    sy = outcome_rank.sub(outcome_rank.mean(axis=1), axis=0)
    denominator = np.sqrt((sx ** 2).sum(axis=1) * (sy ** 2).sum(axis=1))
    ic = (sx * sy).sum(axis=1) / denominator.where(denominator > 0)
    return ic.where(both.sum(axis=1) >= min_names)


def ic_summary(ic: pd.Series, *, lags: int) -> dict[str, Any]:
    """Mean, Newey-West t (lags ~ horizon - 1) and count of an IC series."""
    values = ic.dropna()
    if values.empty:
        return {"mean_ic": None, "t_hac": None, "n": 0}
    return {"mean_ic": float(values.mean()), "t_hac": float(newey_west_t_stat(values.to_numpy(), lags=max(0, int(lags)))), "n": int(len(values))}


def ic_term_structure(scores: pd.DataFrame, closes: pd.DataFrame, horizons: Sequence[int] = HORIZONS) -> dict[int, dict[str, Any]]:
    """The IC against the forward return over each horizon: where in time the signal's information sits."""
    return {int(h): ic_summary(session_rank_ic(scores, forward_returns(closes, int(h))), lags=int(h) - 1) for h in horizons}


def ic_lag_profile(scores: pd.DataFrame, closes: pd.DataFrame, *, step: int = 5, lags: int = 12) -> dict[int, float | None]:
    """The IC of a score held k*step sessions stale against the next `step`-session return: how fast the information fades."""
    outcome = forward_returns(closes, step)
    profile: dict[int, float | None] = {}
    for k in range(lags):
        summary = ic_summary(session_rank_ic(scores, outcome.shift(-k * step)), lags=step - 1)
        profile[k * step] = summary["mean_ic"]
    return profile


def half_life(profile: Mapping[int, float | None]) -> float | None:
    """Sessions until the stale IC halves, from a log-linear fit over the leading run of positive ICs; None when the first IC is not
    positive, fewer than two points are positive, or the fit does not decay."""
    points = []
    for lag in sorted(profile):
        value = profile[lag]
        if value is None or not value > 0:
            break
        points.append((float(lag), math.log(value)))
    if len(points) < 2:
        return None
    x, y = np.array([p[0] for p in points]), np.array([p[1] for p in points])
    slope = float(np.polyfit(x, y, 1)[0])
    return math.log(2.0) / -slope if slope < 0 else None


def ic_by_group(scores: pd.DataFrame, outcome: pd.DataFrame, groups: Mapping[str, str], *, min_names: int = 3, lags: int = 0) -> dict[str, dict[str, Any]]:
    """The IC within each group of tickers (an asset class, a sector)."""
    out = {}
    for group in sorted(set(groups.values())):
        members = [ticker for ticker in scores.columns if groups.get(ticker) == group]
        out[group] = ic_summary(session_rank_ic(scores[members], outcome.reindex(columns=members), min_names=min_names), lags=lags)
    return out


def ic_by_period(ic: pd.Series, labels: pd.Series, *, lags: int = 0) -> dict[str, dict[str, Any]]:
    """The IC series cut by a label per session (a year, a regime). Sessions without a label are left out."""
    labels = labels.reindex(ic.index)
    return {str(label): ic_summary(ic[labels == label], lags=lags) for label in sorted(labels.dropna().unique(), key=str)}


def rank_weights(scores: pd.DataFrame) -> pd.DataFrame:
    """Dollar-neutral weights from each session's ranks: centred, scaled to a gross of one."""
    centred = scores.rank(axis=1, pct=True).sub(scores.rank(axis=1, pct=True).mean(axis=1), axis=0)
    gross = centred.abs().sum(axis=1)
    return centred.div(gross.where(gross > 0), axis=0)


def spread_after_costs(scores: pd.DataFrame, closes: pd.DataFrame, *, horizon: int = 20, cost_bps: float = 10.0) -> dict[str, Any]:
    """The rank-weighted long-short book rebalanced every `horizon` sessions: its gross return per rebalance, its turnover (half the sum
    of absolute weight changes) and the return left after paying `cost_bps` on every unit traded, annualised at 252 sessions."""
    sessions = scores.index[::horizon]
    weights = rank_weights(scores.loc[sessions]).fillna(0.0)
    realised = forward_returns(closes, horizon).reindex(index=sessions, columns=weights.columns)
    gross = (weights * realised.fillna(0.0)).sum(axis=1)
    turnover = weights.diff().abs().sum(axis=1).fillna(weights.abs().sum(axis=1)) / 2.0
    net = gross - 2.0 * turnover * cost_bps / 1e4
    periods = 252.0 / horizon
    return {
        "rebalances": int(len(sessions)), "turnover": float(turnover.mean()) if len(turnover) else None,
        "gross_annual": float(gross.mean() * periods) if len(gross) else None, "net_annual": float(net.mean() * periods) if len(net) else None,
    }


def premia_exposure(scores: pd.DataFrame, factors: Mapping[str, pd.DataFrame], *, min_names: int = MIN_NAMES) -> dict[str, Any]:
    """Per session, a cross-sectional least-squares fit of the score's ranks on the factors' ranks (with an intercept): the mean of
    each factor's coefficient, the mean R-squared, and the residual score table (what the factors don't explain)."""
    names = list(factors)
    betas: dict[str, list[float]] = {name: [] for name in names}
    r_squared: list[float] = []
    residual = pd.DataFrame(np.nan, index=scores.index, columns=scores.columns)
    ranked = {name: table.reindex(index=scores.index, columns=scores.columns).rank(axis=1, pct=True) for name, table in factors.items()}
    score_rank = scores.rank(axis=1, pct=True)
    for session in scores.index:
        y = score_rank.loc[session]
        x = pd.DataFrame({name: ranked[name].loc[session] for name in names})
        usable = y.notna() & x.notna().all(axis=1)
        if int(usable.sum()) < max(min_names, len(names) + 2):
            continue
        design = np.column_stack([np.ones(int(usable.sum())), x[usable].to_numpy(dtype=float)])
        target = y[usable].to_numpy(dtype=float)
        coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
        fitted = design @ coefficients
        total = float(((target - target.mean()) ** 2).sum())
        r_squared.append(1.0 - float(((target - fitted) ** 2).sum()) / total if total > 1e-12 * len(target) else 0.0)  # a constant score's ranks carry float noise
        for index, name in enumerate(names):
            betas[name].append(float(coefficients[index + 1]))
        residual.loc[session, usable[usable].index] = target - fitted
    return {
        "betas": {name: (float(np.mean(values)) if values else None) for name, values in betas.items()},
        "r_squared": float(np.mean(r_squared)) if r_squared else None, "sessions": len(r_squared), "residual": residual,
    }


def breadth(scores: pd.DataFrame, groups: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The mean number of names with a score per session, overall and per group."""
    counts = scores.notna().sum(axis=1)
    out: dict[str, Any] = {"mean_names": float(counts.mean()) if len(counts) else 0.0}
    if groups:
        out["by_group"] = {
            group: float(scores[[t for t in scores.columns if groups.get(t) == group]].notna().sum(axis=1).mean()) for group in sorted(set(groups.values()))
        }
    return out


def alpha_report(scores: pd.DataFrame, closes: pd.DataFrame, *, groups: Mapping[str, str], factors: Mapping[str, pd.DataFrame],
                 regimes: pd.Series | None = None, horizon: int = 20, cost_bps: float = 10.0) -> dict[str, Any]:
    """R-ALPHA1's whole report for one signal: every diagnostic above, the residual IC after the factors, and nothing it selects."""
    outcome = forward_returns(closes, horizon)
    ic = session_rank_ic(scores, outcome)
    profile = ic_lag_profile(scores, closes)
    exposure = premia_exposure(scores, factors)
    years = pd.Series([str(pd.Timestamp(day).year) for day in ic.index], index=ic.index)
    report = {
        "term_structure": ic_term_structure(scores, closes),
        "lag_profile": profile,
        "half_life_sessions": half_life(profile),
        "by_class": ic_by_group(scores, outcome, groups, lags=horizon - 1),
        "by_year": ic_by_period(ic, years, lags=horizon - 1),
        "spread": spread_after_costs(scores, closes, horizon=horizon, cost_bps=cost_bps),
        "premia": {key: value for key, value in exposure.items() if key != "residual"},
        "residual_ic": ic_summary(session_rank_ic(exposure["residual"], outcome), lags=horizon - 1),
        "breadth": breadth(scores, groups),
    }
    if regimes is not None:
        report["by_regime"] = ic_by_period(ic, regimes, lags=horizon - 1)
    return report
