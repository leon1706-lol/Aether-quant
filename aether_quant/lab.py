"""The model lab (V6.7.1): build datasets from closes, train the project's own networks or a linear model on them, judge the
runs by the project's statistics (out-of-sample IC, decay, a cost-aware book, PSR and DSR at the trial count N), sweep,
explain and export them as `aq models` zips.

    from aether_quant import lab, samples
    data = lab.build_dataset(samples.load_sample_prices(), features="core")      # date, ticker, features, target_*, split
    lab.init_lab(Path("mylab")); lab.new_model(Path("mylab"), "m1", "multitask")
    record = lab.train_run(Path("mylab"), "m1")                                   # needs torch for mlp/multitask/tcn
    report = lab.evaluate_run(Path("mylab/runs") / record["id"], lab_dir=Path("mylab"), book=True)

`aq lab`, `aq dataset`, `aq features` and `aq data` are the same from the command line. Importing this module loads no
torch; the networks, losses and training mechanics (`AetherNet`, `soft_spearman_loss`, `set_seed`, ...) load on first use.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from features.feature_registry import FEATURES, SETS, FeatureSpec, build_long, build_wide, catalog, groups_of, resolve
from lab.data_explore import calendar_kind, explore, longest_gaps, read_closes, render_explore_html, render_info
from lab.data_explore import info as data_info
from lab.explain import ablate_run, explain_run, render_mapping, run_predictor, seed_stability
from lab.lab_dataset import (
    HoldoutSealed,
    build_dataset,
    dataset_info,
    default_splits,
    feature_columns,
    holdout_window,
    label_splits,
    leakage_report,
    load_dataset,
    parse_splits,
    rank_features,
    seal,
    target_columns,
)
from lab.model_export import export_files, export_run
from lab.model_export import write_zip as write_model_zip
from lab.model_templates import new_model, valid_name
from lab.objectives import CONTEXT_OBJECTIVES, RANKING_OBJECTIVES
from lab.report_html import fmt, legend, page, svg_bars, svg_heatmap, svg_histogram, svg_lines
from lab.report_html import table as html_table
from lab.run_evaluation import (
    baseline_scores,
    compare_runs,
    daily_ic,
    evaluate_run,
    half_life,
    ic_stats,
    load_run_frame,
    model_card,
    render_compare,
    render_eval,
    render_eval_html,
    sharpe_block,
    spread_returns,
    trial_variance,
)
from lab.run_registry import find_lab, find_run, init_lab, list_runs, new_run_id, read_run, render_runs, write_run
from lab.spec import TEMPLATES, load_spec, parse_override, read_toml
from lab.spec import merge as merge_spec
from lab.spec import validate as validate_spec
from lab.sweep import as_overrides, grid_points, parse_grid, run_sweep, sweep_pbo
from lab.trainer import (
    TorchMissing,
    fit_linear,
    fit_torch,
    head_of,
    ledger_count,
    load_model_module,
    make_folds,
    model_outputs,
    predict_linear,
    predict_torch,
    require_torch,
    sha256_file,
    spread_sharpe,
    train_run,
)

if TYPE_CHECKING:  # the torch-backed names `__getattr__` loads on first use
    from lab.architectures import (
        AetherNet,
        AetherNetMultiTask,
        AetherNetMultiTaskHorizons,
        AetherNetSequenceMultiTask,
        AetherNetSequenceMultiTaskHorizons,
        build_activation,
        build_normalization,
        enabled_extra_heads,
        export_architecture,
        export_multitask_architecture,
        export_multitask_horizons_architecture,
        export_sequence_multitask_architecture,
        export_sequence_multitask_horizons_architecture,
        export_state_dict,
        horizon_head_specs,
        resolve_horizon_head_config,
    )
    from lab.losses import (
        add_rank_label_noise,
        class_group_ids,
        compute_combined_multitask_loss,
        compute_cross_sectional_ranking_loss,
        compute_horizon_consistency_loss,
        ic_pearson_loss,
        listnet_loss,
        long_short_sharpe_loss,
        masked_bce_with_logits_loss,
        masked_mse_loss,
        rank_turnover_penalty,
        row_context_targets,
        soft_rank_within_groups,
        soft_spearman_loss,
    )
    from lab.training_utils import (
        CrossSectionalDateBatchSampler,
        build_cross_sectional_date_batches,
        build_date_group_ids,
        build_lr_scheduler,
        build_optimizer,
        is_new_best_epoch,
        select_device,
        set_seed,
        smoothed_metric,
        swa_accumulate,
        swa_finalize,
    )

_TORCH_NAMES = {
    "lab.architectures": (
        "AetherNet", "AetherNetMultiTask", "AetherNetMultiTaskHorizons", "AetherNetSequenceMultiTask", "AetherNetSequenceMultiTaskHorizons", "build_activation",
        "build_normalization", "enabled_extra_heads", "horizon_head_specs", "resolve_horizon_head_config", "export_state_dict", "export_architecture",
        "export_multitask_architecture", "export_multitask_horizons_architecture", "export_sequence_multitask_architecture", "export_sequence_multitask_horizons_architecture",
    ),
    "lab.losses": (
        "soft_rank_within_groups", "soft_spearman_loss", "listnet_loss", "ic_pearson_loss", "long_short_sharpe_loss", "row_context_targets", "class_group_ids",
        "rank_turnover_penalty", "compute_cross_sectional_ranking_loss", "masked_bce_with_logits_loss", "masked_mse_loss", "add_rank_label_noise",
        "compute_horizon_consistency_loss", "compute_combined_multitask_loss",
    ),
    "lab.training_utils": (
        "set_seed", "build_optimizer", "build_lr_scheduler", "swa_accumulate", "swa_finalize", "smoothed_metric", "is_new_best_epoch",
        "build_cross_sectional_date_batches", "CrossSectionalDateBatchSampler", "build_date_group_ids", "select_device",
    ),
}
_LAZY = {name: module for module, names in _TORCH_NAMES.items() for name in names}


def __getattr__(name: str) -> Any:
    """The torch-backed names, imported on first use so `import aether_quant.lab` stays light."""
    if name in _LAZY:
        value = getattr(importlib.import_module(_LAZY[name]), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'aether_quant.lab' has no attribute {name!r}")


__all__ = [
    "CONTEXT_OBJECTIVES", "FEATURES", "RANKING_OBJECTIVES", "SETS", "TEMPLATES", "FeatureSpec", "HoldoutSealed", "TorchMissing",
    "ablate_run", "as_overrides", "baseline_scores", "build_dataset", "build_long", "build_wide", "calendar_kind", "catalog", "compare_runs",
    "daily_ic", "data_info", "dataset_info", "default_splits", "evaluate_run", "explain_run", "explore", "export_files", "export_run", "feature_columns",
    "find_lab", "find_run", "fit_linear", "fit_torch", "fmt", "grid_points", "groups_of", "half_life", "head_of", "holdout_window", "html_table", "ic_stats",
    "init_lab", "label_splits", "leakage_report", "ledger_count", "legend", "list_runs", "load_dataset", "load_model_module", "load_run_frame", "load_spec",
    "longest_gaps", "make_folds", "merge_spec", "model_card", "model_outputs", "new_model", "new_run_id", "page", "parse_grid", "parse_override", "parse_splits",
    "predict_linear", "predict_torch", "rank_features", "read_closes", "read_run", "read_toml", "render_compare", "render_eval", "render_eval_html",
    "render_explore_html", "render_info", "render_mapping", "render_runs", "require_torch", "resolve", "run_predictor", "run_sweep", "seal", "seed_stability",
    "sha256_file", "sharpe_block", "spread_returns", "spread_sharpe", "svg_bars", "svg_heatmap", "svg_histogram", "svg_lines", "sweep_pbo", "target_columns",
    "train_run", "trial_variance", "valid_name", "validate_spec", "write_model_zip", "write_run",
    "AetherNet", "AetherNetMultiTask", "AetherNetMultiTaskHorizons", "AetherNetSequenceMultiTask", "AetherNetSequenceMultiTaskHorizons",
    "CrossSectionalDateBatchSampler", "add_rank_label_noise", "build_activation", "build_cross_sectional_date_batches", "build_date_group_ids",
    "build_lr_scheduler", "build_normalization", "build_optimizer", "class_group_ids", "compute_combined_multitask_loss",
    "compute_cross_sectional_ranking_loss", "compute_horizon_consistency_loss", "enabled_extra_heads", "export_architecture",
    "export_multitask_architecture", "export_multitask_horizons_architecture", "export_sequence_multitask_architecture",
    "export_sequence_multitask_horizons_architecture", "export_state_dict", "horizon_head_specs", "ic_pearson_loss", "is_new_best_epoch",
    "listnet_loss", "long_short_sharpe_loss", "masked_bce_with_logits_loss", "masked_mse_loss", "rank_turnover_penalty",
    "resolve_horizon_head_config", "row_context_targets", "select_device", "set_seed", "smoothed_metric", "soft_rank_within_groups",
    "soft_spearman_loss", "swa_accumulate", "swa_finalize",
]
