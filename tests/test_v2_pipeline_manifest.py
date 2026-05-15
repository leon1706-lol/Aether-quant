from data_pipeline import build_v2_pipeline_manifest


def test_v2_pipeline_manifest_declares_lean_data_as_training_and_backtest_source():
    config = {
        "name": "Aether Quant",
        "phase1": {
            "universe": {
                "name": "test_universe",
                "resolution": "Daily",
                "assets": [
                    {"ticker": "AAPL", "security_type": "equity"},
                    {"ticker": "BTCUSD", "security_type": "crypto"},
                ],
            },
            "windows": {
                "training": {"start": "2020-01-01", "end": "2020-06-30"},
                "validation": {"start": "2020-07-01", "end": "2020-08-31"},
                "backtest": {"start": "2020-09-01", "end": "2020-12-31"},
            },
            "features": {
                "input_set": ["return_1d"],
                "normalization": "fit train only",
            },
            "target": {"type": "directional_return"},
        },
    }
    dataset_manifest = {
        "training_eligible_assets": ["AAPL", "BTCUSD"],
        "trading_eligible_assets": ["AAPL"],
        "observation_only_assets": ["BTCUSD"],
    }

    manifest = build_v2_pipeline_manifest(config, dataset_manifest)

    assert manifest["data_source"]["type"] == "local_lean_data_folder"
    assert manifest["data_source"]["training_uses_lean_data_folder"] is True
    assert manifest["data_source"]["backtesting_uses_lean_data_folder"] is True
    assert manifest["universe"]["asset_group_counts"] == {"equity": 1, "crypto": 1}
    assert manifest["quality"]["observation_only_assets"] == ["BTCUSD"]
    assert "moe expert datasets" in manifest["consumers"]
