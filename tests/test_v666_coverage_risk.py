"""The last unreached branches of risk/ (V6.6.6, #359): each degrades to a safe value instead of raising."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from risk.asset_class_router import asset_listed_on_venue
from risk.forex_risk import ForexSizingDecision, cap_forex_target_to_book_weight
from risk.futures_risk import FuturesSizingDecision
from risk.kelly import kelly_weights
from risk.kill_switch import KillSwitchDecision, _finite_or_none
from risk.position_sizing import _resolve_effective_volatility
from risk.rl_sizing import RL_SIZING_STATE_KEYS, resolve_rl_shadow_guard, rl_excess_return, rl_shadow_guard_allows, rl_sizing_multiplier
from risk.vol_target import volatility_target_weights


def test_decisions_serialise_to_plain_dicts():
    assert KillSwitchDecision(tripped=False, severity="none").to_dict()["recommended_action"] == "none"
    forex = ForexSizingDecision(1, 1.0, 1.0, 0.1, 0.01, 0.01, 1.0, 0.1, "x")
    futures = FuturesSizingDecision(1, 1.0, 1.0, 0.1, 0.01, 0.01, 1.0, 0.1, "x")
    assert forex.to_dict()["lot_count"] == 1 and futures.to_dict()["contract_count"] == 1


def test_non_numbers_degrade_to_nothing_or_zero():
    assert _finite_or_none("abc") is None and _finite_or_none(None) is None and _finite_or_none(float("nan")) is None and _finite_or_none("2.5") == 2.5
    assert cap_forex_target_to_book_weight("x", 0.1) == 0.0 and cap_forex_target_to_book_weight(0.05, None) == 0.0


def test_predicted_volatility_is_used_only_when_asked_and_present():
    assert _resolve_effective_volatility(0.02, -0.03, True) == (0.03, "predicted")
    assert _resolve_effective_volatility(0.02, None, True) == (0.02, "rolling")
    assert _resolve_effective_volatility(0.02, 0.03, False) == (0.02, "rolling")


def test_kelly_and_vol_targeting_return_zeros_on_bad_input():
    mu, cov = np.array([0.1, 0.2]), np.eye(2)
    assert not kelly_weights(mu, cov, fraction=float("nan")).any() and not kelly_weights(mu, cov, gross_cap=float("inf")).any()
    assert not kelly_weights(mu, np.zeros((2, 2)), ridge=0.0).any(), "a singular system"
    huge = np.array([[1e-300, 0.0], [0.0, 1.0]])
    assert not kelly_weights(np.array([1e300, 1.0]), huge, ridge=0.0).any(), "non-finite weights"
    frame = pd.DataFrame(np.eye(2), index=["A", "B"], columns=["A", "B"])
    assert volatility_target_weights({"A": 0.5}, frame, target_annual_vol=0.1, max_leverage=float("nan")) == {"A": 0.0}
    assert volatility_target_weights({"Z": 0.5}, frame, target_annual_vol=0.1) == {}


def _model():
    n = len(RL_SIZING_STATE_KEYS)
    return {"state_keys": list(RL_SIZING_STATE_KEYS), "actions": [0.6, 1.0], "weights": [[0.0] * (n - 1), [0.0] * n], "bias": [0.0, 1.0], "mean": [0.0] * n, "scale": [1.0] * n}


def test_a_model_whose_action_row_is_the_wrong_length_is_malformed():
    state = {key: 0.0 for key in RL_SIZING_STATE_KEYS}
    assert rl_sizing_multiplier(_model(), state, True) == (1.0, "rl_sizing_malformed_model")


def test_the_shadow_guard_reads_its_config_and_its_history():
    assert resolve_rl_shadow_guard({"window_bars": "many"}) == {"enabled": False, "window_bars": 60, "tolerance_nav_fraction": 0.002}
    assert rl_excess_return({"A": ("x", 1.0), "B": (0.1, 2.0), "C": (0.1, float("nan")), "D": (0.1, 0.0)}, {"A": 0.01, "B": 0.02, "C": 0.01, "D": 0.01}) == 0.1 * 0.5 * 0.02
    assert rl_shadow_guard_allows([-0.01, float("nan")], {"enabled": False}) is True
    assert rl_shadow_guard_allows([-0.01, float("nan")], {"enabled": True, "window_bars": 5, "tolerance_nav_fraction": 0.002}) is False
    assert math.isfinite(rl_excess_return({}, {}))


def test_a_pair_is_unlisted_before_listing_and_from_delisting():
    entry = {"X": {"listed": "2021-01-01", "delisted": "2024-01-01", "suspended": [["2022-01-01", "2022-02-01"]]}}
    assert asset_listed_on_venue("X", "2020-12-31", entry) is False and asset_listed_on_venue("X", "2024-01-01", entry) is False
    assert asset_listed_on_venue("X", "2022-01-15", entry) is False and asset_listed_on_venue("X", "2023-01-01", entry) is True
    assert asset_listed_on_venue("Y", "2023-01-01", entry) is True


def test_drawdown_lock_names_which_limit_and_the_cap_passes_a_small_target():
    from risk_controls import assess_drawdown_lock, cap_target_weight

    assert assess_drawdown_lock(-0.01, -0.2, 0.05, 0.15) == (True, "total_drawdown_limit_breached")
    assert assess_drawdown_lock(-0.06, -0.01, 0.05, 0.15) == (True, "daily_drawdown_limit_breached")
    assert assess_drawdown_lock(0.0, 0.0, 0.05, 0.15) == (False, None)
    assert cap_target_weight(float("nan"), 0.1, 1.0) == (0.0, True) and cap_target_weight(0.2, 0.1, 1.0) == (0.2, False)


def test_forex_cap_clips_to_the_book_weight_and_refuses_non_finite():
    assert cap_forex_target_to_book_weight(float("nan"), 0.1) == 0.0 and cap_forex_target_to_book_weight(0.2, float("inf")) == 0.0
    assert cap_forex_target_to_book_weight(0.05, 0.1) == 0.05 and cap_forex_target_to_book_weight(0.3, -0.1) == 0.1 and cap_forex_target_to_book_weight(-0.3, 0.1) == -0.1


def test_cost_sizing_scales_down_by_the_net_edge_and_a_non_finite_base_sizes_to_nothing():
    from risk.position_sizing import build_dynamic_position_sizing, cost_sizing_multiplier

    assert cost_sizing_multiplier(10.0, 4.0, True) == (0.6, "net_edge_scaled_sizing")
    assert cost_sizing_multiplier(10.0, 40.0, True)[0] == 0.25 and cost_sizing_multiplier(0.0, 1.0, True)[1] == "cost_sizing_disabled_or_absent"
    decision = build_dynamic_position_sizing(float("nan"), 0.8, 0.02, 0.12)
    assert decision.target_weight == 0.0 and decision.to_dict()["sizing_reason"]


def test_rl_state_takes_extra_state_and_a_non_finite_score_is_a_no_op():
    from risk.rl_sizing import build_rl_sizing_state

    base = {key: 0.0 for key in RL_SIZING_STATE_KEYS if key != "confidence"}
    extra_key = next(key for key in RL_SIZING_STATE_KEYS if key != "confidence")
    state = build_rl_sizing_state(base, confidence=0.5, extra_state={extra_key: 3.0})
    assert state[extra_key] == 3.0
    n = len(RL_SIZING_STATE_KEYS)
    model = {"state_keys": list(RL_SIZING_STATE_KEYS), "actions": [0.6, 1.0], "weights": [[0.0] * n, [0.0] * n], "bias": [float("nan"), 1.0], "mean": [0.0] * n, "scale": [1.0] * n}
    assert rl_sizing_multiplier(model, state, True) == (1.0, "rl_sizing_non_finite_score")
    assert resolve_rl_shadow_guard({"window_bars": None})["window_bars"] == 60


def test_the_listing_file_is_read_leniently(tmp_path):
    import json

    from risk.asset_class_router import load_venue_listing_dates

    path = tmp_path / "listing.json"
    path.write_text(json.dumps({"assets": {"BTCUSD": {"listed": "2015-01-01"}, "BAD": 3}}), encoding="utf-8")
    assert load_venue_listing_dates(path) == {"BTCUSD": {"listed": "2015-01-01"}}
    path.write_text(json.dumps({"ETHUSD": {"listed": "2016-05-01"}}), encoding="utf-8")
    assert load_venue_listing_dates(path) == {"ETHUSD": {"listed": "2016-05-01"}}
    path.write_text("{torn", encoding="utf-8")
    assert load_venue_listing_dates(path) == {} and load_venue_listing_dates(tmp_path / "none.json") == {}


def test_a_strategy_that_sizes_nothing_is_skipped_and_the_next_one_tried(monkeypatch):
    import risk.asset_class_router as router

    monkeypatch.setattr(router, "build_options_position_sizing", lambda **kwargs: None)
    monkeypatch.setattr(router, "build_multi_leg_position_sizing", lambda *args, **kwargs: None)
    monkeypatch.setattr(router, "order_enabled_strategies", lambda names, preference: list(names))
    monkeypatch.setattr(router, "strategies_for_volatility_view", lambda view: ["bull_call_spread"])
    spec = type("Spec", (), {"risk_tier": "vega_budget", "shape_family": "vertical"})()
    monkeypatch.setattr(router, "MULTI_LEG_STRATEGY_REGISTRY", {"bull_call_spread": spec})
    result = router.route_multi_leg_option_sizing(
        ["single_leg", "bull_call_spread"], "buy", 0.8, [{"strike": 1}], 100000.0, 100.0, "neutral", "balanced", False, target_delta_at_full_confidence=0.3,
        max_vega_budget_pct_of_equity=0.02, short_leg_delta_offset=0.1, contract_multiplier=100.0, target_margin_utilization=0.1, max_margin_utilization=0.3,
        pct_of_underlying_value=0.2, min_pct_of_underlying_value=0.1,
    )
    assert result is None


def test_a_valid_shadow_guard_config_is_read_and_a_bad_tolerance_falls_back():
    assert resolve_rl_shadow_guard({"enabled": True, "window_bars": 10, "tolerance_nav_fraction": 0.01}) == {"enabled": True, "window_bars": 10, "tolerance_nav_fraction": 0.01}
    assert resolve_rl_shadow_guard({"window_bars": 5, "tolerance_nav_fraction": "x"})["window_bars"] == 60
