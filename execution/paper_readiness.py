"""Pure, Lean-free paper/live broker-readiness gating (Phase V2-21/V2-22).

`execution/order_gate.py::resolve_order_permission()` already implements the
correct mode -> real-vs-simulated decision table, but the `broker_config_present`
flag it depends on used to be `bool(self.paper_brokerage)` in `main.py` - a
string that is never empty by construction, so the check was a no-op. This
module is what actually decides whether that flag should be True, for both
`paper` mode (Lean's built-in PaperBrokerage, no real credentials needed) and
`live` mode (V2-22, real broker credentials).

No imports from AlgorithmImports/QCAlgorithm/psycopg live here on purpose -
see execution/paper_readiness_io.py for the IO layer that feeds these
functions, and execution/paper_readiness_report.py for the offline report
that additionally evaluates observation-mode readiness.
"""

from __future__ import annotations

_PAPER_REASON_ALL_CONFIRMED = "paper_broker_config_confirmed"
_PAPER_REASON_MISSING_BROKERAGE = "paper_broker_config_missing_brokerage"
_PAPER_REASON_MISSING_DATA_PROVIDER = "paper_broker_config_missing_live_data_provider"
_PAPER_REASON_MISSING_MANUAL_REVIEW = "paper_broker_config_missing_manual_review"

_LIVE_REASON_ALL_CONFIRMED = "live_broker_config_confirmed"
_LIVE_REASON_PAPER_NOT_READY = "live_broker_config_paper_corridor_not_ready"
_LIVE_REASON_MISSING_CREDENTIALS = "live_broker_config_missing_credentials"
_LIVE_REASON_RISK_POSTURE_UNSAFE = "live_broker_config_risk_posture_unsafe"
_LIVE_REASON_UNSAFE_DB_PASSWORD = "live_broker_config_unsafe_db_password"


def evaluate_paper_broker_config(paper_trading_config: dict) -> tuple[bool, str]:
    """mode='paper' gate. All three must be true:
    - brokerage is a non-empty known value
    - live_data_provider_configured (human-set attestation - a live market
      data feed is required for Lean's live-paper environment even though
      PaperBrokerage itself needs no broker credentials)
    - manual_review_confirmed (human-set attestation, replaces the old
      phase6.paper_trading.ready_for_live_paper stub)
    """
    if not str(paper_trading_config.get("brokerage", "")).strip():
        return False, _PAPER_REASON_MISSING_BROKERAGE
    if not bool(paper_trading_config.get("live_data_provider_configured", False)):
        return False, _PAPER_REASON_MISSING_DATA_PROVIDER
    if not bool(paper_trading_config.get("manual_review_confirmed", False)):
        return False, _PAPER_REASON_MISSING_MANUAL_REVIEW
    return True, _PAPER_REASON_ALL_CONFIRMED


def evaluate_live_risk_posture(risk_config: dict, live_config: dict) -> tuple[bool, str]:
    """Sanity ceiling for mode='live' - not a redesign of the drawdown
    circuit breaker, just a guard against live mode running with an
    accidentally-loose (or disabled) risk config that was fine for
    paper/observation but is unacceptable once real capital is at risk."""
    max_daily_drawdown_pct = float(risk_config.get("max_daily_drawdown_pct", 1.0))
    max_total_drawdown_pct = float(risk_config.get("max_total_drawdown_pct", 1.0))
    liquidate_on_risk_breach = bool(risk_config.get("liquidate_on_risk_breach", False))

    allowed_daily = float(live_config.get("max_allowed_daily_drawdown_pct", 0.0))
    allowed_total = float(live_config.get("max_allowed_total_drawdown_pct", 0.0))

    if not liquidate_on_risk_breach:
        return False, _LIVE_REASON_RISK_POSTURE_UNSAFE
    if max_daily_drawdown_pct > allowed_daily:
        return False, _LIVE_REASON_RISK_POSTURE_UNSAFE
    if max_total_drawdown_pct > allowed_total:
        return False, _LIVE_REASON_RISK_POSTURE_UNSAFE
    return True, _LIVE_REASON_ALL_CONFIRMED


def evaluate_live_broker_config(
    paper_trading_config: dict,
    live_credentials_present: bool,
    risk_config: dict | None = None,
    live_config: dict | None = None,
    postgres_dsn: str | None = None,
) -> tuple[bool, str]:
    """mode='live' gate (V2-22). You cannot go straight to live without a
    validated paper corridor - the paper check must also pass - AND real
    broker credentials must be present AND (if risk/live config supplied)
    the live risk posture must be safe AND (if a Postgres DSN is supplied) it
    must not still use the published dev-default password.

    `postgres_dsn` is optional and defaults to None (unchecked) so existing
    callers/tests are unaffected; main.py threads the real DSN through so a
    live run against the public default password fails closed."""
    paper_ready, paper_reason = evaluate_paper_broker_config(paper_trading_config)
    if not paper_ready:
        return False, _LIVE_REASON_PAPER_NOT_READY

    if not live_credentials_present:
        return False, _LIVE_REASON_MISSING_CREDENTIALS

    if postgres_dsn is not None:
        from execution.live_credentials import postgres_dsn_is_live_safe

        if not postgres_dsn_is_live_safe(postgres_dsn):
            return False, _LIVE_REASON_UNSAFE_DB_PASSWORD

    if risk_config is not None and live_config is not None:
        risk_ok, _ = evaluate_live_risk_posture(risk_config, live_config)
        if not risk_ok:
            return False, _LIVE_REASON_RISK_POSTURE_UNSAFE

    return True, _LIVE_REASON_ALL_CONFIRMED


def evaluate_broker_config(
    mode: str,
    paper_trading_config: dict,
    live_credentials_present: bool = False,
    risk_config: dict | None = None,
    live_config: dict | None = None,
    postgres_dsn: str | None = None,
) -> tuple[bool, str]:
    """Single entrypoint main.py._order_permission() calls regardless of
    mode - dispatches to the two functions above. Any mode other than
    'live' (including 'backtest'/'observation', where the result is unused
    since resolve_order_permission() never consults broker_config_present
    for those modes) goes through the paper path."""
    if mode == "live":
        return evaluate_live_broker_config(
            paper_trading_config,
            live_credentials_present,
            risk_config,
            live_config,
            postgres_dsn,
        )
    return evaluate_paper_broker_config(paper_trading_config)


def evaluate_observation_readiness(summary: dict, thresholds: dict) -> dict:
    """Turns 4 of the 5 bullets in development/infrastructure.md's "Bereit
    fuer Paper Trading?" checklist into code, given an already-computed
    observation summary (experience.observation_metrics.compute_observation_summary()
    output) and threshold config. The 5th bullet (manual review of trade
    history for plausible entry/exit prices) is deliberately NOT automated -
    it stays a human judgment call, surfaced via paper_trading_config's
    manual_review_confirmed flag (see evaluate_paper_broker_config above).
    """
    min_observations = int(thresholds.get("min_observations", 500))
    min_simulated_sharpe = float(thresholds.get("min_simulated_sharpe", 0.3))
    max_simulated_drawdown_floor = float(thresholds.get("max_simulated_drawdown_floor", -0.15))
    max_single_rejection_reason_share = float(thresholds.get("max_single_rejection_reason_share", 0.5))

    count_observations = int(summary.get("count_observations", 0))
    simulated_sharpe = float(summary.get("simulated_sharpe", 0.0))
    simulated_max_drawdown = float(summary.get("simulated_max_drawdown", 0.0))
    rejected_by_reason = summary.get("rejected_by_reason") or {}
    total_rejections = sum(rejected_by_reason.values())
    top_rejection_share = (max(rejected_by_reason.values()) / total_rejections) if total_rejections > 0 else 0.0

    checks = {
        "observation_count": {
            "pass": count_observations >= min_observations,
            "value": count_observations,
            "threshold": min_observations,
        },
        "simulated_sharpe": {
            "pass": simulated_sharpe >= min_simulated_sharpe,
            "value": simulated_sharpe,
            "threshold": min_simulated_sharpe,
        },
        "simulated_max_drawdown": {
            "pass": simulated_max_drawdown >= max_simulated_drawdown_floor,
            "value": simulated_max_drawdown,
            "threshold": max_simulated_drawdown_floor,
        },
        "dominant_rejection_reason": {
            "pass": top_rejection_share <= max_single_rejection_reason_share,
            "value": top_rejection_share,
            "threshold": max_single_rejection_reason_share,
        },
    }

    blocking_reasons = [name for name, check in checks.items() if not check["pass"]]

    return {
        "ready": len(blocking_reasons) == 0,
        "checks": checks,
        "blocking_reasons": blocking_reasons,
    }
