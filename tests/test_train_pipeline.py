import numpy as np
import pandas as pd

from train import (
    build_asset_quality,
    engineer_features,
    fit_and_apply_scaler,
    validate_training_inputs,
)


FEATURE_NAMES = [
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
]


def test_engineer_features_uses_adaptive_lookbacks_for_short_series():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=4, freq="D"),
            "open": [10.0, 11.0, 12.0, 13.0],
            "high": [11.0, 12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0, 12.0],
            "close": [10.0, 12.0, 11.0, 13.0],
            "volume": [100.0, 120.0, 90.0, 150.0],
        }
    )
    windows = {
        "training": {"start": "2020-01-01", "end": "2020-01-04"},
        "validation": {"start": "2020-02-01", "end": "2020-02-28"},
        "backtest": {"start": "2020-03-01", "end": "2020-03-31"},
    }

    engineered = engineer_features(frame, FEATURE_NAMES, windows)

    assert len(engineered) == 2
    assert engineered["split"].tolist() == ["train", "train"]
    assert engineered["target_direction"].tolist() == [0, 1]
    assert engineered[FEATURE_NAMES].isna().sum().sum() == 0


def test_asset_quality_marks_thin_assets_observation_only():
    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {"ticker": "CORE", "security_type": "equity", "market": "usa"},
                    {"ticker": "THIN", "security_type": "crypto", "market": "coinbase"},
                ]
            }
        },
        "phase9": {
            "asset_quality": {
                "min_total_feature_rows": 3,
                "min_training_rows": 2,
                "min_backtest_rows": 1,
            }
        },
    }
    dataset = pd.DataFrame(
        {
            "ticker": ["CORE", "CORE", "CORE", "THIN", "THIN"],
            "split": ["train", "train", "backtest", "validation", "backtest"],
        }
    )
    metadata = {
        "asset_summaries": [
            {"ticker": "CORE", "available_rows": 4, "feature_rows": 3},
            {"ticker": "THIN", "available_rows": 3, "feature_rows": 2},
        ]
    }

    quality = build_asset_quality(config, dataset, metadata)

    assert quality["CORE"]["quality_tier"] == "core"
    assert quality["CORE"]["training_eligible"] is True
    assert quality["CORE"]["trading_eligible"] is True
    assert quality["THIN"]["quality_tier"] == "thin"
    assert quality["THIN"]["role"] == "observation_only"
    assert quality["THIN"]["trading_eligible"] is False


def test_scaler_fits_only_training_eligible_rows():
    dataset = pd.DataFrame(
        {
            "ticker": ["CORE", "CORE", "THIN"],
            "split": ["train", "train", "train"],
            "training_eligible": [True, True, False],
            "feature": [10.0, 20.0, 1000.0],
        }
    )

    scaled, scaler = fit_and_apply_scaler(dataset, ["feature"])

    assert np.isclose(scaler.mean_[0], 15.0)
    assert "feature_scaled" in scaled.columns
    assert np.isclose(scaled.loc[0, "feature_scaled"], -1.0)
    assert np.isclose(scaled.loc[1, "feature_scaled"], 1.0)


def test_validate_training_inputs_reports_missing_data_file():
    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {
                        "ticker": "MISSING",
                        "security_type": "equity",
                        "market": "usa",
                        "data_path": "data/equity/usa/daily/does_not_exist.zip",
                    }
                ]
            },
            "windows": {
                "training": {"start": "2020-01-01", "end": "2020-01-31"},
                "validation": {"start": "2020-02-01", "end": "2020-02-28"},
                "backtest": {"start": "2020-03-01", "end": "2020-03-31"},
            },
        }
    }

    issues = validate_training_inputs(config)

    assert any("does_not_exist.zip" in issue for issue in issues)


def test_validate_training_inputs_reports_reversed_window():
    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {
                        "ticker": "DERIVED",
                        "security_type": "crypto",
                        "market": "coinbase",
                        "data_path": "data/crypto/coinbase/daily/derived.zip",
                        "derived_from": "data/crypto/coinbase/minute/derived",
                    }
                ]
            },
            "windows": {
                "training": {"start": "2020-02-01", "end": "2020-01-01"},
                "validation": {"start": "2020-02-01", "end": "2020-02-28"},
                "backtest": {"start": "2020-03-01", "end": "2020-03-31"},
            },
        }
    }

    issues = validate_training_inputs(config)

    assert "training: start date is after end date." in issues
