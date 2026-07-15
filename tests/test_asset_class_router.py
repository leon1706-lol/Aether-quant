from risk.asset_class_router import (
    resolve_asset_class_enabled,
    route_position_sizing,
    should_liquidate_disabled_asset_class_position,
)
from risk.position_sizing import build_dynamic_position_sizing


def _equity_crypto_kwargs() -> dict:
    return dict(rolling_volatility=0.02, max_position_weight=0.2, target_daily_volatility=0.015)


def _es_spec() -> dict:
    return {"multiplier": 50, "tick_size": 0.25, "initial_margin_usd": 13200, "exchange": "CME"}


def _sample_chain() -> list[dict]:
    return [{"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.5, "vega": 45.0}]


def _vertical_spread_chain() -> list[dict]:
    # Two same-expiry call strikes - enough for a bull_call_spread long+
    # short leg pair (unlike _sample_chain()'s single strike above, which
    # is deliberately too thin for a vertical).
    return [
        {"strike": 500, "expiry": "2026-08-21", "right": "call", "delta": 0.50, "vega": 45.0},
        {"strike": 520, "expiry": "2026-08-21", "right": "call", "delta": 0.25, "vega": 35.0},
    ]


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


# ---------------------------------------------------------------------------
# resolve_asset_class_enabled / should_liquidate_disabled_asset_class_position
# ---------------------------------------------------------------------------


def test_resolve_asset_class_enabled_equity_crypto_bond_always_true():
    for asset_class in ("equity", "crypto", "bond", "unrecognized_class", None):
        assert resolve_asset_class_enabled(asset_class, futures_risk_enabled=False, options_risk_enabled=False) is True
        assert resolve_asset_class_enabled(asset_class, futures_risk_enabled=True, options_risk_enabled=True) is True


def test_resolve_asset_class_enabled_future_follows_futures_risk_flag():
    assert resolve_asset_class_enabled("future", futures_risk_enabled=True, options_risk_enabled=False) is True
    assert resolve_asset_class_enabled("future", futures_risk_enabled=False, options_risk_enabled=True) is False


def test_resolve_asset_class_enabled_option_follows_options_risk_flag():
    assert resolve_asset_class_enabled("option", futures_risk_enabled=False, options_risk_enabled=True) is True
    assert resolve_asset_class_enabled("option", futures_risk_enabled=True, options_risk_enabled=False) is False


def test_should_liquidate_disabled_asset_class_position_truth_table():
    assert should_liquidate_disabled_asset_class_position(asset_class_enabled=False, is_invested=True) is True
    assert should_liquidate_disabled_asset_class_position(asset_class_enabled=False, is_invested=False) is False
    assert should_liquidate_disabled_asset_class_position(asset_class_enabled=True, is_invested=True) is False
    assert should_liquidate_disabled_asset_class_position(asset_class_enabled=True, is_invested=False) is False


# ---------------------------------------------------------------------------
# option spread_strategy dispatch (execution/risk realism pass, part 3)
# ---------------------------------------------------------------------------


def test_option_default_spread_strategy_is_byte_identical_to_no_spread_strategy_key():
    # The critical zero-behavior-change proof: options_kwargs entirely
    # absent (today's calling convention, unchanged) must produce the
    # exact same result as options_kwargs explicitly saying "single_leg" -
    # confirms the new dispatch branch is unreachable at the default.
    baseline_decision, baseline_extra = route_position_sizing(
        "option", "buy", 1.0, 0.1, portfolio_value=1_000_000, available_chain=_sample_chain(),
        options_kwargs=dict(target_delta_at_full_confidence=0.5, max_vega_budget_pct_of_equity=0.02),
    )
    explicit_decision, explicit_extra = route_position_sizing(
        "option", "buy", 1.0, 0.1, portfolio_value=1_000_000, available_chain=_sample_chain(),
        options_kwargs=dict(spread_strategy="single_leg", target_delta_at_full_confidence=0.5, max_vega_budget_pct_of_equity=0.02),
    )
    assert baseline_decision == explicit_decision
    assert baseline_extra["options_decision"] == explicit_extra["options_decision"]


def test_option_single_leg_ignores_stray_short_leg_delta_offset_without_raising():
    # short_leg_delta_offset is a vertical-only kwarg -
    # build_options_position_sizing() doesn't accept it. Config could
    # legitimately carry it (e.g. staged for a future switch to
    # "vertical") even while spread_strategy stays "single_leg" - this
    # must never raise a TypeError.
    decision, extra = route_position_sizing(
        "option", "buy", 1.0, 0.1, portfolio_value=1_000_000, available_chain=_sample_chain(),
        options_kwargs=dict(
            spread_strategy="single_leg", short_leg_delta_offset=0.20,
            target_delta_at_full_confidence=0.5, max_vega_budget_pct_of_equity=0.02,
        ),
    )
    assert extra["options_decision"].__class__.__name__ == "OptionsPositionDecision"


def test_option_vertical_spread_strategy_returns_spread_decision():
    decision, extra = route_position_sizing(
        "option", "buy", 1.0, 0.1, portfolio_value=1_000_000, available_chain=_vertical_spread_chain(),
        options_kwargs=dict(
            spread_strategy="vertical", target_delta_at_full_confidence=0.5,
            short_leg_delta_offset=0.20, max_vega_budget_pct_of_equity=0.02,
        ),
    )
    assert extra["options_decision"].__class__.__name__ == "OptionsSpreadPositionDecision"
    assert extra["options_decision"].strategy_name == "bull_call_spread"
    assert decision.sizing_reason == "delta_targeted_net_vega_budgeted_vertical_spread_sizing"


def test_option_vertical_spread_short_selects_bear_put_spread():
    put_chain = [
        {"strike": 500, "expiry": "2026-08-21", "right": "put", "delta": -0.50, "vega": 45.0},
        {"strike": 480, "expiry": "2026-08-21", "right": "put", "delta": -0.25, "vega": 30.0},
    ]
    decision, extra = route_position_sizing(
        "option", "short", 1.0, -0.1, portfolio_value=1_000_000, available_chain=put_chain,
        options_kwargs=dict(
            spread_strategy="vertical", target_delta_at_full_confidence=0.5,
            short_leg_delta_offset=0.20, max_vega_budget_pct_of_equity=0.02,
        ),
    )
    assert extra["options_decision"].strategy_name == "bear_put_spread"


def test_option_vertical_spread_no_usable_spread_degrades_to_zero_no_crash():
    decision, extra = route_position_sizing(
        "option", "buy", 1.0, 0.1, portfolio_value=1_000_000, available_chain=_sample_chain(),  # single strike, no short leg possible
        options_kwargs=dict(spread_strategy="vertical", target_delta_at_full_confidence=0.5, short_leg_delta_offset=0.20),
    )
    assert extra == {}
    assert decision.target_weight == 0.0
    assert decision.sizing_reason == "no_usable_vertical_spread_or_zero_signal"
