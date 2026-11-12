"""A general, cost-aware backtest of any weights on any prices (V6.6.5, #345): no Lean, no Docker, no model.

Accounting is in units, as a broker books it. A decision row dated D sizes each order at D's close (`weight * NAV / close`);
with `fill="next_open"` the order fills at the next row's open, with `fill="close"` at D's close. Between decisions the
units are held and the weights drift. That is the convention `evaluation.target_weights_engine.simulate_target_weights`
uses for equities, and a test holds the two to the same returns.

    result = backtest(weights, closes, opens=opens, cost_model=LinearCostModel(commission_bps=10))
    print(result.report())
    result.stats()["sharpe_ratio"]
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from evaluation.lean_statistics import lean_statistics
from execution.cost_models import CostModel

__all__ = ["BacktestResult", "backtest", "summary_statistics"]


def _max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return 0.0
    peak = nav.cummax()
    return float((1.0 - nav / peak).max())


def summary_statistics(returns: pd.Series, *, periods_per_year: int = 252, risk_free: float = 0.0, turnover: pd.Series | None = None,
                       costs: pd.Series | None = None, nav: pd.Series | None = None) -> dict[str, float]:
    """CAGR, volatility, Sharpe, Sortino, PSR (Lean's formulas, at a constant annual `risk_free`), max drawdown, Calmar,
    annual turnover and annual cost drag in bps. Non-finite returns are dropped; an empty series gives zeros."""
    clean = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    days = [pd.Timestamp(index).date() for index in clean.index] if len(clean) else []
    lean = lean_statistics(clean.tolist(), days, trading_days_per_year=int(periods_per_year), rate_changes=[(date(1900, 1, 1), float(risk_free))])
    curve = nav if nav is not None else (1.0 + clean).cumprod()
    years = len(clean) / float(periods_per_year) if len(clean) else 0.0
    growth = float((1.0 + clean).prod()) if len(clean) else 1.0
    cagr = growth ** (1.0 / years) - 1.0 if years > 0 and growth > 0 else 0.0
    max_dd = _max_drawdown(curve)
    turnover_annual = float(turnover.sum() / years) if turnover is not None and years > 0 else 0.0
    cost_drag = float(costs.sum() / years * 1e4) if costs is not None and years > 0 else 0.0
    out = {
        "total_return": growth - 1.0,
        "cagr": cagr,
        "annual_volatility": float(lean["annual_standard_deviation"]),
        "sharpe_ratio": float(lean["sharpe_ratio"]),
        "sortino_ratio": float(lean["sortino_ratio"]),
        "probabilistic_sharpe_ratio": float(lean["probabilistic_sharpe_ratio"]),
        "max_drawdown": max_dd,
        "calmar_ratio": cagr / max_dd if max_dd > 0 else 0.0,
        "turnover_annual": turnover_annual,
        "cost_drag_bps_annual": cost_drag,
        "observations": float(len(clean)),
    }
    return {key: (value if math.isfinite(value) else 0.0) for key, value in out.items()}


@dataclass(frozen=True)
class BacktestResult:
    """Daily series of one path. `returns` are net of costs, `gross_returns` before them; `costs` and `turnover` are
    fractions of the previous NAV; `weights` are the end-of-day holdings."""

    returns: pd.Series
    gross_returns: pd.Series
    nav: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series
    costs: pd.Series
    periods_per_year: int = 252

    def stats(self, *, risk_free: float = 0.0) -> dict[str, float]:
        """`summary_statistics` of the net returns."""
        return summary_statistics(self.returns, periods_per_year=self.periods_per_year, risk_free=risk_free, turnover=self.turnover,
                                  costs=self.costs, nav=self.nav)

    def to_frame(self) -> pd.DataFrame:
        """The daily series side by side."""
        return pd.DataFrame({"nav": self.nav, "return": self.returns, "gross_return": self.gross_returns, "turnover": self.turnover,
                             "cost": self.costs, "gross_exposure": self.weights.abs().sum(axis=1)})

    def report(self, *, title: str = "Backtest", risk_free: float = 0.0) -> str:
        """A plain-text summary table."""
        stats = self.stats(risk_free=risk_free)
        start, end = (str(self.nav.index[0]), str(self.nav.index[-1])) if len(self.nav) else ("-", "-")
        rows = [
            ("Window", f"{start} to {end}"), ("Total return", f"{stats['total_return']:.2%}"), ("CAGR", f"{stats['cagr']:.2%}"),
            ("Volatility", f"{stats['annual_volatility']:.2%}"), ("Sharpe", f"{stats['sharpe_ratio']:.2f}"), ("Sortino", f"{stats['sortino_ratio']:.2f}"),
            ("Max drawdown", f"{stats['max_drawdown']:.2%}"), ("Calmar", f"{stats['calmar_ratio']:.2f}"), ("Turnover / yr", f"{stats['turnover_annual']:.1f}x"),
            ("Cost drag / yr", f"{stats['cost_drag_bps_annual']:.0f} bps"),
        ]
        width = max(len(name) for name, _ in rows)
        return "\n".join([title, "-" * len(title)] + [f"{name.ljust(width)}  {value}" for name, value in rows])


def _decision_rows(weights: pd.DataFrame, rebalance_every: int) -> list[bool]:
    has_row = weights.notna().any(axis=1).to_numpy()
    step = max(int(rebalance_every), 1)
    out, seen = [], 0
    for flag in has_row:
        decide = False
        if flag:
            decide = seen % step == 0
            seen += 1
        out.append(bool(decide))
    return out


def backtest(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    opens: pd.DataFrame | None = None,
    cost_model: CostModel | None = None,
    fill: Literal["next_open", "close"] = "next_open",
    initial_nav: float = 100_000.0,
    rebalance_every: int = 1,
    periods_per_year: int = 252,
    adv_usd: Mapping[str, float] | None = None,
    daily_vol: Mapping[str, float] | None = None,
    min_weight_change: float = 0.0,
) -> BacktestResult:
    """Run `weights` (dates x tickers, a row of all-NaN = no decision that day, NaN cell = 0) over `prices` (closes).

    `rebalance_every=k` acts on every k-th decision row. With `fill="next_open"`, `opens` is required; a name without an open
    that day fills at the previous close. A name without a usable close is never sized (its units are left alone).
    `adv_usd` and `daily_vol` feed a cost model that needs them (square-root impact). `min_weight_change` is the live
    path's deadband (`portfolio.target_weights.rebalance_deltas`): a smaller change is not traded, but a zero target always
    closes the name."""
    if fill not in ("next_open", "close"):
        raise ValueError("fill must be 'next_open' or 'close'")
    if fill == "next_open" and opens is None:
        raise ValueError("fill='next_open' needs opens")
    nav0 = float(initial_nav)
    if not math.isfinite(nav0) or nav0 <= 0.0:
        raise ValueError("initial_nav must be positive and finite")
    index = prices.index
    tickers = list(prices.columns)
    target = weights.reindex(index=index, columns=tickers)
    decide = _decision_rows(target, rebalance_every)
    target_values = target.fillna(0.0).to_numpy(float)
    closes = prices.astype(float).ffill().to_numpy(float)
    open_values = opens.reindex(index=index, columns=tickers).astype(float).to_numpy(float) if opens is not None else closes

    units = np.zeros(len(tickers))
    cash = nav0
    pending: np.ndarray | None = None
    nav_out = np.zeros(len(index))
    gross_out = np.zeros(len(index))
    turnover_out = np.zeros(len(index))
    cost_out = np.zeros(len(index))
    held_weights = np.zeros((len(index), len(tickers)))
    previous_nav = nav0

    def value(row: int) -> float:
        marks = np.where(np.isfinite(closes[row]), closes[row], 0.0)
        return float(cash + units @ marks)

    def trade(delta: np.ndarray, price: np.ndarray) -> tuple[float, float]:
        nonlocal cash
        traded_value = 0.0
        fee_total = 0.0
        for column in np.nonzero(delta)[0]:
            notional = abs(float(delta[column] * price[column]))
            fee = 0.0
            if cost_model is not None and notional > 0.0:
                ticker = tickers[column]
                bps = cost_model.cost_bps(notional, adv_usd=(adv_usd or {}).get(ticker), daily_vol=(daily_vol or {}).get(ticker))
                fee = notional * (bps if math.isfinite(bps) and bps > 0.0 else 0.0) / 1e4
            cash -= float(delta[column] * price[column]) + fee
            units[column] += delta[column]
            traded_value += notional
            fee_total += fee
        return traded_value, fee_total

    for row in range(len(index)):
        traded = fees = 0.0
        if pending is not None:
            price = np.where(np.isfinite(open_values[row]) & (open_values[row] > 0.0), open_values[row], closes[row - 1] if row > 0 else closes[row])
            delta = np.where(np.isfinite(price) & (price > 0.0), pending - units, 0.0)
            traded, fees = trade(delta, price)
            pending = None
        nav_now = value(row)
        if decide[row] and nav_now > 0.0:
            price = closes[row]
            usable = np.isfinite(price) & (price > 0.0)
            safe_price = np.where(usable, price, 1.0)
            wanted = np.where(usable, target_values[row] * nav_now / safe_price, units)
            if min_weight_change > 0.0:
                current = units * safe_price / nav_now
                small = usable & (target_values[row] != 0.0) & (np.abs(target_values[row] - current) < float(min_weight_change))
                wanted = np.where(small, units, wanted)
            if fill == "close":
                more_traded, more_fees = trade(np.where(usable, wanted - units, 0.0), price)
                traded, fees = traded + more_traded, fees + more_fees
                nav_now = value(row)
            else:
                pending = wanted
        nav_out[row] = nav_now
        marks = np.where(np.isfinite(closes[row]), closes[row], 0.0)
        held_weights[row] = units * marks / nav_now if nav_now > 0.0 else 0.0
        turnover_out[row] = traded / previous_nav if previous_nav > 0.0 else 0.0
        cost_out[row] = fees / previous_nav if previous_nav > 0.0 else 0.0
        gross_out[row] = (nav_now + fees) / previous_nav - 1.0 if previous_nav > 0.0 else 0.0
        previous_nav = nav_now

    nav_series = pd.Series(nav_out, index=index, name="nav")
    returns = nav_series / pd.Series(np.r_[nav0, nav_out[:-1]], index=index) - 1.0
    return BacktestResult(
        returns=returns.rename("return"), gross_returns=pd.Series(gross_out, index=index, name="gross_return"), nav=nav_series,
        weights=pd.DataFrame(held_weights, index=index, columns=tickers), turnover=pd.Series(turnover_out, index=index, name="turnover"),
        costs=pd.Series(cost_out, index=index, name="cost"), periods_per_year=int(periods_per_year),
    )

