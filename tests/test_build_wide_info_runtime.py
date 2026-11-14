"""scripts/build_wide_info.py's runtime (V6.6.6, #359): each part of the wide root's non-price data, the contact-leak search and the resumable `main()`,
with SEC, FINRA, the factor library and the network replaced by fakes."""

from __future__ import annotations

import gzip
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from script_loader import load_script


@pytest.fixture
def module(monkeypatch, tmp_path):
    script = load_script("build_wide_info")
    wide = tmp_path / "data_wide"
    (wide / "reference").mkdir(parents=True)
    (wide / "_cache").mkdir()
    for name, value in (("ROOT", tmp_path), ("WIDE", wide), ("REFERENCE", wide / "reference"), ("CACHE", wide / "_cache")):
        monkeypatch.setattr(script, name, value)
    monkeypatch.setattr(script.member_tickers, "__defaults__", (wide,))  # the default root is bound when the module loads
    monkeypatch.setattr(script._time, "sleep", lambda seconds: None)
    monkeypatch.setenv(script.CONTACT_ENV, "owner@example.org")
    return script


def test_member_tickers_are_the_sorted_members_only(module):
    (module.WIDE / "wide_manifest.json").write_text(json.dumps({"tickers": {"BBB": {"member": True}, "AAA": {"member": True}, "CCC": {}}}), encoding="utf-8")
    assert module.member_tickers(module.WIDE) == ["AAA", "BBB"]


def test_the_sec_client_needs_a_contact(module, monkeypatch):
    assert "owner@example.org" in module.sec_headers()["User-Agent"]
    monkeypatch.setenv(module.CONTACT_ENV, "")
    with pytest.raises(SystemExit, match="no contact"):
        module.sec_headers()


def test_fundamentals_splits_and_extended_are_written_beside_their_counts(module, monkeypatch):
    facts = module.edgar_facts
    monkeypatch.setattr(facts, "fetch_fundamentals", lambda tickers, cache_dir: ([{"a": 1}], {"BBB": "tech", "AAA": "energy"}, {"ZZZ"}))
    written = []
    monkeypatch.setattr(facts, "write_fundamentals", lambda rows, path: written.append(path.name))
    monkeypatch.setattr(facts, "collect_cached_eps", lambda tickers, cache_dir: [("AAA", "2020-01-01", "2020-03-31", "2020-05-01", 1.5)])
    assert module.build_fundamentals(["AAA"]) == {"fundamental_rows": 1, "tickers_with_sector": 2, "no_sec_data": ["ZZZ"]}
    assert json.loads((module.REFERENCE / "sectors.json").read_text(encoding="utf-8")) == {"AAA": "energy", "BBB": "tech"} and (module.REFERENCE / "edgar_eps.csv.gz").exists()
    monkeypatch.setattr(facts, "fetch_extended", lambda tickers, cache_dir: ([{"a": 1}, {"a": 2}], {"QQQ"}))
    assert module.build_extended(["AAA"]) == {"extended_rows": 2, "no_sec_data": ["QQQ"]} and written == ["edgar_fundamentals.csv.gz", "edgar_fundamentals_ext.csv.gz"]
    monkeypatch.setattr(facts, "fetch_splits_tolerant", lambda tickers: ([("AAA", "2020-01-01", 2.0)], {"BAD"}))
    assert module.build_splits(["AAA"]) == {"split_rows": 1, "split_lookup_failed": ["BAD"]} and (module.REFERENCE / "equity_splits.csv").exists()


def _requests(monkeypatch, **attributes):
    stub = types.ModuleType("requests")
    for name, value in attributes.items():
        setattr(stub, name, value)
    monkeypatch.setitem(sys.modules, "requests", stub)
    return stub


def test_the_sec_getter_returns_bytes_or_none(module, monkeypatch):
    _requests(monkeypatch, get=lambda *args, **kwargs: None)
    responses = iter([SimpleNamespace(content=b"zip"), None])
    monkeypatch.setattr(module.net_retry, "fetch", lambda url, get, headers, timeout: next(responses))
    getter = module._sec_get_bytes({"User-Agent": "x"})
    assert getter("u") == b"zip" and getter("u") is None


def test_insider_quarters_are_read_from_cache_refetched_when_empty_and_never_cached_empty(module, monkeypatch, capsys):
    _requests(monkeypatch, get=lambda *args, **kwargs: None)
    monkeypatch.setattr(module.sec_form345, "quarters", lambda start, end, quarter: [(2006, 1), (2006, 2), (2006, 3), (2006, 4)])
    cache = module.CACHE / "form345"
    cache.mkdir(parents=True)
    pd.DataFrame({"ticker": ["AAA"], "shares": ["5"]}).to_csv(cache / "2006q1.csv.gz", index=False, compression="gzip")
    pd.DataFrame({"ticker": [], "shares": []}).to_csv(cache / "2006q2.csv.gz", index=False, compression="gzip")
    fetched = []

    def fetch(periods, get, wanted):
        fetched.append(periods[0])
        return pd.DataFrame({"ticker": ["BBB"], "shares": [7]}) if periods[0] != (2006, 3) else pd.DataFrame()

    monkeypatch.setattr(module.sec_form345, "fetch_trades", fetch)
    result = module.build_insiders(["AAA", "BBB"])
    assert result == {"insider_trades": 3} and fetched == [(2006, 2), (2006, 3), (2006, 4)] and not (cache / "2006q3.csv.gz").exists() and "no trades, not cached" in capsys.readouterr().out


class _Session:
    def __init__(self):
        self.headers = {}
        self.get = lambda url, **kwargs: None


def _period_range(monkeypatch, module, months):
    monkeypatch.setattr(module.pd, "period_range", lambda start, end, freq: pd.PeriodIndex(months, freq="M"))


def test_short_volume_is_cached_by_month_and_files_that_are_absent_are_skipped(module, monkeypatch, capsys):
    _requests(monkeypatch, Session=_Session)
    _period_range(monkeypatch, module, ["2018-08", "2018-09", "2018-10"])
    cache = module.CACHE / "finra"
    cache.mkdir(parents=True)
    pd.DataFrame({"AAA": [0.4]}, index=["2018-08-01"]).astype("float32").to_parquet(cache / "2018-08.parquet")
    seen = []

    def fetch(days, get_text, tickers):
        seen.append(len(days))
        if days[0].startswith("2018-09"):
            assert get_text("u") == "text" and get_text("v") is None
            return pd.DataFrame()
        return pd.DataFrame({"AAA": [0.5, 0.6]}, index=["2018-10-01", "2018-10-02"])

    answers = iter([SimpleNamespace(text="text"), None])
    monkeypatch.setattr(module.net_retry, "fetch", lambda url, get, absent_codes, timeout: next(answers))
    monkeypatch.setattr(module.finra_short_volume, "fetch_ratios", fetch)
    result = module.build_short(["AAA"])
    assert result["short_ratio_days"] == 3 and result["short_ratio_first"] == "2018-08-01" and len(seen) == 2 and "no files, not cached" in capsys.readouterr().out


def test_a_short_volume_run_that_read_nothing_is_a_failure(module, monkeypatch):
    _requests(monkeypatch, Session=_Session)
    _period_range(monkeypatch, module, ["2018-08"])
    cache = module.CACHE / "finra"
    cache.mkdir(parents=True)
    pd.DataFrame({"AAA": []}, dtype="float32").to_parquet(cache / "2018-08.parquet")
    with pytest.raises(SystemExit, match="no short-volume file read"):
        module.build_short(["AAA"])


def test_factors_are_downloaded_and_summarized_by_their_last_date(module, monkeypatch):
    _requests(monkeypatch, get=lambda url, timeout, headers: SimpleNamespace(content=b"csv", raise_for_status=lambda: None))
    frame = pd.DataFrame({"MKT": [0.1, 0.2], "SMB": [0.0, None]}, index=["2020-01-01", "2020-01-02"])
    monkeypatch.setattr(module.factor_library, "fetch_factors", lambda get: (get("u") == b"csv") and frame)
    result = module.build_factors()
    assert result["factors"] == ["MKT", "SMB"] and result["factors_last"] == {"MKT": "2020-01-02", "SMB": "2020-01-01"} and (module.REFERENCE / "factors_daily.parquet").exists()


def test_a_contact_is_found_in_plain_and_gzipped_files_but_not_where_it_cannot_be_read(module, monkeypatch, tmp_path):
    root = tmp_path / "scan"
    (root / "folder").mkdir(parents=True)
    (root / "plain.txt").write_text("hello owner@example.org", encoding="utf-8")
    (root / "zipped.gz").write_bytes(gzip.compress(b"hello owner@example.org"))
    (root / "clean.txt").write_text("nothing", encoding="utf-8")
    (root / "locked.txt").write_text("owner@example.org", encoding="utf-8")
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError("denied")) if self.name == "locked.txt" else real(self))
    hits = module.contact_leaks(root, "owner@example.org")
    assert sorted(Path(hit).name for hit in hits) == ["plain.txt", "zipped.gz"] and module.contact_leaks(root, "") == []


def _main_world(module, monkeypatch, tmp_path, *, builders=None):
    (module.WIDE / "wide_manifest.json").write_text(json.dumps({"tickers": {"AAA": {"member": True}}}), encoding="utf-8")
    ran = []
    for name in ("build_fundamentals", "build_splits", "build_insiders", "build_short", "build_extended"):
        monkeypatch.setattr(module, name, (builders or {}).get(name, lambda tickers, _n=name: ran.append(_n) or {"rows": 1, "names": ["a"]}))
    monkeypatch.setattr(module, "build_factors", (builders or {}).get("build_factors", lambda: ran.append("build_factors") or {"factors": ["MKT"]}))
    return ran


def test_the_default_parts_run_in_order_and_each_result_is_saved(module, monkeypatch, tmp_path, capsys):
    ran = _main_world(module, monkeypatch, tmp_path)
    (module.REFERENCE / "wide_info_report.json").write_text(json.dumps({"earlier": {"x": 1}}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["build_wide_info"])
    assert module.main() == 0
    report = json.loads((module.REFERENCE / "wide_info_report.json").read_text(encoding="utf-8"))
    assert ran == ["build_fundamentals", "build_splits", "build_insiders", "build_short", "build_factors"] and set(report) == {"earlier", "fundamentals", "splits", "insiders", "short", "factors"}


def test_a_refresh_drops_the_extended_cache_and_a_leak_fails_the_run(module, monkeypatch, tmp_path, capsys):
    ran = _main_world(module, monkeypatch, tmp_path)
    (module.CACHE / "edgar_ext").mkdir()
    (module.CACHE / "edgar_ext" / "old.json").write_text("{}", encoding="utf-8")
    (module.REFERENCE / "leak.txt").write_text("owner@example.org", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["build_wide_info", "--parts", "extended", "--refresh"])
    assert module.main() == 2
    assert ran == ["build_extended"] and not (module.CACHE / "edgar_ext").exists() and "CONTACT FOUND IN" in capsys.readouterr().err


def test_a_network_outage_stops_the_run_with_a_resumable_exit(module, monkeypatch, tmp_path, capsys):
    def down(tickers):
        raise module.net_retry.NetworkOutage("offline")

    _main_world(module, monkeypatch, tmp_path, builders={"build_splits": down})
    monkeypatch.setattr(sys, "argv", ["build_wide_info", "--parts", "splits"])
    assert module.main() == 3 and "stopped by a network outage" in capsys.readouterr().err
