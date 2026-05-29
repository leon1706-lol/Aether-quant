"""Expert-specific dataset slicing for Aether Quant V2."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from regime import build_market_regime_vector


EXPERT_DEFINITIONS = {
    "bullish": {
        "description": "Rows where momentum structure is bullish.",
        "filter": {"trend_regime": ["bullish"]},
    },
    "bearish": {
        "description": "Rows where momentum structure is bearish.",
        "filter": {"trend_regime": ["bearish"]},
    },
    "sideways": {
        "description": "Rows where trend signal is flat or mixed.",
        "filter": {"trend_regime": ["sideways"]},
    },
    "volatility": {
        "description": "Rows where volatility is elevated and risk control matters most.",
        "filter": {"volatility_regime": ["high_volatility"]},
    },
}


@dataclass(frozen=True)
class ExpertDatasetSummary:
    expert: str
    description: str
    rows: int
    train_rows: int
    validation_rows: int
    backtest_rows: int
    tickers: list[str]
    positive_target_rate: float | None
    date_start: str | None
    date_end: str | None
    filter: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _phase_v2_regime_config(config: dict | None) -> dict:
    config = config or {}
    return config.get("phase_v2", {}).get("regime_detection", {})


def annotate_dataset_with_regimes(dataset: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    """Return a copy of the dataset with V2 regime columns added."""
    result = dataset.copy()
    regime_config = _phase_v2_regime_config(config)

    regime_rows = []
    for row in result.to_dict(orient="records"):
        vector = build_market_regime_vector(
            row,
            portfolio_drawdown=row.get("portfolio_drawdown", 0.0),
            average_correlation=row.get("average_correlation", 0.0),
            bullish_threshold=float(regime_config.get("bullish_threshold", 0.02)),
            bearish_threshold=float(regime_config.get("bearish_threshold", -0.02)),
            low_volatility_threshold=float(regime_config.get("low_volatility_threshold", 0.01)),
            high_volatility_threshold=float(regime_config.get("high_volatility_threshold", 0.03)),
            risk_off_drawdown_threshold=float(regime_config.get("risk_off_drawdown_threshold", 0.08)),
            risk_on_drawdown_threshold=float(regime_config.get("risk_on_drawdown_threshold", 0.03)),
            high_correlation_threshold=float(regime_config.get("high_correlation_threshold", 0.75)),
        )
        regime_rows.append(vector.to_dict())

    regime_frame = pd.DataFrame(regime_rows, index=result.index)
    for column in regime_frame.columns:
        result[f"regime_{column}"] = regime_frame[column]
    return result


def _filter_for_expert(dataset: pd.DataFrame, expert_filter: dict) -> pd.Series:
    mask = pd.Series(True, index=dataset.index)
    for column, allowed_values in expert_filter.items():
        regime_column = f"regime_{column}"
        mask = mask & dataset[regime_column].isin(allowed_values)
    return mask


def _summarize_expert_dataset(expert: str, definition: dict, frame: pd.DataFrame) -> ExpertDatasetSummary:
    split_counts = frame["split"].value_counts().to_dict() if "split" in frame.columns else {}
    positive_target_rate = None
    if "target_direction" in frame.columns and len(frame) > 0:
        positive_target_rate = float(frame["target_direction"].mean())

    tickers = sorted(frame["ticker"].dropna().unique().tolist()) if "ticker" in frame.columns else []
    date_start = str(frame["date"].min()) if "date" in frame.columns and len(frame) > 0 else None
    date_end = str(frame["date"].max()) if "date" in frame.columns and len(frame) > 0 else None

    return ExpertDatasetSummary(
        expert=expert,
        description=str(definition["description"]),
        rows=int(len(frame)),
        train_rows=int(split_counts.get("train", 0)),
        validation_rows=int(split_counts.get("validation", 0)),
        backtest_rows=int(split_counts.get("backtest", 0)),
        tickers=tickers,
        positive_target_rate=positive_target_rate,
        date_start=date_start,
        date_end=date_end,
        filter=dict(definition["filter"]),
    )


def build_expert_dataset_manifest(
    dataset: pd.DataFrame,
    dataset_manifest: dict,
    config: dict | None = None,
    expert_definitions: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    annotated = annotate_dataset_with_regimes(dataset, config)
    definitions = expert_definitions or EXPERT_DEFINITIONS

    eligible = annotated
    if "training_eligible" in eligible.columns:
        eligible = eligible[eligible["training_eligible"]].copy()

    expert_summaries = {}
    for expert, definition in definitions.items():
        expert_frame = eligible[_filter_for_expert(eligible, definition["filter"])].copy()
        expert_summaries[expert] = _summarize_expert_dataset(
            expert,
            definition,
            expert_frame,
        ).to_dict()

    manifest = {
        "project": dataset_manifest.get("project", "Aether Quant"),
        "phase": "v2_expert_datasets",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dataset_rows": int(len(dataset)),
        "eligible_dataset_rows": int(len(eligible)),
        "feature_names": list(dataset_manifest.get("feature_names", [])),
        "model_input_names": list(dataset_manifest.get("model_input_names", [])),
        "target_column": dataset_manifest.get("target_column", "target_direction"),
        "regime_columns": [
            "regime_primary_regime",
            "regime_trend_regime",
            "regime_volatility_regime",
            "regime_risk_regime",
            "regime_confidence",
        ],
        "experts": expert_summaries,
    }
    return annotated, manifest


def write_expert_dataset_artifacts(
    annotated_dataset: pd.DataFrame,
    manifest: dict,
    output_dir: Path,
    manifest_path: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    eligible = annotated_dataset
    if "training_eligible" in eligible.columns:
        eligible = eligible[eligible["training_eligible"]].copy()

    for expert, summary in manifest["experts"].items():
        expert_dir = output_dir / expert
        expert_dir.mkdir(parents=True, exist_ok=True)
        expert_frame = eligible[_filter_for_expert(eligible, summary["filter"])].copy()
        expert_frame.to_csv(expert_dir / "all_splits.csv", index=False)

        if "split" not in expert_frame.columns:
            continue
        for split_name in ("train", "validation", "backtest"):
            split_frame = expert_frame[expert_frame["split"] == split_name]
            split_frame.to_csv(expert_dir / f"{split_name}.csv", index=False)
