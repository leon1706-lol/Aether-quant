"""Offline trainer for the Phase 2 sequence-encoder multitask model:
direction + return magnitude + volatility predicted from a causal TCN
trunk over a rolling window of bars, instead of Phase 1's flat-MLP trunk
(AetherNetMultiTask/train_multitask.py) collapsing each bar into one row.

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
build_sequence_tensor_dataset() only windows over the same 48-dim
model_input vector the flat multitask model already consumes, using each
row's own trailing history within its ticker.

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
    AetherNetSequenceMultiTask,
    build_sequence_tensor_dataset,
    compute_binary_metrics,
    compute_regression_metrics,
    export_sequence_multitask_architecture,
    export_state_dict,
    find_optimal_threshold,
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
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    mask = (dataset["split"] == split_name).to_numpy()
    split_sequences = sequences[mask]
    split_frame = dataset[mask]
    features = torch.tensor(split_sequences, dtype=torch.float32)
    direction = torch.tensor(split_frame["target_direction"].to_numpy(dtype=np.float32), dtype=torch.float32)
    magnitude = torch.tensor(split_frame["target_return_1d"].to_numpy(dtype=np.float32), dtype=torch.float32)
    volatility = torch.tensor(split_frame["target_volatility_next_day"].to_numpy(dtype=np.float32), dtype=torch.float32)
    return features, direction, magnitude, volatility


def compute_sequence_multitask_metrics(
    model: AetherNetSequenceMultiTask,
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
        training_config = load_sequence_training_config(Path(args.config_path))
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
        }
        missing_columns = required_columns - set(dataset.columns)
        if missing_columns:
            LOGGER.info("train_sequence: dataset missing columns %s - skipping.", sorted(missing_columns))
            return 0

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

        train_features, train_direction, train_magnitude, train_volatility = _split_sequence_tensors(eligible, sequences, "train")
        validation_features, validation_direction, validation_magnitude, validation_volatility = _split_sequence_tensors(
            eligible, sequences, "validation"
        )
        validation_features = validation_features.to(device)
        validation_direction = validation_direction.to(device)
        validation_magnitude = validation_magnitude.to(device)
        validation_volatility = validation_volatility.to(device)

        train_loader = torch.utils.data.DataLoader(
            torch.utils.data.TensorDataset(train_features, train_direction, train_magnitude, train_volatility),
            batch_size=batch_size,
            shuffle=True,
        )

        model = AetherNetSequenceMultiTask(
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
                v_direction_logits, v_magnitude_predictions, v_volatility_predictions = model(validation_features)
                validation_loss = (
                    direction_criterion(v_direction_logits, validation_direction)
                    + magnitude_loss_weight * magnitude_criterion(v_magnitude_predictions, validation_magnitude)
                    + volatility_loss_weight * volatility_criterion(v_volatility_predictions, validation_volatility)
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
        backtest_features, backtest_direction, backtest_magnitude, backtest_volatility = _split_sequence_tensors(
            eligible, sequences, "backtest"
        )
        backtest_features = backtest_features.to(device)
        backtest_direction = backtest_direction.to(device)
        backtest_magnitude = backtest_magnitude.to(device)
        backtest_volatility = backtest_volatility.to(device)

        trained_at = datetime.now(timezone.utc).isoformat()
        metrics = {
            "project": "aether_quant",
            "phase": "sequence_multitask_phase2",
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
            "threshold_optimization": {
                "metric": threshold_metric,
                "default_threshold": decision_threshold,
                "selected_threshold": tuned_threshold,
                "selected_validation_metrics": tuned_validation_direction_metrics,
            },
            "train": compute_sequence_multitask_metrics(
                model, train_features_device, train_direction_device, train_magnitude_device,
                train_volatility_device, direction_criterion, tuned_threshold,
            ),
            "validation": compute_sequence_multitask_metrics(
                model, validation_features, validation_direction, validation_magnitude,
                validation_volatility, direction_criterion, tuned_threshold,
            ),
            "backtest": compute_sequence_multitask_metrics(
                model, backtest_features, backtest_direction, backtest_magnitude,
                backtest_volatility, direction_criterion, tuned_threshold,
            ),
            "history": history,
        }

        model_payload = {
            "project": "Aether Quant",
            "phase": "v2_sequence_multitask_model",
            "version_id": args.version_id,
            "status": "trained",
            "trained_at": trained_at,
            "model": {
                "type": "sequence_multitask_direction_magnitude_volatility",
                "model_input_features": feature_names,
                "window_size": window_size,
                "channels": channels,
                "kernel_size": kernel_size,
                "dropout": dropout,
                "decision_threshold": tuned_threshold,
            },
            "export": export_sequence_multitask_architecture(model) | {"state_dict": export_state_dict(model)},
        }
        feature_schema_payload = {"model_input_names": feature_names, "window_size": window_size}

        paths = sequence_candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        paths["sequence_model"].write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        paths["sequence_feature_schema"].write_text(json.dumps(feature_schema_payload, indent=2), encoding="utf-8")
        paths["sequence_training_metrics"].write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        LOGGER.info(
            "train_sequence: wrote sequence artifacts for version %s "
            "(backtest direction mcc=%.4f, magnitude mae=%.6f, volatility mae=%.6f).",
            args.version_id,
            metrics["backtest"]["direction"]["mcc"],
            metrics["backtest"]["magnitude"]["mae"],
            metrics["backtest"]["volatility"]["mae"],
        )
        return 0
    except Exception as exc:  # never let an unexpected failure look ambiguous to the caller
        LOGGER.error("train_sequence: unexpected failure - %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
