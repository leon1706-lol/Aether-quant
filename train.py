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
import bisect
import copy
import json
import logging
import math
import random
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import joblib
import numpy as np
import pandas as pd
import torch
from experts import EXPERT_DEFINITIONS, build_expert_dataset_manifest, write_expert_dataset_artifacts
from features import (
    BOND_FEATURE_NAMES,
    CREDIT_SPREAD_LEVEL_NEUTRAL,
    CREDIT_SPREAD_NEUTRAL,
    CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL,
    CRYPTO_RISK_APPETITE_NEUTRAL,
    YIELD_CURVE_CURVATURE_NEUTRAL,
    YIELD_CURVE_LEVEL_NEUTRAL,
    YIELD_CURVE_SLOPE_NEUTRAL,
    average_true_range_pct,
    bollinger_pctb,
    bond_yield_curve_slope,
    compute_greeks,
    credit_spread_level,
    credit_spread_proxy,
    crypto_risk_appetite_proxy,
    distance_from_52w_high,
    empirical_duration_beta,
    futures_term_structure_slope,
    implied_volatility,
    macd_histogram_normalized,
    options_implied_vol_skew,
    options_put_call_ratio,
    relative_strength_index,
    volume_zscore,
    yield_curve_curvature,
    yield_curve_level,
    yield_curve_slope_proxy,
)
from data_pipeline.fred_backfill import bond_reference_series, load_cached_fred_series
from liquidity import estimate_high_low_spread
from liquidity.market_liquidity import TYPICAL_SPREAD_BY_TYPE
from regime import build_market_regime_vector
from sklearn.preprocessing import StandardScaler
from topology import build_market_topology
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


LOGGER = logging.getLogger("aether_quant.train")
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FACTOR_FILES_DIR = DATA_DIR / "equity" / "usa" / "factor_files"
SECTOR_MAPPING_PATH = DATA_DIR / "reference" / "sector_mapping.json"
ML_DIR = ROOT / "ml"
DATASET_DIR = ML_DIR / "datasets"
EXPERT_DATASET_DIR = ML_DIR / "expert_datasets"
EXPERT_MODEL_DIR = ML_DIR / "expert_models"
BACKTESTS_DIR = ROOT / "backtests"
VIS_DIR = ROOT / "visualization"
GRAFANA_DIR = VIS_DIR / "grafana"
CONFIG_PATH = ROOT / "config.json"
MODEL_WEIGHTS_PATH = ML_DIR / "model_weights.json"
MODEL_CHECKPOINT_PATH = ML_DIR / "model.pt"
TRAINING_METRICS_PATH = ML_DIR / "training_metrics.json"
EXPERT_TRAINING_METRICS_PATH = ML_DIR / "expert_training_metrics.json"
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
    parser.add_argument(
        "--experts-only",
        action="store_true",
        help="Build datasets and train V2 expert models, but skip the baseline model."
    )
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="Train a candidate model into ml/versions/<version-id>/ without touching the active model (V2-17)."
    )
    parser.add_argument(
        "--version-id",
        type=str,
        default=None,
        help="Candidate model_version_id (UUID). Required with --candidate."
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help=(
            "Phase 4 of the 5/10 -> 9/10 roadmap: run the baseline model's dataset-build + "
            "training pipeline once per walk-forward window (see generate_walk_forward_windows()) "
            "instead of once on the fixed phase1.windows. Never touches active ml/ - each window "
            "writes to ml/versions/<run-id>/window_<i>/, same as --candidate."
        ),
    )
    parser.add_argument(
        "--step-days",
        type=int,
        default=None,
        help="Walk-forward step size in days. Defaults to phase_v2.retraining.walk_forward.step_days.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=("rolling", "expanding"),
        default=None,
        help="Walk-forward mode. Defaults to phase_v2.retraining.walk_forward.mode.",
    )
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def ensure_directories() -> None:
    for path in (
        ML_DIR,
        DATASET_DIR,
        EXPERT_DATASET_DIR,
        EXPERT_MODEL_DIR,
        ML_DIR / "versions",
        VIS_DIR,
        GRAFANA_DIR,
        BACKTESTS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def candidate_output_paths(version_id: str) -> dict[str, Path]:
    """Every artifact path a `--candidate --version-id <id>` run writes to,
    all under ml/versions/<id>/ - never the active ml/ paths (Phase V2-17)."""
    version_dir = ML_DIR / "versions" / version_id
    return {
        "version_dir": version_dir,
        "model_checkpoint": version_dir / "model.pt",
        "model_weights": version_dir / "model_weights.json",
        "training_metrics": version_dir / "training_metrics.json",
        "strategy_report": version_dir / "strategy_report.json",
        "equity_curves": version_dir / "equity_curves.csv",
        "scaler": version_dir / "scaler.pkl",
        "scaler_stats": version_dir / "scaler_stats.json",
        "feature_schema": version_dir / "feature_schema.json",
        "dataset_manifest": version_dir / "dataset_manifest.json",
    }


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

        # Merge with whatever is already on disk (e.g. yfinance-backfilled
        # history from data_pipeline/yfinance_backfill.py) instead of
        # clobbering it — freshly computed minute-derived rows win on any
        # overlapping date since they're real trade data, but backfilled
        # rows for dates with no minute data must survive this rebuild.
        existing_lines: dict[str, str] = {}
        if output_zip.exists():
            with ZipFile(output_zip) as archive:
                member = archive.namelist()[0]
                with archive.open(member) as handle:
                    for line in handle.read().decode("utf-8").splitlines():
                        if line.strip():
                            existing_lines[line.split(",")[0].split()[0]] = line

        for line in daily_rows:
            existing_lines[line.split(",")[0].split()[0]] = line

        merged_lines = [existing_lines[key] for key in sorted(existing_lines)]

        output_zip.parent.mkdir(parents=True, exist_ok=True)
        member_name = f"{asset['ticker'].lower()}.csv"
        with ZipFile(output_zip, "w") as archive:
            archive.writestr(member_name, "\n".join(merged_lines) + "\n")


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


def load_factor_file(ticker: str) -> pd.DataFrame | None:
    """Reads a Lean-format equity factor file (date, price_factor,
    split_factor, reference_price - no header), the exact file Lean's own
    engine consults to apply DataNormalizationMode.Adjusted (the default
    main.py's runtime self.add_equity(ticker, self.resolution) subscription
    already gets - see apply_split_adjustments()'s docstring). Returns None
    when the file doesn't exist (e.g. AAA's thin history) - callers must
    degrade to an identity/no-adjustment fallback, never raise."""
    path = FACTOR_FILES_DIR / f"{ticker.lower()}.csv"
    if not path.exists():
        return None

    factors = pd.read_csv(path, header=None, names=["factor_date", "price_factor", "split_factor", "reference_price"])
    factors["factor_date"] = pd.to_datetime(factors["factor_date"], format="%Y%m%d", errors="coerce")
    factors = factors.dropna(subset=["factor_date"]).sort_values("factor_date").reset_index(drop=True)
    return factors if not factors.empty else None


def apply_split_adjustments(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Backward-adjusts a raw per-asset OHLCV frame for splits/dividends
    using Lean's own factor files - the same adjustment
    DataNormalizationMode.Adjusted already applies to main.py's live/
    backtest data feed at runtime (Lean's default for AddEquity()), which
    load_lean_bars() never applied until now since it reads the raw daily
    zip directly, bypassing Lean's data engine entirely.

    Without this, a raw stock split (e.g. AAPL's 2020-08-31 4-for-1 split,
    or USO's 2020-04-28 1-for-8 reverse split) shows up as an impossible
    single-day return in every offline trainer's dataset even though
    main.py's real backtest never sees it - a genuine train/runtime
    feature-parity gap, not merely a label-outlier nuisance (see
    development/Problems.md's full incident writeup). No main.py mirror is
    needed for this fix, unlike the volume_change_1d clamp above - Lean's
    engine already does this adjustment for main.py, only train.py's
    from-scratch zip reader was missing it.

    For each row dated D, finds the factor-file row with the smallest
    factor_date >= D (pd.merge_asof(direction="forward"), Lean's own
    lookup convention) and multiplies open/high/low/close by that row's
    price_factor * split_factor, dividing volume by split_factor alone (a
    cash dividend doesn't change share count, only a split does). Rows
    dated after every factor-file entry (none in this dataset's window,
    but a safe fallback matching Lean's own far-future sentinel row) get
    factor 1.0 - i.e. no adjustment.
    """
    factors = load_factor_file(ticker)
    if factors is None:
        return frame

    result = frame.sort_values("date").reset_index(drop=True)
    merged = pd.merge_asof(
        result[["date"]],
        factors.rename(columns={"factor_date": "date"}),
        on="date",
        direction="forward",
    )
    price_factor = merged["price_factor"].fillna(1.0).to_numpy()
    split_factor = merged["split_factor"].fillna(1.0).to_numpy()
    combined_factor = price_factor * split_factor

    result = result.copy()
    for column in ("open", "high", "low", "close"):
        result[column] = result[column].to_numpy() * combined_factor
    result["volume"] = result["volume"].to_numpy() / split_factor
    return result


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

    if asset["security_type"] == "equity":
        frame = apply_split_adjustments(frame, asset["ticker"])

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


# volume_change_1d clamp bounds - see the comment at its append() call
# below for why. Duplicated (not imported) in main.py::_build_model_input()
# since main.py never imports train.py (heavy training-only deps).
VOLUME_CHANGE_FLOOR = -1.0
VOLUME_CHANGE_CEILING = 20.0

# Matches main.py's self.symbol_long_windows (deque(maxlen=260)) - the
# long-lookback indicators (macd_histogram_normalized/distance_from_52w_high)
# recompute fresh from whatever window they're given (see
# features/technical_indicators.py's docstring), so offline must slice to
# this SAME bounded window for train/runtime parity, not pass unbounded
# full history (which would make the offline EMA/high-water-mark reflect a
# different, longer lookback than the live buffer ever sees).
LONG_LOOKBACK_WINDOW_BARS = 260


# Fallback per-security-type bounds for the label-outlier guards below,
# used when config.json's phase1.target.max_abs_* keys are absent (older
# configs / test fixtures) - real config values should be preferred, these
# are only safety-net defaults. Horizon bounds widen with the window since
# more trading days give more room for genuine cumulative moves.
DEFAULT_MAX_ABS_DAILY_RETURN = {"equity": 0.5, "crypto": 1.5}
DEFAULT_MAX_ABS_RETURN_5D = {"equity": 0.9, "crypto": 2.5}
DEFAULT_MAX_ABS_RETURN_20D = {"equity": 1.5, "crypto": 4.0}


def engineer_features(
    frame: pd.DataFrame,
    feature_names: list[str],
    windows: dict,
    *,
    security_type: str = "equity",
    max_abs_daily_return: dict | None = None,
    max_abs_return_5d: dict | None = None,
    max_abs_return_20d: dict | None = None,
) -> pd.DataFrame:
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
    # Phase 6 technical indicators - shared pure implementations
    # (features/technical_indicators.py) imported at module level above, so
    # this loop and main.py::_build_model_input() compute every one
    # identically by construction. rsi_14/atr_pct_14/bollinger_pctb_20/
    # volume_zscore_20 only ever look at their own trailing period (<=20
    # bars), so passing this loop's full growing `closes[:index+1]` slice
    # produces the same result as main.py's bounded 25-bar
    # self.symbol_windows buffer once enough history exists - no explicit
    # truncation needed. macd_histogram_normalized/distance_from_52w_high
    # DO care about how much history they're given (fresh EMA/rolling-max
    # each call), so those two are explicitly capped to
    # LONG_LOOKBACK_WINDOW_BARS to match main.py's self.symbol_long_windows
    # buffer size.
    rsi_14: list[float] = [np.nan]
    atr_pct_14: list[float] = [np.nan]
    bollinger_pctb_20: list[float] = [np.nan]
    volume_zscore_20: list[float] = [np.nan]
    macd_histogram_norm: list[float] = [np.nan]
    dist_52w_high: list[float] = [np.nan]

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
        raw_volume_change = 0.0 if previous_volume == 0 else volumes[index] / previous_volume - 1.0
        # Clamped to [-1.0, 20.0] (volume can't fall more than 100%, and a
        # >2000% single-day jump is a data-feed unit discontinuity, not a
        # real signal - see BTCUSD 2018-08-14's raw volume jumping ~520,000x
        # in one day, traced in development/Problems.md). Mirrored exactly
        # in main.py::_build_model_input() for train/runtime parity.
        volume_change_1d.append(max(VOLUME_CHANGE_FLOOR, min(VOLUME_CHANGE_CEILING, raw_volume_change)))

        trailing_closes = closes[: index + 1]
        rsi_14.append(relative_strength_index(trailing_closes, period=14))
        atr_pct_14.append(average_true_range_pct(highs[: index + 1], lows[: index + 1], trailing_closes, period=14))
        bollinger_pctb_20.append(bollinger_pctb(trailing_closes, period=20))
        volume_zscore_20.append(volume_zscore(volumes[: index + 1], period=20))

        long_window_start = max(0, index + 1 - LONG_LOOKBACK_WINDOW_BARS)
        long_trailing_closes = closes[long_window_start : index + 1]
        macd_histogram_norm.append(macd_histogram_normalized(long_trailing_closes))
        dist_52w_high.append(distance_from_52w_high(long_trailing_closes, window=LONG_LOOKBACK_WINDOW_BARS))

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
    result["rsi_14"] = rsi_14
    result["atr_pct_14"] = atr_pct_14
    result["bollinger_pctb_20"] = bollinger_pctb_20
    result["volume_zscore_20"] = volume_zscore_20
    result["macd_histogram_norm"] = macd_histogram_norm
    result["dist_52w_high"] = dist_52w_high

    result["target_return_1d"] = result["close"].shift(-1) / result["close"] - 1.0

    # Label-outlier guard: an unadjusted stock split (AAPL's 2020-08-28
    # 4-for-1 split shows as a fake -74% "return") or unadjusted reverse
    # split (USO's 2020-04-28 1-for-8 shows as +745%) produces an
    # impossible single-day return that corrupts target_direction/
    # target_return_1d for every trainer reading this column. Bounds are
    # per security-type since real crypto moves (e.g. XRP's 2021-01-29
    # +56%) can legitimately exceed any equity-sane threshold. NaN'd out
    # here so the existing dropna(required_columns) below removes the row
    # exactly like any other missing-label row - not winsorized, since a
    # clipped fake -74% is still a fake "down" label, not a smaller real
    # one. See development/Problems.md for the full incident writeup.
    return_bounds = max_abs_daily_return or DEFAULT_MAX_ABS_DAILY_RETURN
    return_bound = float(return_bounds.get(security_type, return_bounds.get("equity", 0.5)))
    impossible_return = result["target_return_1d"].abs() > return_bound
    result.loc[impossible_return, "target_return_1d"] = np.nan

    result["target_direction"] = np.where(
        result["target_return_1d"].notna(),
        (result["target_return_1d"] > 0).astype(int),
        np.nan,
    )

    # Multi-horizon targets (5d/20d) - the highest-leverage change this
    # codebase's root-cause investigation identified: next-day binary
    # direction on liquid daily bars is close to efficient-market noise;
    # longer horizons give momentum/mean-reversion more room to show up.
    # Deliberately NOT added to required_columns below - the trailing
    # ~5/~20 rows of each asset's history that lack a future close far
    # enough out stay in the dataset with NaN targets here, handled by
    # train_multitask.py's/train_sequence.py's masked loss instead of
    # being dropped outright (dropping would also shrink every per-expert
    # dataset slice downstream, which only ever needs the 1d target).
    result["target_return_5d"] = result["close"].shift(-5) / result["close"] - 1.0
    result["target_return_20d"] = result["close"].shift(-20) / result["close"] - 1.0

    return_bounds_5d = max_abs_return_5d or DEFAULT_MAX_ABS_RETURN_5D
    return_bound_5d = float(return_bounds_5d.get(security_type, return_bounds_5d.get("equity", 0.9)))
    impossible_5d = result["target_return_5d"].abs() > return_bound_5d
    result.loc[impossible_5d, "target_return_5d"] = np.nan

    return_bounds_20d = max_abs_return_20d or DEFAULT_MAX_ABS_RETURN_20D
    return_bound_20d = float(return_bounds_20d.get(security_type, return_bounds_20d.get("equity", 1.5)))
    impossible_20d = result["target_return_20d"].abs() > return_bound_20d
    result.loc[impossible_20d, "target_return_20d"] = np.nan

    # Stays float (NaN-able) - unlike target_direction above, this is never
    # forced to int since it's not in required_columns's dropna.
    result["target_direction_5d"] = np.where(
        result["target_return_5d"].notna(), (result["target_return_5d"] > 0).astype(float), np.nan
    )
    result["target_direction_20d"] = np.where(
        result["target_return_20d"].notna(), (result["target_return_20d"] > 0).astype(float), np.nan
    )

    # Next-day realized-volatility proxy for the multitask model's volatility
    # head (train_multitask.py): next day's own high_low_range_pct, already
    # computed above from that day's high/low/close - a genuine one-day-ahead
    # realized-range measure, NaN only on the same last-per-asset row
    # target_return_1d is already NaN on (both are shift(-1) of price data),
    # so it never introduces additional dropped rows beyond what
    # target_return_1d already drops.
    result["target_volatility_next_day"] = result["high_low_range_pct"].shift(-1)
    result["split"] = result["date"].apply(lambda value: assign_split(value, windows))

    required_columns = feature_names + [
        "target_return_1d",
        "target_direction",
        "target_volatility_next_day",
        "split",
    ]
    result = result.dropna(subset=required_columns).reset_index(drop=True)
    result["target_direction"] = result["target_direction"].astype(int)
    return result


# ---------------------------------------------------------------------------
# Cross-subsystem input features (Phase 1 remainder): regime/liquidity/
# topology become genuine model *inputs*, not just downstream consumers of
# the model's own output. Mirrors main.py's own runtime computation of each
# subsystem exactly (same functions, same config keys) so train/runtime
# feature parity holds - see build_feature_dataset()'s orchestration below
# and main.py's matching _build_model_input() changes.
# ---------------------------------------------------------------------------

# Matches main.py's self.symbol_windows (deque(maxlen=25), so up to 24
# daily returns) - both the topology returns window and the liquidity
# high/low spread-estimation window below reuse this exact size so offline
# reconstruction sees the same trailing history depth the live loop does.
CROSS_SECTIONAL_WINDOW_BARS = 25
CROSS_SECTIONAL_RETURNS_WINDOW = CROSS_SECTIONAL_WINDOW_BARS - 1

REGIME_ONEHOT_FEATURE_NAMES = [
    "regime_trend_bullish", "regime_trend_bearish", "regime_trend_sideways",
    "regime_volatility_low", "regime_volatility_normal", "regime_volatility_high",
    "regime_risk_on", "regime_risk_off", "regime_risk_neutral",
]
REGIME_CONTINUOUS_FEATURE_NAMES = ["regime_signal_confidence", "regime_signal_trend_score", "regime_signal_risk_score"]
REGIME_FEATURE_NAMES = REGIME_ONEHOT_FEATURE_NAMES + REGIME_CONTINUOUS_FEATURE_NAMES

LIQUIDITY_FEATURE_NAMES = ["liquidity_log_dollar_volume", "liquidity_spread_proxy"]

TOPOLOGY_ONEHOT_FEATURE_NAMES = ["topology_risk_normal", "topology_risk_elevated", "topology_risk_isolated"]
TOPOLOGY_CONTINUOUS_FEATURE_NAMES = ["topology_correlation_strength"]
TOPOLOGY_FEATURE_NAMES = TOPOLOGY_ONEHOT_FEATURE_NAMES + TOPOLOGY_CONTINUOUS_FEATURE_NAMES


def _encode_regime_row(row: pd.Series) -> dict:
    """Reconstructs the same MarketRegimeVector main.py's
    _build_regime_payload() computes at runtime, from this row's own
    already-engineered momentum/volatility features. portfolio_drawdown=0.0
    and average_correlation=0.0 are an honest, documented offline
    simplification (no live portfolio/topology state exists at dataset-
    build time) - the exact same simplification train_gating.py's
    build_gating_training_rows() already established for the identical
    reason; trend_regime/volatility_regime (the two most-used regime keys)
    are unaffected by either default."""
    features = {
        "momentum_5d": row["momentum_5d"],
        "momentum_20d": row["momentum_20d"],
        "rolling_volatility_5d": row["rolling_volatility_5d"],
        "rolling_volatility_20d": row["rolling_volatility_20d"],
    }
    vector = build_market_regime_vector(features, portfolio_drawdown=0.0, average_correlation=0.0)
    return {
        "regime_trend_bullish": 1.0 if vector.trend_regime == "bullish" else 0.0,
        "regime_trend_bearish": 1.0 if vector.trend_regime == "bearish" else 0.0,
        "regime_trend_sideways": 1.0 if vector.trend_regime == "sideways" else 0.0,
        "regime_volatility_low": 1.0 if vector.volatility_regime == "low_volatility" else 0.0,
        "regime_volatility_normal": 1.0 if vector.volatility_regime == "normal_volatility" else 0.0,
        "regime_volatility_high": 1.0 if vector.volatility_regime == "high_volatility" else 0.0,
        "regime_risk_on": 1.0 if vector.risk_regime == "risk_on" else 0.0,
        "regime_risk_off": 1.0 if vector.risk_regime == "risk_off" else 0.0,
        "regime_risk_neutral": 1.0 if vector.risk_regime == "risk_neutral" else 0.0,
        "regime_signal_confidence": vector.confidence,
        "regime_signal_trend_score": vector.trend_score,
        "regime_signal_risk_score": vector.risk_score,
    }


def add_regime_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Row-wise: every surviving row already has the momentum/volatility
    features build_market_regime_vector() needs, so this never drops rows."""
    encoded = frame.apply(_encode_regime_row, axis=1, result_type="expand")
    return pd.concat([frame.reset_index(drop=True), encoded.reset_index(drop=True)], axis=1)


def add_liquidity_features(frame: pd.DataFrame, security_type: str) -> pd.DataFrame:
    """Asset-intrinsic liquidity features only: daily_dollar_volume (log1p-
    scaled, since raw values span orders of magnitude) and the Corwin-
    Schultz spread_proxy over a trailing CROSS_SECTIONAL_WINDOW_BARS window,
    both reusing liquidity/market_liquidity.py's exact runtime functions.
    Deliberately excludes participation_rate/estimated_slippage/
    adjusted_target_weight from build_liquidity_decision() - those need an
    assumed order size (target_weight * portfolio_value), which has no
    principled offline value before any sizing decision exists; feeding a
    made-up order size in as a "feature" would be circular. This is a
    documented adaptation of the original plan text, not an oversight.

    Must be called on the RAW per-asset frame, before engineer_features()
    drops that asset's first row (its close_to_close_return_1d etc. are
    NaN, no previous close to compute from) - main.py's real
    self.symbol_windows starts accumulating from that same first raw bar,
    so spread_proxy's trailing window must see it too, or the first
    ~CROSS_SECTIONAL_WINDOW_BARS rows of every asset's history would be
    silently short one bar offline versus what the live loop actually
    sees (confirmed via a real train/runtime parity check on ETHUSD's
    earliest rows - high/low pairs, unlike returns, are legitimately
    available for that first row even though its own return isn't)."""
    closes = frame["close"].tolist()
    volumes = frame["volume"].tolist()
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    fallback_spread = TYPICAL_SPREAD_BY_TYPE.get(str(security_type), 0.001)

    log_dollar_volume: list[float] = []
    spread_proxy: list[float] = []
    for index in range(len(frame)):
        log_dollar_volume.append(float(np.log1p(max(closes[index] * volumes[index], 0.0))))

        window_start = max(0, index + 1 - CROSS_SECTIONAL_WINDOW_BARS)
        window_highs = highs[window_start : index + 1]
        window_lows = lows[window_start : index + 1]
        estimated = estimate_high_low_spread(window_highs, window_lows) if len(window_highs) >= 2 else None
        spread_proxy.append(float(estimated) if estimated is not None else fallback_spread)

    result = frame.copy()
    result["liquidity_log_dollar_volume"] = log_dollar_volume
    result["liquidity_spread_proxy"] = spread_proxy
    return result


def peer_return_feature_names(top_peers_n: int) -> list[str]:
    """Schema-stable peer-return feature names - never ticker-named (peer
    identity changes bar to bar and asset to asset), always rank-based:
    peer_rank1_return_1d is "this asset's single most-correlated peer's
    latest 1-day return", down to peer_rankN_return_1d, plus
    peer_mean_return_1d (mean across whichever peers exist). Shared by
    build_topology_features_by_date() (offline) and
    main.py::_build_model_input() (runtime) so both sides register the
    exact same column/feature names."""
    return [f"peer_rank{rank}_return_1d" for rank in range(1, top_peers_n + 1)] + ["peer_mean_return_1d"]


def build_topology_features_by_date(asset_frames: dict[str, pd.DataFrame], config: dict) -> dict[str, pd.DataFrame]:
    """Cross-sectional per-date topology + peer-return reconstruction -
    genuinely new code, no existing pattern in train.py computed a
    cross-asset relationship at dataset-build time before this (only
    main.py's runtime _build_topology_payload() did, once per bar before
    the symbol loop).

    For each unique historical date across the whole universe, gathers each
    asset's trailing CROSS_SECTIONAL_RETURNS_WINDOW-return window ending at
    that date and calls the exact same build_market_topology() the runtime
    path uses. `embedding_iterations=1` is deliberate: correlation_strength/
    topology_risk/top_peers/top_peer_returns (the only fields consumed
    here) are computed in build_market_topology()'s Pass 1/Pass 3 and do
    not depend on the SMACOF x/y embedding at all, so the expensive
    iterative embedding step is skipped for speed without changing any of
    those output values. Peer-return features are folded into this SAME
    per-date loop (not a separate function re-running build_market_topology()
    a second time) since they come from the exact same per-date topology
    call - a real, already-documented cost (see development/Changelog.md's
    "topology per-date cross-sectional loop" dataset-rebuild timing note),
    not worth doubling.

    `asset_frames` values must each have 'date' (pandas Timestamp, not yet
    stringified) and 'close_to_close_return_1d' columns - i.e. called after
    engineer_features() but before build_feature_dataset()'s final
    concat/strftime. regime_labels_by_symbol is intentionally omitted
    (passed as {}): it only affects TopologyCluster.dominant_regime_label
    and TopologyNode.regime_label, neither of which this function reads.

    Peer-return features (peer_rank1_return_1d, ..., peer_mean_return_1d -
    see peer_return_feature_names()) are schema-stable, never ticker-named
    (a peer's identity changes bar to bar and asset to asset). A missing
    peer (universe smaller than top_peers_n) gets 0.0, identically on both
    the offline (here) and runtime (main.py::_build_model_input()) sides -
    no lookahead, since each peer's latest 1d return is already known as
    of the current row's own date.
    """
    topology_config = config.get("phase_v2", {}).get("topology", {})
    correlation_threshold = float(topology_config.get("correlation_threshold", 0.6))
    link_threshold = float(topology_config.get("link_threshold", 0.5))
    min_observations = int(topology_config.get("min_observations", 5))
    top_peers_n = int(topology_config.get("top_peers_n", 3))
    peer_feature_names = peer_return_feature_names(top_peers_n)

    dates_by_ticker = {ticker: frame["date"].tolist() for ticker, frame in asset_frames.items()}
    returns_by_ticker = {ticker: frame["close_to_close_return_1d"].tolist() for ticker, frame in asset_frames.items()}
    all_dates = sorted({date for dates in dates_by_ticker.values() for date in dates})

    correlation_strength_by_ticker_date: dict[str, dict] = {ticker: {} for ticker in asset_frames}
    topology_risk_by_ticker_date: dict[str, dict] = {ticker: {} for ticker in asset_frames}
    peer_features_by_ticker_date: dict[str, dict] = {ticker: {} for ticker in asset_frames}

    for current_date in all_dates:
        returns_by_symbol: dict[str, list[float]] = {}
        for ticker in asset_frames:
            dates = dates_by_ticker[ticker]
            position = bisect.bisect_right(dates, current_date)
            if position == 0:
                continue
            window = returns_by_ticker[ticker][max(0, position - CROSS_SECTIONAL_RETURNS_WINDOW) : position]
            if len(window) >= 2:
                returns_by_symbol[ticker] = window

        if len(returns_by_symbol) < 2:
            continue

        topology = build_market_topology(
            returns_by_symbol=returns_by_symbol,
            correlation_threshold=correlation_threshold,
            link_threshold=link_threshold,
            min_observations=min_observations,
            embedding_iterations=1,
            top_peers_n=top_peers_n,
        )
        for node in topology.nodes:
            correlation_strength_by_ticker_date[node.symbol][current_date] = node.correlation_strength
            topology_risk_by_ticker_date[node.symbol][current_date] = node.topology_risk
            padded_returns = list(node.top_peer_returns) + [0.0] * (top_peers_n - len(node.top_peer_returns))
            mean_peer_return = float(np.mean(node.top_peer_returns)) if node.top_peer_returns else 0.0
            peer_features_by_ticker_date[node.symbol][current_date] = padded_returns + [mean_peer_return]

    updated_frames: dict[str, pd.DataFrame] = {}
    for ticker, frame in asset_frames.items():
        result = frame.copy()
        correlation_lookup = correlation_strength_by_ticker_date[ticker]
        risk_lookup = topology_risk_by_ticker_date[ticker]
        peer_lookup = peer_features_by_ticker_date[ticker]
        # Rows where topology couldn't be computed (fewer than min_observations
        # trailing returns exist yet, or no other asset qualified that date)
        # default to the same "isolated, zero correlation" signal
        # build_market_topology()'s own _isolated_node() fallback produces -
        # a real, meaningful value, never a NaN needing an extra dropna pass.
        # Peer features default to all-zero for the same rows, matching the
        # missing-peer convention above.
        result["topology_correlation_strength"] = [correlation_lookup.get(date, 0.0) for date in result["date"]]
        risk_values = [risk_lookup.get(date, "isolated") for date in result["date"]]
        result["topology_risk_normal"] = [1.0 if value == "normal" else 0.0 for value in risk_values]
        result["topology_risk_elevated"] = [1.0 if value == "elevated" else 0.0 for value in risk_values]
        result["topology_risk_isolated"] = [1.0 if value == "isolated" else 0.0 for value in risk_values]

        zero_peer_features = [0.0] * (top_peers_n + 1)
        peer_values = [peer_lookup.get(date, zero_peer_features) for date in result["date"]]
        for index, feature_name in enumerate(peer_feature_names):
            result[feature_name] = [row[index] for row in peer_values]

        updated_frames[ticker] = result
    return updated_frames


DEFAULT_MACRO_REFERENCE_TICKERS = {
    "long_duration": "TLT",
    "short_duration": "SHY",
    "high_yield": "HYG",
    "investment_grade": "LQD",
    "crypto": "BTCUSD",
}
MACRO_FEATURE_NAMES = [
    "macro_yield_curve_slope_proxy",
    "macro_credit_spread_proxy",
    "macro_crypto_risk_appetite_proxy",
]


def build_macro_features_by_date(asset_frames: dict[str, pd.DataFrame], config: dict) -> dict[str, pd.DataFrame]:
    """Phase 1b of the 5/10 -> 9/10 roadmap: deliberate, explicit
    cross-asset-class "macro" features (features/macro_features.py),
    computed once per date from a small fixed set of reference tickers
    (the Phase 1a bond ETF sleeve + the existing crypto sleeve) and
    broadcast identically to every asset's row for that date - additive to,
    not a replacement for, the existing generic correlation-based peer
    mechanism (build_topology_features_by_date() above).

    Reuses each reference ticker's own already-computed momentum_20d
    column (engineer_features()) rather than re-deriving returns from
    scratch - no new buffer/window logic needed, unlike
    features/technical_indicators.py's long-lookback indicators.
    `asset_frames` values must each have 'date' and 'momentum_20d' columns,
    i.e. called after engineer_features() but before build_feature_dataset()'s
    final concat/strftime - same calling convention as
    build_topology_features_by_date().

    A reference ticker absent from this particular `asset_frames` (e.g. a
    universe subset without the bond sleeve, or a reference ticker not yet
    trading as of a given date) neutral-defaults its proxy to 0.0 for every
    date - never raises, matching features/macro_features.py's own
    "missing reference -> 0.0" convention.
    """
    reference_tickers = {
        **DEFAULT_MACRO_REFERENCE_TICKERS,
        **config.get("phase1", {}).get("features", {}).get("macro_reference_tickers", {}),
    }

    def _dates_and_momentum(ticker: str) -> tuple[list, list]:
        frame = asset_frames.get(ticker)
        if frame is None:
            return [], []
        return frame["date"].tolist(), frame["momentum_20d"].tolist()

    long_dates, long_momentum = _dates_and_momentum(reference_tickers["long_duration"])
    short_dates, short_momentum = _dates_and_momentum(reference_tickers["short_duration"])
    high_yield_dates, high_yield_momentum = _dates_and_momentum(reference_tickers["high_yield"])
    investment_grade_dates, investment_grade_momentum = _dates_and_momentum(reference_tickers["investment_grade"])
    crypto_dates, crypto_momentum = _dates_and_momentum(reference_tickers["crypto"])

    def _momentum_asof(dates: list, values: list, current_date) -> float | None:
        if not dates:
            return None
        position = bisect.bisect_right(dates, current_date)
        if position == 0:
            return None
        value = values[position - 1]
        return None if pd.isna(value) else float(value)

    all_dates = sorted({date for frame in asset_frames.values() for date in frame["date"]})

    slope_by_date: dict = {}
    spread_by_date: dict = {}
    crypto_appetite_by_date: dict = {}
    for current_date in all_dates:
        long_value = _momentum_asof(long_dates, long_momentum, current_date)
        short_value = _momentum_asof(short_dates, short_momentum, current_date)
        high_yield_value = _momentum_asof(high_yield_dates, high_yield_momentum, current_date)
        investment_grade_value = _momentum_asof(investment_grade_dates, investment_grade_momentum, current_date)
        crypto_value = _momentum_asof(crypto_dates, crypto_momentum, current_date)
        slope_by_date[current_date] = yield_curve_slope_proxy(long_value, short_value)
        spread_by_date[current_date] = credit_spread_proxy(high_yield_value, investment_grade_value)
        crypto_appetite_by_date[current_date] = crypto_risk_appetite_proxy(crypto_value)

    updated_frames: dict[str, pd.DataFrame] = {}
    for ticker, frame in asset_frames.items():
        result = frame.copy()
        result["macro_yield_curve_slope_proxy"] = [
            slope_by_date.get(date, YIELD_CURVE_SLOPE_NEUTRAL) for date in result["date"]
        ]
        result["macro_credit_spread_proxy"] = [
            spread_by_date.get(date, CREDIT_SPREAD_NEUTRAL) for date in result["date"]
        ]
        result["macro_crypto_risk_appetite_proxy"] = [
            crypto_appetite_by_date.get(date, CRYPTO_RISK_APPETITE_NEUTRAL) for date in result["date"]
        ]
        updated_frames[ticker] = result
    return updated_frames


def build_bond_features_by_date(
    asset_frames: dict[str, pd.DataFrame],
    config: dict,
    fred_series: dict[str, list[dict]],
) -> dict[str, pd.DataFrame]:
    """Real-data sibling of build_macro_features_by_date() -
    features/bond_features.py, backed by data_pipeline/fred_backfill.py's
    actual FRED Treasury-yield/credit-spread series rather than
    macro_features.py's bond-ETF-price-momentum proxies.

    bond_yield_curve_level/slope/curvature and bond_credit_spread_level are
    date-only (identical across every asset on a given date) and broadcast
    to EVERY asset's row - same "compute once per date, every asset sees
    it" shape as build_macro_features_by_date() - this is the concrete
    mechanism making real yield-curve/credit-spread signal usable for
    equity/crypto/future/option predictions too, not just bonds themselves.

    bond_empirical_duration_beta is asset-specific: computed once per
    ticker (NOT a true rolling/date-varying value - a single OLS slope over
    that asset's whole available history, using
    features.empirical_duration_beta()) for assets tagged asset_class ==
    "bond" only, and broadcast unchanged to every row of that asset's own
    frame; every other asset gets a flat 0.0 (neutral - "no measurable
    duration sensitivity", not "unknown"). A bond-tagged asset with fewer
    than empirical_duration_beta()'s min_observations valid paired rows
    also gets 0.0, same neutral-pad convention as the missing-reference
    case above.

    fred_series is a plain {series_key: [{"date": date, "value": float},
    ...]} mapping - load_cached_fred_series()'s return shape, loaded once
    by the caller (never fetched live mid-run; Lean backtests are
    date-bounded). A series absent from fred_series (fresh clone, backfill
    never run) makes every bond feature for every date fall back to its
    neutral default - never raises.
    """
    assets_by_ticker = {asset["ticker"]: asset for asset in config["phase1"]["universe"]["assets"]}

    def _series_asof_lookup(series_key: str):
        rows = sorted(fred_series.get(series_key, []), key=lambda row: row["date"])
        dates = [row["date"] for row in rows]
        values = [row["value"] for row in rows]

        def _asof(current_date) -> float | None:
            target = current_date.date() if hasattr(current_date, "date") else current_date
            position = bisect.bisect_right(dates, target)
            if position == 0:
                return None
            return values[position - 1]

        return _asof

    treasury_3mo_asof = _series_asof_lookup("treasury_3mo")
    treasury_2yr_asof = _series_asof_lookup("treasury_2yr")
    treasury_5yr_asof = _series_asof_lookup("treasury_5yr")
    treasury_10yr_asof = _series_asof_lookup("treasury_10yr")
    credit_spread_asof = _series_asof_lookup("credit_spread_baa10y")

    all_dates = sorted({date_value for frame in asset_frames.values() for date_value in frame["date"]})

    level_by_date: dict = {}
    slope_by_date: dict = {}
    curvature_by_date: dict = {}
    credit_by_date: dict = {}
    treasury_10yr_by_date: dict = {}
    for current_date in all_dates:
        t3mo = treasury_3mo_asof(current_date)
        t2yr = treasury_2yr_asof(current_date)
        t5yr = treasury_5yr_asof(current_date)
        t10yr = treasury_10yr_asof(current_date)
        baa10y = credit_spread_asof(current_date)
        level_by_date[current_date] = yield_curve_level(t10yr)
        slope_by_date[current_date] = bond_yield_curve_slope(t10yr, t3mo)
        curvature_by_date[current_date] = yield_curve_curvature(t2yr, t5yr, t10yr)
        credit_by_date[current_date] = credit_spread_level(baa10y)
        treasury_10yr_by_date[current_date] = t10yr

    updated_frames: dict[str, pd.DataFrame] = {}
    for ticker, frame in asset_frames.items():
        result = frame.copy()
        result["bond_yield_curve_level"] = [level_by_date.get(d, YIELD_CURVE_LEVEL_NEUTRAL) for d in result["date"]]
        result["bond_yield_curve_slope"] = [slope_by_date.get(d, 0.0) for d in result["date"]]
        result["bond_yield_curve_curvature"] = [
            curvature_by_date.get(d, YIELD_CURVE_CURVATURE_NEUTRAL) for d in result["date"]
        ]
        result["bond_credit_spread_level"] = [
            credit_by_date.get(d, CREDIT_SPREAD_LEVEL_NEUTRAL) for d in result["date"]
        ]

        asset_config = assets_by_ticker.get(ticker, {})
        is_bond = (asset_config.get("asset_class") or asset_config.get("security_type")) == "bond"
        beta = None
        if is_bond and "close_to_close_return_1d" in result.columns:
            dates_sorted = result["date"].tolist()
            treasury_10yr_sorted = [treasury_10yr_by_date.get(d) for d in dates_sorted]
            delta_10yr = [None] * len(treasury_10yr_sorted)
            for index in range(1, len(treasury_10yr_sorted)):
                previous_value = treasury_10yr_sorted[index - 1]
                current_value = treasury_10yr_sorted[index]
                if previous_value is not None and current_value is not None:
                    delta_10yr[index] = current_value - previous_value
            beta = empirical_duration_beta(result["close_to_close_return_1d"].tolist(), delta_10yr)
        result["bond_empirical_duration_beta"] = beta if beta is not None else 0.0

        updated_frames[ticker] = result
    return updated_frames


def build_derivatives_macro_features_by_date(asset_frames: dict[str, pd.DataFrame], config: dict) -> dict[str, pd.DataFrame]:
    """Third cross-asset macro sibling to build_macro_features_by_date()/
    build_bond_features_by_date() - features/derivatives_macro_features.py's
    futures-term-structure/options-sentiment signals, broadcast identically
    to EVERY asset's row (the mechanism making derivatives-derived signal
    usable for equity/crypto/bond predictions too, not just futures/options
    themselves - generalizing well past any single hardcoded example pair).

    Reuses the SAME `aq fetch futures`/`aq fetch options` historical Lean
    zips already loaded into `asset_frames` - no separate bulk-fetch
    pipeline. Real values require the user to have explicitly fetched
    contracts shaped for this:

    - Futures term structure: two future-class assets sharing a
      `family_ticker` matching `phase1.features.derivatives_reference_tickers
      .futures_term_structure` (default "ES") - e.g. `aq fetch futures
      --ticker ES_FRONT --family-ticker ES --contract-month <early> --apply`
      and `... --ticker ES_NEXT --family-ticker ES --contract-month <later>
      --apply`. Ordered by `contract_month` when present (nearest = front),
      else by ticker name. Fewer than 2 family members -> neutral (0.0).
    - Options sentiment: option-class assets whose `underlying_ticker`
      matches `derivatives_reference_tickers.options_sentiment` (default
      "SPY"), each carrying `strike`/`expiry`/`right` metadata (written by
      `aq fetch options --strike ... --expiry ... --right ...`). Per date,
      each contract's IV is solved from that date's close price via
      features/options_greeks.py::implied_volatility() (using the
      underlying's own close that date as spot, `phase_v2.options_risk
      .risk_free_rate`), then delta via compute_greeks() - aggregate
      volume for the put/call ratio, nearest-25-delta IV pair for the
      skew. No option assets configured for the reference underlying ->
      neutral (0.0).

    Every lookup neutral-defaults to 0.0 - never raises - the same
    "no data configured -> 0.0, indistinguishable from a genuinely neutral
    signal" convention as every other cross-asset macro feature here.
    Real historical acquisition via IB is inherently a manual, per-contract,
    rate-limited process (see data_pipeline/README.md) - this function
    just consumes whatever the user has already fetched."""
    assets_by_ticker = {
        asset["ticker"]: asset
        for asset in config.get("phase1", {}).get("universe", {}).get("assets", [])
    }
    reference_tickers = {
        "futures_term_structure": "ES",
        "options_sentiment": "SPY",
        **config.get("phase1", {}).get("features", {}).get("derivatives_reference_tickers", {}),
    }
    risk_free_rate = float(config.get("phase_v2", {}).get("options_risk", {}).get("risk_free_rate", 0.045))

    def _asset_class(ticker: str) -> str | None:
        asset = assets_by_ticker.get(ticker, {})
        return asset.get("asset_class") or asset.get("security_type")

    # --- Futures term structure: two family members, sorted front-to-next ---
    term_structure_by_date: dict = {}
    futures_family_ref = reference_tickers.get("futures_term_structure")
    futures_members = sorted(
        (
            ticker for ticker in asset_frames
            if _asset_class(ticker) == "future"
            and assets_by_ticker.get(ticker, {}).get("family_ticker", ticker) == futures_family_ref
        ),
        key=lambda ticker: assets_by_ticker[ticker].get("contract_month") or ticker,
    )
    if len(futures_members) >= 2:
        front_by_date = dict(zip(asset_frames[futures_members[0]]["date"], asset_frames[futures_members[0]]["close"]))
        next_by_date = dict(zip(asset_frames[futures_members[1]]["date"], asset_frames[futures_members[1]]["close"]))
        for current_date in set(front_by_date) | set(next_by_date):
            term_structure_by_date[current_date] = futures_term_structure_slope(
                front_by_date.get(current_date), next_by_date.get(current_date)
            )

    # --- Options sentiment: every option-class asset for the reference underlying ---
    put_call_ratio_by_date: dict = {}
    iv_skew_by_date: dict = {}
    options_ref = reference_tickers.get("options_sentiment")
    option_members = [
        ticker for ticker in asset_frames
        if _asset_class(ticker) == "option" and assets_by_ticker.get(ticker, {}).get("underlying_ticker") == options_ref
    ]
    if option_members and options_ref in asset_frames:
        underlying_close_by_date = dict(zip(asset_frames[options_ref]["date"], asset_frames[options_ref]["close"]))
        member_rows = {}
        for ticker in option_members:
            asset = assets_by_ticker[ticker]
            right = str(asset.get("right", "")).lower()
            strike = float(asset.get("strike", 0.0) or 0.0)
            expiry = asset.get("expiry")
            if right not in ("call", "put") or strike <= 0 or not expiry:
                continue
            expiry_date = pd.Timestamp(expiry).date()
            frame = asset_frames[ticker]
            volume_by_date = dict(zip(frame["date"], frame["volume"])) if "volume" in frame.columns else {}
            close_by_date = dict(zip(frame["date"], frame["close"]))
            member_rows[ticker] = {"right": right, "strike": strike, "expiry_date": expiry_date, "volume_by_date": volume_by_date, "close_by_date": close_by_date}

        all_dates = set(underlying_close_by_date)
        for meta in member_rows.values():
            all_dates |= set(meta["close_by_date"])

        for current_date in all_dates:
            spot = underlying_close_by_date.get(current_date)
            current_date_only = current_date.date() if hasattr(current_date, "date") else current_date
            put_volume = 0.0
            call_volume = 0.0
            put_candidates: list[tuple[float, float]] = []
            call_candidates: list[tuple[float, float]] = []
            for meta in member_rows.values():
                option_price = meta["close_by_date"].get(current_date)
                if spot is None or option_price is None or spot <= 0 or option_price <= 0:
                    continue
                time_to_expiry_years = (meta["expiry_date"] - current_date_only).days / 365.0
                if time_to_expiry_years <= 0:
                    continue
                volume = float(meta["volume_by_date"].get(current_date, 0.0) or 0.0)
                if meta["right"] == "put":
                    put_volume += volume
                else:
                    call_volume += volume
                iv = implied_volatility(option_price, spot, meta["strike"], time_to_expiry_years, risk_free_rate, 0.0, meta["right"])
                if iv is None:
                    continue
                delta = compute_greeks(spot, meta["strike"], time_to_expiry_years, risk_free_rate, iv, 0.0, meta["right"])["delta"]
                (put_candidates if meta["right"] == "put" else call_candidates).append((delta, iv))

            put_call_ratio_by_date[current_date] = options_put_call_ratio(
                put_volume if (put_volume or call_volume) else None, call_volume if (put_volume or call_volume) else None
            )
            nearest_put_iv = min(put_candidates, key=lambda pair: abs(pair[0] - (-0.25)))[1] if put_candidates else None
            nearest_call_iv = min(call_candidates, key=lambda pair: abs(pair[0] - 0.25))[1] if call_candidates else None
            iv_skew_by_date[current_date] = options_implied_vol_skew(nearest_put_iv, nearest_call_iv)

    updated_frames: dict[str, pd.DataFrame] = {}
    for ticker, frame in asset_frames.items():
        result = frame.copy()
        result["futures_term_structure_slope"] = [term_structure_by_date.get(d, 0.0) for d in result["date"]]
        result["options_put_call_ratio"] = [put_call_ratio_by_date.get(d, 0.0) for d in result["date"]]
        result["options_implied_vol_skew"] = [iv_skew_by_date.get(d, 0.0) for d in result["date"]]
        updated_frames[ticker] = result
    return updated_frames


DEFAULT_RANKING_MIN_UNIVERSE_SIZE = 10
DEFAULT_SECTOR_NEUTRAL_MIN_SECTOR_SIZE = 3
UNKNOWN_SECTOR_LABEL = "Unknown"


def load_sector_mapping(config: dict) -> dict[str, str]:
    """Phase 5 of the 5/10 -> 9/10 roadmap: ticker -> sector-neutral-ranking
    bucket, from the checked-in data/reference/sector_mapping.json (or an
    override path via config phase1.target.ranking.sector_neutral.mapping_path).
    Same defensive posture as load_factor_file(): returns {} (never raises)
    when the file is missing or unparseable, so a caller degrades to every
    ticker resolving to UNKNOWN_SECTOR_LABEL rather than crashing the whole
    dataset build over a missing reference file.
    """
    mapping_path_str = (
        config.get("phase1", {}).get("target", {}).get("ranking", {}).get("sector_neutral", {}).get("mapping_path")
    )
    mapping_path = Path(mapping_path_str) if mapping_path_str else SECTOR_MAPPING_PATH
    if not mapping_path.exists():
        return {}

    try:
        raw = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    return {ticker: sector for ticker, sector in raw.items() if not ticker.startswith("_")}


def build_cross_sectional_rank_targets(asset_frames: dict[str, pd.DataFrame], config: dict) -> dict[str, pd.DataFrame]:
    """Cross-sectional per-date percentile-rank targets (Phase 4) - the
    highest-leverage change this codebase's root-cause investigation
    identified: which asset outperforms its peers this period is typically
    far more learnable than absolute next-day direction, and maps directly
    onto a long/short portfolio (rank the universe, go long the top,
    short the bottom), unlike a per-asset direction call.

    For each historical date across the whole universe, ranks every
    asset's forward target_return_5d/target_return_20d (already computed
    by engineer_features(), including that function's own per-horizon
    label-outlier guard) into a [0, 1] percentile (ties averaged) among all
    assets with a valid forward return on that date - pandas'
    `.rank(pct=True)`, the same convention every other rank-based metric in
    this codebase would expect.

    Must be called after the per-asset engineer_features() loop (needs
    target_return_5d/20d already computed) but before build_feature_dataset()'s
    final concat/strftime - same ordering constraint as
    build_topology_features_by_date(), and deliberately a separate function
    from it (no pairwise correlation computation needed here, so none of
    that function's O(N^2) machinery applies).

    `min_universe_size` (config phase1.target.ranking.min_universe_size,
    default 10) guards against thin dates (e.g. weekends, when only crypto
    trades) - below that threshold the rank is NaN, not a near-meaningless
    percentile over a handful of assets. This is free: the masked loss
    (masked_mse_loss()) used by the rank_5d/20d training heads already
    treats NaN as "no target this row", the same convention the
    direction_5d/20d targets above already established.

    Also adds sibling `target_sector_neutral_rank_5d/20d` columns (Phase 5) -
    the SAME per-date percentile rank, but computed WITHIN each asset's
    sector bucket (load_sector_mapping()) instead of across the whole
    universe: "is this asset outperforming its sector peers," a cleaner
    signal than "is this asset outperforming the whole universe" when the
    universe's variance is dominated by a systematic tech/market factor.
    Purely additive - target_rank_5d/20d and every existing consumer
    (rank_sizing_multiplier(), the rank_5d/20d heads) are untouched.
    `min_sector_size` (config phase1.target.ranking.sector_neutral.min_sector_size,
    default 3) is the same "too few members -> NaN, not a near-meaningless
    rank" guard as min_universe_size, applied per (date, sector) instead of
    per date. Assets whose sector can't be resolved (load_sector_mapping()
    has no entry) get UNKNOWN_SECTOR_LABEL, which naturally NaNs out unless
    enough OTHER unmapped assets exist that day to clear min_sector_size.
    """
    ranking_config = config.get("phase1", {}).get("target", {}).get("ranking", {})
    min_universe_size = int(ranking_config.get("min_universe_size", DEFAULT_RANKING_MIN_UNIVERSE_SIZE))
    sector_neutral_config = ranking_config.get("sector_neutral", {})
    min_sector_size = int(sector_neutral_config.get("min_sector_size", DEFAULT_SECTOR_NEUTRAL_MIN_SECTOR_SIZE))
    sector_by_ticker = load_sector_mapping(config)

    updated_frames: dict[str, pd.DataFrame] = dict(asset_frames)
    for horizon_days in (5, 20):
        return_column = f"target_return_{horizon_days}d"
        rank_column = f"target_rank_{horizon_days}d"
        sector_neutral_rank_column = f"target_sector_neutral_rank_{horizon_days}d"

        long_frame = pd.concat(
            [
                pd.DataFrame({"ticker": ticker, "date": frame["date"], return_column: frame[return_column]})
                for ticker, frame in updated_frames.items()
            ],
            ignore_index=True,
        )
        eligible = long_frame.dropna(subset=[return_column]).copy()
        universe_size_by_date = eligible.groupby("date")[return_column].transform("size")
        eligible = eligible[universe_size_by_date >= min_universe_size].copy()
        eligible["rank_value"] = eligible.groupby("date")[return_column].rank(pct=True)
        rank_lookup = eligible.set_index(["ticker", "date"])["rank_value"].to_dict()

        sector_eligible = long_frame.dropna(subset=[return_column]).copy()
        sector_eligible["sector"] = sector_eligible["ticker"].map(sector_by_ticker).fillna(UNKNOWN_SECTOR_LABEL)
        sector_size = sector_eligible.groupby(["date", "sector"])[return_column].transform("size")
        sector_eligible = sector_eligible[sector_size >= min_sector_size].copy()
        sector_eligible["sector_rank_value"] = sector_eligible.groupby(["date", "sector"])[return_column].rank(
            pct=True
        )
        sector_rank_lookup = sector_eligible.set_index(["ticker", "date"])["sector_rank_value"].to_dict()

        for ticker, frame in updated_frames.items():
            result = frame.copy()
            result[rank_column] = [rank_lookup.get((ticker, date), np.nan) for date in result["date"]]
            result[sector_neutral_rank_column] = [
                sector_rank_lookup.get((ticker, date), np.nan) for date in result["date"]
            ]
            updated_frames[ticker] = result

    return updated_frames


def build_cross_sectional_momentum_rank_features(asset_frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Cross-sectional per-date percentile rank of each asset's own
    momentum_20d (Phase 6) - the best-documented daily cross-sectional
    anomaly (12-1 month momentum). Unlike build_cross_sectional_rank_targets()'s
    forward-looking targets, today's momentum_20d is already fully known as
    of today - no lookahead concern, no min_universe_size guard needed
    beyond the plain "need >= 2 assets to rank" rule
    features.cross_sectional_momentum_rank() already encodes (thin dates
    default to 0.5, the exact middle, via that same neutral-default
    convention).

    Computed here via pandas .rank(pct=True) directly (mathematically
    identical to features.cross_sectional_momentum_rank()'s own
    average-tie-rank formula - both are the standard percentile-rank-with-
    averaged-ties convention) since a full per-date DataFrame already
    exists offline, unlike main.py's runtime per-bar dict.

    Must be called after the per-asset engineer_features() loop (needs
    momentum_20d already computed) but before build_feature_dataset()'s
    final concat/strftime - same ordering constraint as
    build_topology_features_by_date()/build_cross_sectional_rank_targets().
    """
    long_frame = pd.concat(
        [
            pd.DataFrame({"ticker": ticker, "date": frame["date"], "momentum_20d": frame["momentum_20d"]})
            for ticker, frame in asset_frames.items()
        ],
        ignore_index=True,
    )
    universe_size_by_date = long_frame.groupby("date")["momentum_20d"].transform("size")
    long_frame["cs_momentum_rank_20"] = np.where(
        universe_size_by_date >= 2,
        long_frame.groupby("date")["momentum_20d"].rank(pct=True),
        CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL,
    )
    rank_lookup = long_frame.set_index(["ticker", "date"])["cs_momentum_rank_20"].to_dict()

    updated_frames: dict[str, pd.DataFrame] = {}
    for ticker, frame in asset_frames.items():
        result = frame.copy()
        result["cs_momentum_rank_20"] = [
            rank_lookup.get((ticker, date), CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL) for date in result["date"]
        ]
        updated_frames[ticker] = result
    return updated_frames


# The original phase1.features.input_set - always required for
# engineer_features()'s own dropna, computed per-asset before any
# cross-sectional (topology) or regime/liquidity feature exists. Kept as an
# explicit constant (not read from config) since regime/liquidity features
# below are computed from these same names via row-wise .get() lookups -
# renaming one of these 10 without updating _encode_regime_row() would be a
# silent mismatch, so keeping them fixed here is deliberate.
BASE_FEATURE_NAMES = [
    "close_to_close_return_1d",
    "close_to_close_return_5d",
    "close_to_close_return_20d",
    "rolling_volatility_5d",
    "rolling_volatility_20d",
    "momentum_5d",
    "momentum_20d",
    "high_low_range_pct",
    "open_close_range_pct",
    "volume_change_1d",
    # Phase 6 technical indicators - appended, not inserted among the
    # original 10 (the docstring above's "renaming one of these 10" warning
    # is about renaming, not appending; _encode_regime_row() looks up its
    # own specific names by key via .get(), unaffected by new keys existing
    # alongside them).
    "rsi_14",
    "atr_pct_14",
    "bollinger_pctb_20",
    "volume_zscore_20",
    "macd_histogram_norm",
    "dist_52w_high",
]


def _categorical_feature_names(dataset: pd.DataFrame) -> list[str]:
    """Regime/topology one-hot flags present in `dataset` - unscaled model
    inputs, same treatment as the asset-context one-hots
    add_asset_context_features() produces (already-bounded [0,1] flags, no
    StandardScaler needed). Filtered against `dataset.columns` rather than
    returned unconditionally so a --candidate/--dataset-only run against an
    older dataset without these columns degrades gracefully instead of
    KeyError-ing downstream."""
    return [name for name in (REGIME_ONEHOT_FEATURE_NAMES + TOPOLOGY_ONEHOT_FEATURE_NAMES) if name in dataset.columns]


def build_feature_dataset(config: dict) -> tuple[pd.DataFrame, dict]:
    phase1 = config["phase1"]
    assets = phase1["universe"]["assets"]
    windows = phase1["windows"]
    target_config = phase1.get("target", {})
    max_abs_daily_return = target_config.get("max_abs_daily_return", DEFAULT_MAX_ABS_DAILY_RETURN)
    max_abs_return_5d = target_config.get("max_abs_return_5d", DEFAULT_MAX_ABS_RETURN_5D)
    max_abs_return_20d = target_config.get("max_abs_return_20d", DEFAULT_MAX_ABS_RETURN_20D)

    asset_frames = {
        asset["ticker"]: load_lean_bars(asset, phase1["universe"]["common_window"])
        for asset in assets
    }
    union_dates = sorted({date_value for frame in asset_frames.values() for date_value in frame["date"].tolist()})
    intersection_dates: set[pd.Timestamp] | None = None
    for frame in asset_frames.values():
        date_set = set(frame["date"].tolist())
        intersection_dates = date_set if intersection_dates is None else intersection_dates & date_set

    engineered_frames: dict[str, pd.DataFrame] = {}
    asset_summaries = []
    for asset in assets:
        ticker = asset["ticker"]
        asset_frame = asset_frames[ticker].sort_values("date").reset_index(drop=True)
        # add_liquidity_features() runs on the RAW frame (before
        # engineer_features() drops the first row) so its trailing spread
        # window sees the true, undropped bar sequence - see that
        # function's docstring for why this ordering is load-bearing, not
        # cosmetic.
        asset_frame = add_liquidity_features(asset_frame, asset["security_type"])
        engineered = engineer_features(
            asset_frame,
            BASE_FEATURE_NAMES,
            windows,
            security_type=asset["security_type"],
            max_abs_daily_return=max_abs_daily_return,
            max_abs_return_5d=max_abs_return_5d,
            max_abs_return_20d=max_abs_return_20d,
        )
        engineered = add_regime_features(engineered)
        engineered_frames[ticker] = engineered
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

    # Cross-sectional (needs every asset's engineered frame simultaneously) -
    # must run after the per-asset loop above, before the final concat.
    engineered_frames = build_topology_features_by_date(engineered_frames, config)
    engineered_frames = build_macro_features_by_date(engineered_frames, config)
    engineered_frames = build_bond_features_by_date(engineered_frames, config, load_cached_fred_series())
    engineered_frames = build_derivatives_macro_features_by_date(engineered_frames, config)
    engineered_frames = build_cross_sectional_rank_targets(engineered_frames, config)
    engineered_frames = build_cross_sectional_momentum_rank_features(engineered_frames)

    dataset = pd.concat(list(engineered_frames.values()), ignore_index=True)
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


def fit_and_apply_scaler(
    dataset: pd.DataFrame,
    feature_names: list[str],
    *,
    winsorize_quantiles: tuple[float, float] = (0.001, 0.999),
    clip_sigma: float = 10.0,
) -> tuple[pd.DataFrame, StandardScaler, float]:
    train_mask = dataset["split"] == "train"
    if "training_eligible" in dataset.columns:
        train_mask = train_mask & dataset["training_eligible"]
    if int(train_mask.sum()) == 0:
        raise ValueError("No training-eligible rows available to fit scaler.")

    train_features = dataset.loc[train_mask, feature_names]
    # Winsorize a COPY of the train-only slice before fitting so a single
    # extreme outlier (e.g. BTCUSD's 2018-08-14 volume-feed discontinuity,
    # see development/Problems.md) can't distort the scaler's mean/std
    # estimate - only the fit is robustified, every row's real,
    # unwinsorized value is still what gets transformed below.
    lower_quantile, upper_quantile = winsorize_quantiles
    lower_bounds = train_features.quantile(lower_quantile)
    upper_bounds = train_features.quantile(upper_quantile)
    winsorized_train_features = train_features.clip(lower=lower_bounds, upper=upper_bounds, axis=1)

    scaler = StandardScaler()
    scaler.fit(winsorized_train_features)

    scaled_values = scaler.transform(dataset[feature_names])
    # Clip in scaled (sigma) space too - this is the layer that actually
    # protects downstream models (especially the sequence encoder, whose
    # sliding window replicates a single poisoned row into every subsequent
    # window) from a validation/backtest-split outlier the train-only
    # winsorized fit above can't see or bound on its own.
    scaled_values = np.clip(scaled_values, -clip_sigma, clip_sigma)
    for index, feature_name in enumerate(feature_names):
        dataset[f"{feature_name}_scaled"] = scaled_values[:, index]

    return dataset, scaler, float(clip_sigma)


def add_asset_context_features(dataset: pd.DataFrame, tickers: list[str]) -> tuple[pd.DataFrame, list[str]]:
    context_columns: list[str] = []
    for ticker in tickers:
        column_name = f"asset_{ticker}"
        dataset[column_name] = (dataset["ticker"] == ticker).astype(float)
        context_columns.append(column_name)
    return dataset, context_columns


ASSET_CLASS_VALUES = ("equity", "crypto", "bond", "future", "option")


def add_asset_class_context_features(dataset: pd.DataFrame, asset_class_by_ticker: dict[str, str]) -> tuple[pd.DataFrame, list[str]]:
    """5-column one-hot over ASSET_CLASS_VALUES - additive sibling to
    add_asset_context_features()'s per-ticker one-hot, deliberately using
    the same "asset_"-prefixed naming convention (asset_class_equity,
    asset_class_bond, ...) so build_dataset_manifest()'s existing generic
    `column.startswith("asset_")` filter picks these up as
    context_feature_names automatically - zero changes needed there. This
    is the mechanism letting the model condition on asset class (equity vs
    crypto vs bond vs future vs option) inside one shared, unified feature
    vector rather than requiring a separate model per asset class - see
    train.py's module-level docstring / development/v2_architecture.md for
    why a single shared vector was chosen over per-asset-class models
    (fragmenting the rank-IC promotion gate and MoE gating architecture
    across 5 models, and breaking cross-asset macro-feature sharing).

    A ticker missing from asset_class_by_ticker (shouldn't happen -
    callers always build it from the full configured universe, but
    defensive) falls back to "equity", the least-surprising default and
    this codebase's existing Lean security_type default everywhere else."""
    ticker_classes = dataset["ticker"].map(lambda ticker: asset_class_by_ticker.get(ticker, "equity"))
    context_columns: list[str] = []
    for asset_class in ASSET_CLASS_VALUES:
        column_name = f"asset_class_{asset_class}"
        dataset[column_name] = (ticker_classes == asset_class).astype(float)
        context_columns.append(column_name)
    return dataset, context_columns


def select_model_context_columns(dataset_columns) -> list[str]:
    """The one place that decides which "asset_"-prefixed dataset columns
    become actual model inputs - used by build_dataset_manifest() (what
    gets exported as feature_schema.json's context_feature_names, which
    main.py reads at runtime) AND by every trainer's own feature_names
    construction, so the exported schema and the actually-trained model
    input vector can never drift apart (same predicate, same column order,
    computed from the same dataset object).

    Selects only the 5 asset_class_* columns (add_asset_class_context_features()),
    not the per-ticker asset_<TICKER> ones (add_asset_context_features()) -
    35 of this model's 85 inputs used to be static per-ticker identity
    flags (development/Problems.md), which can only encode each ticker's
    own base rate and pushes the net toward a constant per-asset output.
    Collapsing to 5 class-level flags keeps the "which kind of asset is
    this" context signal (needed for the macro/bond/crypto feature blocks
    to mean the right thing per asset class) without the per-ticker
    memorization capacity. add_asset_context_features() itself is
    unchanged and still runs (other, non-model-input consumers may still
    want the per-ticker columns in the dataset) - this only changes which
    columns get SELECTED as model inputs.

    Safe on the runtime side without further plumbing: main.py's
    context_values dict (main.py::_build_model_input()) is built generically
    from whatever names feature_schema.json's context_feature_names lists,
    filling asset_<ticker>/asset_class_<class> keys only "if key in
    context_values" - a per-ticker key simply won't exist post-collapse,
    exactly like an older exported model's schema missing the (newer)
    asset_class_ keys entirely already degrades gracefully today."""
    return [column for column in dataset_columns if str(column).startswith("asset_class_")]


def asset_class_by_ticker_from_config(config: dict) -> dict[str, str]:
    return {
        asset["ticker"]: asset.get("asset_class") or asset.get("security_type")
        for asset in config["phase1"]["universe"]["assets"]
    }


def build_dataset_manifest(
    config: dict,
    dataset: pd.DataFrame,
    inventory: dict,
    metadata: dict,
    asset_quality: dict,
) -> dict:
    base_feature_names = config["phase1"]["features"]["input_set"]
    context_feature_names = select_model_context_columns(dataset.columns)
    categorical_feature_names = _categorical_feature_names(dataset)
    scaled_feature_names = [f"{feature_name}_scaled" for feature_name in base_feature_names]
    model_input_names = scaled_feature_names + categorical_feature_names + context_feature_names

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
        "categorical_feature_names": categorical_feature_names,
        "context_feature_names": context_feature_names,
        "model_input_names": model_input_names,
        "model_input_count": len(model_input_names),
        "target_column": "target_direction",
        "aux_target_column": "target_return_1d",
        # Additive head->column map for the multi-horizon/ranking heads
        # (train_multitask.py/train_sequence.py) - never replaces
        # target_column/aux_target_column above, which every existing
        # consumer (experts/expert_datasets.py, feature_schema.json)
        # still reads unchanged.
        "target_columns": {
            "direction": "target_direction",
            "magnitude": "target_return_1d",
            "volatility": "target_volatility_next_day",
            "direction_5d": "target_direction_5d",
            "direction_20d": "target_direction_20d",
            "rank_5d": "target_rank_5d",
            "rank_20d": "target_rank_20d",
            "sector_neutral_rank_20d": "target_sector_neutral_rank_20d",
        },
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


def write_scaler_artifacts(
    scaler: StandardScaler,
    manifest: dict,
    *,
    scaler_path: Path = SCALER_PATH,
    scaler_stats_path: Path = SCALER_STATS_PATH,
    clip_sigma: float = 10.0,
) -> None:
    """Persists the fitted scaler as both the joblib pickle (training-only)
    and the JSON mean/scale arrays main.py actually loads for inference.
    `clip_sigma` (the scaled-value clip bound fit_and_apply_scaler() already
    applied offline) is carried along so main.py can apply the identical
    bound at runtime - see main.py::_build_model_input()'s matching clamp,
    with a safe default of 10.0 for scaler_stats.json files written before
    this field existed.

    Extracted out of write_dataset_artifacts() so candidate training (V2-17)
    can write into ml/versions/<id>/ without touching the active scaler.
    """
    scaler_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(scaler, scaler_path)
    scaler_stats_path.write_text(
        json.dumps(
            {
                "feature_names": manifest["feature_names"],
                "mean": [float(value) for value in scaler.mean_.tolist()],
                "scale": [float(value) for value in scaler.scale_.tolist()],
                "clip_sigma": float(clip_sigma),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def write_dataset_artifacts(
    dataset: pd.DataFrame,
    manifest: dict,
    scaler: StandardScaler,
    config: dict | None = None,
    clip_sigma: float = 10.0,
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
                "categorical_feature_names": manifest["categorical_feature_names"],
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
    write_scaler_artifacts(scaler, manifest, clip_sigma=clip_sigma)

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


class AetherNetMultiTask(nn.Module):
    """Shared-trunk, three-head variant of AetherNet: direction (binary
    logit), magnitude (raw regression) and volatility (Softplus, always
    non-negative). The trunk is identical in shape to AetherNet's own
    hidden-layer stack (same build_activation/build_normalization reuse) -
    only the single output Linear(., 1) is replaced with three independent
    small heads sharing the trunk's representation. See
    inference/exported_model.py::run_exported_multitask_model() for the
    matching interpreter and export_multitask_architecture() below for the
    matching exporter."""

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
        self.trunk = nn.Sequential(*layers)
        self.head_direction = nn.Linear(current_dim, 1)
        self.head_magnitude = nn.Linear(current_dim, 1)
        self.head_volatility = nn.Linear(current_dim, 1)

    def forward(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        trunk_output = self.trunk(features)
        direction_logit = self.head_direction(trunk_output).squeeze(-1)
        magnitude = self.head_magnitude(trunk_output).squeeze(-1)
        volatility = nn.functional.softplus(self.head_volatility(trunk_output).squeeze(-1))
        return direction_logit, magnitude, volatility


class AetherNetMultiTaskHorizons(nn.Module):
    """Extends AetherNetMultiTask with 4 additional heads: direction_5d/
    direction_20d (longer-horizon direction - the highest-leverage change
    this codebase's root-cause investigation identified, since next-day
    binary direction on liquid daily bars is close to efficient-market
    noise, and longer horizons give momentum/mean-reversion more room to
    show up) and rank_5d/rank_20d (cross-sectional percentile-rank of
    forward return across the universe on the same date - typically far
    more learnable than absolute direction, and maps directly onto a
    long/short portfolio).

    A NEW sibling class, not a modification of AetherNetMultiTask -
    train.py::_train_expert_multitask() (the 4 regime experts' own
    multitask heads) keeps using the original 3-head class completely
    unchanged, by design (experts/baseline/gating stay 1d-direction-only,
    see development/Changelog.md). Same trunk-building logic as
    AetherNetMultiTask; all 7 heads share it.

    forward() returns a dict, not AetherNetMultiTask's fixed 3-tuple - one
    raw (pre-activation, except volatility which applies softplus
    internally same as AetherNetMultiTask) tensor per head. This naming
    maps 1:1 onto the export's "heads" dict keys (see
    export_multitask_horizons_architecture()), which
    inference/exported_model.py::run_exported_multitask_model() already
    iterates generically - no interpreter changes needed for the new
    heads."""

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
        self.trunk = nn.Sequential(*layers)
        self.head_direction = nn.Linear(current_dim, 1)
        self.head_magnitude = nn.Linear(current_dim, 1)
        self.head_volatility = nn.Linear(current_dim, 1)
        self.head_direction_5d = nn.Linear(current_dim, 1)
        self.head_direction_20d = nn.Linear(current_dim, 1)
        self.head_rank_5d = nn.Linear(current_dim, 1)
        self.head_rank_20d = nn.Linear(current_dim, 1)
        # Phase 5 of the 5/10 -> 9/10 roadmap: a NEW sibling head, not a
        # modification of head_rank_20d - every existing consumer of
        # rank_20d (rank_sizing_multiplier(), etc.) is unaffected until/
        # unless someone deliberately switches to this sector-demeaned
        # variant. See build_cross_sectional_rank_targets()'s docstring.
        self.head_sector_neutral_rank_20d = nn.Linear(current_dim, 1)

    def forward(self, features: torch.Tensor) -> dict[str, torch.Tensor]:
        trunk_output = self.trunk(features)
        return {
            "direction": self.head_direction(trunk_output).squeeze(-1),
            "magnitude": self.head_magnitude(trunk_output).squeeze(-1),
            "volatility": nn.functional.softplus(self.head_volatility(trunk_output).squeeze(-1)),
            "direction_5d": self.head_direction_5d(trunk_output).squeeze(-1),
            "direction_20d": self.head_direction_20d(trunk_output).squeeze(-1),
            "rank_5d": self.head_rank_5d(trunk_output).squeeze(-1),
            "rank_20d": self.head_rank_20d(trunk_output).squeeze(-1),
            "sector_neutral_rank_20d": self.head_sector_neutral_rank_20d(trunk_output).squeeze(-1),
        }


class AetherNetSequenceMultiTask(nn.Module):
    """Phase 2: a causal TCN (temporal convolutional network) trunk over a
    rolling window of already-computed flat model_input vectors, replacing
    AetherNetMultiTask's flat-MLP trunk with genuine temporal structure -
    the root limitation the original root-cause investigation flagged
    ("AetherNet is a plain feedforward MLP with zero temporal structure").

    A stack of causal, dilated Conv1d layers (dilation doubling each layer:
    1, 2, 4, ... - the standard WaveNet/TCN receptive-field-growth idiom),
    each left-padded by (kernel_size-1)*dilation timesteps before the conv
    so output[t] never depends on input[>t] (no lookahead, same invariant
    every other feature in this codebase already respects) - matching
    inference/exported_model.py::_conv1d_causal()'s exact convention.
    Pools to the trunk's most-recent (causal) timestep, then the same
    three direction/magnitude/volatility heads AetherNetMultiTask already
    uses.

    Chosen over a Transformer encoder block for this first real Phase 2
    model specifically because a causal conv stack is simpler to verify
    bit-for-bit end-to-end (see
    inference/exported_model.py::run_exported_sequence_multitask_model()) -
    _multihead_attention() is implemented and independently tested as
    interpreter infrastructure for a future attention-based model, not
    wired to a trained model in this pass; see train_sequence.py's module
    docstring for the fuller scope note.
    """

    def __init__(
        self,
        input_dim: int,
        channels: list[int],
        kernel_size: int,
        dropout: float,
    ) -> None:
        super().__init__()
        if not channels:
            raise ValueError("AetherNetSequenceMultiTask requires at least one trunk channel size.")
        self.kernel_size = int(kernel_size)
        self.conv_layers = nn.ModuleList()
        current_channels = input_dim
        for layer_index, out_channels in enumerate(channels):
            dilation = 2**layer_index
            self.conv_layers.append(nn.Conv1d(current_channels, out_channels, self.kernel_size, dilation=dilation))
            current_channels = out_channels
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()
        self.head_direction = nn.Linear(current_channels, 1)
        self.head_magnitude = nn.Linear(current_channels, 1)
        self.head_volatility = nn.Linear(current_channels, 1)

    def forward(self, sequence: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        # sequence: (batch, window, input_dim) -> Conv1d wants channels-first.
        current = sequence.transpose(1, 2)  # (batch, input_dim, window)
        for layer_index, conv in enumerate(self.conv_layers):
            dilation = conv.dilation[0]
            pad_left = (self.kernel_size - 1) * dilation
            current = nn.functional.pad(current, (pad_left, 0))
            current = conv(current)
            current = self.dropout(self.activation(current))

        pooled = current[:, :, -1]  # (batch, channels[-1]) - most-recent timestep
        direction_logit = self.head_direction(pooled).squeeze(-1)
        magnitude = self.head_magnitude(pooled).squeeze(-1)
        volatility = nn.functional.softplus(self.head_volatility(pooled).squeeze(-1))
        return direction_logit, magnitude, volatility


class AetherNetSequenceMultiTaskHorizons(nn.Module):
    """Sequence-encoder sibling of AetherNetMultiTaskHorizons: the same
    causal TCN trunk as AetherNetSequenceMultiTask, extended with the same
    4 additional heads (direction_5d/20d, rank_5d/20d). A NEW class, not a
    modification of AetherNetSequenceMultiTask - same reasoning as
    AetherNetMultiTaskHorizons above (experts never use the sequence
    model at all, so there is no shared-code risk here, but the
    new-sibling-class convention stays consistent across both trainers).
    forward() returns a dict, matching AetherNetMultiTaskHorizons and the
    export's "heads" dict shape."""

    def __init__(
        self,
        input_dim: int,
        channels: list[int],
        kernel_size: int,
        dropout: float,
    ) -> None:
        super().__init__()
        if not channels:
            raise ValueError("AetherNetSequenceMultiTaskHorizons requires at least one trunk channel size.")
        self.kernel_size = int(kernel_size)
        self.conv_layers = nn.ModuleList()
        current_channels = input_dim
        for layer_index, out_channels in enumerate(channels):
            dilation = 2**layer_index
            self.conv_layers.append(nn.Conv1d(current_channels, out_channels, self.kernel_size, dilation=dilation))
            current_channels = out_channels
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()
        self.head_direction = nn.Linear(current_channels, 1)
        self.head_magnitude = nn.Linear(current_channels, 1)
        self.head_volatility = nn.Linear(current_channels, 1)
        self.head_direction_5d = nn.Linear(current_channels, 1)
        self.head_direction_20d = nn.Linear(current_channels, 1)
        self.head_rank_5d = nn.Linear(current_channels, 1)
        self.head_rank_20d = nn.Linear(current_channels, 1)
        # Phase 5 of the 5/10 -> 9/10 roadmap - see
        # AetherNetMultiTaskHorizons.head_sector_neutral_rank_20d's
        # identical docstring.
        self.head_sector_neutral_rank_20d = nn.Linear(current_channels, 1)

    def forward(self, sequence: torch.Tensor) -> dict[str, torch.Tensor]:
        current = sequence.transpose(1, 2)  # (batch, input_dim, window)
        for conv in self.conv_layers:
            dilation = conv.dilation[0]
            pad_left = (self.kernel_size - 1) * dilation
            current = nn.functional.pad(current, (pad_left, 0))
            current = conv(current)
            current = self.dropout(self.activation(current))

        pooled = current[:, :, -1]  # (batch, channels[-1]) - most-recent timestep
        return {
            "direction": self.head_direction(pooled).squeeze(-1),
            "magnitude": self.head_magnitude(pooled).squeeze(-1),
            "volatility": nn.functional.softplus(self.head_volatility(pooled).squeeze(-1)),
            "direction_5d": self.head_direction_5d(pooled).squeeze(-1),
            "direction_20d": self.head_direction_20d(pooled).squeeze(-1),
            "rank_5d": self.head_rank_5d(pooled).squeeze(-1),
            "rank_20d": self.head_rank_20d(pooled).squeeze(-1),
            "sector_neutral_rank_20d": self.head_sector_neutral_rank_20d(pooled).squeeze(-1),
        }


def _export_conv1d_trunk(model) -> list[dict]:
    """Shared by export_sequence_multitask_architecture() and
    export_sequence_multitask_horizons_architecture() - both models build
    their causal TCN trunk identically (AetherNetSequenceMultiTask/
    AetherNetSequenceMultiTaskHorizons.__init__ are the same conv-stack
    loop), only their heads differ."""
    trunk: list[dict] = []
    for layer_index, conv in enumerate(model.conv_layers):
        trunk.append(
            {
                "type": "conv1d_causal",
                "weight_key": f"conv_layers.{layer_index}.weight",
                "bias_key": f"conv_layers.{layer_index}.bias",
                "dilation": conv.dilation[0],
                "in_channels": conv.in_channels,
                "out_channels": conv.out_channels,
                "kernel_size": conv.kernel_size[0],
            }
        )
        trunk.append({"type": "relu"})
        trunk.append({"type": "dropout", "p": model.dropout.p if isinstance(model.dropout, nn.Dropout) else 0.0})
    return trunk


def export_sequence_multitask_architecture(model: AetherNetSequenceMultiTask) -> dict:
    """Branching export for AetherNetSequenceMultiTask - same {"trunk":
    [...], "heads": {...}} shape export_multitask_architecture() produces,
    but trunk entries are "conv1d_causal" layers (each carrying its own
    dilation, doubling per layer to match __init__'s dilation=2**layer_index)
    instead of "linear". Consumed by
    inference/exported_model.py::run_exported_sequence_multitask_model()."""
    return {
        "trunk": _export_conv1d_trunk(model),
        "heads": {
            "direction": _export_head(model.head_direction, "head_direction", "sigmoid"),
            "magnitude": _export_head(model.head_magnitude, "head_magnitude", None),
            "volatility": _export_head(model.head_volatility, "head_volatility", "softplus"),
        },
    }


def export_sequence_multitask_horizons_architecture(model: AetherNetSequenceMultiTaskHorizons) -> dict:
    """Branching export for AetherNetSequenceMultiTaskHorizons - same
    {"trunk", "heads"} shape export_sequence_multitask_architecture()
    produces for the original 3-head sequence model, extended with 4 more
    head entries (direction_5d/20d, rank_5d/20d).
    inference/exported_model.py::run_exported_sequence_multitask_model()
    already iterates export["heads"] generically, so no interpreter change
    is needed to support the extra heads."""
    return {
        "trunk": _export_conv1d_trunk(model),
        "heads": {
            "direction": _export_head(model.head_direction, "head_direction", "sigmoid"),
            "magnitude": _export_head(model.head_magnitude, "head_magnitude", None),
            "volatility": _export_head(model.head_volatility, "head_volatility", "softplus"),
            "direction_5d": _export_head(model.head_direction_5d, "head_direction_5d", "sigmoid"),
            "direction_20d": _export_head(model.head_direction_20d, "head_direction_20d", "sigmoid"),
            "rank_5d": _export_head(model.head_rank_5d, "head_rank_5d", "sigmoid"),
            "rank_20d": _export_head(model.head_rank_20d, "head_rank_20d", "sigmoid"),
            "sector_neutral_rank_20d": _export_head(
                model.head_sector_neutral_rank_20d, "head_sector_neutral_rank_20d", "sigmoid"
            ),
        },
    }


def build_sequence_tensor_dataset(
    dataset: pd.DataFrame, model_input_names: list[str], window_size: int
) -> np.ndarray:
    """Builds a (rows, window_size, features) tensor, row-order-aligned
    with `dataset` itself (sequences[i] corresponds to dataset.iloc[i]),
    using each ticker's own trailing window of already-computed
    model_input columns - the exact same 48-dim vector AetherNetMultiTask's
    flat trunk already consumes per row. Phase 2 needs no new feature
    engineering, only windowing over what Phase 1 already computes per bar
    - `dataset` must already be sorted the way build_feature_dataset()
    leaves it (by date within each ticker's own rows, in chronological
    order).

    Rows with fewer than `window_size` preceding rows (including itself)
    for their ticker are LEFT-PADDED with zeros - main.py's runtime
    rolling buffer (main.py::_build_sequence_model_input()) starts empty
    and fills up bar by bar the same way, so this is the correct offline
    mirror of that behavior, not an approximation."""
    feature_matrix = dataset[model_input_names].to_numpy(dtype=np.float32)
    tickers = dataset["ticker"].to_numpy()

    sequences = np.zeros((len(dataset), window_size, len(model_input_names)), dtype=np.float32)
    positions_by_ticker: dict[str, list[int]] = {}
    for position, ticker in enumerate(tickers):
        positions_by_ticker.setdefault(ticker, []).append(position)

    for positions in positions_by_ticker.values():
        for index_within_ticker, position in enumerate(positions):
            window_start = max(0, index_within_ticker + 1 - window_size)
            window_positions = positions[window_start : index_within_ticker + 1]
            window_values = feature_matrix[window_positions]
            sequences[position, -len(window_values):, :] = window_values

    return sequences


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


def is_new_best_epoch(
    candidate_metric: float,
    best_metric_so_far: float,
    epoch: int,
    min_epoch: int = 3,
) -> bool:
    """Shared early-stopping decision for every direction-classification
    trainer (train_model/_train_expert_classifier here; train_multitask.py/
    train_sequence.py/train_gating.py call this too). Monitors a SKILL
    metric (validation balanced_accuracy - higher is better), not raw
    validation loss.

    Root cause this fixes (development/Problems.md): with near-flat logits,
    validation BCE loss was observed lowest at epoch 1 and rising every
    epoch after - so the old "epoch with min validation loss" rule shipped
    best_epoch=1 for the baseline, multitask AND sequence models alike: the
    checkpoint shipped was essentially the random initialization. Loss and
    balanced-accuracy are not the same surface - the network can still
    improve its decision boundary (balanced-accuracy) for a few epochs even
    while its calibration (BCE loss) degrades, which is exactly what a
    near-noise label produces. `min_epoch` additionally refuses to
    ship an epoch-1/2 checkpoint at all (returns False for epoch <
    min_epoch), forcing at least a few real gradient updates before any
    checkpoint becomes eligible, so a network that never improves past its
    initialization is at least given the chance to."""
    if epoch < min_epoch:
        return False
    return candidate_metric > best_metric_so_far


def compute_regression_metrics(predictions: torch.Tensor, targets: torch.Tensor) -> dict:
    """Plain regression metrics (MAE/RMSE + bias) for the magnitude/volatility
    heads - compute_binary_metrics() above stays direction-only, since MCC/
    F1/precision-recall are meaningless for a continuous target."""
    predictions_np = predictions.detach().cpu().numpy()
    targets_np = targets.detach().cpu().numpy()
    errors = predictions_np - targets_np
    mae = float(np.abs(errors).mean()) if len(errors) else 0.0
    rmse = float(np.sqrt((errors ** 2).mean())) if len(errors) else 0.0
    bias = float(errors.mean()) if len(errors) else 0.0
    return {
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "mean_prediction": float(predictions_np.mean()) if len(predictions_np) else 0.0,
        "mean_target": float(targets_np.mean()) if len(targets_np) else 0.0,
    }


def masked_bce_with_logits_loss(logits: torch.Tensor, targets: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Binary cross-entropy over only the rows where `mask` is True - used
    for the horizon-direction heads (direction_5d/20d), whose targets are
    NaN for the trailing few rows of each asset's history that don't yet
    have a full 5/20-day-forward close, rather than dropped from the
    dataset entirely (see engineer_features()'s docstring on why - dropping
    would also shrink every per-expert dataset slice downstream). Returns
    a true zero (no gradient contribution) rather than NaN/erroring when no
    row in this batch has a valid target for this head."""
    if not torch.any(mask):
        return torch.zeros((), device=logits.device)
    return nn.functional.binary_cross_entropy_with_logits(logits[mask], targets[mask])


def masked_mse_loss(predictions: torch.Tensor, targets: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Same masking convention as masked_bce_with_logits_loss() above, for
    regression targets - used by the cross-sectional rank_5d/20d heads
    (masked MSE against each row's percentile-rank target)."""
    if not torch.any(mask):
        return torch.zeros((), device=predictions.device)
    return nn.functional.mse_loss(predictions[mask], targets[mask])


def compute_masked_binary_metrics(
    logits: torch.Tensor,
    targets: torch.Tensor,
    criterion: nn.Module,
    threshold: float,
) -> dict | None:
    """compute_binary_metrics(), restricted to rows where `targets` is not
    NaN - compute_binary_metrics() itself has no NaN-awareness (a NaN
    target would silently miscount as a negative in its ==1/==0
    comparisons), so this must filter first. Returns None when a split has
    zero valid rows for this head (e.g. an unrealistically short backtest
    window shorter than the horizon itself) rather than reporting
    meaningless all-zero metrics."""
    mask = ~torch.isnan(targets)
    if not torch.any(mask):
        return None
    return compute_binary_metrics(logits[mask], targets[mask], criterion, threshold)


def compute_masked_regression_metrics(predictions: torch.Tensor, targets: torch.Tensor) -> dict | None:
    """compute_regression_metrics(), restricted to rows where `targets` is
    not NaN - same masking convention as compute_masked_binary_metrics()
    above, for the rank_5d/20d heads."""
    mask = ~torch.isnan(targets)
    if not torch.any(mask):
        return None
    return compute_regression_metrics(predictions[mask], targets[mask])


def _rank_ic_from_arrays(
    predictions: np.ndarray,
    targets: np.ndarray,
    dates: np.ndarray,
    non_overlapping_stride: int = 1,
) -> dict:
    """Torch-free core of compute_rank_ic() (Phase 6 of the 5/10 -> 9/10
    roadmap) - plain numpy arrays in, so this is usable from a lightweight
    production monitoring job (performance/rank_ic_monitor.py, fed rows
    from a Postgres query) without a torch dependency, not just from
    training-time tensors. compute_rank_ic() below is now a thin wrapper
    that converts tensors to numpy and calls this - both callers share the
    identical, tested logic, zero duplication.

    Per-date Spearman rank correlation ("rank-IC") between a model's raw
    rank_5d/20d prediction score and the realized cross-sectional rank
    target (target_rank_5d/20d - already a per-date percentile rank of
    forward return, see build_cross_sectional_rank_targets()). This is the
    standard evaluation metric for a cross-sectional/long-short signal,
    replacing "win condition" from absolute-direction MCC now that Phase 4
    exists: a mean rank-IC of 0.02-0.05 with a real t-stat is a genuine,
    monetizable edge in this literature, unlike 1d-direction MCC's noise
    band.

    Spearman(A, B) = Pearson(rank(A), rank(B)); target_rank is already
    rank(realized return) rescaled to [0, 1] (a positive affine transform,
    which Pearson is invariant to), so only the model's own raw prediction
    needs an explicit per-date rank transform before a plain Pearson
    correlation against target_rank directly reproduces the true Spearman
    correlation between prediction and realized return.

    `non_overlapping_stride` (e.g. 5 for the 5d horizon, 20 for the 20d
    horizon) subsamples to every Nth unique date before computing -
    consecutive daily rows share most of their forward-return window, so
    the naive daily IC series is autocorrelated and its plain t-stat
    overstates significance; the non-overlapping subsample gives a more
    honest (if noisier, fewer-observation) significance check. Pass 1
    (default) for the full, autocorrelated series.

    Dates with fewer than 2 eligible (non-NaN target) assets, or zero
    variance on either side (e.g. every asset tied), contribute no IC
    value for that date (skipped, not a spurious 0.0 - which would
    misrepresent "undefined" as "no correlation")."""
    frame = pd.DataFrame({"date": np.asarray(dates), "prediction": predictions, "target_rank": targets})
    frame = frame.dropna(subset=["target_rank"])

    if non_overlapping_stride > 1:
        unique_dates = sorted(frame["date"].unique())
        keep_dates = set(unique_dates[::non_overlapping_stride])
        frame = frame[frame["date"].isin(keep_dates)]

    ic_values = []
    for _, group in frame.groupby("date"):
        if len(group) < 2:
            continue
        prediction_rank = group["prediction"].rank(pct=True)
        if prediction_rank.nunique() < 2 or group["target_rank"].nunique() < 2:
            continue
        correlation = float(np.corrcoef(prediction_rank, group["target_rank"])[0, 1])
        if not np.isnan(correlation):
            ic_values.append(correlation)

    if not ic_values:
        return {"mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0, "num_dates": 0, "ic_values": []}

    ic_array = np.asarray(ic_values)
    mean_ic = float(ic_array.mean())
    std_ic = float(ic_array.std(ddof=1)) if len(ic_array) >= 2 else 0.0
    t_stat = float(mean_ic / (std_ic / np.sqrt(len(ic_array)))) if std_ic > 0 else 0.0
    # ic_values (Phase 2 of the 5/10 -> 9/10 roadmap): the raw per-date
    # series, previously discarded once the aggregate stats above were
    # computed - callers now need it for bootstrap_ic_confidence_interval()
    # rather than recomputing this whole function from scratch. Additive
    # dict key, backward-compatible with every existing caller that only
    # reads mean_ic/std_ic/t_stat/num_dates.
    return {
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "t_stat": t_stat,
        "num_dates": int(len(ic_array)),
        "ic_values": [float(value) for value in ic_values],
    }


def compute_rank_ic(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    dates,
    *,
    non_overlapping_stride: int = 1,
) -> dict:
    """Training-time wrapper over _rank_ic_from_arrays() - converts torch
    tensors to numpy, then defers entirely to the shared core. See
    _rank_ic_from_arrays()'s docstring for the actual algorithm."""
    predictions_np = predictions.detach().cpu().numpy()
    targets_np = targets.detach().cpu().numpy()
    return _rank_ic_from_arrays(predictions_np, targets_np, np.asarray(dates), non_overlapping_stride)


def bootstrap_ic_confidence_interval(
    ic_values: list[float],
    n_resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 42,
) -> dict:
    """Phase 2 of the 5/10 -> 9/10 roadmap: a resample-with-replacement
    bootstrap confidence interval over compute_rank_ic()'s raw per-date IC
    series, the most direct way to answer this codebase's own promotion
    question ("mean rank-IC > 0.02, t-stat > 2, non-overlapping dates,
    stable across reruns" - see development/Changelog.md's "frontier-model
    edge investigation" entry) with an actual interval instead of a single
    point estimate that a single unlucky/lucky rerun could shift.

    Deterministic (fixed `seed`) so repeated calls on the same ic_values
    reproduce the exact same interval - this codebase's other
    randomness-touching code (e.g. topology warm-start) is deliberately
    seeded the same way. Returns a degenerate all-zero interval (never
    raises) when fewer than 2 IC values are available - a bootstrap over 0
    or 1 observations is undefined, not "wide," and callers (e.g.
    assess_ranking_quality() below) must treat that as a failure to
    demonstrate significance, not a passing near-zero interval."""
    if len(ic_values) < 2:
        return {
            "lower_bound": 0.0,
            "upper_bound": 0.0,
            "mean_ic": 0.0,
            "confidence": confidence,
            "n_resamples": 0,
            "num_observations": len(ic_values),
        }

    rng = np.random.default_rng(seed)
    ic_array = np.asarray(ic_values, dtype=float)
    resample_means = np.empty(n_resamples, dtype=float)
    for index in range(n_resamples):
        sample = rng.choice(ic_array, size=len(ic_array), replace=True)
        resample_means[index] = sample.mean()

    alpha = 1.0 - confidence
    lower_bound = float(np.quantile(resample_means, alpha / 2.0))
    upper_bound = float(np.quantile(resample_means, 1.0 - alpha / 2.0))
    return {
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "mean_ic": float(ic_array.mean()),
        "confidence": confidence,
        "n_resamples": n_resamples,
        "num_observations": len(ic_values),
    }


def purged_embargoed_folds(
    dates,
    n_folds: int,
    horizon_days: int,
    embargo_days: int = 0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Phase 2 of the 5/10 -> 9/10 roadmap: a standard purged/embargoed
    K-fold split (Lopez de Prado-style) over `dates` (any array-like of
    orderable date values, one entry per dataset row - duplicates expected,
    since every asset shares each date). Layered *inside* the existing
    fixed phase1.windows train split as an additional diagnostic for
    hyperparameter/early-stopping robustness and a more honest in-sample IC
    distribution - it does NOT replace the top-level train/validation/backtest
    wall (that stays the single no-lookahead-across-the-wall boundary; see
    assign_split()), nor does it change which rows actually get promoted.

    For each of `n_folds` contiguous, equal-width date-range folds (assigned
    by unique date, not by row, so every asset's same-date rows always fall
    in the same fold together): the *validation* fold is exactly that
    date-range; the *training* rows are every row from the OTHER folds,
    minus (a) any row whose own forward-return window (horizon_days ahead)
    would overlap the validation fold's date range at all ("purge" - a
    training row labeled using information that reaches into the validation
    window leaks), and (b) any row falling within `embargo_days` immediately
    AFTER the validation fold's end date ("embargo" - guards against
    lookback-feature leakage, e.g. rolling_volatility_20d/momentum_20d
    computed just after the validation window still partially "sees" it).

    Returns a list of (train_row_indices, validation_row_indices) index
    arrays into `dates` itself (positional, 0-based) - same shape
    convention as sklearn's KFold.split(), so this composes with any
    existing sklearn-based tooling without adapting a different interface.
    Returns [] (never raises) when there are fewer unique dates than
    `n_folds`, matching this codebase's "guard against thin data" convention
    throughout train.py (e.g. build_cross_sectional_rank_targets()'s
    min_universe_size gate)."""
    # pd.to_datetime(), not np.asarray(): `dates` in real callers (e.g.
    # assess_ranking_quality_from_predictions(), fed train_multitask.py/
    # train_sequence.py's `frame["date"]`) is a plain string array -
    # build_feature_dataset() stringifies the date column
    # (dataset["date"].dt.strftime(...)) before any trainer ever reads it.
    # A raw np.asarray() on strings stays strings, and `era_start + Timedelta`
    # below would then raise "can only concatenate str to str" - explicit
    # datetime coercion here makes this function robust to string,
    # Timestamp, or datetime64 input alike, matching every other
    # date-accepting function in this file (e.g. assign_split()'s own
    # pd.Timestamp(date_value) coercion).
    #
    # np.unique(), not sorted(set(dates_array.tolist())): for a raw
    # datetime64[ns] numpy array (as opposed to a pandas Series, whose
    # .tolist() preserves Timestamp objects), .tolist() silently degrades
    # to plain nanosecond ints - Python's stdlib datetime can't represent
    # nanosecond precision - which would then compare incompatibly against
    # the still-datetime64 dates_array below. np.unique() preserves dtype
    # natively and needs no such workaround.
    dates_array = pd.to_datetime(np.asarray(dates))
    unique_dates = np.unique(dates_array)
    if len(unique_dates) < n_folds:
        return []

    fold_boundaries = np.array_split(unique_dates, n_folds)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    horizon = pd.Timedelta(days=horizon_days)
    embargo = pd.Timedelta(days=embargo_days)

    for fold_dates in fold_boundaries:
        if len(fold_dates) == 0:
            continue
        validation_start = fold_dates[0]
        validation_end = fold_dates[-1]
        validation_mask = (dates_array >= validation_start) & (dates_array <= validation_end)

        # Purge: a training row's own forward-return window (up to
        # horizon_days ahead of its own date) must not reach into the
        # validation date range - equivalently, exclude any row whose date
        # falls within horizon_days BEFORE the validation window starts.
        purge_start = validation_start - horizon
        purged_mask = (dates_array >= purge_start) & (dates_array < validation_start)

        # Embargo: exclude rows in the embargo_days immediately after the
        # validation window ends.
        embargo_end = validation_end + embargo
        embargoed_mask = (dates_array > validation_end) & (dates_array <= embargo_end)

        excluded_mask = validation_mask | purged_mask | embargoed_mask
        train_indices = np.where(~excluded_mask)[0]
        validation_indices = np.where(validation_mask)[0]
        if len(train_indices) == 0 or len(validation_indices) == 0:
            continue
        folds.append((train_indices, validation_indices))

    return folds


def split_into_non_overlapping_eras(dates, era_length_days: int) -> list[tuple]:
    """Phase 2 of the 5/10 -> 9/10 roadmap: chops the date range covered by
    `dates` (any array-like of orderable date values) into consecutive,
    non-overlapping eras of `era_length_days` each - e.g. quarterly eras
    over the existing 2019-2021 backtest window - so
    compute_rank_ic()/assess_ranking_quality() can be run independently per
    era instead of only ever producing one aggregate number. Turns the
    single "28 independent 20-day windows" analysis
    (development/Changelog.md) into a distribution across eras: was the
    edge concentrated in one regime (e.g. 2020 volatility), or stable?

    Returns a list of (era_start, era_end) date tuples spanning the full
    range of `dates` (inclusive on both ends, last era may be shorter than
    `era_length_days` if the range doesn't divide evenly - never dropped,
    since silently discarding the tail would bias eras away from the most
    recent data). Returns [] (never raises) when `dates` is empty."""
    # pd.to_datetime(), not np.asarray(): see purged_embargoed_folds()'s
    # identical comment - `dates` in every real caller is a plain string
    # array (build_feature_dataset() stringifies the date column), and
    # `era_start + era_length` below would raise on raw strings.
    dates_array = pd.to_datetime(np.asarray(dates))
    if len(dates_array) == 0:
        return []

    # np.unique(), not sorted(set(dates_array.tolist())) - see
    # purged_embargoed_folds()'s identical comment on why raw datetime64[ns]
    # numpy arrays need this, unlike a pandas Series.
    unique_dates = np.unique(dates_array)
    range_start = unique_dates[0]
    range_end = unique_dates[-1]
    era_length = pd.Timedelta(days=era_length_days)

    eras: list[tuple] = []
    era_start = range_start
    while era_start <= range_end:
        era_end = min(era_start + era_length - pd.Timedelta(days=1), range_end)
        eras.append((era_start, era_end))
        era_start = era_end + pd.Timedelta(days=1)

    return eras


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

    # Compound per ticker, not across the whole frame: `frame` may hold every
    # traded asset interleaved by (date, ticker) (see build_strategy_report's
    # per-split call), and a plain .cumprod() over that would compound one
    # ticker's return into the next ticker's running total.
    report_frame["cumulative_strategy"] = report_frame.groupby("ticker")["strategy_return"].transform(
        lambda returns: (1.0 + returns).cumprod()
    )
    report_frame["cumulative_baseline"] = report_frame.groupby("ticker")["baseline_return"].transform(
        lambda returns: (1.0 + returns).cumprod()
    )
    report_frame["strategy_drawdown"] = report_frame.groupby("ticker")["cumulative_strategy"].transform(
        lambda cumulative: cumulative / cumulative.cummax() - 1.0
    )
    report_frame["baseline_drawdown"] = report_frame.groupby("ticker")["cumulative_baseline"].transform(
        lambda cumulative: cumulative / cumulative.cummax() - 1.0
    )

    strategy_returns = report_frame["strategy_return"].to_numpy(dtype=float)
    baseline_returns = report_frame["baseline_return"].to_numpy(dtype=float)
    positions = report_frame["position"].to_numpy(dtype=float)
    position_changes = np.abs(np.diff(np.concatenate(([0.0], positions))))

    # Aggregate total-return/drawdown as an equal-weighted portfolio across
    # tickers per date (not per-ticker's own cumprod, which has no single
    # "last row" once multiple assets are present) - reduces to the same
    # single-ticker curve above when `frame` only holds one ticker.
    portfolio_by_date = report_frame.groupby("date")[["strategy_return", "baseline_return"]].mean().sort_index()
    portfolio_cumulative_strategy = (1.0 + portfolio_by_date["strategy_return"]).cumprod()
    portfolio_cumulative_baseline = (1.0 + portfolio_by_date["baseline_return"]).cumprod()

    strategy_total_return = (
        float(portfolio_cumulative_strategy.iloc[-1] - 1.0) if len(portfolio_cumulative_strategy) else 0.0
    )
    baseline_total_return = (
        float(portfolio_cumulative_baseline.iloc[-1] - 1.0) if len(portfolio_cumulative_baseline) else 0.0
    )

    strategy_mean = float(strategy_returns.mean()) if len(strategy_returns) else 0.0
    baseline_mean = float(baseline_returns.mean()) if len(baseline_returns) else 0.0
    strategy_vol = float(strategy_returns.std(ddof=1)) if len(strategy_returns) > 1 else 0.0
    baseline_vol = float(baseline_returns.std(ddof=1)) if len(baseline_returns) > 1 else 0.0

    annual_factor = math.sqrt(trading_days_per_year)
    strategy_sharpe = (strategy_mean / strategy_vol) * annual_factor if strategy_vol > 0 else 0.0
    baseline_sharpe = (baseline_mean / baseline_vol) * annual_factor if baseline_vol > 0 else 0.0

    strategy_max_drawdown = (
        float((portfolio_cumulative_strategy / portfolio_cumulative_strategy.cummax() - 1.0).min())
        if len(portfolio_cumulative_strategy)
        else 0.0
    )
    baseline_max_drawdown = (
        float((portfolio_cumulative_baseline / portfolio_cumulative_baseline.cummax() - 1.0).min())
        if len(portfolio_cumulative_baseline)
        else 0.0
    )
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
    min_positive_rate: float = 0.15,
    max_positive_rate: float = 0.85,
) -> tuple[float, dict]:
    """MCC (or whatever metric_name is) is nearly flat when logits carry
    little discriminative signal, so its weak maximum tends to sit at a
    near-degenerate corner - an operating point that calls almost
    everything positive (or almost everything negative). Confirmed live:
    the shipped baseline model picked threshold 0.46 -> positive_rate 0.91,
    the sequence model's threshold picked 0.545 -> positive_rate 0.0004
    (development/Problems.md). Neither is a useful trading signal even
    though each was the metric-optimal point in its unconstrained search.

    `min_positive_rate`/`max_positive_rate` restrict SELECTION to
    thresholds whose predicted positive rate falls in a non-degenerate
    band (every candidate is still scored, so the metric surface is swept
    faithfully). If every candidate in the sweep is degenerate, falls back
    to the plain best-scoring threshold from the unconstrained sweep rather
    than silently returning the never-searched default 0.5 - callers can
    tell which happened via best_metrics['positive_rate'] sitting outside
    the band."""
    best_threshold = 0.5
    best_metrics = compute_binary_metrics(logits, targets, criterion, best_threshold)
    best_score = best_metrics.get(metric_name, best_metrics["f1"])
    best_threshold_unconstrained = best_threshold
    best_metrics_unconstrained = best_metrics
    best_score_unconstrained = best_score

    def _within_band(metrics: dict) -> bool:
        positive_rate = float(metrics.get("positive_rate", 0.5))
        return min_positive_rate <= positive_rate <= max_positive_rate

    found_non_degenerate = _within_band(best_metrics)

    for threshold in np.linspace(threshold_min, threshold_max, threshold_steps):
        threshold = float(round(float(threshold), 4))
        metrics = compute_binary_metrics(logits, targets, criterion, threshold)
        score = metrics.get(metric_name, metrics["f1"])

        if score > best_score_unconstrained or (
            abs(score - best_score_unconstrained) < 1e-12 and abs(threshold - 0.5) < abs(best_threshold_unconstrained - 0.5)
        ):
            best_threshold_unconstrained = threshold
            best_metrics_unconstrained = metrics
            best_score_unconstrained = score

        if _within_band(metrics) and (
            score > best_score or (abs(score - best_score) < 1e-12 and abs(threshold - 0.5) < abs(best_threshold - 0.5))
        ):
            best_threshold = threshold
            best_metrics = metrics
            best_score = score
            found_non_degenerate = True

    if found_non_degenerate:
        return best_threshold, best_metrics
    return best_threshold_unconstrained, best_metrics_unconstrained


def find_optimal_masked_threshold(
    logits: torch.Tensor,
    targets: torch.Tensor,
    criterion: nn.Module,
    metric_name: str,
    threshold_min: float,
    threshold_max: float,
    threshold_steps: int,
) -> tuple[float, dict] | tuple[None, None]:
    """find_optimal_threshold(), restricted to non-NaN rows first - a
    horizon-direction head's own probability distribution is unrelated to
    the primary "direction" head's, so it needs its own tuned threshold
    (reusing the primary head's threshold verbatim was observed to
    silently collapse a horizon head to always-predict-positive, since a
    threshold tuned for one head's logit distribution is meaningless
    applied to another's - see development/Problems.md). Shared by
    train_multitask.py/train_sequence.py, both of which train
    AetherNetMultiTaskHorizons/AetherNetSequenceMultiTaskHorizons's
    identically-named horizon heads."""
    mask = ~torch.isnan(targets)
    if not torch.any(mask):
        return None, None
    return find_optimal_threshold(logits[mask], targets[mask], criterion, metric_name, threshold_min, threshold_max, threshold_steps)


# Head name -> (target column, "binary"/"rank", non_overlapping_stride for
# rank-IC's non-overlapping subsample - unused by binary heads). Shared by
# train_multitask.py/train_sequence.py - both trainers' Horizons model
# variants expose identically-named heads (see
# AetherNetMultiTaskHorizons/AetherNetSequenceMultiTaskHorizons docstrings).
HORIZON_HEAD_SPECS = {
    "direction_5d": ("target_direction_5d", "binary", None),
    "direction_20d": ("target_direction_20d", "binary", None),
    "rank_5d": ("target_rank_5d", "rank", 5),
    "rank_20d": ("target_rank_20d", "rank", 20),
    # Phase 5 of the 5/10 -> 9/10 roadmap - a "rank"-kind head like rank_20d,
    # so it automatically gets the exact same masked-MSE loss, rank-IC
    # metrics, AND assess_ranking_quality_from_predictions() promotion-gate
    # assessment as rank_20d, with zero extra wiring beyond this entry -
    # every consumer of HORIZON_HEAD_SPECS (compute_combined_multitask_loss(),
    # compute_multitask_metrics()/compute_sequence_multitask_metrics()) is
    # already fully generic over this dict.
    "sector_neutral_rank_20d": ("target_sector_neutral_rank_20d", "rank", 20),
}
DEFAULT_HORIZON_HEAD_CONFIG = {
    "direction_5d": {"enabled": True, "loss_weight": 1.0},
    "direction_20d": {"enabled": True, "loss_weight": 0.5},
    "rank_5d": {"enabled": True, "loss_weight": 1.0},
    "rank_20d": {"enabled": True, "loss_weight": 0.5},
    # Lighter weight than rank_20d - the newest, least-validated head;
    # doesn't dominate training until its own promotion criteria clear.
    "sector_neutral_rank_20d": {"enabled": True, "loss_weight": 0.3},
}


def resolve_horizon_head_config(training_config: dict) -> dict:
    """Merges a trainer's own config.json horizon_heads block (e.g.
    phase_v2.retraining.multitask_training.horizon_heads or
    ...sequence_training.horizon_heads) over DEFAULT_HORIZON_HEAD_CONFIG -
    an older config missing this key entirely (or missing one head's
    entry) still gets sane defaults for every head, rather than silently
    treating an absent head as disabled."""
    configured = training_config.get("horizon_heads", {})
    resolved = {}
    for head_name, defaults in DEFAULT_HORIZON_HEAD_CONFIG.items():
        head_config = {**defaults, **configured.get(head_name, {})}
        resolved[head_name] = head_config
    return resolved


def compute_combined_multitask_loss(
    outputs: dict[str, torch.Tensor],
    targets: dict[str, torch.Tensor],
    direction_criterion: nn.Module,
    magnitude_loss_weight: float,
    volatility_loss_weight: float,
    horizon_head_config: dict,
) -> torch.Tensor:
    """Combined loss for both AetherNetMultiTaskHorizons and
    AetherNetSequenceMultiTaskHorizons (identical head-name dict shape,
    see each class's forward()) - BCEWithLogitsLoss(direction) + weighted
    MSE(magnitude)/MSE(volatility) + a masked BCE/MSE term per enabled
    horizon head (masked since direction_5d/20d/rank_5d/20d are NaN for
    the trailing few rows of an asset's history that lack a full forward
    window, see engineer_features()'s docstring)."""
    loss = (
        direction_criterion(outputs["direction"], targets["direction"])
        + magnitude_loss_weight * nn.functional.mse_loss(outputs["magnitude"], targets["magnitude"])
        + volatility_loss_weight * nn.functional.mse_loss(outputs["volatility"], targets["volatility"])
    )
    for head_name, (_column, kind, _stride) in HORIZON_HEAD_SPECS.items():
        head_config = horizon_head_config[head_name]
        if not head_config.get("enabled", True):
            continue
        mask = ~torch.isnan(targets[head_name])
        head_loss = (
            masked_bce_with_logits_loss(outputs[head_name], targets[head_name], mask)
            if kind == "binary"
            else masked_mse_loss(outputs[head_name], targets[head_name], mask)
        )
        loss = loss + float(head_config.get("loss_weight", 1.0)) * head_loss
    return loss


def export_state_dict(model: nn.Module) -> dict:
    exported = {}
    for key, value in model.state_dict().items():
        exported[key] = value.detach().cpu().tolist()
    return exported


def _export_sequential_layers(sequential_module: nn.Sequential, key_prefix: str) -> list[dict]:
    """Per-layer export walk shared by export_architecture() (prefix
    "network") and export_multitask_architecture()'s trunk (prefix "trunk")
    below - extracted verbatim from the original export_architecture() body,
    a behavior-preserving refactor (same dict shapes, same key naming)."""
    architecture: list[dict] = []
    for index, module in enumerate(sequential_module):
        if isinstance(module, nn.Linear):
            architecture.append(
                {
                    "type": "linear",
                    "weight_key": f"{key_prefix}.{index}.weight",
                    "bias_key": f"{key_prefix}.{index}.bias",
                    "in_features": module.in_features,
                    "out_features": module.out_features,
                }
            )
        elif isinstance(module, nn.LayerNorm):
            architecture.append(
                {
                    "type": "layernorm",
                    "weight_key": f"{key_prefix}.{index}.weight",
                    "bias_key": f"{key_prefix}.{index}.bias",
                    "normalized_shape": list(module.normalized_shape),
                    "eps": module.eps,
                }
            )
        elif isinstance(module, nn.BatchNorm1d):
            architecture.append(
                {
                    "type": "batchnorm1d",
                    "weight_key": f"{key_prefix}.{index}.weight",
                    "bias_key": f"{key_prefix}.{index}.bias",
                    "running_mean_key": f"{key_prefix}.{index}.running_mean",
                    "running_var_key": f"{key_prefix}.{index}.running_var",
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
    return architecture


def export_architecture(model: AetherNet) -> list[dict]:
    architecture = _export_sequential_layers(model.network, "network")
    architecture.append({"type": "sigmoid"})
    return architecture


def _export_head(module: nn.Linear, key_prefix: str, final_activation: str | None) -> list[dict]:
    """A single head's export: one Linear layer plus its final activation
    (or none, for the raw-regression magnitude head). Heads are
    deliberately restricted to a single Linear - inference/exported_model.py::
    run_exported_multitask_model() and AetherNetMultiTask both assume this
    shape; a deeper head would need matching changes in both places."""
    head: list[dict] = [
        {
            "type": "linear",
            "weight_key": f"{key_prefix}.weight",
            "bias_key": f"{key_prefix}.bias",
            "in_features": module.in_features,
            "out_features": module.out_features,
        }
    ]
    if final_activation is not None:
        head.append({"type": final_activation})
    return head


def export_multitask_architecture(model: AetherNetMultiTask) -> dict:
    """Branching export for AetherNetMultiTask - a {"trunk": [...], "heads":
    {"direction": [...], "magnitude": [...], "volatility": [...]}} structure
    instead of export_architecture()'s single flat list. Consumed by
    inference/exported_model.py::run_exported_multitask_model(), never by
    run_exported_model() (which only understands a flat "architecture" list
    and would KeyError on this shape - the two exports are not
    interchangeable, matching the two different interpreter entry points)."""
    return {
        "trunk": _export_sequential_layers(model.trunk, "trunk"),
        "heads": {
            "direction": _export_head(model.head_direction, "head_direction", "sigmoid"),
            "magnitude": _export_head(model.head_magnitude, "head_magnitude", None),
            "volatility": _export_head(model.head_volatility, "head_volatility", "softplus"),
        },
    }


def export_multitask_horizons_architecture(model: AetherNetMultiTaskHorizons) -> dict:
    """Branching export for AetherNetMultiTaskHorizons - same {"trunk",
    "heads"} shape export_multitask_architecture() produces for the
    original 3-head model, extended with 4 more head entries (direction_5d/
    20d, rank_5d/20d). inference/exported_model.py::run_exported_multitask_model()
    already iterates export["heads"] generically, so no interpreter change
    is needed to support the extra heads."""
    return {
        "trunk": _export_sequential_layers(model.trunk, "trunk"),
        "heads": {
            "direction": _export_head(model.head_direction, "head_direction", "sigmoid"),
            "magnitude": _export_head(model.head_magnitude, "head_magnitude", None),
            "volatility": _export_head(model.head_volatility, "head_volatility", "softplus"),
            "direction_5d": _export_head(model.head_direction_5d, "head_direction_5d", "sigmoid"),
            "direction_20d": _export_head(model.head_direction_20d, "head_direction_20d", "sigmoid"),
            "rank_5d": _export_head(model.head_rank_5d, "head_rank_5d", "sigmoid"),
            "rank_20d": _export_head(model.head_rank_20d, "head_rank_20d", "sigmoid"),
            "sector_neutral_rank_20d": _export_head(
                model.head_sector_neutral_rank_20d, "head_sector_neutral_rank_20d", "sigmoid"
            ),
        },
    }


def train_model(
    config: dict,
    dataset: pd.DataFrame,
    *,
    checkpoint_path: Path = MODEL_CHECKPOINT_PATH,
    metrics_path: Path = TRAINING_METRICS_PATH,
    strategy_report_path: Path = STRATEGY_REPORT_PATH,
    equity_curves_path: Path = EQUITY_CURVES_PATH,
) -> dict:
    """Trains the baseline model and writes its artifacts.

    Output paths default to the active ml//backtests locations so every
    existing call site is unaffected; candidate training (V2-17) passes
    ml/versions/<id>/... paths instead, keeping the active model untouched.
    """
    phase3 = config["phase3"]
    training_config = phase3["training"]
    model_config = phase3["model"]
    feature_names = [f"{name}_scaled" for name in config["phase1"]["features"]["input_set"]]
    feature_names += _categorical_feature_names(dataset)
    if bool(model_config.get("use_asset_context", False)):
        feature_names += select_model_context_columns(dataset.columns)

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
    best_validation_balanced_accuracy = float("-inf")
    epochs_without_improvement = 0
    history: list[dict] = []
    min_best_epoch = int(training_config.get("min_best_epoch", 3))

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

        # Monitors validation balanced-accuracy (a skill metric), not raw
        # loss - see is_new_best_epoch()'s docstring for why (Problems.md:
        # loss-monitoring shipped best_epoch=1, essentially the untrained
        # initialization, for baseline/multitask/sequence alike).
        if is_new_best_epoch(validation_metrics["balanced_accuracy"], best_validation_balanced_accuracy, epoch, min_best_epoch):
            best_validation_balanced_accuracy = validation_metrics["balanced_accuracy"]
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
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, checkpoint_path)

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
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    strategy_report, equity_curves = build_strategy_report(
        config=config,
        model=model,
        dataset=training_dataset,
        feature_names=feature_names,
        threshold=tuned_threshold,
        device=device,
    )
    strategy_report_path.parent.mkdir(parents=True, exist_ok=True)
    strategy_report_path.write_text(json.dumps(strategy_report, indent=2), encoding="utf-8")
    equity_curves.to_csv(equity_curves_path, index=False)

    return {
        "model": model,
        "metrics": metrics,
        "strategy_report": strategy_report,
        "scaled_feature_names": feature_names,
        "threshold": tuned_threshold,
        "model_config": model_config,
        "training_config": training_config,
    }


def _feature_names_for_model(config: dict, dataset: pd.DataFrame) -> list[str]:
    model_config = config["phase3"]["model"]
    feature_names = [f"{name}_scaled" for name in config["phase1"]["features"]["input_set"]]
    feature_names += _categorical_feature_names(dataset)
    if bool(model_config.get("use_asset_context", False)):
        feature_names += select_model_context_columns(dataset.columns)
    return feature_names


def _expert_training_config(config: dict) -> tuple[dict, dict]:
    expert_config = config.get("phase_v2", {}).get("expert_models", {})
    model_config = copy.deepcopy(config["phase3"]["model"])
    model_config["hidden_layers"] = [24]
    model_config["dropout"] = 0.30
    model_config["normalization"] = "layernorm"
    model_config.update(expert_config.get("model", {}))

    training_config = copy.deepcopy(config["phase3"]["training"])
    training_config["epochs"] = min(int(training_config.get("epochs", 120)), 60)
    training_config["patience"] = min(int(training_config.get("patience", 18)), 8)
    training_config["weight_decay"] = max(float(training_config.get("weight_decay", 0.0)), 0.001)
    training_config["learning_rate"] = min(float(training_config.get("learning_rate", 0.0007)), 0.0005)
    training_overrides = expert_config.get("training", {})
    training_config.update(training_overrides)
    training_config["epochs"] = int(training_config.get("epochs", 60))
    training_config["patience"] = int(training_config.get("patience", 8))
    training_config["min_train_rows"] = int(training_overrides.get("min_train_rows", 50))
    training_config["min_validation_rows"] = int(training_overrides.get("min_validation_rows", 10))
    training_config["min_backtest_rows"] = int(training_overrides.get("min_backtest_rows", 10))
    training_config["quality_gate"] = {
        # Raised to coin-flip-or-better (development/Problems.md): these
        # used to default BELOW random (0.48 balanced-accuracy, -0.05 MCC),
        # so every expert this codebase ever trained cleared the gate
        # automatically regardless of whether it had learned anything -
        # confirmed live, every shipped expert's validation MCC was 0.02-0.11
        # and still passed. moe/gating.py's _performance_score() applies the
        # matching 0.0-below-coin-flip floor at inference time; this is the
        # training-time gate that should have caught it first.
        "min_validation_balanced_accuracy": float(training_overrides.get("min_validation_balanced_accuracy", 0.50)),
        "min_backtest_balanced_accuracy": float(training_overrides.get("min_backtest_balanced_accuracy", 0.50)),
        "min_backtest_mcc": float(training_overrides.get("min_backtest_mcc", 0.0)),
        "max_train_backtest_balanced_accuracy_gap": float(
            training_overrides.get("max_train_backtest_balanced_accuracy_gap", 0.20)
        ),
        "watchlist_margin": float(training_overrides.get("watchlist_margin", 0.03)),
    }
    return model_config, training_config


def assess_expert_quality(metrics: dict, training_config: dict) -> dict:
    gate = training_config.get("quality_gate", {})
    min_validation_balanced_accuracy = float(gate.get("min_validation_balanced_accuracy", 0.50))
    min_backtest_balanced_accuracy = float(gate.get("min_backtest_balanced_accuracy", 0.50))
    min_backtest_mcc = float(gate.get("min_backtest_mcc", 0.0))
    max_gap = float(gate.get("max_train_backtest_balanced_accuracy_gap", 0.20))
    watchlist_margin = float(gate.get("watchlist_margin", 0.03))

    train_balanced_accuracy = float(metrics.get("train", {}).get("balanced_accuracy", 0.0) or 0.0)
    validation_balanced_accuracy = float(metrics.get("validation", {}).get("balanced_accuracy", 0.0) or 0.0)
    backtest_balanced_accuracy = float(metrics.get("backtest", {}).get("balanced_accuracy", 0.0) or 0.0)
    backtest_mcc = float(metrics.get("backtest", {}).get("mcc", 0.0) or 0.0)
    train_backtest_gap = train_balanced_accuracy - backtest_balanced_accuracy

    failures = []
    near_misses = []
    if validation_balanced_accuracy < min_validation_balanced_accuracy:
        failures.append("validation_balanced_accuracy_below_gate")
    elif validation_balanced_accuracy < min_validation_balanced_accuracy + watchlist_margin:
        near_misses.append("validation_balanced_accuracy_near_gate")

    if backtest_balanced_accuracy < min_backtest_balanced_accuracy:
        failures.append("backtest_balanced_accuracy_below_gate")
    elif backtest_balanced_accuracy < min_backtest_balanced_accuracy + watchlist_margin:
        near_misses.append("backtest_balanced_accuracy_near_gate")

    if backtest_mcc < min_backtest_mcc:
        failures.append("backtest_mcc_below_gate")
    elif backtest_mcc < min_backtest_mcc + watchlist_margin:
        near_misses.append("backtest_mcc_near_gate")

    if train_backtest_gap > max_gap:
        failures.append("train_backtest_gap_too_large")
    elif train_backtest_gap > max_gap - watchlist_margin:
        near_misses.append("train_backtest_gap_near_limit")

    if failures:
        quality_status = "disabled_for_gating"
    elif near_misses:
        quality_status = "watchlist"
    else:
        quality_status = "stable"

    return {
        "quality_status": quality_status,
        "gating_eligible": quality_status in {"stable", "watchlist"},
        "failures": failures,
        "near_misses": near_misses,
        "thresholds": {
            "min_validation_balanced_accuracy": min_validation_balanced_accuracy,
            "min_backtest_balanced_accuracy": min_backtest_balanced_accuracy,
            "min_backtest_mcc": min_backtest_mcc,
            "max_train_backtest_balanced_accuracy_gap": max_gap,
            "watchlist_margin": watchlist_margin,
        },
        "observed": {
            "train_balanced_accuracy": train_balanced_accuracy,
            "validation_balanced_accuracy": validation_balanced_accuracy,
            "backtest_balanced_accuracy": backtest_balanced_accuracy,
            "backtest_mcc": backtest_mcc,
            "train_backtest_balanced_accuracy_gap": train_backtest_gap,
        },
    }


def assess_regression_quality(regression_metrics_by_split: dict, training_config: dict) -> dict:
    """Direction models get assess_expert_quality()'s MCC/balanced-accuracy
    gate above; magnitude/volatility regression heads (train_multitask.py,
    train_sequence.py) had no equivalent gate at all until now - the
    sequence encoder's real backtest RMSE 2.09 vs MAE 0.068 (~31x, every
    other model's ratio is ~1.5-3x) shipped silently because nothing ever
    inspected it (root cause: a single poisoned feature row replicated
    into 30 consecutive sliding-window predictions - see
    development/Problems.md). Mirrors assess_expert_quality()'s
    failures/near_misses/quality_status shape so callers can treat both
    gates the same way.

    regression_metrics_by_split must be {"train": {...}, "validation":
    {...}, "backtest": {...}}, each a compute_regression_metrics() output
    (mae/rmse/bias/...) for ONE head (magnitude or volatility) - callers
    with multiple heads call this once per head.
    """
    gate = training_config.get("quality_gate", {})
    max_rmse_mae_ratio = float(gate.get("max_rmse_mae_ratio", 4.0))
    max_backtest_train_rmse_ratio = float(gate.get("max_backtest_train_rmse_ratio", 3.0))
    watchlist_margin = float(gate.get("regression_watchlist_margin", 0.5))

    train_rmse = float(regression_metrics_by_split.get("train", {}).get("rmse", 0.0) or 0.0)
    backtest_rmse = float(regression_metrics_by_split.get("backtest", {}).get("rmse", 0.0) or 0.0)
    backtest_mae = float(regression_metrics_by_split.get("backtest", {}).get("mae", 0.0) or 0.0)

    # A zero-valued denominator means "can't compute" (e.g. an empty
    # split), not "infinitely bad" - ratio stays 0.0 so it's never
    # spuriously flagged as a gate failure.
    rmse_mae_ratio = backtest_rmse / backtest_mae if backtest_mae > 0 else 0.0
    backtest_train_rmse_ratio = backtest_rmse / train_rmse if train_rmse > 0 else 0.0

    failures = []
    near_misses = []
    if rmse_mae_ratio > max_rmse_mae_ratio:
        failures.append("rmse_mae_ratio_above_gate")
    elif rmse_mae_ratio > max_rmse_mae_ratio - watchlist_margin:
        near_misses.append("rmse_mae_ratio_near_gate")

    if backtest_train_rmse_ratio > max_backtest_train_rmse_ratio:
        failures.append("backtest_train_rmse_ratio_above_gate")
    elif backtest_train_rmse_ratio > max_backtest_train_rmse_ratio - watchlist_margin:
        near_misses.append("backtest_train_rmse_ratio_near_gate")

    if failures:
        quality_status = "disabled_for_gating"
    elif near_misses:
        quality_status = "watchlist"
    else:
        quality_status = "stable"

    return {
        "quality_status": quality_status,
        "gating_eligible": quality_status in {"stable", "watchlist"},
        "failures": failures,
        "near_misses": near_misses,
        "thresholds": {
            "max_rmse_mae_ratio": max_rmse_mae_ratio,
            "max_backtest_train_rmse_ratio": max_backtest_train_rmse_ratio,
            "watchlist_margin": watchlist_margin,
        },
        "observed": {
            "backtest_rmse_mae_ratio": rmse_mae_ratio,
            "backtest_train_rmse_ratio": backtest_train_rmse_ratio,
            "train_rmse": train_rmse,
            "backtest_rmse": backtest_rmse,
            "backtest_mae": backtest_mae,
        },
    }


def assess_ranking_quality(
    non_overlapping_rank_ic: dict,
    bootstrap_result: dict,
    per_era_mean_ics: list[float],
    training_config: dict,
) -> dict:
    """Phase 2 of the 5/10 -> 9/10 roadmap: the code-enforced version of
    the promotion criterion this codebase's own prior investigation
    documented but never actually implemented in code (see
    development/Changelog.md's "frontier-model edge investigation" entry:
    "promote when backtest mean rank-IC > 0.02, t-stat > 2, on
    non-overlapping dates" - and risk/README.md's rank_sizing_multiplier()
    docstring, which explains why rank_sizing_enabled shipped off by
    default: the non-overlapping subsample's t-stat was only 1.20, not the
    4.40 the full autocorrelated series showed). Mirrors
    assess_regression_quality()'s failures/near_misses/quality_status shape
    so callers can treat every quality gate in this codebase the same way.

    Callers compute each input via the already-existing building blocks
    rather than this function re-deriving them:
    - `non_overlapping_rank_ic`: a compute_rank_ic() result computed WITH
      non_overlapping_stride > 1 (the honest, non-autocorrelated series -
      never pass the full daily series here, that's exactly the inflated
      number this gate exists to not be fooled by).
    - `bootstrap_result`: bootstrap_ic_confidence_interval() run over that
      SAME non-overlapping series' "ic_values".
    - `per_era_mean_ics`: one compute_rank_ic()["mean_ic"] per era from
      split_into_non_overlapping_eras() - was the edge concentrated in one
      regime, or stable? Even a single era whose sign contradicts the
      overall aggregate disqualifies promotion, regardless of how strong
      the aggregate looks - a real edge should not require throwing away
      an inconvenient era.
    """
    gate = training_config.get("phase1", {}).get("target", {}).get("ranking", {}).get("promotion_gate", {})
    min_non_overlapping_t_stat = float(gate.get("min_non_overlapping_t_stat", 2.0))
    min_bootstrap_ci_lower = float(gate.get("min_bootstrap_ci_lower", 0.0))
    watchlist_margin = float(gate.get("ranking_watchlist_margin", 0.3))

    non_overlapping_t_stat = float(non_overlapping_rank_ic.get("t_stat", 0.0) or 0.0)
    non_overlapping_mean_ic = float(non_overlapping_rank_ic.get("mean_ic", 0.0) or 0.0)
    bootstrap_lower_bound = float(bootstrap_result.get("lower_bound", 0.0) or 0.0)

    opposite_sign_eras = [
        era_ic
        for era_ic in per_era_mean_ics
        if (non_overlapping_mean_ic > 0 and era_ic < 0) or (non_overlapping_mean_ic < 0 and era_ic > 0)
    ]

    failures = []
    near_misses = []
    if non_overlapping_t_stat < min_non_overlapping_t_stat:
        failures.append("non_overlapping_t_stat_below_gate")
    elif non_overlapping_t_stat < min_non_overlapping_t_stat + watchlist_margin:
        near_misses.append("non_overlapping_t_stat_near_gate")

    if bootstrap_lower_bound < min_bootstrap_ci_lower:
        failures.append("bootstrap_ci_lower_bound_below_gate")

    if opposite_sign_eras:
        failures.append("era_sign_instability")

    if failures:
        quality_status = "not_promotable"
    elif near_misses:
        quality_status = "watchlist"
    else:
        quality_status = "promotable"

    return {
        "quality_status": quality_status,
        # Matches assess_regression_quality()'s "gating_eligible" convention:
        # "watchlist" (a near-miss, not an outright failure) still counts as
        # eligible, same treatment every other quality gate in this codebase
        # gives a near-gate-but-passing result.
        "promotion_eligible": quality_status in {"promotable", "watchlist"},
        "failures": failures,
        "near_misses": near_misses,
        "thresholds": {
            "min_non_overlapping_t_stat": min_non_overlapping_t_stat,
            "min_bootstrap_ci_lower": min_bootstrap_ci_lower,
            "watchlist_margin": watchlist_margin,
        },
        "observed": {
            "non_overlapping_t_stat": non_overlapping_t_stat,
            "non_overlapping_mean_ic": non_overlapping_mean_ic,
            "bootstrap_ci_lower_bound": bootstrap_lower_bound,
            "bootstrap_ci_upper_bound": float(bootstrap_result.get("upper_bound", 0.0) or 0.0),
            "num_eras": len(per_era_mean_ics),
            "num_opposite_sign_eras": len(opposite_sign_eras),
        },
    }


def assess_ranking_quality_from_predictions(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    dates,
    non_overlapping_stride: int,
    config: dict,
) -> dict:
    """Phase 2 of the 5/10 -> 9/10 roadmap: orchestrates
    compute_rank_ic()/bootstrap_ic_confidence_interval()/
    split_into_non_overlapping_eras()/assess_ranking_quality() into one
    call, so train_multitask.py/train_sequence.py's main() gets the full
    promotion-gate verdict for one rank head's BACKTEST split from a single
    call, the same way assess_regression_quality() is already called
    directly on an already-assembled metrics dict.

    Unlike assess_regression_quality() (which reads a narrow, per-model
    training_config), this reads `config` as the FULL config.json (same
    convention as build_cross_sectional_rank_targets()/
    build_macro_features_by_date() above) - the ranking promotion gate
    (phase1.target.ranking.promotion_gate) is a property of the ranking
    TARGET itself, not a per-model training hyperparameter, so it lives in
    one place shared by every model with a rank head, not duplicated under
    each model's own training config block.
    """
    non_overlapping_ic = compute_rank_ic(predictions, targets, dates, non_overlapping_stride=non_overlapping_stride)
    bootstrap_result = bootstrap_ic_confidence_interval(non_overlapping_ic["ic_values"])

    promotion_gate_config = config.get("phase1", {}).get("target", {}).get("ranking", {}).get("promotion_gate", {})
    era_length_days = int(promotion_gate_config.get("era_length_days", 90))

    # pd.to_datetime(), not np.asarray(): `dates` here is a plain string
    # array in every real caller (train_multitask.py/train_sequence.py
    # pass frame["date"], stringified by build_feature_dataset() before
    # any trainer reads it) - comparing raw strings against
    # split_into_non_overlapping_eras()'s Timestamp era boundaries below
    # would raise. See that function's own identical fix/comment.
    dates_array = pd.to_datetime(np.asarray(dates))
    per_era_mean_ics: list[float] = []
    for era_start, era_end in split_into_non_overlapping_eras(dates_array, era_length_days):
        era_mask = (dates_array >= era_start) & (dates_array <= era_end)
        if not era_mask.any():
            continue
        era_mask_tensor = torch.as_tensor(era_mask)
        era_result = compute_rank_ic(
            predictions[era_mask_tensor],
            targets[era_mask_tensor],
            dates_array[era_mask],
            non_overlapping_stride=non_overlapping_stride,
        )
        if era_result["num_dates"] > 0:
            per_era_mean_ics.append(era_result["mean_ic"])

    return assess_ranking_quality(non_overlapping_ic, bootstrap_result, per_era_mean_ics, config)


def generate_walk_forward_windows(
    common_window: dict,
    train_span_days: int,
    validation_span_days: int,
    backtest_span_days: int,
    step_days: int,
    mode: str = "rolling",
) -> list[dict]:
    """Phase 4 of the 5/10 -> 9/10 roadmap: generates a sequence of
    {"training": {...}, "validation": {...}, "backtest": {...}} window
    dicts spanning `common_window` - each one has the EXACT shape of
    today's single phase1.windows, so every existing consumer
    (assign_split(), build_feature_dataset(), build_dataset_manifest())
    needs zero changes to accept a walk-forward window instead of the
    fixed one. Walk-forward is achieved by calling the existing pipeline
    once per generated window, not by changing what "a window" means.

    `mode="rolling"`: a fixed-length training window slides forward by
    `step_days` each iteration (window i's train_start = common_window's
    start + i*step_days). `mode="expanding"`: the training window's start
    stays fixed at common_window's start and only its END grows by
    step_days each iteration (train_end = start + train_span_days - 1 +
    i*step_days) - each window sees strictly more history than the last,
    never less.

    Validation and backtest immediately follow training with no gap
    (validation_start = train_end + 1 day, etc.) and never overlap between
    consecutive windows' training data and a later window's backtest data
    within the SAME window - each window's own three sub-ranges are
    contiguous and disjoint by construction.

    Returns [] (never raises) once a window's backtest_end would exceed
    common_window's end - including immediately, on the very first
    iteration, if `common_window` is too short for even one full window to
    fit. This is the same "guard against thin data" convention
    build_cross_sectional_rank_targets()'s min_universe_size gate and
    every other thin-data guard in this file already follow.
    """
    range_start = pd.Timestamp(common_window["start"])
    range_end = pd.Timestamp(common_window["end"])

    windows: list[dict] = []
    index = 0
    while True:
        if mode == "expanding":
            train_start = range_start
            train_end = range_start + pd.Timedelta(days=train_span_days - 1 + step_days * index)
        else:
            train_start = range_start + pd.Timedelta(days=step_days * index)
            train_end = train_start + pd.Timedelta(days=train_span_days - 1)

        validation_start = train_end + pd.Timedelta(days=1)
        validation_end = validation_start + pd.Timedelta(days=validation_span_days - 1)
        backtest_start = validation_end + pd.Timedelta(days=1)
        backtest_end = backtest_start + pd.Timedelta(days=backtest_span_days - 1)

        if backtest_end > range_end:
            break

        windows.append(
            {
                "training": {"start": train_start.strftime("%Y-%m-%d"), "end": train_end.strftime("%Y-%m-%d")},
                "validation": {
                    "start": validation_start.strftime("%Y-%m-%d"),
                    "end": validation_end.strftime("%Y-%m-%d"),
                },
                "backtest": {"start": backtest_start.strftime("%Y-%m-%d"), "end": backtest_end.strftime("%Y-%m-%d")},
            }
        )
        index += 1

    return windows


def summarize_walk_forward_run(per_window_metric_values: list[float]) -> dict:
    """Phase 4 of the 5/10 -> 9/10 roadmap: cross-window stability summary
    for a walk-forward run - turns a single "trained once on one fixed
    window" number into a distribution across windows (was performance
    concentrated in one window, or stable across the whole walk-forward
    run?), the direct generalization of Phase 2's "single non-overlapping
    IC number" -> "distribution across eras" upgrade
    (split_into_non_overlapping_eras()/assess_ranking_quality()) applied
    one level up, across whole retrain windows instead of within one.

    Deliberately takes a plain `list[float]` (whatever numeric metric the
    caller cares about per window - rank-IC mean, MCC, Sharpe - already
    extracted from that window's own training_metrics.json) rather than
    assuming any particular metrics-JSON shape, so this composes with any
    current or future trainer's own metrics without modification. Reuses
    bootstrap_ic_confidence_interval() for the cross-window confidence
    interval rather than reimplementing the same bootstrap logic - despite
    the "_ic" in that function's name, it is a plain bootstrap-mean-CI over
    any float series, not IC-specific in what it actually computes.
    """
    bootstrap_result = bootstrap_ic_confidence_interval(per_window_metric_values)
    return {
        "num_windows": len(per_window_metric_values),
        "per_window_metric_values": list(per_window_metric_values),
        "cross_window_bootstrap": bootstrap_result,
    }


def _train_expert_classifier(
    expert_name: str,
    expert_frame: pd.DataFrame,
    feature_names: list[str],
    model_config: dict,
    training_config: dict,
    device: torch.device,
) -> dict:
    train_frame = split_frame(expert_frame, "train")
    validation_frame = split_frame(expert_frame, "validation")
    backtest_frame = split_frame(expert_frame, "backtest")

    min_train_rows = int(training_config.get("min_train_rows", 50))
    min_validation_rows = int(training_config.get("min_validation_rows", 10))
    min_backtest_rows = int(training_config.get("min_backtest_rows", 10))
    if len(train_frame) < min_train_rows or len(validation_frame) < min_validation_rows or len(backtest_frame) < min_backtest_rows:
        return {
            "expert": expert_name,
            "status": "skipped",
            "reason": "not_enough_rows_for_expert_training",
            "rows": int(len(expert_frame)),
            "split_rows": {
                "train": int(len(train_frame)),
                "validation": int(len(validation_frame)),
                "backtest": int(len(backtest_frame)),
            },
            "minimums": {
                "train": min_train_rows,
                "validation": min_validation_rows,
                "backtest": min_backtest_rows,
            },
        }

    seed = int(training_config["seed"]) + sum(ord(character) for character in expert_name)
    set_seed(seed)

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
    threshold_metric = str(training_config.get("optimize_threshold_metric", "f1"))
    threshold_min = float(training_config.get("threshold_search_min", 0.35))
    threshold_max = float(training_config.get("threshold_search_max", 0.65))
    threshold_steps = int(training_config.get("threshold_search_steps", 61))
    max_epochs = int(training_config["epochs"])
    patience = int(training_config["patience"])

    best_state = None
    best_epoch = 0
    best_validation_balanced_accuracy = float("-inf")
    epochs_without_improvement = 0
    history: list[dict] = []
    min_best_epoch = int(training_config.get("min_best_epoch", 3))

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

        model.eval()
        with torch.no_grad():
            validation_logits = model(validation_features)
        validation_metrics = compute_binary_metrics(validation_logits, validation_targets, criterion, threshold)
        train_epoch_loss = running_loss / max(sample_count, 1)
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

        if is_new_best_epoch(validation_metrics["balanced_accuracy"], best_validation_balanced_accuracy, epoch, min_best_epoch):
            best_validation_balanced_accuracy = validation_metrics["balanced_accuracy"]
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
        "expert": expert_name,
        "status": "trained",
        "rows": int(len(expert_frame)),
        "split_rows": {
            "train": int(len(train_frame)),
            "validation": int(len(validation_frame)),
            "backtest": int(len(backtest_frame)),
        },
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
        "tickers": sorted(expert_frame["ticker"].unique().tolist()) if "ticker" in expert_frame.columns else [],
        "history": history,
    }
    metrics["quality_gate"] = assess_expert_quality(metrics, training_config)
    return {
        "expert": expert_name,
        "status": "trained",
        "quality_status": metrics["quality_gate"]["quality_status"],
        "gating_eligible": metrics["quality_gate"]["gating_eligible"],
        "model": model,
        "state_dict": best_state,
        "threshold": tuned_threshold,
        "metrics": metrics,
    }


def _write_expert_model_export(
    expert_name: str,
    result: dict,
    model_config: dict,
    training_config: dict,
    feature_names: list[str],
    output_dir: Path,
) -> dict:
    def artifact_path(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    expert_dir = output_dir / expert_name
    expert_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = expert_dir / "model.pt"
    weights_path = expert_dir / "model_weights.json"
    metrics_path = expert_dir / "metrics.json"

    torch.save(result["state_dict"], checkpoint_path)
    metrics_path.write_text(json.dumps(result["metrics"], indent=2), encoding="utf-8")
    payload = {
        "project": "Aether Quant",
        "phase": "v2_expert_model",
        "expert": expert_name,
        "status": "trained",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "type": model_config["type"],
            "model_input_features": feature_names,
            "hidden_layers": model_config["hidden_layers"],
            "dropout": model_config["dropout"],
            "activation": model_config.get("activation", "relu"),
            "normalization": model_config.get("normalization", "none"),
            "use_asset_context": model_config.get("use_asset_context", False),
            "output_activation": model_config.get("output_activation", "sigmoid"),
        },
        "training": {
            "decision_threshold": result["threshold"],
            "threshold_metric": training_config.get("optimize_threshold_metric", "f1"),
            "best_epoch": result["metrics"]["best_epoch"],
            "epochs_ran": result["metrics"]["epochs_ran"],
            "quality_status": result["metrics"]["quality_gate"]["quality_status"],
            "gating_eligible": result["metrics"]["quality_gate"]["gating_eligible"],
        },
        "quality_gate": result["metrics"]["quality_gate"],
        "metrics_path": artifact_path(metrics_path),
        "checkpoint_path": artifact_path(checkpoint_path),
        "export": {
            "architecture": export_architecture(result["model"]),
            "state_dict": export_state_dict(result["model"]),
        },
    }
    weights_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "weights_path": artifact_path(weights_path),
        "metrics_path": artifact_path(metrics_path),
        "checkpoint_path": artifact_path(checkpoint_path),
    }


def _expert_multitask_tensors(
    frame: pd.DataFrame, feature_names: list[str]
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    features = torch.tensor(frame[feature_names].to_numpy(dtype=np.float32), dtype=torch.float32)
    direction = torch.tensor(frame["target_direction"].to_numpy(dtype=np.float32), dtype=torch.float32)
    magnitude = torch.tensor(frame["target_return_1d"].to_numpy(dtype=np.float32), dtype=torch.float32)
    volatility = torch.tensor(frame["target_volatility_next_day"].to_numpy(dtype=np.float32), dtype=torch.float32)
    return features, direction, magnitude, volatility


def _train_expert_multitask(
    expert_name: str,
    expert_frame: pd.DataFrame,
    feature_names: list[str],
    model_config: dict,
    training_config: dict,
    device: torch.device,
) -> dict:
    """Per-expert multitask (direction+magnitude+volatility) trainer -
    mirrors _train_expert_classifier()'s exact shape (split -> loader ->
    model -> Adam -> epoch loop with early stopping on validation loss ->
    best-state reload -> threshold tuning) but trains AetherNetMultiTask
    with the same combined BCE+MSE+MSE loss train_multitask.py's main()
    uses, over the SAME regime-filtered per-expert dataset slice
    _train_expert_classifier() already trains its direction-only
    classifier on. This is what lets moe/gating.py blend per-expert
    magnitude/volatility the same weighted-average way it already blends
    expert_probability_up (see moe/README.md's scope note on this)."""
    required_target_columns = {"target_return_1d", "target_volatility_next_day"}
    if not required_target_columns.issubset(expert_frame.columns):
        # Older/synthetic datasets (e.g. built before the multitask targets
        # existed, or hand-constructed test fixtures) simply don't have
        # these columns - best-effort skip, never a hard failure, matching
        # every other optional stage in this pipeline.
        return {
            "expert": expert_name,
            "status": "skipped",
            "reason": "dataset_missing_multitask_target_columns",
        }

    train_frame = split_frame(expert_frame, "train")
    validation_frame = split_frame(expert_frame, "validation")
    backtest_frame = split_frame(expert_frame, "backtest")

    min_train_rows = int(training_config.get("min_train_rows", 50))
    min_validation_rows = int(training_config.get("min_validation_rows", 10))
    min_backtest_rows = int(training_config.get("min_backtest_rows", 10))
    if len(train_frame) < min_train_rows or len(validation_frame) < min_validation_rows or len(backtest_frame) < min_backtest_rows:
        return {
            "expert": expert_name,
            "status": "skipped",
            "reason": "not_enough_rows_for_expert_multitask_training",
        }

    # +1 vs _train_expert_classifier()'s own seed formula, so the two
    # models' random initialization/batch shuffling are decorrelated
    # rather than accidentally identical.
    seed = int(training_config["seed"]) + sum(ord(character) for character in expert_name) + 1
    set_seed(seed)

    magnitude_loss_weight = float(training_config.get("magnitude_loss_weight", 1.0))
    volatility_loss_weight = float(training_config.get("volatility_loss_weight", 1.0))

    train_features, train_direction, train_magnitude, train_volatility = _expert_multitask_tensors(train_frame, feature_names)
    validation_features, validation_direction, validation_magnitude, validation_volatility = _expert_multitask_tensors(
        validation_frame, feature_names
    )
    validation_features = validation_features.to(device)
    validation_direction = validation_direction.to(device)
    validation_magnitude = validation_magnitude.to(device)
    validation_volatility = validation_volatility.to(device)

    train_loader = DataLoader(
        TensorDataset(train_features, train_direction, train_magnitude, train_volatility),
        batch_size=int(training_config["batch_size"]),
        shuffle=True,
    )

    model = AetherNetMultiTask(
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
    direction_criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    magnitude_criterion = nn.MSELoss()
    volatility_criterion = nn.MSELoss()

    threshold = float(training_config["decision_threshold"])
    threshold_metric = str(training_config.get("optimize_threshold_metric", "f1"))
    threshold_min = float(training_config.get("threshold_search_min", 0.35))
    threshold_max = float(training_config.get("threshold_search_max", 0.65))
    threshold_steps = int(training_config.get("threshold_search_steps", 61))
    max_epochs = int(training_config["epochs"])
    patience = int(training_config["patience"])

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
    tuned_threshold, tuned_validation_metrics = find_optimal_threshold(
        validation_direction_logits,
        validation_direction,
        direction_criterion,
        threshold_metric,
        threshold_min,
        threshold_max,
        threshold_steps,
    )

    def compute_split_metrics(features, direction, magnitude, volatility) -> dict:
        model.eval()
        with torch.no_grad():
            direction_logits, magnitude_predictions, volatility_predictions = model(features)
        return {
            "direction": compute_binary_metrics(direction_logits, direction, direction_criterion, tuned_threshold),
            "magnitude": compute_regression_metrics(magnitude_predictions, magnitude),
            "volatility": compute_regression_metrics(volatility_predictions, volatility),
        }

    backtest_features, backtest_direction, backtest_magnitude, backtest_volatility = _expert_multitask_tensors(
        backtest_frame, feature_names
    )
    backtest_features = backtest_features.to(device)
    backtest_direction = backtest_direction.to(device)
    backtest_magnitude = backtest_magnitude.to(device)
    backtest_volatility = backtest_volatility.to(device)

    metrics = {
        "expert": expert_name,
        "status": "trained",
        "rows": int(len(expert_frame)),
        "split_rows": {
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
            "default_threshold": threshold,
            "selected_threshold": tuned_threshold,
            "selected_validation_metrics": tuned_validation_metrics,
        },
        "train": compute_split_metrics(
            train_features.to(device), train_direction.to(device), train_magnitude.to(device), train_volatility.to(device)
        ),
        "validation": compute_split_metrics(validation_features, validation_direction, validation_magnitude, validation_volatility),
        "backtest": compute_split_metrics(backtest_features, backtest_direction, backtest_magnitude, backtest_volatility),
        "history": history,
    }
    return {
        "expert": expert_name,
        "status": "trained",
        "model": model,
        "threshold": tuned_threshold,
        "metrics": metrics,
    }


def _write_expert_multitask_export(
    expert_name: str,
    result: dict,
    model_config: dict,
    feature_names: list[str],
    output_dir: Path,
) -> dict:
    def artifact_path(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    expert_dir = output_dir / expert_name
    expert_dir.mkdir(parents=True, exist_ok=True)
    weights_path = expert_dir / "multitask_model.json"
    metrics_path = expert_dir / "multitask_training_metrics.json"

    metrics_path.write_text(json.dumps(result["metrics"], indent=2), encoding="utf-8")
    payload = {
        "project": "Aether Quant",
        "phase": "v2_expert_multitask_model",
        "expert": expert_name,
        "status": "trained",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "type": "multitask_direction_magnitude_volatility",
            "model_input_features": feature_names,
            "hidden_layers": model_config["hidden_layers"],
            "dropout": model_config["dropout"],
            "activation": model_config.get("activation", "relu"),
            "normalization": model_config.get("normalization", "none"),
            "decision_threshold": result["threshold"],
        },
        "export": export_multitask_architecture(result["model"]) | {"state_dict": export_state_dict(result["model"])},
    }
    weights_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "weights_path": artifact_path(weights_path),
        "metrics_path": artifact_path(metrics_path),
    }


def train_expert_models(
    config: dict,
    dataset: pd.DataFrame,
    dataset_manifest: dict,
    output_dir: Path = EXPERT_MODEL_DIR,
    metrics_path: Path = EXPERT_TRAINING_METRICS_PATH,
) -> dict:
    annotated_dataset, expert_dataset_manifest = build_expert_dataset_manifest(dataset, dataset_manifest, config)
    eligible = annotated_dataset
    if "training_eligible" in eligible.columns:
        eligible = eligible[eligible["training_eligible"]].copy()

    model_config, training_config = _expert_training_config(config)
    feature_names = _feature_names_for_model(config, annotated_dataset)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Per-expert multitask (direction+magnitude+volatility) training config -
    # reuses phase_v2.retraining.multitask_training's magnitude_loss_weight/
    # volatility_loss_weight (train_multitask.py's own config block) layered
    # onto the expert classifier's own training_config, so both loss weights
    # and the classifier's regularization/epoch/patience settings apply.
    multitask_overrides = config.get("phase_v2", {}).get("retraining", {}).get("multitask_training", {})
    expert_multitask_training_config = dict(training_config)
    expert_multitask_training_config["magnitude_loss_weight"] = float(multitask_overrides.get("magnitude_loss_weight", 1.0))
    expert_multitask_training_config["volatility_loss_weight"] = float(multitask_overrides.get("volatility_loss_weight", 1.0))

    summary = {
        "project": config["name"],
        "phase": "v2_expert_models_stabilized",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "device": str(device),
        "feature_names": feature_names,
        "model_config": model_config,
        "training_config": {
            key: value for key, value in training_config.items() if key != "seed"
        },
        "source_dataset_rows": int(len(dataset)),
        "eligible_dataset_rows": int(len(eligible)),
        "expert_dataset_manifest": expert_dataset_manifest,
        "experts": {},
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    for expert_name, expert_summary in expert_dataset_manifest["experts"].items():
        definition = EXPERT_DEFINITIONS[expert_name]
        expert_frame = eligible.copy()
        for column, allowed_values in definition["filter"].items():
            expert_frame = expert_frame[expert_frame[f"regime_{column}"].isin(allowed_values)].copy()

        result = _train_expert_classifier(
            expert_name,
            expert_frame,
            feature_names,
            model_config,
            training_config,
            device,
        )
        if result["status"] == "trained":
            artifacts = _write_expert_model_export(
                expert_name,
                result,
                model_config,
                training_config,
                feature_names,
                output_dir,
            )

            # Best-effort per-expert multitask head - a failure/skip here
            # never affects the classifier's own "trained" status above;
            # this only adds an optional multitask_model.json sibling file
            # moe/gating.py's per-expert magnitude/volatility blend
            # consumes when present (see moe/README.md).
            multitask_result = _train_expert_multitask(
                expert_name,
                expert_frame,
                feature_names,
                model_config,
                expert_multitask_training_config,
                device,
            )
            multitask_summary: dict = dict(multitask_result)
            multitask_summary.pop("model", None)
            if multitask_result["status"] == "trained":
                multitask_artifacts = _write_expert_multitask_export(
                    expert_name,
                    multitask_result,
                    model_config,
                    feature_names,
                    output_dir,
                )
                multitask_summary["artifacts"] = multitask_artifacts

            summary["experts"][expert_name] = {
                **result["metrics"],
                "description": expert_summary["description"],
                "artifacts": artifacts,
                "multitask": multitask_summary,
            }
        else:
            summary["experts"][expert_name] = {
                **result,
                "description": expert_summary["description"],
            }

    summary["trained_experts"] = [
        expert for expert, payload in summary["experts"].items() if payload.get("status") == "trained"
    ]
    summary["skipped_experts"] = [
        expert for expert, payload in summary["experts"].items() if payload.get("status") != "trained"
    ]
    summary["gating_eligible_experts"] = [
        expert for expert, payload in summary["experts"].items() if payload.get("quality_gate", {}).get("gating_eligible")
    ]
    summary["disabled_for_gating_experts"] = [
        expert
        for expert, payload in summary["experts"].items()
        if payload.get("status") == "trained" and not payload.get("quality_gate", {}).get("gating_eligible", False)
    ]
    summary["quality_status_counts"] = dict(
        Counter(
            payload.get("quality_gate", {}).get("quality_status", payload.get("status", "unknown"))
            for payload in summary["experts"].values()
        )
    )
    metrics_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def write_model_export(
    config: dict,
    data_summary: dict,
    dataset_manifest: dict | None = None,
    training_result: dict | None = None,
    *,
    weights_path: Path = MODEL_WEIGHTS_PATH,
    dataset_manifest_path: Path = DATASET_MANIFEST_PATH,
    scaler_path: Path = SCALER_PATH,
    scaler_stats_path: Path = SCALER_STATS_PATH,
    checkpoint_path: Path = MODEL_CHECKPOINT_PATH,
    metrics_path: Path = TRAINING_METRICS_PATH,
    strategy_report_path: Path = STRATEGY_REPORT_PATH,
) -> None:
    """Writes the Lean-readable model export.

    All *_path kwargs default to the active ml/ locations so every existing
    call site is unaffected; candidate training (V2-17) passes
    ml/versions/<id>/... paths so the export's own path fields describe the
    candidate, not the active model.
    """
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
        "dataset_manifest_path": str(dataset_manifest_path.relative_to(ROOT)) if dataset_manifest else None,
        "scaler_path": str(scaler_path.relative_to(ROOT)) if dataset_manifest else None,
        "scaler_stats_path": str(scaler_stats_path.relative_to(ROOT)) if dataset_manifest else None,
        "checkpoint_path": str(checkpoint_path.relative_to(ROOT)) if training_result else None,
        "metrics_path": str(metrics_path.relative_to(ROOT)) if training_result else None,
        "strategy_report_path": str(strategy_report_path.relative_to(ROOT)) if training_result else None,
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

    weights_path.parent.mkdir(parents=True, exist_ok=True)
    weights_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


def _run_walk_forward(config: dict, data_summary: dict, step_days: int, mode: str) -> dict:
    """Phase 4 of the 5/10 -> 9/10 roadmap: `python train.py --walk-forward`'s
    implementation - runs the baseline model's existing dataset-build +
    training pipeline once per generate_walk_forward_windows() window,
    writing each window to ml/versions/<run_id>/window_<i>/ (extends
    candidate_output_paths()'s directory convention: this deliberately
    duplicates the same handful of calls the `--candidate` branch below
    already makes, in a loop, rather than refactoring that already-tested
    branch to share code - zero regression risk to it as a result).

    Never touches active ml/ - same as --candidate. Returns a summary dict
    with per-window results and a summarize_walk_forward_run() cross-window
    stability readout over each window's backtest MCC (the baseline
    model's own headline metric - see train_model()/compute_binary_metrics()).
    """
    walk_forward_config = config.get("phase_v2", {}).get("retraining", {}).get("walk_forward", {})
    train_span_days = int(walk_forward_config.get("train_span_days", 1095))
    validation_span_days = int(walk_forward_config.get("validation_span_days", 365))
    backtest_span_days = int(walk_forward_config.get("backtest_span_days", 365))

    windows = generate_walk_forward_windows(
        config["phase1"]["universe"]["common_window"],
        train_span_days=train_span_days,
        validation_span_days=validation_span_days,
        backtest_span_days=backtest_span_days,
        step_days=step_days,
        mode=mode,
    )
    if not windows:
        LOGGER.warning(
            "walk-forward: no windows fit inside common_window with train=%s/validation=%s/backtest=%s/step=%s days.",
            train_span_days, validation_span_days, backtest_span_days, step_days,
        )
        return {"run_id": None, "num_windows": 0, "window_results": [], "summary": summarize_walk_forward_run([])}

    run_id = f"walk-forward-{uuid.uuid4()}"
    feature_names = config["phase1"]["features"]["input_set"]
    window_results: list[dict] = []
    backtest_mcc_by_window: list[float] = []

    for window_index, window in enumerate(windows):
        window_config = copy.deepcopy(config)
        window_config["phase1"]["windows"] = window
        LOGGER.info(
            "walk-forward window %s/%s: train=%s..%s validation=%s..%s backtest=%s..%s",
            window_index + 1, len(windows),
            window["training"]["start"], window["training"]["end"],
            window["validation"]["start"], window["validation"]["end"],
            window["backtest"]["start"], window["backtest"]["end"],
        )

        dataset, metadata = build_feature_dataset(window_config)
        asset_quality = build_asset_quality(window_config, dataset, metadata)
        dataset = apply_asset_quality_flags(dataset, asset_quality)

        feature_config = window_config["phase1"]["features"]
        winsorize_quantiles = tuple(feature_config.get("winsorize_quantiles", (0.001, 0.999)))
        clip_sigma = float(feature_config.get("scaled_feature_clip_sigma", 10.0))
        dataset, scaler, clip_sigma = fit_and_apply_scaler(
            dataset, feature_names, winsorize_quantiles=winsorize_quantiles, clip_sigma=clip_sigma,
        )
        dataset, _ = add_asset_context_features(
            dataset, [asset["ticker"] for asset in window_config["phase1"]["universe"]["assets"]],
        )
        dataset, _ = add_asset_class_context_features(dataset, asset_class_by_ticker_from_config(window_config))
        dataset_manifest = build_dataset_manifest(window_config, dataset, {}, metadata, asset_quality)

        version_id = f"{run_id}/window_{window_index}"
        paths = candidate_output_paths(version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        write_scaler_artifacts(
            scaler, dataset_manifest, scaler_path=paths["scaler"], scaler_stats_path=paths["scaler_stats"],
            clip_sigma=clip_sigma,
        )
        paths["dataset_manifest"].write_text(json.dumps(dataset_manifest, indent=2), encoding="utf-8")

        training_result = train_model(
            window_config, dataset,
            checkpoint_path=paths["model_checkpoint"], metrics_path=paths["training_metrics"],
            strategy_report_path=paths["strategy_report"], equity_curves_path=paths["equity_curves"],
        )
        write_model_export(
            window_config, data_summary, dataset_manifest=dataset_manifest, training_result=training_result,
            weights_path=paths["model_weights"], dataset_manifest_path=paths["dataset_manifest"],
            scaler_path=paths["scaler"], scaler_stats_path=paths["scaler_stats"],
            checkpoint_path=paths["model_checkpoint"], metrics_path=paths["training_metrics"],
            strategy_report_path=paths["strategy_report"],
        )

        backtest_mcc = float(training_result["metrics"]["backtest"].get("mcc", 0.0) or 0.0)
        backtest_mcc_by_window.append(backtest_mcc)
        window_results.append({"window": window, "version_id": version_id, "backtest_mcc": backtest_mcc})
        LOGGER.info("walk-forward window %s/%s backtest MCC: %.4f", window_index + 1, len(windows), backtest_mcc)

    summary = summarize_walk_forward_run(backtest_mcc_by_window)
    run_summary = {"run_id": run_id, "num_windows": len(windows), "window_results": window_results, "summary": summary}
    (ML_DIR / "versions" / run_id / "walk_forward_summary.json").parent.mkdir(parents=True, exist_ok=True)
    (ML_DIR / "versions" / run_id / "walk_forward_summary.json").write_text(
        json.dumps(run_summary, indent=2), encoding="utf-8"
    )
    return run_summary


def main() -> int:
    setup_logging()
    args = parse_args()
    if args.candidate and not args.version_id:
        raise SystemExit("--candidate requires --version-id")
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

    if args.walk_forward:
        walk_forward_config = config.get("phase_v2", {}).get("retraining", {}).get("walk_forward", {})
        step_days = args.step_days if args.step_days is not None else int(walk_forward_config.get("step_days", 90))
        mode = args.mode if args.mode is not None else str(walk_forward_config.get("mode", "expanding"))
        run_summary = _run_walk_forward(config, data_summary, step_days=step_days, mode=mode)
        if run_summary["num_windows"] == 0:
            print("Walk-forward run produced no windows - common_window too short for the configured spans.")
            return 0
        print(
            f"Walk-forward run {run_summary['run_id']}: {run_summary['num_windows']} windows trained into "
            f"ml/versions/{run_summary['run_id']}/window_*/.",
            f"Cross-window backtest MCC: mean={run_summary['summary']['cross_window_bootstrap']['mean_ic']:.4f}, "
            f"95% CI=[{run_summary['summary']['cross_window_bootstrap']['lower_bound']:.4f}, "
            f"{run_summary['summary']['cross_window_bootstrap']['upper_bound']:.4f}].",
        )
        LOGGER.info("Walk-forward run finished — active ml/ artifacts untouched.")
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

    feature_config = config["phase1"]["features"]
    winsorize_quantiles = tuple(feature_config.get("winsorize_quantiles", (0.001, 0.999)))
    clip_sigma = float(feature_config.get("scaled_feature_clip_sigma", 10.0))
    dataset, scaler, clip_sigma = fit_and_apply_scaler(
        dataset,
        feature_names,
        winsorize_quantiles=winsorize_quantiles,
        clip_sigma=clip_sigma,
    )
    dataset, _ = add_asset_context_features(
        dataset,
        [asset["ticker"] for asset in config["phase1"]["universe"]["assets"]],
    )
    dataset, _ = add_asset_class_context_features(dataset, asset_class_by_ticker_from_config(config))
    dataset_manifest = build_dataset_manifest(config, dataset, inventory, metadata, asset_quality)

    if args.candidate:
        paths = candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)

        write_scaler_artifacts(
            scaler,
            dataset_manifest,
            scaler_path=paths["scaler"],
            scaler_stats_path=paths["scaler_stats"],
            clip_sigma=clip_sigma,
        )
        paths["feature_schema"].write_text(
            json.dumps(
                {
                    "project": dataset_manifest["project"],
                    "phase": 2,
                    "feature_names": dataset_manifest["feature_names"],
                    "scaled_feature_names": dataset_manifest["scaled_feature_names"],
                    "categorical_feature_names": dataset_manifest["categorical_feature_names"],
                    "context_feature_names": dataset_manifest["context_feature_names"],
                    "model_input_names": dataset_manifest["model_input_names"],
                    "target_column": dataset_manifest["target_column"],
                    "split_column": "split",
                    "asset_quality": dataset_manifest["asset_quality"],
                    "training_eligible_assets": dataset_manifest["training_eligible_assets"],
                    "trading_eligible_assets": dataset_manifest["trading_eligible_assets"],
                    "observation_only_assets": dataset_manifest["observation_only_assets"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        paths["dataset_manifest"].write_text(json.dumps(dataset_manifest, indent=2), encoding="utf-8")

        LOGGER.info("Training candidate model %s.", args.version_id)
        training_result = train_model(
            config,
            dataset,
            checkpoint_path=paths["model_checkpoint"],
            metrics_path=paths["training_metrics"],
            strategy_report_path=paths["strategy_report"],
            equity_curves_path=paths["equity_curves"],
        )
        write_model_export(
            config,
            data_summary,
            dataset_manifest=dataset_manifest,
            training_result=training_result,
            weights_path=paths["model_weights"],
            dataset_manifest_path=paths["dataset_manifest"],
            scaler_path=paths["scaler"],
            scaler_stats_path=paths["scaler_stats"],
            checkpoint_path=paths["model_checkpoint"],
            metrics_path=paths["training_metrics"],
            strategy_report_path=paths["strategy_report"],
        )
        print(
            f"Candidate {args.version_id} trained into {paths['version_dir']}.",
            f"Backtest sharpe: {training_result['strategy_report']['backtest']['strategy']['sharpe']:.4f}.",
            f"Backtest max drawdown: {training_result['strategy_report']['backtest']['strategy']['max_drawdown']:.4f}.",
        )
        LOGGER.info("Candidate training finished — active ml/ artifacts untouched.")
        return 0

    write_dataset_artifacts(dataset, dataset_manifest, scaler, config=config, clip_sigma=clip_sigma)

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

    if args.experts_only:
        LOGGER.info("Training expert models.")
        expert_training_result = train_expert_models(config, dataset, dataset_manifest)
        write_visualization_state(
            config,
            inventory,
            data_summary,
            dataset_manifest=dataset_manifest,
            training_context=load_existing_training_context(),
        )
        print(
            "Phase V2-8.5 stabilized expert models trained.",
            f"Trained: {', '.join(expert_training_result['trained_experts']) or 'none'}.",
            f"Skipped: {', '.join(expert_training_result['skipped_experts']) or 'none'}.",
            f"Gating eligible: {', '.join(expert_training_result['gating_eligible_experts']) or 'none'}.",
            f"Disabled for gating: {', '.join(expert_training_result['disabled_for_gating_experts']) or 'none'}.",
        )
        return 0

    LOGGER.info("Training model.")
    training_result = train_model(config, dataset)
    LOGGER.info("Training expert models.")
    expert_training_result = train_expert_models(config, dataset, dataset_manifest)
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
        f"Expert models trained: {', '.join(expert_training_result['trained_experts']) or 'none'}.",
        f"Gating eligible experts: {', '.join(expert_training_result['gating_eligible_experts']) or 'none'}.",
    )
    LOGGER.info("Training pipeline finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
