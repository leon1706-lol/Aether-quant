"""V2 metadata contract for the existing Lean-data training pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _asset_group_counts(assets: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset in assets:
        security_type = str(asset.get("security_type", "unknown"))
        counts[security_type] = counts.get(security_type, 0) + 1
    return counts


def _pipeline_consumers() -> list[str]:
    return [
        "train.py baseline model training",
        "Lean backtesting via main.py",
        "moe expert datasets",
        "regime detection features",
        "topology snapshots",
        "dynamic risk and volatility dashboard feeds",
    ]


def build_v2_pipeline_manifest(config: dict, dataset_manifest: dict | None = None) -> dict:
    phase1 = config["phase1"]
    universe = phase1["universe"]
    assets = list(universe["assets"])
    dataset_manifest = dataset_manifest or {}

    return {
        "project": config.get("name", "Aether Quant"),
        "version": "v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_source": {
            "type": "local_lean_data_folder",
            "root": "data",
            "absolute_root": str(ROOT / "data"),
            "training_uses_lean_data_folder": True,
            "backtesting_uses_lean_data_folder": True,
        },
        "universe": {
            "name": universe.get("name"),
            "resolution": universe.get("resolution"),
            "asset_count": len(assets),
            "asset_group_counts": _asset_group_counts(assets),
            "tickers": [asset["ticker"] for asset in assets],
        },
        "windows": phase1["windows"],
        "features": {
            "base_features": phase1["features"]["input_set"],
            "target": phase1["target"],
            "normalization": phase1["features"].get("normalization"),
        },
        "quality": {
            "training_eligible_assets": dataset_manifest.get("training_eligible_assets", []),
            "trading_eligible_assets": dataset_manifest.get("trading_eligible_assets", []),
            "observation_only_assets": dataset_manifest.get("observation_only_assets", []),
        },
        "consumers": _pipeline_consumers(),
        "next_v2_dependencies": [
            "regime vectors",
            "expert-specific training slices",
            "topology snapshots",
            "volatility sizing inputs",
            "experience observations",
        ],
    }

