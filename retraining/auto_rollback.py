"""V5.1 Phase 6 (production safety): automated rollback selection.

Pure - never touches Postgres or calls orchestrator.rollback() itself.
retraining/worker.py is the caller: it assembles active_version/
version_history/degradation_signals from Postgres (the same
fetch_active_model_version()/fetch_rollback_candidates() calls
retraining/status_export.py already uses), calls select_rollback_target(),
and only THEN calls the EXISTING, already-fully-implemented
orchestrator.rollback() when told to - this module makes no new
promotion/rollback mechanism, it only decides whether the existing one
should fire automatically instead of waiting for a human to run
`aq retrain rollback`.
"""

from __future__ import annotations


def select_rollback_target(
    active_version: dict,
    version_history: list[dict],
    degradation_signals: dict,
    config: dict,
) -> dict:
    """Returns {"should_rollback": bool, "to_version_id": str | None,
    "reason": str, "failures": list[str]}.

    active_version: the currently active model_versions row (retraining/
    postgres_registry.py::fetch_active_model_version()'s shape).
    version_history: candidate rollback TARGETS, newest first (fetch_rollback_candidates()'s
    shape - status in {"archived", "rolled_back"}).
    degradation_signals: {"kill_switch_tripped": bool, "net_sharpe_decay": bool,
    "rank_ic_decay": bool, "bars_since_promotion": int, "bars_since_last_rollback": int | None}
    - the trigger flags plus the two "how long has X been true" counters this
    function needs to enforce cooldown/runway (deliberately plain integers,
    not timestamps - retraining/worker.py owns translating its own notion
    of "how long" into a count, this module never needs to know what a
    "bar" represents in that context).

    GUARDRAIL - enabled defaults to False: an automatic weight swap is the
    single most consequential action in this system, must be opt-in.

    REFUSES to act (should_rollback=False, reason names exactly which
    guard blocked it) when:
    - config["enabled"] is not True.
    - none of config["triggers"] (default ["kill_switch_tripped",
      "net_sharpe_decay", "rank_ic_decay"]) are True in degradation_signals.
    - degradation_signals["bars_since_promotion"] < config["min_bars_since_promotion"]
      (default 40) - the active version needs a minimum runway to prove
      itself before being judged.
    - a rollback already happened within config["cooldown_bars"] (default
      120) - degradation_signals["bars_since_last_rollback"] is None (never
      rolled back) or >= cooldown_bars to pass this guard.
    - no candidate in version_history satisfies config["require_prior_gate_pass"]
      (default True) - metrics.validation_gate.passed must be True on the
      chosen candidate; a version that never cleared the gate itself is
      never a valid rollback target, no matter how badly the active one is
      degrading.

    Picks the NEWEST (version_history[0]) candidate that passes the gate
    check - never an arbitrary/older one when a newer valid candidate
    exists."""
    failures: list[str] = []

    if not bool(config.get("enabled", False)):
        return {"should_rollback": False, "to_version_id": None, "reason": "auto_rollback_disabled", "failures": []}

    configured_triggers = list(config.get("triggers", ["kill_switch_tripped", "net_sharpe_decay", "rank_ic_decay"]))
    fired_triggers = [name for name in configured_triggers if bool(degradation_signals.get(name, False))]
    if not fired_triggers:
        return {
            "should_rollback": False, "to_version_id": None,
            "reason": "no_configured_trigger_fired", "failures": [],
        }

    min_bars_since_promotion = int(config.get("min_bars_since_promotion", 40))
    bars_since_promotion = degradation_signals.get("bars_since_promotion")
    if bars_since_promotion is None or int(bars_since_promotion) < min_bars_since_promotion:
        failures.append("active_version_below_min_runway")

    cooldown_bars = int(config.get("cooldown_bars", 120))
    bars_since_last_rollback = degradation_signals.get("bars_since_last_rollback")
    if bars_since_last_rollback is not None and int(bars_since_last_rollback) < cooldown_bars:
        failures.append("cooldown_active")

    require_prior_gate_pass = bool(config.get("require_prior_gate_pass", True))
    to_version_id = None
    if not failures:
        for candidate in version_history:
            if require_prior_gate_pass:
                gate_passed = bool((candidate.get("metrics") or {}).get("validation_gate", {}).get("passed", False))
                if not gate_passed:
                    continue
            to_version_id = candidate.get("model_version_id")
            break
        if to_version_id is None:
            failures.append("no_eligible_rollback_target")

    if failures:
        return {
            "should_rollback": False, "to_version_id": None,
            "reason": f"blocked: {', '.join(failures)}", "failures": failures,
        }

    return {
        "should_rollback": True,
        "to_version_id": to_version_id,
        "reason": f"triggered_by: {', '.join(fired_triggers)}",
        "failures": [],
    }
