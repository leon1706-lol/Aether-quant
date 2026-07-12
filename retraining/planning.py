"""Pure retraining control-layer decisions (Phase V2-17).

Mirrors execution/order_gate.py's and performance/triggers.py's style: every
function here operates on plain dicts/scalars, no Postgres/Redis/Lean
dependency lives here. The caller (retraining/worker.py,
retraining/orchestrator.py) is responsible for fetching
performance_triggers rows (performance.postgres_triggers.fetch_candidate_triggers),
recent retraining_events rows, and the total experience_events observation
count, then handing them to evaluate_retraining_plan().

Only triggers with retrain_candidate=True ever reach this module - Phase 16
already enforces that in the SQL WHERE clause, but select_candidate_trigger()
re-checks it defensively so this stays correct even if called with an
unfiltered list in a test.
"""

from __future__ import annotations

from datetime import datetime

_ACTIVE_EVENT_STATUSES = ("planned", "running", "promoted")

# V2-17.5 - priority weighting so select_candidate_trigger() picks the most
# consequential eligible trigger, not just the newest one. A lone weak
# topology event never reaches this list in the first place (performance/
# triggers.py's persistence guards keep retrain_candidate=False for
# one-off noise) - this scoring only breaks ties *among* triggers that
# already cleared that bar.
_SEVERITY_SCORE = {"critical": 30, "warning": 20, "info": 10}
_TYPE_BASE_SCORE = {
    "risk_lock_trigger": 5,
    "drawdown_trigger": 4,
    "sharpe_degradation_trigger": 3,
    "win_rate_trigger": 3,
    "confidence_decay_trigger": 3,
    "regime_shift_trigger": 2,
    "liquidity_warning_trigger": 2,
    "observation_count_trigger": 1,
    "topology_uncertainty_trigger": 2,
    "topology_regime_mismatch_trigger": 2,
    "cluster_drift_trigger": 2,
    "model_topology_disagreement_trigger": 2,
    "trigger_frequency_spike": 2,
    # Phase 6 of the 5/10 -> 9/10 roadmap - comparable weight to
    # sharpe_degradation_trigger/win_rate_trigger/confidence_decay_trigger:
    # a decaying edge in the signal driving rank_sizing_enabled/the
    # portfolio book is a first-class reason to retrain, same tier as any
    # other model-quality trigger. select_candidate_trigger() already
    # generically handles any retrain_candidate=True trigger type - no
    # other change needed here.
    "rank_ic_decay_trigger": 3,
}
_TOPOLOGY_TRIGGER_TYPES = {
    "topology_uncertainty_trigger",
    "topology_regime_mismatch_trigger",
    "cluster_drift_trigger",
    "model_topology_disagreement_trigger",
}
_REGIME_TOPOLOGY_COMBO_BONUS = 5
_REPEAT_BONUS_PER_EXTRA = 2
_REPEAT_BONUS_CAP = 6


def _parse_timestamp(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _trigger_priority_score(trigger: dict, eligible: list[dict]) -> float:
    """Combines severity + trigger-type importance + two persistence-aware
    bonuses: a "regime shift plus a topology trigger co-occurring" combo
    bonus (a regime shift alongside topology uncertainty/drift is a
    stronger signal than either alone - applied only to the regime_shift
    and topology-type triggers themselves, not to unrelated candidates that
    merely happen to be eligible at the same time), and a capped "this
    trigger type/scope has repeated" bonus (a topology mismatch seen 3
    times among the eligible set outranks one seen once)."""
    severity_score = _SEVERITY_SCORE.get(trigger.get("severity"), 10)
    trigger_type = trigger.get("trigger_type")
    type_score = _TYPE_BASE_SCORE.get(trigger_type, 1)

    types_present = {candidate.get("trigger_type") for candidate in eligible}
    is_combo_participant = trigger_type == "regime_shift_trigger" or trigger_type in _TOPOLOGY_TRIGGER_TYPES
    combo_bonus = (
        _REGIME_TOPOLOGY_COMBO_BONUS
        if is_combo_participant and "regime_shift_trigger" in types_present and (types_present & _TOPOLOGY_TRIGGER_TYPES)
        else 0
    )

    repeat_count = sum(
        1
        for candidate in eligible
        if candidate.get("trigger_type") == trigger.get("trigger_type") and candidate.get("scope") == trigger.get("scope")
    )
    repeat_bonus = min((repeat_count - 1) * _REPEAT_BONUS_PER_EXTRA, _REPEAT_BONUS_CAP)

    return severity_score + type_score + combo_bonus + repeat_bonus


def select_candidate_trigger(triggers: list[dict], config: dict) -> dict | None:
    """Highest-priority trigger among those with retrain_candidate=True and
    an eligible severity, ties broken by newest first.

    `eligible_severities` defaults to ("warning", "critical") - "info"
    triggers (e.g. observation_count_trigger) never justify a retrain on
    their own. Priority is `_trigger_priority_score()` - see its docstring
    for the weighting (critical drawdown beats a topology warning; a
    regime-shift+topology combo beats either alone; a repeated trigger
    type/scope beats a single occurrence).
    """
    eligible_severities = set(config.get("eligible_severities", ("warning", "critical")))
    eligible = [
        trigger
        for trigger in triggers
        if trigger.get("retrain_candidate") and trigger.get("severity") in eligible_severities
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda trigger: (_trigger_priority_score(trigger, eligible), _parse_timestamp(trigger["created_at"])),
    )


def min_observations_satisfied(observation_count: int, min_observations: int) -> bool:
    return observation_count >= min_observations


def cooldown_remaining_seconds(recent_events: list[dict], cooldown_minutes: float, now: datetime) -> float:
    """Seconds until the cooldown clears, 0.0 if no active-status event is within it.

    An event counts against the cooldown while its status is planned/running/
    promoted - a rejected or failed retraining does not block the next
    attempt, so noisy triggers can't wedge the system into a permanent
    cooldown without ever producing a promoted model.
    """
    if cooldown_minutes <= 0:
        return 0.0

    cooldown_seconds = cooldown_minutes * 60.0
    latest_active_at: datetime | None = None
    for event in recent_events:
        if event.get("status") not in _ACTIVE_EVENT_STATUSES:
            continue
        created_at = _parse_timestamp(event["created_at"])
        if latest_active_at is None or created_at > latest_active_at:
            latest_active_at = created_at

    if latest_active_at is None:
        return 0.0

    elapsed_seconds = (now - latest_active_at).total_seconds()
    remaining = cooldown_seconds - elapsed_seconds
    return max(0.0, remaining)


def count_events_in_last_day(recent_events: list[dict], now: datetime) -> int:
    return sum(1 for event in recent_events if (now - _parse_timestamp(event["created_at"])).total_seconds() <= 86400)


def evaluate_retraining_plan(
    triggers: list[dict],
    recent_events: list[dict],
    observation_count: int,
    config: dict,
    now: datetime,
) -> dict:
    """Top-level pure decision. Checks run in order; the first failure
    short-circuits with an explanatory reason.

    Returns:
        {
          "should_plan": bool,
          "reason": str,
          "selected_trigger": dict | None,
          "cooldown_remaining_seconds": float,
          "daily_count": int,
          "daily_limit_reached": bool,
        }
    """
    if not config.get("enabled", True):
        return {
            "should_plan": False,
            "reason": "retraining_disabled",
            "selected_trigger": None,
            "cooldown_remaining_seconds": 0.0,
            "daily_count": 0,
            "daily_limit_reached": False,
        }

    selected_trigger = select_candidate_trigger(triggers, config)
    if selected_trigger is None:
        return {
            "should_plan": False,
            "reason": "no_eligible_candidate_trigger",
            "selected_trigger": None,
            "cooldown_remaining_seconds": 0.0,
            "daily_count": 0,
            "daily_limit_reached": False,
        }

    min_observations = int(config.get("min_observations", 0))
    if not min_observations_satisfied(observation_count, min_observations):
        return {
            "should_plan": False,
            "reason": f"min_observations_not_satisfied ({observation_count} < {min_observations})",
            "selected_trigger": selected_trigger,
            "cooldown_remaining_seconds": 0.0,
            "daily_count": 0,
            "daily_limit_reached": False,
        }

    cooldown_minutes = float(config.get("cooldown_minutes", 0))
    remaining = cooldown_remaining_seconds(recent_events, cooldown_minutes, now)
    if remaining > 0:
        return {
            "should_plan": False,
            "reason": f"cooldown_active ({remaining:.0f}s remaining)",
            "selected_trigger": selected_trigger,
            "cooldown_remaining_seconds": remaining,
            "daily_count": 0,
            "daily_limit_reached": False,
        }

    daily_count = count_events_in_last_day(recent_events, now)
    max_per_day = int(config.get("max_retrainings_per_day", 0)) or None
    daily_limit_reached = max_per_day is not None and daily_count >= max_per_day
    if daily_limit_reached:
        return {
            "should_plan": False,
            "reason": f"daily_retraining_limit_reached ({daily_count} >= {max_per_day})",
            "selected_trigger": selected_trigger,
            "cooldown_remaining_seconds": 0.0,
            "daily_count": daily_count,
            "daily_limit_reached": True,
        }

    return {
        "should_plan": True,
        "reason": f"eligible_candidate_trigger_selected ({selected_trigger['trigger_type']}/{selected_trigger['severity']})",
        "selected_trigger": selected_trigger,
        "cooldown_remaining_seconds": 0.0,
        "daily_count": daily_count,
        "daily_limit_reached": False,
    }
