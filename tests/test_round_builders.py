"""evaluation/round_builders.py: a round names a builder from a closed set, and a missing input is a trial that did not run (V6.6.4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.round_builders import BUILDERS, MissingInput, apply_gate, build_trial_table

DAYS = [day.strftime("%Y-%m-%d") for day in pd.date_range("2021-01-01", periods=260)]
COINS = ["BTCUSD", "ETHUSD", "AAAUSD", "BBBUSD"]


class _Cell:
    def __init__(self, root=None):
        known = pd.DataFrame(100.0 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.03, (260, 4)), axis=0)), index=DAYS, columns=COINS)
        self.context = type("Context", (), {"panel": type("Panel", (), {"known": known, "fred": {}})()})()
        self.features = {"liquid": pd.DataFrame(True, index=DAYS, columns=COINS), "quote_volume": pd.DataFrame(1e6, index=DAYS, columns=COINS)}
        self.root = root
        self.data_dir = "data_wide"


def test_every_builder_is_a_name_in_the_closed_set_and_nothing_else_resolves():
    assert {"low_vol", "amihud", "similarity_table", "term_credit_timing", "cross_asset_trend"} <= set(BUILDERS)
    for hostile in ("os.system", "__import__", "eval", "", "LOW_VOL"):
        with pytest.raises(KeyError):
            build_trial_table(hostile, {}, _Cell())


def test_a_price_builder_needs_no_reference_file():
    table = build_trial_table("low_vol", {"window": 30}, _Cell())
    assert table.shape == (260, 4) and table.iloc[40:].notna().all().all()


def test_a_builder_that_reads_a_reference_file_says_so_when_it_is_missing(tmp_path):
    with pytest.raises(MissingInput):
        build_trial_table("similarity_table", {}, _Cell(root=tmp_path))
    with pytest.raises(MissingInput):
        build_trial_table("announcement_proximity", {}, _Cell(root=None))
    with pytest.raises(MissingInput):
        build_trial_table("term_credit_timing", {"ticker": "SPY"}, _Cell(root=tmp_path))


def test_a_builder_that_needs_a_feature_the_cell_lacks_says_so():
    cell = _Cell()
    cell.features = {}
    with pytest.raises(MissingInput):
        build_trial_table("amihud", {}, cell)


def test_cross_asset_trend_takes_its_tickers_from_the_rule_file_as_a_list():
    table = build_trial_table("cross_asset_trend", {"tickers": ["BTCUSD", "ETHUSD"], "long": 200, "skip": 20}, _Cell())
    assert set(table.columns[table.notna().any()]) == {"BTCUSD", "ETHUSD"}


def test_the_regime_gate_is_the_only_gate_and_an_unknown_one_is_an_error():
    cell = _Cell()
    table = pd.DataFrame(1.0, index=DAYS, columns=COINS)
    gated = apply_gate(table, "regime", cell)
    assert gated.isna().all(axis=1).any() and gated.notna().any().any()
    assert apply_gate(table, None, cell) is table
    with pytest.raises(KeyError):
        apply_gate(table, "volatility", cell)
