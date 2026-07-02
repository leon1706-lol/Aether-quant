"""Tests for retraining.validation_gate — V2-17.

Conventions: no test classes, module-level helpers, pure functions tested
with plain dicts shaped like ml/training_metrics.json and
backtests/strategy_report.json.
"""

from retraining.validation_gate import compute_overfitting_gap, evaluate_validation_gate

_CONFIG = {
    "min_sharpe": 0.3,
    "max_validation_loss_increase_ratio": 0.10,
    "max_train_backtest_balanced_accuracy_gap": 0.20,
    "min_trade_count": 10,
    "min_exposure_rate": 0.05,
    "watchlist_margin": 0.03,
}


def _metrics(**overrides) -> dict:
    defaults = {
        "train": {"balanced_accuracy": 0.60},
        "validation": {"balanced_accuracy": 0.58, "loss": 0.60},
        "backtest": {"balanced_accuracy": 0.55},
    }
    defaults.update(overrides)
    return defaults


def _report(sharpe=0.5, max_drawdown=-0.10, trade_count=50, exposure_rate=0.20) -> dict:
    return {
        "backtest": {
            "trade_count": trade_count,
            "exposure_rate": exposure_rate,
            "strategy": {"sharpe": sharpe, "max_drawdown": max_drawdown, "total_return": 0.10},
        }
    }


_ACTIVE_METRICS = _metrics()
_ACTIVE_REPORT = _report()


def test_compute_overfitting_gap():
    gap = compute_overfitting_gap(_metrics(train={"balanced_accuracy": 0.70}, backtest={"balanced_accuracy": 0.50}))

    assert gap == 0.20 or abs(gap - 0.20) < 1e-9


def test_evaluate_validation_gate_accepts_better_candidate():
    candidate_metrics = _metrics(validation={"balanced_accuracy": 0.60, "loss": 0.55})
    candidate_report = _report(sharpe=0.8, max_drawdown=-0.05, trade_count=60, exposure_rate=0.25)

    result = evaluate_validation_gate(candidate_metrics, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert result["passed"] is True
    assert result["failures"] == []


def test_evaluate_validation_gate_rejects_worse_drawdown():
    candidate_report = _report(max_drawdown=-0.30)

    result = evaluate_validation_gate(_ACTIVE_METRICS, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert result["passed"] is False
    assert "candidate_drawdown_worse_than_active" in result["failures"]


def test_evaluate_validation_gate_rejects_sharpe_below_minimum():
    candidate_report = _report(sharpe=0.1)

    result = evaluate_validation_gate(_ACTIVE_METRICS, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert result["passed"] is False
    assert "candidate_sharpe_below_minimum" in result["failures"]


def test_evaluate_validation_gate_rejects_unstable_validation_loss():
    candidate_metrics = _metrics(validation={"balanced_accuracy": 0.58, "loss": 5.0})

    result = evaluate_validation_gate(candidate_metrics, _ACTIVE_REPORT, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert result["passed"] is False
    assert "candidate_validation_loss_unstable" in result["failures"]


def test_evaluate_validation_gate_rejects_overfitting_gap_too_large():
    candidate_metrics = _metrics(train={"balanced_accuracy": 0.90}, backtest={"balanced_accuracy": 0.50})

    result = evaluate_validation_gate(candidate_metrics, _ACTIVE_REPORT, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert result["passed"] is False
    assert "candidate_overfitting_gap_too_large" in result["failures"]


def test_evaluate_validation_gate_rejects_too_few_trades():
    candidate_report = _report(trade_count=1)

    result = evaluate_validation_gate(_ACTIVE_METRICS, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert result["passed"] is False
    assert "candidate_trade_count_too_low" in result["failures"]


def test_evaluate_validation_gate_rejects_low_exposure_rate():
    candidate_report = _report(exposure_rate=0.0)

    result = evaluate_validation_gate(_ACTIVE_METRICS, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert result["passed"] is False
    assert "candidate_exposure_rate_too_low" in result["failures"]
