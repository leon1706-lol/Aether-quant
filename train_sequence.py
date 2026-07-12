"""Offline trainer for the Phase 2 sequence-encoder multitask model:
direction + return magnitude + volatility + longer-horizon direction
(5d/20d) + cross-sectional rank (5d/20d) predicted from a causal TCN trunk
over a rolling window of bars, instead of Phase 1's flat-MLP trunk
(AetherNetMultiTaskHorizons/train_multitask.py) collapsing each bar into
one row.

This is the "genuinely new temporal structure" step the original root-
cause investigation called out as still missing after Phase 1 shipped
(direction+magnitude+volatility prediction, but still zero temporal
structure in the trunk itself). See train.py::AetherNetSequenceMultiTask's
docstring for why a causal TCN was chosen over a Transformer encoder block
for this first real sequence model (interpreter support for attention -
inference/exported_model.py::_multihead_attention() - already exists and
is tested, just not wired to a trained export yet).

Same convention as train_multitask.py: reads the already-built active
dataset (ml/datasets/full_dataset.csv) and feature_schema.json's
model_input_names, needs no new feature engineering - train.py::
build_sequence_tensor_dataset() only windows over the same model_input
vector the flat multitask model already consumes, using each row's own
trailing history within its ticker. Shares train.py's horizon-head
machinery (HORIZON_HEAD_SPECS/resolve_horizon_head_config()/
compute_combined_multitask_loss()/find_optimal_masked_threshold()) with
train_multitask.py - both trainers' Horizons model variants expose
identically-named heads, so the loss/threshold/config logic is
genuinely shared, not duplicated (see train.py's docstrings for why this
codebase's usual "new sibling function" convention doesn't apply here).

Usage:
    python train_sequence.py --version-id <uuid> [--config-path config.json] [--dataset-path ml/datasets/full_dataset.csv]

Writes ml/versions/<version_id>/sequence_model.json, sequence_feature_schema.json
and sequence_training_metrics.json. Exits 0 (not an error) when there isn't
enough data yet - "skipped" must never look like "failed" to the caller,
mirroring train_multitask.py/train_gating.py/train_topology.py.
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

from train import (
    HORIZON_HEAD_SPECS,
    AetherNetSequenceMultiTaskHorizons,
    assess_ranking_quality_from_predictions,
    assess_regression_quality,
    build_sequence_tensor_dataset,
    compute_binary_metrics,
    compute_combined_multitask_loss,
    compute_masked_binary_metrics,
    compute_masked_regression_metrics,
    compute_rank_ic,
    compute_regression_metrics,
    export_sequence_multitask_horizons_architecture,
    export_state_dict,
    find_optimal_masked_threshold,
    find_optimal_threshold,
    resolve_horizon_head_config,
    set_seed,
)

LOGGER = logging.getLogger("aether_quant.train_sequence")
ROOT = Path(__file__).resolve().parent
ML_DIR = ROOT / "ml"
CONFIG_PATH = ROOT / "config.json"
DATASET_PATH = ML_DIR / "datasets" / "full_dataset.csv"
FEATURE_SCHEMA_PATH = ML_DIR / "feature_schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether Quant Phase 2 sequence-encoder trainer")
    parser.add_argument("--version-id", type=str, required=True, help="Candidate model_version_id (UUID)")
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    parser.add_argument("--dataset-path", type=str, default=str(DATASET_PATH))
    return parser.parse_args()


def load_sequence_training_config(config_path: Path = CONFIG_PATH) -> dict:
    with Path(config_path).open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("retraining", {}).get("sequence_training", {})


def sequence_candidate_output_paths(version_id: str) -> dict[str, Path]:
    """Own local helper mirroring train_multitask.py's
    multitask_candidate_output_paths() - kept independent since the two
    write disjoint filenames."""
    version_dir = ML_DIR / "versions" / version_id
    return {
        "version_dir": version_dir,
        "sequence_model": version_dir / "sequence_model.json",
        "sequence_feature_schema": version_dir / "sequence_feature_schema.json",
        "sequence_training_metrics": version_dir / "sequence_training_metrics.json",
    }


def _split_sequence_tensors(
    dataset: pd.DataFrame, sequences: np.ndarray, split_name: str
) -> tuple[torch.Tensor, dict[str, torch.Tensor], pd.Series]:
    """Returns (features, targets, dates) for one split - targets is a dict
    keyed by head name, same shape as train_multitask.py::frame_to_multitask_tensors()'s
    return, so compute_sequence_multitask_metrics() below can share its
    structure with train_multitask.py's compute_multitask_metrics()."""
    mask = (dataset["split"] == split_name).to_numpy()
    split_sequences = sequences[mask]
    split_frame = dataset[mask]
    features = torch.tensor(split_sequences, dtype=torch.float32)
    targets = {
        "direction": torch.tensor(split_frame["target_direction"].to_numpy(dtype=np.float32), dtype=torch.float32),
        "magnitude": torch.tensor(split_frame["target_return_1d"].to_numpy(dtype=np.float32), dtype=torch.float32),
        "volatility": torch.tensor(
            split_frame["target_volatility_next_day"].to_numpy(dtype=np.float32), dtype=torch.float32
        ),
    }
    for head_name, (column, _kind, _stride) in HORIZON_HEAD_SPECS.items():
        targets[head_name] = torch.tensor(split_frame[column].to_numpy(dtype=np.float32), dtype=torch.float32)
    return features, targets, split_frame["date"]


def compute_sequence_multitask_metrics(
    model: AetherNetSequenceMultiTaskHorizons,
    features: torch.Tensor,
    targets: dict[str, torch.Tensor],
    dates: pd.Series,
    direction_criterion: nn.Module,
    threshold: float,
    head_thresholds: dict[str, float],
    horizon_head_config: dict,
    ranking_promotion_config: dict | None = None,
) -> dict:
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
            # promotion-gate verdict (purged/embargoed CV validation rigor,
            # bootstrap CI, cross-era stability), only computed for the
            # BACKTEST split (ranking_promotion_config passed only by that
            # call site below) - never on train/validation, matching how
            # assess_regression_quality() above only ever gates on backtest
            # RMSE/MAE.
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
    return metrics


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()

    try:
        training_config = load_sequence_training_config(Path(args.config_path))
        # Phase 2 of the 5/10 -> 9/10 roadmap: assess_ranking_quality_from_predictions()
        # needs phase1.target.ranking.promotion_gate, which lives in the
        # FULL config.json, not the narrow sequence_training sub-dict
        # load_sequence_training_config() returns - see that function's
        # docstring for why the promotion gate deliberately isn't
        # duplicated per-model.
        full_config = json.loads(Path(args.config_path).read_text(encoding="utf-8"))
        if not bool(training_config.get("enabled", True)):
            LOGGER.info("train_sequence: disabled via config - skipping.")
            return 0

        min_train_rows = int(training_config.get("min_train_rows", 200))
        min_validation_rows = int(training_config.get("min_validation_rows", 30))
        min_backtest_rows = int(training_config.get("min_backtest_rows", 30))
        window_size = int(training_config.get("window_size", 30))
        channels = list(training_config.get("channels", [32, 32]))
        kernel_size = int(training_config.get("kernel_size", 3))
        dropout = float(training_config.get("dropout", 0.15))
        learning_rate = float(training_config.get("learning_rate", 0.0007))
        weight_decay = float(training_config.get("weight_decay", 0.0001))
        batch_size = int(training_config.get("batch_size", 64))
        max_epochs = int(training_config.get("epochs", 60))
        patience = int(training_config.get("patience", 10))
        decision_threshold = float(training_config.get("decision_threshold", 0.5))
        threshold_metric = str(training_config.get("optimize_threshold_metric", "mcc"))
        threshold_min = float(training_config.get("threshold_search_min", 0.35))
        threshold_max = float(training_config.get("threshold_search_max", 0.65))
        threshold_steps = int(training_config.get("threshold_search_steps", 61))
        magnitude_loss_weight = float(training_config.get("magnitude_loss_weight", 1.0))
        volatility_loss_weight = float(training_config.get("volatility_loss_weight", 1.0))
        horizon_head_config = resolve_horizon_head_config(training_config)
        seed = int(training_config.get("seed", 42))

        if not FEATURE_SCHEMA_PATH.exists():
            LOGGER.info("train_sequence: missing feature schema - skipping.")
            return 0
        with FEATURE_SCHEMA_PATH.open("r", encoding="utf-8") as f:
            feature_schema = json.load(f)
        feature_names = list(feature_schema["model_input_names"])

        dataset_path = Path(args.dataset_path)
        if not dataset_path.exists():
            LOGGER.info("train_sequence: dataset not found at %s - skipping.", dataset_path)
            return 0
        dataset = pd.read_csv(dataset_path)

        required_columns = set(feature_names) | {
            "target_direction",
            "target_return_1d",
            "target_volatility_next_day",
            "split",
            "ticker",
            "date",
        }
        missing_columns = required_columns - set(dataset.columns)
        if missing_columns:
            LOGGER.info("train_sequence: dataset missing columns %s - skipping.", sorted(missing_columns))
            return 0
        # Horizon target columns are NOT required the way the core 3 are -
        # an older dataset built before Phase 3/4 shipped simply won't have
        # them, in which case every horizon head trains on an all-NaN
        # column (masked loss/metrics degrade to a true no-op), same
        # graceful backward-compatibility contract as train_multitask.py.
        for head_name, (column, _kind, _stride) in HORIZON_HEAD_SPECS.items():
            if column not in dataset.columns:
                dataset[column] = np.nan
                horizon_head_config[head_name] = {**horizon_head_config[head_name], "enabled": False}
                LOGGER.info("train_sequence: dataset missing %s - disabling %s head.", column, head_name)

        eligible = dataset
        if "training_eligible" in dataset.columns:
            eligible = dataset[dataset["training_eligible"]].reset_index(drop=True)
        else:
            eligible = dataset.reset_index(drop=True)

        train_rows = int((eligible["split"] == "train").sum())
        validation_rows = int((eligible["split"] == "validation").sum())
        backtest_rows = int((eligible["split"] == "backtest").sum())
        if train_rows < min_train_rows or validation_rows < min_validation_rows or backtest_rows < min_backtest_rows:
            LOGGER.info(
                "train_sequence: only %d train / %d validation / %d backtest rows "
                "(need >= %d / %d / %d) - skipping, not writing artifacts.",
                train_rows,
                validation_rows,
                backtest_rows,
                min_train_rows,
                min_validation_rows,
                min_backtest_rows,
            )
            return 0

        set_seed(seed)
        device = torch.device("cpu")

        LOGGER.info("train_sequence: building (rows=%d, window=%d, features=%d) sequence tensor...", len(eligible), window_size, len(feature_names))
        sequences = build_sequence_tensor_dataset(eligible, feature_names, window_size)

        train_features, train_targets, train_dates = _split_sequence_tensors(eligible, sequences, "train")
        validation_features, validation_targets, validation_dates = _split_sequence_tensors(eligible, sequences, "validation")
        validation_features = validation_features.to(device)
        validation_targets = {name: tensor.to(device) for name, tensor in validation_targets.items()}

        target_names_sorted = sorted(train_targets)
        train_loader = torch.utils.data.DataLoader(
            torch.utils.data.TensorDataset(
                train_features,
                *[train_targets[name] for name in target_names_sorted],
            ),
            batch_size=batch_size,
            shuffle=True,
        )

        model = AetherNetSequenceMultiTaskHorizons(
            input_dim=len(feature_names),
            channels=channels,
            kernel_size=kernel_size,
            dropout=dropout,
        ).to(device)

        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        train_split_frame = eligible[eligible["split"] == "train"]
        positive_count = max(float(train_split_frame["target_direction"].sum()), 1.0)
        negative_count = max(float(len(train_split_frame) - train_split_frame["target_direction"].sum()), 1.0)
        pos_weight = torch.tensor(negative_count / positive_count, dtype=torch.float32, device=device)
        direction_criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        best_state = None
        best_epoch = 0
        best_validation_loss = float("inf")
        epochs_without_improvement = 0
        history: list[dict] = []

        for epoch in range(1, max_epochs + 1):
            model.train()
            running_loss = 0.0
            sample_count = 0

            for batch in train_loader:
                batch_features = batch[0].to(device)
                batch_targets = {name: tensor.to(device) for name, tensor in zip(target_names_sorted, batch[1:])}

                optimizer.zero_grad()
                outputs = model(batch_features)
                loss = compute_combined_multitask_loss(
                    outputs, batch_targets, direction_criterion, magnitude_loss_weight, volatility_loss_weight, horizon_head_config
                )
                loss.backward()
                optimizer.step()

                running_loss += float(loss.item()) * len(batch_features)
                sample_count += len(batch_features)

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
                )
            history.append(
                {
                    "epoch": epoch,
                    "train_loss": running_loss / max(sample_count, 1),
                    "validation_loss": float(validation_loss.item()),
                }
            )

            if float(validation_loss.item()) < best_validation_loss:
                best_validation_loss = float(validation_loss.item())
                best_epoch = epoch
                best_state = copy.deepcopy(model.state_dict())
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1

            if epochs_without_improvement >= patience:
                break

        if best_state is None:
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
        backtest_features, backtest_targets, backtest_dates = _split_sequence_tensors(eligible, sequences, "backtest")
        backtest_features = backtest_features.to(device)
        backtest_targets = {name: tensor.to(device) for name, tensor in backtest_targets.items()}

        trained_at = datetime.now(timezone.utc).isoformat()
        metrics = {
            "project": "aether_quant",
            "phase": "sequence_multitask_horizons_phase2",
            "version_id": args.version_id,
            "trained_at": trained_at,
            "window_size": window_size,
            "channels": channels,
            "kernel_size": kernel_size,
            "row_counts": {"train": train_rows, "validation": validation_rows, "backtest": backtest_rows},
            "best_epoch": best_epoch,
            "epochs_ran": len(history),
            "loss_weights": {
                "magnitude_loss_weight": magnitude_loss_weight,
                "volatility_loss_weight": volatility_loss_weight,
            },
            "horizon_heads": horizon_head_config,
            "threshold_optimization": {
                "metric": threshold_metric,
                "default_threshold": decision_threshold,
                "selected_threshold": tuned_threshold,
                "selected_validation_metrics": tuned_validation_direction_metrics,
                "head_thresholds": head_thresholds,
            },
            "train": compute_sequence_multitask_metrics(
                model, train_features_device, train_targets_device, train_dates,
                direction_criterion, tuned_threshold, head_thresholds, horizon_head_config,
            ),
            "validation": compute_sequence_multitask_metrics(
                model, validation_features, validation_targets, validation_dates,
                direction_criterion, tuned_threshold, head_thresholds, horizon_head_config,
            ),
            "backtest": compute_sequence_multitask_metrics(
                model, backtest_features, backtest_targets, backtest_dates,
                direction_criterion, tuned_threshold, head_thresholds, horizon_head_config,
                ranking_promotion_config=full_config,
            ),
            "history": history,
        }
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
            "phase": "v2_sequence_multitask_horizons_model",
            "version_id": args.version_id,
            "status": "trained",
            "trained_at": trained_at,
            "model": {
                "type": "sequence_multitask_direction_magnitude_volatility_horizons",
                "model_input_features": feature_names,
                "window_size": window_size,
                "channels": channels,
                "kernel_size": kernel_size,
                "dropout": dropout,
                "decision_threshold": tuned_threshold,
            },
            "export": export_sequence_multitask_horizons_architecture(model) | {"state_dict": export_state_dict(model)},
        }
        feature_schema_payload = {"model_input_names": feature_names, "window_size": window_size}

        paths = sequence_candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        paths["sequence_model"].write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        paths["sequence_feature_schema"].write_text(json.dumps(feature_schema_payload, indent=2), encoding="utf-8")
        paths["sequence_training_metrics"].write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        rank_5d_ic = metrics["backtest"].get("rank_5d_ic") or {}
        LOGGER.info(
            "train_sequence: wrote sequence artifacts for version %s "
            "(backtest direction mcc=%.4f, magnitude mae=%.6f rmse=%.6f [%s], volatility mae=%.6f [%s], "
            "rank_5d mean_ic=%.4f t_stat=%.2f).",
            args.version_id,
            metrics["backtest"]["direction"]["mcc"],
            metrics["backtest"]["magnitude"]["mae"],
            metrics["backtest"]["magnitude"]["rmse"],
            metrics["magnitude_quality"]["quality_status"],
            metrics["backtest"]["volatility"]["mae"],
            metrics["volatility_quality"]["quality_status"],
            rank_5d_ic.get("mean_ic", 0.0),
            rank_5d_ic.get("t_stat", 0.0),
        )
        return 0
    except Exception as exc:  # never let an unexpected failure look ambiguous to the caller
        LOGGER.error("train_sequence: unexpected failure - %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
