"""A tiny synthetic dataset, feature schema and config for running the trainers' `main()` end to end on a CPU (V6.6.6, #359): 14 tickers, a few dozen dates in train, validation, backtest and
holdout, a handful of features, every target column the heads read, and a config cut down to a couple of epochs and a few hidden units."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
FEATURES = ["f_a", "f_b", "f_c", "f_d", "f_e", "f_f"]
TICKERS = [f"T{n:02d}" for n in range(14)]
TARGET_COLUMNS = ["target_direction", "target_return_1d", "target_volatility_next_day", "target_direction_5d", "target_direction_20d", "target_rank_5d", "target_rank_20d",
                  "target_sector_neutral_rank_20d", "target_residual_rank_5d", "target_residual_rank_20d", "target_beta_neutral_rank_20d"]


def make_frame(*, seed: int = 0, train_dates: int = 30, other_dates: int = 14) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    start = datetime.date(2019, 1, 1)
    total = train_dates + 3 * other_dates
    for day in range(total):
        date = (start + datetime.timedelta(days=day)).isoformat()
        split = "train" if day < train_dates else ("validation" if day < train_dates + other_dates else ("backtest" if day < train_dates + 2 * other_dates else "holdout"))
        ranks = rng.permutation(len(TICKERS)) / (len(TICKERS) - 1)
        for index, ticker in enumerate(TICKERS):
            features = rng.normal(0.0, 1.0, len(FEATURES))
            signal = float(features[0]) * 0.3 + (ranks[index] - 0.5)
            row = {"date": date, "ticker": ticker, "split": split, "training_eligible": True, "security_type": "equity", "close": 100.0 + index + day * 0.1, "open": 100.0 + index, "high": 101.0 + index,
                   "low": 99.0 + index, "volume": 1_000_000.0 + 1000 * index}
            row.update({name: float(value) for name, value in zip(FEATURES, features)})
            row["target_return_1d"] = float(0.01 * signal + rng.normal(0, 0.01))
            row["target_direction"] = float(row["target_return_1d"] > 0)
            row["target_volatility_next_day"] = float(abs(rng.normal(0.015, 0.005)))
            row["target_direction_5d"] = float(signal + rng.normal(0, 0.3) > 0)
            row["target_direction_20d"] = float(signal + rng.normal(0, 0.5) > 0)
            for name in ("target_rank_5d", "target_rank_20d", "target_sector_neutral_rank_20d", "target_residual_rank_5d", "target_residual_rank_20d", "target_beta_neutral_rank_20d"):
                row[name] = float(np.clip(ranks[index] + rng.normal(0, 0.15), 0.0, 1.0))
            rows.append(row)
    return pd.DataFrame(rows)


def write_world(root: Path, *, frame: pd.DataFrame | None = None, epochs: int = 2, training_overrides: dict | None = None, sequence_overrides: dict | None = None) -> dict:
    """`root/config.json`, `root/ml/feature_schema.json` and the dataset CSVs, with the retraining blocks cut down to run in seconds. Returns the paths."""
    frame = make_frame() if frame is None else frame
    config = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
    retraining = config["phase_v2"]["retraining"]
    small = {"epochs": epochs, "patience": 2, "hidden_layers": [8], "batch_size": 64, "min_train_rows": 50, "min_validation_rows": 10, "min_backtest_rows": 10, "min_best_epoch": 1,
             "cross_sectional_batch_dates": 2, "min_cross_sectional_group_size": 5}
    retraining["multitask_training"].update(small)
    retraining["multitask_training"]["swa"] = {"enabled": True, "start_epoch_fraction": 0.5}
    retraining["multitask_training"].update(training_overrides or {})
    retraining["sequence_training"].update({**small, "window_size": 4, "channels": [8, 8], "min_train_rows": 50, "min_validation_rows": 10, "min_backtest_rows": 10})
    retraining["sequence_training"].update(sequence_overrides or {})
    config["phase1"]["target"]["ranking"]["min_universe_size"] = 5
    config["phase1"]["features"]["cross_sectional_inputs"] = {"enabled": False}
    root.mkdir(parents=True, exist_ok=True)
    (root / "ml").mkdir(exist_ok=True)
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (root / "ml" / "feature_schema.json").write_text(json.dumps({"model_input_names": FEATURES, "feature_names": FEATURES, "scaled_feature_names": FEATURES}), encoding="utf-8")
    dataset = root / "ml" / "dataset.csv"
    frame.to_csv(dataset, index=False)
    return {"config": root / "config.json", "dataset": dataset, "schema": root / "ml" / "feature_schema.json", "frame": frame}
