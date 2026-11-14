"""data_pipeline/edgar_facts.py's remaining branches (V6.6.6, #359): incomplete facts, trailing twelve months without a comparative,
resumable fetches that lose a company, the SEC and Yahoo calls, and the command line."""

from __future__ import annotations

import json
import sys
from datetime import date
from types import ModuleType, SimpleNamespace

import pandas as pd

from data_pipeline import edgar_facts as ef


def _facts(tag, entries, taxonomy="us-gaap", unit="USD/shares"):
    return {"facts": {taxonomy: {tag: {"units": {unit: entries}}}}}


def test_incomplete_entries_are_skipped_in_every_reader():
    quarter = {"start": "2024-01-01", "end": "2024-03-31", "filed": "2024-05-01", "val": 1.0, "form": "10-Q"}
    broken = [{"start": "2024-01-01"}, {**quarter, "val": None}, quarter]
    assert len(ef.quarterly_first_filings(_facts("EarningsPerShareDiluted", broken))) == 1
    assert list(ef._first_filed_durations(_facts("NetIncomeLoss", [{**quarter, "form": "8-K"}, quarter]), "NetIncomeLoss")) == [("2024-01-01", "2024-03-31")]
    instants = [{"end": "2024-03-31", "filed": "2024-05-01", "val": 5, "form": "10-Q"}, {"end": None, "filed": "x", "val": 1, "form": "10-Q"}, {"end": "2024-06-30", "filed": "2024-08-01", "val": None, "form": "10-Q"}]
    assert [row["value"] for row in ef._first_filed_instants(_facts("Assets", instants), "Assets")] == [5.0]


def test_a_year_to_date_figure_without_a_comparative_year_offers_nothing():
    durations = {
        ("2023-01-01", "2023-12-31"): {"filed": "2024-02-01", "form": "10-K", "value": 100.0},
        ("2024-01-01", "2024-06-30"): {"filed": "2024-08-01", "form": "10-Q", "value": 60.0},
    }
    rows = ef._ttm_rows(durations)
    assert [row["period_end"] for row in rows] == ["2023-12-31"]


class _Directory:
    def __init__(self, failing=(), empty=()):
        self.failing, self.empty = set(failing), set(empty)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if url == ef.TICKERS_URL:
            return {str(index): {"ticker": name, "cik_str": 100 + index} for index, name in enumerate(["AAA", "BBB", "CCC"])}
        if "submissions" in url:
            return {"sic": 3571}
        cik = int(url.rsplit("CIK", 1)[1][:10])
        if cik in {100 + i for i, name in enumerate(["AAA", "BBB", "CCC"]) if name in self.failing}:
            raise RuntimeError("down")
        if cik in {100 + i for i, name in enumerate(["AAA", "BBB", "CCC"]) if name in self.empty}:
            return {}
        return _facts("EarningsPerShareDiluted", [{"start": "2024-01-01", "end": "2024-03-31", "filed": "2024-05-01", "val": 1.0}])


def test_fetch_extended_and_fundamentals_lose_only_the_company_that_failed(tmp_path, monkeypatch, capsys):
    slept = []
    monkeypatch.setattr(ef._time, "sleep", lambda seconds: slept.append(seconds))
    rows, missing = ef.fetch_extended(["AAA", "BBB", "ZZZ"], get_json=_Directory(failing=["AAA"], empty=["BBB"]), pause_seconds=0.1, cache_dir=tmp_path / "x")
    assert missing == ["AAA", "BBB", "ZZZ"] and rows == [] and "AAA: RuntimeError" in capsys.readouterr().out and slept == [0.1]
    rows, sectors, missing = ef.fetch_fundamentals(["AAA", "BBB", "ZZZ"], get_json=_Directory(failing=["AAA"], empty=["BBB"]), pause_seconds=0.1, cache_dir=tmp_path / "y")
    assert missing == ["AAA", "BBB", "ZZZ"] and sectors == {"BBB": "information_technology"} and "AAA: RuntimeError" in capsys.readouterr().out
    assert (tmp_path / "y" / "bbb.json").exists() and slept == [0.1, 0.1]
    again = ef.fetch_fundamentals(["BBB"], get_json=_Directory(), pause_seconds=0, cache_dir=tmp_path / "y")
    assert again[1] == {"BBB": "information_technology"}


def test_the_sec_client_sets_a_user_agent_and_the_eps_fetch_pauses_between_companies(monkeypatch):
    seen = {}
    requests = ModuleType("requests")
    requests.get = lambda url, timeout, headers: seen.update(url=url, headers=headers) or SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"ok": 1})
    monkeypatch.setitem(sys.modules, "requests", requests)
    monkeypatch.setenv(ef.CONTACT_ENV, "me@example.org")
    assert ef._get_json("https://sec") == {"ok": 1} and seen["headers"]["User-Agent"].endswith("me@example.org")
    slept = []
    monkeypatch.setattr(ef._time, "sleep", lambda seconds: slept.append(seconds))
    rows, missing = ef.fetch_eps(["AAA", "FB", "ZZZ"], get_json=_Directory(), pause_seconds=0.2)
    assert missing == ["FB", "ZZZ"] and rows and slept == [0.2]
    assert ef.fetch_eps(["AAA"], get_json=_Directory(failing=["AAA"]), pause_seconds=0)[1] == ["AAA"]


def _yahoo(monkeypatch, splits_by_symbol):
    module = ModuleType("yfinance")

    def ticker(symbol):
        value = splits_by_symbol[symbol]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(splits=value)

    module.Ticker = ticker
    monkeypatch.setitem(sys.modules, "yfinance", module)


def test_splits_come_from_yahoo_and_a_failed_name_is_listed(monkeypatch):
    series = pd.Series([2.0, 0.0], index=pd.to_datetime(["2020-08-31", "2021-01-04"]))
    _yahoo(monkeypatch, {"AAA": series, "META": series, "BRK-B": series, "BAD": RuntimeError("no")})
    assert ef.fetch_splits(["AAA", "FB"]) == [{"ticker": "AAA", "date": "2020-08-31", "ratio": 2.0}, {"ticker": "FB", "date": "2020-08-31", "ratio": 2.0}]
    rows, failed = ef.fetch_splits_tolerant(["BRK.B", "BAD"])
    assert failed == ["BAD"] and rows[0]["ticker"] == "BRK.B"


def test_a_filing_after_the_last_session_sets_no_surprise():
    rows = [{"ticker": "AAA", "period_end": f"20{20 + index // 4}-{(index % 4) * 3 + 3:02d}-28", "filed": f"20{20 + index // 4}-{(index % 4) * 3 + 3:02d}-29", "eps": [1.0, 1.2, 1.1, 1.5, 1.3, 1.9, 1.4, 2.0][index]} for index in range(8)]
    rows.append({"ticker": "AAA", "period_end": "2022-03-28", "filed": "2030-01-01", "eps": 99.0})
    sessions = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2020-01-01", "2022-06-30")]
    table = ef.surprise_table(pd.DataFrame(rows), sessions, ["AAA"], hold_sessions=5)
    assert table.shape == (len(sessions), 1)


def test_the_command_line_plans_fetches_splits_and_eps(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"phase1": {"universe": {"assets": [{"ticker": "AAA", "security_type": "equity"}, {"ticker": "BTC", "security_type": "crypto"}]}}}), encoding="utf-8")
    monkeypatch.setattr(ef, "OUTPUT", tmp_path / "eps.csv")
    monkeypatch.setattr(ef, "SPLITS_OUTPUT", tmp_path / "splits.csv")
    assert ef.main(["--config", str(config)]) == 0 and "would fetch 1 tickers" in capsys.readouterr().out
    monkeypatch.setattr(ef, "fetch_splits", lambda tickers: [{"ticker": "AAA", "date": "2020-08-31", "ratio": 2.0}])
    written = []
    monkeypatch.setattr(ef, "write_splits", lambda rows: written.append(rows))
    assert ef.main(["--config", str(config), "--apply", "--splits"]) == 0 and written and "1 splits for 1 tickers" in capsys.readouterr().out
    monkeypatch.setattr(ef, "fetch_eps", lambda tickers: ([{"ticker": "AAA"}], []))
    monkeypatch.setattr(ef, "write_eps", lambda rows: written.append(rows))
    assert ef.main(["--config", str(config), "--apply"]) == 0 and "1 quarters for 1 tickers" in capsys.readouterr().out
    assert date is not None


def test_a_ticker_outside_the_columns_is_ignored_in_the_fundamentals_table():
    rows = pd.DataFrame([{"ticker": "OTHER", "field": "revenue", "period_end": "2023-12-31", "filed": "2024-02-01", "form": "10-K", "value": 1.0}])
    table = ef.fundamentals_table(rows, ["2024-02-02", "2024-02-05"], ["AAA"], "revenue")
    assert table.isna().all().all()


def test_the_module_runs_as_a_script(tmp_path, monkeypatch, capsys):
    import runpy

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"phase1": {"universe": {"assets": [{"ticker": "AAA", "security_type": "equity"}]}}}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["edgar_facts", "--config", str(config)])
    monkeypatch.delitem(sys.modules, "data_pipeline.edgar_facts", raising=False)
    try:
        runpy.run_module("data_pipeline.edgar_facts", run_name="__main__")
    except SystemExit as stop:
        assert stop.code == 0
    assert "would fetch" in capsys.readouterr().out
