"""Offline trainer for the multi-task model: direction + return magnitude +
volatility predicted jointly from one shared trunk (AetherNetMultiTask,
train.py).

Separate script from train.py, same convention as train_gating.py/
train_topology.py: reads the already-built active dataset
(ml/datasets/full_dataset.csv) and the active feature_schema.json rather
than rebuilding the dataset itself, so this never touches train.py's own
CLI flow or its baseline/expert artifacts. Uses the exact same
model_input_names as the baseline model (scaled features + asset context) -
this phase does not change what the input feature set is, only what the
model predicts from it (see development/Changelog.md for why regime/
liquidity/topology-as-inputs was scoped out of this pass).

Loss is BCEWithLogitsLoss(direction) + magnitude_loss_weight * MSE(magnitude)
+ volatility_loss_weight * MSE(volatility), both weights defaulting to 1.0
(phase_v2.retraining.multitask_training). Early stopping and threshold
tuning both operate on the combined validation loss / direction logits
respectively - magnitude/volatility are evaluated with plain MAE/RMSE
(train.py::compute_regression_metrics()), never MCC/F1 (meaningless for a
continuous target).

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
    AetherNetMultiTask,
    compute_binary_metrics,
    compute_regression_metrics,
    export_multitask_architecture,
    export_state_dict,
    find_optimal_threshold,
    set_seed,
)

LOGGER = logging.getLogger("aether_quant.train_multitask")
ROOT = Path(__file__).resolve().parent
ML_DIR = ROOT / "ml"
CONFIG_PATH = ROOT / "config.json"
DATASET_PATH = ML_DIR / "datasets" / "full_dataset.csv"
FEATURE_SCHEMA_PATH = ML_DIR / "feature_schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether Quant multi-task (direction+magnitude+volatility) trainer")
    parser.add_argument("--version-id", type=str, required=True, help="Candidate model_version_id (UUID)")
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    parser.add_argument("--dataset-path", type=str, default=str(DATASET_PATH))
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


def frame_to_multitask_tensors(
    frame: pd.DataFrame, feature_names: list[str]
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    features = torch.tensor(frame[feature_names].to_numpy(dtype=np.float32), dtype=torch.float32)
    direction_targets = torch.tensor(frame["target_direction"].to_numpy(dtype=np.float32), dtype=torch.float32)
    magnitude_targets = torch.tensor(frame["target_return_1d"].to_numpy(dtype=np.float32), dtype=torch.float32)
    volatility_targets = torch.tensor(
        frame["target_volatility_next_day"].to_numpy(dtype=np.float32), dtype=torch.float32
    )
    return features, direction_targets, magnitude_targets, volatility_targets


def compute_multitask_metrics(
    model: AetherNetMultiTask,
    features: torch.Tensor,
    direction_targets: torch.Tensor,
    magnitude_targets: torch.Tensor,
    volatility_targets: torch.Tensor,
    direction_criterion: nn.Module,
    threshold: float,
) -> dict:
    model.eval()
    with torch.no_grad():
        direction_logits, magnitude_predictions, volatility_predictions = model(features)
    return {
        "direction": compute_binary_metrics(direction_logits, direction_targets, direction_criterion, threshold),
        "magnitude": compute_regression_metrics(magnitude_predictions, magnitude_targets),
        "volatility": compute_regression_metrics(volatility_predictions, volatility_targets),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()

    try:
        training_config = load_multitask_training_config(Path(args.config_path))
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
        seed = int(training_config.get("seed", 42))

        if not FEATURE_SCHEMA_PATH.exists():
            LOGGER.info("train_multitask: missing feature schema - skipping.")
            return 0
        with FEATURE_SCHEMA_PATH.open("r", encoding="utf-8") as f:
            feature_schema = json.load(f)
        feature_names = list(feature_schema["model_input_names"])

        dataset_path = Path(args.dataset_path)
        if not dataset_path.exists():
            LOGGER.info("train_multitask: dataset not found at %s - skipping.", dataset_path)
            return 0
        dataset = pd.read_csv(dataset_path)

        required_columns = set(feature_names) | {
            "target_direction",
            "target_return_1d",
            "target_volatility_next_day",
            "split",
        }
        missing_columns = required_columns - set(dataset.columns)
        if missing_columns:
            LOGGER.info("train_multitask: dataset missing columns %s - skipping.", sorted(missing_columns))
            return 0

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

        train_features, train_direction, train_magnitude, train_volatility = frame_to_multitask_tensors(
            train_frame, feature_names
        )
        validation_features, validation_direction, validation_magnitude, validation_volatility = frame_to_multitask_tensors(
            validation_frame, feature_names
        )
        validation_features = validation_features.to(device)
        validation_direction = validation_direction.to(device)
        validation_magnitude = validation_magnitude.to(device)
        validation_volatility = validation_volatility.to(device)

        train_loader = DataLoader(
            TensorDataset(train_features, train_direction, train_magnitude, train_volatility),
            batch_size=batch_size,
            shuffle=True,
        )

        model = AetherNetMultiTask(
            input_dim=len(feature_names),
            hidden_layers=hidden_layers,
            dropout=dropout,
            activation=activation,
            normalization=normalization,
        ).to(device)

        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        positive_count = max(float(train_frame["target_direction"].sum()), 1.0)
        negative_count = max(float(len(train_frame) - train_frame["target_direction"].sum()), 1.0)
        pos_weight = torch.tensor(negative_count / positive_count, dtype=torch.float32, device=device)
        direction_criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        magnitude_criterion = nn.MSELoss()
        volatility_criterion = nn.MSELoss()

        best_state = None
        best_epoch = 0
        best_validation_loss = float("inf")
        epochs_without_improvement = 0
        history: list[dict] = []

        for epoch in range(1, max_epochs + 1):
            model.train()
            running_loss = 0.0
            sample_count = 0

            for batch_features, batch_direction, batch_magnitude, batch_volatility in train_loader:
                batch_features = batch_features.to(device)
                batch_direction = batch_direction.to(device)
                batch_magnitude = batch_magnitude.to(device)
                batch_volatility = batch_volatility.to(device)

                optimizer.zero_grad()
                direction_logits, magnitude_predictions, volatility_predictions = model(batch_features)
                loss = (
                    direction_criterion(direction_logits, batch_direction)
                    + magnitude_loss_weight * magnitude_criterion(magnitude_predictions, batch_magnitude)
                    + volatility_loss_weight * volatility_criterion(volatility_predictions, batch_volatility)
                )
                loss.backward()
                optimizer.step()

                running_loss += float(loss.item()) * len(batch_direction)
                sample_count += len(batch_direction)

            model.eval()
            with torch.no_grad():
                validation_direction_logits, validation_magnitude_predictions, validation_volatility_predictions = model(
                    validation_features
                )
                validation_loss = (
                    direction_criterion(validation_direction_logits, validation_direction)
                    + magnitude_loss_weight * magnitude_criterion(validation_magnitude_predictions, validation_magnitude)
                    + volatility_loss_weight * volatility_criterion(validation_volatility_predictions, validation_volatility)
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
            validation_direction_logits, _, _ = model(validation_features)
        tuned_threshold, tuned_validation_direction_metrics = find_optimal_threshold(
            validation_direction_logits,
            validation_direction,
            direction_criterion,
            threshold_metric,
            threshold_min,
            threshold_max,
            threshold_steps,
        )

        train_features_device = train_features.to(device)
        train_direction_device = train_direction.to(device)
        train_magnitude_device = train_magnitude.to(device)
        train_volatility_device = train_volatility.to(device)
        backtest_features, backtest_direction, backtest_magnitude, backtest_volatility = frame_to_multitask_tensors(
            backtest_frame, feature_names
        )
        backtest_features = backtest_features.to(device)
        backtest_direction = backtest_direction.to(device)
        backtest_magnitude = backtest_magnitude.to(device)
        backtest_volatility = backtest_volatility.to(device)

        trained_at = datetime.now(timezone.utc).isoformat()
        metrics = {
            "project": "aether_quant",
            "phase": "multitask_direction_magnitude_volatility",
            "version_id": args.version_id,
            "trained_at": trained_at,
            "row_counts": {
                "train": int(len(train_frame)),
                "validation": int(len(validation_frame)),
                "backtest": int(len(backtest_frame)),
            },
            "best_epoch": best_epoch,
            "epochs_ran": len(history),
            "loss_weights": {
                "magnitude_loss_weight": magnitude_loss_weight,
                "volatility_loss_weight": volatility_loss_weight,
            },
            "threshold_optimization": {
                "metric": threshold_metric,
                "default_threshold": decision_threshold,
                "selected_threshold": tuned_threshold,
                "selected_validation_metrics": tuned_validation_direction_metrics,
            },
            "train": compute_multitask_metrics(
                model, train_features_device, train_direction_device, train_magnitude_device,
                train_volatility_device, direction_criterion, tuned_threshold,
            ),
            "validation": compute_multitask_metrics(
                model, validation_features, validation_direction, validation_magnitude,
                validation_volatility, direction_criterion, tuned_threshold,
            ),
            "backtest": compute_multitask_metrics(
                model, backtest_features, backtest_direction, backtest_magnitude,
                backtest_volatility, direction_criterion, tuned_threshold,
            ),
            "history": history,
        }

        model_payload = {
            "project": "Aether Quant",
            "phase": "v2_multitask_model",
            "version_id": args.version_id,
            "status": "trained",
            "trained_at": trained_at,
            "model": {
                "type": "multitask_direction_magnitude_volatility",
                "model_input_features": feature_names,
                "hidden_layers": hidden_layers,
                "dropout": dropout,
                "activation": activation,
                "normalization": normalization,
                "decision_threshold": tuned_threshold,
            },
            "export": export_multitask_architecture(model) | {"state_dict": export_state_dict(model)},
        }
        feature_schema_payload = {"model_input_names": feature_names}

        paths = multitask_candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        paths["multitask_model"].write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        paths["multitask_feature_schema"].write_text(json.dumps(feature_schema_payload, indent=2), encoding="utf-8")
        paths["multitask_training_metrics"].write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        LOGGER.info(
            "train_multitask: wrote multitask artifacts for version %s "
            "(backtest direction mcc=%.4f, magnitude mae=%.6f, volatility mae=%.6f).",
            args.version_id,
            metrics["backtest"]["direction"]["mcc"],
            metrics["backtest"]["magnitude"]["mae"],
            metrics["backtest"]["volatility"]["mae"],
        )
        return 0
    except Exception as exc:  # never let an unexpected failure look ambiguous to the caller
        LOGGER.error("train_multitask: unexpected failure - %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
