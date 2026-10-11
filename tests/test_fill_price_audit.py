"""Tests for evaluation/fill_price_audit.py (V5.7.0): fills vs the dataset open and the Lean zip open."""

import zipfile
from datetime import datetime, timezone

import pytest

from evaluation.fill_price_audit import (
    audit_fills,
    fill_vs_reference,
    fills_from_run,
    lean_daily_zip_path,
    read_zip_daily_opens,
    reference_gap,
)


def _epoch(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


def _event(order_id, symbol, when, price, direction, status="filled", quantity=10.0):
    return {
        "orderId": order_id, "symbolValue": symbol, "time": when, "status": status, "fillPrice": price,
        "fillQuantity": quantity if direction == "buy" else -quantity, "direction": direction,
    }


def _run():
    return {
        "result": {"orders": {"1": {"securityType": 1, "type": 0}, "2": {"securityType": 1, "type": 1}, "3": {"securityType": 7, "type": 0}}},
        "order_events": [
            _event(1, "AAPL", _epoch(2019, 3, 5, 14, 30), 100.10, "buy"),       # market buy, 10 bps above a 100 open
            _event(2, "AAPL", _epoch(2019, 3, 6, 14, 30), 99.90, "sell"),       # limit sell, 10 bps below a 100 open
            _event(3, "BTCUSD", _epoch(2019, 3, 7, 0, 0), 4000.0, "buy"),
            _event(1, "AAPL", _epoch(2019, 3, 5, 14, 29), 0.0, "buy", status="submitted"),
            _event(1, "AAPL", _epoch(2019, 3, 5, 14, 30), 100.0, "buy", status="canceled"),
        ],
    }


def test_fills_keep_only_real_fills_and_date_equities_by_the_new_york_session():
    fills = fills_from_run(_run())
    assert [(f["symbol"], f["date"], f["order_type"], f["direction"], f["asset_class"]) for f in fills] == [
        ("AAPL", "2019-03-05", "market", 1, "equity"),
        ("AAPL", "2019-03-06", "limit", -1, "equity"),
        ("BTCUSD", "2019-03-07", "market", 1, "crypto"),
    ]


def test_signed_cost_is_positive_when_the_fill_is_worse_than_the_reference():
    references = {("AAPL", "2019-03-05"): 100.0, ("AAPL", "2019-03-06"): 100.0}
    report = fill_vs_reference(fills_from_run(_run()), references)
    assert report["groups"]["equity/market"]["median_signed_bps"] == pytest.approx(10.0)
    assert report["groups"]["equity/limit"]["median_signed_bps"] == pytest.approx(10.0)  # sold 10 bps below the open
    assert report["groups"]["equity/all"]["n"] == 2
    assert report["fills_without_reference"] == 1  # the BTCUSD fill has no reference


def test_a_better_than_open_fill_is_negative_and_non_positive_references_are_ignored():
    fills = [{"symbol": "X", "date": "2020-01-02", "price": 99.0, "direction": 1, "asset_class": "equity", "order_type": "market"}]
    assert fill_vs_reference(fills, {("X", "2020-01-02"): 100.0})["groups"]["equity/all"]["median_signed_bps"] == pytest.approx(-100.0)
    assert fill_vs_reference(fills, {("X", "2020-01-02"): 0.0})["fills_without_reference"] == 1


def _write_zip(path, name, rows):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "\n".join(rows))


def test_zip_reader_scales_deci_cent_equity_prices_and_skips_bad_rows(tmp_path):
    zip_path = tmp_path / "aapl.zip"
    _write_zip(zip_path, "aapl.csv", ["20190305 00:00,1000000,1010000,990000,1005000,100", "garbage", "20190306 00:00,abc,1,1,1,1"])
    assert read_zip_daily_opens(zip_path, 1e-4) == {"2019-03-05": pytest.approx(100.0)}
    assert read_zip_daily_opens(tmp_path / "missing.zip") == {}


def test_factor_rows_adjust_opens_like_lean_and_the_dataset_builder(tmp_path):
    from evaluation.fill_price_audit import apply_factor_rows, read_factor_file

    path = tmp_path / "aapl.csv"
    path.write_text("20200101,0.5,1,100\n20200201,0.5,2,200\n20500101,1,1,300\n", encoding="utf-8")
    factors = read_factor_file(path)
    assert factors[0] == ("2020-01-01", 0.5, 1.0)
    adjusted = apply_factor_rows({"2019-12-31": 100.0, "2020-01-01": 100.0, "2020-01-15": 100.0, "2020-02-02": 100.0}, factors)
    # a row takes the factor of the first entry dated on/after it
    assert adjusted == {"2019-12-31": 50.0, "2020-01-01": 50.0, "2020-01-15": 100.0 * 0.5 * 2.0, "2020-02-02": 100.0}
    assert apply_factor_rows({"2020-01-01": 7.0}, []) == {"2020-01-01": 7.0}
    assert read_factor_file(tmp_path / "missing.csv") == []


def test_zip_paths_follow_the_lean_layout():
    root = "data"
    assert lean_daily_zip_path(root, "AAPL", "equity").as_posix() == "data/equity/usa/daily/aapl.zip"
    assert lean_daily_zip_path(root, "BTCUSD", "crypto").as_posix() == "data/crypto/coinbase/daily/btcusd_trade.zip"
    assert lean_daily_zip_path(root, "EURUSD", "forex").as_posix() == "data/forex/oanda/daily/eurusd.zip"
    assert lean_daily_zip_path(root, "ES", "future") is None


def test_reference_gap_detects_a_dataset_that_reads_different_prices_than_lean():
    zip_opens = {("A", "2020-01-02"): 100.0, ("A", "2020-01-03"): 100.0}
    assert reference_gap({("A", "2020-01-02"): 100.0, ("A", "2020-01-03"): 100.0}, zip_opens)["max_abs_bps"] == 0.0
    gap = reference_gap({("A", "2020-01-02"): 101.0, ("B", "2020-01-02"): 5.0}, zip_opens)
    assert gap["n"] == 1 and gap["max_abs_bps"] == pytest.approx(100.0)


def test_audit_fills_end_to_end(tmp_path):
    equity_dir = tmp_path / "equity" / "usa" / "daily"
    equity_dir.mkdir(parents=True)
    _write_zip(equity_dir / "aapl.zip", "aapl.csv", ["20190305 00:00,1000000,1,1,1,1", "20190306 00:00,1000000,1,1,1,1"])
    dataset_opens = {("AAPL", "2019-03-05"): 100.0, ("AAPL", "2019-03-06"): 100.5}
    report = audit_fills(_run(), dataset_opens, tmp_path)
    assert report["num_fills"] == 3
    assert report["fill_vs_zip_open"]["groups"]["equity/market"]["median_signed_bps"] == pytest.approx(10.0)
    assert report["dataset_open_vs_zip_open_on_traded_dates"]["n"] == 2
    assert report["dataset_open_vs_zip_open_on_traded_dates"]["max_abs_bps"] == pytest.approx(50.0)
