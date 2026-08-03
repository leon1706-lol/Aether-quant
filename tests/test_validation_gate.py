"""Tests for retraining.validation_gate — V2-17.

Conventions: no test classes, module-level helpers, pure functions tested
with plain dicts shaped like ml/training_metrics.json and
backtests/strategy_report.json.
"""

from retraining.validation_gate import compute_overfitting_gap, evaluate_ranking_promotion_gate, evaluate_validation_gate

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


def test_evaluate_validation_gate_rejects_candidate_with_no_demonstrated_skill():
    # development/Problems.md: every other check here is Sharpe/drawdown/
    # exposure-shaped, which a model with ZERO discriminative power can pass
    # trivially during a sustained-trend backtest window - exactly what the
    # shipped baseline model did (MCC 0.066, balanced-accuracy 0.519, yet a
    # real 20% backtest return riding a bull market). A candidate at-or-below
    # a coin flip on BOTH balanced-accuracy and MCC must fail even if every
    # other Sharpe/drawdown/trade-count check passes.
    candidate_metrics = _metrics(backtest={"balanced_accuracy": 0.49, "mcc": -0.01})

    result = evaluate_validation_gate(candidate_metrics, _report(), _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert result["passed"] is False
    assert "candidate_no_demonstrated_skill" in result["failures"]


def test_evaluate_validation_gate_accepts_candidate_with_skill_on_either_metric():
    # Only ONE of balanced_accuracy/mcc needs to clear the floor (an OR) -
    # a candidate with mcc exactly at the default active fixture's implicit
    # 0.0 (unset) but a real balanced-accuracy edge still passes this check.
    candidate_metrics = _metrics(backtest={"balanced_accuracy": 0.55})  # mcc unset -> defaults to 0.0, clears min_mcc=0.0

    result = evaluate_validation_gate(candidate_metrics, _report(), _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)

    assert "candidate_no_demonstrated_skill" not in result["failures"]


def test_evaluate_validation_gate_skill_floor_thresholds_are_configurable():
    candidate_metrics = _metrics(backtest={"balanced_accuracy": 0.52, "mcc": 0.02})
    strict_config = {**_CONFIG, "min_balanced_accuracy": 0.55, "min_mcc": 0.05}

    result = evaluate_validation_gate(candidate_metrics, _report(), _ACTIVE_METRICS, _ACTIVE_REPORT, strict_config)

    assert result["passed"] is False
    assert "candidate_no_demonstrated_skill" in result["failures"]
    assert result["thresholds"]["min_balanced_accuracy"] == 0.55
    assert result["thresholds"]["min_mcc"] == 0.05


# ---------------------------------------------------------------------------
# evaluate_ranking_promotion_gate (V5.1 Phase 4, item 7 - "the dead end")
# ---------------------------------------------------------------------------

_RANKING_CONFIG = {
    "enabled": True,
    "model": "sequence",
    "head": "residual_rank_20d",
    "require_quality_status": ["promotable", "watchlist"],
    "min_net_sharpe": 0.40,
    "max_annualized_turnover": 12.0,
    "min_capacity_usd": 250000,
    "min_walk_forward_windows": 3,
    "max_window_sign_flip_fraction": 0.34,
    "missing_metrics_action": "near_miss",
}


def _ranking_metrics(quality_status="promotable", net_sharpe=0.6, turnover=5.0, capacity_usd=300000) -> dict:
    return {
        "sequence": {
            "backtest": {
                "residual_rank_20d_ranking_quality": {"quality_status": quality_status},
                "residual_rank_20d_net_performance": {
                    "observed": {
                        "net_sharpe": net_sharpe,
                        "annualized_turnover": turnover,
                        "capacity_usd": capacity_usd,
                    }
                },
            }
        }
    }


def test_evaluate_ranking_promotion_gate_passes_when_everything_clears():
    result = evaluate_ranking_promotion_gate(_ranking_metrics(), _RANKING_CONFIG)

    assert result["passed"] is True
    assert result["failures"] == []


def test_evaluate_ranking_promotion_gate_fails_on_not_promotable_quality_status():
    result = evaluate_ranking_promotion_gate(_ranking_metrics(quality_status="not_promotable"), _RANKING_CONFIG)

    assert result["passed"] is False
    assert "ranking_quality_status_not_accepted" in result["failures"]


def test_evaluate_ranking_promotion_gate_fails_on_net_sharpe_below_gate():
    result = evaluate_ranking_promotion_gate(_ranking_metrics(net_sharpe=0.1), _RANKING_CONFIG)

    assert result["passed"] is False
    assert "net_sharpe_below_gate" in result["failures"]


def test_evaluate_ranking_promotion_gate_missing_metrics_is_near_miss_not_failure_by_default():
    # The MISSING-METRICS CONTRACT: an older candidate trained before V5.1
    # has neither key at all - default missing_metrics_action="near_miss"
    # must NOT reject it (that would auto-reject the very first retrain
    # after V5.1 ships).
    result = evaluate_ranking_promotion_gate({"sequence": None, "multitask": None}, _RANKING_CONFIG)

    assert result["passed"] is True
    assert "ranking_gate_metrics_absent" in result["near_misses"]


def test_evaluate_ranking_promotion_gate_missing_metrics_fails_when_configured_to():
    strict_config = {**_RANKING_CONFIG, "missing_metrics_action": "fail"}

    result = evaluate_ranking_promotion_gate({"sequence": None, "multitask": None}, strict_config)

    assert result["passed"] is False
    assert "ranking_gate_metrics_absent" in result["failures"]


def test_evaluate_ranking_promotion_gate_missing_metrics_ignored_when_configured_to():
    ignore_config = {**_RANKING_CONFIG, "missing_metrics_action": "ignore"}

    result = evaluate_ranking_promotion_gate({"sequence": None, "multitask": None}, ignore_config)

    assert result["passed"] is True
    assert result["near_misses"] == []
    assert result["failures"] == []


def test_evaluate_ranking_promotion_gate_walk_forward_stability_optional_input():
    walk_forward_summary = {
        "stability_by_metric": {
            "residual_rank_20d_ic": {"num_windows": 6, "sign_flip_fraction": 0.1},
        }
    }

    result = evaluate_ranking_promotion_gate(_ranking_metrics(), _RANKING_CONFIG, walk_forward_summary)

    assert result["passed"] is True
    assert result["observed"]["walk_forward_num_windows"] == 6


def test_evaluate_ranking_promotion_gate_fails_on_insufficient_walk_forward_windows():
    walk_forward_summary = {"stability_by_metric": {"residual_rank_20d_ic": {"num_windows": 1, "sign_flip_fraction": 0.0}}}

    result = evaluate_ranking_promotion_gate(_ranking_metrics(), _RANKING_CONFIG, walk_forward_summary)

    assert result["passed"] is False
    assert "insufficient_walk_forward_windows" in result["failures"]


# ---------------------------------------------------------------------------
# evaluate_validation_gate + candidate_ranking_metrics wiring (V5.1 Phase 4)
# ---------------------------------------------------------------------------


def test_evaluate_validation_gate_candidate_ranking_metrics_none_is_byte_identical_to_today():
    candidate_metrics = _metrics(validation={"balanced_accuracy": 0.60, "loss": 0.55})
    candidate_report = _report(sharpe=0.8, max_drawdown=-0.05, trade_count=60, exposure_rate=0.25)

    without = evaluate_validation_gate(candidate_metrics, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG)
    with_default = evaluate_validation_gate(
        candidate_metrics, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, _CONFIG,
        candidate_ranking_metrics=None,
    )

    assert without == with_default


def test_evaluate_validation_gate_ranking_disabled_is_a_no_op_even_with_metrics_provided():
    candidate_metrics = _metrics(validation={"balanced_accuracy": 0.60, "loss": 0.55})
    candidate_report = _report(sharpe=0.8, max_drawdown=-0.05, trade_count=60, exposure_rate=0.25)
    config_without_ranking = {**_CONFIG}  # no "ranking" key at all -> disabled by default

    result = evaluate_validation_gate(
        candidate_metrics, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, config_without_ranking,
        candidate_ranking_metrics=_ranking_metrics(quality_status="not_promotable"),
    )

    assert result["passed"] is True
    assert "ranking" not in result["thresholds"]


def test_evaluate_validation_gate_merges_ranking_gate_failures_when_enabled():
    candidate_metrics = _metrics(validation={"balanced_accuracy": 0.60, "loss": 0.55})
    candidate_report = _report(sharpe=0.8, max_drawdown=-0.05, trade_count=60, exposure_rate=0.25)
    config_with_ranking = {**_CONFIG, "ranking": _RANKING_CONFIG}

    result = evaluate_validation_gate(
        candidate_metrics, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, config_with_ranking,
        candidate_ranking_metrics=_ranking_metrics(quality_status="not_promotable"),
    )

    # Every baseline check still passes on its own (same fixture as the
    # "accepts better candidate" test) - only the ranking sub-gate fails,
    # and it alone must be enough to reject the whole candidate.
    assert result["passed"] is False
    assert "ranking_quality_status_not_accepted" in result["failures"]
    assert "ranking" in result["thresholds"]
    assert "ranking" in result["observed"]


def test_evaluate_validation_gate_ranking_enabled_but_metrics_absent_does_not_reject():
    candidate_metrics = _metrics(validation={"balanced_accuracy": 0.60, "loss": 0.55})
    candidate_report = _report(sharpe=0.8, max_drawdown=-0.05, trade_count=60, exposure_rate=0.25)
    config_with_ranking = {**_CONFIG, "ranking": _RANKING_CONFIG}

    result = evaluate_validation_gate(
        candidate_metrics, candidate_report, _ACTIVE_METRICS, _ACTIVE_REPORT, config_with_ranking,
        candidate_ranking_metrics={"sequence": None, "multitask": None},
    )

    assert result["passed"] is True
    assert "ranking_gate_metrics_absent" in result["near_misses"]
