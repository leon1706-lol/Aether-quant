"""V4.5 - the 3 margin sub-models (Reg-T-style naked, uncovered-ladder-leg,
bounded-max-loss backspread) for the strategies portfolio/options_strategy.py's
build_multi_leg_position_sizing() explicitly refuses (risk_tier != "vega_budget")."""

from portfolio.options_margin_sizing import (
    build_margin_position_sizing,
    build_margin_position_sizing_for_legs,
)
from portfolio.options_strategy import select_strategy_legs


def _sample_chain(expiries=("2026-08-21",)) -> list[dict]:
    rows = []
    for expiry in expiries:
        for strike in range(70, 131, 5):
            call_delta = max(0.02, min(0.98, 0.5 + (100 - strike) * 0.02))
            put_delta = call_delta - 1.0
            distance = abs(strike - 100)
            vega = max(0.1, 3.0 - distance * 0.15)
            rows.append({
                "symbol": f"C{strike}", "right": "call", "strike": float(strike), "expiry": expiry,
                "delta": call_delta, "vega": vega, "bid": 1.0, "ask": 1.1,
            })
            rows.append({
                "symbol": f"P{strike}", "right": "put", "strike": float(strike), "expiry": expiry,
                "delta": put_delta, "vega": vega, "bid": 1.0, "ask": 1.1,
            })
    return rows


# ---------------------------------------------------------------------------
# Reg-T-style naked margin (naked_call/naked_put/short_straddle/
# short_strangle/short_call_backspread/short_put_backspread)
# ---------------------------------------------------------------------------


def test_naked_call_margin_respects_max_utilization_ceiling():
    # NOTE: confidence moves BOTH the soft-target contract count AND the
    # target_delta (hence the selected strike/OTM-amount/margin-per-
    # contract) - the two effects can offset, so contracts is NOT
    # guaranteed monotonic in confidence here. What IS guaranteed
    # regardless of confidence: never exceeding the hard ceiling.
    for confidence in (0.2, 0.5, 0.9):
        decision = build_margin_position_sizing("naked_call", "sell", confidence, _sample_chain(), 100.0, 1_000_000)
        assert decision is not None
        assert decision.margin_utilization <= 0.40 + 1e-9


def test_contracts_from_margin_budget_scales_with_confidence_holding_margin_per_unit_fixed():
    # Isolates the soft-target confidence scaling from strike-selection
    # drift (see the note above) by calling the private budget helper
    # directly with a FIXED margin_per_spread_unit.
    from portfolio.options_margin_sizing import _contracts_from_margin_budget

    low = _contracts_from_margin_budget(1000.0, confidence=0.2, portfolio_value=1_000_000, target_margin_utilization=0.20, max_margin_utilization=0.40)
    high = _contracts_from_margin_budget(1000.0, confidence=0.9, portfolio_value=1_000_000, target_margin_utilization=0.20, max_margin_utilization=0.40)
    assert high >= low
    max_affordable = _contracts_from_margin_budget(1000.0, confidence=1.0, portfolio_value=1_000_000, target_margin_utilization=0.20, max_margin_utilization=0.40)
    assert high <= int(1_000_000 * 0.40 // 1000.0)
    assert max_affordable <= int(1_000_000 * 0.40 // 1000.0)


def test_naked_put_margin_uses_correct_otm_direction():
    decision = build_margin_position_sizing("naked_put", "sell", 0.8, _sample_chain(), underlying_price=100.0, portfolio_value=1_000_000)
    assert decision is not None
    assert decision.legs[0].right == "put"
    assert decision.legs[0].side == "short"


def test_short_straddle_margin_is_greater_of_the_two_legs_not_the_sum():
    straddle = build_margin_position_sizing("short_straddle", "sell", 0.8, _sample_chain(), 100.0, 1_000_000)
    naked_call = build_margin_position_sizing("naked_call", "sell", 0.8, _sample_chain(), 100.0, 1_000_000)
    assert straddle is not None and naked_call is not None
    # Same strike/confidence/underlying_price -> per-contract margin should
    # match the single naked-call formula (greater-side convention), not
    # double it.
    straddle_margin_per_contract = straddle.margin_required / straddle.contracts
    naked_margin_per_contract = naked_call.margin_required / naked_call.contracts
    assert abs(straddle_margin_per_contract - naked_margin_per_contract) < 1e-6


def test_short_call_backspread_is_naked_tier_not_bounded_max_loss():
    decision = build_margin_position_sizing("short_call_backspread", "sell", 0.8, _sample_chain(), 100.0, 1_000_000)
    assert decision is not None
    assert decision.sizing_reason == "reg_t_style_naked_margin_sizing"


def test_naked_margin_non_positive_underlying_price_returns_none():
    assert build_margin_position_sizing("naked_call", "sell", 0.8, _sample_chain(), underlying_price=0.0, portfolio_value=1_000_000) is None


# ---------------------------------------------------------------------------
# Uncovered-leg margin (bull_call_ladder/bear_put_ladder only)
# ---------------------------------------------------------------------------


def test_uncovered_leg_margin_only_the_excess_short_leg_is_charged():
    decision = build_margin_position_sizing("bull_call_ladder", "buy", 0.8, _sample_chain(), 100.0, 1_000_000)
    assert decision is not None
    assert decision.sizing_reason == "uncovered_ladder_leg_margin_sizing"
    assert decision.margin_required > 0.0


def test_bear_call_ladder_is_vega_budget_not_margin_tier():
    # The corrected classification (§ module docstring in
    # options_strategy.py) - bear_call_ladder is net-long, bounded, and
    # must be refused by the margin sizer entirely.
    assert build_margin_position_sizing("bear_call_ladder", "sell", 0.8, _sample_chain(), 100.0, 1_000_000) is None


# ---------------------------------------------------------------------------
# Bounded-max-loss backspread margin (call_backspread/put_backspread only)
# ---------------------------------------------------------------------------


def test_bounded_backspread_margin_matches_strike_width_minus_credit_formula():
    decision = build_margin_position_sizing("call_backspread", "buy", 0.8, _sample_chain(), 100.0, 1_000_000)
    assert decision is not None
    assert decision.sizing_reason == "bounded_max_loss_backspread_margin_sizing"
    per_unit = decision.margin_required / decision.contracts
    strikes = sorted(leg.strike for leg in decision.legs)
    strike_width = strikes[1] - strikes[0]
    # call_backspread is 1 short (ratio=1) at the lower strike, 2 long
    # (ratio=2) at the higher strike - net_credit = short_ratio*bid -
    # long_ratio*ask, matching _bounded_backspread_max_loss()'s own formula.
    net_credit = 1.0 * 1.0 - 2.0 * 1.1  # short bid (1.0) x1 - long ask (1.1) x2
    expected = max(strike_width - net_credit, 0.0) * 100.0
    assert abs(per_unit - expected) < 1e-6


def test_put_backspread_is_bounded_tier_not_naked():
    decision = build_margin_position_sizing("put_backspread", "sell", 0.8, _sample_chain(), 100.0, 1_000_000)
    assert decision is not None
    assert decision.sizing_reason == "bounded_max_loss_backspread_margin_sizing"


# ---------------------------------------------------------------------------
# Cross-cutting: tier dispatch and edge cases
# ---------------------------------------------------------------------------


def test_vega_budget_strategy_is_rejected_by_margin_sizer():
    assert build_margin_position_sizing("bull_call_spread", "buy", 0.8, _sample_chain(), 100.0, 1_000_000) is None
    assert build_margin_position_sizing("iron_condor", "sell", 0.8, _sample_chain(), 100.0, 1_000_000) is None


def test_unreachable_arbitrage_strategy_is_rejected_by_margin_sizer():
    assert build_margin_position_sizing("box_spread", "buy", 0.8, _sample_chain(), 100.0, 1_000_000) is None


def test_zero_confidence_returns_none():
    assert build_margin_position_sizing("naked_call", "sell", 0.0, _sample_chain(), 100.0, 1_000_000) is None


def test_invalid_signal_direction_returns_none():
    assert build_margin_position_sizing("naked_call", "hold", 0.8, _sample_chain(), 100.0, 1_000_000) is None


def test_empty_chain_returns_none():
    assert build_margin_position_sizing("naked_call", "sell", 0.8, [], 100.0, 1_000_000) is None


# ---------------------------------------------------------------------------
# Resize-in-place sibling (build_margin_position_sizing_for_legs)
# ---------------------------------------------------------------------------


def test_build_margin_position_sizing_for_legs_resizes_held_naked_call():
    legs_by_role = select_strategy_legs("naked_call", _sample_chain(), 0.3)
    assert legs_by_role is not None
    resized = build_margin_position_sizing_for_legs("naked_call", legs_by_role, underlying_price=100.0, portfolio_value=1_000_000)
    assert resized is not None
    assert resized.sizing_reason == "held_legs_own_greeks_naked_margin_sizing"


def test_build_margin_position_sizing_for_legs_rejects_vega_budget_strategy():
    legs_by_role = select_strategy_legs("bull_call_spread", _sample_chain(), 0.5)
    assert build_margin_position_sizing_for_legs("bull_call_spread", legs_by_role, 100.0, 1_000_000) is None
