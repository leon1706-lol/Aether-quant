"""R-LEAN13 (V6.4.0, Problems #221 / #225): is a confirming Lean run of an adopted change kept? Pure given two statistics dicts.

The adopted book (10-session rebalance, 20-session hold, crypto core only) was decided on the offline simulator, which tracks Lean at a
daily correlation of ~0.7. One Lean run (BT6) confirms or reverts it, judged against the run that differs only by the change (BT5):

    (a) the strategy's Sharpe without a risk-free rate (T-bill sweep taken out) is not worse than the baseline's by more than 0.10,
    (b) the portfolio's maximum drawdown is not worse than the baseline's by more than 1 percentage point,
    (c) the engine log shows a complete run: statistics written, the interpreter teardown reached, and no model-inference failure.
        (The teardown TIMEOUT is the PC's, Problems #104/#204, and is reported, not judged.)

R-LEAN14 (V6.4.2, `--rule superiority`) adopts a change on Lean evidence instead of confirming one: clause (a) becomes "better
than the baseline by at least the margin" (0.10), (b) and (c) are unchanged.

Each run's statistics use the config it ran with (`ml/evaluation/run_configs/<run folder>.json`), the root config.json only
when no frozen copy exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MAX_SHARPE_LOSS = 0.10
MAX_DRAWDOWN_WORSENING = 0.01  # fraction of NAV: 1 percentage point


def _row(stats: dict[str, Any], section: str, metric: str, column: str):
    for row in (stats.get("sections") or {}).get(section) or []:
        if row.get("metric") == metric:
            return row.get(column)
    return None


def strategy_sharpe(stats: dict[str, Any]) -> Any:
    """The strategy's annualised Sharpe (no risk-free rate) as the Lean report's statistics table prints it."""
    return _row(stats, "efficiency", "Annualized Sharpe ratio (no risk-free rate)", "strategy")


def max_drawdown(stats: dict[str, Any]) -> Any:
    """The portfolio's maximum drawdown as the Lean report's statistics table prints it."""
    return _row(stats, "runs", "Maximum drawdown", "portfolio")


def engine_log_status(engine_log_text: str) -> dict[str, Any]:
    """What a Lean engine log says about a run: whether teardown was reached, inference failures and a timed-out teardown."""
    return {
        "teardown_reached": bool(re.search(r"PythonInitializer\.Shutdown\(\): start", engine_log_text)),
        "inference_failures": len(re.findall(r"inference failed", engine_log_text)),
        "teardown_timed_out": "Operation timed out" in engine_log_text or "Failed to shutdown python" in engine_log_text,
    }


def r_lean13(baseline: dict[str, Any], candidate: dict[str, Any], candidate_engine_log: str) -> dict[str, Any]:
    """{"checks": {...}, "keep": bool, "values": {...}}; a value that cannot be read fails its clause."""
    base_sharpe, new_sharpe = strategy_sharpe(baseline), strategy_sharpe(candidate)
    base_drawdown, new_drawdown = max_drawdown(baseline), max_drawdown(candidate)
    log = engine_log_status(candidate_engine_log)
    checks = {
        "strategy_sharpe_within_0.10": None not in (base_sharpe, new_sharpe) and new_sharpe >= base_sharpe - MAX_SHARPE_LOSS,
        "max_drawdown_within_1pp": None not in (base_drawdown, new_drawdown) and new_drawdown <= base_drawdown + MAX_DRAWDOWN_WORSENING,
        "complete_run_no_inference_failure": candidate.get("status") == "OK" and log["teardown_reached"] and log["inference_failures"] == 0,
    }
    return {
        "checks": checks, "keep": all(checks.values()),
        "values": {"baseline_strategy_sharpe": base_sharpe, "candidate_strategy_sharpe": new_sharpe,
                   "baseline_max_drawdown": base_drawdown, "candidate_max_drawdown": new_drawdown, "engine_log": log},
    }


def r_lean14(baseline: dict[str, Any], candidate: dict[str, Any], candidate_engine_log: str, margin: float = MAX_SHARPE_LOSS) -> dict[str, Any]:
    """R-LEAN13 with clause (a) turned into superiority: the strategy Sharpe must beat the baseline's by `margin`."""
    result = r_lean13(baseline, candidate, candidate_engine_log)
    base_sharpe, new_sharpe = result["values"]["baseline_strategy_sharpe"], result["values"]["candidate_strategy_sharpe"]
    checks = dict(result["checks"])
    checks.pop("strategy_sharpe_within_0.10")
    checks = {f"strategy_sharpe_above_by_{margin:.2f}": None not in (base_sharpe, new_sharpe) and new_sharpe >= base_sharpe + margin,
              **checks}
    return dict(result, checks=checks, keep=all(checks.values()))


RULES = {"non_inferiority": ("R-LEAN13", r_lean13), "superiority": ("R-LEAN14", r_lean14)}


def run_config(run_dir: Path, root: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    """The config a run was frozen with (`ml/evaluation/run_configs/<folder>.json`), else `fallback`."""
    frozen = Path(root) / "ml" / "evaluation" / "run_configs" / f"{Path(run_dir).name}.json"
    return json.loads(frozen.read_text(encoding="utf-8")) if frozen.exists() else fallback


def verdict_for_run_dirs(baseline_dir: Path, candidate_dir: Path, config: dict[str, Any], root: Path, rule: str = "non_inferiority",
                         margin: float = MAX_SHARPE_LOSS) -> dict[str, Any]:
    """Statistics of both run folders (`backtest_statistics.compute_for_run_dir`, each with its own frozen config) and the
    candidate's engine log."""
    from evaluation.backtest_statistics import compute_for_run_dir

    baseline = compute_for_run_dir(Path(baseline_dir), run_config(baseline_dir, root, config), Path(root))
    candidate = compute_for_run_dir(Path(candidate_dir), run_config(candidate_dir, root, config), Path(root))
    log_path = Path(candidate_dir) / "log.txt"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    name, judge = RULES[rule]
    result = judge(baseline, candidate, log, margin) if rule == "superiority" else judge(baseline, candidate, log)
    result.update(rule=name, baseline=Path(baseline_dir).name, candidate=Path(candidate_dir).name)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", required=True, help="the run that differs only by the change (BT5)")
    parser.add_argument("--candidate", required=True, help="the confirming run (BT6)")
    parser.add_argument("--out", default="ml/evaluation/v640/r_lean13.json")
    parser.add_argument("--rule", choices=sorted(RULES), default="non_inferiority",
                        help="non_inferiority (R-LEAN13, confirm an adopted change) or superiority (R-LEAN14, adopt one)")
    parser.add_argument("--margin", type=float, default=MAX_SHARPE_LOSS, help="the superiority rule's Sharpe margin")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    result = verdict_for_run_dirs(root / args.baseline, root / args.candidate, config, root, args.rule, args.margin)
    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["keep"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
