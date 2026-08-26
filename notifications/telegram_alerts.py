"""Pure Telegram alert gating + formatting (Phase V2-19).

Mirrors experience/observation_metrics.py's and performance/triggers.py's
design: every function here operates on plain dicts already produced
elsewhere (a performance_triggers row from performance/postgres_triggers.py,
or a session_summary event from experience/redis_queue.py's
build_session_summary_event()) — nothing here recomputes a metric, it only
decides whether to alert and how to render the message. No Postgres/Telegram/
network dependency lives here; see notifications/postgres_telegram.py for the
I/O layer and notifications/telegram_client.py for the outbound HTTP call.
"""

from __future__ import annotations

SEVERITY_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "\U0001f6a8"}
_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def should_alert_trigger(trigger: dict, min_severity: str = "warning") -> bool:
    """True if trigger["severity"] clears min_severity (info < warning < critical)."""
    trigger_rank = _SEVERITY_RANK.get(trigger.get("severity"), 0)
    threshold_rank = _SEVERITY_RANK.get(min_severity, 1)
    return trigger_rank >= threshold_rank


def format_trigger_alert(trigger: dict) -> str:
    """Render a performance_triggers row as a Telegram message.

    Renders fields performance/triggers.py already computed (message,
    recommended_action) — recomputes nothing.
    """
    emoji = SEVERITY_EMOJI.get(trigger.get("severity"), "")
    lines = [
        f"{emoji} {trigger.get('trigger_type', 'trigger')} ({trigger.get('severity', 'unknown')})",
        trigger.get("message", ""),
        f"Scope: {trigger.get('scope', 'portfolio')} | Mode: {trigger.get('mode', 'unknown')}",
        f"Recommended action: {trigger.get('recommended_action', 'none')}",
    ]
    return "\n".join(line for line in lines if line)


def _num(value, default: float = 0.0) -> float:
    """V5.4.7 (development/Problems.md #124): an explicit JSONB null (a
    key PRESENT with value None) previously crashed every f-string format
    below - `.get(key, default)` only covers a MISSING key - and the
    worker's frozen watermark then refetched the poison row forever,
    permanently blocking ALL alerts. Coerce anything non-numeric to the
    default instead."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_session_summary_alert(session_summary_event: dict) -> str:
    """Render a session_summary experience event as a Telegram digest.

    Reads the observation_summary sub-dict produced by
    experience/observation_metrics.py::compute_observation_summary() —
    recomputes nothing.
    """
    summary = session_summary_event.get("observation_summary") or {}
    win_loss = summary.get("simulated_win_loss") or {}
    session_return = _num(session_summary_event.get("session_return"))
    win_rate = _num(win_loss.get("win_rate"))
    simulated_sharpe = _num(summary.get("simulated_sharpe"))
    simulated_max_drawdown = _num(summary.get("simulated_max_drawdown"))

    lines = [
        f"\U0001f4ca Session summary — {session_summary_event.get('session_date', 'unknown date')}",
        f"Mode: {session_summary_event.get('mode', 'unknown')}",
        f"Equity: {_num(session_summary_event.get('session_start_equity')):,.2f} -> "
        f"{_num(session_summary_event.get('session_end_equity')):,.2f} ({session_return:+.2%})",
        f"Observations: {_num(summary.get('count_observations')):.0f}",
        f"Simulated win/loss: {_num(win_loss.get('wins')):.0f}/{_num(win_loss.get('losses')):.0f} "
        f"(win rate {win_rate:.1%})",
        f"Simulated Sharpe: {simulated_sharpe:.2f}",
        f"Simulated max drawdown: {simulated_max_drawdown:.2%}",
    ]
    return "\n".join(lines)
