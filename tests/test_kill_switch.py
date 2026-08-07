"""Tests for risk/kill_switch.py - V5.1 Phase 6 (production safety)."""

import pytest

from risk.kill_switch import evaluate_kill_switch


def _config(**overrides):
    config = {
        "enabled": True,
        "evaluation_bars": 60,
        "min_rolling_sharpe": -1.0,
        # 0.0 (not the real 0.0005 production default) so every EXISTING
        # test below keeps exercising the exact-zero-variance guard only,
        # unaffected by the new near-zero floor - tests specifically
        # targeting min_return_std_for_sharpe override it explicitly.
        "min_return_std_for_sharpe": 0.0,
        "max_drawdown_velocity_pct_per_bar": 0.01,
        "min_live_rank_ic": -0.02,
        "max_consecutive_losses": 12,
        "max_slippage_divergence_bps": 25.0,
        "max_model_age_days": 180,
        "action": "trade_lock",
    }
    config.update(overrides)
    return config


# ---------------------------------------------------------------------------
# enabled=False / no runtime_metrics -> strict no-op
# ---------------------------------------------------------------------------


def test_disabled_never_trips_regardless_of_inputs():
    runtime_metrics = {
        "recent_bar_returns": [-0.1] * 60,
        "drawdown_velocity_pct_per_bar": 1.0,
        "live_rank_ic": -1.0,
        "consecutive_losses": 999,
        "slippage_divergence_bps": 9999.0,
        "model_age_days": 9999,
        "reconciliation_breach": True,
    }
    decision = evaluate_kill_switch(runtime_metrics, _config(enabled=False))

    assert decision.tripped is False
    assert decision.severity == "none"
    assert decision.reason == "kill_switch_disabled"


def test_default_config_disabled_key_absent_never_trips():
    # config.get("enabled", False) - absent key must default to disabled,
    # not raise KeyError and not silently default to enabled.
    decision = evaluate_kill_switch({}, {})
    assert decision.tripped is False


def test_empty_runtime_metrics_never_trips_when_enabled():
    decision = evaluate_kill_switch({}, _config())
    assert decision.tripped is False
    assert decision.severity == "none"


def test_unconfigured_individual_thresholds_default_to_strict_no_op():
    # Enabled overall, but NONE of the individual threshold keys set -
    # every condition must degrade to its own no-op, not raise or use a
    # surprising implicit default.
    runtime_metrics = {
        "recent_bar_returns": [-0.5, -0.5, -0.5, -0.5],
        "drawdown_velocity_pct_per_bar": 0.5,
        "live_rank_ic": -0.9,
        "consecutive_losses": 100,
        "slippage_divergence_bps": 500.0,
        "model_age_days": 5000,
    }
    decision = evaluate_kill_switch(runtime_metrics, {"enabled": True})

    assert decision.tripped is False


# ---------------------------------------------------------------------------
# Each trigger fires independently
# ---------------------------------------------------------------------------


def test_rolling_sharpe_below_floor_trips():
    # Strongly negative mean, small non-zero variance -> a strongly
    # negative Sharpe. Constant returns (zero variance) would instead
    # report Sharpe=0.0 per _rolling_sharpe()'s own documented convention -
    # deliberately avoided here. 60 bars to clear the default
    # min_bars_for_sharpe warmup (== evaluation_bars, 60 in _config()).
    returns = [-0.025, -0.015] * 30
    decision = evaluate_kill_switch({"recent_bar_returns": returns}, _config())

    assert decision.tripped is True
    assert "rolling_sharpe_below_floor" in decision.triggers
    assert decision.severity == "warning"


def test_rolling_sharpe_insufficient_data_never_trips():
    decision = evaluate_kill_switch({"recent_bar_returns": [-0.5]}, _config())
    assert decision.tripped is False
    assert decision.observed["rolling_sharpe"] is None


# ---------------------------------------------------------------------------
# Warmup guard (bug fix: evaluation_bars was only a slice bound, never a
# minimum-sample requirement - a 2-bar mildly-negative run annualized into
# an absurd Sharpe and tripped the switch within the first few bars of
# every run).
# ---------------------------------------------------------------------------


def test_two_mildly_negative_bars_no_longer_trips_under_default_warmup():
    # The exact regression scenario: 2 mildly-negative bars used to trip
    # the switch because _rolling_sharpe() had no floor on sample size.
    decision = evaluate_kill_switch({"recent_bar_returns": [-0.001, -0.0005]}, _config())
    assert decision.tripped is False
    assert decision.observed["rolling_sharpe"] is None
    assert decision.observed["rolling_sharpe_num_bars"] == 2


def test_rolling_sharpe_trigger_stays_silent_below_min_bars_for_sharpe_even_with_extreme_returns():
    # Below the warmup floor, the trigger must not fire no matter how bad
    # the (tiny) sample looks - the whole point of a minimum-sample
    # requirement is that it isn't overridable by how extreme the data is.
    decision = evaluate_kill_switch(
        {"recent_bar_returns": [-0.5, -0.4, -0.3]}, _config(evaluation_bars=60, min_rolling_sharpe=-1.0)
    )
    assert decision.tripped is False
    assert decision.observed["rolling_sharpe"] is None


def test_min_bars_for_sharpe_independently_configurable_below_evaluation_bars():
    # An operator who genuinely wants a faster-reacting (but still
    # warmed-up) trigger can set min_bars_for_sharpe below evaluation_bars
    # explicitly - it must not be silently forced back up to
    # evaluation_bars.
    returns = [-0.03, -0.02] * 5  # 10 bars
    decision = evaluate_kill_switch(
        {"recent_bar_returns": returns},
        _config(evaluation_bars=60, min_bars_for_sharpe=10, min_rolling_sharpe=-1.0),
    )
    assert decision.tripped is True
    assert "rolling_sharpe_below_floor" in decision.triggers


def test_min_bars_for_sharpe_defaults_to_evaluation_bars():
    decision = evaluate_kill_switch({}, _config(evaluation_bars=45))
    assert decision.thresholds["min_bars_for_sharpe"] == 45


def test_evaluation_bars_zero_or_negative_never_trips_rolling_sharpe_instead_of_using_full_history():
    # Python's own `x[-0:]` == `x[0:]` slice semantics previously meant
    # evaluation_bars=0 silently fell back to the ENTIRE return history
    # instead of a real (empty) window - a misconfiguration should degrade
    # to "insufficient data", never to "unbounded history".
    returns = [-0.5] * 500
    decision = evaluate_kill_switch(
        {"recent_bar_returns": returns}, _config(evaluation_bars=0, min_rolling_sharpe=-1.0)
    )
    assert decision.tripped is False
    assert decision.observed["rolling_sharpe"] is None
    assert decision.observed["rolling_sharpe_num_bars"] == 0

    negative_decision = evaluate_kill_switch(
        {"recent_bar_returns": returns}, _config(evaluation_bars=-5, min_rolling_sharpe=-1.0)
    )
    assert negative_decision.tripped is False
    assert negative_decision.observed["rolling_sharpe_num_bars"] == 0


# ---------------------------------------------------------------------------
# Minimum-variance floor (bug fix: a near-flat/mostly-cash return window
# with a couple of small real values mixed in produced numerically
# explosive, meaningless Sharpe swings even with enough samples to clear
# min_bars_for_sharpe - count and variance are orthogonal guards).
# ---------------------------------------------------------------------------


def test_near_flat_window_with_tiny_noise_does_not_trip_under_the_real_default_floor():
    # 58 exact zeros + 2 tiny real values - passes min_bars_for_sharpe (60)
    # easily, but is exactly the degenerate low-variance shape that used to
    # produce an arbitrary-sign, arbitrary-magnitude Sharpe. Uses the REAL
    # production default (min_return_std_for_sharpe not overridden away).
    returns = [0.0] * 58 + [0.0001, -0.0001]
    config = _config()
    del config["min_return_std_for_sharpe"]  # exercise the real 0.0005 default
    decision = evaluate_kill_switch({"recent_bar_returns": returns}, config)
    assert decision.tripped is False
    assert decision.observed["rolling_sharpe"] == 0.0


def test_min_return_std_for_sharpe_floor_suppresses_a_low_variance_extreme_reading():
    # A window whose real std sits just under an explicit floor must report
    # a clean 0.0, not the unstable ratio the same data would otherwise
    # produce - reproduces the class of swing seen replaying a real
    # backtest's equity curve (Problems.md).
    returns = [0.0] * 58 + [0.0003, -0.0002]
    below_floor = evaluate_kill_switch(
        {"recent_bar_returns": returns}, _config(min_return_std_for_sharpe=0.01, min_rolling_sharpe=-1.0)
    )
    assert below_floor.tripped is False
    assert below_floor.observed["rolling_sharpe"] == 0.0

    # The identical data with the floor disabled (0.0, this file's
    # baseline) is free to compute the real, unstable ratio - demonstrates
    # the floor is actually doing something, not just always returning 0.0.
    with_floor_disabled = evaluate_kill_switch({"recent_bar_returns": returns}, _config())
    assert with_floor_disabled.observed["rolling_sharpe"] != 0.0


def test_min_return_std_for_sharpe_does_not_suppress_genuinely_volatile_bad_patch():
    # A real, meaningfully volatile bad stretch must still trip - the floor
    # only silences numerically degenerate (near-zero-variance) windows,
    # never a genuine risk-adjusted signal.
    returns = [-0.025, -0.015] * 30
    decision = evaluate_kill_switch(
        {"recent_bar_returns": returns}, _config(min_return_std_for_sharpe=0.0005, min_rolling_sharpe=-1.0)
    )
    assert decision.tripped is True
    assert "rolling_sharpe_below_floor" in decision.triggers


def test_min_return_std_for_sharpe_defaults_to_a_positive_value_not_zero():
    # Distinguishes the production default (0.0005) from this test file's
    # own deliberately-zeroed _config() baseline - build a config without
    # the key at all to see the function's own real default.
    config_without_key = _config()
    del config_without_key["min_return_std_for_sharpe"]
    decision = evaluate_kill_switch({}, config_without_key)
    assert decision.thresholds["min_return_std_for_sharpe"] == pytest.approx(0.0005)


def test_thresholds_reflect_configured_min_return_std_for_sharpe():
    decision = evaluate_kill_switch({}, _config(min_return_std_for_sharpe=0.002))
    assert decision.thresholds["min_return_std_for_sharpe"] == 0.002


def test_drawdown_velocity_above_cap_trips():
    decision = evaluate_kill_switch({"drawdown_velocity_pct_per_bar": 0.05}, _config())

    assert decision.tripped is True
    assert "drawdown_velocity_above_cap" in decision.triggers


def test_drawdown_velocity_none_never_trips():
    decision = evaluate_kill_switch({"drawdown_velocity_pct_per_bar": None}, _config())
    assert decision.tripped is False


def test_live_rank_ic_below_floor_trips():
    decision = evaluate_kill_switch({"live_rank_ic": -0.10}, _config())

    assert decision.tripped is True
    assert "live_rank_ic_below_floor" in decision.triggers


def test_live_rank_ic_none_never_trips():
    # None must mean "not available", never treated as 0.0 or a real reading.
    decision = evaluate_kill_switch({"live_rank_ic": None}, _config())
    assert decision.tripped is False


def test_consecutive_losses_above_cap_trips():
    decision = evaluate_kill_switch({"consecutive_losses": 20}, _config())

    assert decision.tripped is True
    assert "consecutive_losses_above_cap" in decision.triggers


def test_slippage_divergence_above_cap_trips():
    decision = evaluate_kill_switch({"slippage_divergence_bps": 50.0}, _config())

    assert decision.tripped is True
    assert "slippage_divergence_above_cap" in decision.triggers


def test_model_age_above_cap_trips():
    decision = evaluate_kill_switch({"model_age_days": 400}, _config())

    assert decision.tripped is True
    assert "model_age_above_cap" in decision.triggers


def test_reconciliation_breach_trips():
    decision = evaluate_kill_switch({"reconciliation_breach": True}, _config())

    assert decision.tripped is True
    assert "reconciliation_breach" in decision.triggers


def test_reconciliation_breach_false_never_trips_on_its_own():
    decision = evaluate_kill_switch({"reconciliation_breach": False}, _config())
    assert decision.tripped is False


# ---------------------------------------------------------------------------
# Severity, multiple triggers, thresholds/observed reporting
# ---------------------------------------------------------------------------


def test_single_trigger_is_warning_severity():
    decision = evaluate_kill_switch({"model_age_days": 400}, _config())
    assert decision.severity == "warning"


def test_multiple_triggers_is_critical_severity():
    decision = evaluate_kill_switch(
        {"model_age_days": 400, "consecutive_losses": 20}, _config()
    )
    assert decision.severity == "critical"
    assert len(decision.triggers) == 2


def test_thresholds_reflect_configured_values():
    decision = evaluate_kill_switch({}, _config(min_rolling_sharpe=-2.5))
    assert decision.thresholds["min_rolling_sharpe"] == -2.5


def test_recommended_action_comes_from_config():
    decision = evaluate_kill_switch({"model_age_days": 400}, _config(action="liquidate_and_lock"))
    assert decision.recommended_action == "liquidate_and_lock"


def test_untripped_decision_has_no_recommended_action():
    decision = evaluate_kill_switch({}, _config())
    assert decision.recommended_action == "none"


def test_evaluation_bars_windows_the_return_history():
    # Only the trailing evaluation_bars returns should feed the rolling
    # Sharpe - a long-past bad stretch outside the window must not still
    # be dragging the current rolling Sharpe down.
    old_bad_returns = [-0.5] * 100
    recent_good_returns = [0.01, -0.005, 0.008, 0.01, -0.003, 0.007, 0.009, 0.006]
    returns = old_bad_returns + recent_good_returns
    decision = evaluate_kill_switch(
        {"recent_bar_returns": returns}, _config(evaluation_bars=len(recent_good_returns), min_rolling_sharpe=-5.0)
    )

    assert decision.observed["rolling_sharpe_num_bars"] == len(recent_good_returns)


# ---------------------------------------------------------------------------
# Statelessness (documenting why "sticky until cleared" is main.py's job,
# not this pure function's - see main.py's own trade-lock wiring)
# ---------------------------------------------------------------------------


def test_function_is_pure_stateless_reevaluating_healthy_inputs_never_trips():
    # evaluate_kill_switch() itself carries no state between calls - a bar
    # with healthy inputs always returns tripped=False, REGARDLESS of
    # whether a previous call (with unhealthy inputs) tripped. Staying
    # locked across bars once main.py's trade_lock_active is set is main.py's
    # own responsibility (the same sticky contract the existing total-
    # drawdown lock already has) - this function has no memory of the past.
    config = _config()
    tripped_decision = evaluate_kill_switch({"model_age_days": 400}, config)
    healthy_decision = evaluate_kill_switch({"model_age_days": 1}, config)

    assert tripped_decision.tripped is True
    assert healthy_decision.tripped is False
