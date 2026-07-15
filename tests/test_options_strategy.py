import json

from portfolio.options_strategy import (
    OptionsPositionDecision,
    OptionsSpreadLeg,
    OptionsSpreadPositionDecision,
    build_options_position_sizing,
    build_vertical_spread_position_sizing,
    select_single_leg_contract,
    select_vertical_spread_legs,
)


def _sample_chain() -> list[dict]:
    return [
        {"strike": 480, "expiry": "2026-08-21", "right": "call", "delta": 0.75, "vega": 40.0},
        {"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.50, "vega": 45.0},
        {"strike": 520, "expiry": "2026-08-21", "right": "call", "delta": 0.25, "vega": 35.0},
        {"strike": 500, "expiry": "2026-08-21", "right": "put", "delta": -0.50, "vega": 45.0},
        {"strike": 480, "expiry": "2026-08-21", "right": "put", "delta": -0.25, "vega": 30.0},
    ]


# ---------------------------------------------------------------------------
# select_single_leg_contract
# ---------------------------------------------------------------------------


def test_select_single_leg_contract_picks_nearest_delta():
    contract = select_single_leg_contract(_sample_chain(), target_delta=0.5, right="call")
    assert contract["strike"] == 500


def test_select_single_leg_contract_picks_nearest_when_not_exact():
    contract = select_single_leg_contract(_sample_chain(), target_delta=0.68, right="call")
    assert contract["strike"] == 480  # |0.75-0.68|=0.07 is closer than |0.50-0.68|=0.18


def test_select_single_leg_contract_filters_by_right():
    contract = select_single_leg_contract(_sample_chain(), target_delta=0.5, right="put")
    assert contract["right"] == "put"
    assert contract["strike"] == 500


def test_select_single_leg_contract_empty_chain_returns_none():
    assert select_single_leg_contract([], target_delta=0.5, right="call") is None


def test_select_single_leg_contract_no_matching_right_returns_none():
    chain_calls_only = [row for row in _sample_chain() if row["right"] == "call"]
    assert select_single_leg_contract(chain_calls_only, target_delta=0.5, right="put") is None


def test_select_single_leg_contract_right_is_case_insensitive():
    contract = select_single_leg_contract(_sample_chain(), target_delta=0.5, right="CALL")
    assert contract is not None


# ---------------------------------------------------------------------------
# build_options_position_sizing
# ---------------------------------------------------------------------------


def test_build_options_position_sizing_buy_selects_calls():
    decision = build_options_position_sizing(
        "buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000, target_delta_at_full_confidence=0.5
    )
    assert decision is not None
    assert decision.right == "call"
    assert decision.contracts > 0


def test_build_options_position_sizing_short_selects_puts():
    decision = build_options_position_sizing(
        "short", confidence=0.8, available_chain=_sample_chain(), portfolio_value=1_000_000, target_delta_at_full_confidence=0.5
    )
    assert decision is not None
    assert decision.right == "put"


def test_build_options_position_sizing_sell_selects_puts():
    decision = build_options_position_sizing(
        "sell", confidence=0.8, available_chain=_sample_chain(), portfolio_value=1_000_000, target_delta_at_full_confidence=0.5
    )
    assert decision is not None
    assert decision.right == "put"


def test_build_options_position_sizing_target_delta_scales_with_confidence():
    full_conf = build_options_position_sizing(
        "buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000, target_delta_at_full_confidence=0.6
    )
    half_conf = build_options_position_sizing(
        "buy", confidence=0.5, available_chain=_sample_chain(), portfolio_value=1_000_000, target_delta_at_full_confidence=0.6
    )
    assert full_conf.target_delta == 0.6
    assert half_conf.target_delta == 0.3


def test_build_options_position_sizing_respects_vega_budget():
    decision = build_options_position_sizing(
        "buy",
        confidence=1.0,
        available_chain=_sample_chain(),
        portfolio_value=1_000_000,
        target_delta_at_full_confidence=0.5,
        max_vega_budget_pct_of_equity=0.02,
    )
    assert decision.vega_budget_used <= 0.02 + 1e-9


def test_build_options_position_sizing_empty_chain_returns_none():
    assert build_options_position_sizing("buy", confidence=1.0, available_chain=[], portfolio_value=1_000_000) is None


def test_build_options_position_sizing_zero_confidence_returns_none():
    assert build_options_position_sizing("buy", confidence=0.0, available_chain=_sample_chain(), portfolio_value=1_000_000) is None


def test_build_options_position_sizing_unknown_direction_returns_none():
    assert build_options_position_sizing("hold", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000) is None


def test_build_options_position_sizing_non_positive_portfolio_value_returns_none():
    assert build_options_position_sizing("buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=0.0) is None


def test_build_options_position_sizing_zero_vega_contract_returns_none():
    chain = [{"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.5, "vega": 0.0}]
    assert build_options_position_sizing("buy", confidence=1.0, available_chain=chain, portfolio_value=1_000_000) is None


# ---------------------------------------------------------------------------
# contract_symbol / to_dict() JSON-safety (main.py needs the real Symbol to
# place an order; the dashboard state writer needs a JSON-safe string - see
# portfolio/options_strategy.py::OptionsPositionDecision.to_dict()).
# ---------------------------------------------------------------------------


def test_build_options_position_sizing_populates_contract_symbol_from_chain_row():
    chain = [{"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.5, "vega": 45.0, "symbol": "SPY 260821C00500000"}]
    decision = build_options_position_sizing("buy", confidence=1.0, available_chain=chain, portfolio_value=1_000_000, target_delta_at_full_confidence=0.5)
    assert decision.contract_symbol == "SPY 260821C00500000"


def test_build_options_position_sizing_contract_symbol_none_when_chain_row_has_no_symbol():
    decision = build_options_position_sizing(
        "buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000, target_delta_at_full_confidence=0.5
    )
    assert decision.contract_symbol is None


def test_options_position_decision_to_dict_stringifies_non_none_contract_symbol():
    class _FakeLeanSymbol:
        def __str__(self) -> str:
            return "SPY 260821C00500000"

    decision = OptionsPositionDecision(
        contracts=3,
        right="call",
        strike=500.0,
        expiry="2026-08-21",
        target_delta=0.5,
        actual_delta=0.5,
        vega_budget_used=0.01,
        sizing_reason="delta_targeted_vega_budgeted_sizing",
        contract_symbol=_FakeLeanSymbol(),
    )
    result = decision.to_dict()
    assert result["contract_symbol"] == "SPY 260821C00500000"
    assert isinstance(result["contract_symbol"], str)


def test_options_position_decision_to_dict_emits_none_when_contract_symbol_absent():
    decision = OptionsPositionDecision(
        contracts=3,
        right="call",
        strike=500.0,
        expiry="2026-08-21",
        target_delta=0.5,
        actual_delta=0.5,
        vega_budget_used=0.01,
        sizing_reason="delta_targeted_vega_budgeted_sizing",
    )
    result = decision.to_dict()
    assert result["contract_symbol"] is None


def test_options_position_decision_to_dict_is_json_serializable():
    import json

    class _FakeLeanSymbol:
        def __str__(self) -> str:
            return "SPY 260821C00500000"

    decision = OptionsPositionDecision(
        contracts=3,
        right="call",
        strike=500.0,
        expiry="2026-08-21",
        target_delta=0.5,
        actual_delta=0.5,
        vega_budget_used=0.01,
        sizing_reason="delta_targeted_vega_budgeted_sizing",
        contract_symbol=_FakeLeanSymbol(),
    )
    json.dumps(decision.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# select_vertical_spread_legs / build_vertical_spread_position_sizing
# (execution/risk realism pass, part 3) - a deliberately minimal 2-leg
# vertical spread, explicit scope-in of the "multi-leg is a non-goal" note
# above. _sample_chain() already has 3 same-expiry call strikes and 2
# same-expiry put strikes, enough for both call and put verticals with no
# fixture changes needed.
# ---------------------------------------------------------------------------


def test_select_vertical_spread_legs_call_picks_correct_long_and_short():
    legs = select_vertical_spread_legs(_sample_chain(), target_delta=0.5, right="call", short_leg_delta_offset=0.20)
    assert legs is not None
    long_leg, short_leg = legs
    assert long_leg["strike"] == 500  # nearest to target_delta=0.5, same as select_single_leg_contract
    assert short_leg["strike"] == 520  # only call strike above 500 (risk-capping side)


def test_select_vertical_spread_legs_put_picks_correct_long_and_short():
    legs = select_vertical_spread_legs(_sample_chain(), target_delta=0.5, right="put", short_leg_delta_offset=0.20)
    assert legs is not None
    long_leg, short_leg = legs
    assert long_leg["strike"] == 500
    assert short_leg["strike"] == 480  # only put strike below 500 (risk-capping side)


def test_select_vertical_spread_legs_short_leg_matches_offset_delta():
    # target_delta=0.5, offset=0.20 -> short target = 0.30, nearest
    # available is strike 520 (delta 0.25) - the only same-expiry call
    # candidate above the long strike.
    legs = select_vertical_spread_legs(_sample_chain(), target_delta=0.5, right="call", short_leg_delta_offset=0.20)
    _, short_leg = legs
    assert short_leg["delta"] == 0.25


def test_select_vertical_spread_legs_no_usable_long_leg_returns_none():
    assert select_vertical_spread_legs([], target_delta=0.5, right="call", short_leg_delta_offset=0.20) is None


def test_select_vertical_spread_legs_no_usable_short_leg_returns_none():
    # Only one call strike at this expiry - a long leg exists, but no
    # candidate exists on the risk-capping side for a short leg.
    chain = [{"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.50, "vega": 45.0}]
    assert select_vertical_spread_legs(chain, target_delta=0.5, right="call", short_leg_delta_offset=0.20) is None


def test_select_vertical_spread_legs_ignores_different_expiry_candidates():
    chain = _sample_chain() + [
        {"strike": 540, "expiry": "2026-09-18", "right": "call", "delta": 0.20, "vega": 30.0},
    ]
    legs = select_vertical_spread_legs(chain, target_delta=0.5, right="call", short_leg_delta_offset=0.20)
    _, short_leg = legs
    assert short_leg["strike"] == 520  # NOT the different-expiry 540 strike, despite closer delta
    assert short_leg["expiry"] == "2026-08-21"


def test_build_vertical_spread_position_sizing_buy_selects_bull_call_spread():
    decision = build_vertical_spread_position_sizing(
        "buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000,
        target_delta_at_full_confidence=0.5, short_leg_delta_offset=0.20,
    )
    assert decision is not None
    assert decision.strategy_name == "bull_call_spread"
    assert decision.legs[0].side == "long"
    assert decision.legs[1].side == "short"
    assert decision.legs[0].strike == 500
    assert decision.legs[1].strike == 520


def test_build_vertical_spread_position_sizing_short_selects_bear_put_spread():
    decision = build_vertical_spread_position_sizing(
        "short", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000,
        target_delta_at_full_confidence=0.5, short_leg_delta_offset=0.20,
    )
    assert decision is not None
    assert decision.strategy_name == "bear_put_spread"
    assert decision.legs[0].strike == 500
    assert decision.legs[1].strike == 480


def test_build_vertical_spread_position_sizing_sizes_by_net_vega_not_long_leg_vega():
    # Long leg vega=45.0, short leg vega=35.0 -> net_vega_per_spread=10.0.
    # A budget sized against the FULL long-leg vega (45) would give fewer
    # contracts than one sized against the smaller net vega (10) -
    # confirms this function uses the net, not the long leg alone.
    decision = build_vertical_spread_position_sizing(
        "buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000,
        target_delta_at_full_confidence=0.5, short_leg_delta_offset=0.20, max_vega_budget_pct_of_equity=0.02,
    )
    budget = 0.02 * 1_000_000
    assert decision.contracts == int(budget // 10.0)


def test_build_vertical_spread_position_sizing_net_debit_from_bid_ask():
    chain = [
        {"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.50, "vega": 45.0, "bid": 10.0, "ask": 10.5},
        {"strike": 520, "expiry": "2026-08-21", "right": "call", "delta": 0.25, "vega": 35.0, "bid": 5.0, "ask": 5.5},
    ]
    decision = build_vertical_spread_position_sizing(
        "buy", confidence=1.0, available_chain=chain, portfolio_value=1_000_000,
        target_delta_at_full_confidence=0.5, short_leg_delta_offset=0.20,
    )
    assert decision.net_debit_or_credit == 10.5 - 5.0


def test_build_vertical_spread_position_sizing_net_debit_zero_when_bid_ask_absent():
    decision = build_vertical_spread_position_sizing(
        "buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000,
        target_delta_at_full_confidence=0.5, short_leg_delta_offset=0.20,
    )
    assert decision.net_debit_or_credit == 0.0


def test_build_vertical_spread_position_sizing_net_delta_is_long_minus_short():
    decision = build_vertical_spread_position_sizing(
        "buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000,
        target_delta_at_full_confidence=0.5, short_leg_delta_offset=0.20,
    )
    assert decision.net_delta == 0.50 - 0.25


def test_build_vertical_spread_position_sizing_empty_chain_returns_none():
    assert build_vertical_spread_position_sizing("buy", confidence=1.0, available_chain=[], portfolio_value=1_000_000) is None


def test_build_vertical_spread_position_sizing_zero_confidence_returns_none():
    assert (
        build_vertical_spread_position_sizing("buy", confidence=0.0, available_chain=_sample_chain(), portfolio_value=1_000_000)
        is None
    )


def test_build_vertical_spread_position_sizing_unknown_direction_returns_none():
    assert (
        build_vertical_spread_position_sizing("hold", confidence=1.0, available_chain=_sample_chain(), portfolio_value=1_000_000)
        is None
    )


def test_build_vertical_spread_position_sizing_non_positive_portfolio_value_returns_none():
    assert build_vertical_spread_position_sizing("buy", confidence=1.0, available_chain=_sample_chain(), portfolio_value=0.0) is None


def test_build_vertical_spread_position_sizing_no_usable_short_leg_returns_none():
    chain = [{"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.50, "vega": 45.0}]
    assert (
        build_vertical_spread_position_sizing("buy", confidence=1.0, available_chain=chain, portfolio_value=1_000_000)
        is None
    )


def test_build_vertical_spread_position_sizing_non_positive_net_vega_returns_none():
    # Short leg vega (50.0) exceeds long leg vega (45.0) -> net_vega <= 0,
    # unsizeable.
    chain = [
        {"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.50, "vega": 45.0},
        {"strike": 520, "expiry": "2026-08-21", "right": "call", "delta": 0.25, "vega": 50.0},
    ]
    assert (
        build_vertical_spread_position_sizing("buy", confidence=1.0, available_chain=chain, portfolio_value=1_000_000)
        is None
    )


def test_options_spread_leg_and_decision_to_dict_json_serializable():
    class _FakeLeanSymbol:
        def __init__(self, label: str) -> None:
            self._label = label

        def __str__(self) -> str:
            return self._label

    decision = OptionsSpreadPositionDecision(
        strategy_name="bull_call_spread",
        legs=(
            OptionsSpreadLeg(strike=500.0, right="call", side="long", contract_symbol=_FakeLeanSymbol("LEG_LONG")),
            OptionsSpreadLeg(strike=520.0, right="call", side="short", contract_symbol=_FakeLeanSymbol("LEG_SHORT")),
        ),
        expiry="2026-08-21",
        contracts=5,
        net_debit_or_credit=5.5,
        net_delta=0.25,
        net_vega=0.02,
        sizing_reason="delta_targeted_net_vega_budgeted_vertical_spread_sizing",
    )
    result = decision.to_dict()
    assert result["legs"][0]["contract_symbol"] == "LEG_LONG"
    assert result["legs"][1]["contract_symbol"] == "LEG_SHORT"
    assert isinstance(result["legs"][0]["contract_symbol"], str)
    json.dumps(result)  # must not raise


def test_options_spread_position_decision_to_dict_emits_none_for_absent_contract_symbol():
    decision = OptionsSpreadPositionDecision(
        strategy_name="bear_put_spread",
        legs=(
            OptionsSpreadLeg(strike=500.0, right="put", side="long"),
            OptionsSpreadLeg(strike=480.0, right="put", side="short"),
        ),
        expiry="2026-08-21",
        contracts=5,
        net_debit_or_credit=0.0,
        net_delta=-0.25,
        net_vega=0.02,
        sizing_reason="delta_targeted_net_vega_budgeted_vertical_spread_sizing",
    )
    result = decision.to_dict()
    assert result["legs"][0]["contract_symbol"] is None
    assert result["legs"][1]["contract_symbol"] is None
