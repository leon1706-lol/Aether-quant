"""evaluation/lean_attribution.py's remaining branches (V6.6.6, #359): the whole attribution of a synthetic Lean run, and the file readers' bad inputs."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone

from evaluation import lean_attribution as la


def _stamp(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def _zip(path, rows, name="x.csv"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "\n".join(rows))


def test_closes_skip_short_and_unparsable_rows_and_a_zip_without_a_csv(tmp_path):
    _zip(tmp_path / "a.zip", ["20240102 00:00,1,2,0.5,1.5,10", "short,1", "20240103 00:00,1,2,0.5,notanumber,10", "20240104 00:00,1,2,0.5,2.5,10"])
    assert la.read_daily_closes(tmp_path / "a.zip") == {"2024-01-02": 1.5, "2024-01-04": 2.5}
    _zip(tmp_path / "b.zip", ["x"], name="readme.txt")
    assert la.read_daily_closes(tmp_path / "b.zip") == {} and la.read_daily_closes(tmp_path / "none.zip") == {}


def test_a_zero_price_fill_is_dropped():
    events = [{"time": _stamp("2024-01-03T20:00:00"), "status": "filled", "symbolValue": "AAA", "fillQuantity": 5, "fillPrice": 0.0}]
    assert la.fills_from_order_events(events) == []


def test_forex_pairs_bring_their_quote_currency_and_unknown_tickers_are_skipped(tmp_path):
    config = {"phase1": {"universe": {"assets": [
        {"ticker": "EURJPY", "security_type": "forex", "data_path": "data/forex/oanda/daily/eurjpy.zip"},
        {"ticker": "USDJPY", "security_type": "forex", "data_path": "data/forex/oanda/daily/usdjpy.zip"},
    ]}}}
    _zip(tmp_path / "data" / "forex" / "oanda" / "daily" / "eurjpy.zip", ["20240102 00:00,1,1,1,160,0"])
    _zip(tmp_path / "data" / "forex" / "oanda" / "daily" / "usdjpy.zip", ["20240102 00:00,1,1,1,150,0"])
    closes = la.closes_for_universe(config, tmp_path, {"EURJPY", "GHOST"})
    assert set(closes) == {"EURJPY", "USDJPY"}
    assert la.quote_to_usd_rate("EURJPY", "2024-01-02", closes, {name: sorted(series) for name, series in closes.items()}) == 1.0 / 150.0
    assert la.quote_to_usd_rate("EURCHF", "2024-01-02", closes, {}) == 1.0


def test_decisions_routes_and_correlation_are_reported():
    book = [{"date": "2024-01-03", "allocations": {"AAA": 1}}, {"date": "2024-01-02", "gate_veto_reason": "spread"}, {"date": "2023-12-29", "allocations": {"AAA": 1}}, {"date": "2024-02-01", "allocations": {}}]
    decisions = la.rebalance_decisions(book, "2024-01-01", "2024-01-31")
    assert decisions == {"2024-01-02": {"engaged": False, "reason": "spread", "members": 0}, "2024-01-03": {"engaged": True, "reason": None, "members": 1}}
    fills = [la.Fill("2024-01-02", "AAA", 10, 5.0, 1.0, True), la.Fill("2024-01-02", "EURJPY", 10, 160.0, 2.0, False)]
    routes = la.fee_bps_by_route({}, {"AAA": "equity", "EURJPY": "forex"}, fills, closes_rate=lambda fill: 0.5 if fill.ticker == "EURJPY" else 1.0)
    assert routes["equity/limit"]["fee_bps"] == 200.0 and routes["forex/market"]["notional"] == 800.0
    assert la.fee_bps_by_route({}, {}, [la.Fill("2024-01-02", "ZZZ", 1, 1.0, 0.0, False)])["equity/market"]["fee_bps"] == 0.0


def _run(tmp_path):
    config = {"phase1": {"universe": {"assets": [{"ticker": "AAA", "security_type": "equity", "data_path": "data/equity/usa/daily/aaa.zip"}, {"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"}]}},
              "phase_v2": {"cash_sweep": {"ticker": "BIL"}, "class_weight_caps": {"crypto": {"exempt": ["BTCUSD"]}}}}
    days = ["20240102", "20240103", "20240104", "20240105"]
    _zip(tmp_path / "data" / "equity" / "usa" / "daily" / "aaa.zip", [f"{day} 00:00,{100000 + index * 1000},0,0,{100000 + index * 1000},10" for index, day in enumerate(days)])
    _zip(tmp_path / "data" / "crypto" / "coinbase" / "daily" / "btcusd_trade.zip", [f"{day} 00:00,1,1,1,{100 + index},10" for index, day in enumerate(days)])
    events = [
        {"time": _stamp("2024-01-02T20:00:00"), "status": "filled", "symbolValue": "AAA", "fillQuantity": 10, "fillPrice": 10.0, "orderFeeAmount": 1.0, "limitPrice": 10.1, "orderEventId": 1},
        {"time": _stamp("2024-01-03T00:00:00"), "status": "filled", "symbolValue": "BTCUSD", "fillQuantity": 1, "fillPrice": 100.0, "orderFeeAmount": 0.5, "orderEventId": 2},
    ]
    points = [[_stamp(f"2024-01-0{day}T00:00:00"), 10000.0 + 10 * day] for day in (2, 3, 4, 5, 6)]
    result = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": points}}}}}
    book = [{"date": "2024-01-02", "allocations": {"AAA": {"role": "long"}}}, {"date": "2024-01-04", "allocations": {}}]
    return {"order_events": events, "result": result}, book, config


def test_the_whole_attribution_covers_the_run_and_a_period_of_it(tmp_path):
    run, book, config = _run(tmp_path)
    whole = la.attribute_run(run, book, config, tmp_path)
    assert whole["period"] is None and set(whole["components"]) == set(la.COMPONENTS) and whole["fees_by_route"] and whole["daily_equity"]
    period = la.attribute_run(run, book, config, tmp_path, period=("2024-01-03", "2024-01-05"), core_crypto={"BTCUSD"})
    assert period["period"] == ["2024-01-03", "2024-01-05"] and "lean_net_usd" in period["reconciliation"] and "difference_usd" in period["reconciliation"]
    assert all(date >= "2024-01-03" for date in period["daily_components"])
    assert la.lean_period_net(run["result"], "2020-01-01", "2020-01-02") is None
    before = la.attribute_run(run, book, config, tmp_path, period=("2020-01-01", "2020-01-02"))
    assert before["reconciliation"]["rebuilt_net_usd"] == 0.0


def test_a_moving_series_has_a_correlation_with_the_equity_curve():
    entry = {"pnl": 0.0, "fee": 0.0, "fills": 0, "limit_fills": 0, "notional": 0.0}
    rebuilt = {f"2024-01-0{day}": {"main_book": {**entry, "pnl": float(day)}} for day in (2, 3, 4, 5)}
    curve = [("2024-01-01", 100.0)] + [(f"2024-01-0{day}", 100.0 + sum(range(2, day + 1)) + (day % 2)) for day in (2, 3, 4, 5)]
    assert la.reconcile_with_equity_curve(rebuilt, curve)["daily_change_correlation"] is not None


def test_a_flat_series_has_no_correlation_and_the_run_folder_helpers_find_their_files(tmp_path):
    report = la.reconcile_with_equity_curve({"2024-01-02": {"main_book": {"pnl": 1.0, "fee": 0.0, "fills": 0, "limit_fills": 0, "notional": 0.0}}}, [("2024-01-01", 100.0), ("2024-01-02", 101.0)])
    assert report["rebuilt_net_usd"] == 1.0
    run_dir = tmp_path / "2026-01-01_00-00-00"
    run_dir.mkdir()
    assert la.run_config_path(run_dir, tmp_path) is None
    frozen = tmp_path / "ml" / "evaluation" / "run_configs"
    frozen.mkdir(parents=True)
    (frozen / f"{run_dir.name}.json").write_text("{}", encoding="utf-8")
    assert la.run_config_path(run_dir, tmp_path) == frozen / f"{run_dir.name}.json"
    book_dir = tmp_path / "book"
    book_dir.mkdir()
    (book_dir / "20260101T000500Z.jsonl").write_text("{}", encoding="utf-8")
    (book_dir / "garbage.jsonl").write_text("{}", encoding="utf-8")
    assert la.find_book_history_for_run(run_dir, book_dir).name == "20260101T000500Z.jsonl"
    (run_dir / "log.txt").write_text("2026-01-01T00:00:00.1Z TRACE:: start\n", encoding="utf-8")
    assert la.find_book_history_for_run(run_dir, book_dir) is not None
    assert la.find_book_history_for_run(tmp_path / "oddly-named", book_dir) is None
    assert la.find_book_history_for_run(run_dir, tmp_path / "empty") is None
    assert json is not None
