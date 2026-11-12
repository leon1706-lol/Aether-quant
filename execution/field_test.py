"""The field test without a broker (V6.6.5, #351): drive the safety paths of a real `main.py` in Lean's paper brokerage,
and judge what the run recorded.

A field test needs three keys turned at once: `phase_v2.diagnostics.field_test.enabled: true` in the run's config, the
environment variable `AQ_FIELD_TEST=1` in its container, and a runtime mode that can never reach real money (`paper` or
`observation`, with `allow_live_orders` false). Then:

- **At `order_after_bars`:** it hands `target_weights` to the target-weights path's own `_apply_target_row`, standing in
  for the decision a weekday's equity close would bring.
- **From `drift_after_bars`:** it adds `drift_weight` of `drift_symbol` to the holdings reconciliation reads.
- **From `shock_after_bars`:** it reports a drawdown velocity above the kill switch's limit.

Everything else is the real code path: the orders, the paper brokerage's fills, the trip, the flatten, the audit chain,
restarts and outages. `main.py` writes `FIELD_TEST ...` lines to the engine log (`field_test_log_line`), and
`judge_field_test` turns the run's evidence into pass/fail checks. It proves plumbing, never edge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "FieldTestPlan", "CHECKS", "LOG_PREFIX", "resolve_field_test_plan", "field_test_allowed", "field_test_target", "inject_metrics",
    "inject_reconciliation_drift", "field_test_log_line", "parse_field_test_log", "judge_field_test",
]
LOG_PREFIX = "FIELD_TEST"

CHECKS: tuple[str, ...] = (
    "orders_submitted", "orders_filled", "kill_switch_tripped", "flat_after_trip", "reconciliation_breach_detected", "restart_restored",
    "outages_survived", "audit_chain_valid", "accounts_isolated",
)


@dataclass(frozen=True)
class FieldTestPlan:
    """When and how hard to push. Bars count from the algorithm's first `on_data`."""

    enabled: bool = False
    shock_after_bars: int = 0
    drawdown_shock_pct: float = 0.0
    drift_after_bars: int = 0
    drift_symbol: str = ""
    drift_weight: float = 0.0
    order_after_bars: int = 0
    target_weights: tuple[tuple[str, float], ...] = ()


def resolve_field_test_plan(raw: Mapping[str, Any] | None) -> FieldTestPlan:
    """The plan from `phase_v2.diagnostics.field_test`; absent or malformed means disabled."""
    if not isinstance(raw, Mapping) or not raw.get("enabled"):
        return FieldTestPlan()
    try:
        weights = raw.get("target_weights") or {}
        return FieldTestPlan(
            enabled=True, shock_after_bars=max(int(raw.get("shock_after_bars", 0)), 0), drawdown_shock_pct=float(raw.get("drawdown_shock_pct", 0.0)),
            drift_after_bars=max(int(raw.get("drift_after_bars", 0)), 0), drift_symbol=str(raw.get("drift_symbol", "")), drift_weight=float(raw.get("drift_weight", 0.0)),
            order_after_bars=max(int(raw.get("order_after_bars", 0)), 0),
            target_weights=tuple(sorted((str(ticker), float(weight)) for ticker, weight in dict(weights).items())),
        )
    except (TypeError, ValueError):
        return FieldTestPlan()


PAPER_BROKERAGE = "lean_paper_brokerage"


def field_test_allowed(plan: FieldTestPlan, *, runtime_mode: str, paper_brokerage: str, env_flag: str | None) -> bool:
    """True only for an enabled plan, `AQ_FIELD_TEST=1`, and a run that cannot reach real money: observation (no orders at all),
    or paper on Lean's own paper brokerage (`phase_v2.paper_trading.brokerage`). Never live, whatever else is set."""
    if not plan.enabled or env_flag != "1":
        return False
    return runtime_mode == "observation" or (runtime_mode == "paper" and str(paper_brokerage).strip() == PAPER_BROKERAGE)


def field_test_target(plan: FieldTestPlan, bar_index: int) -> dict[str, float] | None:
    """The target row to apply on exactly bar `order_after_bars`, else None (one decision per run)."""
    if not plan.enabled or not plan.target_weights or plan.order_after_bars <= 0 or bar_index != plan.order_after_bars:
        return None
    return {ticker: weight for ticker, weight in plan.target_weights}


def field_test_log_line(event: str, bar_index: int, **fields: object) -> str:
    """`FIELD_TEST event=<event> bar=<n> key=value ...`: one engine-log line the report parses."""
    extra = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    return f"{LOG_PREFIX} event={event} bar={int(bar_index)}" + (f" {extra}" if extra else "")


def parse_field_test_log(text: str) -> list[dict[str, str]]:
    """Every `FIELD_TEST` line of an engine log as a dict of its fields."""
    events = []
    for line in text.splitlines():
        index = line.find(LOG_PREFIX + " ")
        if index < 0:
            continue
        fields = dict(part.split("=", 1) for part in line[index + len(LOG_PREFIX) + 1:].split() if "=" in part)
        if "event" in fields:
            events.append(fields)
    return events


def inject_metrics(runtime_metrics: Mapping[str, Any], plan: FieldTestPlan, bar_index: int) -> dict[str, Any]:
    """The kill switch's inputs, with the drawdown shock from `shock_after_bars` on (a copy; the input is not touched)."""
    out = dict(runtime_metrics)
    if plan.enabled and plan.drawdown_shock_pct > 0.0 and bar_index >= plan.shock_after_bars > 0:
        current = out.get("drawdown_velocity_pct_per_bar")
        out["drawdown_velocity_pct_per_bar"] = max(float(current) if isinstance(current, (int, float)) else 0.0, float(plan.drawdown_shock_pct))
        out["field_test_injected"] = True
    return out


def inject_reconciliation_drift(actual_by_symbol: Mapping[str, float], plan: FieldTestPlan, bar_index: int) -> dict[str, float]:
    """The holdings reconciliation compares, with the drift from `drift_after_bars` on (a copy)."""
    out = {str(key): float(value) for key, value in actual_by_symbol.items()}
    if plan.enabled and plan.drift_symbol and plan.drift_weight and bar_index >= plan.drift_after_bars > 0:
        out[plan.drift_symbol] = out.get(plan.drift_symbol, 0.0) + float(plan.drift_weight)
    return out


def _check(passed: bool | None, detail: str) -> dict[str, Any]:
    return {"pass": bool(passed) if passed is not None else False, "status": "pass" if passed else ("not_run" if passed is None else "fail"), "detail": detail}


def judge_field_test(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Pass/fail per check from a run's evidence (`scripts/lean_smoke/field_test.py` collects it from the engine
    logs, the result JSON, the audit chain and the services log). A check without evidence is `not_run`, which fails."""
    runs: Sequence[Mapping[str, Any]] = evidence.get("runs", []) or []
    first = runs[0] if runs else {}
    orders = int(first.get("orders_submitted", 0) or 0)
    fills = int(first.get("orders_filled", 0) or 0)
    trip_bar, shock_bar = first.get("kill_switch_trip_bar"), first.get("shock_bar")
    checks = {
        "orders_submitted": _check(orders >= 1 if runs else None, f"{orders} orders submitted to the paper brokerage"),
        "orders_filled": _check(fills >= 1 if runs else None, f"{fills} fills"),
        "kill_switch_tripped": _check(
            (trip_bar is not None and shock_bar is not None and 0 <= int(trip_bar) - int(shock_bar) <= 3) if runs else None,
            f"shock at bar {shock_bar}, trip at bar {trip_bar}",
        ),
        "flat_after_trip": _check(
            (first.get("gross_after_trip") is not None and float(first["gross_after_trip"]) <= 1e-6) if runs else None,
            f"strategy exposure after the trip (the T-bill sweep is cash, as in the lock's liquidation): {first.get('gross_after_trip')}",
        ),
        "reconciliation_breach_detected": _check(
            bool(first.get("reconciliation_breach")) and bool(first.get("reconciliation_audit_event")) if runs else None,
            "breach seen in state.json and an audit event written" if first.get("reconciliation_audit_event") else "no breach event",
        ),
        "restart_restored": _check(
            bool(evidence.get("restart", {}).get("started")) and not evidence.get("restart", {}).get("reconciliation_breach_on_start", True)
            if evidence.get("restart") else None,
            "second run started on the same project and its first reconciliation matched",
        ),
        "outages_survived": _check(
            all(bool(item.get("engine_alive_after")) for item in evidence.get("outages", [])) if evidence.get("outages") else None,
            ", ".join(f"{item.get('service')}: {'up' if item.get('engine_alive_after') else 'DOWN'}" for item in evidence.get("outages", [])),
        ),
        "audit_chain_valid": _check(evidence.get("audit_chain_valid") if "audit_chain_valid" in evidence else None, f"{evidence.get('audit_entries', 0)} entries"),
        "accounts_isolated": _check(
            (len(set(evidence.get("account_ids_in_audit", []))) >= 2 and bool(evidence.get("state_dirs_distinct"))) if "account_ids_in_audit" in evidence else None,
            f"accounts in the audit chain: {sorted(set(evidence.get('account_ids_in_audit', [])))}",
        ),
    }
    passed = [name for name in CHECKS if checks[name]["pass"]]
    return {"checks": checks, "passed": len(passed), "total": len(CHECKS), "all_passed": len(passed) == len(CHECKS),
            "note": "Plumbing on Lean's paper brokerage with a fake feed. It proves no edge and no real-broker behaviour (#338, #192)."}
