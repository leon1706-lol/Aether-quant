"""Rule-based sleeves and the weight pipeline of V6.5.0 (`portfolio/target_weights.py` runs what this produces).

A signal is a table of session x ticker, each row known at that session's equity close: equity closes of the session
itself, crypto and forex closes of the bars dated before it (`known_closes`, the timing of `features/cross_asset_timing.py`),
FRED series lagged a day. NaN means "not tradable today". `tests/test_premia_signals.py::test_no_lookahead` holds every
sleeve to it: a signal computed on data cut at D equals row D computed on all the data.

`signal_to_weights` turns a signal into target weights: within-class ranks (each class its own budget, so a pooled rank
cannot reward group size, Problems.md #259) or per-asset risk-scaled directions, then one ex-ante volatility target,
then the caps. Nothing here is fitted to returns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from portfolio.target_weights import NEXT_BAR_CLASSES

TRADING_DAYS = 252.0
VOL_WINDOW = 60
MIN_HISTORY = 61
XS = "cross_sectional"
TS = "time_series"
DIRECT = "direct"
POOLED = "cross_sectional_pooled"
RISK_ASSETS_TREND = ("SPY", "QQQ", "IWM", "EEM", "TLT", "IEF", "USO")


@dataclass(frozen=True)
class WeightSettings:
    target_vol: float = 0.07
    gross_cap: float = 1.4
    name_cap: float = 0.15
    class_caps: Mapping[str, float] = field(default_factory=lambda: {"crypto": 0.15})
    name_cap_by_class: Mapping[str, float] = field(default_factory=lambda: {"crypto": 0.05})


@dataclass(frozen=True)
class SleeveSpec:
    id: str
    track: str
    kind: str
    family: str
    universe: tuple[str, ...]
    rebalance_every: int
    params: Mapping[str, float] = field(default_factory=dict)


@dataclass
class ResearchPanel:
    """What sleeves may read: `known` closes by session, each ticker's class, and FRED series as {key: dated rows}."""

    known: pd.DataFrame
    asset_class: Mapping[str, str]
    fred: Mapping[str, pd.Series] = field(default_factory=dict)
    extras: Mapping[str, pd.DataFrame] = field(default_factory=dict)

    def truncated(self, end: str) -> ResearchPanel:
        return ResearchPanel(
            self.known[self.known.index <= end], self.asset_class,
            {key: series[series.index <= end] for key, series in self.fred.items()},
            {key: frame[frame.index <= end] for key, frame in self.extras.items()},
        )


def known_closes(dates: list[str], tickers: list[str], closes: np.ndarray, asset_class: Mapping[str, str], sessions: set[str]) -> pd.DataFrame:
    """Closes known at each session's equity close. A crypto or forex bar dated D closes at the midnight after that
    close, so on session D the latest usable bar of those classes is the one dated before D."""
    frame = pd.DataFrame(closes, index=dates, columns=tickers, dtype=float).ffill()
    lagged = [ticker for ticker in tickers if asset_class.get(ticker) in NEXT_BAR_CLASSES]
    frame[lagged] = frame[lagged].shift(1)
    return frame.loc[[date for date in dates if date in sessions]]


def fred_series_table(fred_rows: Mapping[str, list[dict]], keys: tuple[str, ...]) -> dict[str, pd.Series]:
    """{key: value by date string} from `load_cached_fred_series()` rows."""
    out: dict[str, pd.Series] = {}
    for key in keys:
        rows = fred_rows.get(key) or []
        pairs = {str(row["date"])[:10]: row.get("value") for row in rows}
        series = pd.to_numeric(pd.Series(pairs, dtype=object), errors="coerce").dropna().sort_index()
        out[key] = series.astype(float)
    return out


def _asof(series: pd.Series, sessions: pd.Index, *, lag_sessions: int = 1) -> pd.Series:
    """The value published by each session's close, a session late: FRED's daily marks post after the equity tick."""
    if series is None or series.empty:
        return pd.Series(np.nan, index=sessions)
    union = series.reindex(series.index.union(sessions)).ffill()
    return union.reindex(sessions).shift(lag_sessions)


def _columns(panel: ResearchPanel, universe: tuple[str, ...]) -> list[str]:
    return [ticker for ticker in panel.known.columns if panel.asset_class.get(ticker) in universe or ticker in universe]


def _returns_over(known: pd.DataFrame, window: int, skip: int = 0) -> pd.DataFrame:
    return known.shift(skip) / known.shift(window) - 1.0


def _residual_daily(known: pd.DataFrame, market: str = "SPY", window: int = VOL_WINDOW) -> pd.DataFrame:
    daily = known.pct_change(fill_method=None)
    bench = daily[market]
    covariance = daily.rolling(window, min_periods=window).cov(bench)
    variance = bench.rolling(window, min_periods=window).var()
    beta = covariance.div(variance, axis=0).shift(1)
    return daily.sub(beta.mul(bench, axis=0))


def _zscore(series: pd.Series, window: int = 252) -> pd.Series:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std()
    return ((series - mean) / std).replace([np.inf, -np.inf], np.nan).clip(-2.0, 2.0) / 2.0


def _direct(panel: ResearchPanel, exposures: Mapping[str, pd.Series]) -> pd.DataFrame:
    frame = pd.DataFrame(np.nan, index=panel.known.index, columns=panel.known.columns)
    for ticker, series in exposures.items():
        if ticker in frame.columns:
            frame[ticker] = series.reindex(frame.index)
    return frame


def crypto_trend(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Long while the trailing return over the lookback is positive; flat otherwise (long-only: no reliable short venue)."""
    known = panel.known[_columns(panel, spec.universe)]
    lookbacks = [int(value) for key, value in spec.params.items() if key.startswith("lookback")]
    votes = [(_returns_over(known, lookback) > 0.0).astype(float).where(known.shift(lookback).notna()) for lookback in lookbacks]
    return sum(votes) / len(votes)


def cross_sectional_return(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Rank on the trailing return over `lookback`, skipping the last `skip` sessions."""
    known = panel.known[_columns(panel, spec.universe)]
    return _returns_over(known, int(spec.params["lookback"]), int(spec.params.get("skip", 0)))


def fx_carry_signal(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Rank on the 3-month rate differential; `momentum_weight` adds a rank of the trailing 63-session return."""
    known = panel.known[_columns(panel, spec.universe)]
    carry = panel.extras["fx_carry"].reindex(index=known.index, columns=known.columns).where(known.notna())
    weight = float(spec.params.get("momentum_weight", 0.0))
    if weight <= 0.0:
        return carry
    momentum = _returns_over(known, 63)
    return carry.rank(axis=1, pct=True) * (1.0 - weight) + momentum.rank(axis=1, pct=True) * weight


def residual_reversal(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Rank against the market-residual return of the last `window` sessions."""
    known = panel.known
    residual = _residual_daily(known)[_columns(panel, spec.universe)]
    return -residual.rolling(int(spec.params["window"]), min_periods=int(spec.params["window"])).sum()


def residual_momentum(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Rank on the market-residual return from `lookback` to `skip` sessions ago."""
    residual = _residual_daily(panel.known)[_columns(panel, spec.universe)]
    lookback, skip = int(spec.params["lookback"]), int(spec.params["skip"])
    return residual.shift(skip).rolling(lookback - skip, min_periods=lookback - skip).sum()


def low_volatility(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    known = panel.known[_columns(panel, spec.universe)]
    return -known.pct_change(fill_method=None).rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()


def time_series_momentum(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Direction of the trailing return, averaged over the lookbacks."""
    columns = [ticker for ticker in _columns(panel, spec.universe) if not spec.params.get("trend_set") or ticker in RISK_ASSETS_TREND]
    known = panel.known[columns]
    lookbacks = [int(value) for key, value in spec.params.items() if key.startswith("lookback")]
    votes = [np.sign(_returns_over(known, lookback)) for lookback in lookbacks]
    return sum(votes) / len(votes)


def bond_slope_timing(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Long duration against the short end while the 10y-3m slope is above its one-year mean, and the reverse."""
    sessions = panel.known.index
    slope = _asof(panel.fred.get("treasury_10yr"), sessions) - _asof(panel.fred.get("treasury_3mo"), sessions)
    tilt = _zscore(slope)
    return _direct(panel, {"IEF": tilt * 0.5, "TLT": tilt * 0.5, "SHY": -tilt})


def bond_credit_timing(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Long credit against duration while the BAA spread is narrowing over the last quarter, and the reverse."""
    sessions = panel.known.index
    spread = _asof(panel.fred.get("credit_spread_baa10y"), sessions)
    tilt = _zscore(-(spread - spread.shift(63)))
    return _direct(panel, {"HYG": tilt, "LQD": tilt, "IEF": -2.0 * tilt})


def vix_term_structure(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Long SPY while VIX is below VIX3M. `threshold` gives an on/off rule; without it, exposure grows with the gap."""
    sessions = panel.known.index
    ratio = _asof(panel.fred.get("implied_volatility_vix"), sessions) / _asof(panel.fred.get("implied_volatility_3m"), sessions)
    threshold = spec.params.get("threshold")
    if threshold is not None:
        exposure = (ratio < float(threshold)).astype(float).where(ratio.notna())
    else:
        exposure = ((1.0 - ratio) / 0.1).clip(0.0, 1.0)
    return _direct(panel, {"SPY": exposure})


def turn_of_month(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """Hold SPY over the month's last session and the next three. A decision is filled at the next open, so the holding
    days are decided one session earlier. Calendar arithmetic only (weekdays, no holiday table: never reads the future)."""
    sessions = pd.DatetimeIndex(panel.known.index)
    exposure = np.zeros(len(sessions))
    for position, day in enumerate(sessions):
        month_end = (day + pd.offsets.BMonthEnd(0)).normalize()
        weekdays_left = int(np.busday_count(day.date(), month_end.date()))
        weekdays_in = int(np.busday_count(day.replace(day=1).date(), day.date()))
        # holding tomorrow means: tomorrow is the month's last weekday, or among the first three of the next month
        holds_tomorrow = weekdays_left <= 1 or weekdays_in <= 1
        exposure[position] = 1.0 if holds_tomorrow else 0.0
    return _direct(panel, {"SPY": pd.Series(exposure, index=panel.known.index)})


def external_score(panel: ResearchPanel, spec: SleeveSpec) -> pd.DataFrame:
    """A score table computed elsewhere (a walk-forward model, COT positioning, earnings surprise), already as of each session."""
    known = panel.known[_columns(panel, spec.universe)]
    return panel.extras[spec.params["table"]].reindex(index=known.index, columns=known.columns)


def align_score_table(table: pd.DataFrame, asset_class: Mapping[str, str]) -> pd.DataFrame:
    """A score table keyed by dataset date: a crypto or forex score dated D reads bar D, which closes after D's equity
    decision, so it may only be used a row later. `test_no_lookahead` can't see into a precomputed table."""
    aligned = table.copy()
    late = [ticker for ticker in aligned.columns if asset_class.get(ticker) in NEXT_BAR_CLASSES]
    aligned[late] = aligned[late].shift(1)
    return aligned


FAMILIES: dict[str, Callable[[ResearchPanel, SleeveSpec], pd.DataFrame]] = {
    "crypto_trend": crypto_trend,
    "cross_sectional_return": cross_sectional_return,
    "fx_carry": fx_carry_signal,
    "residual_reversal": residual_reversal,
    "residual_momentum": residual_momentum,
    "low_volatility": low_volatility,
    "time_series_momentum": time_series_momentum,
    "bond_slope_timing": bond_slope_timing,
    "bond_credit_timing": bond_credit_timing,
    "vix_term_structure": vix_term_structure,
    "turn_of_month": turn_of_month,
    "external_score": external_score,
}


def sleeve_signal(spec: SleeveSpec, panel: ResearchPanel) -> pd.DataFrame:
    signal = FAMILIES[spec.family](panel, spec)
    # a signal never trades a ticker without enough price history for its risk estimate
    history = panel.known[signal.columns].notna().rolling(MIN_HISTORY, min_periods=MIN_HISTORY).sum() >= MIN_HISTORY
    return signal.where(history)


def _raw_weights(row: pd.Series, kind: str, volatility: pd.Series, asset_class: Mapping[str, str], top_k: int | None = None) -> pd.Series:
    live = row.dropna()
    if live.empty:
        return pd.Series(dtype=float)
    if kind == XS:
        pieces = []
        for _, members in live.groupby(lambda ticker: asset_class.get(ticker)):
            if len(members) < 4:
                continue
            ranks = members.rank(pct=True) - (len(members) + 1) / (2.0 * len(members))
            if top_k:
                # the book as it trades today: equal weight in the best and worst k (a third of a small class)
                count = min(top_k, len(members) // 3) or 1
                ordered = members.sort_values(kind="mergesort")
                ranks = pd.Series(0.0, index=members.index)
                ranks[ordered.index[:count]] = -1.0
                ranks[ordered.index[-count:]] = 1.0
            gross = ranks.abs().sum()
            if gross > 0.0:
                pieces.append(ranks / gross)
        return pd.concat(pieces) if pieces else pd.Series(dtype=float)
    if kind == POOLED:
        # Ranks stay centred within a class, so knowing a name's group still earns nothing (#259), but a class's gross follows its breadth: a
        # 15-name sector gets the conviction per name of a 60-name one, not the same budget spread over a quarter of the names.
        pieces = []
        for _, members in live.groupby(lambda ticker: asset_class.get(ticker)):
            if len(members) >= 4:
                pieces.append(members.rank(pct=True) - (len(members) + 1) / (2.0 * len(members)))
        return pd.concat(pieces) if pieces else pd.Series(dtype=float)
    if kind == TS:
        vol = volatility.reindex(live.index)
        return (live / vol).replace([np.inf, -np.inf], np.nan).dropna()
    return live


def scale_and_cap(raw: pd.Series, covariance: pd.DataFrame, asset_class: Mapping[str, str], settings: WeightSettings) -> dict[str, float]:
    """One ex-ante volatility target, then the per-name, per-class and gross caps. Crypto is long-only."""
    weights = raw.copy()
    crypto = [ticker for ticker in weights.index if asset_class.get(ticker) == "crypto"]
    weights[crypto] = weights[crypto].clip(lower=0.0)
    weights = weights[weights != 0.0]
    if weights.empty:
        return {}
    names = list(weights.index)
    matrix = covariance.reindex(index=names, columns=names).fillna(0.0).to_numpy()
    vector = weights.to_numpy(float)
    variance = float(vector @ matrix @ vector) * TRADING_DAYS
    if not np.isfinite(variance) or variance <= 0.0:
        return {}
    weights = weights * (settings.target_vol / np.sqrt(variance))
    for ticker in weights.index:
        cap = settings.name_cap_by_class.get(asset_class.get(ticker), settings.name_cap)
        weights[ticker] = float(np.clip(weights[ticker], -cap, cap))
    for name, cap in settings.class_caps.items():
        members = [ticker for ticker in weights.index if asset_class.get(ticker) == name]
        gross = weights[members].abs().sum() if members else 0.0
        if gross > cap:
            weights[members] = weights[members] * (cap / gross)
    gross = weights.abs().sum()
    if gross > settings.gross_cap:
        weights = weights * (settings.gross_cap / gross)
    return {ticker: float(value) for ticker, value in weights.items() if value != 0.0}


def signal_to_weights(
    signal: pd.DataFrame,
    panel: ResearchPanel,
    *,
    kind: str,
    rebalance_every: int,
    phase_offset: int = 0,
    settings: WeightSettings | None = None,
    start: str | None = None,
    end: str | None = None,
    listed: Callable[[str, str], bool] | None = None,
    top_k: int | None = None,
) -> dict[str, dict[str, float]]:
    """{date: {ticker: weight}} on every `rebalance_every`-th session from `start`, counted from `phase_offset`."""
    settings = settings or WeightSettings()
    daily = panel.known.pct_change(fill_method=None)
    sessions = [date for date in signal.index if (start is None or date >= start) and (end is None or date <= end)]
    rows: dict[str, dict[str, float]] = {}
    position = {date: i for i, date in enumerate(panel.known.index)}
    for count, date in enumerate(sessions):
        if count < phase_offset or (count - phase_offset) % rebalance_every:
            continue
        row = signal.loc[date]
        if listed is not None:
            row = row[[listed(ticker, date) for ticker in row.index]]
        at = position[date]
        window = daily.iloc[max(0, at - VOL_WINDOW + 1):at + 1]
        live = row.dropna().index
        history = window[live]
        raw = _raw_weights(row, kind, history.std(), panel.asset_class, top_k)
        rows[date] = scale_and_cap(raw, history.cov(), panel.asset_class, settings) if not raw.empty else {}
    return rows


def null_signal(signal: pd.DataFrame, mode: str, *, seed: int, asset_class: Mapping[str, str], block: int = 60, min_shift: int = 252) -> pd.DataFrame:
    """A signal with the skill removed, for placebos.

    `asset_block`: relabel assets within their class, held for `block` sessions; keeps turnover and persistence.
    `time_shift`: a circular shift of at least a year; keeps each asset's long-run tilt, so a survivor or class effect that
    an asset relabelling would credit as skill is matched here.
    `sign_block`: for time-series and timing sleeves, reverse the position per asset in `block`-session blocks (a long/flat
    signal in 0..1 swaps long and flat)."""
    rng = np.random.default_rng(seed)
    values = signal.to_numpy(dtype=float).copy()
    available = np.isfinite(values)
    rows, columns = values.shape
    if mode == "time_shift":
        if rows <= 2 * min_shift:
            raise ValueError("signal too short for a time shift of at least a year")
        shift = int(rng.integers(min_shift, rows - min_shift))
        shifted = np.roll(values, shift, axis=0)
        shifted[~available] = np.nan
        return pd.DataFrame(shifted, index=signal.index, columns=signal.columns)
    if mode == "asset_block":
        groups: dict[str, list[int]] = {}
        for column, ticker in enumerate(signal.columns):
            groups.setdefault(str(asset_class.get(ticker)), []).append(column)
        out = np.full_like(values, np.nan)
        for start in range(0, rows, block):
            stop = min(start + block, rows)
            for members in groups.values():
                permuted = rng.permutation(members)
                out[start:stop, members] = values[start:stop, permuted]
        out[~available] = np.nan
        return pd.DataFrame(out, index=signal.index, columns=signal.columns)
    if mode == "sign_block":
        finite = values[available]
        long_flat = finite.size > 0 and finite.min() >= 0.0
        out = values.copy()
        for start in range(0, rows, block):
            stop = min(start + block, rows)
            for column in range(columns):
                if rng.random() < 0.5:
                    out[start:stop, column] = (1.0 - values[start:stop, column]) if long_flat else -values[start:stop, column]
        return pd.DataFrame(out, index=signal.index, columns=signal.columns)
    raise ValueError(f"unknown placebo mode {mode!r}")


def combine_sleeves(
    sleeve_weights: Mapping[str, Mapping[str, Mapping[str, float]]],
    panel: ResearchPanel,
    *,
    method: str = "inverse_vol",
    every: int = 21,
    settings: WeightSettings | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, dict[str, float]]:
    """A fixed-rule mix of sleeves, never fitted to their returns: each month a sleeve's budget comes from the trailing year of its
    own gross returns (inverse volatility, or hierarchical risk parity), and the sum is scaled to one volatility target."""
    from portfolio.hrp_allocation import compute_hrp_weights

    settings = settings or WeightSettings()
    sessions = list(panel.known.index)
    daily = panel.known.pct_change(fill_method=None).fillna(0.0)
    held: dict[str, pd.DataFrame] = {}
    for name, rows in sleeve_weights.items():
        frame = pd.DataFrame.from_dict({date: dict(row) for date, row in rows.items()}, orient="index").reindex(columns=panel.known.columns)
        frame = frame.reindex(sessions)
        marked = frame.notna().any(axis=1) | frame.index.isin(list(rows))
        frame = frame.where(~marked, frame.fillna(0.0)).ffill().fillna(0.0)
        held[name] = frame
    # a weight decided at D earns from the session after D
    sleeve_returns = pd.DataFrame({name: (frame.shift(1) * daily).sum(axis=1) for name, frame in held.items()})
    out: dict[str, dict[str, float]] = {}
    budget: dict[str, float] = {}
    active = [date for date in sessions if (start is None or date >= start) and (end is None or date <= end)]
    position = {date: i for i, date in enumerate(sessions)}
    changes = sorted({date for rows in sleeve_weights.values() for date in rows})
    change_set = set(changes)
    for count, date in enumerate(active):
        at = position[date]
        if count % every == 0 or not budget:
            history = sleeve_returns.iloc[max(0, at - 251):at + 1]
            usable = [name for name in history.columns if history[name].std() > 0.0]
            if len(usable) == 0:
                budget = {name: 1.0 / len(held) for name in held}
            elif method == "hrp" and len(usable) >= 2:
                budget = {name: float(value) for name, value in compute_hrp_weights(history[usable]).items()}
            else:
                inverse = 1.0 / history[usable].std()
                budget = {name: float(value) for name, value in (inverse / inverse.sum()).items()}
        elif date not in change_set:
            continue
        mixture = sum(held[name].iloc[at] * budget.get(name, 0.0) for name in held)
        mixture = mixture[mixture != 0.0]
        window = panel.known.pct_change(fill_method=None).iloc[max(0, at - VOL_WINDOW + 1):at + 1]
        out[date] = scale_and_cap(mixture, window[list(mixture.index)].cov(), panel.asset_class, settings) if not mixture.empty else {}
    return out
