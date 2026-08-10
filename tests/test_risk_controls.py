import pytest

from risk_controls import (
    active_position_limit_reached,
    assess_drawdown_lock,
    build_forex_order_sizing_record,
    cap_target_weight,
    compute_forex_order_units,
    compute_held_weight,
    compute_incremental_order_quantity,
    compute_position_exit_tracking_update,
    evaluate_non_model_exit,
    is_backtest_safety_bypass_active,
    is_position_resize_permitted,
    is_regime_drawdown_bypass_active,
    is_sticky_trade_lock_bypass_active,
    should_lock_in_duration_beta,
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
# V5.2.7 (development/Problems.md) - is_sticky_trade_lock_bypass_active()/
# is_regime_drawdown_bypass_active() split the legacy combined
# bypass_safety_gates flag into two independently-configurable ones. A real
# backtest showed a single kill-switch trip lock 336/336 (100%) of
# book-member decisions for the remaining 13 months of a 2.2-year backtest -
# these let that sticky-lock clearing be enabled WITHOUT also disabling the
# unrelated regime risk_off drawdown protection, which the old single flag
# forced as a bundled side effect.
# ---------------------------------------------------------------------------


def test_sticky_trade_lock_bypass_active_via_new_flag_in_backtest():
    assert is_sticky_trade_lock_bypass_active("backtest", True, False) is True


def test_sticky_trade_lock_bypass_active_via_legacy_flag_in_backtest():
    # Backward compatibility - anyone with the old bypass_safety_gates=true
    # config must keep getting the sticky-lock-clear behavior unchanged.
    assert is_sticky_trade_lock_bypass_active("backtest", False, True) is True


def test_sticky_trade_lock_bypass_inactive_when_neither_flag_set():
    assert is_sticky_trade_lock_bypass_active("backtest", False, False) is False


def test_sticky_trade_lock_bypass_never_active_outside_backtest():
    assert is_sticky_trade_lock_bypass_active("paper", True, True) is False
    assert is_sticky_trade_lock_bypass_active("live", True, True) is False


def test_regime_drawdown_bypass_active_via_new_flag_in_backtest():
    assert is_regime_drawdown_bypass_active("backtest", True, False) is True


def test_regime_drawdown_bypass_active_via_legacy_flag_in_backtest():
    assert is_regime_drawdown_bypass_active("backtest", False, True) is True


def test_regime_drawdown_bypass_inactive_when_neither_flag_set():
    assert is_regime_drawdown_bypass_active("backtest", False, False) is False


def test_regime_drawdown_bypass_never_active_outside_backtest():
    assert is_regime_drawdown_bypass_active("paper", True, True) is False
    assert is_regime_drawdown_bypass_active("live", True, True) is False


def test_sticky_bypass_and_regime_bypass_are_independent():
    # The actual bug-closing test: setting ONLY the sticky-lock flag must
    # never also activate the regime-drawdown bypass, and vice versa - this
    # is the entire point of splitting the two apart.
    assert is_sticky_trade_lock_bypass_active("backtest", True, False) is True
    assert is_regime_drawdown_bypass_active("backtest", False, False) is False

    assert is_sticky_trade_lock_bypass_active("backtest", False, False) is False
    assert is_regime_drawdown_bypass_active("backtest", True, False) is True


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


# ---------------------------------------------------------------------------
# should_lock_in_duration_beta() - V5.2.5 (development/Problems.md #91-
# continuation): whether enough history has accumulated to compute
# bond_empirical_duration_beta ONCE and cache it, matching train.py's own
# offline "compute once per ticker, broadcast unchanged" semantic instead
# of re-rolling a fresh, drifting estimate every bar.
# ---------------------------------------------------------------------------


def test_should_lock_in_duration_beta_false_when_both_windows_still_filling():
    assert should_lock_in_duration_beta(window_length=50, treasury_window_length=50, target_window_length=260) is False


def test_should_lock_in_duration_beta_false_when_only_price_window_is_full():
    # AND, not OR - one window clearing the bar isn't enough.
    assert should_lock_in_duration_beta(window_length=260, treasury_window_length=50, target_window_length=260) is False


def test_should_lock_in_duration_beta_false_when_only_treasury_window_is_full():
    assert should_lock_in_duration_beta(window_length=50, treasury_window_length=260, target_window_length=260) is False


def test_should_lock_in_duration_beta_true_at_exactly_the_target_boundary():
    assert should_lock_in_duration_beta(window_length=260, treasury_window_length=260, target_window_length=260) is True


def test_should_lock_in_duration_beta_true_when_both_windows_exceed_the_target():
    assert should_lock_in_duration_beta(window_length=300, treasury_window_length=300, target_window_length=260) is True


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
# V5.2.7 (development/Problems.md) - compute_forex_order_units()/
# build_forex_order_sizing_record(). Confirmed bug: main.py used to divide
# notional by (lot_size * close_price) - a full 100,000-unit standard lot -
# which on a $100k account with a realistic book-member position weight
# (4-12%) always rounded to 0, silently discarding every forex trade that
# had already cleared every other risk/liquidity/confidence gate.
# ---------------------------------------------------------------------------


def test_compute_forex_order_units_realistic_book_member_scale_is_nonzero():
    # The literal confirmed-bug scenario: an 8% EURUSD-like position on a
    # $100k account. Pre-fix, this rounded to 0 lots every time.
    units = compute_forex_order_units(target_weight=0.08, close_price=1.10, portfolio_value=100_000.0)
    assert units > 0
    assert units == 7273


def test_compute_forex_order_units_does_not_round_to_lot_multiple():
    # Explicit regression guard against reintroducing the original bug
    # under a new name - a "round to nearest whole lot_size (100,000)
    # multiple" fix would look plausible but leaves every realistic
    # position rounding to zero.
    units = compute_forex_order_units(target_weight=0.08, close_price=1.10, portfolio_value=100_000.0)
    assert units % 100_000 != 0
    assert units != 0


def test_compute_forex_order_units_scales_with_weight():
    small = compute_forex_order_units(target_weight=0.04, close_price=1.10, portfolio_value=100_000.0)
    large = compute_forex_order_units(target_weight=0.08, close_price=1.10, portfolio_value=100_000.0)
    assert large == pytest.approx(2 * small, abs=1)


def test_compute_forex_order_units_negative_weight_gives_negative_units():
    units = compute_forex_order_units(target_weight=-0.08, close_price=1.10, portfolio_value=100_000.0)
    assert units < 0


def test_compute_forex_order_units_zero_close_price_gives_zero():
    assert compute_forex_order_units(target_weight=0.08, close_price=0.0, portfolio_value=100_000.0) == 0


def test_compute_forex_order_units_non_positive_portfolio_value_gives_zero():
    assert compute_forex_order_units(target_weight=0.08, close_price=1.10, portfolio_value=0.0) == 0
    assert compute_forex_order_units(target_weight=0.08, close_price=1.10, portfolio_value=-100.0) == 0


def test_build_forex_order_sizing_record_notional_ratio_near_one_for_sane_inputs():
    units = compute_forex_order_units(target_weight=0.08, close_price=1.10, portfolio_value=100_000.0)
    record = build_forex_order_sizing_record(
        "2019-01-08", "EURUSD", "short", 0.08, 100_000.0, 1.10, units
    )
    assert record["notional_ratio"] == pytest.approx(1.0, abs=0.01)


def test_build_forex_order_sizing_record_flags_gross_mismatch():
    # Feed it the OLD, buggy lot-based output (0, since every realistic
    # weight rounded to 0 lots) against a real intended notional - the
    # ratio must come back unambiguously wrong (0.0), not silently near 1.0.
    record = build_forex_order_sizing_record(
        "2019-01-08", "EURUSD", "short", 0.08, 100_000.0, 1.10, 0
    )
    assert record["notional_ratio"] == pytest.approx(0.0, abs=1e-9)


def test_build_forex_order_sizing_record_handles_zero_intended_notional():
    record = build_forex_order_sizing_record(
        "2019-01-08", "EURUSD", "short", 0.0, 100_000.0, 1.10, 0
    )
    assert record["notional_ratio"] is None


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
