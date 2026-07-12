"""Tests for retraining.planning — V2-17.

Conventions: no test classes, module-level helpers, pure functions tested
with plain dicts (no Postgres/mocking needed).
"""

from datetime import datetime, timezone

from retraining.planning import (
    _trigger_priority_score,
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


def test_rank_ic_decay_trigger_is_retrain_eligible_and_scores_like_other_quality_triggers():
    # Phase 6 of the 5/10 -> 9/10 roadmap: select_candidate_trigger()
    # already generically handles any retrain_candidate=True trigger type
    # via _TYPE_BASE_SCORE - confirms rank_ic_decay_trigger is registered
    # there (not silently falling back to the default weight of 1) and is
    # actually selectable, same as every other model-quality trigger.
    rank_ic_trigger = _trigger(trigger_id="trg-rank-ic", trigger_type="rank_ic_decay_trigger", severity="warning")

    selected = select_candidate_trigger([rank_ic_trigger], _CONFIG)

    assert selected["trigger_id"] == "trg-rank-ic"
    sharpe_trigger = _trigger(trigger_id="trg-sharpe", trigger_type="sharpe_degradation_trigger", severity="warning")
    rank_ic_score = _trigger_priority_score(rank_ic_trigger, [rank_ic_trigger, sharpe_trigger])
    sharpe_score = _trigger_priority_score(sharpe_trigger, [rank_ic_trigger, sharpe_trigger])
    assert rank_ic_score == sharpe_score  # same weight (3), same severity -> same score


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


# -- V2-17.5 priority weighting ----------------------------------------------


def test_select_candidate_trigger_prefers_critical_drawdown_over_topology_warning():
    drawdown = _trigger(
        trigger_id="dd",
        trigger_type="drawdown_trigger",
        severity="critical",
        created_at="2026-07-01T00:00:00+00:00",
    )
    # newer, but only a warning-severity topology trigger — must still lose.
    topology = _trigger(
        trigger_id="tu",
        trigger_type="topology_uncertainty_trigger",
        severity="warning",
        created_at="2026-07-02T11:00:00+00:00",
    )

    selected = select_candidate_trigger([drawdown, topology], _CONFIG)

    assert selected["trigger_id"] == "dd"


def test_regime_topology_combo_scores_higher_than_standalone_topology_trigger():
    standalone = _trigger(trigger_id="topo", trigger_type="cluster_drift_trigger", severity="warning")
    regime = _trigger(trigger_id="regime", trigger_type="regime_shift_trigger", severity="warning")

    standalone_score = _trigger_priority_score(standalone, [standalone])
    combo_score = _trigger_priority_score(standalone, [standalone, regime])

    assert combo_score > standalone_score


def test_regime_topology_combo_bonus_does_not_apply_to_unrelated_trigger_types():
    sharpe = _trigger(trigger_id="sharpe", trigger_type="sharpe_degradation_trigger", severity="warning")
    topology = _trigger(trigger_id="topo", trigger_type="cluster_drift_trigger", severity="warning")
    regime = _trigger(trigger_id="regime", trigger_type="regime_shift_trigger", severity="warning")

    sharpe_score_alone = _trigger_priority_score(sharpe, [sharpe])
    sharpe_score_with_combo_present = _trigger_priority_score(sharpe, [sharpe, topology, regime])

    assert sharpe_score_alone == sharpe_score_with_combo_present


def test_repeated_topology_mismatch_beats_single_occurrence():
    single = [_trigger(trigger_id="single", trigger_type="cluster_drift_trigger", severity="warning", scope="portfolio")]
    repeated = [
        _trigger(trigger_id="repeat-1", trigger_type="cluster_drift_trigger", severity="warning", scope="portfolio"),
        _trigger(trigger_id="repeat-2", trigger_type="cluster_drift_trigger", severity="warning", scope="portfolio"),
        _trigger(trigger_id="repeat-3", trigger_type="cluster_drift_trigger", severity="warning", scope="portfolio"),
    ]

    single_score = _trigger_priority_score(single[0], single)
    repeated_score = _trigger_priority_score(repeated[0], repeated)

    assert repeated_score > single_score


def test_evaluate_retraining_plan_ignores_weak_one_off_topology_trigger():
    """A topology trigger that never earned retrain_candidate=True (because
    performance/triggers.py's persistence guard rejected it as a one-off)
    must not be selectable, regardless of how this module weighs it."""
    weak_topology = _trigger(
        trigger_id="topo-weak", trigger_type="topology_uncertainty_trigger", severity="warning", retrain_candidate=False
    )

    result = evaluate_retraining_plan([weak_topology], [], 1000, _CONFIG, _NOW)

    assert result["should_plan"] is False
    assert result["reason"] == "no_eligible_candidate_trigger"


def test_evaluate_retraining_plan_accepts_severe_topology_trigger():
    severe_topology = _trigger(
        trigger_id="topo-severe",
        trigger_type="cluster_drift_trigger",
        severity="critical",
        retrain_candidate=True,
    )

    result = evaluate_retraining_plan([severe_topology], [], 1000, _CONFIG, _NOW)

    assert result["should_plan"] is True
    assert result["selected_trigger"]["trigger_id"] == "topo-severe"
