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


def evaluate_ranking_promotion_gate(
    ranking_metrics_by_model: dict, config: dict, walk_forward_summary: dict | None = None
) -> dict:
    """V5.1 Phase 4 (item 7 - "the dead end"): assess_ranking_quality()'s
    verdict has always been written to a candidate's own
    {sequence,multitask}_training_metrics.json, but nothing in retraining/
    ever read it - a candidate could be `not_promotable` on every rank head
    and still sail through evaluate_validation_gate() untouched, because
    that function only ever looked at the BASELINE model's Sharpe/drawdown/
    MCC. This closes that gap. Pure. Returns
    {passed, failures, near_misses, thresholds, observed}.

    ranking_metrics_by_model: {"sequence": <sequence_training_metrics.json
    dict, or None>, "multitask": <multitask_training_metrics.json dict, or
    None>} - the SAME two files retraining/orchestrator.py::validate()
    already loads via _load_json_if_exists() for the baseline gate.

    config: phase_v2.retraining.validation_gate.ranking (model/head to
    gate on, require_quality_status, min_net_sharpe/max_annualized_turnover/
    min_capacity_usd, min_walk_forward_windows/max_window_sign_flip_fraction,
    missing_metrics_action).

    Reads backtest.{head}_ranking_quality.quality_status and
    backtest.{head}_net_performance (both written by
    train_multitask.py/train_sequence.py's compute_*_metrics(), V5.1 Phases
    2-4) off the configured model's metrics, plus walk_forward_summary's
    stability_by_metric[f"{head}_ic"] when a walk-forward summary happens
    to be passed in (optional, default None - no caller is required to go
    find one; a candidate retrain has no walk-forward run of its own).

    MISSING-METRICS CONTRACT: when the configured model/head has neither a
    ranking_quality nor a net_performance entry (an older candidate trained
    before V5.1, or net_performance simply disabled in config), the
    outcome is governed by missing_metrics_action - "near_miss" (default,
    passed=True but flagged) / "fail" (passed=False) / "ignore" (passed=True,
    unflagged). WITHOUT the "near_miss" default, the very first retrain
    after V5.1 ships would auto-reject itself for metrics that simply don't
    exist yet on an older-format candidate."""
    model_name = str(config.get("model", "sequence"))
    head = str(config.get("head", "residual_rank_20d"))
    require_quality_status = set(config.get("require_quality_status", ["promotable", "watchlist"]))
    min_net_sharpe = float(config.get("min_net_sharpe", 0.0))
    max_annualized_turnover = float(config.get("max_annualized_turnover", 1e9))
    min_capacity_usd = float(config.get("min_capacity_usd", 0.0))
    min_walk_forward_windows = int(config.get("min_walk_forward_windows", 0))
    max_window_sign_flip_fraction = float(config.get("max_window_sign_flip_fraction", 1.0))
    missing_metrics_action = str(config.get("missing_metrics_action", "near_miss"))

    failures: list[str] = []
    near_misses: list[str] = []

    model_metrics = (ranking_metrics_by_model or {}).get(model_name) or {}
    backtest_metrics = model_metrics.get("backtest", {}) or {}
    ranking_quality = backtest_metrics.get(f"{head}_ranking_quality")
    net_performance = backtest_metrics.get(f"{head}_net_performance")

    observed: dict = {
        "model": model_name,
        "head": head,
        "quality_status": (ranking_quality or {}).get("quality_status"),
        "net_sharpe": (net_performance or {}).get("observed", {}).get("net_sharpe"),
        "annualized_turnover": (net_performance or {}).get("observed", {}).get("annualized_turnover"),
        "capacity_usd": (net_performance or {}).get("observed", {}).get("capacity_usd"),
    }

    if ranking_quality is None and net_performance is None:
        if missing_metrics_action == "fail":
            failures.append("ranking_gate_metrics_absent")
        elif missing_metrics_action == "near_miss":
            near_misses.append("ranking_gate_metrics_absent")
        # "ignore" - neither list touched, this gate is a pure no-op for this candidate.
    else:
        if ranking_quality is not None and ranking_quality.get("quality_status") not in require_quality_status:
            failures.append("ranking_quality_status_not_accepted")

        if net_performance is not None:
            net_observed = net_performance.get("observed", {}) or {}
            if float(net_observed.get("net_sharpe", 0.0) or 0.0) < min_net_sharpe:
                failures.append("net_sharpe_below_gate")
            if float(net_observed.get("annualized_turnover", 0.0) or 0.0) > max_annualized_turnover:
                failures.append("annualized_turnover_above_gate")
            if float(net_observed.get("capacity_usd", 0.0) or 0.0) < min_capacity_usd:
                failures.append("capacity_usd_below_gate")

    if walk_forward_summary is not None:
        stability = (walk_forward_summary.get("stability_by_metric") or {}).get(f"{head}_ic")
        if stability is not None:
            observed["walk_forward_num_windows"] = stability.get("num_windows")
            observed["walk_forward_sign_flip_fraction"] = stability.get("sign_flip_fraction")
            if int(stability.get("num_windows", 0) or 0) < min_walk_forward_windows:
                failures.append("insufficient_walk_forward_windows")
            if float(stability.get("sign_flip_fraction", 0.0) or 0.0) > max_window_sign_flip_fraction:
                failures.append("walk_forward_sign_flip_fraction_above_gate")

    return {
        "passed": not failures,
        "failures": failures,
        "near_misses": near_misses,
        "thresholds": {
            "model": model_name,
            "head": head,
            "require_quality_status": sorted(require_quality_status),
            "min_net_sharpe": min_net_sharpe,
            "max_annualized_turnover": max_annualized_turnover,
            "min_capacity_usd": min_capacity_usd,
            "min_walk_forward_windows": min_walk_forward_windows,
            "max_window_sign_flip_fraction": max_window_sign_flip_fraction,
            "missing_metrics_action": missing_metrics_action,
        },
        "observed": observed,
    }


def evaluate_validation_gate(
    candidate_metrics: dict,
    candidate_report: dict,
    active_metrics: dict,
    active_report: dict,
    config: dict,
    *,
    candidate_ranking_metrics: dict | None = None,
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
    - candidate backtest balanced_accuracy >= min_balanced_accuracy OR
      candidate backtest mcc >= min_mcc (skill floor - see below)
    - V5.1 Phase 4 (item 7): when candidate_ranking_metrics is provided
      (keyword-only, default None -> zero change for every existing
      caller/test) AND config["ranking"]["enabled"] is true,
      evaluate_ranking_promotion_gate() also runs against it, and its
      failures/near_misses are merged into this function's own lists
      before the final passed = not failures - one candidate, one combined
      verdict, rather than two gates a caller could forget to check both of.
    """
    min_sharpe = float(config.get("min_sharpe", 0.3))
    max_validation_loss_increase_ratio = float(config.get("max_validation_loss_increase_ratio", 0.10))
    max_gap = float(config.get("max_train_backtest_balanced_accuracy_gap", 0.20))
    min_trade_count = int(config.get("min_trade_count", 0))
    min_exposure_rate = float(config.get("min_exposure_rate", 0.0))
    watchlist_margin = float(config.get("watchlist_margin", 0.03))
    # Skill floor (development/Problems.md): every prior check here is
    # Sharpe/drawdown/exposure-shaped, which a model with ZERO
    # discriminative power can pass trivially during any backtest window
    # with a sustained trend (a constant "always slightly bullish" output
    # rides a bull market to a positive Sharpe with full exposure - exactly
    # what the shipped baseline model did: MCC 0.066, balanced-accuracy
    # 0.519, positive_rate 0.91, yet a real 20% backtest return). Requires
    # EITHER metric to clear a coin-flip-or-better bar (an OR, not AND -
    # balanced_accuracy and MCC can disagree at the margin, and a model
    # need only demonstrate skill on one recognized axis).
    min_balanced_accuracy = float(config.get("min_balanced_accuracy", 0.50))
    min_mcc = float(config.get("min_mcc", 0.0))

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
    candidate_backtest_balanced_accuracy = float(
        candidate_metrics.get("backtest", {}).get("balanced_accuracy", 0.0) or 0.0
    )
    candidate_backtest_mcc = float(candidate_metrics.get("backtest", {}).get("mcc", 0.0) or 0.0)

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

    # 7. Skill floor - see min_balanced_accuracy/min_mcc's own comment above.
    has_balanced_accuracy_skill = candidate_backtest_balanced_accuracy >= min_balanced_accuracy
    has_mcc_skill = candidate_backtest_mcc >= min_mcc
    if not (has_balanced_accuracy_skill or has_mcc_skill):
        failures.append("candidate_no_demonstrated_skill")
    elif not has_balanced_accuracy_skill or not has_mcc_skill:
        near_misses.append("candidate_skill_marginal_on_one_metric")

    # V5.1 Phase 4 (item 7) - see this function's own docstring above.
    ranking_gate_result = None
    ranking_config = config.get("ranking", {})
    if candidate_ranking_metrics is not None and ranking_config.get("enabled", False):
        ranking_gate_result = evaluate_ranking_promotion_gate(candidate_ranking_metrics, ranking_config)
        failures.extend(ranking_gate_result["failures"])
        near_misses.extend(ranking_gate_result["near_misses"])

    passed = not failures

    thresholds = {
        "min_sharpe": min_sharpe,
        "max_validation_loss_increase_ratio": max_validation_loss_increase_ratio,
        "max_train_backtest_balanced_accuracy_gap": max_gap,
        "min_trade_count": min_trade_count,
        "min_exposure_rate": min_exposure_rate,
        "watchlist_margin": watchlist_margin,
        "min_balanced_accuracy": min_balanced_accuracy,
        "min_mcc": min_mcc,
    }
    observed = {
        "candidate_drawdown": candidate_drawdown,
        "active_drawdown": active_drawdown,
        "candidate_sharpe": candidate_sharpe,
        "candidate_validation_loss": candidate_validation_loss,
        "active_validation_loss": active_validation_loss,
        "max_allowed_validation_loss": max_allowed_validation_loss,
        "candidate_overfitting_gap": candidate_gap,
        "candidate_trade_count": candidate_trade_count,
        "candidate_exposure_rate": candidate_exposure_rate,
        "candidate_backtest_balanced_accuracy": candidate_backtest_balanced_accuracy,
        "candidate_backtest_mcc": candidate_backtest_mcc,
    }
    if ranking_gate_result is not None:
        thresholds["ranking"] = ranking_gate_result["thresholds"]
        observed["ranking"] = ranking_gate_result["observed"]

    return {
        "passed": passed,
        "failures": failures,
        "near_misses": near_misses,
        "thresholds": thresholds,
        "observed": observed,
    }
