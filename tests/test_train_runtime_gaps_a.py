"""train.py's input checks, data-tree helpers, feature and target builders on small synthetic frames (V6.6.6, #359): each branch the pipeline run in test_train_pipeline_runtime.py does not reach."""

from __future__ import annotations

import builtins
import datetime
import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest
import torch

import train
import train_world as world


def frame_of(dates, **columns):
    return pd.DataFrame({"date": pd.to_datetime(dates), **columns})


# ---- inputs, data tree, crypto series -------------------------------------------------------------------------------


def test_every_kind_of_bad_training_input_is_reported_and_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(train, "ROOT", tmp_path)
    assert "No assets configured in phase1.universe.assets." in train.validate_training_inputs({})
    config = {"phase1": {"universe": {"assets": [{"ticker": "A"}, {"ticker": "B", "data_path": "data/b.zip"}, {"ticker": "C", "data_path": "data/c.zip", "derived_from": "x"}]},
                         "windows": {"training": {"start": "2020-01-01"}, "validation": {"start": "nope", "end": "2020-02-01"}, "backtest": {"start": "2020-03-01", "end": "2020-02-01"}}}}
    issues = train.validate_training_inputs(config)
    text = "\n".join(issues)
    assert "A: missing data_path." in text and "B: data file does not exist" in text and "C:" not in text
    assert "training: invalid date window" in text and "validation: invalid date window" in text and "backtest: start date is after end date." in text
    assert "Missing phase1.windows.backtest." in "\n".join(train.validate_training_inputs({"phase1": {"windows": {"training": {"start": "2020-01-01", "end": "2020-02-01"}}}}))
    with pytest.raises(ValueError, match="Training input validation failed"):
        train.raise_if_validation_failed(issues)
    train.raise_if_validation_failed([])


def write_minute_zip(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", "\n".join(rows) + "\n")


def test_a_derived_crypto_daily_series_skips_what_it_cannot_aggregate(monkeypatch, tmp_path):
    monkeypatch.setattr(train, "ROOT", tmp_path)

    def config(**asset):
        return {"phase1": {"universe": {"assets": [{"ticker": "X", "data_path": "data/out/x.zip", "derived_from": "data/minute", "aggregation": "daily_from_minute_trade", **asset}]}}}

    train.ensure_derived_crypto_daily_series({"phase1": {"universe": {"assets": [{"ticker": "Y", "data_path": "data/y.zip"}]}}})
    train.ensure_derived_crypto_daily_series(config())  # no source directory
    (tmp_path / "data" / "minute").mkdir(parents=True)
    train.ensure_derived_crypto_daily_series(config())  # no trade files
    write_minute_zip(tmp_path / "data" / "minute" / "notadate_trade.zip", ["0,1,2,0.5,1.5,10"])
    train.ensure_derived_crypto_daily_series(config())  # a file name that is not a date
    write_minute_zip(tmp_path / "data" / "minute" / "20200102_trade.zip", ["abc,x,y,z,w,v"])
    train.ensure_derived_crypto_daily_series(config())  # a day with no usable bars
    assert not (tmp_path / "data" / "out" / "x.zip").exists()
    write_minute_zip(tmp_path / "data" / "minute" / "20200103_trade.zip", ["60000,10,12,9,11,5", "120000,11,13,10,12,6"])
    train.ensure_derived_crypto_daily_series(config())
    with zipfile.ZipFile(tmp_path / "data" / "out" / "x.zip") as archive:
        assert archive.read(archive.namelist()[0]).decode().strip() == "20200103 00:00,10.0,13.0,9.0,12.0,11.0"


def test_the_data_tree_summary_and_zip_inspection_cover_a_missing_tree_and_an_empty_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(train, "ROOT", tmp_path)
    monkeypatch.setattr(train, "DATA_DIR", tmp_path / "data")
    assert train.summarize_data_tree() == {"available": False, "asset_groups": [], "sample_files": []}
    (tmp_path / "data" / "empty").mkdir(parents=True)
    with zipfile.ZipFile(tmp_path / "data" / "empty" / "e.zip", "w") as archive:
        archive.writestr("e.csv", "")
    inspected = train.inspect_zip_timeseries("data/empty/e.zip")
    assert inspected["available"] and inspected["rows"] == 0 and inspected["start"] is None
    assert train.inspect_zip_timeseries("data/none.zip")["available"] is False
    summary = train.summarize_data_tree(limit=1)
    assert summary["available"] and summary["asset_groups"] == [{"name": "empty", "files": 1}] and len(summary["sample_files"]) == 1


def test_assets_are_synchronised_to_their_common_dates():
    a = frame_of(["2020-01-01", "2020-01-02", "2020-01-03"], close=[1, 2, 3])
    b = frame_of(["2020-01-02", "2020-01-03", "2020-01-04"], close=[4, 5, 6])
    synced, dates = train.synchronize_assets({"A": a, "B": b})
    assert [d.day for d in dates] == [2, 3] and len(synced["A"]) == 2 and list(synced["B"]["close"]) == [4, 5]
    assert train.synchronize_assets({})[1] == []


def test_resident_memory_is_read_from_proc_when_it_exists_and_logged(monkeypatch):
    PROC_STATUS = "Name:\tpython\nVmRSS:\t2048 kB\nVmHWM:\t4096 kB\n"
    real_open = builtins.open
    monkeypatch.setattr(train, "open", lambda path, *a, **k: io.StringIO(PROC_STATUS) if path == "/proc/self/status" else real_open(path, *a, **k), raising=False)
    assert train.resident_memory_mb() == (2.0, 4.0)
    lines = []
    monkeypatch.setattr(train.LOGGER, "info", lambda message, *args: lines.append(message % args))
    train.log_resident_memory("probe")
    assert lines == ["memory probe: rss=2 MB peak=4 MB"]
    monkeypatch.setattr(train, "open", lambda *a, **k: io.StringIO("Name:\tpython\n"), raising=False)
    assert train.resident_memory_mb() is None


# ---- features and targets -------------------------------------------------------------------------------------------


def test_extra_horizon_targets_are_derived_bounded_and_the_purge_must_cover_them():
    assert train.resolve_extra_horizon_days({"phase1": {"target": {"ranking": {"extra_horizon_days": [5, 10, 20, 60]}}, "windows": {"purge_label_horizon_days": 60}}}) == (10, 60)
    with pytest.raises(ValueError, match="shorter than the 60-day target"):
        train.resolve_extra_horizon_days({"phase1": {"target": {"ranking": {"extra_horizon_days": [60]}}, "windows": {"purge_label_horizon_days": 20}}})
    assert train.extra_horizon_return_bound(80, "crypto", {"crypto": 4.0, "equity": 1.5}) == pytest.approx(8.0)
    assert train.extra_horizon_return_bound(20, "future", {"equity": 1.5}) == pytest.approx(1.5)
    rng = np.random.default_rng(1)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 120)))
    raw = frame_of(pd.date_range("2020-01-01", periods=120).strftime("%Y-%m-%d"), open=closes, high=closes * 1.01, low=closes * 0.99, close=closes, volume=1e6)
    windows = {"training": {"start": "2020-01-01", "end": "2020-03-01"}, "validation": {"start": "2020-03-02", "end": "2020-04-01"}, "backtest": {"start": "2020-04-02", "end": "2020-06-01"},
               "purge_label_horizon_days": 40, "purge_label_calendar_days": 7}
    engineered = train.engineer_features(raw, ["close_to_close_return_1d"], windows, extra_horizon_days=(10, 40))
    assert {"target_return_10d", "target_return_40d"} <= set(engineered.columns) and (engineered["split"] == "purged").any()


def test_holiday_bars_are_dropped_only_when_there_are_holidays_and_a_forex_frame_with_no_rows_stays_empty():
    frame = frame_of(["2020-01-01", "2020-01-02"], close=[1.0, 2.0])
    assert train.drop_lean_holiday_bars(frame, frozenset()) is frame
    assert train.drop_lean_holiday_bars(frame.iloc[0:0], frozenset({1})) .empty
    empty = frame_of([], open=[], high=[], low=[], close=[], volume=[], ticker=[], security_type=[], market=[])
    result = train.engineer_forex_features_on_lean_calendar(empty, ["close_to_close_return_1d"], world.WINDOWS)
    assert result.empty


def test_regime_features_exist_even_on_an_empty_frame():
    result = train.add_regime_features(pd.DataFrame({"date": pd.to_datetime([])}))
    assert result.empty and set(train.REGIME_ENCODED_FEATURE_NAMES) <= set(result.columns)


def test_a_sensitivity_run_with_fewer_drivers_still_writes_every_feature_column():
    dates = pd.date_range("2020-01-01", periods=40).strftime("%Y-%m-%d")
    frames = {"A": frame_of(dates, close_to_close_return_1d=np.linspace(-0.01, 0.01, 40))}
    config = {"phase1": {"features": {"cross_asset_sensitivity": {"enabled": True, "lookback_days": 20, "min_observations": 5, "drivers": {"vix": "implied_volatility_vix"}}}}}
    fred = {"implied_volatility_vix": [{"date": datetime.date.fromisoformat(d), "value": 15.0 + i * 0.1} for i, d in enumerate(dates)]}
    result = train.build_cross_asset_sensitivity_features(frames, config, fred)["A"]
    assert set(train.CROSS_ASSET_SENSITIVITY_FEATURE_NAMES) <= set(result.columns)
    assert (result["sens_dollar_beta"] == 0.0).all()


def test_option_rows_that_cannot_be_priced_are_skipped_in_the_derivatives_features():
    dates = ["2020-01-02", "2020-01-03", "2020-03-20"]
    spot = frame_of(dates, close=[100.0, 0.0, 100.0], volume=[1.0, 1.0, 1.0])
    option = frame_of(dates, close=[5.0, 5.0, 5.0], volume=[10.0, 10.0, 10.0])
    expired = frame_of(dates, close=[5.0, 5.0, 5.0], volume=[10.0, 10.0, 10.0])
    absurd = frame_of(dates, close=[0.0001, 0.0001, 0.0001], volume=[10.0, 10.0, 10.0])
    config = {"phase1": {"universe": {"assets": [
        {"ticker": "SPY", "security_type": "equity"},
        {"ticker": "C1", "security_type": "option", "asset_class": "option", "underlying_ticker": "SPY", "right": "call", "strike": 100.0, "expiry": "2020-06-19"},
        {"ticker": "C2", "security_type": "option", "asset_class": "option", "underlying_ticker": "SPY", "right": "put", "strike": 100.0, "expiry": "2020-01-01"},
        {"ticker": "C3", "security_type": "option", "asset_class": "option", "underlying_ticker": "SPY", "right": "call", "strike": 10.0, "expiry": "2020-06-19"},
        {"ticker": "C4", "security_type": "option", "asset_class": "option", "underlying_ticker": "SPY", "right": "straddle", "strike": 100.0, "expiry": "2020-06-19"}]}}}
    result = train.build_derivatives_macro_features_by_date({"SPY": spot, "C1": option, "C2": expired, "C3": absurd, "C4": option}, config)
    assert len(result["SPY"]) == 3 and np.isfinite(result["SPY"]["options_put_call_ratio"]).all()


def synthetic_universe(count=24, dates=60, seed=0):
    rng = np.random.default_rng(seed)
    labels = pd.date_range("2020-01-01", periods=dates).strftime("%Y-%m-%d")
    market = rng.normal(0, 0.01, dates)
    frames = {"MKT": frame_of(labels, target_return_5d=market, target_return_20d=market, close_to_close_return_1d=market, liquidity_log_dollar_volume=18.0)}
    for index in range(count):
        noise = rng.normal(0, 0.01, dates)
        own = (0.5 + index / count) * market + noise
        frames[f"T{index:02d}"] = frame_of(labels, target_return_5d=own, target_return_20d=own, close_to_close_return_1d=own, liquidity_log_dollar_volume=15.0 + index % 5)
    return frames


def residual_config(tmp_path, **ranking):
    mapping = tmp_path / "sectors.json"
    mapping.write_text(json.dumps({f"T{index:02d}": ("tech" if index % 2 else "energy") for index in range(24)}), encoding="utf-8")
    return {"phase1": {"target": {"ranking": {"beta_estimation": "asof", "sector_neutral": {"mapping_path": str(mapping)},
                                               "residual_neutral": {"enabled": True, "market": True, "sector": True, "size": True, "market_ticker": "MKT", "min_universe_size": 10,
                                                                    "min_beta_observations": 20, "size_proxy_column": "liquidity_log_dollar_volume"}, **ranking}}}}


def test_residual_ranks_use_the_as_of_beta_the_sector_dummies_and_the_size_factor(tmp_path):
    result = train.build_residual_rank_targets(synthetic_universe(), residual_config(tmp_path))
    ranks = pd.concat(result.values())["target_residual_rank_20d"].dropna()
    assert len(ranks) > 500 and ranks.between(0.0, 1.0).all()
    no_returns = {name: frame.assign(target_return_5d=np.nan, target_return_20d=np.nan) for name, frame in synthetic_universe().items()}
    empty = train.build_residual_rank_targets(no_returns, residual_config(tmp_path))
    assert all(frame["target_residual_rank_5d"].isna().all() for frame in empty.values())


def test_the_as_of_helpers_degrade_without_a_return_column_or_a_market():
    frame = frame_of(["2020-01-01"], close=[1.0])
    assert train._asof_betas(frame, {}) == [0.0]
    assert train._market_daily_by_date(None) == {} and train._market_daily_by_date(frame) == {}
    assert train._asof_betas(frame_of(["2020-01-01", "2020-01-02"], close_to_close_return_1d=[0.01, 0.02]), {}) == [0.0, 0.0]


def test_the_as_of_beta_also_feeds_the_cross_sectional_rank_targets(tmp_path):
    frames = synthetic_universe()
    config = residual_config(tmp_path)
    ranking = config["phase1"]["target"]["ranking"]
    ranking.update({"horizon_days": [5, 20], "min_universe_size": 10, "beta_neutral": {"market_ticker": "MKT", "min_observations": 20}, "sector_neutral": {**ranking["sector_neutral"], "min_sector_size": 3}})
    result = train.build_cross_sectional_rank_targets(frames, config)
    assert "target_beta_neutral_rank_20d" in result["T01"].columns


# ---- asset quality, scaler, holdout -------------------------------------------------------------------------------


def test_asset_quality_tiers_follow_the_row_counts_and_the_history_basis():
    dataset = pd.DataFrame({"ticker": ["A"] * 6 + ["B"] * 3 + ["C"] * 1, "split": ["train"] * 3 + ["validation"] * 2 + ["backtest"] * 1 + ["train"] * 2 + ["backtest"] + ["train"]})
    metadata = {"asset_summaries": [{"ticker": "A", "feature_rows": 6}, {"ticker": "B", "feature_rows": 3}, {"ticker": "C", "feature_rows": 1}, {"ticker": "D", "feature_rows": 0}]}
    config = {"phase1": {"universe": {"assets": [{"ticker": t, "security_type": "equity", "market": "usa"} for t in "ABCD"]}},
              "phase9": {"asset_quality": {"min_total_feature_rows": 2, "min_training_rows": 5, "min_backtest_rows": 1, "trading_eligibility_basis": "history", "min_trading_history_rows": 3}}}
    quality = train.build_asset_quality(config, dataset, metadata)
    assert quality["A"]["role"] == "trading_without_training_rows" and quality["B"]["quality_tier"] == "thin"
    assert quality["C"]["quality_tier"] == "insufficient" and quality["D"]["quality_tier"] == "insufficient" and not quality["D"]["trading_eligible"]


def test_a_scaler_needs_training_rows_and_a_saved_scaler_applies_the_same_transform(tmp_path):
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0], "split": ["backtest"] * 3, "training_eligible": [True] * 3})
    with pytest.raises(ValueError, match="No training-eligible rows"):
        train.fit_and_apply_scaler(frame, ["x"])
    stats = {"feature_names": ["x", "y"], "mean": [1.0, 0.0], "scale": [2.0, 0.0], "clip_sigma": 2.0}
    scaled = train.apply_scaler_stats(pd.DataFrame({"x": [1.0, 9.0, -9.0], "y": [3.0, 4.0, 5.0]}), stats)
    assert scaled["x_scaled"].tolist() == [0.0, 2.0, -2.0] and scaled["y_scaled"].tolist() == [2.0, 2.0, 2.0]


def test_the_holdout_config_reads_from_the_holdout_root_and_drops_assets_without_a_zip(monkeypatch, tmp_path):
    monkeypatch.setattr(train, "ROOT", tmp_path)
    (tmp_path / "data_holdout" / "equity").mkdir(parents=True)
    (tmp_path / "data_holdout" / "equity" / "a.zip").write_bytes(b"x")
    config = {"phase1": {"universe": {"assets": [{"ticker": "A", "data_path": "data/equity/a.zip"}, {"ticker": "B", "data_path": "data/equity/b.zip"}, {"ticker": "C", "data_path": "elsewhere/c.zip"}], "common_window": {"start": "2020-01-01", "end": "2020-12-31"}},
                         "windows": {"training": {"start": "2020-01-01", "end": "2020-06-30"}, "validation": {"start": "2020-07-01", "end": "2020-09-30"}}}}
    holdout, dropped = train.build_holdout_config(config, "data_holdout", "2021-01-01", "2021-06-30")
    assert dropped == ["B", "C"] and holdout["phase1"]["universe"]["assets"][0]["data_path"] == "data_holdout/equity/a.zip"
    assert holdout["phase1"]["universe"]["common_window"]["end"] == "2021-06-30" and holdout["phase1"]["windows"]["backtest"] == {"start": "2021-01-01", "end": "2021-06-30"}
    assert config["phase1"]["universe"]["assets"][0]["data_path"] == "data/equity/a.zip"


# ---- model building blocks -------------------------------------------------------------------------------------------


def test_activations_and_normalisations_are_built_by_name_and_unknown_names_are_refused():
    assert isinstance(train.build_activation("GELU"), torch.nn.GELU) and isinstance(train.build_activation("silu"), torch.nn.SiLU)
    with pytest.raises(ValueError, match="Unsupported activation"):
        train.build_activation("tanh")
    assert isinstance(train.build_normalization("batchnorm", 4), torch.nn.BatchNorm1d) and train.build_normalization("off", 4) is None
    with pytest.raises(ValueError, match="Unsupported normalization"):
        train.build_normalization("weird", 4)


def test_a_multitask_network_gets_a_head_per_extra_horizon_and_every_layer_kind_is_exported(monkeypatch):
    model = train.AetherNetMultiTaskHorizons(input_dim=4, hidden_layers=[6], dropout=0.1, activation="gelu", normalization="batchnorm", extra_heads=("rank_5d",))
    assert hasattr(model, "head_rank_5d")
    sequential = torch.nn.Sequential(torch.nn.Linear(4, 4), torch.nn.BatchNorm1d(4), torch.nn.GELU(), torch.nn.SiLU(), torch.nn.Dropout(0.2), torch.nn.Tanh())
    kinds = [layer["type"] for layer in train._export_sequential_layers(sequential, "net")]
    assert kinds == ["linear", "batchnorm1d", "gelu", "silu", "dropout", "tanh"]
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    seen = []
    monkeypatch.setattr(torch.cuda, "manual_seed_all", lambda seed: seen.append(seed))
    train.set_seed(3)
    assert seen and set(seen) == {3}


def test_the_ranking_losses_skip_groups_of_one_and_return_zero_when_nothing_is_left():
    predictions = torch.tensor([0.1, 0.4, 0.3])
    targets = torch.tensor([0.2, 0.5, 0.1])
    groups = torch.tensor([0, 1, 2])
    mask = torch.ones(3, dtype=torch.bool)
    assert float(train.soft_spearman_loss(predictions, targets, groups, mask, 0.1)) == 0.0
    assert float(train.listnet_loss(predictions, targets, groups, mask, 0.1)) == 0.0
    mixed = torch.tensor([0, 0, 1])
    assert float(train.soft_spearman_loss(predictions, targets, mixed, mask, 0.1)) != 0.0 and float(train.listnet_loss(predictions, targets, mixed, mask, 0.1)) != 0.0


def test_horizon_heads_merge_over_the_defaults_and_rank_labels_can_be_noised():
    resolved = train.resolve_horizon_head_config({"horizon_heads": {name: {"loss_weight": 0.3} for name in train.EXTRA_HORIZON_HEAD_SPECS}})
    assert all(resolved[name]["enabled"] is False and resolved[name]["loss_weight"] == 0.3 for name in train.EXTRA_HORIZON_HEAD_SPECS)
    specs = {"rank_20d": ("c", "rank", 20), "direction_5d": ("d", "binary", None), "short": ("e", "rank", 5), "missing": ("f", "rank", 5)}
    targets = {"rank_20d": torch.linspace(0, 1, 10), "direction_5d": torch.ones(10), "short": torch.tensor([float("nan")] * 9 + [0.5])}
    assert train.add_rank_label_noise(targets, specs, 0.0, None) is targets
    noisy = train.add_rank_label_noise(targets, specs, 0.1, torch.Generator().manual_seed(0))
    assert not torch.equal(noisy["rank_20d"], targets["rank_20d"]) and torch.equal(noisy["direction_5d"], targets["direction_5d"]) and torch.allclose(noisy["short"], targets["short"], equal_nan=True)
    assert float(noisy["rank_20d"].min()) >= 0.0 and float(noisy["rank_20d"].max()) <= 1.0


def test_the_quality_gates_report_near_misses_and_a_nested_metric_that_is_absent():
    config = {"quality_gate": {"min_validation_balanced_accuracy": 0.5, "min_backtest_balanced_accuracy": 0.5, "min_backtest_mcc": 0.0, "max_train_backtest_balanced_accuracy_gap": 0.1, "watchlist_margin": 0.05}}
    near = {"validation": {"balanced_accuracy": 0.6}, "backtest": {"balanced_accuracy": 0.52, "mcc": 0.02}, "train": {"balanced_accuracy": 0.6}}
    assessed = train.assess_expert_quality(near, config)
    assert assessed["quality_status"] == "watchlist" and {"backtest_balanced_accuracy_near_gate", "backtest_mcc_near_gate", "train_backtest_gap_near_limit"} <= set(assessed["near_misses"])
    failing = train.assess_expert_quality({"validation": {"balanced_accuracy": 0.6}, "backtest": {"balanced_accuracy": 0.6, "mcc": 0.1}, "train": {"balanced_accuracy": 0.9}}, config)
    assert "train_backtest_gap_too_large" in failing["failures"] and failing["quality_status"] == "disabled_for_gating"
    assert train.extract_metric_by_path({"a": {"b": None}}, "a.b") is None


def test_the_regression_gate_flags_a_ratio_close_to_its_limit_as_a_watchlist_status():
    config = {"quality_gate": {"max_rmse_mae_ratio": 1.5, "max_backtest_train_rmse_ratio": 2.0, "regression_watchlist_margin": 0.2}}
    result = train.assess_regression_quality({"train": {"rmse": 1.0}, "backtest": {"rmse": 1.4, "mae": 1.0}}, config)
    assert result["quality_status"] == "watchlist" and "rmse_mae_ratio_near_gate" in result["near_misses"]
