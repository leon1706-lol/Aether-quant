"""The V6.4.3 research / audit flags of `aq evaluate` and `aq research` (the audit_runners.py pattern): each loads only what
it needs, runs one pure tool and returns its JSON-ready report."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
ML_DIR = ROOT_DIR / "ml"
DEFAULT_DATASET = ML_DIR / "datasets" / "full_dataset.csv"
CLASS_COLUMNS = ("asset_class_equity", "asset_class_crypto", "asset_class_bond", "asset_class_future", "asset_class_option", "asset_class_forex")
FACTOR_INPUTS = ("close_to_close_return_1d", "close_to_close_return_5d", "momentum_20d", "rolling_volatility_20d", "dist_52w_high",
                 "target_return_1d")


def _scaled_features() -> list[str]:
    return list(json.loads((ML_DIR / "feature_schema.json").read_text(encoding="utf-8"))["scaled_feature_names"])


def run_audit_leakage(dataset_path=None, *, target_column: str = "target_rank_20d") -> dict:
    from evaluation.leakage_audit import audit_leakage
    from evaluation.research_probes import load_research_frame

    features = _scaled_features()
    frame = load_research_frame(dataset_path or DEFAULT_DATASET, columns=[*features, target_column, *CLASS_COLUMNS],
                                splits=("train", "validation"))
    report = audit_leakage(frame, feature_columns=features, target_column=target_column, class_columns=CLASS_COLUMNS)
    report["dataset"] = str(dataset_path or DEFAULT_DATASET)
    return report


def run_overfit_report(ml_dir: Path = ML_DIR) -> dict:
    from evaluation.overfit_diagnostics import training_gap_report

    paths = {name: ml_dir / f"{name}_training_metrics.json" for name in ("multitask", "sequence")}
    return {"models": training_gap_report({name: path for name, path in paths.items() if path.exists()})}


def run_pbo(trial_returns_path: Path, *, blocks: int = 16) -> dict:
    from evaluation.pbo import probability_of_backtest_overfitting

    path = Path(trial_returns_path)
    matrix = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, index_col=0)
    report = probability_of_backtest_overfitting(matrix.fillna(0.0).to_numpy(), blocks=blocks)
    report.update(source=str(path), trials=list(map(str, matrix.columns)))
    return report


def _signal_frame(signal_path: Path, dataset_path, columns) -> pd.DataFrame:
    from evaluation.research_probes import load_research_frame

    signal = pd.read_csv(signal_path)
    signal["date"] = signal["date"].astype(str).str[:10]
    frame = load_research_frame(dataset_path or DEFAULT_DATASET, columns=columns)
    return frame.merge(signal[["date", "ticker", "score"]], on=["date", "ticker"], how="left")


def run_factor_spanning(signal_path: Path, dataset_path=None, *, split: str = "backtest") -> dict:
    from evaluation.factor_spanning import FACTOR_COLUMNS, build_factor_returns, build_factor_scores, factor_spanning

    frame = _signal_frame(Path(signal_path), dataset_path, FACTOR_INPUTS)
    frame = pd.concat([frame, build_factor_scores(frame)], axis=1)
    part = frame[frame["split"] == split]
    factor_returns = build_factor_returns(part, list(FACTOR_COLUMNS))
    signal_returns = build_factor_returns(part, ["score"])["score"]
    return {"signal": str(signal_path), "split": split, **factor_spanning(signal_returns, factor_returns)}


def run_signal_report(signal_path: Path, dataset_path=None, *, horizons=(5, 20), splits=("validation", "backtest")) -> dict:
    from evaluation.research_harness import evaluate_signal

    targets = [f"target_rank_{h}d" for h in horizons]
    frame = _signal_frame(Path(signal_path), dataset_path, [*targets, "target_return_1d"])
    report = evaluate_signal(frame, score_column="score", splits=splits, horizons=horizons)
    report["signal"] = str(signal_path)
    return report


def run_sim_lean_gap(calibration_path: Path, *, variant: str = "calibrated") -> dict:
    from evaluation.sim_lean_calibration import gap_report

    calibration = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
    return {"source": str(calibration_path), "variant": variant, "windows": gap_report(calibration, variant=variant)}
