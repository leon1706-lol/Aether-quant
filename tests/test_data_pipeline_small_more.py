"""The last small branches of data_pipeline/ (V6.6.6, #359): CFTC, public candles, the data audit, the AQR workbook, bar synthesis, S&P membership,
Form 3/4/5, the Binance listing, filing text and FINRA."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import zipfile
from datetime import date
from types import ModuleType, SimpleNamespace
from xml.etree import ElementTree  # noqa: F401  (documents the listing format the Binance test feeds)

import numpy as np
import pandas as pd
import pytest

from data_pipeline import (
    bar_synthesis,
    binance_archive,
    cftc_cot,
    data_audit,
    factor_library,
    filing_text,
    finra_short_volume,
    public_candles,
    sec_form345,
    sp500_membership,
)


def _requests(monkeypatch, content=b"data", text="body"):
    module = ModuleType("requests")
    module.get = lambda url, timeout, headers=None: SimpleNamespace(raise_for_status=lambda: None, content=content, text=text)
    monkeypatch.setitem(sys.modules, "requests", module)


def test_cftc_downloads_and_the_command_plans_or_writes(tmp_path, monkeypatch, capsys):
    _requests(monkeypatch, content=b"zip bytes")
    assert cftc_cot._download("https://cftc") == b"zip bytes"
    monkeypatch.setattr(cftc_cot, "OUTPUT", tmp_path / "cot.csv")
    assert cftc_cot.main(["--start-year", "2020", "--end-year", "2021"]) == 0 and "would fetch 2 years" in capsys.readouterr().out
    rows = [{"report_date": "2020-01-07", "publication_date": "2020-01-10", "market": "EUR", "net_pct_oi": 1.5}, {"report_date": "2021-01-05", "publication_date": "2021-01-08", "market": "EUR", "net_pct_oi": 2.5}]
    monkeypatch.setattr(cftc_cot, "fetch_years", lambda years: rows)
    written = []
    monkeypatch.setattr(cftc_cot, "write_positioning", lambda rows: written.append(rows))
    assert cftc_cot.main(["--apply"]) == 0 and written and "2 rows, 2020-01-07..2021-01-05" in capsys.readouterr().out


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def test_the_json_client_retries_and_then_names_the_failure(monkeypatch):
    sleeps = []
    monkeypatch.setattr(public_candles.time, "sleep", lambda seconds: sleeps.append(seconds))
    attempts = iter([urllib.error.URLError("down"), _Response(b"[1, 2]")])

    def urlopen(request, timeout):
        outcome = next(attempts)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(public_candles.urllib.request, "urlopen", urlopen)
    assert public_candles.default_get_json("https://x", retries=3) == [1, 2] and sleeps == [1.0]
    monkeypatch.setattr(public_candles.urllib.request, "urlopen", lambda request, timeout: (_ for _ in ()).throw(TimeoutError("slow")))
    with pytest.raises(ConnectionError, match="slow"):
        public_candles.default_get_json("https://x", retries=2)


def test_the_candle_cache_ignores_damage_and_a_read_only_folder(tmp_path):
    (tmp_path / "BTC.csv").write_text("date,open\n2025-01-01,1\n", encoding="utf-8")
    (tmp_path / "BTC.json").write_text("{torn", encoding="utf-8")
    assert public_candles._read_cache(tmp_path, "BTC") is None
    (tmp_path / "BTC.json").write_text(json.dumps({"start": "2025-01-01", "end": "2025-01-02"}), encoding="utf-8")
    assert public_candles._read_cache(tmp_path, "BTC") is None
    (tmp_path / "BTC.json").write_text(json.dumps([1]), encoding="utf-8")
    assert public_candles._read_cache(tmp_path, "BTC") is None
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    public_candles._write_cache(blocker / "sub", "BTC", pd.DataFrame(columns=list(public_candles.COLUMNS)), date(2025, 1, 1), date(2025, 1, 2))
    assert public_candles.bars_to_panel({"BTC": pd.DataFrame(columns=list(public_candles.COLUMNS))}).empty


def _write_zip(path, name, text):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, text)


def test_an_empty_zip_reads_as_an_empty_frame_and_the_window_trims(tmp_path):
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w"):
        pass
    assert data_audit.read_lean_daily_zip(empty, "equity").empty
    days = pd.bdate_range("2025-01-01", periods=10)
    frame = pd.DataFrame({"date": days, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0})
    trimmed = data_audit.audit_series(frame, "equity", start="2025-01-03", end="2025-01-08")
    assert trimmed["rows"] == 4
    assert data_audit.audit_series(frame, "equity", start="2030-01-01") == {"rows": 0, "problems": ["no rows in window"]}


def test_a_non_positive_price_and_inconsistent_bars_are_named():
    days = pd.bdate_range("2025-01-01", periods=6)
    frame = pd.DataFrame({"date": days, "open": [100.0, 100.0, 0.0, 100.0, 100.0, 100.0], "high": [101.0, 99.0, 101.0, 101.0, 101.0, 101.0], "low": [99.0, 98.0, 99.0, 99.0, 99.0, 99.0], "close": 100.0, "volume": 1.0})
    problems = " ".join(data_audit.audit_series(frame, "equity")["problems"])
    assert "non-positive price" in problems and "outside open/close" in problems


def test_the_universe_audit_names_a_missing_quote_zip_and_the_non_daily_readers(tmp_path):
    root = tmp_path / "data"
    trade = root / "crypto" / "coinbase" / "daily" / "btcusd_trade.zip"
    trade.parent.mkdir(parents=True)
    _write_zip(trade, "btcusd.csv", "\n".join(f"{day:%Y%m%d} 00:00,1,2,0.5,1.5,10" for day in pd.bdate_range("2025-01-01", periods=3)))
    config = {"phase1": {"universe": {"resolution": "Hour", "assets": [{"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"}]}}}
    report = data_audit.audit_universe(config, root)
    assert "missing quote zip" in report["assets"]["BTCUSD"]["problems"] and report["flagged"] == ["BTCUSD"]
    hour = root / "equity" / "usa" / "hour"
    hour.mkdir(parents=True)
    _write_zip(hour / "aapl.zip", "aapl.csv", "20250102 09:30,1,2,3,4,5\n\n")
    _write_zip(hour / "empty.zip", "readme.txt", "x")
    (hour / "torn.zip").write_text("not a zip", encoding="utf-8")
    _write_zip(hour / "odd.zip", "odd.csv", "abc,1\n")
    _write_zip(hour / "blank.zip", "blank.csv", "\n")
    found = data_audit.audit_non_daily_files(config, root)
    reads = {entry["path"]: entry["read_by"] for entry in found["files"]}
    assert reads["equity/usa/hour/aapl.zip"] == "universe_resolution" and found["num_files"] == 5
    assert {entry["path"]: entry["last"] for entry in found["files"]}["equity/usa/hour/aapl.zip"] == "2025-01-02"
    assert [entry["last"] for entry in found["files"] if entry["path"].endswith(("empty.zip", "torn.zip", "odd.zip", "blank.zip"))] == [None, None, None, None]


def test_an_aqr_workbook_is_read_below_its_prose():
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    for row in (["Some prose", None], ["DATE", "USA"], ["01/02/2020", 0.01], ["01/03/2020", None], ["not a date", 0.5], ["01/06/2020", 0.02]):
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    series = factor_library.parse_aqr_sheet(buffer.getvalue(), sheet="Sheet1", name="mkt")
    assert list(series.index) == ["2020-01-02", "2020-01-06"] and series.name == "mkt"


def test_the_signal_records_sells_and_holds_through_the_callback():
    seen = []
    common = dict(decision_threshold=0.5, buy_threshold=0.6, effective_sell_threshold=0.4, max_position_weight=0.2, record_observation=lambda key, value: seen.append((key, value)), symbol_key="X")
    assert bar_synthesis.derive_signal(0.3, **common)[0] == "sell" and bar_synthesis.derive_signal(0.7, **common)[0] == "buy" and bar_synthesis.derive_signal(0.5, **common)[0] == "hold"
    assert len(seen) == 3 and bar_synthesis.derive_signal(0.3, decision_threshold=0.5, buy_threshold=0.6, effective_sell_threshold=0.4, max_position_weight=0.2)[2] < 0


def test_membership_is_fetched_with_requests_by_default(tmp_path, monkeypatch):
    _requests(monkeypatch, text="date,tickers\n2020-01-01,AAA\n")
    monkeypatch.setattr(sp500_membership, "parse_membership", lambda text: {"AAA": [("2020-01-01", "2020-12-31")]})
    result = sp500_membership.fetch_membership(tmp_path)
    assert result["tickers"] == 1 and (tmp_path / sp500_membership.MEMBERSHIP_FILE).read_text(encoding="utf-8").startswith("date")


def test_insider_tables_handle_an_empty_set_and_an_uncovered_ticker():
    empty = pd.DataFrame(columns=sec_form345.TRADE_COLUMNS)
    assert sec_form345.opportunistic(empty).empty
    trades = pd.DataFrame([{"ticker": "OTHER", "owner": "o", "filed": "2025-01-02", "traded": "2025-01-01", "code": "P", "value": 5.0}])
    table = sec_form345.insider_net_table(trades, ["2025-01-02", "2025-01-03"], ["AAA"])
    assert (table == 0.0).all().all()


def test_the_binance_listing_stops_when_the_page_has_no_marker():
    page = (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>true</IsTruncated></ListBucketResult>'
    )
    assert binance_archive.list_symbols(lambda url: page) == []


def test_an_8k_without_the_earnings_item_is_not_an_earnings_row():
    filings = [{"form": "10-K", "filingDate": "2025-01-01"}, {"form": "8-K", "items": "5.02", "filingDate": "2025-01-02"}, {"form": "8-K", "items": "2.02, 9.01", "filingDate": "2025-01-03", "acceptanceDateTime": "2025-01-03T16:30:00"}]
    assert filing_text.earnings_rows(filings) == [{"accepted": "2025-01-03T16:30:00", "filed": "2025-01-03"}]


def test_a_finra_file_without_the_expected_columns_has_no_ratios():
    assert finra_short_volume.parse_day("a|b\n1|2\n") == {}
    assert np is not None
