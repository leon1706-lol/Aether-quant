"""Offline trainer for the multi-task model: direction + return magnitude +
volatility + longer-horizon direction (5d/20d) + cross-sectional rank
(5d/20d) predicted jointly from one shared trunk (AetherNetMultiTaskHorizons,
train.py).

Separate script from train.py, same convention as train_gating.py/
train_topology.py: reads the already-built active dataset
(ml/datasets/full_dataset.csv) and the active feature_schema.json rather
than rebuilding the dataset itself, so this never touches train.py's own
CLI flow or its baseline/expert artifacts. Uses the exact same
model_input_names as the baseline model (scaled features + asset context) -
this phase does not change what the input feature set is, only what the
model predicts from it (see development/Changelog.md for why regime/
liquidity/topology-as-inputs was scoped out of an earlier pass).

Loss is BCEWithLogitsLoss(direction) + magnitude_loss_weight * MSE(magnitude)
+ volatility_loss_weight * MSE(volatility) + a masked BCE/MSE term per
enabled horizon head (direction_5d/20d, rank_5d/20d - see
train.py::masked_bce_with_logits_loss()/masked_mse_loss()), each row-masked
since these targets are NaN for the trailing rows of an asset's history
that don't yet have a full forward window (not dropped from the dataset -
see train.py::engineer_features()'s docstring). Early stopping and
threshold tuning both operate on the combined validation loss / direction
logits respectively - magnitude/volatility/rank heads are evaluated with
plain MAE/RMSE (train.py::compute_regression_metrics()), direction_5d/20d
with MCC/F1 (train.py::compute_masked_binary_metrics()), and rank_5d/20d
additionally get a rank-IC block (train.py::compute_rank_ic()) - the
cross-sectional signal's actual win condition, not MCC (meaningless for a
continuous/rank target).

Usage:
    python train_multitask.py --version-id <uuid> [--config-path config.json] [--dataset-path ml/datasets/full_dataset.csv]

Writes ml/versions/<version_id>/multitask_model.json, multitask_feature_schema.json
and multitask_training_metrics.json. Exits 0 (not an error) when there isn't
enough data yet - "skipped" must never look like "failed" to the caller,
mirroring train_gating.py/train_topology.py.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from train import (
    HORIZON_HEAD_SPECS,
    AetherNetMultiTaskHorizons,
    assess_net_performance_quality,
    assess_ranking_quality_from_predictions,
    assess_regression_quality,
    build_cross_sectional_date_batches,
    build_date_group_ids,
    build_lr_scheduler,
    build_optimizer,
    compute_binary_metrics,
    compute_combined_multitask_loss,
    compute_gate_friendliness_weight_by_date,
    compute_masked_binary_metrics,
    compute_masked_regression_metrics,
    compute_purged_cv_rank_ic_diagnostic,
    compute_rank_ic,
    compute_regression_metrics,
    export_multitask_horizons_architecture,
    export_state_dict,
    find_optimal_masked_threshold,
    find_optimal_threshold,
    is_new_best_epoch,
    load_sector_mapping,
    resolve_horizon_head_config,
    run_net_performance_simulation,
    set_seed,
    smoothed_metric,
    swa_accumulate,
    swa_finalize,
)

LOGGER = logging.getLogger("aether_quant.train_multitask")
ROOT = Path(__file__).resolve().parent
ML_DIR = ROOT / "ml"
CONFIG_PATH = ROOT / "config.json"
DATASET_PATH = ML_DIR / "datasets" / "full_dataset.csv"
FEATURE_SCHEMA_PATH = ML_DIR / "feature_schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether Quant multi-task (direction+magnitude+volatility+horizons) trainer")
    parser.add_argument("--version-id", type=str, required=True, help="Candidate model_version_id (UUID)")
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    parser.add_argument("--dataset-path", type=str, default=str(DATASET_PATH))
    # V5.1 Phase 4 (item 4) - previously FEATURE_SCHEMA_PATH was a hardcoded
    # module constant with no override, which meant this trainer could only
    # ever read the ACTIVE ml/feature_schema.json - fine for the normal
    # candidate-retraining path (which shares that active dataset/schema),
    # but a hard blocker for train.py::_run_walk_forward()'s per-window
    # subprocess calls, where each window has its own schema that does NOT
    # match the active one. Defaults to the module constant - a no-op for
    # every existing caller.
    parser.add_argument("--feature-schema-path", type=str, default=str(FEATURE_SCHEMA_PATH))
    # Stage 4 of the rank-pivot roadmap (development/Problems.md#43):
    # seed-ensembling support. Overrides config.json's multitask_training.seed
    # for THIS invocation only (never mutates config.json) - run this script
    # once per seed (e.g. --seed 42/43/44), each with its own --version-id,
    # writing independent candidates under ml/versions/. Combine their
    # backtest rank_20d predictions afterward with
    # train.py::aggregate_seed_ensemble_rank_ic() (average_ensemble_predictions()
    # is prediction-averaging, not weight-averaging - see its docstring for
    # why that's the only statistically valid form here). Defaults to None
    # (use config.json's seed unchanged) - zero behavior change for anyone
    # not passing this flag.
    parser.add_argument("--seed", type=int, default=None, help="Override config.json's seed for this run (seed-ensembling)")
    # V5.1 Phase 3 (item 1) - one-run A/B override without editing config.json,
    # same precedent as --seed immediately above. None (default) leaves
    # training_config["ranking_loss"]["objective"] unchanged.
    parser.add_argument(
        "--ranking-objective",
        type=str,
        default=None,
        choices=["mse", "soft_spearman", "listnet"],
        help="Override config.json's ranking_loss.objective for this run only (A/B testing)",
    )
    return parser.parse_args()


def load_multitask_training_config(config_path: Path = CONFIG_PATH) -> dict:
    with Path(config_path).open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("retraining", {}).get("multitask_training", {})


def multitask_candidate_output_paths(version_id: str) -> dict[str, Path]:
    """Own local helper mirroring train_gating.py's gating_candidate_output_paths()
    - kept independent of train.py's own candidate_output_paths() since the
    two write disjoint filenames."""
    version_dir = ML_DIR / "versions" / version_id
    return {
        "version_dir": version_dir,
        "multitask_model": version_dir / "multitask_model.json",
        "multitask_feature_schema": version_dir / "multitask_feature_schema.json",
        "multitask_training_metrics": version_dir / "multitask_training_metrics.json",
    }


def frame_to_multitask_tensors(frame: pd.DataFrame, feature_names: list[str]) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Returns (features, targets) where targets is a dict keyed by head
    name - direction/magnitude/volatility are never NaN (engineer_features()'s
    required_columns dropna already guarantees this), the 4 horizon heads
    may be NaN for a trailing few rows per asset (see
    HORIZON_HEAD_SPECS/masked_bce_with_logits_loss()'s docstring)."""
    features = torch.tensor(frame[feature_names].to_numpy(dtype=np.float32), dtype=torch.float32)
    targets = {
        "direction": torch.tensor(frame["target_direction"].to_numpy(dtype=np.float32), dtype=torch.float32),
        "magnitude": torch.tensor(frame["target_return_1d"].to_numpy(dtype=np.float32), dtype=torch.float32),
        "volatility": torch.tensor(frame["target_volatility_next_day"].to_numpy(dtype=np.float32), dtype=torch.float32),
    }
    for head_name, (column, _kind, _stride) in HORIZON_HEAD_SPECS.items():
        targets[head_name] = torch.tensor(frame[column].to_numpy(dtype=np.float32), dtype=torch.float32)
    return features, targets


def compute_multitask_metrics(
    model: AetherNetMultiTaskHorizons,
    features: torch.Tensor,
    targets: dict[str, torch.Tensor],
    dates: pd.Series,
    direction_criterion: nn.Module,
    threshold: float,
    head_thresholds: dict[str, float],
    horizon_head_config: dict,
    ranking_promotion_config: dict | None = None,
    net_performance_context: dict | None = None,
) -> dict:
    """net_performance_context (V5.1 Phase 4, items 7/12), only passed by
    the BACKTEST split call site (same convention as ranking_promotion_config
    above): {"raw_frame": pd.DataFrame with ticker/date/target_return_1d,
    row-aligned with `features`/`dates`; "net_performance_config": dict;
    "sector_by_ticker": dict; "head": str - which HORIZON_HEAD_SPECS head
    to run the simulation for; "full_config": the full config.json, for
    assess_net_performance_quality()'s promotion_gate lookup}. Writes
    metrics[f"{head}_net_performance"] via train.py::
    run_net_performance_simulation()/assess_net_performance_quality() - the
    same simulator train.py::_run_walk_forward()'s per-window evaluation
    and `aq evaluate --rank-book` both use, so this number is directly
    comparable to those, not a re-derived approximation."""
    model.eval()
    with torch.no_grad():
        outputs = model(features)
    metrics = {
        "direction": compute_binary_metrics(outputs["direction"], targets["direction"], direction_criterion, threshold),
        "magnitude": compute_regression_metrics(outputs["magnitude"], targets["magnitude"]),
        "volatility": compute_regression_metrics(outputs["volatility"], targets["volatility"]),
    }
    for head_name, (_column, kind, stride) in HORIZON_HEAD_SPECS.items():
        if not horizon_head_config[head_name].get("enabled", True):
            metrics[head_name] = None
            continue
        if kind == "binary":
            metrics[head_name] = compute_masked_binary_metrics(
                outputs[head_name], targets[head_name], direction_criterion, head_thresholds.get(head_name, 0.5)
            )
        else:
            metrics[head_name] = compute_masked_regression_metrics(outputs[head_name], targets[head_name])
            metrics[f"{head_name}_ic"] = compute_rank_ic(outputs[head_name], targets[head_name], dates)
            metrics[f"{head_name}_ic_non_overlapping"] = compute_rank_ic(
                outputs[head_name], targets[head_name], dates, non_overlapping_stride=stride
            )
            # Phase 2 of the 5/10 -> 9/10 roadmap: the code-enforced
            # promotion-gate verdict, only computed for the BACKTEST split
            # (ranking_promotion_config passed only by that call site) -
            # see train_sequence.py::compute_sequence_multitask_metrics()'s
            # identical wiring and train.py::assess_ranking_quality_from_predictions()'s
            # docstring.
            if ranking_promotion_config is not None:
                mask = ~torch.isnan(targets[head_name])
                dates_masked = np.asarray(dates)[mask.detach().cpu().numpy()]
                metrics[f"{head_name}_ranking_quality"] = assess_ranking_quality_from_predictions(
                    outputs[head_name][mask],
                    targets[head_name][mask],
                    dates_masked,
                    non_overlapping_stride=stride,
                    config=ranking_promotion_config,
                )
            if net_performance_context is not None and net_performance_context.get("head") == head_name:
                raw_frame = net_performance_context["raw_frame"].copy()
                raw_frame["_predicted_head"] = outputs[head_name].detach().cpu().numpy()
                net_performance_result = run_net_performance_simulation(
                    raw_frame, "_predicted_head",
                    net_performance_context["net_performance_config"],
                    net_performance_context["sector_by_ticker"],
                )
                if net_performance_result is not None:
                    metrics[f"{head_name}_net_performance"] = assess_net_performance_quality(
                        net_performance_result["simulation"],
                        net_performance_result["capacity"],
                        net_performance_result["stress"],
                        net_performance_context["full_config"],
                    )
    return metrics


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()

    try:
        training_config = load_multitask_training_config(Path(args.config_path))
        # Phase 2 of the 5/10 -> 9/10 roadmap: assess_ranking_quality_from_predictions()
        # needs phase1.target.ranking.promotion_gate, which lives in the
        # FULL config.json, not the narrow multitask_training sub-dict -
        # see train.py::assess_ranking_quality_from_predictions()'s docstring.
        full_config = json.loads(Path(args.config_path).read_text(encoding="utf-8"))
        if not bool(training_config.get("enabled", True)):
            LOGGER.info("train_multitask: disabled via config - skipping.")
            return 0

        min_train_rows = int(training_config.get("min_train_rows", 100))
        min_validation_rows = int(training_config.get("min_validation_rows", 20))
        min_backtest_rows = int(training_config.get("min_backtest_rows", 20))
        hidden_layers = list(training_config.get("hidden_layers", [64, 32]))
        dropout = float(training_config.get("dropout", 0.15))
        activation = str(training_config.get("activation", "relu"))
        normalization = str(training_config.get("normalization", "layernorm"))
        learning_rate = float(training_config.get("learning_rate", 0.0007))
        weight_decay = float(training_config.get("weight_decay", 0.0001))
        batch_size = int(training_config.get("batch_size", 64))
        max_epochs = int(training_config.get("epochs", 120))
        patience = int(training_config.get("patience", 18))
        decision_threshold = float(training_config.get("decision_threshold", 0.5))
        threshold_metric = str(training_config.get("optimize_threshold_metric", "mcc"))
        threshold_min = float(training_config.get("threshold_search_min", 0.35))
        threshold_max = float(training_config.get("threshold_search_max", 0.65))
        threshold_steps = int(training_config.get("threshold_search_steps", 61))
        magnitude_loss_weight = float(training_config.get("magnitude_loss_weight", 1.0))
        volatility_loss_weight = float(training_config.get("volatility_loss_weight", 1.0))
        # Stage 4 of the rank-pivot roadmap - see
        # compute_combined_multitask_loss()'s docstring for why this
        # defaults to 1.0 (fully backward-compatible) but config.json sets
        # it low for this trainer specifically: the primary "direction" head
        # is a near-noise 1-day objective main.py never reads.
        direction_loss_weight = float(training_config.get("direction_loss_weight", 1.0))
        # Stage 4 of the rank-pivot roadmap - see
        # compute_horizon_consistency_loss()'s docstring. Defaults to 0.0
        # (fully backward-compatible - a zero weight adds zero gradient);
        # config.json sets this to a small positive value for this trainer.
        consistency_loss_weight = float(training_config.get("consistency_loss_weight", 0.0))
        horizon_head_config = resolve_horizon_head_config(training_config)
        # --seed (if passed) wins over config.json for this invocation only -
        # see parse_args()'s docstring for the seed-ensembling workflow.
        seed = int(args.seed) if args.seed is not None else int(training_config.get("seed", 42))

        # V5.1 Phase 3 (items 1, 10, 11) - "random"/"none"/"adam" are every
        # FUNCTION default below (build_optimizer/build_lr_scheduler/
        # batch construction), so an older config.json missing this whole
        # block reproduces today's training run byte-for-byte.
        batch_mode = str(training_config.get("batch_mode", "random"))
        cross_sectional_batch_dates = int(training_config.get("cross_sectional_batch_dates", 4))
        min_cross_sectional_group_size = int(training_config.get("min_cross_sectional_group_size", 20))
        ranking_loss_config = training_config.get("ranking_loss") if batch_mode == "cross_sectional" else None
        if ranking_loss_config is not None and args.ranking_objective is not None:
            ranking_loss_config = {**ranking_loss_config, "objective": args.ranking_objective}
        # V5.2.8 (development/Problems.md #94) - opt-in, default-off gate-
        # aware ranking weight (see compute_gate_friendliness_weight_by_date()'s
        # own docstring). Same "nested under this trainer's own config
        # block" convention as ranking_loss immediately above, not a
        # separate shared namespace. Only meaningful when a ranking loss
        # is actually active - byte-identical to before this existed
        # whenever disabled or ranking_loss_config is None.
        gate_aware_ranking_weights_enabled = (
            ranking_loss_config is not None
            and bool(training_config.get("gate_aware_ranking_weights", {}).get("enabled", False))
        )
        risk_off_override_min_severity = float(
            full_config.get("phase_v2", {}).get("regime_detection", {}).get("risk_off_override_min_severity") or 0.0
        )
        swa_config = training_config.get("swa", {})
        swa_enabled = bool(swa_config.get("enabled", False))
        swa_start_epoch_fraction = float(swa_config.get("start_epoch_fraction", 0.7))
        early_stop_head = str(training_config.get("early_stop_head", "rank_20d"))
        early_stop_smoothing_epochs = int(training_config.get("early_stop_smoothing_epochs", 1))

        feature_schema_path = Path(args.feature_schema_path)
        if not feature_schema_path.exists():
            LOGGER.info("train_multitask: missing feature schema at %s - skipping.", feature_schema_path)
            return 0
        with feature_schema_path.open("r", encoding="utf-8") as f:
            feature_schema = json.load(f)
        feature_names = list(feature_schema["model_input_names"])

        dataset_path = Path(args.dataset_path)
        if not dataset_path.exists():
            LOGGER.info("train_multitask: dataset not found at %s - skipping.", dataset_path)
            return 0
        dataset = pd.read_csv(dataset_path)

        # Horizon target columns are NOT required here the way the core 3
        # are - an older dataset built before Phase 3/4 shipped simply
        # won't have them, in which case every horizon head trains on an
        # all-NaN column (masked loss/metrics degrade to a true no-op, see
        # masked_bce_with_logits_loss()'s docstring), same graceful
        # backward-compatibility contract as every other optional stage in
        # this pipeline.
        required_columns = set(feature_names) | {
            "target_direction",
            "target_return_1d",
            "target_volatility_next_day",
            "split",
            "date",
        }
        missing_columns = required_columns - set(dataset.columns)
        if missing_columns:
            LOGGER.info("train_multitask: dataset missing columns %s - skipping.", sorted(missing_columns))
            return 0
        for head_name, (column, _kind, _stride) in HORIZON_HEAD_SPECS.items():
            if column not in dataset.columns:
                dataset[column] = np.nan
                horizon_head_config[head_name] = {**horizon_head_config[head_name], "enabled": False}
                LOGGER.info("train_multitask: dataset missing %s - disabling %s head.", column, head_name)

        eligible = dataset
        if "training_eligible" in dataset.columns:
            eligible = dataset[dataset["training_eligible"]].copy()

        train_frame = eligible[eligible["split"] == "train"].reset_index(drop=True)
        validation_frame = eligible[eligible["split"] == "validation"].reset_index(drop=True)
        backtest_frame = eligible[eligible["split"] == "backtest"].reset_index(drop=True)

        if len(train_frame) < min_train_rows or len(validation_frame) < min_validation_rows or len(backtest_frame) < min_backtest_rows:
            LOGGER.info(
                "train_multitask: only %d train / %d validation / %d backtest rows "
                "(need >= %d / %d / %d) - skipping, not writing artifacts.",
                len(train_frame),
                len(validation_frame),
                len(backtest_frame),
                min_train_rows,
                min_validation_rows,
                min_backtest_rows,
            )
            return 0

        set_seed(seed)
        device = torch.device("cpu")

        train_features, train_targets = frame_to_multitask_tensors(train_frame, feature_names)
        validation_features, validation_targets = frame_to_multitask_tensors(validation_frame, feature_names)
        validation_features = validation_features.to(device)
        validation_targets = {name: tensor.to(device) for name, tensor in validation_targets.items()}

        target_names_sorted = sorted(train_targets)
        # V5.1 Phase 3 (item 1) - "random" (default) reproduces today's
        # DataLoader byte-for-byte; "cross_sectional" batches are built
        # fresh per epoch further down (needs a fresh seed+epoch shuffle,
        # see build_cross_sectional_date_batches()'s docstring), and
        # train_date_group_ids is only computed when a ranking loss is
        # actually configured to use it.
        if batch_mode == "cross_sectional":
            train_loader = None
        else:
            train_loader = DataLoader(
                TensorDataset(
                    train_features,
                    *[train_targets[name] for name in target_names_sorted],
                ),
                batch_size=batch_size,
                shuffle=True,
            )
        train_dates_array = train_frame["date"].to_numpy()
        train_date_group_ids = build_date_group_ids(train_dates_array) if ranking_loss_config is not None else None
        validation_date_group_ids = (
            torch.as_tensor(build_date_group_ids(validation_frame["date"].to_numpy()), dtype=torch.int64, device=device)
            if ranking_loss_config is not None
            else None
        )
        # V5.2.8 (development/Problems.md #94) - per-ROW weight tensor
        # aligned to train_date_group_ids (each row gets its date's own
        # weight), built once here rather than per-batch/per-epoch since
        # neither the dataset nor the config changes during training.
        # None whenever the feature is disabled - byte-identical training
        # loop below in that case.
        if gate_aware_ranking_weights_enabled:
            weight_by_date = compute_gate_friendliness_weight_by_date(train_frame, risk_off_override_min_severity)
            train_date_weights = torch.as_tensor(
                [weight_by_date.get(str(date), 1.0) for date in train_dates_array], dtype=torch.float32
            )
        else:
            train_date_weights = None

        model = AetherNetMultiTaskHorizons(
            input_dim=len(feature_names),
            hidden_layers=hidden_layers,
            dropout=dropout,
            activation=activation,
            normalization=normalization,
        ).to(device)

        # V5.1 Phase 3 (item 11) - "adam" is build_optimizer()'s own
        # FUNCTION default (byte-identical to the plain torch.optim.Adam
        # call this replaces, when training_config has no "optimizer" key).
        optimizer = build_optimizer(model, training_config)
        scheduler = build_lr_scheduler(optimizer, training_config, max_epochs)
        swa_state: dict | None = None
        swa_count = 0
        swa_start_epoch = max(1, int(round(max_epochs * swa_start_epoch_fraction))) if swa_enabled else None
        positive_count = max(float(train_frame["target_direction"].sum()), 1.0)
        negative_count = max(float(len(train_frame) - train_frame["target_direction"].sum()), 1.0)
        pos_weight = torch.tensor(negative_count / positive_count, dtype=torch.float32, device=device)
        direction_criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        best_state = None
        best_epoch = 0
        best_validation_metric = float("-inf")
        epochs_without_improvement = 0
        history: list[dict] = []
        min_best_epoch = int(training_config.get("min_best_epoch", 3))
        # Stage 4 of the rank-pivot roadmap (development/Problems.md#43): the
        # comment this replaces documented an EARLIER attempt at fixing this
        # same untrained-init bug by monitoring direction balanced-accuracy
        # instead of loss - that measurably improved direction MCC but
        # DEGRADED the sibling sequence model's rank_20d backtest signal
        # (non-overlapping t-stat 2.90 -> 2.21, confirmed by direct
        # comparison). This model's actual downstream consumer is
        # main.py's portfolio_book (predicted_rank_20d), not the direction
        # head at all - monitoring validation rank_20d mean IC directly is a
        # third, previously-untried option (not a repeat of the balanced-
        # accuracy regression above), so it's config-gated
        # (early_stop_metric) rather than a silent hardcoded switch: revert
        # to the previous "validation_loss" behavior in one config edit if a
        # future comparison shows the same kind of regression. Falls back to
        # "validation_loss" automatically if the rank_20d head itself is
        # disabled/missing - monitoring an IC that doesn't exist is not a
        # valid choice regardless of what this key says.
        # early_stop_head/early_stop_smoothing_epochs (V5.1 Phase 3):
        # generalizes the rank_20d-only monitor above to any HORIZON_HEAD_SPECS
        # head, and smooths the monitored value over the last N epochs
        # before comparing - a 365-day validation split at stride 20 gives
        # only ~18 non-overlapping IC observations, so early-stopping on
        # the RAW per-epoch value reliably picks a lucky epoch.
        # early_stop_smoothing_epochs defaults to 1 (smoothed_metric()'s
        # own byte-identical-to-"raw value" case), and early_stop_head
        # defaults to "rank_20d" - together, an old config.json with
        # neither key reproduces the exact "rank_20d" monitoring behavior
        # this block replaces.
        early_stop_metric = str(training_config.get("early_stop_metric", "rank_ic"))
        monitor_rank_ic = (
            early_stop_metric in ("rank_ic", "rank_ic_non_overlapping")
            and early_stop_head in horizon_head_config
            and early_stop_head in HORIZON_HEAD_SPECS
            and horizon_head_config[early_stop_head].get("enabled", True)
        )
        monitored_metric_key = f"validation_{early_stop_head}_mean_ic"
        if early_stop_metric == "rank_ic_non_overlapping":
            monitored_metric_key = f"validation_{early_stop_head}_non_overlapping_mean_ic"

        for epoch in range(1, max_epochs + 1):
            model.train()
            running_loss = 0.0
            sample_count = 0

            if batch_mode == "cross_sectional":
                epoch_batches = build_cross_sectional_date_batches(
                    train_dates_array,
                    batch_dates=cross_sectional_batch_dates,
                    min_group_size=min_cross_sectional_group_size,
                    shuffle=True,
                    seed=seed + epoch,
                )
                batch_source = (
                    (
                        train_features[torch.as_tensor(row_indices, dtype=torch.long)].to(device),
                        {
                            name: train_targets[name][torch.as_tensor(row_indices, dtype=torch.long)].to(device)
                            for name in target_names_sorted
                        },
                        torch.as_tensor(train_date_group_ids[row_indices], dtype=torch.int64, device=device)
                        if train_date_group_ids is not None
                        else None,
                        train_date_weights[torch.as_tensor(row_indices, dtype=torch.long)].to(device)
                        if train_date_weights is not None
                        else None,
                    )
                    for row_indices in epoch_batches
                )
            else:
                batch_source = (
                    (
                        batch[0].to(device),
                        {name: tensor.to(device) for name, tensor in zip(target_names_sorted, batch[1:])},
                        None,
                        None,
                    )
                    for batch in train_loader
                )

            for batch_features, batch_targets, batch_group_ids, batch_date_weights in batch_source:
                optimizer.zero_grad()
                outputs = model(batch_features)
                loss = compute_combined_multitask_loss(
                    outputs,
                    batch_targets,
                    direction_criterion,
                    magnitude_loss_weight,
                    volatility_loss_weight,
                    horizon_head_config,
                    direction_loss_weight,
                    consistency_loss_weight,
                    date_group_ids=batch_group_ids,
                    ranking_loss_config=ranking_loss_config,
                    date_weights=batch_date_weights,
                )
                loss.backward()
                optimizer.step()

                running_loss += float(loss.item()) * len(batch_features)
                sample_count += len(batch_features)

            if scheduler is not None:
                scheduler.step()

            model.eval()
            with torch.no_grad():
                validation_outputs = model(validation_features)
                validation_loss = compute_combined_multitask_loss(
                    validation_outputs,
                    validation_targets,
                    direction_criterion,
                    magnitude_loss_weight,
                    volatility_loss_weight,
                    horizon_head_config,
                    direction_loss_weight,
                    consistency_loss_weight,
                    date_group_ids=validation_date_group_ids,
                    ranking_loss_config=ranking_loss_config,
                )
            # validation_direction_metrics is always computed and recorded
            # for diagnostics regardless of what's actually monitored below
            # (see monitor_rank_ic's assignment above for the monitoring
            # decision itself).
            validation_direction_metrics = compute_binary_metrics(
                validation_outputs["direction"], validation_targets["direction"], direction_criterion, decision_threshold
            )

            validation_head_ic = None
            if monitor_rank_ic:
                _column, _kind, head_stride = HORIZON_HEAD_SPECS[early_stop_head]
                non_overlapping_stride = head_stride if early_stop_metric == "rank_ic_non_overlapping" else 1
                validation_head_ic = compute_rank_ic(
                    validation_outputs[early_stop_head],
                    validation_targets[early_stop_head],
                    validation_frame["date"],
                    non_overlapping_stride=non_overlapping_stride,
                )

            history_entry = {
                "epoch": epoch,
                "train_loss": running_loss / max(sample_count, 1),
                "validation_loss": float(validation_loss.item()),
                "validation_direction_balanced_accuracy": validation_direction_metrics["balanced_accuracy"],
            }
            if validation_head_ic is not None:
                history_entry[monitored_metric_key] = validation_head_ic["mean_ic"]
                # Backward-compat key, kept exactly as before, for any
                # existing dashboard/consumer reading this specific name
                # when monitoring rank_20d via the original "rank_ic" mode.
                if early_stop_metric == "rank_ic" and early_stop_head == "rank_20d":
                    history_entry["validation_rank_20d_mean_ic"] = validation_head_ic["mean_ic"]
            history.append(history_entry)

            if monitor_rank_ic:
                smoothed = smoothed_metric(history, monitored_metric_key, early_stop_smoothing_epochs)
                candidate_metric = smoothed if smoothed is not None else -float(validation_loss.item())
            else:
                candidate_metric = -float(validation_loss.item())

            if swa_enabled and swa_start_epoch is not None and epoch >= swa_start_epoch:
                swa_state, swa_count = swa_accumulate(swa_state, model.state_dict(), swa_count)

            if is_new_best_epoch(candidate_metric, best_validation_metric, epoch, min_best_epoch):
                best_validation_metric = candidate_metric
                best_epoch = epoch
                best_state = copy.deepcopy(model.state_dict())
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1

            if epoch >= min_best_epoch and epochs_without_improvement >= patience:
                break

        # V5.1 Phase 3 (item 10) - SWA (when enabled and at least one epoch
        # was accumulated) REPLACES the single best-validation-epoch
        # checkpoint with the averaged tail-of-training weights - see
        # swa_accumulate()'s docstring for why this is a valid, different
        # technique from the ensemble-averaging this codebase already
        # rejects. best_epoch is left as whatever epoch loop variable value
        # it last held (informational only in this branch - "best_epoch"
        # stops meaning "the single checkpoint used" once SWA is active,
        # see the swa metrics block below for the authoritative record).
        if swa_enabled and swa_state is not None:
            best_state = swa_finalize(swa_state)
        elif best_state is None:
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = len(history)

        model.load_state_dict(best_state)
        model.eval()
        with torch.no_grad():
            validation_outputs_for_threshold = model(validation_features)
        tuned_threshold, tuned_validation_direction_metrics = find_optimal_threshold(
            validation_outputs_for_threshold["direction"],
            validation_targets["direction"],
            direction_criterion,
            threshold_metric,
            threshold_min,
            threshold_max,
            threshold_steps,
        )
        # Each binary horizon head gets its OWN tuned threshold from its own
        # validation logit distribution - see find_optimal_masked_threshold()'s
        # docstring for why reusing the primary head's threshold is wrong.
        head_thresholds = {"direction": tuned_threshold}
        for head_name, (_column, kind, _stride) in HORIZON_HEAD_SPECS.items():
            if kind != "binary" or not horizon_head_config[head_name].get("enabled", True):
                continue
            head_threshold, _head_metrics = find_optimal_masked_threshold(
                validation_outputs_for_threshold[head_name],
                validation_targets[head_name],
                direction_criterion,
                threshold_metric,
                threshold_min,
                threshold_max,
                threshold_steps,
            )
            head_thresholds[head_name] = head_threshold if head_threshold is not None else 0.5

        train_features_device = train_features.to(device)
        train_targets_device = {name: tensor.to(device) for name, tensor in train_targets.items()}
        backtest_features, backtest_targets = frame_to_multitask_tensors(backtest_frame, feature_names)
        backtest_features = backtest_features.to(device)
        backtest_targets = {name: tensor.to(device) for name, tensor in backtest_targets.items()}

        trained_at = datetime.now(timezone.utc).isoformat()
        # V5.1 Phase 4 (items 7, 12) - net-performance simulation context,
        # only meaningful for the BACKTEST split (same convention as
        # ranking_promotion_config below). Config-gated: an absent/disabled
        # phase1.target.ranking.net_performance block leaves
        # net_performance_context None, and compute_multitask_metrics()
        # then writes no *_net_performance key at all - zero behavior
        # change for anyone not opting in.
        net_performance_config = full_config.get("phase1", {}).get("target", {}).get("ranking", {}).get(
            "net_performance", {}
        )
        net_performance_context = (
            {
                "raw_frame": backtest_frame,
                "net_performance_config": net_performance_config,
                "sector_by_ticker": load_sector_mapping(full_config),
                "head": str(net_performance_config.get("head", "rank_20d")),
                "full_config": full_config,
            }
            if net_performance_config.get("enabled", False)
            else None
        )

        metrics = {
            "project": "aether_quant",
            "phase": "multitask_direction_magnitude_volatility_horizons",
            "version_id": args.version_id,
            "trained_at": trained_at,
            "row_counts": {
                "train": int(len(train_frame)),
                "validation": int(len(validation_frame)),
                "backtest": int(len(backtest_frame)),
            },
            "seed": seed,
            "best_epoch": best_epoch,
            "early_stop_metric": f"{early_stop_head}_ic" if monitor_rank_ic else "validation_loss",
            "epochs_ran": len(history),
            "loss_weights": {
                "magnitude_loss_weight": magnitude_loss_weight,
                "volatility_loss_weight": volatility_loss_weight,
            },
            # V5.1 Phase 3 (items 1, 10, 11) - the training recipe actually
            # used for this candidate, so "which model am I looking at" is
            # answerable from the artifact alone (see
            # src/components/neuralnet/TrainingRecipePanel.tsx).
            "training_recipe": {
                "optimizer": str(training_config.get("optimizer", "adam")),
                "lr_schedule": str(training_config.get("lr_schedule", "none")),
                "batch_mode": batch_mode,
                "ranking_loss": ranking_loss_config,
                "swa": {"enabled": swa_enabled, "epochs_averaged": swa_count if swa_enabled else 0},
                "early_stop_metric": early_stop_metric,
                "early_stop_head": early_stop_head,
                "early_stop_smoothing_epochs": early_stop_smoothing_epochs,
            },
            "horizon_heads": horizon_head_config,
            "threshold_optimization": {
                "metric": threshold_metric,
                "default_threshold": decision_threshold,
                "selected_threshold": tuned_threshold,
                "selected_validation_metrics": tuned_validation_direction_metrics,
                "head_thresholds": head_thresholds,
            },
            "train": compute_multitask_metrics(
                model, train_features_device, train_targets_device, train_frame["date"],
                direction_criterion, tuned_threshold, head_thresholds, horizon_head_config,
            ),
            "validation": compute_multitask_metrics(
                model, validation_features, validation_targets, validation_frame["date"],
                direction_criterion, tuned_threshold, head_thresholds, horizon_head_config,
            ),
            "backtest": compute_multitask_metrics(
                model, backtest_features, backtest_targets, backtest_frame["date"],
                direction_criterion, tuned_threshold, head_thresholds, horizon_head_config,
                ranking_promotion_config=full_config,
                net_performance_context=net_performance_context,
            ),
            "history": history,
        }
        # Stage 5 of the rank-pivot roadmap (development/Problems.md#43):
        # actually invokes purged_embargoed_folds() via
        # compute_purged_cv_rank_ic_diagnostic() - see that function's
        # docstring for why phase1.target.ranking.purged_cv.enabled was
        # previously dead configuration (zero call sites). Evaluates the
        # SAME already-trained model over the TRAIN split's own purged/
        # embargoed folds - no extra training. Only runs when the rank_20d
        # head itself is enabled (an IC diagnostic for a disabled head is
        # meaningless).
        purged_cv_config = full_config.get("phase1", {}).get("target", {}).get("ranking", {}).get("purged_cv", {})
        if purged_cv_config.get("enabled", False) and horizon_head_config["rank_20d"].get("enabled", True):
            model.eval()
            with torch.no_grad():
                train_outputs_for_purged_cv = model(train_features_device)
            metrics["purged_cv_rank_20d"] = compute_purged_cv_rank_ic_diagnostic(
                train_outputs_for_purged_cv["rank_20d"],
                train_targets_device["rank_20d"],
                train_frame["date"],
                n_folds=int(purged_cv_config.get("n_folds", 5)),
                horizon_days=20,
                embargo_days=int(purged_cv_config.get("embargo_days", 5)),
            )
        metrics["magnitude_quality"] = assess_regression_quality(
            {
                "train": metrics["train"]["magnitude"],
                "validation": metrics["validation"]["magnitude"],
                "backtest": metrics["backtest"]["magnitude"],
            },
            training_config,
        )
        metrics["volatility_quality"] = assess_regression_quality(
            {
                "train": metrics["train"]["volatility"],
                "validation": metrics["validation"]["volatility"],
                "backtest": metrics["backtest"]["volatility"],
            },
            training_config,
        )

        model_payload = {
            "project": "Aether Quant",
            "phase": "v2_multitask_horizons_model",
            "version_id": args.version_id,
            "status": "trained",
            "trained_at": trained_at,
            "model": {
                "type": "multitask_direction_magnitude_volatility_horizons",
                "model_input_features": feature_names,
                "hidden_layers": hidden_layers,
                "dropout": dropout,
                "activation": activation,
                "normalization": normalization,
                "decision_threshold": tuned_threshold,
            },
            "export": export_multitask_horizons_architecture(model) | {"state_dict": export_state_dict(model)},
        }
        feature_schema_payload = {"model_input_names": feature_names}

        paths = multitask_candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        paths["multitask_model"].write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        paths["multitask_feature_schema"].write_text(json.dumps(feature_schema_payload, indent=2), encoding="utf-8")
        paths["multitask_training_metrics"].write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        rank_5d_ic = metrics["backtest"].get("rank_5d_ic") or {}
        LOGGER.info(
            "train_multitask: wrote multitask artifacts for version %s "
            "(backtest direction mcc=%.4f, magnitude mae=%.6f [%s], volatility mae=%.6f [%s], "
            "rank_5d mean_ic=%.4f t_stat=%.2f).",
            args.version_id,
            metrics["backtest"]["direction"]["mcc"],
            metrics["backtest"]["magnitude"]["mae"],
            metrics["magnitude_quality"]["quality_status"],
            metrics["backtest"]["volatility"]["mae"],
            metrics["volatility_quality"]["quality_status"],
            rank_5d_ic.get("mean_ic", 0.0),
            rank_5d_ic.get("t_stat", 0.0),
        )
        return 0
    except Exception as exc:  # never let an unexpected failure look ambiguous to the caller
        LOGGER.error("train_multitask: unexpected failure - %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
