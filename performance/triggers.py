"""Pure trigger evaluation over experience-event dicts (Phase V2-16).

Mirrors experience/observation_metrics.py's design: every function here
operates on a plain list[dict] of experience-event-shaped dicts (in-memory
log or Postgres JSONB rows) - one shape, source-agnostic. No Postgres/Redis/
Lean dependency lives here; see performance/postgres_triggers.py for the I/O
layer and performance/trigger_worker.py for the standalone durable worker.

Phase V2-16 only detects/scores/logs triggers - it never retrains anything.
retrain_candidate is a flag consumed by Phase V2-17, not an action taken here.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from experience.observation_metrics import (
    simulated_max_drawdown,
    simulated_sharpe,
    simulated_win_loss,
)

SEVERITIES = ("info", "warning", "critical")
TRIGGER_TYPES = (
    "observation_count_trigger",
    "drawdown_trigger",
    "sharpe_degradation_trigger",
    "win_rate_trigger",
    "confidence_decay_trigger",
    "regime_shift_trigger",
    "liquidity_warning_trigger",
    "risk_lock_trigger",
    # V2-17.5 - topology-aware triggers, all read event["topology"] fields
    # produced by topology.learned_topology.apply_learned_topology().
    "topology_uncertainty_trigger",
    "topology_regime_mismatch_trigger",
    "cluster_drift_trigger",
    "model_topology_disagreement_trigger",
    # Different shape (operates on trigger rows, not events) - see
    # trigger_frequency_spike()'s own docstring.
    "trigger_frequency_spike",
    # Retraining-cadence triggers - unlike observation_count_trigger (which
    # counts every per-asset-per-bar event and fires at "info" severity, so
    # it can never itself select a retraining run), these are designed to
    # actually be retrain-eligible. See executed_trade_count_trigger's and
    # sustained_drawdown_trigger's own docstrings.
    "executed_trade_count_trigger",
    "sustained_drawdown_trigger",
    # V2-22 - deployment-health trigger, not a model-quality trigger. Fires
    # when mode=='live' but the order gate is still silently simulating
    # fills (misconfigured credentials/flag/risk-lock in a deployment that
    # believes it's live). See _NON_RETRAIN_TRIGGERS below - retraining a
    # model cannot fix a broker misconfiguration.
    "live_order_permission_blocked_trigger",
)

_MODEL_QUALITY_TRIGGERS = {
    "drawdown_trigger",
    "sharpe_degradation_trigger",
    "win_rate_trigger",
    "confidence_decay_trigger",
    "regime_shift_trigger",
    "topology_uncertainty_trigger",
    "topology_regime_mismatch_trigger",
    "cluster_drift_trigger",
    "model_topology_disagreement_trigger",
    "sustained_drawdown_trigger",
}

# Cadence triggers are always retrain-eligible when they fire at all (they
# only fire at meaningful checkpoints - an exact trade-count multiple - not
# on every bar), same special-casing as risk_lock_trigger.
_CADENCE_TRIGGERS = {
    "risk_lock_trigger",
    "executed_trade_count_trigger",
}

# Deployment-health triggers are never retrain-eligible, even at critical
# severity - a broker/credential/flag misconfiguration is an ops problem,
# not something a new model version can fix.
_NON_RETRAIN_TRIGGERS = {
    "live_order_permission_blocked_trigger",
}

_RECOMMENDED_ACTIONS = {
    "observation_count_trigger": "monitor",
    "drawdown_trigger": "reduce_exposure",
    "sharpe_degradation_trigger": "review_model_quality",
    "win_rate_trigger": "review_model_quality",
    "confidence_decay_trigger": "review_model_quality",
    "regime_shift_trigger": "investigate_regime_shift",
    "liquidity_warning_trigger": "investigate_liquidity",
    "risk_lock_trigger": "escalate_risk_review",
    "topology_uncertainty_trigger": "investigate_topology_uncertainty",
    "topology_regime_mismatch_trigger": "investigate_regime_mismatch",
    "cluster_drift_trigger": "investigate_cluster_drift",
    "model_topology_disagreement_trigger": "review_topology_model",
    "trigger_frequency_spike": "investigate_trigger_volume",
    "executed_trade_count_trigger": "consider_scheduled_retraining",
    "sustained_drawdown_trigger": "reduce_exposure",
    "live_order_permission_blocked_trigger": "escalate_deployment_review",
}

_LIQUIDITY_REJECTION_ACTIONS = {"block", "reduce_size"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_created_at(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _breach_ratio_below(value: float, threshold: float) -> float:
    """For metrics that fire when value < threshold (lower is worse)."""
    scale = abs(threshold) if threshold != 0 else 1.0
    return 1.0 + max(0.0, (threshold - value) / scale)


def _breach_ratio_above(value: float, threshold: float) -> float:
    """For metrics that fire when value >= threshold (higher is worse)."""
    scale = abs(threshold) if threshold != 0 else 1.0
    return 1.0 + max(0.0, (value - threshold) / scale)


def _severity_for_breach(breach_ratio: float) -> str:
    return "critical" if breach_ratio >= 1.5 else "warning"


def _is_retrain_candidate(trigger_type: str, severity: str) -> bool:
    if trigger_type in _NON_RETRAIN_TRIGGERS:
        return False
    if trigger_type in _CADENCE_TRIGGERS:
        return True
    if severity == "critical":
        return True
    if trigger_type in _MODEL_QUALITY_TRIGGERS and severity == "warning":
        return True
    return False


def _latest_mode(events: list[dict]) -> str:
    for event in reversed(events):
        mode = event.get("mode")
        if mode:
            return mode
    return "unknown"


def _dominant(labels) -> str:
    counts = Counter(labels)
    return max(sorted(counts), key=lambda value: counts[value])


def _make_trigger(
    trigger_type: str,
    severity: str,
    mode: str,
    scope: str,
    metric_value: float,
    threshold: float,
    message: str,
) -> dict:
    return {
        "trigger_id": str(uuid.uuid4()),
        "created_at": _now_iso(),
        "trigger_type": trigger_type,
        "severity": severity,
        "mode": mode,
        "scope": scope,
        "metric_value": metric_value,
        "threshold": threshold,
        "message": message,
        "recommended_action": _RECOMMENDED_ACTIONS[trigger_type],
        "retrain_candidate": _is_retrain_candidate(trigger_type, severity),
    }


def observation_count_trigger(events: list[dict], interval: int = 100) -> list[dict]:
    count = len(events)
    if interval <= 0 or count == 0 or count % interval != 0:
        return []

    return [
        _make_trigger(
            "observation_count_trigger",
            "info",
            _latest_mode(events),
            "portfolio",
            float(count),
            float(interval),
            f"Reached {count} observations (interval {interval}).",
        )
    ]


def executed_trade_count_trigger(events: list[dict], interval: int = 100) -> list[dict]:
    """Retraining-cadence trigger based on actually executed trades, not raw
    observation volume. observation_count_trigger counts every per-asset-per-
    bar event regardless of action (most are hold/observe/simulate) and fires
    at "info" severity, which phase_v2.retraining.eligible_severities
    excludes - so it can never itself select a retraining run. This trigger
    counts only event["action"] == "trade" entries and fires at "warning"
    (a fixed severity, not breach-ratio-derived - there is no "how bad" axis
    for a count-reached signal), so a periodic cadence tied to real trading
    activity can actually drive retraining."""
    trade_count = sum(1 for event in events if event.get("action") == "trade")
    if interval <= 0 or trade_count == 0 or trade_count % interval != 0:
        return []

    return [
        _make_trigger(
            "executed_trade_count_trigger",
            "warning",
            _latest_mode(events),
            "portfolio",
            float(trade_count),
            float(interval),
            f"Reached {trade_count} executed trades (interval {interval}).",
        )
    ]


def drawdown_trigger(events: list[dict], max_drawdown_threshold: float = -0.10) -> list[dict]:
    if not events:
        return []

    sim_max_dd = simulated_max_drawdown(events)
    real_dd_raw = (events[-1].get("portfolio") or {}).get("current_drawdown")
    real_dd = float(real_dd_raw) if real_dd_raw is not None else 0.0

    worst = min(sim_max_dd, real_dd)
    if worst > max_drawdown_threshold:
        return []

    severity = _severity_for_breach(_breach_ratio_below(worst, max_drawdown_threshold))
    source = "simulated" if sim_max_dd <= real_dd else "real"
    return [
        _make_trigger(
            "drawdown_trigger",
            severity,
            _latest_mode(events),
            "portfolio",
            worst,
            max_drawdown_threshold,
            f"{source} drawdown reached {worst:.2%} (threshold {max_drawdown_threshold:.2%}).",
        )
    ]


def _worst_real_drawdown_by_day(events: list[dict]) -> dict[date, float]:
    worst_by_day: dict[date, float] = {}
    for event in events:
        created_at = event.get("created_at")
        current_drawdown = (event.get("portfolio") or {}).get("current_drawdown")
        if created_at is None or current_drawdown is None:
            continue
        day = _parse_created_at(created_at).date()
        worst_by_day[day] = min(worst_by_day.get(day, 0.0), float(current_drawdown))
    return worst_by_day


def sustained_drawdown_trigger(
    events: list[dict],
    max_drawdown_threshold: float = -0.10,
    consecutive_days: int = 2,
) -> list[dict]:
    """A slower, day-granularity companion to drawdown_trigger's single-bar
    point-in-time check - not a replacement. drawdown_trigger still fires
    immediately on one severe bar; this fires only when the real portfolio's
    worst drawdown breaches max_drawdown_threshold on `consecutive_days`
    distinct *trailing* trading days in a row, catching a moderate-but-
    persistent decline a point check might miss (or a single noisy bad bar
    that recovers the next day, which this correctly does not fire on)."""
    if not events or consecutive_days <= 0:
        return []

    worst_by_day = _worst_real_drawdown_by_day(events)
    trading_days = sorted(worst_by_day)
    if len(trading_days) < consecutive_days:
        return []

    trailing_days = trading_days[-consecutive_days:]
    trailing_drawdowns = [worst_by_day[day] for day in trailing_days]
    if any(value > max_drawdown_threshold for value in trailing_drawdowns):
        return []

    worst = min(trailing_drawdowns)
    severity = _severity_for_breach(_breach_ratio_below(worst, max_drawdown_threshold))
    return [
        _make_trigger(
            "sustained_drawdown_trigger",
            severity,
            _latest_mode(events),
            "portfolio",
            worst,
            max_drawdown_threshold,
            f"Drawdown breached {max_drawdown_threshold:.2%} on {consecutive_days} consecutive "
            f"trading days (worst {worst:.2%}).",
        )
    ]


def sharpe_degradation_trigger(
    events: list[dict],
    min_sharpe: float = 0.3,
    window: int = 100,
) -> list[dict]:
    windowed = events[-window:] if window > 0 else events
    if len(windowed) < 2:
        return []

    sharpe = simulated_sharpe(windowed)
    if sharpe >= min_sharpe:
        return []

    severity = _severity_for_breach(_breach_ratio_below(sharpe, min_sharpe))
    return [
        _make_trigger(
            "sharpe_degradation_trigger",
            severity,
            _latest_mode(windowed),
            "portfolio",
            sharpe,
            min_sharpe,
            f"Rolling Sharpe dropped to {sharpe:.2f} (min {min_sharpe:.2f}).",
        )
    ]


def win_rate_trigger(
    events: list[dict],
    min_win_rate: float = 0.45,
    window: int = 100,
) -> list[dict]:
    windowed = events[-window:] if window > 0 else events
    result = simulated_win_loss(windowed)
    total = result["wins"] + result["losses"]
    if total < 5:
        return []

    win_rate = result["win_rate"]
    if win_rate >= min_win_rate:
        return []

    severity = _severity_for_breach(_breach_ratio_below(win_rate, min_win_rate))
    return [
        _make_trigger(
            "win_rate_trigger",
            severity,
            _latest_mode(windowed),
            "portfolio",
            win_rate,
            min_win_rate,
            f"Win rate dropped to {win_rate:.1%} over {total} trades (min {min_win_rate:.1%}).",
        )
    ]


def confidence_decay_trigger(
    events: list[dict],
    window: int = 50,
    decay_ratio_threshold: float = 0.5,
    instability_std_threshold: float = 0.25,
) -> list[dict]:
    confidences = [float(event["confidence"]) for event in events if event.get("confidence") is not None]
    prior = confidences[-2 * window : -window]
    recent = confidences[-window:]
    if len(prior) < window // 2 or len(recent) < window // 2:
        return []

    mean_prior = statistics.mean(prior)
    mean_recent = statistics.mean(recent)
    std_recent = statistics.pstdev(recent)
    mode = _latest_mode(events)

    triggers: list[dict] = []

    decay_threshold_value = mean_prior * decay_ratio_threshold
    if mean_recent <= decay_threshold_value:
        severity = _severity_for_breach(_breach_ratio_below(mean_recent, decay_threshold_value))
        triggers.append(
            _make_trigger(
                "confidence_decay_trigger",
                severity,
                mode,
                "portfolio",
                mean_recent,
                decay_threshold_value,
                f"Confidence decayed to {mean_recent:.3f} (was {mean_prior:.3f}).",
            )
        )

    if std_recent >= instability_std_threshold:
        severity = _severity_for_breach(_breach_ratio_above(std_recent, instability_std_threshold))
        triggers.append(
            _make_trigger(
                "confidence_decay_trigger",
                severity,
                mode,
                "portfolio",
                std_recent,
                instability_std_threshold,
                f"Confidence became unstable (std {std_recent:.3f}, threshold {instability_std_threshold:.3f}).",
            )
        )

    return triggers


def regime_shift_trigger(
    events: list[dict],
    window: int = 20,
    sensitivity: float = 0.6,
) -> list[dict]:
    regimes = [
        event["regime"]["primary_regime"]
        for event in events
        if isinstance(event.get("regime"), dict) and event["regime"].get("primary_regime")
    ]
    prior = regimes[-2 * window : -window]
    recent = regimes[-window:]
    if not prior or not recent:
        return []

    dominant_prior = _dominant(prior)
    dominant_recent = _dominant(recent)
    shift_score = 1.0 - (sum(1 for label in recent if label == dominant_prior) / len(recent))

    if shift_score < sensitivity or dominant_recent == dominant_prior:
        return []

    severity = _severity_for_breach(_breach_ratio_above(shift_score, sensitivity))
    return [
        _make_trigger(
            "regime_shift_trigger",
            severity,
            _latest_mode(events),
            "portfolio",
            shift_score,
            sensitivity,
            f"Regime shifted from '{dominant_prior}' to '{dominant_recent}' (score {shift_score:.2f}).",
        )
    ]


def liquidity_warning_trigger(
    events: list[dict],
    max_liquidity_rejection_rate: float = 0.25,
    window: int = 100,
) -> list[dict]:
    windowed = events[-window:] if window > 0 else events
    if len(windowed) < 5:
        return []

    def action_of(event: dict) -> str | None:
        return (event.get("liquidity") or {}).get("recommended_action")

    total = len(windowed)
    rejections = [event for event in windowed if action_of(event) in _LIQUIDITY_REJECTION_ACTIONS]
    rejection_rate = len(rejections) / total
    if rejection_rate < max_liquidity_rejection_rate:
        return []

    mode = _latest_mode(windowed)
    severity = _severity_for_breach(_breach_ratio_above(rejection_rate, max_liquidity_rejection_rate))
    triggers = [
        _make_trigger(
            "liquidity_warning_trigger",
            severity,
            mode,
            "portfolio",
            rejection_rate,
            max_liquidity_rejection_rate,
            f"Liquidity rejection rate at {rejection_rate:.1%} over {total} observations.",
        )
    ]

    distinct_tickers = {event.get("ticker", "unknown") for event in windowed}
    if len(distinct_tickers) >= 3 and rejections:
        ticker_counts = Counter(event.get("ticker", "unknown") for event in rejections)
        top_ticker, top_count = ticker_counts.most_common(1)[0]
        if top_count / len(rejections) >= 0.5:
            ticker_rate = top_count / total
            triggers.append(
                _make_trigger(
                    "liquidity_warning_trigger",
                    severity,
                    mode,
                    top_ticker,
                    ticker_rate,
                    max_liquidity_rejection_rate,
                    f"{top_ticker} accounts for {top_count}/{len(rejections)} liquidity rejections.",
                )
            )

    return triggers


def risk_lock_trigger(
    events: list[dict],
    max_consecutive_locked_events: int = 20,
) -> list[dict]:
    if not events:
        return []

    def is_locked(event: dict) -> bool:
        return bool((event.get("portfolio") or {}).get("trade_lock_active"))

    mode = _latest_mode(events)
    triggers: list[dict] = []

    if len(events) >= 2 and not is_locked(events[-2]) and is_locked(events[-1]):
        triggers.append(
            _make_trigger(
                "risk_lock_trigger",
                "warning",
                mode,
                "portfolio",
                1.0,
                1.0,
                "Risk lock just activated.",
            )
        )

    run_length = 0
    for event in reversed(events):
        if is_locked(event):
            run_length += 1
        else:
            break

    if run_length >= max_consecutive_locked_events:
        triggers.append(
            _make_trigger(
                "risk_lock_trigger",
                "critical",
                mode,
                "portfolio",
                float(run_length),
                float(max_consecutive_locked_events),
                f"Risk lock has stayed active for {run_length} consecutive observations.",
            )
        )

    return triggers


def live_order_permission_blocked_trigger(
    events: list[dict],
    window: int = 100,
) -> list[dict]:
    """V2-22 deployment-health trigger: fires critical when mode=='live'
    but recent execution_notes are still 'simulated_*' - the order gate is
    silently blocking what should be a real order (misconfigured
    credentials/allow_live_orders flag/risk lock in a deployment that
    believes it's live). Unlike the model-quality triggers above, this is
    never retrain-eligible - see _NON_RETRAIN_TRIGGERS."""
    windowed = events[-window:] if window > 0 else events
    live_events = [event for event in windowed if event.get("mode") == "live"]
    if not live_events:
        return []

    blocked_count = sum(
        1 for event in live_events if str(event.get("execution_note") or "").startswith("simulated_")
    )
    if blocked_count == 0:
        return []

    return [
        _make_trigger(
            "live_order_permission_blocked_trigger",
            "critical",
            "live",
            "portfolio",
            float(blocked_count),
            0.0,
            f"{blocked_count}/{len(live_events)} recent live-mode events were simulated, not real orders - "
            "check broker credentials, allow_live_orders, and the risk lock.",
        )
    ]


def _topology_field_values(events: list[dict], window: int, field: str) -> list[float]:
    windowed = events[-window:] if window > 0 else events
    return [
        float(event["topology"][field])
        for event in windowed
        if isinstance(event.get("topology"), dict) and event["topology"].get(field) is not None
    ]


def topology_uncertainty_trigger(
    events: list[dict],
    window: int = 50,
    max_avg_uncertainty: float = 0.6,
    min_persistent_fraction: float = 0.6,
) -> list[dict]:
    """Fires when learned-topology uncertainty (topology.learned_topology's
    topology_uncertainty) stays elevated across the window - both the
    rolling average AND a minimum fraction of individually-breaching bars
    must clear the threshold, so one noisy bar never fires this alone."""
    uncertainties = _topology_field_values(events, window, "topology_uncertainty")
    if len(uncertainties) < 5:
        return []

    avg_uncertainty = statistics.mean(uncertainties)
    breach_fraction = sum(1 for value in uncertainties if value >= max_avg_uncertainty) / len(uncertainties)
    if avg_uncertainty < max_avg_uncertainty or breach_fraction < min_persistent_fraction:
        return []

    severity = _severity_for_breach(_breach_ratio_above(avg_uncertainty, max_avg_uncertainty))
    return [
        _make_trigger(
            "topology_uncertainty_trigger",
            severity,
            _latest_mode(events),
            "portfolio",
            avg_uncertainty,
            max_avg_uncertainty,
            f"Topology uncertainty averaged {avg_uncertainty:.2f} over {len(uncertainties)} observations "
            f"({breach_fraction:.0%} of bars above threshold {max_avg_uncertainty:.2f}).",
        )
    ]


def topology_regime_mismatch_trigger(
    events: list[dict],
    window: int = 50,
    mismatch_threshold: float = 0.5,
) -> list[dict]:
    """Fires when the deterministic per-asset regime_label disagrees with
    its cluster's dominant_regime_label for a persistent share of the
    window. The rate itself (over `window` observations) is the persistence
    guard - a single mismatched bar cannot push the rate above threshold."""
    windowed = events[-window:] if window > 0 else events
    mismatches = [
        event["topology"].get("regime_label") != event["topology"].get("cluster_dominant_regime_label")
        for event in windowed
        if isinstance(event.get("topology"), dict) and event["topology"].get("cluster_dominant_regime_label") is not None
    ]
    if len(mismatches) < 5:
        return []

    mismatch_rate = sum(1 for value in mismatches if value) / len(mismatches)
    if mismatch_rate < mismatch_threshold:
        return []

    severity = _severity_for_breach(_breach_ratio_above(mismatch_rate, mismatch_threshold))
    return [
        _make_trigger(
            "topology_regime_mismatch_trigger",
            severity,
            _latest_mode(windowed),
            "portfolio",
            mismatch_rate,
            mismatch_threshold,
            f"Topology/regime label mismatch in {mismatch_rate:.0%} of {len(mismatches)} observations "
            f"(threshold {mismatch_threshold:.0%}).",
        )
    ]


def cluster_drift_trigger(
    events: list[dict],
    window: int = 50,
    drift_threshold: float = 0.5,
    min_persistent_fraction: float = 0.6,
) -> list[dict]:
    """Fires when learned-neighbor-set drift (neighbor_shift_score) stays
    elevated across the window - persistence-guarded the same way as
    topology_uncertainty_trigger, so small bar-to-bar noise never fires."""
    shifts = _topology_field_values(events, window, "neighbor_shift_score")
    if len(shifts) < 5:
        return []

    avg_shift = statistics.mean(shifts)
    breach_fraction = sum(1 for value in shifts if value >= drift_threshold) / len(shifts)
    if avg_shift < drift_threshold or breach_fraction < min_persistent_fraction:
        return []

    severity = _severity_for_breach(_breach_ratio_above(avg_shift, drift_threshold))
    return [
        _make_trigger(
            "cluster_drift_trigger",
            severity,
            _latest_mode(events),
            "portfolio",
            avg_shift,
            drift_threshold,
            f"Cluster neighbor drift averaged {avg_shift:.2f} over {len(shifts)} observations "
            f"({breach_fraction:.0%} of bars above threshold {drift_threshold:.2f}).",
        )
    ]


def model_topology_disagreement_trigger(
    events: list[dict],
    window: int = 50,
    disagreement_threshold: float = 0.5,
    min_persistent_fraction: float = 0.6,
) -> list[dict]:
    """Fires when the learned topology model's cluster/regime read stays
    persistently at odds with the deterministic topology (topology_disagreement)."""
    disagreements = _topology_field_values(events, window, "topology_disagreement")
    if len(disagreements) < 5:
        return []

    avg_disagreement = statistics.mean(disagreements)
    breach_fraction = sum(1 for value in disagreements if value >= disagreement_threshold) / len(disagreements)
    if avg_disagreement < disagreement_threshold or breach_fraction < min_persistent_fraction:
        return []

    severity = _severity_for_breach(_breach_ratio_above(avg_disagreement, disagreement_threshold))
    return [
        _make_trigger(
            "model_topology_disagreement_trigger",
            severity,
            _latest_mode(events),
            "portfolio",
            avg_disagreement,
            disagreement_threshold,
            f"Learned/deterministic topology disagreement averaged {avg_disagreement:.2f} over "
            f"{len(disagreements)} observations ({breach_fraction:.0%} of bars above threshold "
            f"{disagreement_threshold:.2f}).",
        )
    ]


def trigger_frequency_spike(
    recent_triggers: list[dict],
    window_minutes: int = 60,
    baseline_window_minutes: int = 1440,
    spike_multiplier: float = 3.0,
    min_recent_count: int = 3,
) -> list[dict]:
    """Fires when the rate of *other* triggers firing spikes relative to
    their own recent baseline - a meta-trigger over trigger rows, not
    experience events. `recent_triggers` should already be scoped to
    roughly `baseline_window_minutes` of history (the caller/worker fetches
    that window from Postgres); this function only needs `min_recent_count`
    triggers inside the newest `window_minutes` slice AND a rate at least
    `spike_multiplier` times the whole-window baseline rate to fire, so a
    handful of unrelated triggers can't spike this on their own."""
    if not recent_triggers:
        return []

    now = max(_parse_created_at(trigger["created_at"]) for trigger in recent_triggers)
    recent_cutoff = now - timedelta(minutes=window_minutes)
    recent = [trigger for trigger in recent_triggers if _parse_created_at(trigger["created_at"]) >= recent_cutoff]
    if len(recent) < min_recent_count:
        return []

    recent_rate = len(recent) / max(window_minutes, 1)
    baseline_rate = max(len(recent_triggers) / max(baseline_window_minutes, 1), 1e-6)
    spike_threshold = baseline_rate * spike_multiplier
    if recent_rate < spike_threshold:
        return []

    severity = _severity_for_breach(_breach_ratio_above(recent_rate, spike_threshold))
    return [
        _make_trigger(
            "trigger_frequency_spike",
            severity,
            _latest_mode(recent_triggers),
            "portfolio",
            recent_rate,
            spike_threshold,
            f"Trigger frequency spiked to {recent_rate:.3f}/min over the last {window_minutes}m "
            f"(baseline {baseline_rate:.3f}/min, {len(recent)} recent triggers).",
        )
    ]


def evaluate_all_triggers(events: list[dict], config: dict, recent_triggers: list[dict] | None = None) -> dict:
    generated_at = _now_iso()
    enabled = bool(config.get("enabled", True))

    if not enabled:
        return {
            "generated_at": generated_at,
            "source_event_count": len(events),
            "enabled": False,
            "triggers": [],
            "summary": {
                "active_trigger_count": 0,
                "severity_distribution": {severity: 0 for severity in SEVERITIES},
                "retrain_candidate": False,
                "latest_trigger": None,
                "trigger_type_counts": {trigger_type: 0 for trigger_type in TRIGGER_TYPES},
            },
        }

    rolling_window = int(config.get("rolling_window", 100))
    triggers: list[dict] = []
    triggers += observation_count_trigger(events, interval=int(config.get("observation_interval", 100)))
    triggers += executed_trade_count_trigger(events, interval=int(config.get("trade_count_interval", 100)))
    triggers += drawdown_trigger(events, max_drawdown_threshold=float(config.get("max_drawdown_threshold", -0.10)))
    triggers += sustained_drawdown_trigger(
        events,
        max_drawdown_threshold=float(config.get("max_drawdown_threshold", -0.10)),
        consecutive_days=int(config.get("sustained_drawdown_days", 2)),
    )
    triggers += sharpe_degradation_trigger(
        events, min_sharpe=float(config.get("min_sharpe", 0.3)), window=rolling_window
    )
    triggers += win_rate_trigger(events, min_win_rate=float(config.get("min_win_rate", 0.45)), window=rolling_window)
    triggers += confidence_decay_trigger(
        events,
        decay_ratio_threshold=float(config.get("confidence_decay_ratio_threshold", 0.5)),
        instability_std_threshold=float(config.get("confidence_instability_std_threshold", 0.25)),
    )
    triggers += regime_shift_trigger(events, sensitivity=float(config.get("regime_shift_sensitivity", 0.6)))
    triggers += liquidity_warning_trigger(
        events,
        max_liquidity_rejection_rate=float(config.get("max_liquidity_rejection_rate", 0.25)),
        window=rolling_window,
    )
    triggers += risk_lock_trigger(
        events, max_consecutive_locked_events=int(config.get("max_consecutive_locked_events", 20))
    )
    triggers += live_order_permission_blocked_trigger(events, window=rolling_window)
    triggers += topology_uncertainty_trigger(
        events,
        window=rolling_window,
        max_avg_uncertainty=float(config.get("topology_uncertainty_threshold", 0.6)),
        min_persistent_fraction=float(config.get("topology_uncertainty_persistent_fraction", 0.6)),
    )
    triggers += topology_regime_mismatch_trigger(
        events,
        window=rolling_window,
        mismatch_threshold=float(config.get("topology_regime_mismatch_threshold", 0.5)),
    )
    triggers += cluster_drift_trigger(
        events,
        window=rolling_window,
        drift_threshold=float(config.get("cluster_drift_threshold", 0.5)),
        min_persistent_fraction=float(config.get("cluster_drift_persistent_fraction", 0.6)),
    )
    triggers += model_topology_disagreement_trigger(
        events,
        window=rolling_window,
        disagreement_threshold=float(config.get("model_topology_disagreement_threshold", 0.5)),
        min_persistent_fraction=float(config.get("model_topology_disagreement_persistent_fraction", 0.6)),
    )
    if recent_triggers is not None:
        triggers += trigger_frequency_spike(
            recent_triggers,
            window_minutes=int(config.get("trigger_frequency_spike_window_minutes", 60)),
            baseline_window_minutes=int(config.get("trigger_frequency_spike_baseline_minutes", 1440)),
            spike_multiplier=float(config.get("trigger_frequency_spike_multiplier", 3.0)),
            min_recent_count=int(config.get("trigger_frequency_spike_min_recent_count", 3)),
        )

    severity_distribution = {severity: 0 for severity in SEVERITIES}
    trigger_type_counts = {trigger_type: 0 for trigger_type in TRIGGER_TYPES}
    for trigger in triggers:
        severity_distribution[trigger["severity"]] = severity_distribution.get(trigger["severity"], 0) + 1
        trigger_type_counts[trigger["trigger_type"]] = trigger_type_counts.get(trigger["trigger_type"], 0) + 1

    latest_trigger = max(triggers, key=lambda trigger: trigger["created_at"]) if triggers else None

    return {
        "generated_at": generated_at,
        "source_event_count": len(events),
        "enabled": True,
        "triggers": triggers,
        "summary": {
            "active_trigger_count": len(triggers),
            "severity_distribution": severity_distribution,
            "retrain_candidate": any(trigger["retrain_candidate"] for trigger in triggers),
            "latest_trigger": latest_trigger,
            "trigger_type_counts": trigger_type_counts,
        },
    }
