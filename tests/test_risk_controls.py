from risk_controls import (
    active_position_limit_reached,
    assess_drawdown_lock,
    cap_target_weight,
    is_backtest_safety_bypass_active,
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
