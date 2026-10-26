"""evaluation/lean_verdict.py (V6.4.1): R-LEAN13, the rule that keeps or reverts a Lean-confirmed change; R-LEAN14 (V6.4.2), the
superiority rule that adopts one, and the per-run frozen config."""

from __future__ import annotations

import json

from evaluation.lean_verdict import engine_log_status, max_drawdown, r_lean13, r_lean14, run_config, strategy_sharpe

CLEAN = "TRACE:: PythonInitializer.Shutdown(): start\nTRACE:: PythonInitializer.Shutdown(): ended\n"


def stats(sharpe, drawdown, status="OK"):
    return {"status": status, "sections": {
        "efficiency": [{"metric": "Annualized Sharpe ratio (no risk-free rate)", "portfolio": 1.5, "strategy": sharpe}],
        "runs": [{"metric": "Maximum drawdown", "portfolio": drawdown, "strategy": 0.07}],
    }}


def test_rows_are_read_by_metric_name():
    assert strategy_sharpe(stats(0.54, 0.043)) == 0.54 and max_drawdown(stats(0.54, 0.043)) == 0.043
    assert strategy_sharpe({}) is None and max_drawdown({"sections": {}}) is None


def test_a_better_run_is_kept():
    verdict = r_lean13(stats(0.54, 0.043), stats(0.80, 0.040), CLEAN)
    assert verdict["keep"] is True and all(verdict["checks"].values())


def test_each_clause_can_revert():
    base = stats(0.54, 0.043)
    assert r_lean13(base, stats(0.43, 0.043), CLEAN)["checks"]["strategy_sharpe_within_0.10"] is False
    assert r_lean13(base, stats(0.54, 0.054), CLEAN)["checks"]["max_drawdown_within_1pp"] is False
    assert r_lean13(base, stats(0.54, 0.043), "no teardown line")["keep"] is False
    assert r_lean13(base, stats(0.54, 0.043), CLEAN + "ERROR:: inference failed for AAPL\n")["keep"] is False
    assert r_lean13(base, stats(0.54, 0.043, status="no equity curve"), CLEAN)["keep"] is False


def test_boundaries_and_unreadable_values():
    base = stats(0.54, 0.043)
    assert r_lean13(base, stats(0.4401, 0.0529), CLEAN)["keep"] is True  # just inside both margins
    assert r_lean13(base, {"status": "OK", "sections": {}}, CLEAN)["keep"] is False


def test_the_teardown_timeout_is_reported_not_judged():
    log = CLEAN + "ERROR:: Failed to shutdown python: Operation timed out\n"
    status = engine_log_status(log)
    assert status["teardown_timed_out"] is True and status["teardown_reached"] is True
    assert r_lean13(stats(0.5, 0.04), stats(0.5, 0.04), log)["keep"] is True


def test_r_lean14_needs_the_margin_above_the_baseline():
    base = stats(0.35, 0.043)
    passed = r_lean14(base, stats(0.45, 0.050), CLEAN)
    assert passed["keep"] is True and "strategy_sharpe_above_by_0.10" in passed["checks"]
    assert "strategy_sharpe_within_0.10" not in passed["checks"]
    assert r_lean14(base, stats(0.44, 0.043), CLEAN)["keep"] is False  # within R-LEAN13's band, not above the margin
    assert r_lean14(base, stats(0.60, 0.054), CLEAN)["keep"] is False  # drawdown clause unchanged
    assert r_lean14(base, stats(0.60, 0.043), "no teardown line")["keep"] is False
    assert r_lean14(base, stats(0.40, 0.043), CLEAN, margin=0.05)["keep"] is True


def test_each_run_uses_its_frozen_config(tmp_path):
    frozen = tmp_path / "ml" / "evaluation" / "run_configs"
    frozen.mkdir(parents=True)
    (frozen / "2026-10-24_01-00-00.json").write_text(json.dumps({"runtime": {"trading_days_per_year": 252}}), encoding="utf-8")
    fallback = {"runtime": {"trading_days_per_year": 365}}
    assert run_config(tmp_path / "backtests" / "2026-10-24_01-00-00", tmp_path, fallback)["runtime"]["trading_days_per_year"] == 252
    assert run_config(tmp_path / "backtests" / "2026-10-24_02-00-00", tmp_path, fallback) is fallback
