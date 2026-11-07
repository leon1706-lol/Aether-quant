"""Retraining's pure gates and plans (workers and registries stay in `retraining/`)."""

from retraining.auto_rollback import select_rollback_target
from retraining.backtest_gate import compare_backtests
from retraining.planning import cooldown_remaining_seconds, count_events_in_last_day, evaluate_retraining_plan, min_observations_satisfied, select_candidate_trigger
from retraining.rollback_hardening import compute_degradation_score, select_rollback_target_dry_run
from retraining.validation_gate import compute_overfitting_gap, evaluate_ranking_promotion_gate, evaluate_validation_gate
from retraining.vault_commands import build_av_add_command, build_av_commit_command, build_av_head_command, build_av_push_command, build_av_restore_command, build_av_status_command, build_commit_plan

__all__ = [
    "build_av_add_command",
    "build_av_commit_command",
    "build_av_head_command",
    "build_av_push_command",
    "build_av_restore_command",
    "build_av_status_command",
    "build_commit_plan",
    "compare_backtests",
    "compute_degradation_score",
    "compute_overfitting_gap",
    "cooldown_remaining_seconds",
    "count_events_in_last_day",
    "evaluate_ranking_promotion_gate",
    "evaluate_retraining_plan",
    "evaluate_validation_gate",
    "min_observations_satisfied",
    "select_candidate_trigger",
    "select_rollback_target",
    "select_rollback_target_dry_run",
]
