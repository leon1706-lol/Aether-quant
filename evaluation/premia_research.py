"""Scores a sleeve on the offline engine (V6.5.0): the median over rebalance phases, by sub-period, and against placebos.

One Lean run is one rebalance phase and phase luck is real (a tranche study once ranged from -1.02 to +0.57 Sharpe on a single
split), so a sleeve is judged on the median over `PHASES` offsets. The rule R-SLEEVE2 itself (`selection_gate`) is a pure
function of these scores, so its text and its code can be compared directly.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.target_weights_engine import MarketPanel, load_market_panel, simulate_target_weights
from portfolio.financing import load_rate_series
from portfolio.premia_signals import (
    DIRECT,
    TS,
    XS,
    ResearchPanel,
    SleeveSpec,
    WeightSettings,
    fred_series_table,
    known_closes,
    null_signal,
    signal_to_weights,
    sleeve_signal,
)
from portfolio.target_weights import TargetWeightsConfig, resolve_target_weights_config

PHASES = 5
ANNUALIZATION = 365.0
FRED_KEYS = ("treasury_10yr", "treasury_3mo", "credit_spread_baa10y", "implied_volatility_vix", "implied_volatility_3m")


def annual_sharpe(daily: pd.Series) -> float | None:
    values = daily.to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 20 or values.std(ddof=1) <= 0.0:
        return None
    return float(values.mean() / values.std(ddof=1) * math.sqrt(ANNUALIZATION))


def max_drawdown(daily: pd.Series) -> float:
    if daily.empty:
        return 0.0
    curve = (1.0 + daily.fillna(0.0)).cumprod().to_numpy()
    return float(1.0 - (curve / np.maximum.accumulate(curve)).min())


def phase_offsets(rebalance_every: int, phases: int = PHASES) -> list[int]:
    return sorted({int(i * rebalance_every / phases) for i in range(phases)})


def nulls_for(spec: SleeveSpec) -> tuple[str, ...]:
    """A ranking can be relabelled across assets; a direction or a timing rule has no cross-section to relabel."""
    return ("asset_block", "time_shift") if spec.kind == XS else ("sign_block", "time_shift")


@dataclass
class ResearchContext:
    market: MarketPanel
    panel: ResearchPanel
    config: TargetWeightsConfig
    sweep: dict
    rf_dates: list[str]
    rf_rates: list[float]
    carry: Callable[[str, str], float]
    listed: Callable[[str, str], bool]
    settings: WeightSettings = field(default_factory=WeightSettings)

    def simulate(self, weights: Mapping[str, Mapping[str, float]], start: str, end: str) -> dict:
        return simulate_target_weights(
            weights, self.market, self.config, start=start, end=end, sweep_config=self.sweep, rf_dates=self.rf_dates,
            rf_rates=self.rf_rates, carry_fn=self.carry,
        )


def build_context(root: Path, config: dict, *, data_dir: str = "data") -> ResearchContext:
    from data_pipeline.cftc_cot import change_by_session, fx_pair_scores, macro_scores, read_positioning
    from data_pipeline.fred_backfill import load_cached_fred_series
    from features.fx_carry import fx_carry_3m
    from risk.asset_class_router import asset_listed_on_venue, load_venue_listing_dates

    root = Path(root)
    market = load_market_panel(root, config, data_dir=data_dir)
    known = known_closes(market.dates, market.tickers, market.closes, market.asset_class, market.sessions)
    fred_rows = load_cached_fred_series()
    forex = [ticker for ticker in known.columns if market.asset_class.get(ticker) == "forex"]

    def carry(ticker: str, date: str) -> float:
        return fx_carry_3m(ticker, "forex", datetime.date.fromisoformat(str(date)[:10]), fred_rows)

    sessions = list(known.index)
    carry_table = pd.DataFrame({ticker: [carry(ticker, day) for day in sessions] for ticker in forex}, index=sessions, dtype=float)
    extras: dict[str, pd.DataFrame] = {"fx_carry": carry_table}
    cot_path = root / "data" / "reference" / "cot_positioning.csv"
    if cot_path.exists():
        change = change_by_session(read_positioning(cot_path), sessions)
        extras["cot_fx"] = fx_pair_scores(change, forex)
        extras["cot_macro"] = macro_scores(change)
    panel = ResearchPanel(known, market.asset_class, fred_series_table(fred_rows, FRED_KEYS), extras)
    guard = config["phase_v2"].get("venue_listing_guard") or {}
    listing_dates = load_venue_listing_dates(root / str(guard.get("path"))) if guard.get("enabled") else {}
    rf_dates, rf_rates = load_rate_series(root / data_dir / "alternative" / "interest-rate" / "usa" / "interest-rate.csv")
    return ResearchContext(
        market, panel, resolve_target_weights_config(config["phase_v2"].get("target_weights")), config["phase_v2"]["cash_sweep"],
        rf_dates, rf_rates, carry, lambda ticker, date: asset_listed_on_venue(ticker, date, listing_dates),
    )


def weights_for(spec: SleeveSpec, context: ResearchContext, signal: pd.DataFrame, *, start: str, end: str, phase_offset: int) -> dict:
    return signal_to_weights(
        signal, context.panel, kind=spec.kind, rebalance_every=spec.rebalance_every, phase_offset=phase_offset,
        settings=context.settings, start=start, end=end, listed=context.listed, top_k=spec.params.get("top_k"),
    )


def score_sleeve(spec: SleeveSpec, context: ResearchContext, *, start: str, split: str, end: str, signal: pd.DataFrame | None = None) -> dict:
    """Median over the phases of the ex-T-bill Sharpe: pooled and on both sides of `split`."""
    signal = sleeve_signal(spec, context.panel) if signal is None else signal
    pooled, first, second, drawdowns, turnover, gross = [], [], [], [], [], []
    daily_by_phase: dict[int, pd.Series] = {}
    for offset in phase_offsets(spec.rebalance_every):
        result = context.simulate(weights_for(spec, context, signal, start=start, end=end, phase_offset=offset), start, end)
        strategy = result["strategy"]
        pooled.append(annual_sharpe(strategy))
        first.append(annual_sharpe(strategy[strategy.index < split]))
        second.append(annual_sharpe(strategy[strategy.index >= split]))
        drawdowns.append(max_drawdown(strategy))
        turnover.append(result["turnover"])
        gross.append(float(result["gross"].mean()) if not result["gross"].empty else 0.0)
        daily_by_phase[offset] = strategy

    def median(values: list) -> float | None:
        finite = [value for value in values if value is not None]
        return float(np.median(finite)) if finite else None

    return {
        "id": spec.id, "track": spec.track, "kind": spec.kind, "phases": len(pooled), "sharpe": median(pooled),
        "sharpe_first_half": median(first), "sharpe_second_half": median(second), "max_drawdown": median(drawdowns),
        "turnover": median(turnover), "mean_gross": median(gross), "daily": daily_by_phase,
    }


def placebo_sharpes(spec: SleeveSpec, context: ResearchContext, mode: str, *, start: str, end: str, draws: int, seed: int = 1) -> list[float]:
    """Sharpes of `draws` placebo runs over the same window, one random rebalance phase each."""
    signal = sleeve_signal(spec, context.panel)
    rng = np.random.default_rng(seed)
    offsets = phase_offsets(spec.rebalance_every)
    out: list[float] = []
    for draw in range(draws):
        placebo = null_signal(signal, mode, seed=seed * 100_003 + draw, asset_class=context.panel.asset_class)
        offset = int(offsets[int(rng.integers(len(offsets)))])
        value = annual_sharpe(context.simulate(weights_for(spec, context, placebo, start=start, end=end, phase_offset=offset), start, end)["strategy"])
        if value is not None:
            out.append(value)
    return out


def placebo_p_value(observed: float | None, placebos: list[float]) -> float:
    """Share of placebos at or above the observed Sharpe, counting the observation itself (never exactly zero)."""
    if observed is None or not placebos:
        return 1.0
    return (1.0 + sum(value >= observed for value in placebos)) / (len(placebos) + 1.0)


def passes_sharpe_clauses(score: Mapping, *, half_floor: float = 0.40, pooled_floor: float = 0.50) -> bool:
    values = (score.get("sharpe"), score.get("sharpe_first_half"), score.get("sharpe_second_half"))
    return (
        all(value is not None for value in values)
        and values[0] >= pooled_floor and values[1] >= half_floor and values[2] >= half_floor
    )


def selection_gate(scores: list[dict], p_values: Mapping[str, Mapping[str, float]], *, max_survivors: int = 5, max_correlation: float = 0.7, alpha: float = 0.05) -> dict:
    """R-SLEEVE2. A survivor passes both Sharpe clauses and every placebo test; among survivors the higher Sharpe keeps its place
    against any other with daily correlation above `max_correlation`; at most `max_survivors` remain."""
    passing = []
    failed: dict[str, str] = {}
    for score in sorted(scores, key=lambda item: item.get("sharpe") if item.get("sharpe") is not None else -math.inf, reverse=True):
        name = score["id"]
        if not passes_sharpe_clauses(score):
            failed[name] = "sharpe"
        elif not p_values.get(name) or any(value >= alpha for value in p_values[name].values()):
            failed[name] = "placebo"
        else:
            passing.append(score)
    survivors: list[dict] = []
    for score in passing:
        series = _first_phase(score)
        too_close = any(
            series is not None and _first_phase(kept) is not None
            and float(pd.concat([series, _first_phase(kept)], axis=1, join="inner").corr().iloc[0, 1]) > max_correlation
            for kept in survivors
        )
        if too_close:
            failed[score["id"]] = "correlated"
        elif len(survivors) >= max_survivors:
            failed[score["id"]] = "budget"
        else:
            survivors.append(score)
    return {"survivors": [score["id"] for score in survivors], "failed": failed}


def _first_phase(score: Mapping) -> pd.Series | None:
    daily = score.get("daily") or {}
    return daily[min(daily)] if daily else None


__all__ = [
    "DIRECT", "TS", "XS", "PHASES", "ResearchContext", "annual_sharpe", "build_context", "max_drawdown", "nulls_for",
    "phase_offsets", "passes_sharpe_clauses", "placebo_p_value", "placebo_sharpes", "score_sleeve", "selection_gate", "weights_for",
]
