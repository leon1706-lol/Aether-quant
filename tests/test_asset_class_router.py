from datetime import date

from risk.asset_class_router import (
    resolve_asset_class_enabled,
    route_multi_leg_option_sizing,
    route_position_sizing,
    should_liquidate_disabled_asset_class_position,
)
from risk.position_sizing import build_dynamic_position_sizing


def _equity_crypto_kwargs() -> dict:
    return dict(rolling_volatility=0.02, max_position_weight=0.2, target_daily_volatility=0.015)


def _es_spec() -> dict:
    return {"multiplier": 50, "tick_size": 0.25, "initial_margin_usd": 13200, "exchange": "CME"}


def _eurusd_spec() -> dict:
    return {"pip_size": 0.0001, "lot_size": 100000, "leverage_max": 50, "margin_pct": 0.02}


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
# forex (V4.6)
# ---------------------------------------------------------------------------


def test_forex_returns_positive_lot_count_in_extra():
    decision, extra = route_position_sizing(
        "forex", "buy", 1.0, 0.1, price=1.10, portfolio_value=1_000_000, pair_spec=_eurusd_spec()
    )
    assert "lot_count" in extra
    assert extra["lot_count"] > 0
    assert decision.target_weight > 0.0


def test_forex_short_gives_negative_lot_count():
    decision, extra = route_position_sizing(
        "forex", "short", 1.0, -0.1, price=1.10, portfolio_value=1_000_000, pair_spec=_eurusd_spec()
    )
    assert extra["lot_count"] < 0
    assert decision.target_weight < 0.0


def test_forex_leverage_factor_is_margin_utilization_ratio():
    decision, _ = route_position_sizing(
        "forex", "buy", 1.0, 0.1, price=1.10, portfolio_value=1_000_000, pair_spec=_eurusd_spec(),
        forex_kwargs=dict(target_leverage_utilization=0.20, max_leverage_utilization=0.40),
    )
    assert 0.0 <= decision.leverage_factor <= 1.0 + 1e-9


def test_forex_missing_pair_spec_gives_zero_position():
    decision, extra = route_position_sizing("forex", "buy", 1.0, 0.1, price=1.10, portfolio_value=1_000_000, pair_spec=None)
    assert extra["lot_count"] == 0
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


def test_resolve_asset_class_enabled_forex_follows_forex_risk_flag():
    assert resolve_asset_class_enabled("forex", False, False, forex_risk_enabled=True) is True
    assert resolve_asset_class_enabled("forex", False, False, forex_risk_enabled=False) is False


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


# ---------------------------------------------------------------------------
# route_multi_leg_option_sizing (V4.5 - full OptionStrategies coverage)
# ---------------------------------------------------------------------------


def _full_coverage_chain() -> list[dict]:
    rows = []
    for strike in range(70, 131, 5):
        call_delta = max(0.02, min(0.98, 0.5 + (100 - strike) * 0.02))
        put_delta = call_delta - 1.0
        distance = abs(strike - 100)
        vega = max(0.1, 3.0 - distance * 0.15)
        rows.append({"symbol": f"C{strike}", "right": "call", "strike": float(strike), "expiry": "2026-08-21", "delta": call_delta, "vega": vega, "bid": 1.0, "ask": 1.1})
        rows.append({"symbol": f"P{strike}", "right": "put", "strike": float(strike), "expiry": "2026-08-21", "delta": put_delta, "vega": vega, "bid": 1.0, "ask": 1.1})
    return rows


def _multi_leg_kwargs(**overrides) -> dict:
    base = dict(
        target_delta_at_full_confidence=0.6, max_vega_budget_pct_of_equity=0.02, short_leg_delta_offset=0.20,
        contract_multiplier=100.0, target_margin_utilization=0.20, max_margin_utilization=0.40,
        pct_of_underlying_value=0.20, min_pct_of_underlying_value=0.10,
    )
    base.update(overrides)
    return base


def test_route_multi_leg_option_sizing_default_list_single_leg_wins():
    result = route_multi_leg_option_sizing(
        ["single_leg", "bull_call_spread", "bear_put_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False, **_multi_leg_kwargs(),
    )
    assert result is not None
    decision, extra = result
    assert extra["options_decision"].right == "call"


def test_route_multi_leg_option_sizing_short_vol_prefers_iron_condor_over_short_straddle():
    result = route_multi_leg_option_sizing(
        ["short_straddle", "iron_condor"], "sell", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "short_vol", "defined_risk_first", True, **_multi_leg_kwargs(),
    )
    assert result is not None
    _, extra = result
    assert extra["options_decision"].strategy_name == "iron_condor"


def test_route_multi_leg_option_sizing_neutral_view_excludes_straddle_and_iron_condor():
    result = route_multi_leg_option_sizing(
        ["short_straddle", "iron_condor"], "sell", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", True, **_multi_leg_kwargs(),
    )
    assert result is None


def test_route_multi_leg_option_sizing_margin_tier_requires_margin_family_enabled():
    disabled = route_multi_leg_option_sizing(
        ["naked_call"], "sell", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False, **_multi_leg_kwargs(),
    )
    assert disabled is None
    enabled = route_multi_leg_option_sizing(
        ["naked_call"], "sell", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", True, **_multi_leg_kwargs(),
    )
    assert enabled is not None
    assert enabled[1]["options_decision"].strategy_name == "naked_call"


def test_route_multi_leg_option_sizing_covered_protective_never_selected():
    result = route_multi_leg_option_sizing(
        ["covered_call"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", True, **_multi_leg_kwargs(),
    )
    assert result is None


def test_route_multi_leg_option_sizing_arbitrage_never_selected():
    result = route_multi_leg_option_sizing(
        ["box_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", True, **_multi_leg_kwargs(),
    )
    assert result is None


def test_route_multi_leg_option_sizing_empty_enabled_list_returns_none():
    result = route_multi_leg_option_sizing(
        [], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False, **_multi_leg_kwargs(),
    )
    assert result is None


# ---------------------------------------------------------------------------
# route_multi_leg_option_sizing - arbitrage mispricing detector (V4.6,
# development/Problems.md #60)
# ---------------------------------------------------------------------------


def test_route_multi_leg_option_sizing_arbitrage_disabled_by_default_stays_unreachable():
    # _multi_leg_kwargs() doesn't set arbitrage_detector_enabled - confirms
    # the router's own default (False) keeps box_spread unreachable even
    # when explicitly the only enabled name.
    result = route_multi_leg_option_sizing(
        ["box_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False, **_multi_leg_kwargs(),
    )
    assert result is None


def test_route_multi_leg_option_sizing_arbitrage_enabled_and_mispriced_sizes():
    result = route_multi_leg_option_sizing(
        ["box_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False,
        current_date=date(2026, 7, 21), risk_free_rate=0.045, arbitrage_detector_enabled=True, min_mispricing_bps=1.0,
        **_multi_leg_kwargs(),
    )
    assert result is not None
    _, extra = result
    assert extra["options_decision"].strategy_name == "box_spread"


def test_route_multi_leg_option_sizing_arbitrage_enabled_but_huge_threshold_stays_unreachable():
    result = route_multi_leg_option_sizing(
        ["box_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False,
        current_date=date(2026, 7, 21), risk_free_rate=0.045, arbitrage_detector_enabled=True, min_mispricing_bps=1_000_000.0,
        **_multi_leg_kwargs(),
    )
    assert result is None


# ---------------------------------------------------------------------------
# route_multi_leg_option_sizing - strategy_selector_scores (V4.7,
# development/Problems.md #29's own framing)
# ---------------------------------------------------------------------------


def test_route_multi_leg_option_sizing_no_scores_matches_static_ordering():
    # Byte-identical-default check: omitting strategy_selector_scores (or
    # passing None/{}) must reproduce exactly today's
    # order_enabled_strategies() winner.
    baseline = route_multi_leg_option_sizing(
        ["single_leg", "bull_call_spread", "bear_put_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False, **_multi_leg_kwargs(),
    )
    with_none = route_multi_leg_option_sizing(
        ["single_leg", "bull_call_spread", "bear_put_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False, strategy_selector_scores=None, **_multi_leg_kwargs(),
    )
    with_empty = route_multi_leg_option_sizing(
        ["single_leg", "bull_call_spread", "bear_put_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False, strategy_selector_scores={}, **_multi_leg_kwargs(),
    )
    assert baseline is not None
    assert baseline[0] == with_none[0] == with_empty[0]


def test_route_multi_leg_option_sizing_scores_rerank_the_winner():
    # Confirms baseline: with no scores, "single_leg" wins (its own
    # dedicated test above already asserts this exact fixture's winner).
    baseline = route_multi_leg_option_sizing(
        ["single_leg", "bull_call_spread", "bear_put_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False, **_multi_leg_kwargs(),
    )
    assert baseline is not None
    assert baseline[1]["options_decision"].right == "call"  # single_leg call, per the existing test above

    # A strong score for bull_call_spread should make IT win instead, even
    # though single_leg would otherwise be tried first.
    scored = route_multi_leg_option_sizing(
        ["single_leg", "bull_call_spread", "bear_put_spread"], "buy", 0.8, _full_coverage_chain(), 1_000_000, 100.0,
        "neutral", "defined_risk_first", False,
        strategy_selector_scores={"bull_call_spread": 10.0, "single_leg": -10.0, "bear_put_spread": -10.0},
        **_multi_leg_kwargs(),
    )
    assert scored is not None
    _, extra = scored
    assert extra["options_decision"].strategy_name == "bull_call_spread"
