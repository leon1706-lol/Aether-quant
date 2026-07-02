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
from datetime import datetime, timezone

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
)

_MODEL_QUALITY_TRIGGERS = {
    "drawdown_trigger",
    "sharpe_degradation_trigger",
    "win_rate_trigger",
    "confidence_decay_trigger",
    "regime_shift_trigger",
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
}

_LIQUIDITY_REJECTION_ACTIONS = {"block", "reduce_size"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if trigger_type == "risk_lock_trigger":
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


def evaluate_all_triggers(events: list[dict], config: dict) -> dict:
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
    triggers += drawdown_trigger(events, max_drawdown_threshold=float(config.get("max_drawdown_threshold", -0.10)))
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
