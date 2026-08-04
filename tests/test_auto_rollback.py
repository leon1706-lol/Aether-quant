"""Tests for retraining/auto_rollback.py - V5.1 Phase 6 (production safety)."""

import pytest

from retraining.auto_rollback import select_rollback_target


def _config(**overrides):
    config = {
        "enabled": True,
        "min_bars_since_promotion": 40,
        "cooldown_bars": 120,
        "require_prior_gate_pass": True,
        "triggers": ["kill_switch_tripped", "net_sharpe_decay", "rank_ic_decay"],
    }
    config.update(overrides)
    return config


def _candidate(version_id: str, gate_passed: bool = True) -> dict:
    return {"model_version_id": version_id, "status": "archived", "metrics": {"validation_gate": {"passed": gate_passed}}}


def _healthy_signals(**overrides) -> dict:
    signals = {
        "kill_switch_tripped": True,
        "net_sharpe_decay": False,
        "rank_ic_decay": False,
        "bars_since_promotion": 100,
        "bars_since_last_rollback": None,
    }
    signals.update(overrides)
    return signals


# ---------------------------------------------------------------------------
# enabled=False -> strict no-op
# ---------------------------------------------------------------------------


def test_disabled_never_rolls_back_even_with_every_trigger_fired():
    result = select_rollback_target({}, [_candidate("v1")], _healthy_signals(), _config(enabled=False))

    assert result["should_rollback"] is False
    assert result["reason"] == "auto_rollback_disabled"


def test_default_config_missing_enabled_key_never_rolls_back():
    result = select_rollback_target({}, [_candidate("v1")], _healthy_signals(), {})
    assert result["should_rollback"] is False


# ---------------------------------------------------------------------------
# No configured trigger fired
# ---------------------------------------------------------------------------


def test_no_trigger_fired_never_rolls_back():
    signals = _healthy_signals(kill_switch_tripped=False)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config())

    assert result["should_rollback"] is False
    assert result["reason"] == "no_configured_trigger_fired"


def test_only_unconfigured_trigger_fired_never_rolls_back():
    # A trigger key not listed in config["triggers"] must not count, even
    # if it happens to be True in degradation_signals.
    signals = _healthy_signals(kill_switch_tripped=False, net_sharpe_decay=False, rank_ic_decay=False)
    signals["some_other_signal"] = True
    result = select_rollback_target({}, [_candidate("v1")], signals, _config())

    assert result["should_rollback"] is False


# ---------------------------------------------------------------------------
# require_prior_gate_pass - refuses a never-promoted target
# ---------------------------------------------------------------------------


def test_refuses_a_target_that_never_passed_the_gate():
    result = select_rollback_target(
        {}, [_candidate("v1", gate_passed=False)], _healthy_signals(), _config()
    )

    assert result["should_rollback"] is False
    assert "no_eligible_rollback_target" in result["failures"]


def test_skips_ineligible_target_and_picks_next_eligible_one():
    version_history = [_candidate("v1", gate_passed=False), _candidate("v2", gate_passed=True)]
    result = select_rollback_target({}, version_history, _healthy_signals(), _config())

    assert result["should_rollback"] is True
    assert result["to_version_id"] == "v2"


def test_require_prior_gate_pass_disabled_accepts_any_target():
    result = select_rollback_target(
        {}, [_candidate("v1", gate_passed=False)], _healthy_signals(),
        _config(require_prior_gate_pass=False),
    )

    assert result["should_rollback"] is True
    assert result["to_version_id"] == "v1"


def test_picks_the_newest_eligible_candidate_not_an_older_one():
    version_history = [_candidate("newest", gate_passed=True), _candidate("older", gate_passed=True)]
    result = select_rollback_target({}, version_history, _healthy_signals(), _config())

    assert result["to_version_id"] == "newest"


# ---------------------------------------------------------------------------
# min_bars_since_promotion / cooldown_bars both bind
# ---------------------------------------------------------------------------


def test_refuses_when_active_version_below_min_runway():
    signals = _healthy_signals(bars_since_promotion=10)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config(min_bars_since_promotion=40))

    assert result["should_rollback"] is False
    assert "active_version_below_min_runway" in result["failures"]


def test_refuses_when_bars_since_promotion_missing():
    signals = _healthy_signals(bars_since_promotion=None)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config())

    assert result["should_rollback"] is False
    assert "active_version_below_min_runway" in result["failures"]


def test_allows_when_exactly_at_min_runway_boundary():
    signals = _healthy_signals(bars_since_promotion=40)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config(min_bars_since_promotion=40))

    assert result["should_rollback"] is True


def test_refuses_when_cooldown_still_active():
    signals = _healthy_signals(bars_since_last_rollback=10)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config(cooldown_bars=120))

    assert result["should_rollback"] is False
    assert "cooldown_active" in result["failures"]


def test_allows_when_never_rolled_back_before():
    # bars_since_last_rollback=None means "never rolled back" - must NOT be
    # treated as "cooldown still active" (which would make auto-rollback
    # permanently refuse to ever act on a fresh system).
    signals = _healthy_signals(bars_since_last_rollback=None)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config())

    assert result["should_rollback"] is True


def test_allows_when_cooldown_has_elapsed():
    signals = _healthy_signals(bars_since_last_rollback=200)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config(cooldown_bars=120))

    assert result["should_rollback"] is True


def test_both_runway_and_cooldown_failures_reported_together():
    signals = _healthy_signals(bars_since_promotion=5, bars_since_last_rollback=10)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config())

    assert "active_version_below_min_runway" in result["failures"]
    assert "cooldown_active" in result["failures"]


# ---------------------------------------------------------------------------
# Reason string reflects the actual fired triggers
# ---------------------------------------------------------------------------


def test_reason_lists_the_fired_triggers():
    signals = _healthy_signals(kill_switch_tripped=True, net_sharpe_decay=True, rank_ic_decay=False)
    result = select_rollback_target({}, [_candidate("v1")], signals, _config())

    assert "kill_switch_tripped" in result["reason"]
    assert "net_sharpe_decay" in result["reason"]
    assert "rank_ic_decay" not in result["reason"]
