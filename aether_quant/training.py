"""Training without the training stack: splits, purges, purged folds, yearly windows, ranked inputs, the walk-forward linear model, signal recipes, and what the models could know."""

from evaluation.model_audit import audit_trial_ids, feature_group_ic, fundamental_coverage, group_table
from evaluation.walk_forward_linear import fama_macbeth_ridge, monthly_slope
from features.training_splits import annual_windows, assign_split, assign_split_series, centred_label, purge_label_overlap, purge_label_overlap_calendar, purged_embargoed_folds, rank_inputs
from portfolio.signal_construction import build_table, residualise_signal

__all__ = [
    "annual_windows",
    "assign_split",
    "assign_split_series",
    "audit_trial_ids",
    "build_table",
    "centred_label",
    "fama_macbeth_ridge",
    "feature_group_ic",
    "fundamental_coverage",
    "group_table",
    "monthly_slope",
    "purge_label_overlap",
    "purge_label_overlap_calendar",
    "purged_embargoed_folds",
    "rank_inputs",
    "residualise_signal",
]
