import json

import pandas as pd

from experts import (
    annotate_dataset_with_regimes,
    build_expert_dataset_manifest,
    write_expert_dataset_artifacts,
)


def _sample_dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [
                "2020-01-01",
                "2020-01-02",
                "2020-01-03",
                "2020-01-04",
                "2020-01-05",
            ],
            "ticker": ["AAPL", "AAPL", "SPY", "SPY", "THIN"],
            "split": ["train", "validation", "train", "backtest", "train"],
            "training_eligible": [True, True, True, True, False],
            "target_direction": [1, 1, 0, 0, 1],
            "momentum_5d": [0.04, 0.03, -0.04, 0.001, 0.05],
            "momentum_20d": [0.06, 0.05, -0.07, -0.001, 0.06],
            "rolling_volatility_20d": [0.012, 0.015, 0.045, 0.006, 0.012],
        }
    )


def _dataset_manifest() -> dict:
    return {
        "project": "Aether Quant",
        "feature_names": ["momentum_5d", "momentum_20d", "rolling_volatility_20d"],
        "model_input_names": ["momentum_5d_scaled", "momentum_20d_scaled"],
        "target_column": "target_direction",
    }


def test_annotate_dataset_with_regimes_adds_routing_columns():
    annotated = annotate_dataset_with_regimes(_sample_dataset())

    assert "regime_primary_regime" in annotated.columns
    assert "regime_trend_regime" in annotated.columns
    assert "regime_volatility_regime" in annotated.columns
    assert "regime_risk_regime" in annotated.columns
    assert annotated.loc[0, "regime_trend_regime"] == "bullish"
    assert annotated.loc[2, "regime_trend_regime"] == "bearish"


def test_build_expert_dataset_manifest_slices_training_eligible_rows():
    annotated, manifest = build_expert_dataset_manifest(
        _sample_dataset(),
        _dataset_manifest(),
    )

    assert len(annotated) == 5
    assert manifest["eligible_dataset_rows"] == 4
    assert manifest["experts"]["bullish"]["rows"] == 2
    assert manifest["experts"]["bearish"]["rows"] == 1
    assert manifest["experts"]["sideways"]["rows"] == 1
    assert manifest["experts"]["volatility"]["rows"] == 1
    assert manifest["experts"]["bullish"]["tickers"] == ["AAPL"]
    assert "THIN" not in manifest["experts"]["bullish"]["tickers"]


def test_write_expert_dataset_artifacts_creates_manifest_and_split_csvs(tmp_path):
    annotated, manifest = build_expert_dataset_manifest(
        _sample_dataset(),
        _dataset_manifest(),
    )
    output_dir = tmp_path / "expert_datasets"
    manifest_path = tmp_path / "expert_dataset_manifest.json"

    write_expert_dataset_artifacts(annotated, manifest, output_dir, manifest_path)

    stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bullish_train = output_dir / "bullish" / "train.csv"
    volatility_all = output_dir / "volatility" / "all_splits.csv"

    assert stored_manifest["phase"] == "v2_expert_datasets"
    assert bullish_train.exists()
    assert volatility_all.exists()
    assert len(pd.read_csv(bullish_train)) == 1
