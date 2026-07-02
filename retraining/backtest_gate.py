"""Pure active/candidate/buy-and-hold backtest comparison (Phase V2-17).

Builds the comparison table directly from the strategy/buy_and_hold blocks
train.py's compute_strategy_metrics() already produces in every
strategy_report.json - no re-computation needed, buy-and-hold is already
built in. See retraining/lean_backtest.py for the optional, best-effort
Lean-backtest IO wrapper this module's caller may also want to run first.
"""

from __future__ import annotations


def _strategy_block(report: dict, key: str) -> dict:
    return report.get("backtest", {}).get(key, {})


def compare_backtests(active_report: dict, candidate_report: dict, config: dict) -> dict:
    """3-way (active / candidate / buy-and-hold) comparison, plus an optional
    4th risk-adjusted-benchmark row.

    A benchmark row is included only if config["benchmark_ticker"] names an
    asset present in candidate_report["backtest_per_asset"] - reuses the
    per-asset breakdown build_strategy_report() already computes.

    Returns {passed, comparison: {active, candidate, buy_and_hold, benchmark|None}, reasons: [...]}.
    """
    active_strategy = _strategy_block(active_report, "strategy")
    candidate_strategy = _strategy_block(candidate_report, "strategy")
    candidate_buy_and_hold = _strategy_block(candidate_report, "buy_and_hold")

    benchmark_ticker = config.get("benchmark_ticker")
    benchmark = None
    if benchmark_ticker:
        per_asset = candidate_report.get("backtest_per_asset", {})
        asset_report = per_asset.get(benchmark_ticker)
        if isinstance(asset_report, dict):
            benchmark = asset_report.get("strategy")

    min_excess_return_vs_active = float(config.get("min_excess_return_vs_active", -0.02))
    candidate_return = float(candidate_strategy.get("total_return", 0.0) or 0.0)
    active_return = float(active_strategy.get("total_return", 0.0) or 0.0)
    excess_return_vs_active = candidate_return - active_return

    reasons: list[str] = []
    passed = True
    if excess_return_vs_active < min_excess_return_vs_active:
        passed = False
        reasons.append(
            f"candidate_excess_return_vs_active_below_threshold "
            f"({excess_return_vs_active:.4f} < {min_excess_return_vs_active:.4f})"
        )

    return {
        "passed": passed,
        "comparison": {
            "active": active_strategy,
            "candidate": candidate_strategy,
            "buy_and_hold": candidate_buy_and_hold,
            "benchmark": benchmark,
        },
        "excess_return_vs_active": excess_return_vs_active,
        "reasons": reasons,
    }
