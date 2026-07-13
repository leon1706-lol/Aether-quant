from risk.asset_class_router import route_position_sizing
from risk.position_sizing import build_dynamic_position_sizing


def _equity_crypto_kwargs() -> dict:
    return dict(rolling_volatility=0.02, max_position_weight=0.2, target_daily_volatility=0.015)


def _es_spec() -> dict:
    return {"multiplier": 50, "tick_size": 0.25, "initial_margin_usd": 13200, "exchange": "CME"}


def _sample_chain() -> list[dict]:
    return [{"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.5, "vega": 45.0}]


# ---------------------------------------------------------------------------
# equity / crypto / bond - existing, unchanged path (adapter transparency)
# ---------------------------------------------------------------------------


def test_equity_routes_byte_identical_to_direct_call():
    kwargs = _equity_crypto_kwargs()
    direct = build_dynamic_position_sizing(base_target_weight=0.1, confidence=0.8, **kwargs)
    routed, extra = route_position_sizing("equity", "buy", 0.8, 0.1, equity_crypto_kwargs=kwargs)
    assert routed == direct
    assert extra == {}


def test_crypto_routes_byte_identical_to_direct_call():
    kwargs = _equity_crypto_kwargs()
    direct = build_dynamic_position_sizing(base_target_weight=0.1, confidence=0.8, **kwargs)
    routed, extra = route_position_sizing("crypto", "buy", 0.8, 0.1, equity_crypto_kwargs=kwargs)
    assert routed == direct
    assert extra == {}


def test_bond_routes_byte_identical_to_direct_call():
    # Bonds get NO new sizing formula in this pass - only better upstream
    # features (features/bond_features.py); the router just dispatches
    # them through the existing volatility-scaled sizer unchanged.
    kwargs = _equity_crypto_kwargs()
    direct = build_dynamic_position_sizing(base_target_weight=0.1, confidence=0.8, **kwargs)
    routed, extra = route_position_sizing("bond", "buy", 0.8, 0.1, equity_crypto_kwargs=kwargs)
    assert routed == direct
    assert extra == {}


def test_unrecognized_asset_class_falls_back_to_equity_path():
    kwargs = _equity_crypto_kwargs()
    direct = build_dynamic_position_sizing(base_target_weight=0.1, confidence=0.8, **kwargs)
    routed, extra = route_position_sizing("unknown_future_asset_class", "buy", 0.8, 0.1, equity_crypto_kwargs=kwargs)
    assert routed == direct


# ---------------------------------------------------------------------------
# future
# ---------------------------------------------------------------------------


def test_future_returns_positive_contract_count_in_extra():
    decision, extra = route_position_sizing(
        "future", "buy", 1.0, 0.1, price=5000.0, portfolio_value=1_000_000, contract_spec=_es_spec()
    )
    assert "contract_count" in extra
    assert extra["contract_count"] > 0
    assert decision.target_weight > 0.0


def test_future_short_gives_negative_contract_count():
    decision, extra = route_position_sizing(
        "future", "short", 1.0, -0.1, price=5000.0, portfolio_value=1_000_000, contract_spec=_es_spec()
    )
    assert extra["contract_count"] < 0
    assert decision.target_weight < 0.0


def test_future_leverage_factor_is_margin_utilization_ratio():
    decision, _ = route_position_sizing(
        "future", "buy", 1.0, 0.1, price=5000.0, portfolio_value=1_000_000, contract_spec=_es_spec(),
        futures_kwargs=dict(target_margin_utilization=0.20, max_margin_utilization=0.40),
    )
    assert 0.0 <= decision.leverage_factor <= 1.0 + 1e-9


def test_future_missing_contract_spec_gives_zero_position():
    decision, extra = route_position_sizing("future", "buy", 1.0, 0.1, price=5000.0, portfolio_value=1_000_000, contract_spec=None)
    assert extra["contract_count"] == 0
    assert decision.target_weight == 0.0


# ---------------------------------------------------------------------------
# option
# ---------------------------------------------------------------------------


def test_option_with_usable_chain_returns_options_decision_in_extra():
    decision, extra = route_position_sizing(
        "option", "buy", 1.0, 0.1, portfolio_value=1_000_000, available_chain=_sample_chain(),
        options_kwargs=dict(target_delta_at_full_confidence=0.5, max_vega_budget_pct_of_equity=0.02),
    )
    assert "options_decision" in extra
    assert extra["options_decision"].right == "call"
    assert decision.sizing_reason == "delta_targeted_vega_budgeted_sizing"


def test_option_empty_chain_degrades_to_zero_no_crash():
    decision, extra = route_position_sizing("option", "buy", 1.0, 0.1, portfolio_value=1_000_000, available_chain=[])
    assert extra == {}
    assert decision.target_weight == 0.0
    assert decision.sizing_reason == "no_usable_option_contract_or_zero_signal"


def test_option_none_available_chain_degrades_to_zero_no_crash():
    decision, extra = route_position_sizing("option", "buy", 1.0, 0.1, portfolio_value=1_000_000, available_chain=None)
    assert extra == {}
    assert decision.target_weight == 0.0
