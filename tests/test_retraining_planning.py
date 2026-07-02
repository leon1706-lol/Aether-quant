"""Tests for retraining.planning — V2-17.

Conventions: no test classes, module-level helpers, pure functions tested
with plain dicts (no Postgres/mocking needed).
"""

from datetime import datetime, timezone

from retraining.planning import (
    cooldown_remaining_seconds,
    count_events_in_last_day,
    evaluate_retraining_plan,
    min_observations_satisfied,
    select_candidate_trigger,
)

_CONFIG = {
    "enabled": True,
    "min_observations": 100,
    "cooldown_minutes": 60,
    "max_retrainings_per_day": 2,
    "eligible_severities": ("warning", "critical"),
}

_NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


def _trigger(**overrides) -> dict:
    defaults = {
        "trigger_id": "trg-1",
        "created_at": "2026-07-02T11:00:00+00:00",
        "trigger_type": "drawdown_trigger",
        "severity": "critical",
        "retrain_candidate": True,
    }
    defaults.update(overrides)
    return defaults


def _event(**overrides) -> dict:
    defaults = {
        "retraining_id": "evt-1",
        "created_at": "2026-07-02T11:30:00+00:00",
        "status": "planned",
    }
    defaults.update(overrides)
    return defaults


def test_select_candidate_trigger_ignores_non_candidate_triggers():
    triggers = [_trigger(retrain_candidate=False, severity="critical")]

    assert select_candidate_trigger(triggers, _CONFIG) is None


def test_select_candidate_trigger_ignores_weak_severity():
    triggers = [_trigger(severity="info", retrain_candidate=True)]

    assert select_candidate_trigger(triggers, _CONFIG) is None


def test_select_candidate_trigger_picks_newest_eligible():
    older = _trigger(trigger_id="trg-old", created_at="2026-07-01T00:00:00+00:00")
    newer = _trigger(trigger_id="trg-new", created_at="2026-07-02T10:00:00+00:00")

    selected = select_candidate_trigger([older, newer], _CONFIG)

    assert selected["trigger_id"] == "trg-new"


def test_min_observations_satisfied():
    assert min_observations_satisfied(500, 100) is True
    assert min_observations_satisfied(50, 100) is False


def test_cooldown_remaining_seconds_zero_when_no_active_events():
    events = [_event(status="rejected"), _event(status="failed")]

    assert cooldown_remaining_seconds(events, cooldown_minutes=60, now=_NOW) == 0.0


def test_cooldown_remaining_seconds_nonzero_when_active_event_recent():
    events = [_event(status="planned", created_at="2026-07-02T11:45:00+00:00")]

    remaining = cooldown_remaining_seconds(events, cooldown_minutes=60, now=_NOW)

    assert remaining > 0.0
    assert remaining <= 60 * 60


def test_cooldown_remaining_seconds_zero_when_cooldown_disabled():
    events = [_event(status="planned", created_at="2026-07-02T11:59:00+00:00")]

    assert cooldown_remaining_seconds(events, cooldown_minutes=0, now=_NOW) == 0.0


def test_count_events_in_last_day():
    events = [
        _event(created_at="2026-07-02T11:00:00+00:00"),
        _event(created_at="2026-06-01T00:00:00+00:00"),
    ]

    assert count_events_in_last_day(events, _NOW) == 1


def test_evaluate_retraining_plan_disabled():
    result = evaluate_retraining_plan([_trigger()], [], 1000, {**_CONFIG, "enabled": False}, _NOW)

    assert result["should_plan"] is False
    assert result["reason"] == "retraining_disabled"


def test_evaluate_retraining_plan_no_eligible_trigger():
    result = evaluate_retraining_plan([_trigger(retrain_candidate=False)], [], 1000, _CONFIG, _NOW)

    assert result["should_plan"] is False
    assert result["reason"] == "no_eligible_candidate_trigger"


def test_evaluate_retraining_plan_min_observations_not_satisfied():
    result = evaluate_retraining_plan([_trigger()], [], 10, _CONFIG, _NOW)

    assert result["should_plan"] is False
    assert "min_observations_not_satisfied" in result["reason"]


def test_evaluate_retraining_plan_respects_cooldown():
    recent_events = [_event(status="planned", created_at="2026-07-02T11:45:00+00:00")]

    result = evaluate_retraining_plan([_trigger()], recent_events, 1000, _CONFIG, _NOW)

    assert result["should_plan"] is False
    assert "cooldown_active" in result["reason"]
    assert result["cooldown_remaining_seconds"] > 0


def test_evaluate_retraining_plan_respects_daily_limit():
    recent_events = [
        _event(retraining_id=f"evt-{i}", status="rejected", created_at="2026-07-02T01:00:00+00:00")
        for i in range(2)
    ]

    result = evaluate_retraining_plan([_trigger()], recent_events, 1000, _CONFIG, _NOW)

    assert result["should_plan"] is False
    assert result["daily_limit_reached"] is True


def test_evaluate_retraining_plan_should_plan_when_all_checks_pass():
    result = evaluate_retraining_plan([_trigger()], [], 1000, _CONFIG, _NOW)

    assert result["should_plan"] is True
    assert result["selected_trigger"]["trigger_id"] == "trg-1"
