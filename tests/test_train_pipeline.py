import inspect
from zipfile import ZipFile

import numpy as np
import pandas as pd

import train
from train import (
    ML_DIR,
    MODEL_CHECKPOINT_PATH,
    MODEL_WEIGHTS_PATH,
    SCALER_PATH,
    SCALER_STATS_PATH,
    TRAINING_METRICS_PATH,
    build_asset_quality,
    candidate_output_paths,
    engineer_features,
    ensure_derived_crypto_daily_series,
    fit_and_apply_scaler,
    train_model,
    validate_training_inputs,
    write_model_export,
    write_scaler_artifacts,
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


def test_candidate_output_paths_are_all_under_versions_directory():
    paths = candidate_output_paths("abc-123")

    version_dir = ML_DIR / "versions" / "abc-123"
    assert paths["version_dir"] == version_dir
    for key, path in paths.items():
        assert version_dir in path.parents or path == version_dir


def test_train_model_default_paths_match_active_constants():
    # Regression guard for the V2-17 parameterization refactor: every
    # existing non-candidate call site (e.g. main()'s baseline training)
    # calls train_model(config, dataset) with no path kwargs, so the
    # defaults must still point at the active ml//backtests locations.
    defaults = inspect.signature(train_model).parameters
    assert defaults["checkpoint_path"].default == MODEL_CHECKPOINT_PATH
    assert defaults["metrics_path"].default == TRAINING_METRICS_PATH


def test_write_model_export_default_paths_match_active_constants():
    defaults = inspect.signature(write_model_export).parameters
    assert defaults["weights_path"].default == MODEL_WEIGHTS_PATH
    assert defaults["scaler_path"].default == SCALER_PATH
    assert defaults["scaler_stats_path"].default == SCALER_STATS_PATH


def test_write_scaler_artifacts_writes_only_to_given_paths(tmp_path):
    dataset = pd.DataFrame({"ticker": ["CORE", "CORE"], "split": ["train", "train"], "feature": [10.0, 20.0]})
    _, scaler = fit_and_apply_scaler(dataset, ["feature"])
    manifest = {"feature_names": ["feature"]}

    active_mtime_before = SCALER_PATH.stat().st_mtime if SCALER_PATH.exists() else None

    candidate_scaler_path = tmp_path / "versions" / "v1" / "scaler.pkl"
    candidate_scaler_stats_path = tmp_path / "versions" / "v1" / "scaler_stats.json"

    write_scaler_artifacts(
        scaler, manifest, scaler_path=candidate_scaler_path, scaler_stats_path=candidate_scaler_stats_path
    )

    assert candidate_scaler_path.exists()
    assert candidate_scaler_stats_path.exists()
    # never touches the active ml/ scaler path
    active_mtime_after = SCALER_PATH.stat().st_mtime if SCALER_PATH.exists() else None
    assert active_mtime_after == active_mtime_before


def test_ensure_derived_crypto_daily_series_merges_with_existing_backfill(tmp_path, monkeypatch):
    # Regression guard: this function used to ZipFile(output_zip, "w") the
    # daily series unconditionally from minute trade data alone, silently
    # discarding any yfinance-backfilled history (data_pipeline/
    # yfinance_backfill.py) already sitting in the same zip whenever
    # train.py ran. It must merge instead: real minute-derived rows win on
    # overlapping dates, but backfilled rows for dates with no minute data
    # must survive.
    monkeypatch.setattr(train, "ROOT", tmp_path)

    minute_dir = tmp_path / "data" / "crypto" / "coinbase" / "minute" / "testusd"
    minute_dir.mkdir(parents=True)
    with ZipFile(minute_dir / "20180101_trade.zip", "w") as archive:
        archive.writestr(
            "20180101_trade.csv",
            "1514800000,10,11,9,10.5,100\n1514800060,10.5,11.5,9.5,11,50\n",
        )

    output_zip = tmp_path / "data" / "crypto" / "coinbase" / "daily" / "testusd_trade.zip"
    output_zip.parent.mkdir(parents=True)
    with ZipFile(output_zip, "w") as archive:
        archive.writestr(
            "testusd.csv",
            "20171231 00:00,1,1,1,1,1\n20180101 00:00,999,999,999,999,999\n",
        )

    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {
                        "ticker": "TESTUSD",
                        "security_type": "crypto",
                        "market": "coinbase",
                        "data_path": "data/crypto/coinbase/daily/testusd_trade.zip",
                        "derived_from": "data/crypto/coinbase/minute/testusd",
                        "aggregation": "daily_from_minute_trade",
                    }
                ]
            }
        }
    }

    ensure_derived_crypto_daily_series(config)

    with ZipFile(output_zip) as archive:
        member = archive.namelist()[0]
        with archive.open(member) as handle:
            lines = [line for line in handle.read().decode("utf-8").splitlines() if line.strip()]

    by_date = {line.split(",")[0].split()[0]: line.split(",") for line in lines}
    assert set(by_date) == {"20171231", "20180101"}
    # backfilled row for a date with no minute data survives untouched
    assert by_date["20171231"] == ["20171231 00:00", "1", "1", "1", "1", "1"]
    # real minute-derived row wins over the stale placeholder for the same date
    fields = by_date["20180101"]
    assert float(fields[1]) == 10.0  # open: first row by timestamp
    assert float(fields[2]) == 11.5  # high: max across the session
    assert float(fields[3]) == 9.0  # low: min across the session
    assert float(fields[4]) == 11.0  # close: last row by timestamp
    assert float(fields[5]) == 150.0  # volume: summed
