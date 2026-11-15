"""Tests for retraining.backtest_gate — V2-17.

Conventions: no test classes, module-level helpers, pure functions tested
with plain dicts shaped like backtests/strategy_report.json
(train.py's compute_strategy_metrics() output).
"""

from retraining.backtest_gate import compare_backtests

_CONFIG = {"min_excess_return_vs_active": -0.02, "benchmark_ticker": None}


def _report(total_return=0.10, per_asset=None) -> dict:
    return {
        "backtest": {
            "strategy": {"total_return": total_return, "sharpe": 0.5, "max_drawdown": -0.10},
            "buy_and_hold": {"total_return": 0.05, "sharpe": 0.3, "max_drawdown": -0.15},
        },
        "backtest_per_asset": per_asset or {},
    }


def test_compare_backtests_passes_when_candidate_at_least_as_good():
    active = _report(total_return=0.10)
    candidate = _report(total_return=0.12)

    result = compare_backtests(active, candidate, _CONFIG)

    assert result["passed"] is True
    assert result["comparison"]["candidate"]["total_return"] == 0.12
    assert result["comparison"]["buy_and_hold"]["total_return"] == 0.05
    assert result["comparison"]["benchmark"] is None


def test_compare_backtests_fails_when_excess_return_below_threshold():
    active = _report(total_return=0.10)
    candidate = _report(total_return=0.0)

    result = compare_backtests(active, candidate, _CONFIG)

    assert result["passed"] is False
    assert result["reasons"]


def test_compare_backtests_includes_benchmark_when_ticker_configured():
    active = _report(total_return=0.10)
    candidate = _report(
        total_return=0.12,
        per_asset={"SPY": {"strategy": {"total_return": 0.08, "sharpe": 0.4, "max_drawdown": -0.08}}},
    )
    config = {**_CONFIG, "benchmark_ticker": "SPY"}

    result = compare_backtests(active, candidate, config)

    assert result["comparison"]["benchmark"]["total_return"] == 0.08


def test_compare_backtests_omits_benchmark_when_ticker_missing_from_candidate():
    active = _report()
    candidate = _report(per_asset={})
    config = {**_CONFIG, "benchmark_ticker": "SPY"}

    result = compare_backtests(active, candidate, config)

    assert result["comparison"]["benchmark"] is None


# --- V6.6.7 (#370, formal/AetherFormal/BacktestGate.lean)

def test_v667_a_missing_candidate_or_a_bad_threshold_fails():
    import math

    from retraining.backtest_gate import compare_backtests

    losing = {"backtest": {"strategy": {"total_return": -0.3}}}
    missing = {"backtest": {"strategy": {}}}
    nan = {"backtest": {"strategy": {"total_return": math.nan}}}
    good = {"backtest": {"strategy": {"total_return": 0.1}}}
    for candidate in (missing, nan):
        out = compare_backtests(losing, candidate, {})
        assert out["passed"] is False and out["reasons"] == ["candidate_return_missing"]
    for threshold in (math.nan, "x", True, None):
        out = compare_backtests(losing, good, {"min_excess_return_vs_active": threshold})
        assert out["passed"] is False and out["reasons"][0].startswith("min_excess_return_vs_active_invalid")
    assert compare_backtests(losing, good, {})["passed"] is True
