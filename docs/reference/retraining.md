# aether_quant.retraining

Retraining's pure gates and plans (workers and registries stay in `retraining/`).

::: aether_quant.retraining
    options:
      members:
        - build_av_add_command
        - build_av_commit_command
        - build_av_head_command
        - build_av_push_command
        - build_av_restore_command
        - build_av_status_command
        - build_commit_plan
        - compare_backtests
        - compute_degradation_score
        - compute_overfitting_gap
        - cooldown_remaining_seconds
        - count_events_in_last_day
        - evaluate_ranking_promotion_gate
        - evaluate_retraining_plan
        - evaluate_validation_gate
        - min_observations_satisfied
        - select_candidate_trigger
        - select_rollback_target
        - select_rollback_target_dry_run
