"""R-LEAN13 (V6.4.0, Problems #221 / #225): is a confirming Lean run of an adopted change kept? Pure given two statistics dicts.

The adopted book (10-session rebalance, 20-session hold, crypto core only) was decided on the offline simulator, which tracks Lean at a
daily correlation of ~0.7. One Lean run (BT6) confirms or reverts it, judged against the run that differs only by the change (BT5):

    (a) the strategy's Sharpe without a risk-free rate (T-bill sweep taken out) is not worse than the baseline's by more than 0.10,
    (b) the portfolio's maximum drawdown is not worse than the baseline's by more than 1 percentage point,
    (c) the engine log shows a complete run: statistics written, the interpreter teardown reached, and no model-inference failure.
        (The teardown TIMEOUT is the PC's, Problems #104/#204, and is reported, not judged.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MAX_SHARPE_LOSS = 0.10
MAX_DRAWDOWN_WORSENING = 0.01  # fraction of NAV: 1 percentage point


def _row(stats: dict, section: str, metric: str, column: str):
    for row in (stats.get("sections") or {}).get(section) or []:
        if row.get("metric") == metric:
            return row.get(column)
    return None


def strategy_sharpe(stats: dict):
    return _row(stats, "efficiency", "Annualized Sharpe ratio (no risk-free rate)", "strategy")


def max_drawdown(stats: dict):
    return _row(stats, "runs", "Maximum drawdown", "portfolio")


def engine_log_status(engine_log_text: str) -> dict:
    return {
        "teardown_reached": bool(re.search(r"PythonInitializer\.Shutdown\(\): start", engine_log_text)),
        "inference_failures": len(re.findall(r"inference failed", engine_log_text)),
        "teardown_timed_out": "Operation timed out" in engine_log_text or "Failed to shutdown python" in engine_log_text,
    }


def r_lean13(baseline: dict, candidate: dict, candidate_engine_log: str) -> dict:
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


def verdict_for_run_dirs(baseline_dir: Path, candidate_dir: Path, config: dict, root: Path) -> dict:
    """Statistics of both run folders (`backtest_statistics.compute_for_run_dir`) and the candidate's engine log."""
    from evaluation.backtest_statistics import compute_for_run_dir

    baseline = compute_for_run_dir(Path(baseline_dir), config, Path(root))
    candidate = compute_for_run_dir(Path(candidate_dir), config, Path(root))
    log_path = Path(candidate_dir) / "log.txt"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    result = r_lean13(baseline, candidate, log)
    result.update(baseline=Path(baseline_dir).name, candidate=Path(candidate_dir).name)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", required=True, help="the run that differs only by the change (BT5)")
    parser.add_argument("--candidate", required=True, help="the confirming run (BT6)")
    parser.add_argument("--out", default="ml/evaluation/v640/r_lean13.json")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    result = verdict_for_run_dirs(root / args.baseline, root / args.candidate, config, root)
    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["keep"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
