"""evaluation/wide_context.py on synthetic wide roots (V6.6.6, #359): an equity cell with prices, sectors, membership, raw closes and fundamentals, a crypto cell with quote volume and funding, the holdout
cells staying closed, and the small helpers (lagging a table onto a calendar, a signal's rank IC, the holdout liquidity mask)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import wide_world
from evaluation import wide_context
from evaluation.research_cells import CELLS


@pytest.fixture(scope="module")
def equity(tmp_path_factory):
    root, base = wide_world.build_equity_root(tmp_path_factory.mktemp("wide_equity"))
    return root, base, wide_context.equity_cell(root, base, "SV", data_dir="data_wide")


def test_an_equity_cell_holds_its_side_of_the_names_with_features_membership_and_sectors(equity):
    root, base, cell = equity
    assert cell.cell.name == "SV" and cell.bars is not None and cell.member is not None and cell.label is not None
    assert set(wide_world.side_a_equities()) <= set(cell.context.market.tickers) and "gp_assets" in cell.features and cell.sectors["SPY"] == wide_context.BENCHMARK_CLASS
    assert {"sue", "accruals_ttm", "noa", "capex_growth"} <= set(cell.features) and cell.sectors["TLT"] == wide_context.BOND_ETF_CLASS and cell.sectors["XLK"] == wide_context.SECTOR_ETF_CLASS
    assert cell.member.loc[:, wide_world.side_a_equities()[0]].any() and cell.context.market.dates[-1] <= CELLS["SV"].end


def test_a_cell_without_the_info_files_or_the_features_still_opens(tmp_path):
    root, base = wide_world.build_equity_root(tmp_path, with_info=False)
    bare = wide_context.equity_cell(root, base, "SV", data_dir="data_wide", with_info=False)
    assert "gp_assets" not in bare.features and bare.bars is not None
    prices_only = wide_context.equity_cell(root, base, "SV", data_dir="data_wide", with_features=False)
    assert prices_only.bars is None and prices_only.features == {}


def test_a_held_out_cell_and_a_cell_of_the_wrong_universe_do_not_open(equity):
    root, base, _ = equity
    with pytest.raises(PermissionError):
        wide_context.equity_cell(root, base, "V3", data_dir="data_wide")
    with pytest.raises(ValueError, match="is a crypto cell"):
        wide_context.equity_cell(root, base, "CS", data_dir="data_wide")


def test_a_crypto_cell_reads_binance_coins_their_liquidity_and_funding(tmp_path):
    root, base, coins = wide_world.build_crypto_root(tmp_path)
    cell = wide_context.crypto_cell(root, base, "CS", data_dir="data_crypto_wide")
    assert "BTCUSD" in cell.context.market.tickers and {"quote_volume", "liquid", "funding"} <= set(cell.features) and cell.member.shape[1] == len(cell.context.market.tickers)
    one_side = wide_context.crypto_cell(root, base, "CS", data_dir="data_crypto_wide", side="A")
    assert one_side.member.any().any()
    with pytest.raises(ValueError, match="not a crypto cell"):
        wide_context.crypto_cell(root, base, "SV", data_dir="data_crypto_wide")


def test_a_crypto_cell_without_funding_has_no_funding_feature(tmp_path):
    root, base, _ = wide_world.build_crypto_root(tmp_path, funding=False)
    cell = wide_context.crypto_cell(root, base, "CS", data_dir="data_crypto_wide")
    assert "funding" not in cell.features and "quote_volume" in cell.features


def test_a_day_indexed_table_is_visible_from_the_next_day_and_carried_forward_at_most_a_limit():
    table = pd.DataFrame({"A": [1.0, 2.0, np.nan]}, index=["2020-01-01", "2020-01-02", "2020-01-03"])
    index = pd.Index(["2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05", "2020-01-06"])
    lagged = wide_context.lag_onto(table, index, limit=1)
    assert lagged["A"].iloc[:3].tolist() == [1.0, 2.0, 2.0] and lagged["A"].iloc[3:].isna().all()


def test_the_holdout_crypto_cell_hides_side_a_coins_until_the_selection_window_has_been_read():
    index = pd.Index(["2020-01-01", "2023-06-01"])
    liquid = pd.DataFrame(True, index=index, columns=["BTCUSD", "CQ999USD"])
    assert wide_context.liquid_mask_for_cell(liquid, CELLS["CS"], ["BTCUSD"]) is liquid
    masked = wide_context.liquid_mask_for_cell(liquid, CELLS["CV"], ["BTCUSD"])
    assert not masked.loc["2020-01-01", "BTCUSD"] and masked.loc["2023-06-01", "BTCUSD"]


def test_a_signal_that_ranks_the_label_has_a_positive_ic_and_a_crypto_one_reads_the_forward_return():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2020-01-01", periods=80).strftime("%Y-%m-%d")
    label = pd.DataFrame(rng.normal(size=(80, 30)), index=dates, columns=[f"T{n}" for n in range(30)])
    signal = label + rng.normal(scale=0.5, size=label.shape)
    result = wide_context.signal_ic_t(signal, label, start=dates[0], end=dates[-1], horizon=5, min_names=10)
    assert result["mean_ic"] > 0.3 and result["num_dates"] == 80
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, (120, 12)), axis=0)), index=pd.bdate_range("2020-01-01", periods=120).strftime("%Y-%m-%d"), columns=[f"C{n}" for n in range(12)])
    ic = wide_context.crypto_ic(known.pct_change(5), known, start=known.index[10], end=known.index[-30], min_names=8, horizon=5)
    assert ic["num_dates"] > 0


def test_a_cell_with_no_session_inside_its_window_has_no_calendar_rows():
    market = wide_context.MarketPanel(["2030-01-01", "2030-01-02"], ["A"], np.ones((2, 1)), np.ones((2, 1)), {"A": "equity"}, {"2030-01-01", "2030-01-02"}) if hasattr(wide_context, "MarketPanel") else None
    assert market is not None and wide_context.calendar_rows(market, CELLS["SV"], warmup_sessions=5) == []


def test_a_ticker_with_no_zip_is_left_out_of_the_ohlcv_tables(equity):
    root, _, _ = equity
    rows = ["2018-01-02", "2018-01-03"]
    tables = wide_context.load_ohlcv(root, ["SPY", "NOZIP"], rows, data_dir="data_wide")
    assert list(tables["open"].columns) == ["SPY", "NOZIP"] and tables["open"]["NOZIP"].isna().all() and tables["open"]["SPY"].notna().all()


def test_a_crypto_cell_of_the_other_side_still_holds_bitcoin_as_the_market(tmp_path):
    root, base, _ = wide_world.build_crypto_root(tmp_path)
    cell = wide_context.crypto_cell(root, base, "CS", data_dir="data_crypto_wide", side="B")
    assert "BTCUSD" in cell.context.market.tickers and not cell.member["BTCUSD"].any()


def test_a_book_is_run_and_its_sharpe_read_at_the_given_sessions(equity):
    _, _, cell = equity
    start, end = "2019-01-02", "2019-12-31"
    series = wide_context.daily_returns_for(cell.context, {}, start=start, end=end)
    sessions = sorted(cell.context.market.sessions)
    from evaluation.premia_research import annual_sharpe

    assert len(series) > 200 and series.abs().max() < 1e-9
    assert wide_context.sharpe_at_sessions(series, sessions) == annual_sharpe(series, sessions=sessions)


def test_the_model_audit_scores_each_feature_group_with_the_cells_own_ic_function(equity):
    from evaluation import model_audit

    _, _, cell = equity
    report = model_audit.feature_group_ic(cell, horizons=(5,))
    assert set(report) == set(model_audit.FEATURE_GROUPS) and report["price_momentum"]["5"]["num_dates"] == 0  # fourteen names, under the audit's twenty-name floor
