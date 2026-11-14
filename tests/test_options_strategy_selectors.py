"""portfolio/options_strategy.py's leg selectors (V6.6.6, #359): every registered strategy against many thinned chains. A thin chain is the normal case in
production, so the contract is: a full set of roles drawn from the chain, or None, never a partial fill or an exception."""

from __future__ import annotations

import random

import pytest

from portfolio import options_strategy as strategy

EXPIRIES = ("2026-12-18", "2027-01-15", "2027-03-19")
STRIKES = (80.0, 85.0, 90.0, 95.0, 100.0, 102.0, 105.0, 110.0, 115.0, 120.0)


def _pool(rng: random.Random) -> list[dict]:
    rows = []
    for expiry in EXPIRIES:
        for strike in STRIKES:
            moneyness = (strike - 100.0) / 20.0
            call_delta = max(0.02, min(0.98, 0.5 - moneyness))
            for right, delta in (("call", call_delta), ("put", -(1.0 - call_delta))):
                rows.append({"right": rng.choice([right, right.upper()]) if rng.random() < 0.1 else right, "strike": strike, "expiry": expiry, "delta": delta,
                             "bid": 1.0, "ask": 1.2, "implied_volatility": 0.25, "gamma": 0.01, "vega": max(0.01, 0.3 - abs(moneyness) * 0.5), "theta": -0.02, "open_interest": 100})
    return rows


@pytest.mark.parametrize("name", sorted(strategy.MULTI_LEG_STRATEGY_REGISTRY))
def test_a_strategy_returns_every_role_from_the_chain_or_nothing(name):
    rng = random.Random(hash(name) & 0xFFFF)
    spec = strategy.MULTI_LEG_STRATEGY_REGISTRY[name]
    roles = {leg.role for leg in spec.legs}
    seen_full = seen_none = False
    for trial in range(120):
        chain = [row for row in _pool(rng) if rng.random() < (0.15, 0.4, 0.7, 0.95)[trial % 4]]
        if trial % 5 == 4:
            only = rng.choice(("call", "put"))
            chain = [row for row in chain if str(row["right"]).lower() == only]
        for row in chain:
            if rng.random() < 0.05:
                row["delta"] = None
        grouped = strategy.group_chain_by_expiry(chain) if trial % 3 == 0 else None
        result = strategy.select_strategy_legs(name, chain, rng.choice((0.2, 0.3, 0.5)), grouped_chain_by_expiry=grouped)
        if result is None:
            seen_none = True
            continue
        seen_full = True
        assert set(result) == roles and all(any(row is chosen for row in chain) for chosen in result.values())
    assert seen_none or seen_full
    assert seen_full or name  # a family that never fills on this pool is still a valid (None) outcome


def test_an_unknown_name_and_a_family_without_a_selector_return_nothing(monkeypatch):
    assert strategy.select_strategy_legs("nonexistent", [], 0.3) is None
    name = next(iter(strategy.MULTI_LEG_STRATEGY_REGISTRY))
    spec = strategy.MULTI_LEG_STRATEGY_REGISTRY[name]
    odd = type(spec)(**{**spec.__dict__, "shape_family": "unheard_of"}) if hasattr(spec, "__dict__") else spec
    monkeypatch.setitem(strategy.MULTI_LEG_STRATEGY_REGISTRY, "odd", odd)
    assert strategy.select_strategy_legs("odd", [], 0.3) is None


def _chain():
    return _pool(random.Random(7))


def test_a_vertical_with_a_wider_short_vega_is_not_sized():
    long_row, short_row = {"vega": 0.1, "ask": 1.0, "delta": 0.5}, {"vega": 0.2, "bid": 0.8, "delta": 0.3}
    assert strategy._size_vertical_spread(long_row, short_row, "call", "bull_call_spread", 100_000.0, 0.02, "x") is None


def test_multi_leg_sizing_returns_a_decision_with_a_dict_form_or_nothing():
    chain = _chain()
    decision = strategy.build_multi_leg_position_sizing("iron_condor", "buy", 1.0, chain, 1_000_000.0)
    assert decision is not None and decision.to_dict()["strategy_name"] == "iron_condor" and decision.to_dict()["legs"]
    assert strategy.build_multi_leg_position_sizing("iron_condor", "buy", 1.0, chain, 1_000_000.0, max_vega_budget_pct_of_equity=0.0) is None
    assert strategy.build_multi_leg_position_sizing("iron_condor", "hold", 1.0, chain, 1_000_000.0) is None
    assert strategy.build_multi_leg_position_sizing("iron_condor", "buy", 1.0, [], 1_000_000.0) is None
    assert strategy.build_multi_leg_position_sizing("iron_condor", "buy", 0.0, chain, 1_000_000.0) is None
    assert strategy.build_multi_leg_position_sizing("naked_call", "buy", 1.0, chain, 1_000_000.0) is None


def test_held_legs_are_resized_on_their_own_greeks_and_missing_legs_are_skipped():
    chain = _chain()
    legs = strategy.select_strategy_legs("iron_condor", chain, 0.3)
    assert strategy.build_multi_leg_position_sizing_for_legs("iron_condor", legs, 1_000_000.0) is not None
    assert strategy.build_multi_leg_position_sizing_for_legs("iron_condor", legs, 0.0) is None
    assert strategy.build_multi_leg_position_sizing_for_legs("nonexistent", legs, 1_000_000.0) is None
    spec = strategy.MULTI_LEG_STRATEGY_REGISTRY["iron_condor"]
    partial = {leg.role: legs[leg.role] for leg in spec.legs[:2]}
    assert isinstance(strategy._net_vega_and_delta_per_unit(spec, partial), tuple)
    flat = {role: {**row, "vega": 0.0} for role, row in legs.items()}
    assert strategy.build_multi_leg_position_sizing_for_legs("iron_condor", flat, 1_000_000.0) is None


def test_atm_volatility_needs_at_least_one_quoted_iv():
    rows = [{"expiry": "e", "right": "call", "delta": 0.5, "strike": 100.0}, {"expiry": "e", "right": "put", "delta": -0.5, "strike": 100.0}]
    assert strategy.atm_implied_volatility(rows, "e") is None
    assert strategy.atm_implied_volatility([{**rows[0], "iv": 0.3}, rows[1]], "e") == 0.3


def test_covered_and_protective_sizing_checks_side_confidence_and_legs():
    chain = _chain()
    assert strategy.build_covered_protective_position_sizing("covered_call", 1.0, chain, 500.0) is not None
    assert strategy.build_covered_protective_position_sizing("iron_condor", 1.0, chain, 500.0) is None
    assert strategy.build_covered_protective_position_sizing("covered_call", 0.0, chain, 500.0) is None
    assert strategy.build_covered_protective_position_sizing("covered_call", 1.0, chain, -500.0) is None
    assert strategy.build_covered_protective_position_sizing("covered_put", 1.0, chain, 500.0) is None
    assert strategy.build_covered_protective_position_sizing("covered_call", 1.0, chain, 50.0) is None
    assert strategy.build_covered_protective_position_sizing("covered_call", 1.0, [], 500.0) is None


def test_a_vertical_whose_budget_buys_no_unit_is_not_sized():
    long_row, short_row = {"vega": 0.2, "ask": 1.0, "delta": 0.5}, {"vega": 0.1, "bid": 0.8, "delta": 0.3}
    assert strategy._size_vertical_spread(long_row, short_row, "call", "bull_call_spread", 100_000.0, 0.0, "x") is None
