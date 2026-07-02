"""Pure candidate-vs-active validation gate (Phase V2-17).

Mirrors train.py's assess_expert_quality() failures/near_misses/status
shape, but compares a candidate model's metrics against the CURRENTLY
ACTIVE model's metrics (relative comparison) instead of assess_expert_quality's
fixed absolute thresholds - there is no existing candidate-vs-active diff
function anywhere else in this codebase.

Inputs are the same JSON shapes train.py already produces:
    candidate_metrics / active_metrics : ml/.../training_metrics.json (compute_binary_metrics shape)
    candidate_report / active_report   : ml/.../strategy_report.json (compute_strategy_metrics shape)

No filesystem/Postgres I/O here - see retraining/artifacts.py for loading
these dicts off disk and for "no missing scaler/schema/artifacts" checks.
"""

from __future__ import annotations


def compute_overfitting_gap(metrics: dict) -> float:
    """train.balanced_accuracy - backtest.balanced_accuracy.

    No such field is pre-computed for the baseline model anywhere today
    (unlike expert models' quality_gate.observed) - self-computed here from
    training_metrics.json's train/backtest splits.
    """
    train_balanced_accuracy = float(metrics.get("train", {}).get("balanced_accuracy", 0.0) or 0.0)
    backtest_balanced_accuracy = float(metrics.get("backtest", {}).get("balanced_accuracy", 0.0) or 0.0)
    return train_balanced_accuracy - backtest_balanced_accuracy


def evaluate_validation_gate(
    candidate_metrics: dict,
    candidate_report: dict,
    active_metrics: dict,
    active_report: dict,
    config: dict,
) -> dict:
    """Returns {passed, failures: [...], near_misses: [...], thresholds: {...}, observed: {...}}.

    Checks, in order:
    - candidate max_drawdown not worse (not more negative) than active
    - candidate backtest sharpe >= min_sharpe
    - candidate validation loss not worse than active's by more than
      max_validation_loss_increase_ratio
    - compute_overfitting_gap(candidate) <= max_train_backtest_balanced_accuracy_gap
    - candidate backtest trade_count >= min_trade_count
    - candidate backtest exposure_rate >= min_exposure_rate
    """
    min_sharpe = float(config.get("min_sharpe", 0.3))
    max_validation_loss_increase_ratio = float(config.get("max_validation_loss_increase_ratio", 0.10))
    max_gap = float(config.get("max_train_backtest_balanced_accuracy_gap", 0.20))
    min_trade_count = int(config.get("min_trade_count", 0))
    min_exposure_rate = float(config.get("min_exposure_rate", 0.0))
    watchlist_margin = float(config.get("watchlist_margin", 0.03))

    candidate_backtest_strategy = candidate_report.get("backtest", {}).get("strategy", {})
    active_backtest_strategy = active_report.get("backtest", {}).get("strategy", {})

    candidate_drawdown = float(candidate_backtest_strategy.get("max_drawdown", 0.0) or 0.0)
    active_drawdown = float(active_backtest_strategy.get("max_drawdown", 0.0) or 0.0)
    candidate_sharpe = float(candidate_backtest_strategy.get("sharpe", 0.0) or 0.0)

    candidate_validation_loss = float(candidate_metrics.get("validation", {}).get("loss", 0.0) or 0.0)
    active_validation_loss = float(active_metrics.get("validation", {}).get("loss", 0.0) or 0.0)
    max_allowed_validation_loss = active_validation_loss * (1.0 + max_validation_loss_increase_ratio)

    candidate_gap = compute_overfitting_gap(candidate_metrics)

    candidate_trade_count = int(candidate_report.get("backtest", {}).get("trade_count", 0) or 0)
    candidate_exposure_rate = float(candidate_report.get("backtest", {}).get("exposure_rate", 0.0) or 0.0)

    failures: list[str] = []
    near_misses: list[str] = []

    # 1. Drawdown not worse than active (drawdowns are <= 0; "worse" = more negative).
    drawdown_margin = abs(active_drawdown) * watchlist_margin
    if candidate_drawdown < active_drawdown:
        failures.append("candidate_drawdown_worse_than_active")
    elif candidate_drawdown < active_drawdown + drawdown_margin:
        near_misses.append("candidate_drawdown_near_active")

    # 2. Sharpe above minimum.
    if candidate_sharpe < min_sharpe:
        failures.append("candidate_sharpe_below_minimum")
    elif candidate_sharpe < min_sharpe + watchlist_margin:
        near_misses.append("candidate_sharpe_near_minimum")

    # 3. Validation loss stable (not much worse than active).
    if candidate_validation_loss > max_allowed_validation_loss:
        failures.append("candidate_validation_loss_unstable")
    elif candidate_validation_loss > max_allowed_validation_loss * (1.0 - watchlist_margin):
        near_misses.append("candidate_validation_loss_near_limit")

    # 4. No obvious overfitting.
    if candidate_gap > max_gap:
        failures.append("candidate_overfitting_gap_too_large")
    elif candidate_gap > max_gap - watchlist_margin:
        near_misses.append("candidate_overfitting_gap_near_limit")

    # 5. Enough trades.
    if candidate_trade_count < min_trade_count:
        failures.append("candidate_trade_count_too_low")

    # 6. Enough exposure/signals.
    if candidate_exposure_rate < min_exposure_rate:
        failures.append("candidate_exposure_rate_too_low")

    passed = not failures

    return {
        "passed": passed,
        "failures": failures,
        "near_misses": near_misses,
        "thresholds": {
            "min_sharpe": min_sharpe,
            "max_validation_loss_increase_ratio": max_validation_loss_increase_ratio,
            "max_train_backtest_balanced_accuracy_gap": max_gap,
            "min_trade_count": min_trade_count,
            "min_exposure_rate": min_exposure_rate,
            "watchlist_margin": watchlist_margin,
        },
        "observed": {
            "candidate_drawdown": candidate_drawdown,
            "active_drawdown": active_drawdown,
            "candidate_sharpe": candidate_sharpe,
            "candidate_validation_loss": candidate_validation_loss,
            "active_validation_loss": active_validation_loss,
            "max_allowed_validation_loss": max_allowed_validation_loss,
            "candidate_overfitting_gap": candidate_gap,
            "candidate_trade_count": candidate_trade_count,
            "candidate_exposure_rate": candidate_exposure_rate,
        },
    }
