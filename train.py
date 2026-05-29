"""
Training pipeline for Aether Quant.

Phase 3 extends the dataset pipeline with a first PyTorch model:
- inspect and inventory the configured Lean data universe
- build synchronized feature datasets with time-based splits
- fit and persist a scaler
- train an MLP classifier with validation and early stopping
- export model metrics, checkpoint and Lean-readable weights
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import joblib
import numpy as np
import pandas as pd
import torch
from experts import build_expert_dataset_manifest, write_expert_dataset_artifacts
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


LOGGER = logging.getLogger("aether_quant.train")
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ML_DIR = ROOT / "ml"
DATASET_DIR = ML_DIR / "datasets"
EXPERT_DATASET_DIR = ML_DIR / "expert_datasets"
BACKTESTS_DIR = ROOT / "backtests"
VIS_DIR = ROOT / "visualization"
GRAFANA_DIR = VIS_DIR / "grafana"
CONFIG_PATH = ROOT / "config.json"
MODEL_WEIGHTS_PATH = ML_DIR / "model_weights.json"
MODEL_CHECKPOINT_PATH = ML_DIR / "model.pt"
TRAINING_METRICS_PATH = ML_DIR / "training_metrics.json"
INVENTORY_PATH = ML_DIR / "dataset_inventory.json"
DATASET_MANIFEST_PATH = ML_DIR / "dataset_manifest.json"
EXPERT_DATASET_MANIFEST_PATH = ML_DIR / "expert_dataset_manifest.json"
FEATURE_SCHEMA_PATH = ML_DIR / "feature_schema.json"
SCALER_PATH = ML_DIR / "scaler.pkl"
SCALER_STATS_PATH = ML_DIR / "scaler_stats.json"
STATE_PATH = VIS_DIR / "state.json"
SCENE_PATH = VIS_DIR / "scene.json"
GRAFANA_METRICS_PATH = GRAFANA_DIR / "metrics_snapshot.json"
GRAFANA_EQUITY_CURVES_PATH = GRAFANA_DIR / "equity_curves.csv"
GRAFANA_ASSET_PERFORMANCE_PATH = GRAFANA_DIR / "asset_performance.csv"
STRATEGY_REPORT_PATH = BACKTESTS_DIR / "strategy_report.json"
EQUITY_CURVES_PATH = BACKTESTS_DIR / "equity_curves.csv"

FULL_DATASET_PATH = DATASET_DIR / "full_dataset.csv"
TRAIN_DATASET_PATH = DATASET_DIR / "train_dataset.csv"
VALIDATION_DATASET_PATH = DATASET_DIR / "validation_dataset.csv"
BACKTEST_DATASET_PATH = DATASET_DIR / "backtest_dataset.csv"

RAW_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
PRICE_COLUMNS = ["open", "high", "low", "close"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether Quant training pipeline")
    parser.add_argument(
        "--init-only",
        action="store_true",
        help="Refresh inventory and placeholders without building datasets or training."
    )
    parser.add_argument(
        "--dataset-only",
        action="store_true",
        help="Build dataset artifacts and scaler, but skip model training."
    )
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def ensure_directories() -> None:
    for path in (ML_DIR, DATASET_DIR, EXPERT_DATASET_DIR, VIS_DIR, GRAFANA_DIR, BACKTESTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def validate_training_inputs(config: dict) -> list[str]:
    issues: list[str] = []
    phase1 = config.get("phase1", {})
    universe = phase1.get("universe", {})
    windows = phase1.get("windows", {})
    assets = universe.get("assets", [])

    if not assets:
        issues.append("No assets configured in phase1.universe.assets.")

    for asset in assets:
        ticker = asset.get("ticker", "<missing ticker>")
        data_path = asset.get("data_path")
        if not data_path:
            issues.append(f"{ticker}: missing data_path.")
            continue
        if not (ROOT / data_path).exists() and not asset.get("derived_from"):
            issues.append(f"{ticker}: data file does not exist: {data_path}.")

    for split_name in ("training", "validation", "backtest"):
        split_window = windows.get(split_name)
        if not split_window:
            issues.append(f"Missing phase1.windows.{split_name}.")
            continue
        try:
            start = pd.Timestamp(split_window["start"])
            end = pd.Timestamp(split_window["end"])
        except (KeyError, ValueError, TypeError) as error:
            issues.append(f"{split_name}: invalid date window: {error}.")
            continue
        if start > end:
            issues.append(f"{split_name}: start date is after end date.")

    return issues


def raise_if_validation_failed(issues: list[str]) -> None:
    if not issues:
        return
    formatted = "\n".join(f"- {issue}" for issue in issues)
    raise ValueError(f"Training input validation failed:\n{formatted}")


def load_project_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def ensure_derived_crypto_daily_series(config: dict) -> None:
    for asset in config["phase1"]["universe"]["assets"]:
        derived_from = asset.get("derived_from")
        aggregation = asset.get("aggregation")
        if not derived_from or aggregation != "daily_from_minute_trade":
            continue

        source_dir = ROOT / derived_from
        output_zip = ROOT / asset["data_path"]
        if not source_dir.exists():
            continue

        trade_files = sorted(source_dir.glob("*_trade.zip"))
        if not trade_files:
            continue

        daily_rows: list[str] = []
        for trade_zip in trade_files:
            date_token = trade_zip.stem.split("_")[0]
            try:
                session_date = datetime.strptime(date_token, "%Y%m%d")
            except ValueError:
                continue

            with ZipFile(trade_zip) as archive:
                member = archive.namelist()[0]
                with archive.open(member) as handle:
                    frame = pd.read_csv(handle, header=None, names=RAW_COLUMNS)

            frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce")
            for column in PRICE_COLUMNS + ["volume"]:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

            frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"]).sort_values("timestamp")
            if frame.empty:
                continue

            open_price = float(frame.iloc[0]["open"])
            high_price = float(frame["high"].max())
            low_price = float(frame["low"].min())
            close_price = float(frame.iloc[-1]["close"])
            volume_value = float(frame["volume"].sum())
            daily_rows.append(
                f"{session_date.strftime('%Y%m%d')} 00:00,{open_price},{high_price},{low_price},{close_price},{volume_value}"
            )

        if not daily_rows:
            continue

        output_zip.parent.mkdir(parents=True, exist_ok=True)
        member_name = f"{asset['ticker'].lower()}.csv"
        with ZipFile(output_zip, "w") as archive:
            archive.writestr(member_name, "\n".join(daily_rows) + "\n")


def summarize_data_tree(limit: int = 12) -> dict:
    if not DATA_DIR.exists():
        return {"available": False, "asset_groups": [], "sample_files": []}

    group_counter: Counter[str] = Counter()
    sample_files: list[str] = []

    for file_path in DATA_DIR.rglob("*"):
        if not file_path.is_file():
            continue

        relative_parts = file_path.relative_to(DATA_DIR).parts
        if relative_parts:
            group_counter[relative_parts[0]] += 1
        if len(sample_files) < limit:
            sample_files.append(str(file_path.relative_to(ROOT)))

    return {
        "available": True,
        "asset_groups": [{"name": name, "files": count} for name, count in sorted(group_counter.items())],
        "sample_files": sample_files,
    }


def inspect_zip_timeseries(relative_path: str) -> dict:
    path = ROOT / relative_path
    if not path.exists():
        return {
            "path": relative_path,
            "available": False,
            "rows": 0,
            "start": None,
            "end": None,
        }

    with ZipFile(path) as archive:
        member = archive.namelist()[0]
        rows = archive.read(member).decode("utf-8").splitlines()

    first_timestamp = rows[0].split(",")[0].split()[0] if rows else None
    last_timestamp = rows[-1].split(",")[0].split()[0] if rows else None
    return {
        "path": relative_path,
        "available": True,
        "rows": len(rows),
        "start": first_timestamp,
        "end": last_timestamp,
    }


def list_directory(relative_path: str) -> list[str]:
    path = ROOT / relative_path
    if not path.exists():
        return []
    return sorted(item.name for item in path.iterdir())


def build_phase_inventory(config: dict, data_summary: dict) -> dict:
    phase1 = config["phase1"]
    coverage_checks = []
    for asset in phase1["universe"]["assets"]:
        coverage = inspect_zip_timeseries(asset["data_path"])
        coverage_checks.append(
            {
                "ticker": asset["ticker"],
                "security_type": asset["security_type"],
                "market": asset["market"],
                **coverage,
            }
        )

    candidates = {
        "equity_daily": list_directory("data/equity/usa/daily"),
        "equity_hour": list_directory("data/equity/usa/hour"),
        "equity_minute": list_directory("data/equity/usa/minute"),
        "crypto_coinbase_daily": list_directory("data/crypto/coinbase/daily"),
        "crypto_coinbase_minute": list_directory("data/crypto/coinbase/minute"),
        "cryptofuture_binance_daily": list_directory("data/cryptofuture/binance/daily"),
        "cryptofuture_binance_minute": list_directory("data/cryptofuture/binance/minute"),
    }

    return {
        "project": config["name"],
        "phase": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "objective": phase1["objective"],
        "high_level_data_summary": data_summary,
        "candidate_sets": candidates,
        "configured_universe": phase1["universe"],
        "configured_windows": phase1["windows"],
        "configured_features": phase1["features"],
        "configured_target": phase1["target"],
        "configured_model": config["phase3"]["model"],
        "coverage_checks": coverage_checks,
    }


def load_lean_bars(asset: dict, common_window: dict) -> pd.DataFrame:
    path = ROOT / asset["data_path"]
    with ZipFile(path) as archive:
        member = archive.namelist()[0]
        with archive.open(member) as handle:
            frame = pd.read_csv(handle, header=None, names=RAW_COLUMNS)

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], format="%Y%m%d %H:%M", errors="coerce")
    for column in PRICE_COLUMNS + ["volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if asset["security_type"] == "equity":
        frame[PRICE_COLUMNS] = frame[PRICE_COLUMNS] / 10000.0

    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"]).copy()
    frame["date"] = frame["timestamp"].dt.normalize()
    frame = frame.sort_values("date").drop_duplicates(subset="date", keep="last")

    start = pd.Timestamp(common_window["start"])
    end = pd.Timestamp(common_window["end"])
    frame = frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()

    frame["ticker"] = asset["ticker"]
    frame["security_type"] = asset["security_type"]
    frame["market"] = asset["market"]
    return frame.reset_index(drop=True)


def synchronize_assets(asset_frames: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp]]:
    common_dates: set[pd.Timestamp] | None = None

    for frame in asset_frames.values():
        date_set = set(frame["date"].tolist())
        common_dates = date_set if common_dates is None else common_dates & date_set

    ordered_dates = sorted(common_dates or [])
    synchronized = {}
    for ticker, frame in asset_frames.items():
        synchronized[ticker] = (
            frame[frame["date"].isin(ordered_dates)]
            .sort_values("date")
            .reset_index(drop=True)
        )
    return synchronized, ordered_dates


def assign_split(date_value: pd.Timestamp, windows: dict) -> str | None:
    date_stamp = pd.Timestamp(date_value)
    training = windows["training"]
    validation = windows["validation"]
    backtest = windows["backtest"]

    if pd.Timestamp(training["start"]) <= date_stamp <= pd.Timestamp(training["end"]):
        return "train"
    if pd.Timestamp(validation["start"]) <= date_stamp <= pd.Timestamp(validation["end"]):
        return "validation"
    if pd.Timestamp(backtest["start"]) <= date_stamp <= pd.Timestamp(backtest["end"]):
        return "backtest"
    return None


def engineer_features(frame: pd.DataFrame, feature_names: list[str], windows: dict) -> pd.DataFrame:
    result = frame.copy()
    closes = result["close"].tolist()
    opens = result["open"].tolist()
    highs = result["high"].tolist()
    lows = result["low"].tolist()
    volumes = result["volume"].tolist()

    close_to_close_return_1d: list[float] = [np.nan]
    close_to_close_return_5d: list[float] = [np.nan]
    close_to_close_return_20d: list[float] = [np.nan]
    rolling_volatility_5d: list[float] = [np.nan]
    rolling_volatility_20d: list[float] = [np.nan]
    momentum_5d: list[float] = [np.nan]
    momentum_20d: list[float] = [np.nan]
    high_low_range_pct: list[float] = [np.nan]
    open_close_range_pct: list[float] = [np.nan]
    volume_change_1d: list[float] = [np.nan]

    for index in range(1, len(result)):
        previous_close = closes[index - 1]
        previous_volume = volumes[index - 1]
        current_close = closes[index]
        current_open = opens[index]

        lookback_5_index = max(0, index - 5)
        lookback_20_index = max(0, index - 20)
        close_5 = closes[lookback_5_index]
        close_20 = closes[lookback_20_index]

        all_recent_returns = [
            closes[position] / closes[position - 1] - 1.0
            for position in range(1, index + 1)
            if closes[position - 1] != 0
        ]
        recent_returns_5 = all_recent_returns[-5:]
        recent_returns_20 = all_recent_returns[-20:]

        close_to_close_return_1d.append(current_close / previous_close - 1.0 if previous_close else 0.0)
        close_to_close_return_5d.append(current_close / close_5 - 1.0 if close_5 else 0.0)
        close_to_close_return_20d.append(current_close / close_20 - 1.0 if close_20 else 0.0)
        rolling_volatility_5d.append(float(np.std(recent_returns_5, ddof=1)) if len(recent_returns_5) >= 2 else 0.0)
        rolling_volatility_20d.append(float(np.std(recent_returns_20, ddof=1)) if len(recent_returns_20) >= 2 else 0.0)
        momentum_5d.append(current_close / close_5 - 1.0 if close_5 else 0.0)
        momentum_20d.append(current_close / close_20 - 1.0 if close_20 else 0.0)
        high_low_range_pct.append((highs[index] - lows[index]) / current_close if current_close else 0.0)
        open_close_range_pct.append((current_close - current_open) / current_open if current_open else 0.0)
        volume_change_1d.append(0.0 if previous_volume == 0 else volumes[index] / previous_volume - 1.0)

    result["close_to_close_return_1d"] = close_to_close_return_1d
    result["close_to_close_return_5d"] = close_to_close_return_5d
    result["close_to_close_return_20d"] = close_to_close_return_20d
    result["rolling_volatility_5d"] = rolling_volatility_5d
    result["rolling_volatility_20d"] = rolling_volatility_20d
    result["momentum_5d"] = momentum_5d
    result["momentum_20d"] = momentum_20d
    result["high_low_range_pct"] = high_low_range_pct
    result["open_close_range_pct"] = open_close_range_pct
    result["volume_change_1d"] = volume_change_1d

    result["target_return_1d"] = result["close"].shift(-1) / result["close"] - 1.0
    result["target_direction"] = np.where(
        result["target_return_1d"].notna(),
        (result["target_return_1d"] > 0).astype(int),
        np.nan,
    )
    result["split"] = result["date"].apply(lambda value: assign_split(value, windows))

    required_columns = feature_names + ["target_return_1d", "target_direction", "split"]
    result = result.dropna(subset=required_columns).reset_index(drop=True)
    result["target_direction"] = result["target_direction"].astype(int)
    return result


def build_feature_dataset(config: dict) -> tuple[pd.DataFrame, dict]:
    phase1 = config["phase1"]
    assets = phase1["universe"]["assets"]
    feature_names = phase1["features"]["input_set"]
    windows = phase1["windows"]

    asset_frames = {
        asset["ticker"]: load_lean_bars(asset, phase1["universe"]["common_window"])
        for asset in assets
    }
    union_dates = sorted({date_value for frame in asset_frames.values() for date_value in frame["date"].tolist()})
    intersection_dates: set[pd.Timestamp] | None = None
    for frame in asset_frames.values():
        date_set = set(frame["date"].tolist())
        intersection_dates = date_set if intersection_dates is None else intersection_dates & date_set

    dataset_frames = []
    asset_summaries = []
    for asset in assets:
        ticker = asset["ticker"]
        asset_frame = asset_frames[ticker].sort_values("date").reset_index(drop=True)
        engineered = engineer_features(asset_frame, feature_names, windows)
        dataset_frames.append(engineered)
        asset_summaries.append(
            {
                "ticker": ticker,
                "available_rows": int(len(asset_frame)),
                "feature_rows": int(len(engineered)),
                "date_start": asset_frame["date"].min().date().isoformat()
                if not asset_frame.empty else None,
                "date_end": asset_frame["date"].max().date().isoformat()
                if not asset_frame.empty else None,
            }
        )

    dataset = pd.concat(dataset_frames, ignore_index=True)
    dataset = dataset.sort_values(["date", "ticker"]).reset_index(drop=True)
    dataset["date"] = dataset["date"].dt.strftime("%Y-%m-%d")

    metadata = {
        "alignment_mode": "per_asset_window_union",
        "union_dates": len(union_dates),
        "intersection_dates": len(intersection_dates or set()),
        "asset_summaries": asset_summaries,
    }
    return dataset, metadata


def build_asset_quality(config: dict, dataset: pd.DataFrame, metadata: dict) -> dict:
    phase9 = config.get("phase9", {})
    quality_config = phase9.get("asset_quality", {})
    min_total_rows = int(quality_config.get("min_total_feature_rows", 50))
    min_training_rows = int(quality_config.get("min_training_rows", 100))
    min_backtest_rows = int(quality_config.get("min_backtest_rows", 20))

    summary_by_ticker = {item["ticker"]: item for item in metadata.get("asset_summaries", [])}
    assets_by_ticker = {asset["ticker"]: asset for asset in config["phase1"]["universe"]["assets"]}
    grouped_counts = dataset.groupby(["ticker", "split"]).size().reset_index(name="rows")
    split_counts: dict[str, dict[str, int]] = {}
    for row in grouped_counts.to_dict(orient="records"):
        split_counts.setdefault(row["ticker"], {})
        split_counts[row["ticker"]][row["split"]] = int(row["rows"])

    quality: dict[str, dict] = {}
    for ticker, asset in assets_by_ticker.items():
        summary = summary_by_ticker.get(ticker, {})
        counts = split_counts.get(ticker, {})
        total_rows = int(summary.get("feature_rows", 0))
        training_rows = int(counts.get("train", 0))
        validation_rows = int(counts.get("validation", 0))
        backtest_rows = int(counts.get("backtest", 0))

        training_eligible = (
            total_rows >= min_total_rows
            and training_rows >= min_training_rows
            and backtest_rows >= min_backtest_rows
        )
        trading_eligible = training_eligible

        if training_eligible:
            quality_tier = "core"
            reason = "sufficient_training_and_backtest_history"
            role = "model_training_and_trading"
        elif total_rows >= 2:
            quality_tier = "thin"
            reason = "kept_visible_but_history_is_too_short_for_model_training_or_trading"
            role = "observation_only"
        else:
            quality_tier = "insufficient"
            reason = "not_enough_feature_rows_after_engineering"
            role = "observation_only"

        quality[ticker] = {
            "ticker": ticker,
            "security_type": asset["security_type"],
            "market": asset["market"],
            "quality_tier": quality_tier,
            "role": role,
            "training_eligible": training_eligible,
            "trading_eligible": trading_eligible,
            "available_rows": int(summary.get("available_rows", 0)),
            "feature_rows": total_rows,
            "split_rows": {
                "train": training_rows,
                "validation": validation_rows,
                "backtest": backtest_rows,
            },
            "date_start": summary.get("date_start"),
            "date_end": summary.get("date_end"),
            "reason": reason,
        }

    return quality


def apply_asset_quality_flags(dataset: pd.DataFrame, asset_quality: dict) -> pd.DataFrame:
    result = dataset.copy()
    result["quality_tier"] = result["ticker"].map(
        lambda ticker: asset_quality.get(ticker, {}).get("quality_tier", "unknown")
    )
    result["training_eligible"] = result["ticker"].map(
        lambda ticker: bool(asset_quality.get(ticker, {}).get("training_eligible", False))
    )
    result["trading_eligible"] = result["ticker"].map(
        lambda ticker: bool(asset_quality.get(ticker, {}).get("trading_eligible", False))
    )
    return result


def fit_and_apply_scaler(dataset: pd.DataFrame, feature_names: list[str]) -> tuple[pd.DataFrame, StandardScaler]:
    train_mask = dataset["split"] == "train"
    if "training_eligible" in dataset.columns:
        train_mask = train_mask & dataset["training_eligible"]
    if int(train_mask.sum()) == 0:
        raise ValueError("No training-eligible rows available to fit scaler.")

    scaler = StandardScaler()
    scaler.fit(dataset.loc[train_mask, feature_names])

    scaled_values = scaler.transform(dataset[feature_names])
    for index, feature_name in enumerate(feature_names):
        dataset[f"{feature_name}_scaled"] = scaled_values[:, index]

    return dataset, scaler


def add_asset_context_features(dataset: pd.DataFrame, tickers: list[str]) -> tuple[pd.DataFrame, list[str]]:
    context_columns: list[str] = []
    for ticker in tickers:
        column_name = f"asset_{ticker}"
        dataset[column_name] = (dataset["ticker"] == ticker).astype(float)
        context_columns.append(column_name)
    return dataset, context_columns


def build_dataset_manifest(
    config: dict,
    dataset: pd.DataFrame,
    inventory: dict,
    metadata: dict,
    asset_quality: dict,
) -> dict:
    base_feature_names = config["phase1"]["features"]["input_set"]
    context_feature_names = [column for column in dataset.columns if column.startswith("asset_")]
    scaled_feature_names = [f"{feature_name}_scaled" for feature_name in base_feature_names]
    model_input_names = scaled_feature_names + context_feature_names

    split_counts = {split: int(count) for split, count in dataset["split"].value_counts().sort_index().items()}
    per_asset_split = {}
    grouped = dataset.groupby(["ticker", "split"]).size().reset_index(name="rows")
    for row in grouped.to_dict(orient="records"):
        ticker = row["ticker"]
        per_asset_split.setdefault(ticker, {})
        per_asset_split[ticker][row["split"]] = int(row["rows"])

    return {
        "project": config["name"],
        "phase": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_rows": int(len(dataset)),
        "feature_count": len(base_feature_names),
        "feature_names": base_feature_names,
        "scaled_feature_names": scaled_feature_names,
        "context_feature_names": context_feature_names,
        "model_input_names": model_input_names,
        "model_input_count": len(model_input_names),
        "target_column": "target_direction",
        "aux_target_column": "target_return_1d",
        "split_counts": split_counts,
        "per_asset_split_counts": per_asset_split,
        "asset_quality": asset_quality,
        "training_eligible_assets": [
            ticker for ticker, quality in asset_quality.items() if quality["training_eligible"]
        ],
        "trading_eligible_assets": [
            ticker for ticker, quality in asset_quality.items() if quality["trading_eligible"]
        ],
        "observation_only_assets": [
            ticker for ticker, quality in asset_quality.items() if not quality["trading_eligible"]
        ],
        "date_range": {
            "start": str(dataset["date"].min()) if not dataset.empty else None,
            "end": str(dataset["date"].max()) if not dataset.empty else None,
        },
        "alignment": metadata,
        "inventory_snapshot": inventory["coverage_checks"],
    }


def write_inventory_file(inventory: dict) -> None:
    INVENTORY_PATH.write_text(json.dumps(inventory, indent=2), encoding="utf-8")


def write_dataset_artifacts(
    dataset: pd.DataFrame,
    manifest: dict,
    scaler: StandardScaler,
    config: dict | None = None,
) -> None:
    dataset.to_csv(FULL_DATASET_PATH, index=False)
    dataset[dataset["split"] == "train"].to_csv(TRAIN_DATASET_PATH, index=False)
    dataset[dataset["split"] == "validation"].to_csv(VALIDATION_DATASET_PATH, index=False)
    dataset[dataset["split"] == "backtest"].to_csv(BACKTEST_DATASET_PATH, index=False)

    DATASET_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    FEATURE_SCHEMA_PATH.write_text(
        json.dumps(
            {
                "project": manifest["project"],
                "phase": 2,
                "feature_names": manifest["feature_names"],
                "scaled_feature_names": manifest["scaled_feature_names"],
                "context_feature_names": manifest["context_feature_names"],
                "model_input_names": manifest["model_input_names"],
                "target_column": manifest["target_column"],
                "split_column": "split",
                "asset_quality": manifest["asset_quality"],
                "training_eligible_assets": manifest["training_eligible_assets"],
                "trading_eligible_assets": manifest["trading_eligible_assets"],
                "observation_only_assets": manifest["observation_only_assets"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    joblib.dump(scaler, SCALER_PATH)
    SCALER_STATS_PATH.write_text(
        json.dumps(
            {
                "feature_names": manifest["feature_names"],
                "mean": [float(value) for value in scaler.mean_.tolist()],
                "scale": [float(value) for value in scaler.scale_.tolist()],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    expert_dataset, expert_manifest = build_expert_dataset_manifest(dataset, manifest, config)
    write_expert_dataset_artifacts(
        expert_dataset,
        expert_manifest,
        EXPERT_DATASET_DIR,
        EXPERT_DATASET_MANIFEST_PATH,
    )


class AetherNet(nn.Module):
    def __init__(
        self,
        input_dim: int,
        hidden_layers: list[int],
        dropout: float,
        activation: str = "relu",
        normalization: str = "none",
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        current_dim = input_dim
        for hidden_dim in hidden_layers:
            layers.append(nn.Linear(current_dim, hidden_dim))
            norm_layer = build_normalization(normalization, hidden_dim)
            if norm_layer is not None:
                layers.append(norm_layer)
            layers.append(build_activation(activation))
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            current_dim = hidden_dim
        layers.append(nn.Linear(current_dim, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features).squeeze(-1)


def build_activation(name: str) -> nn.Module:
    normalized = name.lower()
    if normalized == "relu":
        return nn.ReLU()
    if normalized == "gelu":
        return nn.GELU()
    if normalized == "silu":
        return nn.SiLU()
    raise ValueError(f"Unsupported activation: {name}")


def build_normalization(name: str, hidden_dim: int) -> nn.Module | None:
    normalized = name.lower()
    if normalized in {"none", "off"}:
        return None
    if normalized == "layernorm":
        return nn.LayerNorm(hidden_dim)
    if normalized == "batchnorm":
        return nn.BatchNorm1d(hidden_dim)
    raise ValueError(f"Unsupported normalization: {name}")


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def split_frame(dataset: pd.DataFrame, split_name: str) -> pd.DataFrame:
    return dataset[dataset["split"] == split_name].reset_index(drop=True)


def frame_to_tensors(frame: pd.DataFrame, feature_names: list[str]) -> tuple[torch.Tensor, torch.Tensor]:
    features = torch.tensor(frame[feature_names].to_numpy(dtype=np.float32), dtype=torch.float32)
    targets = torch.tensor(frame["target_direction"].to_numpy(dtype=np.float32), dtype=torch.float32)
    return features, targets


def compute_binary_metrics(
    logits: torch.Tensor,
    targets: torch.Tensor,
    criterion: nn.Module,
    threshold: float,
) -> dict:
    loss = float(criterion(logits, targets).item())
    probabilities = torch.sigmoid(logits)
    predictions = (probabilities >= threshold).float()

    targets_np = targets.detach().cpu().numpy()
    predictions_np = predictions.detach().cpu().numpy()
    probabilities_np = probabilities.detach().cpu().numpy()

    tp = int(((predictions_np == 1) & (targets_np == 1)).sum())
    tn = int(((predictions_np == 0) & (targets_np == 0)).sum())
    fp = int(((predictions_np == 1) & (targets_np == 0)).sum())
    fn = int(((predictions_np == 0) & (targets_np == 1)).sum())

    total = max(len(targets_np), 1)
    accuracy = (tp + tn) / total
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    balanced_accuracy = (recall + specificity) / 2.0
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    denominator = max(((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5, 1e-12)
    matthews_corrcoef = ((tp * tn) - (fp * fn)) / denominator

    return {
        "loss": loss,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
        "mcc": matthews_corrcoef,
        "threshold": threshold,
        "positive_rate": float(predictions_np.mean()) if len(predictions_np) else 0.0,
        "average_probability": float(probabilities_np.mean()) if len(probabilities_np) else 0.0,
        "confusion_matrix": {
            "tp": tp,
            "tn": tn,
            "fp": fp,
            "fn": fn,
        },
    }


def evaluate_split(
    model: nn.Module,
    frame: pd.DataFrame,
    feature_names: list[str],
    criterion: nn.Module,
    threshold: float,
    device: torch.device,
) -> dict:
    features, targets = frame_to_tensors(frame, feature_names)
    features = features.to(device)
    targets = targets.to(device)

    model.eval()
    with torch.no_grad():
        logits = model(features)
    return compute_binary_metrics(logits, targets, criterion, threshold)


def predict_probabilities(
    model: nn.Module,
    frame: pd.DataFrame,
    feature_names: list[str],
    device: torch.device,
) -> np.ndarray:
    features, _ = frame_to_tensors(frame, feature_names)
    features = features.to(device)

    model.eval()
    with torch.no_grad():
        logits = model(features)
        probabilities = torch.sigmoid(logits)
    return probabilities.detach().cpu().numpy()


def compute_strategy_metrics(
    frame: pd.DataFrame,
    probability_column: str,
    buy_threshold: float,
    sell_threshold: float,
    trading_days_per_year: int,
) -> tuple[dict, pd.DataFrame]:
    report_frame = frame.copy()
    report_frame["probability_up"] = report_frame[probability_column].astype(float)
    report_frame["position"] = np.where(report_frame["probability_up"] >= buy_threshold, 1.0, 0.0)
    report_frame["strategy_return"] = report_frame["position"] * report_frame["target_return_1d"]
    report_frame["baseline_return"] = report_frame["target_return_1d"]
    report_frame["cumulative_strategy"] = (1.0 + report_frame["strategy_return"]).cumprod()
    report_frame["cumulative_baseline"] = (1.0 + report_frame["baseline_return"]).cumprod()
    report_frame["strategy_drawdown"] = (
        report_frame["cumulative_strategy"] / report_frame["cumulative_strategy"].cummax() - 1.0
    )
    report_frame["baseline_drawdown"] = (
        report_frame["cumulative_baseline"] / report_frame["cumulative_baseline"].cummax() - 1.0
    )

    strategy_returns = report_frame["strategy_return"].to_numpy(dtype=float)
    baseline_returns = report_frame["baseline_return"].to_numpy(dtype=float)
    positions = report_frame["position"].to_numpy(dtype=float)
    position_changes = np.abs(np.diff(np.concatenate(([0.0], positions))))

    strategy_total_return = float(report_frame["cumulative_strategy"].iloc[-1] - 1.0) if len(report_frame) else 0.0
    baseline_total_return = float(report_frame["cumulative_baseline"].iloc[-1] - 1.0) if len(report_frame) else 0.0

    strategy_mean = float(strategy_returns.mean()) if len(strategy_returns) else 0.0
    baseline_mean = float(baseline_returns.mean()) if len(baseline_returns) else 0.0
    strategy_vol = float(strategy_returns.std(ddof=1)) if len(strategy_returns) > 1 else 0.0
    baseline_vol = float(baseline_returns.std(ddof=1)) if len(baseline_returns) > 1 else 0.0

    annual_factor = math.sqrt(trading_days_per_year)
    strategy_sharpe = (strategy_mean / strategy_vol) * annual_factor if strategy_vol > 0 else 0.0
    baseline_sharpe = (baseline_mean / baseline_vol) * annual_factor if baseline_vol > 0 else 0.0

    strategy_max_drawdown = float(report_frame["strategy_drawdown"].min()) if len(report_frame) else 0.0
    baseline_max_drawdown = float(report_frame["baseline_drawdown"].min()) if len(report_frame) else 0.0
    strategy_hit_rate = float((strategy_returns > 0).mean()) if len(strategy_returns) else 0.0
    baseline_hit_rate = float((baseline_returns > 0).mean()) if len(baseline_returns) else 0.0

    return (
        {
            "rows": int(len(report_frame)),
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "exposure_rate": float(positions.mean()) if len(positions) else 0.0,
            "trade_count": int((position_changes > 0).sum()),
            "turnover": float(position_changes.sum()),
            "strategy": {
                "total_return": strategy_total_return,
                "annualized_return": float((1.0 + strategy_total_return) ** (trading_days_per_year / max(len(report_frame), 1)) - 1.0)
                if len(report_frame) else 0.0,
                "annualized_volatility": strategy_vol * annual_factor,
                "sharpe": strategy_sharpe,
                "max_drawdown": strategy_max_drawdown,
                "hit_rate": strategy_hit_rate,
                "average_daily_return": strategy_mean,
            },
            "buy_and_hold": {
                "total_return": baseline_total_return,
                "annualized_return": float((1.0 + baseline_total_return) ** (trading_days_per_year / max(len(report_frame), 1)) - 1.0)
                if len(report_frame) else 0.0,
                "annualized_volatility": baseline_vol * annual_factor,
                "sharpe": baseline_sharpe,
                "max_drawdown": baseline_max_drawdown,
                "hit_rate": baseline_hit_rate,
                "average_daily_return": baseline_mean,
            },
            "excess_return_vs_buy_and_hold": strategy_total_return - baseline_total_return,
        },
        report_frame,
    )


def build_strategy_report(
    config: dict,
    model: nn.Module,
    dataset: pd.DataFrame,
    feature_names: list[str],
    threshold: float,
    device: torch.device,
) -> tuple[dict, pd.DataFrame]:
    backtest_config = config["phase5"]["backtest"]
    threshold_offset_buy = float(backtest_config.get("buy_threshold_offset", 0.08))
    threshold_offset_sell = float(backtest_config.get("sell_threshold_offset", 0.08))
    buy_threshold = min(0.95, threshold + threshold_offset_buy)
    sell_threshold = max(0.05, threshold - threshold_offset_sell)
    trading_days_per_year = int(backtest_config.get("trading_days_per_year", 252))

    split_reports = {}
    curve_frames = []

    for split_name in ("validation", "backtest"):
        split_frame_df = split_frame(dataset, split_name).copy()
        split_frame_df["probability_up"] = predict_probabilities(model, split_frame_df, feature_names, device)
        split_report, split_curve = compute_strategy_metrics(
            split_frame_df,
            probability_column="probability_up",
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            trading_days_per_year=trading_days_per_year,
        )
        split_reports[split_name] = split_report
        split_curve["split"] = split_name
        curve_frames.append(
            split_curve[
                [
                    "date",
                    "ticker",
                    "split",
                    "probability_up",
                    "position",
                    "strategy_return",
                    "baseline_return",
                    "cumulative_strategy",
                    "cumulative_baseline",
                    "strategy_drawdown",
                    "baseline_drawdown",
                ]
            ]
        )

    per_asset_report = {}
    backtest_frame_df = split_frame(dataset, "backtest").copy()
    backtest_frame_df["probability_up"] = predict_probabilities(model, backtest_frame_df, feature_names, device)
    for ticker in sorted(backtest_frame_df["ticker"].unique()):
        asset_frame = backtest_frame_df[backtest_frame_df["ticker"] == ticker].reset_index(drop=True)
        asset_report, _ = compute_strategy_metrics(
            asset_frame,
            probability_column="probability_up",
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            trading_days_per_year=trading_days_per_year,
        )
        per_asset_report[ticker] = asset_report

    report = {
        "project": config["name"],
        "phase": 5,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy_mode": backtest_config.get("strategy_mode", "long_flat"),
        "buy_threshold": buy_threshold,
        "sell_threshold": sell_threshold,
        "trading_days_per_year": trading_days_per_year,
        "validation": split_reports["validation"],
        "backtest": split_reports["backtest"],
        "backtest_per_asset": per_asset_report,
    }

    combined_curves = pd.concat(curve_frames, ignore_index=True)
    return report, combined_curves


def find_optimal_threshold(
    logits: torch.Tensor,
    targets: torch.Tensor,
    criterion: nn.Module,
    metric_name: str,
    threshold_min: float,
    threshold_max: float,
    threshold_steps: int,
) -> tuple[float, dict]:
    best_threshold = 0.5
    best_metrics = compute_binary_metrics(logits, targets, criterion, best_threshold)
    best_score = best_metrics.get(metric_name, best_metrics["f1"])

    for threshold in np.linspace(threshold_min, threshold_max, threshold_steps):
        threshold = float(round(float(threshold), 4))
        metrics = compute_binary_metrics(logits, targets, criterion, threshold)
        score = metrics.get(metric_name, metrics["f1"])

        if score > best_score or (abs(score - best_score) < 1e-12 and abs(threshold - 0.5) < abs(best_threshold - 0.5)):
            best_threshold = threshold
            best_metrics = metrics
            best_score = score

    return best_threshold, best_metrics


def export_state_dict(model: nn.Module) -> dict:
    exported = {}
    for key, value in model.state_dict().items():
        exported[key] = value.detach().cpu().tolist()
    return exported


def export_architecture(model: AetherNet) -> list[dict]:
    architecture: list[dict] = []
    for index, module in enumerate(model.network):
        if isinstance(module, nn.Linear):
            architecture.append(
                {
                    "type": "linear",
                    "weight_key": f"network.{index}.weight",
                    "bias_key": f"network.{index}.bias",
                    "in_features": module.in_features,
                    "out_features": module.out_features,
                }
            )
        elif isinstance(module, nn.LayerNorm):
            architecture.append(
                {
                    "type": "layernorm",
                    "weight_key": f"network.{index}.weight",
                    "bias_key": f"network.{index}.bias",
                    "normalized_shape": list(module.normalized_shape),
                    "eps": module.eps,
                }
            )
        elif isinstance(module, nn.BatchNorm1d):
            architecture.append(
                {
                    "type": "batchnorm1d",
                    "weight_key": f"network.{index}.weight",
                    "bias_key": f"network.{index}.bias",
                    "running_mean_key": f"network.{index}.running_mean",
                    "running_var_key": f"network.{index}.running_var",
                    "num_features": module.num_features,
                    "eps": module.eps,
                }
            )
        elif isinstance(module, nn.ReLU):
            architecture.append({"type": "relu"})
        elif isinstance(module, nn.GELU):
            architecture.append({"type": "gelu"})
        elif isinstance(module, nn.SiLU):
            architecture.append({"type": "silu"})
        elif isinstance(module, nn.Dropout):
            architecture.append({"type": "dropout", "p": module.p})
        else:
            architecture.append({"type": module.__class__.__name__.lower()})
    architecture.append({"type": "sigmoid"})
    return architecture


def train_model(config: dict, dataset: pd.DataFrame) -> dict:
    phase3 = config["phase3"]
    training_config = phase3["training"]
    model_config = phase3["model"]
    feature_names = [f"{name}_scaled" for name in config["phase1"]["features"]["input_set"]]
    if bool(model_config.get("use_asset_context", False)):
        feature_names += [column for column in dataset.columns if column.startswith("asset_")]

    set_seed(int(training_config["seed"]))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    training_dataset = dataset
    if "training_eligible" in dataset.columns:
        training_dataset = dataset[dataset["training_eligible"]].copy()
    if training_dataset.empty:
        raise ValueError("No training-eligible assets available for model training.")

    train_frame = split_frame(training_dataset, "train")
    validation_frame = split_frame(training_dataset, "validation")
    backtest_frame = split_frame(training_dataset, "backtest")
    if train_frame.empty or validation_frame.empty or backtest_frame.empty:
        raise ValueError("Training, validation and backtest splits must all contain eligible rows.")

    train_features, train_targets = frame_to_tensors(train_frame, feature_names)
    validation_features, validation_targets = frame_to_tensors(validation_frame, feature_names)

    train_loader = DataLoader(
        TensorDataset(train_features, train_targets),
        batch_size=int(training_config["batch_size"]),
        shuffle=True,
    )

    model = AetherNet(
        input_dim=len(feature_names),
        hidden_layers=list(model_config["hidden_layers"]),
        dropout=float(model_config["dropout"]),
        activation=str(model_config.get("activation", "relu")),
        normalization=str(model_config.get("normalization", "none")),
    ).to(device)

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=float(training_config["learning_rate"]),
        weight_decay=float(training_config["weight_decay"]),
    )
    positive_count = max(float(train_frame["target_direction"].sum()), 1.0)
    negative_count = max(float(len(train_frame) - train_frame["target_direction"].sum()), 1.0)
    pos_weight = torch.tensor(negative_count / positive_count, dtype=torch.float32, device=device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    threshold = float(training_config["decision_threshold"])
    patience = int(training_config["patience"])
    max_epochs = int(training_config["epochs"])
    threshold_metric = str(training_config.get("optimize_threshold_metric", "f1"))
    threshold_min = float(training_config.get("threshold_search_min", 0.35))
    threshold_max = float(training_config.get("threshold_search_max", 0.65))
    threshold_steps = int(training_config.get("threshold_search_steps", 61))

    best_state = None
    best_epoch = 0
    best_validation_loss = float("inf")
    epochs_without_improvement = 0
    history: list[dict] = []

    validation_features = validation_features.to(device)
    validation_targets = validation_targets.to(device)

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

        train_epoch_loss = running_loss / max(sample_count, 1)

        model.eval()
        with torch.no_grad():
            validation_logits = model(validation_features)
        validation_metrics = compute_binary_metrics(validation_logits, validation_targets, criterion, threshold)

        history.append(
            {
                "epoch": epoch,
                "train_loss": train_epoch_loss,
                "validation_loss": validation_metrics["loss"],
                "validation_accuracy": validation_metrics["accuracy"],
                "validation_balanced_accuracy": validation_metrics["balanced_accuracy"],
                "validation_f1": validation_metrics["f1"],
            }
        )

        if validation_metrics["loss"] < best_validation_loss:
            best_validation_loss = validation_metrics["loss"]
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
    torch.save(best_state, MODEL_CHECKPOINT_PATH)

    model.eval()
    with torch.no_grad():
        validation_logits = model(validation_features)
    tuned_threshold, tuned_validation_metrics = find_optimal_threshold(
        validation_logits,
        validation_targets,
        criterion,
        threshold_metric,
        threshold_min,
        threshold_max,
        threshold_steps,
    )

    metrics = {
        "project": config["name"],
        "phase": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "device": str(device),
        "best_epoch": best_epoch,
        "epochs_ran": len(history),
        "threshold_optimization": {
            "metric": threshold_metric,
            "default_threshold": threshold,
            "selected_threshold": tuned_threshold,
            "selected_validation_metrics": tuned_validation_metrics,
        },
        "train": evaluate_split(model, train_frame, feature_names, criterion, tuned_threshold, device),
        "validation": evaluate_split(model, validation_frame, feature_names, criterion, tuned_threshold, device),
        "backtest": evaluate_split(model, backtest_frame, feature_names, criterion, tuned_threshold, device),
        "asset_quality": {
            "training_eligible_assets": sorted(training_dataset["ticker"].unique().tolist()),
            "observation_only_assets": sorted(
                dataset.loc[~dataset.get("training_eligible", pd.Series(True, index=dataset.index)), "ticker"]
                .unique()
                .tolist()
            ) if "training_eligible" in dataset.columns else [],
        },
        "history": history,
    }
    TRAINING_METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    strategy_report, equity_curves = build_strategy_report(
        config=config,
        model=model,
        dataset=training_dataset,
        feature_names=feature_names,
        threshold=tuned_threshold,
        device=device,
    )
    STRATEGY_REPORT_PATH.write_text(json.dumps(strategy_report, indent=2), encoding="utf-8")
    equity_curves.to_csv(EQUITY_CURVES_PATH, index=False)

    return {
        "model": model,
        "metrics": metrics,
        "strategy_report": strategy_report,
        "scaled_feature_names": feature_names,
        "threshold": tuned_threshold,
        "model_config": model_config,
        "training_config": training_config,
    }


def write_model_export(
    config: dict,
    data_summary: dict,
    dataset_manifest: dict | None = None,
    training_result: dict | None = None,
) -> None:
    phase1 = config["phase1"]
    payload = {
        "project": config["name"],
        "phase": 3,
        "status": "trained" if training_result else ("dataset_ready" if dataset_manifest else "placeholder"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "type": config["phase3"]["model"]["type"],
            "input_features": phase1["features"]["input_set"],
            "scaled_input_features": [f"{name}_scaled" for name in phase1["features"]["input_set"]],
            "context_input_features": dataset_manifest["context_feature_names"] if dataset_manifest else [],
            "model_input_features": dataset_manifest["model_input_names"] if dataset_manifest else [],
            "output_schema": phase1["target"]["type"],
        },
        "data_summary": data_summary,
        "v1_universe": phase1["universe"],
        "training_windows": phase1["windows"],
        "dataset_manifest_path": str(DATASET_MANIFEST_PATH.relative_to(ROOT)) if dataset_manifest else None,
        "scaler_path": str(SCALER_PATH.relative_to(ROOT)) if dataset_manifest else None,
        "scaler_stats_path": str(SCALER_STATS_PATH.relative_to(ROOT)) if dataset_manifest else None,
        "checkpoint_path": str(MODEL_CHECKPOINT_PATH.relative_to(ROOT)) if training_result else None,
        "metrics_path": str(TRAINING_METRICS_PATH.relative_to(ROOT)) if training_result else None,
        "strategy_report_path": str(STRATEGY_REPORT_PATH.relative_to(ROOT)) if training_result else None,
        "notes": [
            "Phase 3 trains a first MLP classifier on the synchronized daily dataset.",
            "The exported state_dict is JSON-based so Lean-side inference can be added in Phase 4.",
            "Keep ml/model.pt local-only for the binary PyTorch checkpoint.",
        ],
    }

    if training_result:
        model_config = training_result["model_config"]
        metrics = training_result["metrics"]
        payload["model"].update(
            {
                "hidden_layers": model_config["hidden_layers"],
                "dropout": model_config["dropout"],
                "activation": model_config["activation"],
                "normalization": model_config.get("normalization", "none"),
                "use_asset_context": model_config.get("use_asset_context", False),
                "output_activation": model_config["output_activation"],
            }
        )
        payload["training"] = {
            "best_epoch": metrics["best_epoch"],
            "epochs_ran": metrics["epochs_ran"],
            "decision_threshold": training_result["threshold"],
            "threshold_metric": training_result["training_config"].get("optimize_threshold_metric", "f1"),
            "validation_accuracy": metrics["validation"]["accuracy"],
            "validation_balanced_accuracy": metrics["validation"]["balanced_accuracy"],
            "validation_f1": metrics["validation"]["f1"],
            "backtest_accuracy": metrics["backtest"]["accuracy"],
            "backtest_balanced_accuracy": metrics["backtest"]["balanced_accuracy"],
            "backtest_f1": metrics["backtest"]["f1"],
        }
        payload["backtest"] = training_result["strategy_report"]
        payload["export"] = {
            "architecture": export_architecture(training_result["model"]),
            "state_dict": export_state_dict(training_result["model"]),
        }

    MODEL_WEIGHTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_existing_training_context() -> dict | None:
    if not TRAINING_METRICS_PATH.exists() or not STRATEGY_REPORT_PATH.exists():
        return None

    metrics = json.loads(TRAINING_METRICS_PATH.read_text(encoding="utf-8"))
    strategy_report = json.loads(STRATEGY_REPORT_PATH.read_text(encoding="utf-8"))
    feature_schema = json.loads(FEATURE_SCHEMA_PATH.read_text(encoding="utf-8")) if FEATURE_SCHEMA_PATH.exists() else {}
    model_export = json.loads(MODEL_WEIGHTS_PATH.read_text(encoding="utf-8")) if MODEL_WEIGHTS_PATH.exists() else {}
    threshold = metrics.get("threshold_optimization", {}).get(
        "selected_threshold",
        model_export.get("training", {}).get("decision_threshold", 0.5),
    )

    return {
        "metrics": metrics,
        "strategy_report": strategy_report,
        "threshold": threshold,
        "scaled_feature_names": list(feature_schema.get("model_input_names", [])),
    }


def build_phase8_asset_heatmap(strategy_report: dict | None) -> list[dict]:
    if not strategy_report:
        return []

    heatmap = []
    per_asset = strategy_report.get("backtest_per_asset", {})
    for ticker, asset_report in sorted(per_asset.items()):
        strategy = asset_report["strategy"]
        heatmap.append(
            {
                "ticker": ticker,
                "strategy_return": strategy["total_return"],
                "excess_return": asset_report["excess_return_vs_buy_and_hold"],
                "sharpe": strategy["sharpe"],
                "max_drawdown": strategy["max_drawdown"],
                "exposure_rate": asset_report["exposure_rate"],
                "trade_count": asset_report["trade_count"],
                "signal_bias": "positive" if asset_report["excess_return_vs_buy_and_hold"] >= 0 else "negative",
            }
        )
    return heatmap


def build_phase8_scene_payload(
    universe_assets: list[dict],
    strategy_report: dict | None,
    total_portfolio_value: float,
) -> dict:
    nodes = [
        {
            "id": "portfolio_core",
            "label": "Portfolio Core",
            "kind": "portfolio",
            "x": 50,
            "y": 52,
            "z": 0.95,
            "intensity": 0.82,
            "value": total_portfolio_value,
            "detail": "Central portfolio state",
        }
    ]
    links = []
    per_asset = strategy_report.get("backtest_per_asset", {}) if strategy_report else {}
    asset_count = max(len(universe_assets), 1)

    for index, asset in enumerate(universe_assets):
        ticker = asset["ticker"]
        asset_report = per_asset.get(ticker)
        angle = (2 * math.pi * index) / asset_count
        x = 50 + math.cos(angle) * 32
        y = 50 + math.sin(angle) * 22
        z = 0.45 + ((index % 4) * 0.12)
        excess_return = asset_report["excess_return_vs_buy_and_hold"] if asset_report else 0.0
        intensity = 0.5 + max(min(excess_return, 0.6), -0.6) / 1.5
        nodes.append(
            {
                "id": ticker,
                "label": ticker,
                "kind": "asset",
                "x": x,
                "y": y,
                "z": z,
                "intensity": max(0.12, min(0.96, intensity)),
                "value": asset_report["strategy"]["total_return"] if asset_report else 0.0,
                "detail": asset["security_type"],
            }
        )
        links.append(
            {
                "source": "portfolio_core",
                "target": ticker,
                "strength": asset_report["exposure_rate"] if asset_report else 0.25,
            }
        )

    return {
        "layout": "portfolio_star",
        "nodes": nodes,
        "links": links,
        "dimensions": {"width": 100, "height": 100, "depth": 1},
    }


def build_phase8_scorecards(
    config: dict,
    training_context: dict | None,
    total_portfolio_value: float,
) -> list[dict]:
    cards = [
        {
            "key": "portfolio_value",
            "label": "Portfolio Value",
            "value": total_portfolio_value,
            "format": "currency",
        }
    ]

    if not training_context:
        return cards

    metrics = training_context["metrics"]
    strategy_report = training_context["strategy_report"]
    cards.extend(
        [
            {
                "key": "validation_accuracy",
                "label": "Validation Accuracy",
                "value": metrics["validation"]["accuracy"],
                "format": "percent",
            },
            {
                "key": "backtest_return",
                "label": "Backtest Return",
                "value": strategy_report["backtest"]["strategy"]["total_return"],
                "format": "percent",
            },
            {
                "key": "backtest_sharpe",
                "label": "Backtest Sharpe",
                "value": strategy_report["backtest"]["strategy"]["sharpe"],
                "format": "number",
            },
            {
                "key": "max_drawdown",
                "label": "Max Drawdown",
                "value": strategy_report["backtest"]["strategy"]["max_drawdown"],
                "format": "percent",
            },
        ]
    )
    return cards


def write_phase8_exports(
    config: dict,
    training_context: dict | None,
    scene_payload: dict,
    scorecards: list[dict],
    asset_heatmap: list[dict],
) -> None:
    metrics_snapshot = {
        "project": config["name"],
        "phase": 8,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scorecards": scorecards,
        "asset_heatmap": asset_heatmap,
        "feed_files": {
            "state": str(STATE_PATH.relative_to(ROOT)),
            "scene": str(SCENE_PATH.relative_to(ROOT)),
            "equity_curves": str(GRAFANA_EQUITY_CURVES_PATH.relative_to(ROOT)),
            "asset_performance": str(GRAFANA_ASSET_PERFORMANCE_PATH.relative_to(ROOT)),
        },
    }

    if training_context:
        metrics_snapshot["training"] = {
            "best_epoch": training_context["metrics"]["best_epoch"],
            "validation_accuracy": training_context["metrics"]["validation"]["accuracy"],
            "validation_balanced_accuracy": training_context["metrics"]["validation"]["balanced_accuracy"],
            "backtest_accuracy": training_context["metrics"]["backtest"]["accuracy"],
            "decision_threshold": training_context["threshold"],
        }
        metrics_snapshot["strategy"] = training_context["strategy_report"]["backtest"]

    GRAFANA_METRICS_PATH.write_text(json.dumps(metrics_snapshot, indent=2), encoding="utf-8")
    SCENE_PATH.write_text(json.dumps(scene_payload, indent=2), encoding="utf-8")

    if EQUITY_CURVES_PATH.exists():
        GRAFANA_EQUITY_CURVES_PATH.write_text(EQUITY_CURVES_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    asset_frame = pd.DataFrame(asset_heatmap)
    if not asset_frame.empty:
        asset_frame.to_csv(GRAFANA_ASSET_PERFORMANCE_PATH, index=False)


def write_visualization_state(
    config: dict,
    inventory: dict,
    data_summary: dict,
    dataset_manifest: dict | None = None,
    training_context: dict | None = None,
) -> None:
    phase1 = config["phase1"]
    training_state = {
        "status": "trained" if training_context else ("dataset_ready" if dataset_manifest else "not_started"),
        "dataset_available": data_summary["available"],
        "asset_groups": data_summary["asset_groups"],
        "selected_universe": [asset["ticker"] for asset in phase1["universe"]["assets"]],
        "resolution": phase1["universe"]["resolution"],
        "windows": phase1["windows"],
    }

    if dataset_manifest:
        training_state["dataset_rows"] = dataset_manifest["dataset_rows"]
        training_state["feature_count"] = dataset_manifest["feature_count"]
        training_state["split_counts"] = dataset_manifest["split_counts"]
        training_state["alignment_mode"] = dataset_manifest["alignment"]["alignment_mode"]
        training_state["asset_quality"] = dataset_manifest.get("asset_quality", {})
        training_state["training_eligible_assets"] = dataset_manifest.get("training_eligible_assets", [])
        training_state["trading_eligible_assets"] = dataset_manifest.get("trading_eligible_assets", [])
        training_state["observation_only_assets"] = dataset_manifest.get("observation_only_assets", [])

    if training_context:
        metrics = training_context["metrics"]
        strategy_report = training_context["strategy_report"]
        training_state["model_type"] = config["phase3"]["model"]["type"]
        training_state["best_epoch"] = metrics["best_epoch"]
        training_state["model_input_count"] = len(training_context["scaled_feature_names"])
        training_state["validation_accuracy"] = metrics["validation"]["accuracy"]
        training_state["validation_balanced_accuracy"] = metrics["validation"]["balanced_accuracy"]
        training_state["validation_f1"] = metrics["validation"]["f1"]
        training_state["backtest_accuracy"] = metrics["backtest"]["accuracy"]
        training_state["backtest_balanced_accuracy"] = metrics["backtest"]["balanced_accuracy"]
        training_state["backtest_f1"] = metrics["backtest"]["f1"]
        training_state["decision_threshold"] = training_context["threshold"]
        training_state["strategy_total_return"] = strategy_report["backtest"]["strategy"]["total_return"]
        training_state["strategy_sharpe"] = strategy_report["backtest"]["strategy"]["sharpe"]
        training_state["strategy_max_drawdown"] = strategy_report["backtest"]["strategy"]["max_drawdown"]
        training_state["buy_and_hold_return"] = strategy_report["backtest"]["buy_and_hold"]["total_return"]

    total_portfolio_value = float(config["runtime"]["initial_cash"])
    asset_heatmap = build_phase8_asset_heatmap(training_context["strategy_report"] if training_context else None)
    scene_payload = build_phase8_scene_payload(
        phase1["universe"]["assets"],
        training_context["strategy_report"] if training_context else None,
        total_portfolio_value,
    )
    scorecards = build_phase8_scorecards(config, training_context, total_portfolio_value)

    payload = {
        "project": config["name"],
        "mode": "idle",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "insight": "Phase 8 visualization exports ready" if training_context else ("Phase 2 dataset pipeline ready" if dataset_manifest else "Inventory ready"),
        "portfolio": {
            "cash": total_portfolio_value,
            "total_portfolio_value": total_portfolio_value,
        },
        "positions": [],
        "signals": {},
        "training": training_state,
        "dashboard": {
            "scorecards": scorecards,
            "asset_heatmap": asset_heatmap,
            "strategy_snapshot": training_context["strategy_report"]["backtest"] if training_context else None,
            "visualization_stage": "phase8",
        },
        "monitoring": {
            "feeds": {
                "metrics_snapshot": str(GRAFANA_METRICS_PATH.relative_to(ROOT)),
                "equity_curves": str(GRAFANA_EQUITY_CURVES_PATH.relative_to(ROOT)),
                "asset_performance": str(GRAFANA_ASSET_PERFORMANCE_PATH.relative_to(ROOT)),
                "scene": str(SCENE_PATH.relative_to(ROOT)),
            }
        },
        "scene": scene_payload,
        "inventory_snapshot": inventory["coverage_checks"],
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_phase8_exports(config, training_context, scene_payload, scorecards, asset_heatmap)


def main() -> int:
    setup_logging()
    args = parse_args()
    ensure_directories()
    config = load_project_config()
    LOGGER.info("Starting Aether Quant training pipeline.")
    raise_if_validation_failed(validate_training_inputs(config))
    ensure_derived_crypto_daily_series(config)
    data_summary = summarize_data_tree()
    inventory = build_phase_inventory(config, data_summary)
    write_inventory_file(inventory)

    if args.init_only:
        existing_context = load_existing_training_context()
        if existing_context is None and not MODEL_WEIGHTS_PATH.exists():
            write_model_export(config, data_summary)
        write_visualization_state(config, inventory, data_summary, training_context=existing_context)
        LOGGER.info("Inventory refreshed.")
        print("Phase 5 inventory refreshed.")
        return 0

    dataset, metadata = build_feature_dataset(config)
    feature_names = config["phase1"]["features"]["input_set"]
    asset_quality = build_asset_quality(config, dataset, metadata)
    dataset = apply_asset_quality_flags(dataset, asset_quality)
    LOGGER.info(
        "Built dataset with %s rows across %s assets.",
        len(dataset),
        len(asset_quality),
    )
    LOGGER.info(
        "Training-eligible assets: %s",
        ", ".join(ticker for ticker, quality in asset_quality.items() if quality["training_eligible"]),
    )
    observation_only = [ticker for ticker, quality in asset_quality.items() if not quality["trading_eligible"]]
    if observation_only:
        LOGGER.info("Observation-only assets: %s", ", ".join(observation_only))

    dataset, scaler = fit_and_apply_scaler(dataset, feature_names)
    dataset, _ = add_asset_context_features(
        dataset,
        [asset["ticker"] for asset in config["phase1"]["universe"]["assets"]],
    )
    dataset_manifest = build_dataset_manifest(config, dataset, inventory, metadata, asset_quality)
    write_dataset_artifacts(dataset, dataset_manifest, scaler, config=config)

    if args.dataset_only:
        existing_context = load_existing_training_context()
        if existing_context is None:
            write_model_export(config, data_summary, dataset_manifest=dataset_manifest)
        write_visualization_state(
            config,
            inventory,
            data_summary,
            dataset_manifest=dataset_manifest,
            training_context=existing_context,
        )
        print(
            "Phase 5 dataset built without training.",
            f"Rows: {dataset_manifest['dataset_rows']}.",
            f"Splits: {dataset_manifest['split_counts']}.",
        )
        return 0

    LOGGER.info("Training model.")
    training_result = train_model(config, dataset)
    write_model_export(
        config,
        data_summary,
        dataset_manifest=dataset_manifest,
        training_result=training_result,
    )
    write_visualization_state(
        config,
        inventory,
        data_summary,
        dataset_manifest=dataset_manifest,
        training_context=training_result,
    )

    print(
        "Phase 5 model and strategy validation complete.",
        f"Best epoch: {training_result['metrics']['best_epoch']}.",
        f"Validation accuracy: {training_result['metrics']['validation']['accuracy']:.4f}.",
        f"Backtest strategy return: {training_result['strategy_report']['backtest']['strategy']['total_return']:.4f}.",
    )
    LOGGER.info("Training pipeline finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
