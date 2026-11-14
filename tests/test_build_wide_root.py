"""scripts/build_wide_root.py (V6.6.6): Yahoo's adjusted and raw closes from one download, retries and pauses between names,
progress every 25 names, and the CLI. tests/test_sp500_membership.py covers the root's contents; no network here."""

from __future__ import annotations

import datetime
import json
import sys
import types

import pandas as pd

from script_loader import load_script


def _yfinance(monkeypatch, frame):
    module = types.ModuleType("yfinance")
    module.download = lambda symbol, **kwargs: frame
    monkeypatch.setitem(sys.modules, "yfinance", module)


def test_one_download_gives_the_rows_and_the_split_adjusted_closes(monkeypatch):
    module = load_script("build_wide_root")
    index = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    columns = pd.MultiIndex.from_tuples([(name, "AAA") for name in ("Open", "High", "Low", "Close", "Adj Close", "Volume")])
    frame = pd.DataFrame([[10, 11, 9, 10, 9.0, 100], [10, 11, 9, 0.0, 9.0, 100], [12, 13, 11, 12, 10.8, 200]], index=index, columns=columns, dtype=float)
    _yfinance(monkeypatch, frame)
    rows, raw = module.fetch_adjusted_and_raw("AAA", "2020-01-01", "2020-01-07")
    assert [row["date"] for row in rows] == [datetime.date(2020, 1, 2), datetime.date(2020, 1, 6)]
    assert raw == {"2020-01-02": 10.0, "2020-01-06": 12.0} and rows[0]["close"] == 9.0
    _yfinance(monkeypatch, pd.DataFrame())
    assert module.fetch_adjusted_and_raw("AAA", "2020-01-01", "2020-01-07") == ([], {})
    _yfinance(monkeypatch, None)
    assert module.fetch_adjusted_and_raw("AAA", "2020-01-01", "2020-01-07") == ([], {})


def _rows(first, count):
    return [{"date": first + datetime.timedelta(days=offset), "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 100} for offset in range(count)], {}


def test_failures_are_retried_with_a_pause_and_progress_is_saved_every_25_names(tmp_path, monkeypatch, capsys):
    module = load_script("build_wide_root")
    sleeps = []
    monkeypatch.setattr(module._time, "sleep", sleeps.append)
    attempts = {}

    def fetch(symbol, start, end):
        attempts[symbol] = attempts.get(symbol, 0) + 1
        if symbol == "FLAKY" and attempts[symbol] == 1:
            raise ConnectionError("reset")
        if symbol == "DEAD":
            raise ConnectionError("gone")
        return _rows(datetime.date(2005, 1, 3), 3)

    names = ["DEAD", "FLAKY", *[f"N{index:02d}" for index in range(30)]]
    text = "ticker,start_date,end_date\n" + "".join(f"{name},2005-01-03,\n" for name in names)
    config = {"phase1": {"universe": {"assets": []}}}
    manifest = module.build_root(tmp_path / "wide", start="2003-06-01", end="2026-11-03", config=config, source=tmp_path / "none", fetch_fn=fetch,
                                 pause_seconds=0.01, get_membership=lambda url: text, retries=1)
    assert manifest["left_out"]["DEAD"] == "fetch failed: ConnectionError" and "FLAKY" in manifest["tickers"]
    assert attempts["DEAD"] == 2 and 0.05 in sleeps and 0.01 in sleeps
    assert "25 of" in capsys.readouterr().out


def test_main_builds_under_the_repository(tmp_path, monkeypatch, capsys):
    module = load_script("build_wide_root")
    (tmp_path / "config.json").write_text(json.dumps({"phase1": {"universe": {"assets": []}}}), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    seen = {}
    monkeypatch.setattr(module, "build_root", lambda out, **kwargs: seen.update(out=out, **kwargs) or {"tickers": {"A": {}}, "left_out": {}})
    monkeypatch.setattr(module.sys, "argv", ["x", "--out", "wide"])
    assert module.main() == 0
    assert seen["out"] == tmp_path / "wide" and seen["coverage_path"].name.startswith("wide_co") and "1 tickers written" in capsys.readouterr().out
