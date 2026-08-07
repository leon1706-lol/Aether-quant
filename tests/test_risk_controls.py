from risk_controls import (
    active_position_limit_reached,
    assess_drawdown_lock,
    cap_target_weight,
    compute_held_weight,
    compute_incremental_order_quantity,
    compute_position_exit_tracking_update,
    evaluate_non_model_exit,
    is_backtest_safety_bypass_active,
    is_position_resize_permitted,
    should_scale_position,
)


def test_total_drawdown_has_priority_over_daily_drawdown():
    locked, reason = assess_drawdown_lock(
        daily_drawdown=-0.05,
        total_drawdown=-0.13,
        max_daily_drawdown_pct=0.03,
        max_total_drawdown_pct=0.12,
    )

    assert locked is True
    assert reason == "total_drawdown_limit_breached"


def test_daily_drawdown_locks_when_total_drawdown_is_ok():
    locked, reason = assess_drawdown_lock(
        daily_drawdown=-0.04,
        total_drawdown=-0.02,
        max_daily_drawdown_pct=0.03,
        max_total_drawdown_pct=0.12,
    )

    assert locked is True
    assert reason == "daily_drawdown_limit_breached"


def test_active_position_limit_allows_existing_position_updates():
    assert active_position_limit_reached(5, 5, is_currently_invested=False) is True
    assert active_position_limit_reached(5, 5, is_currently_invested=True) is False


def test_cap_target_weight_reduces_weight_to_remaining_exposure():
    adjusted_weight, cap_reached = cap_target_weight(
        target_weight=0.20,
        current_exposure=0.55,
        exposure_cap=0.65,
    )

    assert round(adjusted_weight, 6) == 0.10
    assert cap_reached is False


def test_cap_target_weight_blocks_when_no_exposure_remains():
    adjusted_weight, cap_reached = cap_target_weight(
        target_weight=0.20,
        current_exposure=0.65,
        exposure_cap=0.65,
    )

    assert adjusted_weight == 0.0
    assert cap_reached is True


def test_backtest_safety_bypass_requires_both_backtest_mode_and_flag():
    assert is_backtest_safety_bypass_active("backtest", True) is True


def test_backtest_safety_bypass_off_by_default_even_in_backtest():
    assert is_backtest_safety_bypass_active("backtest", False) is False


def test_backtest_safety_bypass_never_active_in_paper_mode():
    assert is_backtest_safety_bypass_active("paper", True) is False
    assert is_backtest_safety_bypass_active("paper", False) is False


def test_backtest_safety_bypass_never_active_in_live_mode():
    assert is_backtest_safety_bypass_active("live", True) is False
    assert is_backtest_safety_bypass_active("live", False) is False


# ---------------------------------------------------------------------------
# V4.3.0 - allow adding to an existing position (development/Changelog.md).
# should_scale_position() is the equity/crypto/bond churn guard (weight
# threshold); compute_incremental_order_quantity() is the discrete-contract
# (futures/options/spreads) delta primitive that converts an ABSOLUTE
# sizing target into the signed quantity an incremental order (MarketOrder/
# Buy) must submit.
# ---------------------------------------------------------------------------


def test_should_scale_position_true_when_delta_meets_threshold():
    assert should_scale_position(current_weight=0.10, target_weight=0.14, rebalance_threshold_weight=0.03) is True


def test_should_scale_position_false_when_delta_below_threshold():
    assert should_scale_position(current_weight=0.10, target_weight=0.115, rebalance_threshold_weight=0.03) is False


def test_should_scale_position_treats_threshold_as_inclusive_boundary():
    assert should_scale_position(current_weight=0.10, target_weight=0.13, rebalance_threshold_weight=0.03) is True


def test_should_scale_position_handles_negative_target_weight_for_shorts():
    # Both weights negative (an open short growing more negative) - abs()
    # must measure the magnitude of the move, not be confused by sign.
    assert should_scale_position(current_weight=-0.10, target_weight=-0.14, rebalance_threshold_weight=0.03) is True


# ---------------------------------------------------------------------------
# compute_held_weight() - the shared current_weight formula
# ---------------------------------------------------------------------------


def test_compute_held_weight_flat_is_zero():
    assert compute_held_weight(holdings_value=0.0, total_portfolio_value=100_000.0) == 0.0


def test_compute_held_weight_long_position():
    assert compute_held_weight(holdings_value=12_000.0, total_portfolio_value=100_000.0) == 0.12


def test_compute_held_weight_short_position_is_negative():
    assert compute_held_weight(holdings_value=-12_000.0, total_portfolio_value=100_000.0) == -0.12


def test_compute_held_weight_floors_total_portfolio_value_at_one():
    # Never divide by zero/negative - degrades to a floor of 1.0.
    assert compute_held_weight(holdings_value=5.0, total_portfolio_value=0.0) == 5.0


# ---------------------------------------------------------------------------
# is_position_resize_permitted() - V5.2.1 (development/Problems.md): gates
# a book member's SIZE to rebalance bars only, leaves every non-book
# symbol (or every symbol when the book is disabled) untouched.
# ---------------------------------------------------------------------------


def test_resize_permitted_for_non_book_symbol_on_any_bar():
    assert is_position_resize_permitted(
        position_scaling_enabled=True, is_book_selected=False, is_rebalance_bar=False
    ) is True


def test_resize_permitted_for_book_symbol_on_rebalance_bar():
    assert is_position_resize_permitted(
        position_scaling_enabled=True, is_book_selected=True, is_rebalance_bar=True
    ) is True


def test_resize_blocked_for_book_symbol_off_rebalance_bar():
    assert is_position_resize_permitted(
        position_scaling_enabled=True, is_book_selected=True, is_rebalance_bar=False
    ) is False


def test_resize_blocked_when_position_scaling_disabled_regardless_of_book_membership():
    assert is_position_resize_permitted(
        position_scaling_enabled=False, is_book_selected=False, is_rebalance_bar=True
    ) is False
    assert is_position_resize_permitted(
        position_scaling_enabled=False, is_book_selected=True, is_rebalance_bar=True
    ) is False


def test_resize_permitted_matrix_matches_book_gating_contract():
    # Exhaustive 2x2x2 - the full contract in one table, so a future
    # regression to any single combination is caught immediately.
    expected = {
        (True, False, False): True,
        (True, False, True): True,
        (True, True, False): False,
        (True, True, True): True,
        (False, False, False): False,
        (False, False, True): False,
        (False, True, False): False,
        (False, True, True): False,
    }
    for (scaling_enabled, book_selected, rebalance_bar), outcome in expected.items():
        assert is_position_resize_permitted(scaling_enabled, book_selected, rebalance_bar) is outcome
    assert should_scale_position(current_weight=-0.10, target_weight=-0.115, rebalance_threshold_weight=0.03) is False


def test_compute_incremental_order_quantity_positive_delta_when_target_exceeds_current():
    assert compute_incremental_order_quantity(target_quantity=10, current_quantity=6) == 4


def test_compute_incremental_order_quantity_negative_delta_when_target_below_current():
    assert compute_incremental_order_quantity(target_quantity=6, current_quantity=10) == -4


def test_compute_incremental_order_quantity_zero_when_already_at_target():
    assert compute_incremental_order_quantity(target_quantity=10, current_quantity=10) == 0


def test_compute_incremental_order_quantity_handles_negative_current_and_target_quantities():
    # A short futures position growing more negative (target -8 from -5) -
    # the delta itself must be signed correctly for MarketOrder(delta) to
    # sell 3 more, not buy back toward flat.
    assert compute_incremental_order_quantity(target_quantity=-8, current_quantity=-5) == -3


# ---------------------------------------------------------------------------
# V4.10 - pure extraction of main.py::_check_non_model_exit()/
# _update_position_exit_tracking() (development/Problems.md #66). Backstop
# exits independent of the model's own signal: max holding age, then a
# direction-aware trailing stop from the best price since entry.
# ---------------------------------------------------------------------------


def test_evaluate_non_model_exit_returns_none_when_exits_disabled():
    # exits_enabled=False must restore pre-fix behavior byte-for-byte, even
    # with a stale entry well past both thresholds.
    assert (
        evaluate_non_model_exit(
            bar_index=100,
            exits_enabled=False,
            exits_max_holding_bars=5,
            exits_trailing_stop_pct=0.05,
            entry_bar_index=0,
            peak_price_since_entry=100.0,
            direction="long",
            close_price=50.0,
        )
        is None
    )


def test_evaluate_non_model_exit_returns_none_when_no_entry_recorded():
    assert (
        evaluate_non_model_exit(
            bar_index=10,
            exits_enabled=True,
            exits_max_holding_bars=5,
            exits_trailing_stop_pct=0.05,
            entry_bar_index=None,
            peak_price_since_entry=None,
            direction="long",
            close_price=50.0,
        )
        is None
    )


def test_evaluate_non_model_exit_max_holding_age_fires_at_exact_threshold():
    result = evaluate_non_model_exit(
        bar_index=10,
        exits_enabled=True,
        exits_max_holding_bars=5,
        exits_trailing_stop_pct=0.50,  # generous, never fires on its own here
        entry_bar_index=5,
        peak_price_since_entry=100.0,
        direction="long",
        close_price=100.0,
    )
    assert result == "max_holding_age_exceeded"


def test_evaluate_non_model_exit_max_holding_age_does_not_fire_one_bar_before():
    result = evaluate_non_model_exit(
        bar_index=9,
        exits_enabled=True,
        exits_max_holding_bars=5,
        exits_trailing_stop_pct=0.50,
        entry_bar_index=5,
        peak_price_since_entry=100.0,
        direction="long",
        close_price=100.0,
    )
    assert result is None


def test_evaluate_non_model_exit_max_holding_age_takes_priority_over_trailing_stop():
    # Both conditions true simultaneously - first-match-wins order means
    # max_holding_age_exceeded must win, not trailing_stop_triggered.
    result = evaluate_non_model_exit(
        bar_index=10,
        exits_enabled=True,
        exits_max_holding_bars=5,
        exits_trailing_stop_pct=0.05,
        entry_bar_index=5,
        peak_price_since_entry=100.0,
        direction="long",
        close_price=50.0,  # 50% drawdown, well past the 5% trailing stop too
    )
    assert result == "max_holding_age_exceeded"


def test_evaluate_non_model_exit_trailing_stop_fires_for_long_on_drawdown_from_peak():
    result = evaluate_non_model_exit(
        bar_index=10,
        exits_enabled=True,
        exits_max_holding_bars=1000,
        exits_trailing_stop_pct=0.05,
        entry_bar_index=5,
        peak_price_since_entry=100.0,
        direction="long",
        close_price=94.0,  # 6% drawdown from peak >= 5% threshold
    )
    assert result == "trailing_stop_triggered"


def test_evaluate_non_model_exit_trailing_stop_does_not_fire_below_threshold():
    result = evaluate_non_model_exit(
        bar_index=10,
        exits_enabled=True,
        exits_max_holding_bars=1000,
        exits_trailing_stop_pct=0.05,
        entry_bar_index=5,
        peak_price_since_entry=100.0,
        direction="long",
        close_price=96.0,  # 4% drawdown, below the 5% threshold
    )
    assert result is None


def test_evaluate_non_model_exit_trailing_stop_fires_for_short_on_rally_from_trough():
    # Direction-aware inverse math: for a short, "best" is the LOWEST close
    # since entry, and the stop measures a rally back UP from that trough.
    result = evaluate_non_model_exit(
        bar_index=10,
        exits_enabled=True,
        exits_max_holding_bars=1000,
        exits_trailing_stop_pct=0.05,
        entry_bar_index=5,
        peak_price_since_entry=100.0,  # the trough price for a short
        direction="short",
        close_price=106.0,  # 6% rally from the trough >= 5% threshold
    )
    assert result == "trailing_stop_triggered"


def test_evaluate_non_model_exit_trailing_stop_ignores_none_or_nonpositive_peak_price():
    common_kwargs = dict(
        bar_index=10, exits_enabled=True, exits_max_holding_bars=1000,
        exits_trailing_stop_pct=0.05, entry_bar_index=5, direction="long", close_price=50.0,
    )
    assert evaluate_non_model_exit(peak_price_since_entry=None, **common_kwargs) is None
    assert evaluate_non_model_exit(peak_price_since_entry=0.0, **common_kwargs) is None


def test_tracking_update_enter_sets_all_four_fields_for_long():
    update = compute_position_exit_tracking_update(
        was_invested=False,
        is_invested=True,
        close_price=100.0,
        signal_name="buy",
        peak_price_since_entry=None,
        direction=None,
        bar_index=7,
    )
    assert update == {
        "action": "enter",
        "entry_bar_index": 7,
        "entry_price": 100.0,
        "peak_price_since_entry": 100.0,
        "direction": "long",
    }


def test_tracking_update_enter_resolves_short_direction_from_signal_name():
    update = compute_position_exit_tracking_update(
        was_invested=False,
        is_invested=True,
        close_price=100.0,
        signal_name="short",
        peak_price_since_entry=None,
        direction=None,
        bar_index=7,
    )
    assert update["direction"] == "short"


def test_tracking_update_hold_tracks_max_peak_for_long():
    update = compute_position_exit_tracking_update(
        was_invested=True,
        is_invested=True,
        close_price=105.0,
        signal_name="buy",
        peak_price_since_entry=100.0,
        direction="long",
        bar_index=8,
    )
    assert update == {"action": "hold", "peak_price_since_entry": 105.0}
    # A lower close than the recorded peak must not lower the peak.
    update_lower = compute_position_exit_tracking_update(
        was_invested=True,
        is_invested=True,
        close_price=95.0,
        signal_name="buy",
        peak_price_since_entry=100.0,
        direction="long",
        bar_index=9,
    )
    assert update_lower == {"action": "hold", "peak_price_since_entry": 100.0}


def test_tracking_update_hold_tracks_min_trough_for_short():
    update = compute_position_exit_tracking_update(
        was_invested=True,
        is_invested=True,
        close_price=95.0,
        signal_name="short",
        peak_price_since_entry=100.0,
        direction="short",
        bar_index=8,
    )
    assert update == {"action": "hold", "peak_price_since_entry": 95.0}
    # A higher close than the recorded trough must not raise the trough.
    update_higher = compute_position_exit_tracking_update(
        was_invested=True,
        is_invested=True,
        close_price=105.0,
        signal_name="short",
        peak_price_since_entry=95.0,
        direction="short",
        bar_index=9,
    )
    assert update_higher == {"action": "hold", "peak_price_since_entry": 95.0}


def test_tracking_update_hold_result_carries_no_entry_bar_or_price_keys():
    # A "hold" update must never overwrite entry_bar_index/entry_price -
    # they're simply absent from the returned dict, by design.
    update = compute_position_exit_tracking_update(
        was_invested=True,
        is_invested=True,
        close_price=105.0,
        signal_name="buy",
        peak_price_since_entry=100.0,
        direction="long",
        bar_index=8,
    )
    assert "entry_bar_index" not in update
    assert "entry_price" not in update


def test_tracking_update_clear_on_exit():
    update = compute_position_exit_tracking_update(
        was_invested=True,
        is_invested=False,
        close_price=90.0,
        signal_name="sell",
        peak_price_since_entry=100.0,
        direction="long",
        bar_index=12,
    )
    assert update == {"action": "clear"}


def test_tracking_update_noop_when_never_invested():
    update = compute_position_exit_tracking_update(
        was_invested=False,
        is_invested=False,
        close_price=90.0,
        signal_name="hold",
        peak_price_since_entry=None,
        direction=None,
        bar_index=12,
    )
    assert update == {"action": "noop"}
