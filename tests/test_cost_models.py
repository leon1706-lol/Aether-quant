"""execution/cost_models.py (V6.6.5, #345)."""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from evaluation.impact_model import compute_sqrt_impact_bps
from execution.cost_models import (
    CompositeCostModel,
    CostModel,
    LinearCostModel,
    SquareRootImpactModel,
    coinbase_model,
    cost_usd,
    ib_equity_model,
)


def test_linear_model_adds_commission_and_half_spread_and_respects_the_minimum():
    model = LinearCostModel(commission_bps=1.5, half_spread_bps=2.0, min_fee_usd=1.0)
    assert model.cost_bps(100_000.0) == 3.5
    assert math.isclose(model.cost_bps(1_000.0), 10.0)  # $1 on $1,000 is 10 bps, above 3.5
    assert model.cost_bps(0.0) == 0.0
    assert math.isclose(cost_usd(model, -100_000.0), 35.0)


def test_impact_model_is_the_shared_square_root_formula():
    model = SquareRootImpactModel(eta=0.5)
    expected = compute_sqrt_impact_bps(trade_size_fraction=1.0, daily_volatility=0.02, avg_daily_dollar_volume=1e7, portfolio_value=1e5, eta=0.5)
    assert math.isclose(model.cost_bps(1e5, adv_usd=1e7, daily_vol=0.02), expected)
    assert model.cost_bps(1e5) == 0.0  # unknown liquidity is zero, never guessed


def test_composite_and_presets():
    composite = CompositeCostModel((LinearCostModel(commission_bps=1.0), LinearCostModel(half_spread_bps=2.0)))
    assert composite.cost_bps(1e4) == 3.0
    assert coinbase_model("2026-01-01").cost_bps(1e4) == 90.0  # 80 bps taker + 10 bps slippage
    assert coinbase_model("2019-01-01").commission_bps == 30.0
    assert isinstance(ib_equity_model(), CostModel)
    assert ib_equity_model(eta=None).cost_bps(1e6) == 4.5


def test_non_finite_inputs_cost_nothing_rather_than_nan():
    model = CompositeCostModel((LinearCostModel(commission_bps=float("nan")), SquareRootImpactModel(eta=float("inf"))))
    assert model.cost_bps(1e5, adv_usd=float("nan"), daily_vol=0.02) == 0.0
    assert cost_usd(LinearCostModel(commission_bps=5.0), float("nan")) == 0.0


@settings(max_examples=200, deadline=None)
@given(
    st.floats(allow_nan=True, allow_infinity=True), st.floats(min_value=-1e3, max_value=1e3), st.floats(min_value=-1e3, max_value=1e3),
    st.floats(min_value=-10, max_value=10), st.one_of(st.none(), st.floats()), st.one_of(st.none(), st.floats()),
)
def test_a_cost_is_never_negative_or_nan(trade, commission, spread, eta, adv, vol):
    model = CompositeCostModel((LinearCostModel(commission_bps=commission, half_spread_bps=spread, min_fee_usd=1.0), SquareRootImpactModel(eta=eta)))
    value = model.cost_bps(trade, adv_usd=adv, daily_vol=vol)
    assert math.isfinite(value) and value >= 0.0
