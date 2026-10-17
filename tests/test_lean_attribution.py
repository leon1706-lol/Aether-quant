"""evaluation/lean_attribution.py (V6.0.0): a Lean run's daily P&L rebuilt per ticker and per component."""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone

import pytest

from evaluation.lean_attribution import (
    Fill,
    component_daily_pnl,
    component_of,
    daily_ticker_pnl,
    fills_from_order_events,
    formed_book_by_date,
    lean_period_net,
    opener_members_by_date,
    quote_to_usd_rate,
    read_daily_closes,
    reconcile_with_equity_curve,
)


def _stamp(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def test_a_fill_belongs_to_the_bar_whose_end_stamps_it():
    events = [
        {"time": _stamp("2023-07-05T20:00:00"), "status": "filled", "symbolValue": "NVDA", "fillQuantity": 10, "fillPrice": 42.0,
         "orderFeeAmount": 1.0, "limitPrice": 42.3, "orderEventId": 2},
        {"time": _stamp("2023-07-04T00:00:00"), "status": "filled", "symbolValue": "ADAUSD", "fillQuantity": -5, "fillPrice": 0.29,
         "orderFeeAmount": 0.5, "orderEventId": 2},
        {"time": _stamp("2023-07-04T00:00:00"), "status": "submitted", "symbolValue": "ADAUSD", "fillQuantity": 0, "fillPrice": 0},
    ]
    fills = fills_from_order_events(events)
    assert [(fill.ticker, fill.date, fill.quantity, fill.is_limit) for fill in fills] == [
        ("ADAUSD", "2023-07-03", -5.0, False), ("NVDA", "2023-07-05", 10.0, True)
    ]


def test_marks_follow_the_close_and_a_round_trip_sums_to_its_realised_pnl():
    closes = {"AAA": {"2024-01-02": 10.0, "2024-01-03": 11.0, "2024-01-04": 12.0, "2024-01-05": 11.5}}
    fills = [Fill("2024-01-02", "AAA", 100, 10.2, 1.0, True), Fill("2024-01-05", "AAA", -100, 11.4, 1.0, False)]
    pnl = daily_ticker_pnl(fills, closes, sorted(closes["AAA"]))
    assert pnl["2024-01-02"]["AAA"]["pnl"] == pytest.approx(100 * (10.0 - 10.2))
    assert pnl["2024-01-03"]["AAA"]["pnl"] == pytest.approx(100 * 1.0)
    assert pnl["2024-01-05"]["AAA"]["position"] == 0.0
    total = sum(entry["pnl"] for day in pnl.values() for entry in day.values())
    assert total == pytest.approx(100 * (11.4 - 10.2))
    assert sum(entry["fee"] for day in pnl.values() for entry in day.values()) == pytest.approx(2.0)


def test_a_short_and_a_missing_close_carry_the_last_price():
    closes = {"BBB": {"2024-01-02": 50.0, "2024-01-04": 48.0}}
    fills = [Fill("2024-01-02", "BBB", -10, 50.0, 0.0, False)]
    pnl = daily_ticker_pnl(fills, closes, ["2024-01-02", "2024-01-03", "2024-01-04"])
    assert pnl["2024-01-03"]["BBB"]["pnl"] == 0.0
    assert pnl["2024-01-04"]["BBB"]["pnl"] == pytest.approx(20.0)


def test_forex_pnl_is_converted_from_the_quote_currency():
    closes = {
        "USDJPY": {"2024-01-02": 100.0, "2024-01-03": 101.0},
        "GBPUSD": {"2024-01-02": 1.25, "2024-01-03": 1.25},
        "EURGBP": {"2024-01-02": 0.86, "2024-01-03": 0.87},
    }
    dates = {ticker: sorted(series) for ticker, series in closes.items()}
    assert quote_to_usd_rate("EURUSD", "2024-01-03", closes, dates) == 1.0
    assert quote_to_usd_rate("USDJPY", "2024-01-03", closes, dates) == pytest.approx(1 / 101.0)
    assert quote_to_usd_rate("EURGBP", "2024-01-03", closes, dates) == pytest.approx(1.25)
    pnl = daily_ticker_pnl([Fill("2024-01-02", "USDJPY", 1000, 100.0, 2.0, False)], closes, sorted(closes["USDJPY"]), {"USDJPY"})
    assert pnl["2024-01-03"]["USDJPY"]["pnl"] == pytest.approx(1000 * 1.0 / 101.0)


def test_book_membership_survives_a_veto_and_components_follow_it():
    history = [
        {"date": "2024-01-02", "allocations": {"AAA": {}, "BTCUSD": {}, "ADAUSD": {}}},
        {"date": "2024-01-16", "allocations": {}},
        {"date": "2024-01-30", "allocations": {"CCC": {}}},
    ]
    members = formed_book_by_date(history, ["2024-01-01", "2024-01-20", "2024-02-01"])
    assert members["2024-01-01"] == frozenset()
    assert members["2024-01-20"] == {"AAA", "BTCUSD", "ADAUSD"}
    assert members["2024-02-01"] == {"CCC"}
    core = {"BTCUSD"}
    assert component_of("AAA", "equity", members["2024-01-20"], core) == "main_book"
    assert component_of("AAA", "equity", members["2024-02-01"], core) == "legacy"
    assert component_of("BTCUSD", "crypto", members["2024-01-20"], core) == "crypto_core"
    assert component_of("ADAUSD", "crypto", members["2024-01-20"], core) == "crypto_graduate"
    assert component_of("ADAUSD", "crypto", members["2024-02-01"], core) == "legacy_crypto"
    assert component_of("TLT", "bond", frozenset({"TLT"}), core) == "bond_sleeve"
    assert component_of("EURUSD", "forex", frozenset(), core) == "forex_sleeve"
    daily = component_daily_pnl(
        {"2024-01-20": {"AAA": {"pnl": 5.0, "fee": 1.0, "position": 1, "fills": 1, "limit_fills": 0, "notional": 10.0}}},
        {"AAA": "equity"}, members, core,
    )
    assert daily["2024-01-20"]["main_book"]["pnl"] == 5.0


def test_reconciliation_and_period_bracketing():
    components = {"2024-01-02": {"main_book": {"pnl": 10.0, "fee": 1.0}}, "2024-01-03": {"legacy": {"pnl": -4.0, "fee": 0.0}}}
    report = reconcile_with_equity_curve(components, [("2024-01-01", 100.0), ("2024-01-02", 109.0), ("2024-01-03", 105.0)])
    assert report["difference_usd"] == pytest.approx(0.0)
    result = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": [
        [_stamp("2024-01-01T20:00:00"), 100.0], [_stamp("2024-01-02T00:00:00"), 101.0],
        [_stamp("2024-01-02T20:00:00"), 103.0], [_stamp("2024-01-03T00:00:00"), 104.0],
    ]}}}}}
    assert lean_period_net(result, "2024-01-02", "2024-01-02") == pytest.approx(3.0)


def test_read_daily_closes_scales_equity_prices(tmp_path):
    path = tmp_path / "x.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("x.csv", "20240102 00:00,1000000,1010000,990000,1005000,5\n")
    assert read_daily_closes(path, 1 / 10_000) == {"2024-01-02": pytest.approx(100.5)}
    assert read_daily_closes(tmp_path / "missing.zip") == {}


def _entry(position, pnl=1.0):
    return {"pnl": pnl, "fee": 0.0, "position": position, "fills": 0, "limit_fills": 0, "notional": 0.0}


def test_a_position_belongs_to_the_component_that_opened_it():
    members = {"d1": frozenset({"AAA"}), "d2": frozenset(), "d3": frozenset(), "d4": frozenset({"BBB"})}
    ticker_pnl = {
        "d1": {"AAA": _entry(10)},                      # opened as a member
        "d2": {"AAA": _entry(10), "BBB": _entry(5)},    # AAA left the book but is still held; BBB opened outside it
        "d3": {"AAA": _entry(0), "BBB": _entry(5)},     # AAA closed
        "d4": {"BBB": _entry(5), "AAA": _entry(-3)},    # BBB adopted by the book; AAA re-opened short outside it
    }
    owned = opener_members_by_date(ticker_pnl, members)
    assert owned["d2"] == {"AAA"}
    assert owned["d3"] == frozenset()
    assert owned["d4"] == {"BBB"}
    opener = component_daily_pnl(ticker_pnl, {}, members, set())
    membership = component_daily_pnl(ticker_pnl, {}, members, set(), by_opener=False)
    assert opener["d2"]["main_book"]["pnl"] == 1.0 and opener["d2"]["legacy"]["pnl"] == 1.0
    assert membership["d2"]["legacy"]["pnl"] == 2.0 and "main_book" not in membership["d2"]
    assert opener["d4"]["legacy"]["pnl"] == 1.0 and opener["d4"]["main_book"]["pnl"] == 1.0


def test_a_runs_config_is_its_code_snapshot_or_the_frozen_copy(tmp_path):
    from evaluation.lean_attribution import run_config_path

    run = tmp_path / "backtests" / "2026-10-15_17-29-50"
    run.mkdir(parents=True)
    assert run_config_path(run, tmp_path) is None
    frozen = tmp_path / "ml" / "evaluation" / "run_configs" / "2026-10-15_17-29-50.json"
    frozen.parent.mkdir(parents=True)
    frozen.write_text("{}", encoding="utf-8")
    assert run_config_path(run, tmp_path) == frozen
    (run / "code").mkdir()
    (run / "code" / "config.json").write_text("{}", encoding="utf-8")
    assert run_config_path(run, tmp_path) == run / "code" / "config.json"
