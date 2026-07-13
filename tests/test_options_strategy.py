from portfolio.options_strategy import build_options_position_sizing, select_single_leg_contract


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
