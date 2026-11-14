"""portfolio/options_margin_sizing.py's remaining branches (V6.6.6, #359): every margin tier, sized fresh and on held legs, and each refusal."""

from __future__ import annotations

import random

import pytest

from portfolio import options_margin_sizing as sizing
from portfolio import options_strategy as strategy
from test_options_strategy_selectors import _pool

CHAIN = _pool(random.Random(7))
TIERS = {"margin_naked": "naked_call", "margin_uncovered_leg": "bull_call_ladder", "margin_bounded_backspread": "call_backspread", "short_straddle": "short_straddle"}


@pytest.mark.parametrize("name", ["naked_call", "naked_put", "short_straddle", "short_strangle", "short_call_backspread", "bull_call_ladder", "bear_put_ladder", "call_backspread", "put_backspread"])
def test_each_margin_tier_is_sized_fresh_and_on_held_legs(name):
    decision = sizing.build_margin_position_sizing(name, "sell", 1.0, CHAIN, 100.0, 5_000_000.0)
    assert decision is not None and decision.to_dict()["strategy_name"] == name and decision.margin_utilization <= 0.4
    legs = strategy.select_strategy_legs(name, CHAIN, 0.6)
    held = sizing.build_margin_position_sizing_for_legs(name, legs, 100.0, 5_000_000.0)
    assert held is not None and held.sizing_reason.startswith("held_legs_own_greeks")
    assert sizing.build_margin_position_sizing_for_legs(name, legs, 100.0, 1.0) is None
    assert sizing.build_margin_position_sizing_for_legs(name, legs, 0.0, 5_000_000.0) is None


def test_the_naked_margin_floors_and_refuses_bad_inputs():
    assert sizing._naked_margin_per_contract(0.0, 100.0, "call", 100.0, 0.2, 0.1) == 0.0
    assert sizing._naked_margin_per_contract(100.0, 150.0, "call", 100.0, 0.2, 0.1) == 1000.0
    assert sizing._contracts_from_margin_budget(0.0, 1.0, 1e6, 0.2, 0.4) == 0
    assert sizing.build_margin_position_sizing("iron_condor", "sell", 1.0, CHAIN, 100.0, 1e6) is None
    assert sizing.build_margin_position_sizing("naked_call", "sell", 0.0, CHAIN, 100.0, 1e6) is None
    assert sizing.build_margin_position_sizing("naked_call", "hold", 1.0, CHAIN, 100.0, 1e6) is None
    assert sizing.build_margin_position_sizing("naked_call", "sell", 1.0, [], 100.0, 1e6) is None
    assert sizing.build_margin_position_sizing("naked_call", "sell", 1.0, CHAIN, 100.0, 1.0) is None
    assert sizing.build_margin_position_sizing_for_legs("iron_condor", {}, 100.0, 1e6) is None
    legs = strategy.select_strategy_legs("naked_call", CHAIN, 0.6)
    assert sizing.build_margin_position_sizing_for_legs("naked_call", legs, 100.0, 1e6, max_margin_utilization=0.0) is None


def test_a_naked_tier_without_a_short_leg_needs_no_margin():
    spec = type("Spec", (), {"legs": []})()
    assert sizing._naked_margin_requirement_for_naked_tier(spec, {}, 100.0, 100.0, 0.2, 0.1) == 0.0


def test_a_backspread_without_quotes_assumes_no_credit():
    spec = strategy.MULTI_LEG_STRATEGY_REGISTRY["call_backspread"]
    legs = strategy.select_strategy_legs("call_backspread", CHAIN, 0.6)
    bare = {role: {key: value for key, value in row.items() if key not in ("bid", "ask")} for role, row in legs.items()}
    assert sizing._bounded_backspread_max_loss(spec, bare, 100.0) > 0.0 and sizing._bounded_backspread_max_loss(spec, legs, 100.0) > 0.0


def test_held_legs_with_no_margin_requirement_are_not_sized(monkeypatch):
    legs = strategy.select_strategy_legs("naked_call", CHAIN, 0.6)
    monkeypatch.setattr(sizing, "_naked_margin_requirement_for_naked_tier", lambda *args: 0.0)
    assert sizing.build_margin_position_sizing_for_legs("naked_call", legs, 100.0, 1e6) is None
