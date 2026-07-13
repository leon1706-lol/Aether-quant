"""Tests for train.py::add_asset_class_context_features() /
asset_class_by_ticker_from_config() - the 5-column asset-class one-hot
block (train.py::ASSET_CLASS_VALUES) letting the model condition on asset
class inside one shared, unified feature vector. Deliberately uses the
same "asset_"-prefixed naming as add_asset_context_features()'s per-ticker
one-hot so build_dataset_manifest()'s generic column.startswith("asset_")
filter picks these up automatically - see train.py::build_dataset_manifest().
"""

import pandas as pd

from train import ASSET_CLASS_VALUES, add_asset_class_context_features, asset_class_by_ticker_from_config


def test_add_asset_class_context_features_adds_five_columns():
    dataset = pd.DataFrame({"ticker": ["AAPL", "TLT", "BTCUSD"]})
    asset_class_by_ticker = {"AAPL": "equity", "TLT": "bond", "BTCUSD": "crypto"}

    result, columns = add_asset_class_context_features(dataset, asset_class_by_ticker)

    assert columns == [f"asset_class_{value}" for value in ASSET_CLASS_VALUES]
    for column in columns:
        assert column in result.columns


def test_add_asset_class_context_features_one_hot_is_correct_per_row():
    dataset = pd.DataFrame({"ticker": ["AAPL", "TLT", "BTCUSD", "ES", "SPY_OPT"]})
    asset_class_by_ticker = {"AAPL": "equity", "TLT": "bond", "BTCUSD": "crypto", "ES": "future", "SPY_OPT": "option"}

    result, _ = add_asset_class_context_features(dataset, asset_class_by_ticker)

    assert result.loc[result["ticker"] == "AAPL", "asset_class_equity"].iloc[0] == 1.0
    assert result.loc[result["ticker"] == "AAPL", "asset_class_bond"].iloc[0] == 0.0
    assert result.loc[result["ticker"] == "TLT", "asset_class_bond"].iloc[0] == 1.0
    assert result.loc[result["ticker"] == "BTCUSD", "asset_class_crypto"].iloc[0] == 1.0
    assert result.loc[result["ticker"] == "ES", "asset_class_future"].iloc[0] == 1.0
    assert result.loc[result["ticker"] == "SPY_OPT", "asset_class_option"].iloc[0] == 1.0


def test_add_asset_class_context_features_row_sums_to_exactly_one():
    dataset = pd.DataFrame({"ticker": ["AAPL", "TLT", "BTCUSD", "ES", "SPY_OPT"]})
    asset_class_by_ticker = {"AAPL": "equity", "TLT": "bond", "BTCUSD": "crypto", "ES": "future", "SPY_OPT": "option"}

    result, columns = add_asset_class_context_features(dataset, asset_class_by_ticker)

    row_sums = result[columns].sum(axis=1)
    assert (row_sums == 1.0).all()


def test_add_asset_class_context_features_missing_ticker_falls_back_to_equity():
    dataset = pd.DataFrame({"ticker": ["UNKNOWN"]})

    result, _ = add_asset_class_context_features(dataset, {})

    assert result.loc[0, "asset_class_equity"] == 1.0
    assert result.loc[0, "asset_class_bond"] == 0.0


# ---------------------------------------------------------------------------
# asset_class_by_ticker_from_config
# ---------------------------------------------------------------------------


def test_asset_class_by_ticker_from_config_prefers_explicit_asset_class():
    config = {"phase1": {"universe": {"assets": [{"ticker": "TLT", "security_type": "equity", "asset_class": "bond"}]}}}
    assert asset_class_by_ticker_from_config(config) == {"TLT": "bond"}


def test_asset_class_by_ticker_from_config_falls_back_to_security_type():
    config = {"phase1": {"universe": {"assets": [{"ticker": "AAPL", "security_type": "equity"}]}}}
    assert asset_class_by_ticker_from_config(config) == {"AAPL": "equity"}


def test_asset_class_by_ticker_from_config_covers_full_universe():
    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {"ticker": "AAPL", "security_type": "equity"},
                    {"ticker": "BTCUSD", "security_type": "crypto"},
                    {"ticker": "TLT", "security_type": "equity", "asset_class": "bond"},
                ]
            }
        }
    }
    result = asset_class_by_ticker_from_config(config)
    assert result == {"AAPL": "equity", "BTCUSD": "crypto", "TLT": "bond"}
