"""The paper-to-live scorecard (V6.6.5, #352): every condition for live capital, measured, with its evidence and its date.

Six groups, each a few metrics with a threshold. A metric without evidence is **unknown, and unknown fails**: a scorecard is
ready only when every metric has been measured and passed. Stale evidence (a field test or a verification run older than
its limit) fails too. Thresholds are pre-set here and can be tightened in `config.json`'s `phase_v2.live_readiness`; the
scorecard reports, it never trades (`enforce_before_live` defaults to false, and main.py reads nothing else from it).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal

__all__ = ["GROUPS", "DEFAULT_THRESHOLDS", "ReadinessMetric", "Scorecard", "resolve_thresholds", "build_scorecard", "render_markdown", "live_mode_allowed"]

Status = Literal["pass", "fail", "unknown"]
GROUPS = ("edge", "paper", "safety", "operations", "code", "accounts")
DEFAULT_THRESHOLDS: dict[str, float] = {
    "forward_sessions_min": 60, "forward_alpha_t_min": 2.0, "book_dsr_min": 0.95, "round_pbo_max": 0.5,
    "paper_trading_days_min": 120, "paper_rebalances_min": 6,
    "field_test_max_age_days": 90, "max_total_drawdown_pct_max": 0.15,
    "backup_max_age_days": 7, "verification_max_age_days": 30, "mutation_score_min": 0.9,
}


@dataclass(frozen=True)
class ReadinessMetric:
    """One measured condition: its value, threshold and comparator, pass/fail/unknown, and where the evidence came from."""

    key: str
    group: str
    label: str
    value: Any
    threshold: str
    status: Status
    evidence: str
    measured_at: str | None = None


@dataclass(frozen=True)
class Scorecard:
    """Every metric for one account, `ready` only when all pass (unknown counts as fail), and the blocking keys."""

    ready: bool
    account: str
    generated_at: str
    metrics: tuple[ReadinessMetric, ...]
    blocking: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        counts = {status: sum(1 for metric in self.metrics if metric.status == status) for status in ("pass", "fail", "unknown")}
        return {"ready": self.ready, "account": self.account, "generated_at": self.generated_at, "counts": counts,
                "metrics": [asdict(metric) for metric in self.metrics], "blocking": list(self.blocking)}


def resolve_thresholds(raw: Mapping[str, Any] | None) -> dict[str, float]:
    """The defaults, each replaced by a finite number from config (`phase_v2.live_readiness.thresholds`)."""
    out = dict(DEFAULT_THRESHOLDS)
    for key, value in ((raw or {}).get("thresholds") or {}).items():
        if key in out and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            out[key] = float(value)
    return out


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _age_days(stamp: Any, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        day = date.fromisoformat(str(stamp)[:10])
    except ValueError:
        return None
    return float((now.date() - day).days)


def _metric(key: str, group: str, label: str, value: Any, threshold: str, passed: bool | None, evidence: str, measured_at: Any = None) -> ReadinessMetric:
    status: Status = "unknown" if passed is None else ("pass" if passed else "fail")
    return ReadinessMetric(key, group, label, value, threshold, status, evidence, str(measured_at) if measured_at else None)


def _at_least(value: Any, floor: float) -> bool | None:
    number = _number(value)
    return None if number is None else number >= floor


def _at_most(value: Any, ceiling: float) -> bool | None:
    number = _number(value)
    return None if number is None else number <= ceiling


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def build_scorecard(evidence: Mapping[str, Any], thresholds: Mapping[str, float] | None = None, *, now: datetime, account: str = "default") -> Scorecard:
    """The scorecard from `evidence` (see `execution/live_readiness_io.gather_evidence` for the keys). Pure."""
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    field_test = evidence.get("field_test") or {}
    verification = evidence.get("verification") or {}
    field_age, verification_age, backup_age = _age_days(field_test.get("date"), now), _age_days(verification.get("date"), now), _age_days(evidence.get("backup_date"), now)
    metrics = [
        _metric("forward_sessions", "edge", "Forward record sessions", evidence.get("forward_sessions"), f">= {limits['forward_sessions_min']:.0f}",
                _at_least(evidence.get("forward_sessions"), limits["forward_sessions_min"]), str(evidence.get("forward_source", "forward/generations.jsonl"))),
        _metric("forward_alpha_t", "edge", "Forward alpha t (HAC)", evidence.get("forward_alpha_t"), f">= {limits['forward_alpha_t_min']:.1f}",
                _at_least(evidence.get("forward_alpha_t"), limits["forward_alpha_t_min"]), "judge_candidate on the incumbent generation"),
        _metric("book_dsr", "edge", "Deflated Sharpe of the book", evidence.get("book_dsr"), f">= {limits['book_dsr_min']:.2f}",
                _at_least(evidence.get("book_dsr"), limits["book_dsr_min"]), str(evidence.get("book_dsr_source", "ml/evaluation/alpha_proof.json"))),
        _metric("round_pbo", "edge", "PBO of the latest research round", evidence.get("round_pbo"), f"< {limits['round_pbo_max']:.2f}",
                (lambda value: None if value is None else value < limits["round_pbo_max"])(_number(evidence.get("round_pbo"))), str(evidence.get("round_source", "-"))),
        _metric("paper_trading_days", "paper", "Paper trading days", evidence.get("paper_trading_days"), f">= {limits['paper_trading_days_min']:.0f}",
                _at_least(evidence.get("paper_trading_days"), limits["paper_trading_days_min"]), "aq evaluate --paper-check"),
        _metric("paper_rebalances", "paper", "Paper rebalances", evidence.get("paper_rebalances"), f">= {limits['paper_rebalances_min']:.0f}",
                _at_least(evidence.get("paper_rebalances"), limits["paper_rebalances_min"]), "aq evaluate --paper-check"),
        _metric("paper_bands", "paper", "Every paper metric inside its reference band", evidence.get("paper_bands_all_inside"), "all inside",
                _flag(evidence.get("paper_bands_all_inside")), "evaluation/paper_protocol.band_check"),
        _metric("field_test", "safety", "Field test (orders, trip, flatten, breach, restart, outages, accounts)",
                f"{field_test.get('passed')}/{field_test.get('total')}" if field_test else None, f"all, <= {limits['field_test_max_age_days']:.0f} days old",
                None if not field_test else bool(field_test.get("all_passed")) and field_age is not None and field_age <= limits["field_test_max_age_days"],
                str(field_test.get("path", "ml/evaluation/field_test/")), field_test.get("date")),
        _metric("kill_switch_enabled", "safety", "Kill switch enabled", evidence.get("kill_switch_enabled"), "true", _flag(evidence.get("kill_switch_enabled")), "phase_v2.risk.kill_switch.enabled"),
        _metric("reconciliation_trips", "safety", "A reconciliation breach trips the kill switch", evidence.get("reconciliation_trips_kill_switch"), "true",
                _flag(evidence.get("reconciliation_trips_kill_switch")), "phase_v2.reconciliation.trips_kill_switch"),
        _metric("max_total_drawdown", "safety", "Live total-drawdown limit", evidence.get("max_total_drawdown_pct"), f"<= {limits['max_total_drawdown_pct_max']:.2f}",
                _at_most(evidence.get("max_total_drawdown_pct"), limits["max_total_drawdown_pct_max"]), "phase_v2.live.max_allowed_total_drawdown_pct"),
        _metric("secrets", "operations", "Broker secrets resolve from a file, Docker secret or keyring", evidence.get("secrets_detail"), "all, stored safely",
                _flag(evidence.get("secrets_all_safe")), "aq secrets status"),
        _metric("postgres_dsn", "operations", "Postgres password is not the published default", evidence.get("postgres_dsn_safe"), "true",
                _flag(evidence.get("postgres_dsn_safe")), "execution.live_credentials.postgres_dsn_is_live_safe"),
        _metric("audit_chain", "operations", "Audit chain verifies", evidence.get("audit_chain_valid"), "true", _flag(evidence.get("audit_chain_valid")), "visualization/grafana/audit_log.json"),
        _metric("alerts", "operations", "Telegram alerts configured", evidence.get("telegram_configured"), "true", _flag(evidence.get("telegram_configured")), "AETHER_TELEGRAM_*"),
        _metric("backup", "operations", "Postgres backup", evidence.get("backup_date"), f"<= {limits['backup_max_age_days']:.0f} days old",
                None if backup_age is None else backup_age <= limits["backup_max_age_days"], "scripts/backup_postgres.py", evidence.get("backup_date")),
        _metric("image_digest", "operations", "Deployed image digest recorded", evidence.get("image_digest"), "recorded",
                None if evidence.get("image_digest") is None else bool(evidence.get("image_digest")), "state/deploy/image_digest.txt"),
        _metric("verification", "code", "Last full verification green", verification.get("summary"), f"all pass, <= {limits['verification_max_age_days']:.0f} days old",
                None if not verification else bool(verification.get("all_passed")) and verification_age is not None and verification_age <= limits["verification_max_age_days"],
                str(verification.get("path", "-")), verification.get("date")),
        _metric("mutation_score", "code", "Mutation kill rate of the safety modules", evidence.get("mutation_score"), f">= {limits['mutation_score_min']:.2f}",
                _at_least(evidence.get("mutation_score"), limits["mutation_score_min"]), str(evidence.get("mutation_source", "-"))),
        _metric("accounts_valid", "accounts", "Account registry valid (overrides only tighten)", evidence.get("accounts_valid"), "true", _flag(evidence.get("accounts_valid")), "aq accounts validate"),
        _metric("live_account", "accounts", "The account is a real brokerage with capital set", evidence.get("live_account_detail"), "broker != paper, capital_usd set",
                _flag(evidence.get("live_account_ok")), "accounts.json"),
    ]
    blocking = tuple(f"{metric.label}: {metric.status}" for metric in metrics if metric.status != "pass")
    return Scorecard(ready=not blocking, account=account, generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"), metrics=tuple(metrics), blocking=blocking)


def render_markdown(scorecard: Scorecard) -> str:
    """The scorecard as a Markdown table (the docs' generated block and `aq live-readiness --markdown`)."""
    def show(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.3g}"
        return str(value).replace("|", "/")

    counts = scorecard.to_dict()["counts"]
    head = (f"**{'READY' if scorecard.ready else 'NOT READY'}** for live capital (account `{scorecard.account}`, {scorecard.generated_at}): "
            f"{counts['pass']} pass, {counts['fail']} fail, {counts['unknown']} unknown. Unknown counts as fail.")
    rows = ["| Group | Check | Measured | Needs | Status |", "|---|---|---|---|---|"]
    marks = {"pass": "pass", "fail": "**fail**", "unknown": "**unknown**"}
    for metric in scorecard.metrics:
        rows.append(f"| {metric.group} | {metric.label} | {show(metric.value)} | {metric.threshold} | {marks[metric.status]} |")
    return head + "\n\n" + "\n".join(rows) + "\n"


def live_mode_allowed(scorecard_doc: Mapping[str, Any] | None, *, enforce: bool) -> bool:
    """With `phase_v2.live_readiness.enforce_before_live` on, live mode needs the last written scorecard to be ready."""
    if not enforce:
        return True
    return bool(scorecard_doc) and scorecard_doc.get("ready") is True
