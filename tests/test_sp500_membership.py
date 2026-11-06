"""data_pipeline/sp500_membership.py and scripts/build_wide_root.py, on fixtures: no network."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

from data_pipeline.sp500_membership import (
    canonical_issuer,
    coverage_by_year,
    fetch_membership,
    is_member,
    parse_membership,
    suspect_interval,
    tickers_touching,
    yahoo_symbol_for_member,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

TEXT = """ticker,start_date,end_date
AAL,1996-01-02,1997-01-15
AAL,2015-03-23,2024-09-23
FB,2013-12-23,2022-06-09
META,2022-06-09,
BRK.B,2010-02-16,
GONE,2005-01-03,2009-06-01
"""


def test_a_rename_merges_into_one_interval():
    table = parse_membership(TEXT)
    assert "FB" not in table
    assert table["META"] == [("2013-12-23", "9999-12-31")]


def test_a_reused_ticker_keeps_two_intervals_and_membership_excludes_its_end_date():
    table = parse_membership(TEXT)
    assert len(table["AAL"]) == 2
    assert is_member(table, "AAL", "2015-03-23") and is_member(table, "AAL", "1996-06-01")
    assert not is_member(table, "AAL", "2024-09-23") and not is_member(table, "AAL", "2000-01-03")
    assert not is_member(table, "NOPE", "2020-01-02")


def test_tickers_touching_a_window():
    table = parse_membership(TEXT)
    assert "GONE" in tickers_touching(table, "2008-01-01", "2008-12-31")
    assert "GONE" not in tickers_touching(table, "2009-06-01", "2009-12-31")


def test_yahoo_symbol_and_issuer():
    assert yahoo_symbol_for_member("BRK.B") == "BRK-B"
    assert canonical_issuer("GOOG") == canonical_issuer("GOOGL") == "GOOGL"
    assert canonical_issuer("FB") == "META"
    assert canonical_issuer("AAPL") == "AAPL"


def test_a_ticker_whose_bars_begin_after_its_membership_is_suspect():
    intervals = [("2010-01-04", "9999-12-31")]
    assert suspect_interval(intervals, "2015-06-01", window_start="2003-06-01")
    assert not suspect_interval(intervals, "2010-01-04", window_start="2003-06-01")
    assert not suspect_interval(intervals, "2003-06-01", window_start="2003-06-01")
    # a member before the window only needs bars from the window's start
    assert not suspect_interval([("1999-01-04", "9999-12-31")], "2003-06-02", window_start="2003-06-01")
    assert suspect_interval([("1999-01-04", "9999-12-31")], "2009-01-02", window_start="2003-06-01")
    # an interval that ended before the window is no evidence about today's holder of the ticker
    assert not suspect_interval([("1996-01-02", "1997-01-15")], "2005-09-27", window_start="2003-06-01")


def test_coverage_counts_everything_not_available():
    table = {"A": [("2010-01-01", "2011-01-01")], "B": [("2010-01-01", "2011-01-01")], "C": [("2011-01-01", "2012-01-01")]}
    coverage = coverage_by_year(table, {"A", "C"}, first_year=2010, last_year=2011)
    assert coverage["2010"] == pytest.approx(0.5)
    assert coverage["2011"] == pytest.approx(0.0)


def test_fetch_membership_saves_the_source_and_its_hash(tmp_path):
    report = fetch_membership(tmp_path, get=lambda url: TEXT)
    assert (tmp_path / "sp500_ticker_start_end.csv").read_text(encoding="utf-8") == TEXT
    assert len(report["sha256"]) == 64 and report["tickers"] == 4


def _rows(start: datetime.date, count: int) -> tuple[list[dict], dict]:
    rows, raw = [], {}
    for i in range(count):
        day = start + datetime.timedelta(days=i)
        rows.append({"date": day, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 100.0})
        raw[day.isoformat()] = 12.0
    return rows, raw


def test_build_root_skips_bad_names_and_resumes(tmp_path):
    import build_wide_root

    calls = []

    def fetch(symbol, start, end):
        calls.append(symbol)
        if symbol == "NEVER":
            return [], {}
        if symbol == "LATE":
            return _rows(datetime.date(2015, 1, 5), 5)
        return _rows(datetime.date(2005, 1, 3), 5)

    text = "ticker,start_date,end_date\nAAA,2005-01-03,\nBRK.B,2005-01-03,\nNEVER,2005-01-03,\nLATE,2005-01-03,\n"
    source = tmp_path / "source"
    (source / "reference").mkdir(parents=True)
    (source / "reference" / "keep.txt").write_text("x")
    config = {"phase1": {"universe": {"assets": [{"ticker": "PROJ", "security_type": "equity"}, {"ticker": "BTCUSD", "security_type": "crypto"}]}}}
    out = tmp_path / "wide"
    coverage = tmp_path / "coverage.json"
    manifest = build_wide_root.build_root(
        out, start="2003-06-01", end="2026-11-03", config=config, source=source, fetch_fn=fetch, pause_seconds=0.0,
        get_membership=lambda url: text, coverage_path=coverage,
    )
    assert {"AAA", "BRK.B", "PROJ", "SPY", "AGG", "BIL", "XLK"} <= set(manifest["tickers"])
    assert manifest["left_out"]["NEVER"] == "no bars"
    assert manifest["left_out"]["LATE"].startswith("suspect")
    assert "BRK-B" in calls and "BRK.B" not in calls
    assert (out / "equity" / "usa" / "daily" / "brk.b.zip").exists()
    assert json.loads((out / "reference" / "raw_closes" / "aaa.json").read_text())["2005-01-03"] == 12.0
    assert (out / "reference" / "keep.txt").exists()
    report = json.loads(coverage.read_text())
    assert report["excluded"]["NEVER"] == "no bars" and report["missing_share_by_year"]["2010"] == pytest.approx(0.5)
    assert "price" not in json.dumps(report)

    calls.clear()
    build_wide_root.build_root(
        out, start="2003-06-01", end="2026-11-03", config=config, source=source, fetch_fn=fetch, pause_seconds=0.0,
        get_membership=lambda url: text,
    )
    assert "AAA" not in calls and "LATE" not in calls, "a rerun resumes"


def test_wide_config_lists_names_and_keeps_project_crypto():
    import build_wide_root

    manifest = {"tickers": {"AAA": {"first": "2005-01-03", "last": "2026-11-02"}, "BIL": {"first": "2007-05-30", "last": "2026-11-02"}, "SPY": {"first": "2003-06-02", "last": "2026-11-02"}}}
    base = {"phase1": {"universe": {"assets": [{"ticker": "AAPL", "security_type": "equity"}, {"ticker": "BTCUSD", "security_type": "crypto"}]}}, "other": 1}
    config = build_wide_root.wide_config(base, manifest)
    names = [asset["ticker"] for asset in config["phase1"]["universe"]["assets"]]
    assert names == ["AAA", "SPY", "BTCUSD"], "BIL is the sweep, never a universe asset"
    assert config["phase1"]["universe"]["assets"][0]["data_path"] == "data/equity/usa/daily/aaa.zip"
    assert base["phase1"]["universe"]["assets"][0]["ticker"] == "AAPL", "the base is untouched"
    restricted = build_wide_root.wide_config(base, manifest, tickers={"SPY"}, keep_project_crypto=False)
    assert [asset["ticker"] for asset in restricted["phase1"]["universe"]["assets"]] == ["SPY"]


def test_fetch_adjusted_and_raw_applies_the_adjustment_ratio(monkeypatch):
    import pandas as pd

    import build_wide_root

    frame = pd.DataFrame(
        {"Open": [100.0], "High": [110.0], "Low": [90.0], "Close": [100.0], "Adj Close": [50.0], "Volume": [1000.0]},
        index=pd.to_datetime(["2010-01-04"]),
    )
    fake = type("YF", (), {"download": staticmethod(lambda *a, **k: frame)})
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    rows, raw = build_wide_root.fetch_adjusted_and_raw("X", "2010-01-01", "2010-02-01")
    assert rows[0]["close"] == 50.0 and rows[0]["open"] == 50.0 and rows[0]["high"] == 55.0
    assert raw == {"2010-01-04": 100.0}
