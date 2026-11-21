"""features/feature_registry.py: every feature resolves, reads closes up to its own date only, and the sets and groups hold."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from features import feature_registry as registry
from features import technical_indicators


def _closes(rows: int = 320, names: int = 5, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = [str(day.date()) for day in pd.bdate_range("2022-01-03", periods=rows)]
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (rows, names)), axis=0)), index=index, columns=[f"T{i}" for i in range(names)])


def test_every_feature_builds_and_uses_only_its_past():
    closes = _closes()
    full = registry.build_wide(closes, "all")
    prefix = registry.build_wide(closes.iloc[:280], "all")
    for name, table in full.items():
        assert table.shape == closes.shape, name
        pd.testing.assert_frame_equal(table.iloc[:280], prefix[name], check_exact=False, atol=1e-12, obj=name)
        assert not np.isinf(table.to_numpy(dtype=float)).any()
        lookback = registry.FEATURES[name].lookback
        assert table.iloc[lookback + 1:].notna().to_numpy().mean() > 0.9, name


def test_sets_resolve_in_order_without_duplicates_and_unknown_names_say_what_is_close():
    assert registry.resolve("example") == ["ret_1", "ret_5", "ret_20", "ret_60", "vol_20", "vol_60"]
    assert registry.resolve("ret_5, momentum") == ["ret_5", "ret_20", "ret_60", "ret_120", "mom_12_1", "rev_5"]
    assert registry.resolve(["vol_20", "vol_20", ""]) == ["vol_20"]
    assert set(registry.resolve("all")) == set(registry.FEATURES)
    with pytest.raises(KeyError, match="did you mean .*ret_20"):
        registry.resolve("ret_21")
    with pytest.raises(KeyError, match="unknown feature 'zzz'"):
        registry.resolve("zzz")


def test_the_long_table_drops_empty_rows_and_the_catalog_and_groups_describe_it():
    closes = _closes(rows=60)
    closes.iloc[:, 0] = np.inf
    long = registry.build_long(closes, ["ret_1", "ret_5"])
    assert list(long.columns) == ["date", "ticker", "ret_1", "ret_5"]
    assert long[["ret_1", "ret_5"]].notna().any(axis=1).all() and "T0" not in set(long["ticker"])
    rows = registry.catalog()
    assert {row["name"] for row in rows} == set(registry.FEATURES) and all(row["description"] for row in rows)
    assert dict(registry.groups_of(["ret_1", "vol_20", "custom"])) == {"momentum": ["ret_1"], "volatility": ["vol_20"], "other": ["custom"]}


def test_the_technical_features_are_the_shared_indicators_over_a_window():
    closes = _closes(rows=80, names=1)
    rsi = registry.build_wide(closes, ["rsi_14"])["rsi_14"].iloc[-1, 0]
    assert rsi == pytest.approx(technical_indicators.relative_strength_index(list(closes.iloc[-15:, 0]), 14))
    public = {name for name, value in inspect.getmembers(technical_indicators, inspect.isfunction) if value.__module__ == technical_indicators.__name__}
    wrapped = {"relative_strength_index", "bollinger_pctb", "macd_histogram_normalized"}
    assert wrapped <= public


def test_the_ratio_feature_is_missing_where_long_volatility_is_zero():
    closes = pd.DataFrame({"A": [100.0] * 80}, index=[str(day.date()) for day in pd.bdate_range("2023-01-02", periods=80)])
    assert registry.build_wide(closes, ["vol_ratio_20_60"])["vol_ratio_20_60"].isna().all().all()
