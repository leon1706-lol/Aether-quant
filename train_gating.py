"""Offline trainer for the learned gating model (real weights for
moe/gating.py's blend, replacing/augmenting the hardcoded
quality*performance*regime_alignment scoring).

Separate script from train.py: trains a *second-stage* model over the
outputs of the already-trained baseline+expert models, not over raw OHLCV
features. Free to use torch/pandas/numpy, unlike moe/gating.py's pure-Python
runtime path: this script never runs inside the Lean container, only as a
retraining-pipeline subprocess (see retraining/orchestrator.py::train_gating())
or a manual/`aq train --gating-only` CLI call.

Train/validation/backtest split discipline (avoids stacking circularity):
baseline+experts are already fit on the `train` split, so replaying `train`
rows here would just teach this model to correct their training-set
overfit. Instead this trainer replays the `validation` split (held out from
baseline/expert fitting, the right size and held-out status to become this
model's *own* training data) through the exported baseline+expert models,
building the exact 26-dim feature vector moe/gating.py::build_gating_model_features()
would have produced live, paired with the known target_direction label.
Those replayed rows are further shuffle-split into a fit/early-stop pair
(this trainer's own internal early stopping, distinct from the dataset's
`split` column) since `validation` rows now serve as this model's training
data and no longer double as a held-out check. The `backtest` split is
never touched by any fitting anywhere in the pipeline and is replayed only
once, at the end, purely to report a trustworthy number.

Known asymmetry, inherited from the existing system, not introduced here:
train.py's `--candidate` path only versions the baseline model, never
re-trains experts per-candidate - so this trainer always reads expert
exports from the *active* ml/expert_models/, even when training a gating
blend for a candidate baseline version-id.

Model is deliberately restricted to relu/layernorm (never gelu/silu/
batchnorm1d) since inference/exported_model.py::run_exported_model() -
the same interpreter used both here for replay and by moe/gating.py at
runtime - cannot interpret those layer types.

Usage:
    python train_gating.py --version-id <uuid> [--config-path config.json] [--dataset-path ml/datasets/full_dataset.csv]

Writes ml/versions/<version_id>/gating_model.json, gating_feature_schema.json
and gating_training_metrics.json. Exits 0 (not an error) when there isn't
enough data or no upstream models are available yet - "skipped" must never
look like "failed" to the caller.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from inference import run_exported_model
from moe.gating import EXPERT_NAMES, GATING_MODEL_FEATURE_KEYS, build_gating_decision, build_gating_model_features
from regime import build_market_regime_vector
from train import (
    AetherNet,
    compute_binary_metrics,
    export_architecture,
    export_state_dict,
    find_optimal_threshold,
    frame_to_tensors,
    is_new_best_epoch,
    set_seed,
)

LOGGER = logging.getLogger("aether_quant.train_gating")
ROOT = Path(__file__).resolve().parent
ML_DIR = ROOT / "ml"
CONFIG_PATH = ROOT / "config.json"
DATASET_PATH = ML_DIR / "datasets" / "full_dataset.csv"
FEATURE_SCHEMA_PATH = ML_DIR / "feature_schema.json"
EXPERT_TRAINING_METRICS_PATH = ML_DIR / "expert_training_metrics.json"
EXPERT_MODEL_DIR = ML_DIR / "expert_models"
ACTIVE_BASELINE_MODEL_PATH = ML_DIR / "model_weights.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether Quant learned-gating trainer")
    parser.add_argument("--version-id", type=str, required=True, help="Candidate model_version_id (UUID)")
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    parser.add_argument("--dataset-path", type=str, default=str(DATASET_PATH))
    return parser.parse_args()


def load_gating_training_config(config_path: Path = CONFIG_PATH) -> dict:
    with Path(config_path).open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("retraining", {}).get("gating_training", {})


def gating_candidate_output_paths(version_id: str) -> dict[str, Path]:
    """Own local helper mirroring train_topology.py's
    topology_candidate_output_paths(), kept independent of train.py's own
    candidate_output_paths() since the two write disjoint filenames."""
    version_dir = ML_DIR / "versions" / version_id
    return {
        "version_dir": version_dir,
        "gating_model": version_dir / "gating_model.json",
        "gating_feature_schema": version_dir / "gating_feature_schema.json",
        "gating_training_metrics": version_dir / "gating_training_metrics.json",
    }


def load_baseline_export(version_id: str) -> dict | None:
    """Prefers this candidate's own versioned baseline export (written by
    `python train.py --candidate --version-id <id>`) if present; falls back
    to the active baseline export otherwise."""
    versioned_path = ML_DIR / "versions" / version_id / "model_weights.json"
    for path in (versioned_path, ACTIVE_BASELINE_MODEL_PATH):
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    return None


def load_expert_exports() -> dict[str, dict]:
    exports: dict[str, dict] = {}
    for expert_name in EXPERT_NAMES:
        path = EXPERT_MODEL_DIR / expert_name / "model_weights.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                exports[expert_name] = json.load(f)
    return exports


def build_gating_training_rows(
    frame: pd.DataFrame,
    feature_schema: dict,
    expert_training_metrics: dict,
    baseline_export: dict | None,
    expert_exports: dict[str, dict],
) -> tuple[list[list[float]], list[float]]:
    """Replays each dataset row through the exported baseline+expert models
    (run_exported_model(), the same interpreter moe/gating.py uses at
    runtime) to reconstruct the exact feature vector
    build_gating_model_features() would have produced live, paired with the
    already-known target_direction label. Regime reconstruction uses
    portfolio_drawdown=0.0/average_correlation=0.0 (runtime-only state not
    recoverable offline) - an honest, documented simplification; the two
    regime keys _regime_alignment() actually branches on (trend_regime,
    volatility_regime) are unaffected."""
    model_input_names = feature_schema["model_input_names"]
    feature_names = feature_schema["feature_names"]

    rows: list[list[float]] = []
    labels: list[float] = []

    for _, row in frame.iterrows():
        model_inputs = [float(row[name]) for name in model_input_names]
        raw_features = {name: float(row[name]) for name in feature_names}

        expert_probabilities: dict[str, float | None] = {}
        for expert_name in EXPERT_NAMES:
            export = expert_exports.get(expert_name)
            if export is None:
                expert_probabilities[expert_name] = None
                continue
            try:
                expert_probabilities[expert_name] = run_exported_model(export, model_inputs)
            except Exception:
                expert_probabilities[expert_name] = None

        baseline_probability_up = None
        if baseline_export is not None:
            try:
                baseline_probability_up = run_exported_model(baseline_export, model_inputs)
            except Exception:
                baseline_probability_up = None

        regime = build_market_regime_vector(
            raw_features, portfolio_drawdown=0.0, average_correlation=0.0
        ).to_dict()

        decision = build_gating_decision(
            regime=regime,
            expert_training_metrics=expert_training_metrics,
            expert_probabilities=expert_probabilities,
            baseline_probability_up=baseline_probability_up,
        )
        feature_vector = build_gating_model_features(regime, baseline_probability_up, decision.weights)
        rows.append(feature_vector)
        labels.append(float(row["target_direction"]))

    return rows, labels


def rows_to_frame(rows: list[list[float]], labels: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(GATING_MODEL_FEATURE_KEYS))
    frame["target_direction"] = labels
    return frame


def shuffle_split(frame: pd.DataFrame, holdout_fraction: float, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Internal fit/early-stop split of the replayed `validation`-split
    rows - distinct from the dataset's own `split` column, needed because
    those rows are this model's training data here, not a held-out check."""
    shuffled = frame.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    holdout_size = max(1, int(len(shuffled) * holdout_fraction))
    holdout = shuffled.iloc[:holdout_size].reset_index(drop=True)
    fit = shuffled.iloc[holdout_size:].reset_index(drop=True)
    return fit, holdout


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()

    try:
        training_config = load_gating_training_config(Path(args.config_path))
        min_train_rows = int(training_config.get("min_train_rows", 100))
        min_backtest_rows = int(training_config.get("min_backtest_rows", 20))
        holdout_fraction = float(training_config.get("early_stop_holdout_fraction", 0.15))
        hidden_layers = list(training_config.get("hidden_layers", [16]))
        dropout = float(training_config.get("dropout", 0.2))
        learning_rate = float(training_config.get("learning_rate", 0.001))
        weight_decay = float(training_config.get("weight_decay", 0.001))
        batch_size = int(training_config.get("batch_size", 64))
        max_epochs = int(training_config.get("epochs", 60))
        patience = int(training_config.get("patience", 8))
        decision_threshold = float(training_config.get("decision_threshold", 0.5))
        threshold_metric = str(training_config.get("optimize_threshold_metric", "mcc"))
        threshold_min = float(training_config.get("threshold_search_min", 0.35))
        threshold_max = float(training_config.get("threshold_search_max", 0.65))
        threshold_steps = int(training_config.get("threshold_search_steps", 61))
        seed = int(training_config.get("seed", 42))

        if not FEATURE_SCHEMA_PATH.exists() or not EXPERT_TRAINING_METRICS_PATH.exists():
            LOGGER.info("train_gating: missing feature schema or expert training metrics - skipping.")
            return 0

        with FEATURE_SCHEMA_PATH.open("r", encoding="utf-8") as f:
            feature_schema = json.load(f)
        with EXPERT_TRAINING_METRICS_PATH.open("r", encoding="utf-8") as f:
            expert_training_metrics = json.load(f)

        expert_exports = load_expert_exports()
        baseline_export = load_baseline_export(args.version_id)
        if not expert_exports and baseline_export is None:
            LOGGER.info("train_gating: no baseline or expert exports available yet - skipping.")
            return 0

        dataset_path = Path(args.dataset_path)
        if not dataset_path.exists():
            LOGGER.info("train_gating: dataset not found at %s - skipping.", dataset_path)
            return 0
        dataset = pd.read_csv(dataset_path)

        validation_frame = dataset[dataset["split"] == "validation"].reset_index(drop=True)
        backtest_frame = dataset[dataset["split"] == "backtest"].reset_index(drop=True)

        if len(validation_frame) < min_train_rows or len(backtest_frame) < min_backtest_rows:
            LOGGER.info(
                "train_gating: only %d validation / %d backtest rows (need >= %d / %d) - skipping, not writing artifacts.",
                len(validation_frame),
                len(backtest_frame),
                min_train_rows,
                min_backtest_rows,
            )
            return 0

        set_seed(seed)

        LOGGER.info("train_gating: replaying %d validation rows through baseline+experts...", len(validation_frame))
        train_rows, train_labels = build_gating_training_rows(
            validation_frame, feature_schema, expert_training_metrics, baseline_export, expert_exports
        )
        LOGGER.info("train_gating: replaying %d backtest rows through baseline+experts...", len(backtest_frame))
        backtest_rows, backtest_labels = build_gating_training_rows(
            backtest_frame, feature_schema, expert_training_metrics, baseline_export, expert_exports
        )

        full_train_frame = rows_to_frame(train_rows, train_labels)
        backtest_gating_frame = rows_to_frame(backtest_rows, backtest_labels)
        fit_frame, early_stop_frame = shuffle_split(full_train_frame, holdout_fraction, seed)

        device = torch.device("cpu")
        feature_names = list(GATING_MODEL_FEATURE_KEYS)

        fit_features, fit_targets = frame_to_tensors(fit_frame, feature_names)
        early_stop_features, early_stop_targets = frame_to_tensors(early_stop_frame, feature_names)
        early_stop_features = early_stop_features.to(device)
        early_stop_targets = early_stop_targets.to(device)

        train_loader = DataLoader(
            TensorDataset(fit_features, fit_targets),
            batch_size=batch_size,
            shuffle=True,
        )

        model = AetherNet(
            input_dim=len(feature_names),
            hidden_layers=hidden_layers,
            dropout=dropout,
            activation="relu",
            normalization="layernorm",
        ).to(device)

        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        positive_count = max(float(fit_frame["target_direction"].sum()), 1.0)
        negative_count = max(float(len(fit_frame) - fit_frame["target_direction"].sum()), 1.0)
        pos_weight = torch.tensor(negative_count / positive_count, dtype=torch.float32, device=device)
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        best_state = None
        best_epoch = 0
        best_early_stop_balanced_accuracy = float("-inf")
        epochs_without_improvement = 0
        history: list[dict] = []
        min_best_epoch = int(training_config.get("min_best_epoch", 3))

        for epoch in range(1, max_epochs + 1):
            model.train()
            running_loss = 0.0
            sample_count = 0
            for batch_features, batch_targets in train_loader:
                batch_features = batch_features.to(device)
                batch_targets = batch_targets.to(device)

                optimizer.zero_grad()
                logits = model(batch_features)
                loss = criterion(logits, batch_targets)
                loss.backward()
                optimizer.step()

                running_loss += float(loss.item()) * len(batch_targets)
                sample_count += len(batch_targets)

            model.eval()
            with torch.no_grad():
                early_stop_logits = model(early_stop_features)
            early_stop_metrics = compute_binary_metrics(early_stop_logits, early_stop_targets, criterion, decision_threshold)
            history.append(
                {
                    "epoch": epoch,
                    "train_loss": running_loss / max(sample_count, 1),
                    "early_stop_loss": early_stop_metrics["loss"],
                    "early_stop_balanced_accuracy": early_stop_metrics["balanced_accuracy"],
                }
            )

            # See train.py::is_new_best_epoch()'s docstring - monitors
            # skill (balanced-accuracy), not the loss already computed
            # above into early_stop_metrics (development/Problems.md).
            if is_new_best_epoch(
                early_stop_metrics["balanced_accuracy"], best_early_stop_balanced_accuracy, epoch, min_best_epoch
            ):
                best_early_stop_balanced_accuracy = early_stop_metrics["balanced_accuracy"]
                best_epoch = epoch
                best_state = copy.deepcopy(model.state_dict())
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1

            if epoch >= min_best_epoch and epochs_without_improvement >= patience:
                break

        if best_state is None:
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = len(history)

        model.load_state_dict(best_state)
        model.eval()
        with torch.no_grad():
            early_stop_logits = model(early_stop_features)
        tuned_threshold, tuned_early_stop_metrics = find_optimal_threshold(
            early_stop_logits,
            early_stop_targets,
            criterion,
            threshold_metric,
            threshold_min,
            threshold_max,
            threshold_steps,
        )

        backtest_features, backtest_targets = frame_to_tensors(backtest_gating_frame, feature_names)
        backtest_features = backtest_features.to(device)
        backtest_targets = backtest_targets.to(device)
        with torch.no_grad():
            backtest_logits = model(backtest_features)
        backtest_metrics = compute_binary_metrics(backtest_logits, backtest_targets, criterion, tuned_threshold)

        trained_at = datetime.now(timezone.utc).isoformat()
        model_payload = {
            "version_id": args.version_id,
            "trained_at": trained_at,
            "export": {
                "architecture": export_architecture(model),
                "state_dict": export_state_dict(model),
            },
        }
        feature_schema_payload = {"feature_keys": feature_names}
        training_metrics_payload = {
            "project": "aether_quant",
            "phase": "gating_network_learned_weights",
            "version_id": args.version_id,
            "trained_at": trained_at,
            "row_counts": {
                "gating_train_fit": int(len(fit_frame)),
                "gating_train_early_stop": int(len(early_stop_frame)),
                "backtest": int(len(backtest_gating_frame)),
            },
            "best_epoch": best_epoch,
            "epochs_ran": len(history),
            "threshold_optimization": {
                "metric": threshold_metric,
                "default_threshold": decision_threshold,
                "selected_threshold": tuned_threshold,
                "selected_early_stop_metrics": tuned_early_stop_metrics,
            },
            "backtest": backtest_metrics,
            "history": history,
        }

        paths = gating_candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        paths["gating_model"].write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        paths["gating_feature_schema"].write_text(json.dumps(feature_schema_payload, indent=2), encoding="utf-8")
        paths["gating_training_metrics"].write_text(json.dumps(training_metrics_payload, indent=2), encoding="utf-8")

        LOGGER.info(
            "train_gating: wrote gating artifacts for version %s (backtest balanced_accuracy=%.4f, mcc=%.4f).",
            args.version_id,
            backtest_metrics["balanced_accuracy"],
            backtest_metrics["mcc"],
        )
        return 0
    except Exception as exc:  # never let an unexpected failure look ambiguous to the caller
        LOGGER.error("train_gating: unexpected failure - %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
