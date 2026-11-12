"""Composable trading-cost models (V6.6.5, #345): what one trade costs, in basis points of its notional.

Each model answers one question, `cost_bps(trade_value, adv_usd=..., daily_vol=...)`, and models add up in a
`CompositeCostModel`. The square-root impact term is `evaluation.impact_model.compute_sqrt_impact_bps`, and the presets use
the fees the live path charges (`evaluation.target_weights_engine.coinbase_taker_bps`, the IB equity terms), so a research
cost and a live cost are the same numbers.

    model = CompositeCostModel((LinearCostModel(commission_bps=1.5, half_spread_bps=2.0), SquareRootImpactModel(eta=0.5)))
    model.cost_bps(50_000.0, adv_usd=20e6, daily_vol=0.02)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from evaluation.impact_model import compute_sqrt_impact_bps

__all__ = [
    "CostModel", "LinearCostModel", "SquareRootImpactModel", "CompositeCostModel", "cost_usd", "coinbase_model", "ib_equity_model",
]


def _finite_non_negative(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0.0 else None


@runtime_checkable
class CostModel(Protocol):
    """Anything with `cost_bps(trade_value, *, adv_usd, daily_vol) -> float` (never negative, never NaN)."""

    def cost_bps(self, trade_value: float, *, adv_usd: float | None = None, daily_vol: float | None = None) -> float: ...


@dataclass(frozen=True)
class LinearCostModel:
    """A commission and half the quoted spread, both per side in bps, plus an optional dollar minimum per trade."""

    commission_bps: float = 0.0
    half_spread_bps: float = 0.0
    min_fee_usd: float = 0.0

    def cost_bps(self, trade_value: float, *, adv_usd: float | None = None, daily_vol: float | None = None) -> float:
        notional = _finite_non_negative(abs(float(trade_value))) if trade_value is not None else None
        if not notional:
            return 0.0
        bps = (_finite_non_negative(self.commission_bps) or 0.0) + (_finite_non_negative(self.half_spread_bps) or 0.0)
        minimum = _finite_non_negative(self.min_fee_usd) or 0.0
        floor_bps = minimum / notional * 1e4 if minimum > 0.0 else 0.0
        # the minimum is charged up to the whole notional, so a dust trade costs at most itself and never inf bps
        return max(bps, min(floor_bps, 1e4) if math.isfinite(floor_bps) else 1e4)


@dataclass(frozen=True)
class SquareRootImpactModel:
    """Temporary impact `eta * daily_vol * sqrt(trade / ADV)`, in bps. Zero when ADV or volatility is unknown, so an
    unknown is visible as a missing input rather than a guessed cost."""

    eta: float = 0.5

    def cost_bps(self, trade_value: float, *, adv_usd: float | None = None, daily_vol: float | None = None) -> float:
        notional = _finite_non_negative(abs(float(trade_value))) if trade_value is not None else None
        adv, vol, eta = _finite_non_negative(adv_usd), _finite_non_negative(daily_vol), _finite_non_negative(self.eta)
        if not notional or not adv or not vol or eta is None:
            return 0.0
        value = compute_sqrt_impact_bps(trade_size_fraction=1.0, daily_volatility=vol, avg_daily_dollar_volume=adv, portfolio_value=notional, eta=eta)
        return value if math.isfinite(value) and value >= 0.0 else 0.0


@dataclass(frozen=True)
class CompositeCostModel:
    """The sum of its parts."""

    models: Sequence[CostModel] = field(default_factory=tuple)

    def cost_bps(self, trade_value: float, *, adv_usd: float | None = None, daily_vol: float | None = None) -> float:
        return float(sum(model.cost_bps(trade_value, adv_usd=adv_usd, daily_vol=daily_vol) for model in self.models))


def cost_usd(model: CostModel, trade_value: float, *, adv_usd: float | None = None, daily_vol: float | None = None) -> float:
    """The model's cost of one trade in dollars."""
    notional = abs(float(trade_value)) if trade_value is not None and math.isfinite(float(trade_value)) else 0.0
    return notional * model.cost_bps(notional, adv_usd=adv_usd, daily_vol=daily_vol) / 1e4


def coinbase_model(date: str = "2026-01-01", *, slippage_bps: float = 10.0) -> LinearCostModel:
    """Coinbase market orders as the live path and its simulator charge them: the date-effective taker fee plus the
    crypto slippage the target-weights simulator assumes (`portfolio.target_weights.DEFAULT_SLIPPAGE_BPS`)."""
    from evaluation.target_weights_engine import coinbase_taker_bps

    return LinearCostModel(commission_bps=coinbase_taker_bps(date), half_spread_bps=slippage_bps)


def ib_equity_model(*, commission_bps: float = 1.5, min_fee_usd: float = 1.0, slippage_bps: float = 3.0, eta: float | None = 0.5) -> CostModel:
    """US equities through IB as the target-weights path charges them (bps commission with a $1 floor, 3 bps slippage),
    with square-root impact on top unless `eta` is None."""
    linear = LinearCostModel(commission_bps=commission_bps, half_spread_bps=slippage_bps, min_fee_usd=min_fee_usd)
    return linear if eta is None else CompositeCostModel((linear, SquareRootImpactModel(eta=eta)))
