"""Offline simulation of the trend sleeve (V6.4.4, rule R-TREND1).

Daily closes from the shipped Lean zips; on every `rebalance_every_bars`-th session from `start + phase` the sleeve's
target weights come from `portfolio.trend_sleeve.trend_sleeve_weights` on the closes up to and including that session
(the same function main.py calls), filtered by `apply_min_change`, and are bought at that close as units (one-bar lag:
the position earns from the next session on, as live). Units then drift with prices until the next rebalance. Each trade
pays max(commission_bps x notional, min_commission_usd) plus `half_spread_bps`; the sleeve's own loss guard
(`portfolio.sleeve_guard`, NAV fractions) closes it and blocks entries during a cooldown.

Returns are fractions of the account NAV, which grows only by the sleeve's own P&L here (the sleeve's contribution).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from portfolio.sleeve_guard import SleeveGuardConfig, evaluate_sleeve_guard
from portfolio.trend_sleeve import TrendSleeveConfig, apply_min_change, trend_sleeve_weights


def load_daily_closes(root: Path, config: dict, symbols, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """date x symbol closes of the universe assets `symbols` from their config zips (rows where every symbol has a
    close; the trend symbols share the US equity calendar)."""
    from data_pipeline.data_audit import asset_zip_paths, read_lean_daily_zip

    assets = {str(asset["ticker"]): asset for asset in config["phase1"]["universe"]["assets"]}
    series = {}
    for symbol in symbols:
        asset = assets[symbol]
        frame = read_lean_daily_zip(asset_zip_paths(asset, Path(root) / "data")["trade"], str(asset.get("security_type")))
        series[symbol] = frame.set_index(frame["date"].dt.strftime("%Y-%m-%d"))["close"]
    closes = pd.DataFrame(series).dropna().sort_index()
    if start:
        closes = closes[closes.index >= start]
    if end:
        closes = closes[closes.index <= end]
    return closes


def _trade_cost(notional: float, commission_bps: float, min_commission_usd: float, half_spread_bps: float) -> float:
    if notional <= 0.0:
        return 0.0
    return max(notional * commission_bps / 1e4, min_commission_usd) + notional * half_spread_bps / 1e4


def simulate_trend_sleeve(
    closes: pd.DataFrame,
    config: TrendSleeveConfig,
    *,
    start: str,
    end: str,
    phase: int = 0,
    commission_bps: float = 1.5,
    min_commission_usd: float = 1.0,
    half_spread_bps: float = 2.0,
    guard: SleeveGuardConfig | None = None,
    nav: float = 100_000.0,
    annualization: float = 252.0,
) -> dict:
    """One path of the sleeve over [start, end]. `closes` must hold history before `start` for the lookbacks."""
    dates = list(closes.index)
    columns = list(closes.columns)
    values = closes.to_numpy(dtype=float)
    first = next((i for i, date in enumerate(dates) if date >= start), len(dates))
    last = max((i for i, date in enumerate(dates) if date <= end), default=-1)
    units = {symbol: 0.0 for symbol in columns}
    weights_held: dict[str, float] = {}
    equity = float(nav)
    pnl_history: list[float] = []
    suspended_until = None
    daily, gross_series, weight_rows = {}, {}, {}
    total_cost, traded = 0.0, 0.0
    for i in range(first, last + 1):
        date = dates[i]
        prices = dict(zip(columns, values[i]))
        if i > first:
            previous = dict(zip(columns, values[i - 1]))
            pnl = sum(units[s] * (prices[s] - previous[s]) for s in columns)
        else:
            pnl = 0.0
        cost_today = 0.0
        step = i - first - phase
        guard_state = {"active": True}
        if guard is not None:
            pnl_history.append(pnl / nav)
            guard_state = evaluate_sleeve_guard(pnl_history, 1.0, guard, current_bar=i, suspended_until_bar=suspended_until)
            suspended_until = guard_state.get("suspended_until_bar")
        target = None
        if not guard_state["active"]:
            target = {}
        elif step >= 0 and step % config.rebalance_every_bars == 0:
            history = {s: values[: i + 1, columns.index(s)].tolist() for s in config.symbols if s in columns}
            target = apply_min_change(weights_held, trend_sleeve_weights(history, config, annualization=annualization),
                                      config.min_weight_change)
        equity_before = equity + pnl
        if target is not None and target != weights_held:
            for symbol in columns:
                new_units = target.get(symbol, 0.0) * equity_before / prices[symbol]
                if symbol in weights_held and symbol in target and target[symbol] == weights_held[symbol]:
                    new_units = units[symbol]
                notional = abs(new_units - units[symbol]) * prices[symbol]
                if notional > 0.0:
                    cost_today += _trade_cost(notional, commission_bps, min_commission_usd, half_spread_bps)
                    traded += notional
                units[symbol] = new_units
            weights_held = dict(target)
        total_cost += cost_today
        net = pnl - cost_today
        daily[date] = net / equity
        equity += net
        gross_series[date] = sum(abs(units[s]) * prices[s] for s in columns) / equity if equity > 0 else 0.0
        weight_rows[date] = {s: units[s] * prices[s] / equity for s in columns}
    daily_series = pd.Series(daily, dtype=float)
    years = max(len(daily_series) / annualization, 1e-9)
    return {
        "daily": daily_series,
        "gross": pd.Series(gross_series, dtype=float),
        "weights": pd.DataFrame.from_dict(weight_rows, orient="index"),
        "turnover": traded / nav / years,
        "costs": total_cost,
    }


def summarize_daily(daily: pd.Series, annualization: float = 252.0) -> dict:
    """Annualised net Sharpe, total return and max drawdown (NAV fractions) of a daily return series."""
    values = daily.to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return {"net_sharpe": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "days": int(len(values))}
    std = float(np.std(values, ddof=1))
    sharpe = float(np.mean(values) / std * math.sqrt(annualization)) if std > 0 else 0.0
    curve = np.cumprod(1.0 + values)
    drawdown = float(np.max(1.0 - curve / np.maximum.accumulate(curve)))
    return {"net_sharpe": sharpe, "total_return": float(curve[-1] - 1.0), "max_drawdown": drawdown, "days": int(len(values))}


def trend_phase_summary(closes: pd.DataFrame, config: TrendSleeveConfig, *, start: str, end: str, phases: int = 10,
                        **kwargs) -> dict:
    """The sleeve over `phases` evenly spaced rebalance phases: median / min / max of each summary figure, plus phase 0's
    daily returns (the series combined with the main book)."""
    every = config.rebalance_every_bars
    count = max(1, min(phases, every))
    phase_list = sorted({int(round(i * every / count)) % every for i in range(count)})
    summaries, phase0 = [], None
    for phase in phase_list:
        result = simulate_trend_sleeve(closes, config, start=start, end=end, phase=phase, **kwargs)
        summary = summarize_daily(result["daily"]) | {"turnover": result["turnover"], "costs": result["costs"]}
        summaries.append(summary)
        if phase0 is None:
            phase0 = result["daily"]
    out = {"phases": phase_list, "daily_phase0": phase0}
    for key in ("net_sharpe", "total_return", "max_drawdown", "turnover", "costs"):
        column = [summary[key] for summary in summaries]
        out[f"median_{key}"] = float(np.median(column))
        out[f"min_{key}"] = float(np.min(column))
        out[f"max_{key}"] = float(np.max(column))
    return out
