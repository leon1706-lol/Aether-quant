import inspect
import json
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
import torch
import torch.nn as nn

import train
from train import (
    ML_DIR,
    MODEL_CHECKPOINT_PATH,
    MODEL_WEIGHTS_PATH,
    SCALER_PATH,
    SCALER_STATS_PATH,
    TRAINING_METRICS_PATH,
    apply_split_adjustments,
    assess_regression_quality,
    build_asset_quality,
    candidate_output_paths,
    compute_masked_binary_metrics,
    compute_masked_regression_metrics,
    compute_rank_ic,
    engineer_features,
    ensure_derived_crypto_daily_series,
    fit_and_apply_scaler,
    load_factor_file,
    load_lean_bars,
    masked_bce_with_logits_loss,
    masked_mse_loss,
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


def test_engineer_features_clamps_extreme_volume_change():
    # Mirrors the real BTCUSD 2018-08-14 incident: raw volume jumps
    # ~520,000x in one day (a data-feed unit discontinuity), which without
    # clamping becomes a many-thousand-sigma scaled feature - see
    # development/Problems.md.
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=4, freq="D"),
            "open": [10.0, 11.0, 12.0, 13.0],
            "high": [11.0, 12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0, 12.0],
            "close": [10.0, 12.0, 11.0, 13.0],
            "volume": [100.0, 120.0, 5_302_000_000.0, 150.0],
        }
    )
    windows = {
        "training": {"start": "2020-01-01", "end": "2020-01-04"},
        "validation": {"start": "2020-02-01", "end": "2020-02-28"},
        "backtest": {"start": "2020-03-01", "end": "2020-03-31"},
    }

    engineered = engineer_features(frame, FEATURE_NAMES, windows)

    assert engineered["volume_change_1d"].max() == 20.0
    assert engineered["volume_change_1d"].min() >= -1.0


def test_engineer_features_drops_extreme_return_as_label_outlier_for_equity():
    # An unadjusted stock split (e.g. AAPL's 2020-08-28 4-for-1 split
    # showing as a fake -74% "return") produces an impossible single-day
    # return that must not reach any trainer as a real label.
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=6, freq="D"),
            "open": [10.0, 10.5, 11.0, 19.8, 20.0, 20.5],
            "high": [10.2, 10.7, 11.2, 20.0, 20.2, 20.7],
            "low": [9.8, 10.3, 10.8, 19.6, 19.8, 20.3],
            "close": [10.0, 10.5, 11.0, 19.8, 20.0, 20.5],
            "volume": [100.0, 110.0, 105.0, 108.0, 112.0, 115.0],
        }
    )
    windows = {
        "training": {"start": "2020-01-01", "end": "2020-01-06"},
        "validation": {"start": "2020-02-01", "end": "2020-02-28"},
        "backtest": {"start": "2020-03-01", "end": "2020-03-31"},
    }

    engineered = engineer_features(frame, FEATURE_NAMES, windows, security_type="equity")

    # Row 0 is always dropped (no previous close for its own return
    # features) and row 5 is always dropped (no next close for its
    # target) regardless of this guard. Row index 2 (close 11.0 -> 19.8,
    # an 80% one-day return) is additionally excluded by the label-outlier
    # guard - only rows 1, 3, 4 survive.
    assert len(engineered) == 3
    assert engineered["target_return_1d"].abs().max() < 0.5


def test_engineer_features_allows_larger_moves_for_crypto_security_type():
    # The same 80% one-day move is a real, legitimate crypto move (e.g.
    # XRPUSD's 2021-01-29 +56%) and must not be treated as a label outlier
    # under the wider crypto bound.
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=6, freq="D"),
            "open": [10.0, 10.5, 11.0, 19.8, 20.0, 20.5],
            "high": [10.2, 10.7, 11.2, 20.0, 20.2, 20.7],
            "low": [9.8, 10.3, 10.8, 19.6, 19.8, 20.3],
            "close": [10.0, 10.5, 11.0, 19.8, 20.0, 20.5],
            "volume": [100.0, 110.0, 105.0, 108.0, 112.0, 115.0],
        }
    )
    windows = {
        "training": {"start": "2020-01-01", "end": "2020-01-06"},
        "validation": {"start": "2020-02-01", "end": "2020-02-28"},
        "backtest": {"start": "2020-03-01", "end": "2020-03-31"},
    }

    engineered = engineer_features(frame, FEATURE_NAMES, windows, security_type="crypto")

    # Row 0 (no previous close) and row 5 (no next close) are always
    # dropped regardless of this guard; the 80% row survives under the
    # wider crypto bound, so rows 1, 2, 3, 4 survive.
    assert len(engineered) == 4


def test_engineer_features_computes_multi_horizon_targets_without_extra_row_drops():
    # 5d/20d targets must NOT shrink the dataset the way the 1d target
    # does - rows near the end of an asset's history that lack a full
    # 5/20-day-forward close keep target_return_5d/20d as NaN instead of
    # being dropped (train_multitask.py/train_sequence.py mask them out of
    # the loss instead), so every per-expert dataset slice downstream
    # (which only ever needs the 1d target) stays exactly as large as
    # before this change.
    n = 30
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    closes = [100.0 + 0.1 * index for index in range(n)]
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )
    windows = {
        "training": {"start": "2020-01-01", "end": "2020-01-31"},
        "validation": {"start": "2021-01-01", "end": "2021-01-31"},
        "backtest": {"start": "2022-01-01", "end": "2022-01-31"},
    }

    engineered = engineer_features(frame, FEATURE_NAMES, windows)

    # Only the first (no previous close) and last (no next close) rows are
    # dropped - same row count as before multi-horizon targets existed.
    assert len(engineered) == n - 2
    assert "target_return_5d" in engineered.columns
    assert "target_return_20d" in engineered.columns
    assert "target_direction_5d" in engineered.columns
    assert "target_direction_20d" in engineered.columns
    # The trailing rows lacking a full 5/20-day-forward close are NaN, not
    # dropped.
    assert engineered["target_return_5d"].isna().sum() == 4
    assert engineered["target_return_20d"].isna().sum() == 19
    assert engineered["target_direction_5d"].isna().sum() == 4
    assert engineered["target_direction_20d"].isna().sum() == 19
    # Non-NaN target_direction_5d/20d values are still binary.
    assert set(engineered["target_direction_5d"].dropna().unique()) <= {0.0, 1.0}


def test_engineer_features_applies_horizon_specific_outlier_bounds():
    # A move that's within the 1d bound but exceeds the (narrower-relative)
    # 5d bound must be guarded independently per horizon - each target
    # column has its own outlier check, not one shared threshold.
    n = 10
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    closes = [10.0, 10.2, 10.4, 10.6, 10.8, 30.0, 30.2, 30.4, 30.6, 30.8]
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )
    windows = {
        "training": {"start": "2020-01-01", "end": "2020-01-31"},
        "validation": {"start": "2021-01-01", "end": "2021-01-31"},
        "backtest": {"start": "2022-01-01", "end": "2022-01-31"},
    }

    engineered = engineer_features(
        frame,
        FEATURE_NAMES,
        windows,
        security_type="equity",
        max_abs_return_5d={"equity": 0.9},
    )

    # target_return_5d spanning the 3x jump (row index 1, close 10.2 ->
    # 30.2, a ~196% 5-day return) exceeds the 0.9 bound and is NaN'd.
    assert engineered.loc[engineered["date"] == "2020-01-02", "target_return_5d"].isna().all()


def test_build_dataset_manifest_includes_target_columns_map():
    config = {
        "name": "Aether Quant",
        "phase1": {"features": {"input_set": ["feature_a"]}},
    }
    dataset = pd.DataFrame(
        {
            "ticker": ["CORE"],
            "split": ["train"],
            "date": pd.to_datetime(["2020-01-01"]),
        }
    )

    manifest = train.build_dataset_manifest(config, dataset, {"coverage_checks": {}}, {}, {})

    assert manifest["target_columns"]["direction"] == "target_direction"
    assert manifest["target_columns"]["direction_5d"] == "target_direction_5d"
    assert manifest["target_columns"]["direction_20d"] == "target_direction_20d"
    assert manifest["target_columns"]["rank_5d"] == "target_rank_5d"
    assert manifest["target_columns"]["rank_20d"] == "target_rank_20d"
    # Additive only - existing scalar keys every consumer already reads
    # stay exactly as they were.
    assert manifest["target_column"] == "target_direction"
    assert manifest["aux_target_column"] == "target_return_1d"


def test_load_factor_file_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", tmp_path)

    assert load_factor_file("NOFILE") is None


def test_load_factor_file_parses_rows_sorted_by_date(tmp_path, monkeypatch):
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", tmp_path)
    (tmp_path / "test.csv").write_text(
        "20200828,0.9967882,0.25,499.23\n20200806,0.9949942,0.25,455.61\n20501231,1,1,0\n",
        encoding="utf-8",
    )

    factors = load_factor_file("TEST")

    assert factors is not None
    assert factors["factor_date"].tolist() == sorted(factors["factor_date"].tolist())
    assert len(factors) == 3


def test_apply_split_adjustments_backward_adjusts_pre_split_prices(tmp_path, monkeypatch):
    # Mirrors AAPL's real 2020-08-31 4-for-1 split: rows dated on/before the
    # factor-file's split row must be scaled down (split_factor=0.25) to
    # today's post-split share terms; rows dated after must be untouched
    # (split_factor=1) - see train.py::apply_split_adjustments()'s
    # docstring and development/Problems.md.
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", tmp_path)
    (tmp_path / "test.csv").write_text(
        "20200828,1,0.25,499.23\n20501231,1,1,0\n",
        encoding="utf-8",
    )
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-08-27", "2020-08-28", "2020-08-31", "2020-09-01"]),
            "open": [500.0, 499.0, 128.0, 132.0],
            "high": [505.0, 503.0, 130.0, 134.0],
            "low": [495.0, 497.0, 126.0, 130.0],
            "close": [499.0, 499.23, 129.04, 133.0],
            "volume": [40_000_000.0, 44_109_029.0, 210_024_091.0, 142_927_370.0],
        }
    )

    adjusted = apply_split_adjustments(frame, "TEST")

    # Pre-split rows scaled by 0.25 (price) / by 0.25 (volume divided,
    # i.e. multiplied by 4) - post-split rows unchanged.
    assert np.isclose(adjusted.loc[0, "close"], 499.0 * 0.25)
    assert np.isclose(adjusted.loc[1, "close"], 499.23 * 0.25)
    assert np.isclose(adjusted.loc[0, "volume"], 40_000_000.0 / 0.25)
    assert np.isclose(adjusted.loc[2, "close"], 129.04)
    assert np.isclose(adjusted.loc[3, "close"], 133.0)
    assert np.isclose(adjusted.loc[2, "volume"], 210_024_091.0)
    # No fake single-day return remains across the split boundary.
    assert abs(adjusted.loc[2, "close"] / adjusted.loc[1, "close"] - 1.0) < 0.2


def test_apply_split_adjustments_is_identity_when_no_factor_file(tmp_path, monkeypatch):
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", tmp_path)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-08-27", "2020-08-28"]),
            "open": [500.0, 499.0],
            "high": [505.0, 503.0],
            "low": [495.0, 497.0],
            "close": [499.0, 499.23],
            "volume": [40_000_000.0, 44_109_029.0],
        }
    )

    adjusted = apply_split_adjustments(frame, "NOFACTORFILE")

    pd.testing.assert_frame_equal(adjusted, frame)


def test_apply_split_adjustments_noop_is_the_intended_contract_for_aq_fetch_tickers(tmp_path, monkeypatch):
    # Documents (not just incidentally exercises) a second, deliberate
    # data-provenance contract living alongside the original one:
    # data_pipeline/fetch.py::fetch_adhoc_asset() (backing `aq fetch`, used
    # for e.g. bond ETFs like TLT/SHY/LQD) fetches via
    # yfinance_backfill.py::fetch_yahoo_ohlcv()'s auto_adjust=True, so its
    # output is already dividend/split-adjusted before it ever reaches a
    # Lean zip. Unlike the original ~15 equities (raw Lean prices, adjusted
    # here via a checked-in data/equity/usa/factor_files/<ticker>.csv), any
    # `aq fetch`-added ticker has no factor file by design and must NOT get
    # one - a factor file would double-adjust already-adjusted prices. This
    # test locks in that the no-factor-file path is correct for those
    # tickers, not an accidental gap.
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", tmp_path)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-08-27", "2020-08-28"]),
            "open": [89.09, 87.76],
            "high": [89.19, 87.76],
            "low": [88.21, 87.36],
            "close": [88.5, 87.4],
            "volume": [8_000_000.0, 7_500_000.0],
        }
    )

    adjusted = apply_split_adjustments(frame, "TLT")

    pd.testing.assert_frame_equal(adjusted, frame)


def test_load_lean_bars_applies_split_adjustment_for_equities(tmp_path, monkeypatch):
    monkeypatch.setattr(train, "ROOT", tmp_path)
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", tmp_path / "data" / "equity" / "usa" / "factor_files")
    (train.FACTOR_FILES_DIR).mkdir(parents=True)
    (train.FACTOR_FILES_DIR / "test.csv").write_text(
        "20200828,1,0.25,499.23\n20501231,1,1,0\n",
        encoding="utf-8",
    )

    zip_path = tmp_path / "data" / "equity" / "usa" / "daily" / "test.zip"
    zip_path.parent.mkdir(parents=True)
    with ZipFile(zip_path, "w") as archive:
        # Lean's raw equity convention: prices x10000, no header.
        archive.writestr(
            "test.csv",
            "20200828 00:00,4990000,5030000,4970000,4992300,44109029\n"
            "20200831 00:00,1280000,1300000,1260000,1290400,210024091\n",
        )

    asset = {"ticker": "TEST", "security_type": "equity", "market": "usa", "data_path": "data/equity/usa/daily/test.zip"}
    frame = load_lean_bars(asset, {"start": "2020-08-01", "end": "2020-09-01"})

    # Without adjustment this would be a fake ~-74% single-day return.
    day_over_day_return = frame.loc[1, "close"] / frame.loc[0, "close"] - 1.0
    assert abs(day_over_day_return) < 0.2


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

    scaled, scaler, _ = fit_and_apply_scaler(dataset, ["feature"], winsorize_quantiles=(0.0, 1.0))

    assert np.isclose(scaler.mean_[0], 15.0)
    assert "feature_scaled" in scaled.columns
    assert np.isclose(scaled.loc[0, "feature_scaled"], -1.0)
    assert np.isclose(scaled.loc[1, "feature_scaled"], 1.0)


def test_fit_and_apply_scaler_winsorizes_training_outlier_before_fitting():
    # A single extreme training-row outlier (mirrors a real data-feed
    # discontinuity) must not drag the scaler's fitted mean/std far from
    # the bulk of otherwise-normal training data. Uses a wider quantile
    # bound than production's default (0.001/0.999) since with only 11
    # rows the 99.9th percentile sits almost on the outlier itself - the
    # real dataset's ~12,800 training rows are what makes the tight
    # production default meaningful (a handful of genuine extreme rows
    # get clipped, not the whole tail). With only 11 rows, quantile(0.8)
    # lands exactly on the largest normal value (index 8 of 10, no
    # interpolation into the outlier at index 10) - a deterministic upper
    # bound for this fixture's size, unlike 0.9+ which interpolates partway
    # into the outlier itself.
    normal_values = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1, 9.9, 10.3]
    dataset = pd.DataFrame(
        {
            "ticker": ["CORE"] * 11,
            "split": ["train"] * 11,
            "feature": normal_values + [500_000.0],
        }
    )

    _, scaler, clip_sigma = fit_and_apply_scaler(dataset, ["feature"], winsorize_quantiles=(0.0, 0.8))

    # Without winsorization the outlier alone would pull the mean to
    # ~45,463 and the std to ~150,000; with winsorization the fit stays
    # anchored to the normal cluster around 10.
    assert scaler.mean_[0] < 20.0
    assert scaler.scale_[0] < 20.0
    assert clip_sigma == 10.0


def test_fit_and_apply_scaler_default_quantiles_protect_a_realistic_training_set():
    # At production scale (thousands of training rows), the default
    # (0.001, 0.999) quantile bound does meaningfully clip a single extreme
    # outlier without needing a wider bound.
    rng = np.random.default_rng(seed=42)
    normal_values = rng.normal(loc=10.0, scale=1.0, size=2000).tolist()
    dataset = pd.DataFrame(
        {
            "ticker": ["CORE"] * 2001,
            "split": ["train"] * 2001,
            "feature": normal_values + [500_000.0],
        }
    )

    _, scaler, _ = fit_and_apply_scaler(dataset, ["feature"])

    assert scaler.mean_[0] < 20.0
    assert scaler.scale_[0] < 20.0


def test_fit_and_apply_scaler_clips_scaled_outlier_to_sigma_bound():
    # Even after a robust (winsorized) fit, a validation/backtest-split row
    # can still contain a raw outlier the train-only fit never saw - the
    # scaled-space clip is the layer that actually bounds it, which is what
    # protects the sequence encoder's sliding window (see
    # development/Problems.md's BTCUSD incident writeup).
    normal_values = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1, 9.9, 10.3]
    dataset = pd.DataFrame(
        {
            "ticker": ["CORE"] * 11,
            "split": ["train"] * 10 + ["backtest"],
            "feature": normal_values + [500_000.0],
        }
    )

    scaled, _, clip_sigma = fit_and_apply_scaler(dataset, ["feature"], clip_sigma=5.0)

    assert clip_sigma == 5.0
    assert scaled["feature_scaled"].max() == 5.0
    assert scaled["feature_scaled"].min() >= -5.0


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
    _, scaler, _ = fit_and_apply_scaler(dataset, ["feature"])
    manifest = {"feature_names": ["feature"]}

    active_mtime_before = SCALER_PATH.stat().st_mtime if SCALER_PATH.exists() else None

    candidate_scaler_path = tmp_path / "versions" / "v1" / "scaler.pkl"
    candidate_scaler_stats_path = tmp_path / "versions" / "v1" / "scaler_stats.json"

    write_scaler_artifacts(
        scaler,
        manifest,
        scaler_path=candidate_scaler_path,
        scaler_stats_path=candidate_scaler_stats_path,
        clip_sigma=7.5,
    )

    assert candidate_scaler_path.exists()
    assert candidate_scaler_stats_path.exists()
    stats = json.loads(candidate_scaler_stats_path.read_text(encoding="utf-8"))
    assert stats["clip_sigma"] == 7.5
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


def test_assess_regression_quality_flags_exploding_rmse_mae_ratio():
    # Mirrors the real sequence-model incident: backtest MAE 0.068 but
    # RMSE 2.09 (~31x) - a single poisoned feature row replicated across a
    # sliding window, invisible to any pre-existing gate since only
    # direction MCC/balanced-accuracy was ever checked (see
    # development/Problems.md).
    regression_metrics_by_split = {
        "train": {"mae": 0.02, "rmse": 0.04},
        "validation": {"mae": 0.03, "rmse": 0.05},
        "backtest": {"mae": 0.068, "rmse": 2.09},
    }
    training_config = {
        "quality_gate": {
            "max_rmse_mae_ratio": 4.0,
            "max_backtest_train_rmse_ratio": 3.0,
            "regression_watchlist_margin": 0.5,
        }
    }

    quality = assess_regression_quality(regression_metrics_by_split, training_config)

    assert quality["quality_status"] == "disabled_for_gating"
    assert quality["gating_eligible"] is False
    assert "rmse_mae_ratio_above_gate" in quality["failures"]
    assert "backtest_train_rmse_ratio_above_gate" in quality["failures"]
    assert quality["observed"]["backtest_rmse_mae_ratio"] > 30


def test_assess_regression_quality_marks_stable_model_as_stable():
    regression_metrics_by_split = {
        "train": {"mae": 0.02, "rmse": 0.035},
        "validation": {"mae": 0.025, "rmse": 0.04},
        "backtest": {"mae": 0.026, "rmse": 0.05},
    }
    training_config = {
        "quality_gate": {
            "max_rmse_mae_ratio": 4.0,
            "max_backtest_train_rmse_ratio": 3.0,
            "regression_watchlist_margin": 0.5,
        }
    }

    quality = assess_regression_quality(regression_metrics_by_split, training_config)

    assert quality["quality_status"] == "stable"
    assert quality["gating_eligible"] is True
    assert quality["failures"] == []


def test_assess_regression_quality_defaults_when_gate_config_absent():
    # No explicit quality_gate config block (matches assess_expert_quality's
    # own convention - production config.json has no explicit quality_gate
    # section either, relying entirely on this function's defaults).
    regression_metrics_by_split = {
        "train": {"mae": 0.02, "rmse": 0.035},
        "validation": {"mae": 0.025, "rmse": 0.04},
        "backtest": {"mae": 0.026, "rmse": 0.05},
    }

    quality = assess_regression_quality(regression_metrics_by_split, {})

    assert quality["thresholds"]["max_rmse_mae_ratio"] == 4.0
    assert quality["thresholds"]["max_backtest_train_rmse_ratio"] == 3.0
    assert quality["quality_status"] == "stable"


def test_assess_regression_quality_handles_zero_mae_without_false_positive():
    # A zero-valued denominator (e.g. an empty/degenerate split) must read
    # as "can't compute", never as an automatic gate failure.
    regression_metrics_by_split = {
        "train": {"mae": 0.0, "rmse": 0.0},
        "validation": {"mae": 0.0, "rmse": 0.0},
        "backtest": {"mae": 0.0, "rmse": 0.0},
    }

    quality = assess_regression_quality(regression_metrics_by_split, {})

    assert quality["observed"]["backtest_rmse_mae_ratio"] == 0.0
    assert quality["quality_status"] == "stable"


def test_masked_bce_with_logits_loss_ignores_masked_rows():
    logits = torch.tensor([5.0, -5.0, 0.0], dtype=torch.float32)
    targets = torch.tensor([1.0, 0.0, 1.0], dtype=torch.float32)
    mask = torch.tensor([True, True, False])

    loss_masked = masked_bce_with_logits_loss(logits, targets, mask)
    loss_direct = nn.functional.binary_cross_entropy_with_logits(logits[:2], targets[:2])

    assert torch.isclose(loss_masked, loss_direct)


def test_masked_bce_with_logits_loss_returns_zero_when_mask_all_false():
    logits = torch.tensor([5.0, -5.0], dtype=torch.float32)
    targets = torch.tensor([1.0, 0.0], dtype=torch.float32)
    mask = torch.tensor([False, False])

    loss = masked_bce_with_logits_loss(logits, targets, mask)

    assert loss.item() == 0.0


def test_masked_mse_loss_ignores_masked_rows():
    predictions = torch.tensor([1.0, 2.0, 100.0], dtype=torch.float32)
    targets = torch.tensor([1.0, 3.0, -100.0], dtype=torch.float32)
    mask = torch.tensor([True, True, False])

    loss_masked = masked_mse_loss(predictions, targets, mask)
    loss_direct = nn.functional.mse_loss(predictions[:2], targets[:2])

    assert torch.isclose(loss_masked, loss_direct)


def test_masked_mse_loss_returns_zero_when_mask_all_false():
    predictions = torch.tensor([1.0], dtype=torch.float32)
    targets = torch.tensor([100.0], dtype=torch.float32)
    mask = torch.tensor([False])

    assert masked_mse_loss(predictions, targets, mask).item() == 0.0


def test_compute_masked_binary_metrics_ignores_nan_targets():
    logits = torch.tensor([5.0, -5.0, 5.0], dtype=torch.float32)
    targets = torch.tensor([1.0, 0.0, float("nan")], dtype=torch.float32)
    criterion = nn.BCEWithLogitsLoss()

    metrics = compute_masked_binary_metrics(logits, targets, criterion, 0.5)

    assert metrics is not None
    assert metrics["mcc"] == pytest.approx(1.0)


def test_compute_masked_binary_metrics_returns_none_when_all_nan():
    logits = torch.tensor([5.0, -5.0], dtype=torch.float32)
    targets = torch.tensor([float("nan"), float("nan")], dtype=torch.float32)
    criterion = nn.BCEWithLogitsLoss()

    assert compute_masked_binary_metrics(logits, targets, criterion, 0.5) is None


def test_compute_masked_regression_metrics_ignores_nan_targets():
    predictions = torch.tensor([1.0, 2.0, 3.0], dtype=torch.float32)
    targets = torch.tensor([1.0, 2.0, float("nan")], dtype=torch.float32)

    metrics = compute_masked_regression_metrics(predictions, targets)

    assert metrics is not None
    assert metrics["mae"] == pytest.approx(0.0, abs=1e-6)


def test_compute_masked_regression_metrics_returns_none_when_all_nan():
    predictions = torch.tensor([1.0, 2.0], dtype=torch.float32)
    targets = torch.tensor([float("nan"), float("nan")], dtype=torch.float32)

    assert compute_masked_regression_metrics(predictions, targets) is None


def test_compute_rank_ic_perfect_correlation_gives_ic_of_one():
    dates = np.repeat(["2020-01-01", "2020-01-02", "2020-01-03"], 3)
    target_rank = np.tile([1.0, 0.5, 0.0], 3)
    predictions = np.tile([0.9, 0.5, 0.1], 3)  # same per-date ordering as target_rank

    result = compute_rank_ic(
        torch.tensor(predictions, dtype=torch.float32), torch.tensor(target_rank, dtype=torch.float32), dates
    )

    assert result["mean_ic"] == pytest.approx(1.0)
    assert result["num_dates"] == 3
    assert result["ic_values"] == pytest.approx([1.0, 1.0, 1.0])


def test_compute_rank_ic_anti_correlation_gives_ic_of_minus_one():
    dates = np.repeat(["2020-01-01", "2020-01-02", "2020-01-03"], 3)
    target_rank = np.tile([1.0, 0.5, 0.0], 3)
    predictions = np.tile([0.1, 0.5, 0.9], 3)  # reversed ordering

    result = compute_rank_ic(
        torch.tensor(predictions, dtype=torch.float32), torch.tensor(target_rank, dtype=torch.float32), dates
    )

    assert result["mean_ic"] == pytest.approx(-1.0)


def test_compute_rank_ic_skips_dates_with_nan_target():
    dates = np.array(["2020-01-01", "2020-01-01", "2020-01-02", "2020-01-02"])
    target_rank = np.array([1.0, 0.0, float("nan"), float("nan")])
    predictions = np.array([0.9, 0.1, 0.5, 0.5])

    result = compute_rank_ic(
        torch.tensor(predictions, dtype=torch.float32), torch.tensor(target_rank, dtype=torch.float32), dates
    )

    # Only 2020-01-01 has valid targets - the all-NaN 2020-01-02 must be
    # excluded, not counted as a zero-IC date.
    assert result["num_dates"] == 1


def test_compute_rank_ic_non_overlapping_stride_subsamples_dates():
    dates = np.repeat([f"2020-01-{day:02d}" for day in range(1, 11)], 2)
    target_rank = np.tile([1.0, 0.0], 10)
    predictions = np.tile([0.9, 0.1], 10)

    full = compute_rank_ic(
        torch.tensor(predictions, dtype=torch.float32), torch.tensor(target_rank, dtype=torch.float32), dates
    )
    strided = compute_rank_ic(
        torch.tensor(predictions, dtype=torch.float32),
        torch.tensor(target_rank, dtype=torch.float32),
        dates,
        non_overlapping_stride=5,
    )

    assert full["num_dates"] == 10
    assert strided["num_dates"] == 2


def test_compute_rank_ic_returns_zero_when_no_dates_have_enough_assets():
    dates = np.array(["2020-01-01"])
    target_rank = np.array([1.0])
    predictions = np.array([0.5])

    result = compute_rank_ic(
        torch.tensor(predictions, dtype=torch.float32), torch.tensor(target_rank, dtype=torch.float32), dates
    )

    assert result == {"mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0, "num_dates": 0, "ic_values": []}
