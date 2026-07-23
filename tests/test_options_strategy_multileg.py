"""V4.5 - full OptionStrategies coverage: registry, shape-family selectors,
multi-leg sizing, volatility-view classification, and strategy-selection
ordering. Kept separate from the existing ~1000-line test_options_strategy.py
(that file's single-leg/2-leg-vertical coverage is completely untouched)."""

import math

from portfolio.options_strategy import (
    ANNUALIZATION_FACTOR_DAILY_TO_ANNUAL,
    MULTI_LEG_STRATEGY_REGISTRY,
    atm_implied_volatility,
    build_covered_protective_position_sizing,
    build_multi_leg_position_sizing,
    build_multi_leg_position_sizing_for_legs,
    classify_volatility_view,
    option_auto_close_due,
    order_enabled_strategies,
    resolve_enabled_strategy_names,
    rotation_cooldown_active,
    select_strategy_legs,
    strategies_for_volatility_view,
)
from datetime import date


def _sample_chain(expiries=("2026-08-21",)) -> list[dict]:
    """Realistic-shaped synthetic chain: vega peaks ATM and decays away
    from spot (needed so credit verticals/iron condors, whose anchor leg
    is the near-money SHORT leg, produce a nonzero net vega - a flat vega
    curve would make every credit structure's net vega exactly 0, an
    artifact of the fixture, not a real sizing failure)."""
    rows = []
    for expiry in expiries:
        for strike in range(70, 131, 5):
            call_delta = max(0.02, min(0.98, 0.5 + (100 - strike) * 0.02))
            put_delta = call_delta - 1.0
            distance = abs(strike - 100)
            vega = max(0.1, 3.0 - distance * 0.15)
            rows.append({
                "symbol": f"C{strike}_{expiry}", "right": "call", "strike": float(strike), "expiry": expiry,
                "delta": call_delta, "vega": vega, "bid": 1.0, "ask": 1.1, "iv": 0.25,
            })
            rows.append({
                "symbol": f"P{strike}_{expiry}", "right": "put", "strike": float(strike), "expiry": expiry,
                "delta": put_delta, "vega": vega, "bid": 1.0, "ask": 1.1, "iv": 0.25,
            })
    return rows


# ---------------------------------------------------------------------------
# Registry completeness and ground-truth arg_order cross-checks
# ---------------------------------------------------------------------------


def test_registry_has_all_43_strategies():
    assert len(MULTI_LEG_STRATEGY_REGISTRY) == 43


def test_registry_factory_names_are_unique_and_match_keys_or_known_aliases():
    # butterfly_call/call_butterfly and butterfly_put/put_butterfly are the
    # only real aliased-factory pairs (2 distinct OptionStrategies attrs,
    # identical legs) - every other entry's factory_name equals its own key.
    aliases = {"butterfly_call", "call_butterfly", "butterfly_put", "put_butterfly"}
    for name, spec in MULTI_LEG_STRATEGY_REGISTRY.items():
        if name in aliases:
            continue
        assert spec.factory_name == name


def test_iron_condor_vs_short_iron_condor_arg_order_is_asymmetric():
    # The single highest-value ground-truth check this module has - a wrong
    # strike-order silently builds the WRONG structure, never crashes.
    assert MULTI_LEG_STRATEGY_REGISTRY["iron_condor"].arg_order == ("long_put", "short_put", "short_call", "long_call")
    assert MULTI_LEG_STRATEGY_REGISTRY["short_iron_condor"].arg_order == ("short_put", "long_put", "long_call", "short_call")


def test_call_backspread_vs_put_backspread_arg_order_is_asymmetric():
    assert MULTI_LEG_STRATEGY_REGISTRY["call_backspread"].arg_order == ("lower", "higher")
    assert MULTI_LEG_STRATEGY_REGISTRY["put_backspread"].arg_order == ("higher", "lower")


def test_bull_call_spread_and_bear_put_spread_are_debit_shaped_anchor_long():
    for name in ("bull_call_spread", "bear_put_spread"):
        spec = MULTI_LEG_STRATEGY_REGISTRY[name]
        anchor_leg = next(leg for leg in spec.legs if leg.is_anchor)
        assert anchor_leg.side == "long"


def test_bear_call_spread_and_bull_put_spread_are_credit_shaped_anchor_short():
    for name in ("bear_call_spread", "bull_put_spread"):
        spec = MULTI_LEG_STRATEGY_REGISTRY[name]
        anchor_leg = next(leg for leg in spec.legs if leg.is_anchor)
        assert anchor_leg.side == "short"


def test_ladder_risk_tier_correction_only_net_short_ladders_are_margin_uncovered():
    # Real correction found transcribing the actual Lean leg quantities
    # (development/Problems.md): bear_call_ladder/bull_put_ladder are
    # net-long (bounded), bull_call_ladder/bear_put_ladder are net-short
    # (genuinely unbounded).
    assert MULTI_LEG_STRATEGY_REGISTRY["bear_call_ladder"].risk_tier == "vega_budget"
    assert MULTI_LEG_STRATEGY_REGISTRY["bull_put_ladder"].risk_tier == "vega_budget"
    assert MULTI_LEG_STRATEGY_REGISTRY["bull_call_ladder"].risk_tier == "margin_uncovered_leg"
    assert MULTI_LEG_STRATEGY_REGISTRY["bear_put_ladder"].risk_tier == "margin_uncovered_leg"


def test_backspread_risk_tier_correction_only_inverted_backspreads_are_naked():
    assert MULTI_LEG_STRATEGY_REGISTRY["call_backspread"].risk_tier == "margin_bounded_backspread"
    assert MULTI_LEG_STRATEGY_REGISTRY["put_backspread"].risk_tier == "margin_bounded_backspread"
    assert MULTI_LEG_STRATEGY_REGISTRY["short_call_backspread"].risk_tier == "margin_naked"
    assert MULTI_LEG_STRATEGY_REGISTRY["short_put_backspread"].risk_tier == "margin_naked"


def test_arbitrage_strategies_are_tagged_unreachable():
    for name in ("box_spread", "short_box_spread", "conversion", "reverse_conversion", "jelly_roll", "short_jelly_roll"):
        assert MULTI_LEG_STRATEGY_REGISTRY[name].risk_tier == "unreachable_arbitrage"


def test_covered_protective_covering_equity_side_matches_real_leg_direction():
    # covered_call/protective_put/protective_collar pair with a LONG equity
    # holding; covered_put/protective_call pair with a SHORT one (Lean's
    # CoveredPut/ProtectiveCall both carry a negative underlying quantity).
    assert MULTI_LEG_STRATEGY_REGISTRY["covered_call"].covering_equity_side == "long"
    assert MULTI_LEG_STRATEGY_REGISTRY["protective_put"].covering_equity_side == "long"
    assert MULTI_LEG_STRATEGY_REGISTRY["protective_collar"].covering_equity_side == "long"
    assert MULTI_LEG_STRATEGY_REGISTRY["covered_put"].covering_equity_side == "short"
    assert MULTI_LEG_STRATEGY_REGISTRY["protective_call"].covering_equity_side == "short"


# ---------------------------------------------------------------------------
# select_strategy_legs - every registered strategy resolves against a
# realistic synthetic chain
# ---------------------------------------------------------------------------


def test_select_strategy_legs_resolves_every_registered_strategy():
    single_expiry_chain = _sample_chain()
    two_expiry_chain = _sample_chain(("2026-08-21", "2026-09-18"))
    for name, spec in MULTI_LEG_STRATEGY_REGISTRY.items():
        chain = two_expiry_chain if spec.has_expiry_pair else single_expiry_chain
        target_delta = 0.3 if spec.shape_family == "collar" else 0.5
        legs_by_role = select_strategy_legs(name, chain, target_delta)
        assert legs_by_role is not None, f"{name} failed to select legs"
        assert len(legs_by_role) == len(spec.legs), f"{name} returned {len(legs_by_role)} legs, expected {len(spec.legs)}"


def test_iron_condor_selector_produces_strictly_ascending_strikes():
    legs = select_strategy_legs("iron_condor", _sample_chain(), 0.5)
    strikes = [legs["long_put"]["strike"], legs["short_put"]["strike"], legs["short_call"]["strike"], legs["long_call"]["strike"]]
    assert strikes == sorted(strikes)
    assert len(set(strikes)) == 4


def test_protective_collar_selector_produces_call_strike_above_put_strike():
    legs = select_strategy_legs("protective_collar", _sample_chain(), 0.3)
    assert legs["call"]["strike"] > legs["put"]["strike"]


def test_calendar_selector_requires_at_least_two_expiries():
    # A one-expiry chain must degrade to None, never crash or silently
    # pick a same-expiry pair for a strategy whose whole point is 2
    # DIFFERENT expiries.
    assert select_strategy_legs("call_calendar_spread", _sample_chain(("2026-08-21",)), 0.5) is None
    legs = select_strategy_legs("call_calendar_spread", _sample_chain(("2026-08-21", "2026-09-18")), 0.5)
    assert legs is not None
    assert legs["near"]["expiry"] != legs["far"]["expiry"]
    assert legs["near"]["strike"] == legs["far"]["strike"]


def test_expiry_drift_regression_iron_condor_stays_on_one_expiry_with_two_present():
    # The core expiry-anchoring bug this pass fixes: a chain with 2
    # distinct expiries must not let the put side and call side land on
    # different ones.
    chain = _sample_chain(("2026-08-21", "2026-09-18"))
    legs = select_strategy_legs("iron_condor", chain, 0.5)
    expiries = {row["expiry"] for row in legs.values()}
    assert len(expiries) == 1


# ---------------------------------------------------------------------------
# build_multi_leg_position_sizing - vega-budget tier only
# ---------------------------------------------------------------------------


def test_build_multi_leg_position_sizing_iron_condor_sizes_by_absolute_net_vega():
    # A credit structure's anchor leg is the near-money SHORT (higher
    # vega) one - net_vega is structurally NEGATIVE by construction, the
    # real bug this pass fixes: sizing must budget by magnitude, not
    # require positivity.
    decision = build_multi_leg_position_sizing("iron_condor", "sell", 0.8, _sample_chain(), 1_000_000, max_vega_budget_pct_of_equity=0.02)
    assert decision is not None
    assert decision.contracts > 0
    assert decision.net_vega > 0  # reported as a positive budget-used fraction regardless of sign


def test_build_multi_leg_position_sizing_rejects_non_vega_budget_tier():
    assert build_multi_leg_position_sizing("naked_call", "sell", 0.8, _sample_chain(), 1_000_000) is None
    assert build_multi_leg_position_sizing("box_spread", "buy", 0.8, _sample_chain(), 1_000_000) is None


def test_build_multi_leg_position_sizing_zero_confidence_returns_none():
    assert build_multi_leg_position_sizing("straddle", "buy", 0.0, _sample_chain(), 1_000_000) is None


def test_build_multi_leg_position_sizing_butterfly_ratio_recovery():
    decision = build_multi_leg_position_sizing("butterfly_call", "buy", 0.8, _sample_chain(), 1_000_000, max_vega_budget_pct_of_equity=0.02)
    assert decision is not None
    strikes = sorted(leg.strike for leg in decision.legs)
    assert strikes[0] < strikes[1] < strikes[2] or strikes[0] < strikes[1] == strikes[1] < strikes[2]


def test_build_multi_leg_position_sizing_for_legs_resizes_held_position():
    # Mirrors how main.py's _resize_multi_leg_record() resolves a held
    # position's OWN current chain rows (via _option_chain_row_for_contract())
    # and re-sizes on those, skipping selection entirely.
    legs_by_role = select_strategy_legs("iron_condor", _sample_chain(), 0.5)
    resized = build_multi_leg_position_sizing_for_legs("iron_condor", legs_by_role, 1_000_000, max_vega_budget_pct_of_equity=0.02)
    assert resized is not None
    assert resized.contracts > 0


# ---------------------------------------------------------------------------
# Volatility-view classification
# ---------------------------------------------------------------------------


def test_atm_implied_volatility_averages_call_and_put_at_nearest_to_50_delta():
    chain = _sample_chain()
    atm_iv = atm_implied_volatility(chain, "2026-08-21")
    assert atm_iv == 0.25


def test_atm_implied_volatility_returns_none_for_unknown_expiry():
    assert atm_implied_volatility(_sample_chain(), "2099-01-01") is None


def test_classify_volatility_view_long_vol_when_predicted_exceeds_atm_iv_by_margin():
    assert classify_volatility_view(0.35, 0.25, margin=0.05) == "long_vol"


def test_classify_volatility_view_short_vol_when_predicted_below_atm_iv_by_margin():
    assert classify_volatility_view(0.15, 0.25, margin=0.05) == "short_vol"


def test_classify_volatility_view_neutral_within_margin():
    assert classify_volatility_view(0.26, 0.25, margin=0.05) == "neutral"


def test_annualization_factor_matches_sqrt_252():
    assert math.isclose(ANNUALIZATION_FACTOR_DAILY_TO_ANNUAL, math.sqrt(252))


def test_daily_volatility_proxy_requires_annualization_before_comparison_is_meaningful():
    # train.py's target_volatility_next_day is a DAILY high-low-range
    # proxy - comparing it raw against annualized chain IV would almost
    # always read as "short_vol" (a unit-mismatch false signal). Annualizing
    # first is what makes the comparison meaningful.
    daily_proxy = 0.02  # a plausible daily high-low range, e.g. 2%
    atm_iv = 0.25  # a plausible annualized chain IV
    assert classify_volatility_view(daily_proxy, atm_iv, margin=0.05) == "short_vol"  # unit-mismatched: wrong
    annualized = daily_proxy * ANNUALIZATION_FACTOR_DAILY_TO_ANNUAL
    assert annualized > atm_iv  # correctly unit-matched: this is actually a HIGH-vol regime


# ---------------------------------------------------------------------------
# strategies_for_volatility_view / order_enabled_strategies (§9.2)
# ---------------------------------------------------------------------------


def test_strategies_for_volatility_view_long_vol_is_straddle_and_strangle_only():
    assert strategies_for_volatility_view("long_vol") == frozenset({"straddle", "strangle"})


def test_strategies_for_volatility_view_short_vol_includes_iron_and_short_straddle_strangle():
    result = strategies_for_volatility_view("short_vol")
    assert result == frozenset({
        "short_straddle", "short_strangle", "iron_condor", "short_iron_condor", "iron_butterfly", "short_iron_butterfly",
    })


def test_strategies_for_volatility_view_neutral_is_empty():
    assert strategies_for_volatility_view("neutral") == frozenset()


def test_order_enabled_strategies_defined_risk_first_prefers_iron_condor():
    ordered = order_enabled_strategies(["short_straddle", "iron_condor", "short_strangle"], "defined_risk_first")
    assert ordered[0] == "iron_condor"


def test_order_enabled_strategies_premium_maximizing_first_prefers_short_straddle():
    ordered = order_enabled_strategies(["iron_condor", "short_straddle", "short_strangle"], "premium_maximizing_first")
    assert ordered[0] in ("short_straddle", "short_strangle")
    assert ordered[-1] == "iron_condor"


def test_order_enabled_strategies_preserves_relative_order_within_group():
    ordered = order_enabled_strategies(["short_strangle", "short_straddle", "iron_butterfly", "iron_condor"], "defined_risk_first")
    assert ordered.index("iron_butterfly") < ordered.index("iron_condor")
    assert ordered.index("short_strangle") < ordered.index("short_straddle")


def test_order_enabled_strategies_never_drops_or_adds_names():
    names = ["single_leg", "bull_call_spread", "bear_put_spread"]
    assert sorted(order_enabled_strategies(names, "defined_risk_first")) == sorted(names)


# ---------------------------------------------------------------------------
# Covered/protective sizing (§6/§9.3/§9.6)
# ---------------------------------------------------------------------------


def test_build_covered_protective_position_sizing_floors_contracts_from_equity_quantity():
    decision = build_covered_protective_position_sizing("covered_call", 0.8, _sample_chain(), equity_quantity=250, contract_multiplier=100)
    assert decision is not None
    assert decision.contracts == 2  # floor(250/100), never 2.5 or 3


def test_build_covered_protective_position_sizing_rejects_wrong_equity_sign():
    # covered_call needs a LONG equity holding - a short one must reject,
    # not silently size against the wrong side of the book.
    assert build_covered_protective_position_sizing("covered_call", 0.8, _sample_chain(), equity_quantity=-250, contract_multiplier=100) is None


def test_build_covered_protective_position_sizing_covered_put_needs_short_equity():
    decision = build_covered_protective_position_sizing("covered_put", 0.8, _sample_chain(), equity_quantity=-150, contract_multiplier=100)
    assert decision is not None
    assert decision.contracts == 1


def test_build_covered_protective_position_sizing_below_one_contract_returns_none():
    assert build_covered_protective_position_sizing("covered_call", 0.8, _sample_chain(), equity_quantity=50, contract_multiplier=100) is None


def test_build_covered_protective_position_sizing_protective_collar_has_two_legs():
    decision = build_covered_protective_position_sizing("protective_collar", 0.8, _sample_chain(), equity_quantity=100, contract_multiplier=100)
    assert decision is not None
    assert len(decision.legs) == 2
    assert {leg.right for leg in decision.legs} == {"call", "put"}


# ---------------------------------------------------------------------------
# option_auto_close_due (§9.5)
# ---------------------------------------------------------------------------


def test_option_auto_close_due_fires_within_window():
    assert option_auto_close_due(date(2026, 8, 19), date(2026, 8, 21), auto_close_days_before_expiry=2) is True
    assert option_auto_close_due(date(2026, 8, 20), date(2026, 8, 21), auto_close_days_before_expiry=2) is True


def test_option_auto_close_due_does_not_fire_outside_window():
    assert option_auto_close_due(date(2026, 8, 18), date(2026, 8, 21), auto_close_days_before_expiry=2) is False


def test_option_auto_close_due_fires_on_expiry_day_itself():
    assert option_auto_close_due(date(2026, 8, 21), date(2026, 8, 21), auto_close_days_before_expiry=2) is True


def test_option_auto_close_due_none_inputs_return_false():
    assert option_auto_close_due(None, date(2026, 8, 21)) is False
    assert option_auto_close_due(date(2026, 8, 21), None) is False


# ---------------------------------------------------------------------------
# resolve_enabled_strategy_names (V4.6, development/Problems.md #59)
# ---------------------------------------------------------------------------


def test_resolve_enabled_strategy_names_returns_global_default_when_no_override():
    asset = {"ticker": "SPY_OPT", "security_type": "option"}
    assert resolve_enabled_strategy_names(asset, ["single_leg", "bull_call_spread"]) == ["single_leg", "bull_call_spread"]


def test_resolve_enabled_strategy_names_uses_override_when_present():
    asset = {"ticker": "SPY_OPT", "options_strategy_override": {"enabled_strategy_names": ["iron_condor"]}}
    assert resolve_enabled_strategy_names(asset, ["single_leg"]) == ["iron_condor"]


def test_resolve_enabled_strategy_names_ignores_empty_override_list():
    asset = {"ticker": "SPY_OPT", "options_strategy_override": {"enabled_strategy_names": []}}
    assert resolve_enabled_strategy_names(asset, ["single_leg"]) == ["single_leg"]


def test_resolve_enabled_strategy_names_ignores_malformed_override():
    asset = {"ticker": "SPY_OPT", "options_strategy_override": {"enabled_strategy_names": "not_a_list"}}
    assert resolve_enabled_strategy_names(asset, ["single_leg"]) == ["single_leg"]


def test_resolve_enabled_strategy_names_no_override_key_at_all():
    assert resolve_enabled_strategy_names({}, ["single_leg"]) == ["single_leg"]


# ---------------------------------------------------------------------------
# rotation_cooldown_active (V4.6, development/Problems.md #57/#58/#59)
# ---------------------------------------------------------------------------


def test_rotation_cooldown_active_true_within_window():
    assert rotation_cooldown_active(current_bar_index=103, last_rotation_bar=100, cooldown_bars=5) is True


def test_rotation_cooldown_active_false_outside_window():
    assert rotation_cooldown_active(current_bar_index=106, last_rotation_bar=100, cooldown_bars=5) is False


def test_rotation_cooldown_active_false_when_never_rotated():
    assert rotation_cooldown_active(current_bar_index=103, last_rotation_bar=None, cooldown_bars=5) is False


def test_rotation_cooldown_active_boundary_at_exact_cooldown_bars():
    # exactly cooldown_bars later - no longer active (strict less-than)
    assert rotation_cooldown_active(current_bar_index=105, last_rotation_bar=100, cooldown_bars=5) is False
