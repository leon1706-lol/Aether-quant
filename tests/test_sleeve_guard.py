"""portfolio/sleeve_guard.py (V5.8.0): the per-sleeve loss guard."""

from __future__ import annotations

import math

from portfolio.sleeve_guard import (
    SleeveGuardConfig,
    evaluate_sleeve_guard,
    resolve_sleeve_guard_config,
    sleeve_pnl_increment,
    trailing_drawdown,
)


def test_resolve_defaults_to_disabled_and_sanitises_bad_values():
    assert resolve_sleeve_guard_config(None) == SleeveGuardConfig()
    config = resolve_sleeve_guard_config({"enabled": True, "max_loss_fraction_nav": "nan", "lookback_bars": -3, "cooldown_bars": 5})
    assert config.enabled and config.max_loss_fraction_nav == 0.01 and config.lookback_bars == 1 and config.cooldown_bars == 5


def test_trailing_drawdown_measures_peak_to_latest_inside_the_window():
    assert trailing_drawdown([1.0, 2.0, -5.0, 1.0], 10) == 4.0  # peak 3, latest -1
    assert trailing_drawdown([-5.0, 1.0, 1.0], 2) == 0.0  # the loss left the window
    assert trailing_drawdown([float("nan"), -2.0], 5) == 2.0


def test_disabled_guard_never_suspends():
    decision = evaluate_sleeve_guard([-1e9], 100_000.0, SleeveGuardConfig(enabled=False), current_bar=10)
    assert decision["active"] and decision["reason"] == "sleeve_guard_disabled"


def test_breach_suspends_for_the_cooldown_then_resumes_once_healed():
    config = SleeveGuardConfig(enabled=True, max_loss_fraction_nav=0.01, lookback_bars=5, cooldown_bars=3)
    history = [0.0, -600.0, -600.0]  # 1,200 drawdown > 1% of 100k
    first = evaluate_sleeve_guard(history, 100_000.0, config, current_bar=10)
    assert not first["active"] and first["reason"] == "sleeve_guard_loss_limit" and first["suspended_until_bar"] == 13
    held = evaluate_sleeve_guard(history + [0.0], 100_000.0, config, current_bar=12, suspended_until_bar=13)
    assert not held["active"] and held["reason"] == "sleeve_guard_cooldown"
    healed = history + [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # the loss is out of the 5-bar window
    after = evaluate_sleeve_guard(healed, 100_000.0, config, current_bar=13, suspended_until_bar=13)
    assert after["active"] and after["suspended_until_bar"] is None


def test_unhealed_loss_keeps_the_sleeve_off_after_the_cooldown():
    config = SleeveGuardConfig(enabled=True, max_loss_fraction_nav=0.01, lookback_bars=50, cooldown_bars=2)
    decision = evaluate_sleeve_guard([-2000.0, 0.0], 100_000.0, config, current_bar=20, suspended_until_bar=12)
    assert not decision["active"] and decision["suspended_until_bar"] == 22


def test_pnl_increment_is_value_change_minus_cash_put_in():
    assert sleeve_pnl_increment({"A": 1000.0}, {"A": 1100.0, "B": 500.0}, {"B": 510.0}) == 100.0 - 10.0
    assert math.isfinite(sleeve_pnl_increment({}, {}, {}))
