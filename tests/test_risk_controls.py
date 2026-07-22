from risk_controls import (
    active_position_limit_reached,
    assess_drawdown_lock,
    cap_target_weight,
    compute_incremental_order_quantity,
    is_backtest_safety_bypass_active,
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
