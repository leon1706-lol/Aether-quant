"""Promotability of every model head and submodel in one table (V5.8.0, rule R-HEAD).

Each trainer already writes a verdict next to its metrics (rank heads: `backtest.<head>_ranking_quality.quality_status`,
regression heads: `magnitude_quality` / `volatility_quality`, experts: `quality_gate`), but they live in seven files and
nothing reads them together, so a non-promotable head (residual_rank_20d, the gating network at MCC 0.0097) could stay
in the decision path for releases. This module collects them, applies the gate each one already defines, and marks which
heads the live decision path consumes, so "promotable or removed" can be checked mechanically.

Pure: takes already-loaded JSON dicts. `load_head_metrics(ml_dir)` is the one loader.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PASSING_RANK_STATUSES = frozenset({"promotable", "watchlist"})
RANK_HEADS = ("rank_5d", "rank_20d", "sector_neutral_rank_20d", "residual_rank_5d", "residual_rank_20d", "beta_neutral_rank_20d")
DIRECTION_HEADS = ("direction", "direction_5d", "direction_20d")


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_head_metrics(ml_dir: Path) -> dict:
    """Reads every metrics artifact that exists under `ml_dir` (missing files -> absent keys)."""
    ml_dir = Path(ml_dir)
    names = {
        "baseline": "training_metrics.json",
        "multitask": "multitask_training_metrics.json",
        "sequence": "sequence_training_metrics.json",
        "gating": "gating_training_metrics.json",
        "experts": "expert_training_metrics.json",
        "rl_sizing": "rl_sizing_training_metrics.json",
        "rl_sizing_forex": "rl_sizing_forex_training_metrics.json",
        "topology": "topology_training_metrics.json",
    }
    loaded = {}
    for key, name in names.items():
        path = ml_dir / name
        if path.exists():
            try:
                loaded[key] = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                loaded[key] = {"_unreadable": True}
    return loaded


def _direction_row(model: str, head: str, metrics: dict, min_mcc: float, consumers: set[str]) -> dict | None:
    validation = (metrics.get("validation") or {}).get(head)
    backtest = (metrics.get("backtest") or {}).get(head)
    if not isinstance(validation, dict) and not isinstance(backtest, dict):
        return None
    validation_mcc = _finite((validation or {}).get("mcc"))
    backtest_mcc = _finite((backtest or {}).get("mcc"))
    passed = validation_mcc is not None and backtest_mcc is not None and validation_mcc > min_mcc and backtest_mcc > min_mcc
    return {
        "component": f"{model}.{head}", "kind": "direction", "metric": "mcc (validation / backtest)",
        "value": [validation_mcc, backtest_mcc], "threshold": f"> {min_mcc}", "passed": bool(passed),
        "in_decision_path": f"{model}.{head}" in consumers,
    }


def audit_heads(metrics: dict, *, consumers: set[str] | None = None, min_direction_mcc: float = 0.0) -> dict:
    """`metrics` is load_head_metrics()'s dict. `consumers` names the components the live path reads
    (e.g. {"multitask.rank_20d", "sequence.rank_5d", "gating"}); it only annotates the table."""
    consumers = set(consumers or ())
    rows: list[dict] = []
    for model in ("multitask", "sequence"):
        model_metrics = metrics.get(model)
        if not model_metrics:
            continue
        backtest = model_metrics.get("backtest") or {}
        for head in RANK_HEADS:
            quality = backtest.get(f"{head}_ranking_quality")
            if not isinstance(quality, dict):
                continue
            status = quality.get("quality_status")
            rows.append({
                "component": f"{model}.{head}", "kind": "rank", "metric": "ranking_quality", "value": status,
                "threshold": sorted(PASSING_RANK_STATUSES), "passed": status in PASSING_RANK_STATUSES,
                "failures": quality.get("failures", []), "in_decision_path": f"{model}.{head}" in consumers,
            })
        for head, key in (("magnitude", "magnitude_quality"), ("volatility", "volatility_quality")):
            quality = model_metrics.get(key)
            if isinstance(quality, dict):
                rows.append({
                    "component": f"{model}.{head}", "kind": "regression", "metric": "quality_status",
                    "value": quality.get("quality_status"), "threshold": ["stable", "watchlist"],
                    "passed": quality.get("quality_status") in {"stable", "watchlist"},
                    "failures": quality.get("failures", []), "in_decision_path": f"{model}.{head}" in consumers,
                })
        for head in DIRECTION_HEADS:
            row = _direction_row(model, head, model_metrics, min_direction_mcc, consumers)
            if row:
                rows.append(row)
    baseline = metrics.get("baseline")
    if baseline:
        row = _direction_row("baseline", "direction", {"validation": {"direction": baseline.get("validation")},
                                                       "backtest": {"direction": baseline.get("backtest")}},
                             min_direction_mcc, consumers)
        if row:
            rows.append(row)
    experts = (metrics.get("experts") or {}).get("experts") or {}
    disabled = set((metrics.get("experts") or {}).get("disabled_for_gating_experts") or [])
    for name, expert in sorted(experts.items()):
        gate = expert.get("quality_gate") or {}
        status = gate.get("quality_status") or expert.get("quality_status")
        rows.append({
            "component": f"expert.{name}", "kind": "expert", "metric": "quality_status",
            "value": status, "threshold": ["stable", "watchlist"],
            "passed": status in {"stable", "watchlist"} and name not in disabled,
            "failures": gate.get("failures", []), "in_decision_path": f"expert.{name}" in consumers and name not in disabled,
        })
    gating = metrics.get("gating")
    if gating:
        mcc = _finite((gating.get("backtest") or {}).get("mcc"))
        baseline_mcc = _finite(((baseline or {}).get("backtest") or {}).get("mcc"))
        passed = mcc is not None and mcc > min_direction_mcc and (baseline_mcc is None or mcc >= baseline_mcc)
        rows.append({
            "component": "gating", "kind": "gating", "metric": "backtest mcc vs baseline", "value": [mcc, baseline_mcc],
            "threshold": "> 0 and >= baseline", "passed": bool(passed), "in_decision_path": "gating" in consumers,
        })
    for key in ("rl_sizing", "rl_sizing_forex"):
        rl = metrics.get(key)
        if not rl:
            continue
        policy = _finite(rl.get("backtest_policy_expected_reward"))
        constant = _finite(rl.get("backtest_constant_action_1_0_expected_reward"))
        rows.append({
            "component": key, "kind": "rl", "metric": "backtest reward policy vs constant 1.0", "value": [policy, constant],
            "threshold": "policy > constant (R-RL half 1)", "passed": policy is not None and constant is not None and policy > constant,
            "in_decision_path": key in consumers,
        })
    failing_in_path = [row["component"] for row in rows if not row["passed"] and row["in_decision_path"]]
    return {
        "rows": rows,
        "num_components": len(rows),
        "num_passed": sum(1 for row in rows if row["passed"]),
        "failing": [row["component"] for row in rows if not row["passed"]],
        "failing_in_decision_path": failing_in_path,
    }
