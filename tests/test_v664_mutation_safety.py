"""Boundary tests that kill the mutants `scripts/mutation_check.py` left alive in the kill switch (V6.6.4, Problems #341).

The mutation run changed one comparison, operator or constant at a time; these thresholds were only ever tested well away from their edge, so `>` for `>=` went unnoticed.
Every trigger now has a test at its exact threshold (not tripped) and just past it (tripped).
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from risk.kill_switch import KillSwitchDecision, _rolling_sharpe, evaluate_kill_switch

BASE = {"enabled": True, "evaluation_bars": 3, "min_bars_for_sharpe": 3}


def _decide(metrics: dict, **config) -> KillSwitchDecision:
    return evaluate_kill_switch(metrics, {**BASE, **config})


CAPS = [
    # metric key, config key, threshold, trigger, direction ("above" trips when the metric is greater, "below" when it is lower)
    ("drawdown_velocity_pct_per_bar", "max_drawdown_velocity_pct_per_bar", 0.5, "drawdown_velocity_above_cap", "above"),
    ("live_rank_ic", "min_live_rank_ic", 0.02, "live_rank_ic_below_floor", "below"),
    ("consecutive_losses", "max_consecutive_losses", 5, "consecutive_losses_above_cap", "above"),
    ("slippage_divergence_bps", "max_slippage_divergence_bps", 25.0, "slippage_divergence_above_cap", "above"),
    ("model_age_days", "max_model_age_days", 30, "model_age_above_cap", "above"),
]


@pytest.mark.parametrize("metric,key,threshold,trigger,direction", CAPS)
def test_a_cap_trips_only_strictly_past_its_threshold(metric, key, threshold, trigger, direction):
    step = 1 if isinstance(threshold, int) else 0.001
    beyond = threshold + step if direction == "above" else threshold - step
    assert not _decide({metric: threshold}, **{key: threshold}).tripped, "exactly at the threshold is allowed"
    tripped = _decide({metric: beyond}, **{key: threshold})
    assert tripped.tripped and tripped.triggers == [trigger] and tripped.severity == "warning"
    assert tripped.recommended_action == "trade_lock" and trigger in tripped.reason


@pytest.mark.parametrize("metric,key,threshold,trigger,direction", CAPS)
def test_a_missing_or_non_finite_reading_never_trips_its_cap(metric, key, threshold, trigger, direction):
    for value in (None, float("nan"), float("inf")):
        decision = _decide({metric: value}, **{key: threshold})
        # an infinite reading is not a reading: it is treated as absent, like None
        assert not decision.tripped, (metric, value)


def test_two_triggers_are_critical_and_a_reconciliation_breach_is_recorded():
    decision = _decide({"model_age_days": 99, "consecutive_losses": 9, "reconciliation_breach": True}, max_model_age_days=30, max_consecutive_losses=5)
    assert decision.severity == "critical" and len(decision.triggers) == 3 and decision.observed["reconciliation_breach"] is True
    clean = _decide({"reconciliation_breach": False})
    assert not clean.tripped and "reconciliation_breach" not in clean.observed


def test_the_decision_is_immutable():
    decision = _decide({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.tripped = True  # type: ignore[misc]


def test_rolling_sharpe_uses_the_sample_variance_and_the_252_day_year_by_default():
    returns = [0.01, 0.03]
    mean, std = 0.02, math.sqrt(((0.01 - 0.02) ** 2 + (0.03 - 0.02) ** 2) / 1)
    assert _rolling_sharpe(returns) == pytest.approx(mean / std * math.sqrt(252))
    assert _rolling_sharpe(returns, trading_days_per_year=365) == pytest.approx(mean / std * math.sqrt(365))
    assert _rolling_sharpe([0.01]) is None and _rolling_sharpe([]) is None, "fewer than two readings is not a Sharpe"
    assert _rolling_sharpe(returns) is not None, "two readings are enough"


def test_a_std_at_or_below_the_floor_reads_as_zero_not_as_an_extreme_sharpe():
    returns = [0.0, 0.002, 0.0, 0.002]
    mean = sum(returns) / 4
    std = math.sqrt(sum((v - mean) ** 2 for v in returns) / 3)
    assert _rolling_sharpe(returns, min_return_std_floor=std) == 0.0, "equal to the floor counts as below it"
    assert _rolling_sharpe(returns, min_return_std_floor=std * 0.999) == pytest.approx(mean / std * math.sqrt(252))
    assert _rolling_sharpe(returns, min_return_std_floor=-1.0) == pytest.approx(mean / std * math.sqrt(252)), "a negative floor never widens the guard"
    assert _rolling_sharpe([0.001, 0.001, 0.001]) == 0.0


def test_the_default_window_is_sixty_bars_and_the_sharpe_waits_for_all_of_them():
    returns = [(-1) ** i * 0.01 + 0.001 for i in range(60)]
    config = {"enabled": True, "min_rolling_sharpe": 1e6}  # no window keys: the defaults decide
    short = evaluate_kill_switch({"recent_bar_returns": returns[:59]}, config)
    assert short.observed["rolling_sharpe"] is None and not short.tripped
    full = evaluate_kill_switch({"recent_bar_returns": returns}, config)
    assert full.observed["rolling_sharpe"] is not None and full.tripped and full.triggers == ["rolling_sharpe_below_floor"]
    assert full.thresholds["evaluation_bars"] == 60 and full.thresholds["min_bars_for_sharpe"] == 60


def test_the_release_band_only_holds_a_trip_that_was_latched_last_bar():
    returns = [0.02, -0.01, 0.03]  # a Sharpe well above the floor but below the release level
    floor, release = -1.0, 1e9
    free = evaluate_kill_switch({"recent_bar_returns": returns}, {**BASE, "min_rolling_sharpe": floor, "release_rolling_sharpe": release})
    assert not free.tripped, "nothing latched, so the band holds nothing (absent key reads as False)"
    held = evaluate_kill_switch({"recent_bar_returns": returns, "rolling_sharpe_tripped_last_bar": True}, {**BASE, "min_rolling_sharpe": floor, "release_rolling_sharpe": release})
    assert held.tripped and held.rolling_sharpe_tripped
    above = evaluate_kill_switch({"recent_bar_returns": returns, "rolling_sharpe_tripped_last_bar": True}, {**BASE, "min_rolling_sharpe": floor, "release_rolling_sharpe": -1e9})
    assert not above.tripped, "a Sharpe at or above the release level lets go"


# --- execution/order_gate.py -------------------------------------------------------------------------------------------------------------------

from datetime import datetime, timedelta  # noqa: E402

from execution.order_gate import (  # noqa: E402
    compute_fill_slippage_divergence_bps,
    resolve_combo_limit_price,
    resolve_pending_order_action,
    should_skip_for_open_order,
    slippage_amount,
    slippage_reference_price,
)


def test_slippage_amount_is_zero_at_zero_bps_and_exact_above_it():
    assert slippage_amount(100.0, 0.0) == 0.0 and slippage_amount(100.0, -5.0) == 0.0
    assert slippage_amount(100.0, 1.0) == pytest.approx(0.01)
    assert slippage_amount(0.0, 10.0) == 0.0 and slippage_amount(float("nan"), 10.0) == 0.0 and slippage_amount(100.0, float("nan")) == 0.0


def test_combo_limit_price_rounds_to_cents_and_pays_up_on_a_buy_gives_up_on_a_sell():
    assert resolve_combo_limit_price(1.234, 0.0, True) == 1.23, "two decimals, not three"
    assert resolve_combo_limit_price(1.0, 0.1, True) == 1.05 and resolve_combo_limit_price(1.0, 0.1, False) == 0.95
    assert resolve_combo_limit_price(-1.0, 0.1, True) == -0.95 and resolve_combo_limit_price(-1.0, 0.1, False) == -1.05, "a credit's offset keeps its size"


def test_a_pending_order_is_kept_until_its_timeout_and_replaced_at_it():
    pending = {"direction": "buy", "submitted_bar": 10}
    assert resolve_pending_order_action(None, True, 10, 3) == "submit" and resolve_pending_order_action({}, True, 10, 3) == "submit"
    assert resolve_pending_order_action(pending, True, 12, 3) == "keep", "age 2 of 3"
    assert resolve_pending_order_action(pending, True, 13, 3) == "cancel_replace", "age 3 reaches the timeout"
    assert resolve_pending_order_action(pending, True, 9, 3) == "keep", "a bar index behind the submission is not an old order"
    assert resolve_pending_order_action(pending, False, 11, 3) == "cancel_replace", "the other direction"
    assert resolve_pending_order_action(pending, True, 11, 0) == "cancel_replace", "a zero timeout still means one bar"
    assert resolve_pending_order_action(pending, True, 10, 0) == "keep", "and an order submitted this bar is not yet old"
    assert resolve_pending_order_action(pending, True, 11, 1) == "cancel_replace" and resolve_pending_order_action(pending, True, 10, 1) == "keep"
    assert resolve_pending_order_action({"direction": "buy"}, True, 50, 3) == "keep", "no submission bar reads as just submitted"
    assert resolve_pending_order_action({"direction": "buy", "submitted_bar": "x"}, True, 11, 3) == "cancel_replace"


def test_an_untracked_open_order_blocks_a_new_entry_a_tracked_one_does_not():
    assert should_skip_for_open_order(5.0, False) is True and should_skip_for_open_order(-5.0, False) is True
    assert should_skip_for_open_order(5.0, True) is False, "a tracked pending limit is resolve_pending_order_action's to settle"
    assert should_skip_for_open_order(0.0, False) is False
    assert should_skip_for_open_order(float("nan"), False) is False and should_skip_for_open_order(float("inf"), False) is False
    assert should_skip_for_open_order("x", False) is False and should_skip_for_open_order(None, False) is False


def test_fill_slippage_divergence_counts_only_the_adverse_side_and_refuses_unreadable_inputs():
    assert compute_fill_slippage_divergence_bps(101.0, 100.0, 20.0, direction=1.0) == pytest.approx(80.0), "a buy 100 bps above the open, 20 expected"
    assert compute_fill_slippage_divergence_bps(99.0, 100.0, 20.0, direction=1.0) == pytest.approx(-120.0), "price improvement is a negative cost"
    assert compute_fill_slippage_divergence_bps(99.0, 100.0, 20.0, direction=-1.0) == pytest.approx(80.0)
    assert compute_fill_slippage_divergence_bps(99.0, 100.0, 20.0) == pytest.approx(80.0), "without a direction the absolute gap"
    assert compute_fill_slippage_divergence_bps(99.0, 100.0, 20.0, direction=0.0) == pytest.approx(80.0)
    assert compute_fill_slippage_divergence_bps(float("nan"), 100.0, 20.0) is None and compute_fill_slippage_divergence_bps(100.0, float("inf"), 20.0) is None
    assert compute_fill_slippage_divergence_bps(100.0, 100.0, float("nan")) is None, "each input is checked on its own"
    assert compute_fill_slippage_divergence_bps(0.0, 100.0, 20.0) is None and compute_fill_slippage_divergence_bps(100.0, 0.0, 20.0) is None
    assert compute_fill_slippage_divergence_bps(100.0, -1.0, 20.0) is None and compute_fill_slippage_divergence_bps("x", 100.0, 20.0) is None


def test_the_slippage_reference_is_the_submission_price_only_for_a_quick_fill_with_a_usable_price():
    start = datetime(2026, 1, 5, 10, 0, 0)
    quick, edge, slow = start + timedelta(seconds=30), start + timedelta(seconds=3600), start + timedelta(seconds=3601)
    assert slippage_reference_price(100.0, 101.0, start, quick) == (100.0, "submit")
    assert slippage_reference_price(100.0, 101.0, start, edge) == (100.0, "submit"), "exactly the limit still counts as immediate"
    assert slippage_reference_price(100.0, 101.0, start, slow) == (101.0, "fill_bar_open")
    assert slippage_reference_price(100.0, 101.0, start, start) == (100.0, "submit"), "zero seconds is immediate"
    assert slippage_reference_price(100.0, 101.0, quick, start) == (101.0, "fill_bar_open"), "a fill before its submission is not trusted"
    assert slippage_reference_price(100.0, 101.0, None, quick) == (101.0, "fill_bar_open") and slippage_reference_price(100.0, 101.0, start, None) == (101.0, "fill_bar_open")
    assert slippage_reference_price(None, 101.0, start, quick) == (101.0, "fill_bar_open") and slippage_reference_price(0.0, 101.0, start, quick) == (101.0, "fill_bar_open")
    assert slippage_reference_price(float("nan"), 101.0, start, quick) == (101.0, "fill_bar_open")
    assert slippage_reference_price(100.0, None, start, slow) == (None, "fill_bar_open")
    assert slippage_reference_price(100.0, 101.0, "x", quick) == (101.0, "fill_bar_open"), "unreadable timestamps fall back"


# --- risk_controls.py --------------------------------------------------------------------------------------------------------------------------

from risk_controls import (  # noqa: E402
    compute_position_exit_tracking_update,
    evaluate_non_model_exit,
    is_cooldown_exempt,
    projected_signed_quantity,
    resolve_trading_days_per_year,
)


def test_only_a_forced_sell_of_an_open_position_skips_the_cooldown():
    assert is_cooldown_exempt("sell", True, True) is True
    for args in (("sell", True, False), ("sell", False, True), ("buy", True, True), ("short", True, True), ("sell", False, False)):
        assert is_cooldown_exempt(*args) is False, args
    assert is_cooldown_exempt("sell", True) is False, "not forced by default"


def test_the_projected_position_is_held_plus_open_and_unreadable_parts_count_as_zero():
    assert projected_signed_quantity(10.0, 5.0) == 15.0 and projected_signed_quantity(10.0, -15.0) == -5.0
    assert projected_signed_quantity(float("nan"), 5.0) == 5.0 and projected_signed_quantity(10.0, float("inf")) == 10.0 and projected_signed_quantity(10.0, float("-inf")) == 10.0
    assert projected_signed_quantity("x", None) == 0.0


def _exit(**overrides):
    args = dict(bar_index=100, exits_enabled=True, exits_max_holding_bars=50, exits_trailing_stop_pct=0.10, entry_bar_index=60, peak_price_since_entry=100.0, direction="long", close_price=100.0)
    args.update(overrides)
    return evaluate_non_model_exit(**args)


def test_the_trailing_stop_fires_at_the_stop_exactly_not_just_before_it():
    assert _exit(close_price=90.0) == "trailing_stop_triggered", "a drawdown of exactly the stop"
    assert _exit(close_price=90.01) is None
    assert _exit(direction="short", peak_price_since_entry=100.0, close_price=110.0) == "trailing_stop_triggered"
    assert _exit(direction="short", peak_price_since_entry=100.0, close_price=109.99) is None
    assert _exit(peak_price_since_entry=0.0, close_price=1.0) is None and _exit(peak_price_since_entry=None, close_price=1.0) is None
    assert _exit(entry_bar_index=50) == "max_holding_age_exceeded", "age 50 reaches a 50-bar limit"
    assert _exit(entry_bar_index=51) is None, "age 49 does not"


def _tracking(**overrides):
    args = dict(was_invested=True, is_invested=True, close_price=10.0, signal_name="buy", peak_price_since_entry=None, direction="long", bar_index=5, has_entry_state=False,
                held_quantity=None, average_entry_price=None, clear_stale_state=False)
    args.update(overrides)
    return compute_position_exit_tracking_update(**args)


def test_a_position_adopted_without_entry_state_takes_its_direction_from_the_book_and_its_price_from_the_average():
    assert _tracking(held_quantity=-3.0)["direction"] == "short" and _tracking(held_quantity=3.0)["direction"] == "long"
    assert _tracking(held_quantity=0.0, signal_name="short")["direction"] == "short" and _tracking(held_quantity=None, signal_name="buy")["direction"] == "long"
    assert _tracking(held_quantity=3.0, signal_name="short")["direction"] == "long", "the held side beats the signal"
    assert _tracking(average_entry_price=8.0)["entry_price"] == 8.0 and _tracking(average_entry_price=8.0)["peak_price_since_entry"] == 8.0
    for unusable in (0.0, -1.0, float("nan"), None):
        assert _tracking(average_entry_price=unusable)["entry_price"] == 10.0, unusable
    assert _tracking(is_invested=True, was_invested=False, signal_name="short")["direction"] == "short"


def test_the_trading_days_per_year_window_is_inclusive_at_both_ends():
    assert resolve_trading_days_per_year({"trading_days_per_year": 200}) == 200 and resolve_trading_days_per_year({"trading_days_per_year": 366}) == 366
    assert resolve_trading_days_per_year({"trading_days_per_year": 199}) is None and resolve_trading_days_per_year({"trading_days_per_year": 367}) is None
    assert resolve_trading_days_per_year({"trading_days_per_year": 252}) == 252 and resolve_trading_days_per_year({"trading_days_per_year": "x"}) is None
    assert resolve_trading_days_per_year(None) is None and resolve_trading_days_per_year({}) is None
