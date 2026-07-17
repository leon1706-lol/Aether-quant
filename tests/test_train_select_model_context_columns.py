"""Tests for train.py::select_model_context_columns() - the one place that
decides which "asset_"-prefixed dataset columns become actual model inputs
(development/Problems.md). Collapses the old 35-column asset context (30
per-ticker one-hots + 5 asset-class one-hots) down to just the 5 asset_class_*
columns - per-ticker identity flags can only encode a ticker's own base rate,
pushing the net toward a constant per-asset output.
"""

from train import select_model_context_columns


def test_select_model_context_columns_keeps_only_asset_class_columns():
    columns = ["close_scaled", "asset_class_equity", "asset_class_bond", "asset_AAPL", "asset_TLT", "regime_bullish"]

    selected = select_model_context_columns(columns)

    assert selected == ["asset_class_equity", "asset_class_bond"]


def test_select_model_context_columns_excludes_per_ticker_one_hots():
    columns = ["asset_AAPL", "asset_SPY", "asset_BTCUSD"]

    assert select_model_context_columns(columns) == []


def test_select_model_context_columns_empty_when_no_asset_context_present():
    assert select_model_context_columns(["close_scaled", "rsi_14_scaled"]) == []


def test_select_model_context_columns_preserves_column_order():
    columns = ["asset_class_option", "asset_class_bond", "asset_class_equity"]

    assert select_model_context_columns(columns) == ["asset_class_option", "asset_class_bond", "asset_class_equity"]
