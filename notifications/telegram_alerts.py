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


def format_session_summary_alert(session_summary_event: dict) -> str:
    """Render a session_summary experience event as a Telegram digest.

    Reads the observation_summary sub-dict produced by
    experience/observation_metrics.py::compute_observation_summary() —
    recomputes nothing.
    """
    summary = session_summary_event.get("observation_summary") or {}
    win_loss = summary.get("simulated_win_loss") or {}
    session_return = session_summary_event.get("session_return", 0.0)

    lines = [
        f"\U0001f4ca Session summary — {session_summary_event.get('session_date', 'unknown date')}",
        f"Mode: {session_summary_event.get('mode', 'unknown')}",
        f"Equity: {session_summary_event.get('session_start_equity', 0.0):,.2f} -> "
        f"{session_summary_event.get('session_end_equity', 0.0):,.2f} ({session_return:+.2%})",
        f"Observations: {summary.get('count_observations', 0)}",
        f"Simulated win/loss: {win_loss.get('wins', 0)}/{win_loss.get('losses', 0)} "
        f"(win rate {win_loss.get('win_rate', 0.0):.1%})",
        f"Simulated Sharpe: {summary.get('simulated_sharpe', 0.0):.2f}",
        f"Simulated max drawdown: {summary.get('simulated_max_drawdown', 0.0):.2%}",
    ]
    return "\n".join(lines)
