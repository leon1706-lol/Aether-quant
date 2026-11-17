"""The book optimizer (V6.6.9): how one session's scores become raw weights.

The model book's old sizing was a formula per name (`min(max_w, 0.10 + 0.15 * confidence)`), blind to volatility and
correlation. Each function here takes one session's scores and the trailing daily returns of the same names, and returns
raw, unscaled weights; `portfolio.premia_signals.scale_and_cap` then applies the one volatility target and the caps, so
every optimizer is judged at the same risk.

Conventions: `scores` is a Series by ticker (NaN = no view), `returns` a (sessions x tickers) frame of daily returns
on the session calendar, newest last, `asset_class` maps a ticker to its class. A name without usable risk history gets
no weight; nothing here returns a NaN or raises on thin data.

numpy and pandas only at import (HRP imports scipy lazily).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from functools import partial

import numpy as np
import pandas as pd

MIN_CLASS_NAMES = 4
VOL_WINDOW = 60
LONG_WINDOW = 126
EMPTY = pd.Series(dtype=float)


def _volatility(returns: pd.DataFrame, window: int) -> pd.Series:
    """Daily volatility over the last `window` sessions; only names where it is finite and positive."""
    volatility = returns.iloc[-int(window):].std()
    return volatility[np.isfinite(volatility) & (volatility > 0.0)]


def _by_class(values: pd.Series, asset_class: Mapping[str, str]) -> list[pd.Series]:
    """The series split by class; a ticker of no known class belongs to none."""
    return [members for _, members in values.groupby(asset_class.get)] if len(values) else []


def _to_unit_gross(weights: pd.Series) -> pd.Series:
    gross = float(weights.abs().sum())
    return weights / gross if gross > 0.0 and math.isfinite(gross) else weights.iloc[0:0]


def centred_ranks(scores: pd.Series, asset_class: Mapping[str, str], min_names: int = MIN_CLASS_NAMES) -> pd.Series:
    """Per class, the percentile rank centred on zero. Ranks stay centred within a class, so knowing a name's class earns
    nothing (#259), and a class's gross follows its breadth. A class with fewer than `min_names` live names is left out.
    The same numbers as `premia_signals._raw_weights` for the pooled kind."""
    pieces = [
        members.rank(pct=True) - (len(members) + 1) / (2.0 * len(members))
        for members in _by_class(scores.dropna(), asset_class) if len(members) >= min_names
    ]
    return pd.concat(pieces) if pieces else EMPTY.copy()


def pooled(scores: pd.Series, returns: pd.DataFrame, asset_class: Mapping[str, str]) -> pd.Series:
    """Centred ranks as weights: the control every other optimizer is compared with."""
    return centred_ranks(scores, asset_class)


def inverse_vol_ranks(scores: pd.Series, returns: pd.DataFrame, asset_class: Mapping[str, str], vol_window: int = VOL_WINDOW) -> pd.Series:
    """Centred rank over volatility, each class then scaled to the same gross: a calm name and a wild one carry the same
    risk per unit of conviction, and no class dominates by being volatile."""
    ranks = centred_ranks(scores, asset_class)
    volatility = _volatility(returns.reindex(columns=ranks.index), vol_window)
    raw = (ranks.reindex(volatility.index) / volatility).dropna()
    pieces = [_to_unit_gross(members) for members in _by_class(raw, asset_class)]
    pieces = [piece for piece in pieces if len(piece)]
    return pd.concat(pieces) if pieces else EMPTY.copy()


def _sub_book_volatility(weights: pd.Series, returns: pd.DataFrame, window: int) -> float:
    covariance = returns.iloc[-int(window):].reindex(columns=weights.index).cov().fillna(0.0).to_numpy()
    vector = weights.to_numpy(dtype=float)
    variance = float(vector @ covariance @ vector)
    return math.sqrt(variance) if math.isfinite(variance) and variance > 0.0 else 0.0


def _equal_class_risk(sub_books: Sequence[pd.Series], returns: pd.DataFrame, window: int) -> pd.Series:
    """Each class's sub-book scaled by one over its own ex-ante volatility; a class whose risk can't be measured is dropped."""
    pieces = []
    for sub_book in sub_books:
        risk = _sub_book_volatility(sub_book, returns, window) if len(sub_book) else 0.0
        if risk > 0.0:
            pieces.append(sub_book / risk)
    return _to_unit_gross(pd.concat(pieces)) if pieces else EMPTY.copy()


def class_risk_parity(scores: pd.Series, returns: pd.DataFrame, asset_class: Mapping[str, str], vol_window: int = VOL_WINDOW) -> pd.Series:
    """Centred ranks within a class, then every class at the same ex-ante risk: the book's risk is shared by the classes,
    not by the names."""
    ranks = centred_ranks(scores, asset_class)
    known = ranks.reindex(_volatility(returns.reindex(columns=ranks.index), vol_window).index).dropna()
    return _equal_class_risk([_to_unit_gross(members) for members in _by_class(known, asset_class)], returns, vol_window)


def hrp_book(
    scores: pd.Series, returns: pd.DataFrame, asset_class: Mapping[str, str], window: int = LONG_WINDOW, fraction: float = 1.0 / 3.0,
    min_names: int = MIN_CLASS_NAMES,
) -> pd.Series:
    """Per class, the best and worst `fraction` by score, sized by hierarchical risk parity (single linkage, as López de
    Prado has it) on the last `window` sessions; the classes are then set to equal risk."""
    from portfolio.hrp_allocation import build_hrp_allocation

    sub_books = []
    measurable = _volatility(returns.reindex(columns=scores.index), window).index
    for members in _by_class(scores.dropna().reindex(measurable).dropna(), asset_class):
        if len(members) < min_names:
            continue
        ordered = members.sort_values(kind="mergesort")
        count = max(1, int(len(ordered) * fraction))
        longs, shorts = list(ordered.index[-count:]), list(ordered.index[:count])
        history = {ticker: returns[ticker].dropna().iloc[-int(window):].tolist() for ticker in (*longs, *shorts) if ticker in returns.columns}
        sub_books.append(pd.Series(build_hrp_allocation(history, selected_tickers_long=longs, selected_tickers_short=shorts, linkage_method="single"), dtype=float))
    return _equal_class_risk(sub_books, returns, VOL_WINDOW)


def shrunk_covariance(returns: pd.DataFrame, shrinkage: float) -> pd.DataFrame:
    """The sample covariance shrunk toward a constant-correlation target (same variances, the mean correlation everywhere
    else): `(1 - shrinkage) * S + shrinkage * F`. With many names and few sessions the sample matrix is too noisy to invert."""
    sample = returns.cov()
    deviation = np.sqrt(np.diag(sample.to_numpy()))
    outer = np.outer(deviation, deviation)
    count = len(deviation)
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = np.where(outer > 0.0, sample.to_numpy() / outer, 0.0)
    mean_correlation = float((correlation.sum() - count) / (count * (count - 1))) if count > 1 else 0.0
    target = mean_correlation * outer
    np.fill_diagonal(target, deviation**2)
    shrinkage = min(1.0, max(0.0, float(shrinkage)))
    return pd.DataFrame((1.0 - shrinkage) * sample.to_numpy() + shrinkage * target, index=sample.index, columns=sample.columns)


def shrunk_mean_variance(
    scores: pd.Series, returns: pd.DataFrame, asset_class: Mapping[str, str], window: int = LONG_WINDOW, shrinkage: float = 0.5,
) -> pd.Series:
    """Mean-variance with the centred rank as the forecast (`mu_i = rank_i * sigma_i`, a constant information coefficient)
    and a shrunk covariance: `w = pinv(Sigma) mu`. Only names with a full window of returns take part."""
    ranks = centred_ranks(scores, asset_class)
    history = returns.iloc[-int(window):].reindex(columns=ranks.index).dropna(axis=1, how="any")
    volatility = _volatility(history, len(history)) if len(history) > 1 else EMPTY
    if len(volatility) < 2:
        return EMPTY.copy()
    history = history[volatility.index]
    forecast = (ranks.reindex(volatility.index) * volatility).to_numpy(dtype=float)
    weights = np.linalg.pinv(shrunk_covariance(history, shrinkage).to_numpy()) @ forecast
    if not np.isfinite(weights).all():
        return EMPTY.copy()
    return _to_unit_gross(pd.Series(weights, index=volatility.index))


def risk_parity_core(returns: pd.DataFrame, asset_class: Mapping[str, str], vol_window: int = VOL_WINDOW) -> pd.Series:
    """Long-only and model-free: one over volatility within a class, every class at the same risk. What a multi-asset
    book earns from holding the classes, before any view."""
    inverse = 1.0 / _volatility(returns, vol_window)
    return _equal_class_risk([_to_unit_gross(members) for members in _by_class(inverse, asset_class)], returns, vol_window)


def tilted_core(
    scores: pd.Series, returns: pd.DataFrame, asset_class: Mapping[str, str], kappa: float = 1.0, vol_window: int = VOL_WINDOW,
    z_cap: float = 2.0,
) -> pd.Series:
    """The risk-parity core tilted by the view: `core_i * max(0, 1 + kappa * z_i)`, `z_i` the score's z-score within its
    class, capped. Long-only by construction; a name with no view, or in a class too small to rank, keeps its core weight."""
    core = risk_parity_core(returns, asset_class, vol_window)
    tilt = pd.Series(1.0, index=core.index)
    for members in _by_class(scores.reindex(core.index).dropna(), asset_class):
        spread = float(members.std(ddof=0)) if len(members) >= MIN_CLASS_NAMES else 0.0
        if spread > 0.0 and math.isfinite(spread):
            z_score = ((members - members.mean()) / spread).clip(-z_cap, z_cap)
            tilt[members.index] = (1.0 + float(kappa) * z_score).clip(lower=0.0)
    tilted = core * tilt
    return _to_unit_gross(tilted[tilted > 0.0])


def no_trade_band(current: Mapping[str, float], target: Mapping[str, float], band: float = 0.25) -> dict[str, float]:
    """Keep a held weight while the new target is within `band` of it, relative to the larger of the two: small changes
    cost more to trade than they are worth. A name the target drops always goes; applying it twice changes nothing."""
    band = max(0.0, float(band))
    out: dict[str, float] = {}
    for ticker, wanted in target.items():
        wanted = float(wanted)
        held = float(current.get(ticker, 0.0))
        keep = held != 0.0 and abs(wanted - held) <= band * max(abs(wanted), abs(held))
        value = held if keep else wanted
        if value != 0.0:
            out[ticker] = value
    return out


def class_gross(row: Mapping[str, float], asset_class: Mapping[str, str]) -> dict[str, float]:
    """Gross weight per class of one row."""
    out: dict[str, float] = {}
    for ticker, weight in row.items():
        name = str(asset_class.get(ticker))
        out[name] = out.get(name, 0.0) + abs(float(weight))
    return out


def drop_classes(row: Mapping[str, float], asset_class: Mapping[str, str], classes: Sequence[str]) -> dict[str, float]:
    """The row without the names of `classes` (a suspended class holds nothing)."""
    blocked = set(classes)
    return {ticker: float(weight) for ticker, weight in row.items() if asset_class.get(ticker) not in blocked}


def paper_loss_guard(increments: Sequence[float], *, lookback: int, max_loss: float) -> bool:
    """Whether a class may be held: its own unguarded sub-book, on paper, has `lookback` sessions of record and its
    trailing drawdown over them is within `max_loss` (a fraction of the book). It reads only the paper record, never what
    was really held, so it needs no memory: a class comes back when its paper loss has healed, and one with too little
    record stays out."""
    from portfolio.sleeve_guard import trailing_drawdown

    lookback = int(lookback)
    if lookback <= 0 or len(increments) < lookback:
        return False
    return trailing_drawdown(increments, lookback) <= float(max_loss)


class ClassLossGuard:
    """A stateful `guard(date, row)` for `signal_to_weights`: a guarded class is held only while its own unguarded sub-book,
    on paper, has not lost more than `max_loss` of the book over the last `lookback` sessions (`paper_loss_guard`). The
    sub-book's daily increment is the previous row's class weights times the session's returns, so the guard reads nothing
    from the date it decides. A class with fewer than `lookback` sessions of record stays out."""

    def __init__(self, daily: pd.DataFrame, asset_class: Mapping[str, str], classes: Sequence[str], *, lookback: int = 60, max_loss: float = 0.01) -> None:
        self._daily = daily
        self._classes = tuple(classes)
        self._asset_class = asset_class
        self._lookback = int(lookback)
        self._max_loss = float(max_loss)
        self._increments: dict[str, list[float]] = {name: [] for name in self._classes}
        self._previous_date: str | None = None
        self._previous_row: dict[str, float] = {}

    def _record(self, date: str) -> None:
        if self._previous_date is None:
            return
        sessions = self._daily.loc[(self._daily.index > self._previous_date) & (self._daily.index <= date)]
        for name in self._classes:
            held = [ticker for ticker, weight in self._previous_row.items() if self._asset_class.get(ticker) == name and weight != 0.0]
            if not held:
                self._increments[name].extend([0.0] * len(sessions))
                continue
            moves = sessions.reindex(columns=held).fillna(0.0).mul(pd.Series({ticker: self._previous_row[ticker] for ticker in held}), axis=1)
            self._increments[name].extend(moves.sum(axis=1).tolist())

    def __call__(self, date: str, row: dict[str, float]) -> dict[str, float]:
        self._record(date)
        self._previous_date, self._previous_row = date, dict(row)
        blocked = [name for name in self._classes if not paper_loss_guard(self._increments[name], lookback=self._lookback, max_loss=self._max_loss)]
        return drop_classes(row, self._asset_class, blocked) if blocked else dict(row)


def stress_scaler(ratio: pd.Series, threshold: float, factor: float = 0.5) -> Callable[[str, dict[str, float]], dict[str, float]]:
    """A `guard(date, row)` that multiplies the whole row by `factor` on a session whose `ratio` (VIX over VIX3M, as known
    then) is above `threshold`. A missing ratio leaves the row alone."""
    values = ratio.astype(float)

    def guard(date: str, row: dict[str, float]) -> dict[str, float]:
        level = values.get(date)
        scaled = level is not None and bool(pd.notna(level)) and float(level) > float(threshold)
        return {ticker: weight * float(factor) for ticker, weight in row.items()} if scaled else dict(row)

    return guard


def _core_only(scores: pd.Series, returns: pd.DataFrame, asset_class: Mapping[str, str], **params: float) -> pd.Series:
    return risk_parity_core(returns, asset_class, **params)


OPTIMIZERS: dict[str, Callable[..., pd.Series]] = {
    "pooled": pooled,
    "inverse_vol": inverse_vol_ranks,
    "class_risk_parity": class_risk_parity,
    "hrp": hrp_book,
    "mean_variance": shrunk_mean_variance,
    "tilted_core": tilted_core,
    "core": _core_only,
}
OPTIMIZER_PARAMS: dict[str, tuple[str, ...]] = {
    "pooled": (), "inverse_vol": ("vol_window",), "class_risk_parity": ("vol_window",), "hrp": ("window", "fraction"),
    "mean_variance": ("window", "shrinkage"), "tilted_core": ("kappa", "vol_window", "z_cap"), "core": ("vol_window",),
}


def optimizer_for(params: Mapping[str, object] | None) -> Callable[[pd.Series, pd.DataFrame, Mapping[str, str]], pd.Series] | None:
    """The optimizer a definition names under `"optimizer"`, with the parameters it carries; None when it names none (the
    path then sizes as before). The set is closed: an unknown name is an error, never an import."""
    name = (params or {}).get("optimizer")
    if name is None:
        return None
    if name not in OPTIMIZERS:
        raise ValueError(f"unknown optimizer {name!r}; expected one of {sorted(OPTIMIZERS)}")
    settings = {key: params[key] for key in OPTIMIZER_PARAMS[str(name)] if key in params}
    return partial(OPTIMIZERS[str(name)], **settings) if settings else OPTIMIZERS[str(name)]
