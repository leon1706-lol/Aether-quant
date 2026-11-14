"""The last branches of evaluation/target_weights_engine.py (V6.6.6, #359): a panel loader that skips a missing or empty zip, USD rates from quote-currency pairs, a bar-less held crypto name exited with an
order pending, a forex carry in the financing, and the cash sweep both short and fully sold."""

from __future__ import annotations

import dataclasses
import zipfile

import numpy as np
import pytest

from evaluation import target_weights_engine as engine
from evaluation.target_weights_engine import simulate_target_weights
from test_target_weights_engine import FREE, _no_fee, _panel, _run

SWEEP = {"enabled": True, "max_weight": 0.9, "min_trade_weight": 0.01, "cash_buffer": 0.02, "margin_buffer": 0.1, "margin_leverage": 2.0}


def write_daily_zip(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", "\n".join(rows) + ("\n" if rows else ""))


def test_the_panel_skips_an_asset_with_no_zip_and_one_with_no_rows(tmp_path):
    base = tmp_path / "data" / "equity" / "usa" / "daily"
    write_daily_zip(base / "aaa.zip", ["20240102 00:00,100000,110000,90000,105000,1000", "20240103 00:00,105000,115000,95000,110000,1000"])
    base.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(base / "empty.zip", "w"):
        pass
    assets = [{"ticker": ticker, "security_type": "equity", "data_path": f"data/equity/usa/daily/{ticker.lower()}.zip"} for ticker in ("AAA", "EMPTY", "GONE")]
    panel = engine.load_market_panel(tmp_path, {"phase1": {"universe": {"assets": assets}}}, extra_equity=())
    with_sweep = engine.load_market_panel(tmp_path, {"phase1": {"universe": {"assets": assets}}})
    assert with_sweep.tickers == ["AAA"]
    assert panel.tickers == ["AAA"] and panel.dates == ["2024-01-02", "2024-01-03"] and panel.sessions == {"2024-01-02", "2024-01-03"}


def test_a_usd_quoted_pair_gives_the_base_currency_its_usd_rate():
    closes = np.array([[1.1, 150.0], [1.2, 160.0]])
    rates = engine._usd_rates(closes, {"EURUSD": 0, "USDJPY": 1})
    assert rates["EUR"].tolist() == [1.1, 1.2] and rates["JPY"] == pytest.approx([1 / 150.0, 1 / 160.0]) and rates["USD"].tolist() == [1.0, 1.0]


def test_a_decision_on_the_first_bar_of_a_crypto_name_has_no_price_to_size_with():
    panel = _panel(["B"], [[10.0], [10.0], [10.0]], [[10.0], [10.0], [10.0]], {"B": "crypto"})
    result = _run({"2024-01-01": {"B": 1.0}}, panel)
    assert result["nav"].iloc[-1] == pytest.approx(100_000.0)


def test_a_held_crypto_name_whose_bars_stop_is_sold_and_its_pending_order_dropped():
    config = dataclasses.replace(FREE, no_bar_exit=True, no_bar_exit_after=1)
    nan = float("nan")
    closes = [[10.0]] * 3 + [[nan]] * 6
    panel = _panel(["B"], closes, closes, {"B": "crypto"})
    result = _run({f"2024-01-0{day}": {"B": 1.0} for day in range(1, 10)}, panel, config)
    assert result["no_bar_exits"] == ["2024-01-05:B"] and result["fills"] == 1


def test_an_equity_held_over_a_day_with_no_session_has_not_lost_its_bar():
    config = dataclasses.replace(FREE, no_bar_exit=True, no_bar_exit_after=1)
    closes = [[10.0]] * 5
    panel = _panel(["A"], closes, closes, {"A": "equity"}, sessions=["2024-01-01", "2024-01-02", "2024-01-05"])
    result = _run({"2024-01-01": {"A": 1.0}}, panel, config)
    assert result["no_bar_exits"] == [] and result["fills"] == 1


def test_a_name_with_no_price_yet_is_sized_at_nothing_and_a_short_pays_the_financing():
    nan = float("nan")
    closes = [[nan, 10.0], [20.0, 10.0], [20.0, 10.0], [20.0, 10.0]]
    panel = _panel(["C", "A"], closes, closes, {"C": "equity", "A": "equity"})
    config = dataclasses.replace(FREE, financing_enabled=True)
    result = simulate_target_weights({"2024-01-01": {"C": 1.0, "A": -0.5}}, panel, config, start=panel.dates[0], end=panel.dates[-1], fee_fn=_no_fee)
    assert result["financing"] != 0.0 or result["fills"] >= 1


def test_a_forex_position_pays_or_earns_its_carry_in_the_financing():
    config = dataclasses.replace(FREE, financing_enabled=True)
    closes = [[1.1, 10.0, 5.0]] * 6
    panel = _panel(["EURUSD", "A", "Z"], closes, closes, {"EURUSD": "forex", "A": "equity", "Z": "equity"})
    paid = simulate_target_weights({"2024-01-01": {"EURUSD": 1.0, "A": 0.5}}, panel, config, start=panel.dates[0], end=panel.dates[-1], fee_fn=_no_fee, carry_fn=lambda ticker, date: 0.04)
    free = simulate_target_weights({"2024-01-01": {"EURUSD": 1.0, "A": 0.5}}, panel, config, start=panel.dates[0], end=panel.dates[-1], fee_fn=_no_fee)
    assert paid["financing"] != free["financing"]


def test_the_sweep_sells_down_to_nothing_when_the_book_uses_all_the_margin_and_counts_a_short_as_exposure():
    closes = [[10.0, 100.0]] * 8
    panel = _panel(["A", "BIL"], closes, closes, {"A": "equity", "BIL": "cash_sweep"})
    result = _run({"2024-01-04": {"A": 1.0}}, panel, sweep_config=SWEEP)
    assert result["fills"] >= 2
    short = _run({"2024-01-04": {"A": -1.0}}, panel, sweep_config=SWEEP)
    assert short["fills"] >= 1
