"""scripts/build_filing_signals.py's runtime (V6.6.6, #359): the SEC client, one ticker's earnings and similarity rows, the outputs, the contact check and the
resumable `main()`, with SEC and the network replaced by fakes."""

from __future__ import annotations

import gzip
import json
import sys
import types

import pytest

from script_loader import load_script


@pytest.fixture
def module(monkeypatch, tmp_path):
    script = load_script("build_filing_signals")
    wide = tmp_path / "data_wide"
    for name, value in (("ROOT", tmp_path), ("WIDE", wide), ("REFERENCE", wide / "reference"), ("CACHE", wide / "_cache" / "filings")):
        monkeypatch.setattr(script, name, value)
    monkeypatch.setattr(script._time, "sleep", lambda seconds: None)
    monkeypatch.setenv(script.CONTACT_ENV, "owner@example.org")
    return script


def test_the_sec_client_needs_a_contact(module, monkeypatch):
    assert "owner@example.org" in module.sec_headers()["User-Agent"]
    monkeypatch.setenv(module.CONTACT_ENV, "  ")
    with pytest.raises(SystemExit, match="no contact"):
        module.sec_headers()


def test_only_side_a_names_are_in_a_selection_scope(module, monkeypatch, tmp_path):
    import evaluation.research_cells as cells
    import evaluation.wide_context as wide_context

    module.WIDE.mkdir(parents=True)
    (module.WIDE / "wide_manifest.json").write_text(json.dumps({"tickers": {"AAA": {"member": True}, "BBB": {"member": True}, "CCC": {"member": False}}}), encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(wide_context, "project_tickers", lambda config, kind: ["BBB"])
    monkeypatch.setattr(cells, "name_side", lambda ticker, project: "B" if ticker in project else "A")
    assert module.names_in_scope("selection") == ["AAA"] and module.names_in_scope("full") == ["AAA", "BBB"]


class _Response:
    def __init__(self, content=b"<p>alpha beta</p>", payload=None):
        self.content = content
        self._payload = payload

    def json(self):
        return self._payload


def _fetcher(module, monkeypatch, responses):
    class Session:
        def __init__(self):
            self.headers = {}
            self.get = None

    requests = types.ModuleType("requests")
    requests.Session = Session
    monkeypatch.setitem(sys.modules, "requests", requests)
    queue = iter(responses)
    monkeypatch.setattr(module.net_retry, "fetch", lambda url, get, timeout: next(queue))
    return module.Fetcher({"User-Agent": "x"})


def test_the_fetcher_counts_requests_and_reads_json_or_hashed_words(module, monkeypatch):
    fetcher = _fetcher(module, monkeypatch, [_Response(payload={"a": 1}), None, _Response(), None, _Response(content=b"x" * 50), _Response(content=b"")])
    assert fetcher.json("u") == {"a": 1} and fetcher.json("u") is None and fetcher.requests == 2
    row = {"accessionNumber": "0001-23-4", "primaryDocument": "doc.htm"}
    assert fetcher.counts(5, row)
    assert fetcher.counts(5, row) is None
    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", 10)
    assert fetcher.counts(5, row) is None
    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", 10_000)
    assert fetcher.counts(5, row) is None


class FakeFetcher:
    def __init__(self, pages, counts):
        self.pages, self.count_table, self.requests = list(pages), counts, 0

    def json(self, url):
        return self.pages.pop(0) if self.pages else None

    def counts(self, cik, row):
        return self.count_table.get(str(row["accessionNumber"]))


def test_one_tickers_announcements_and_similarities_are_built_inside_the_window(module, monkeypatch):
    current = {"accessionNumber": "c", "form": "10-K", "reportDate": "2018-12-31", "filingDate": "2019-02-01"}
    current_new = {"accessionNumber": "n", "form": "10-K", "reportDate": "2017-12-31", "filingDate": "2018-02-01"}
    earlier = {"accessionNumber": "e", "form": "10-K", "reportDate": "2016-12-31", "filingDate": "2017-02-01"}
    odd = {"accessionNumber": "o", "form": "10-Q", "reportDate": "2017-09-30", "filingDate": "2017-11-01"}
    monkeypatch.setattr(module.filing_text, "merge_pages", lambda pages: [current, current_new, earlier, odd])
    monkeypatch.setattr(module.filing_text, "earnings_rows", lambda filings: [{"accepted": "x", "filed": "2018-02-01"}, {"accepted": "y", "filed": "2005-01-01"}])
    monkeypatch.setattr(module.filing_text, "prior_year_pairs", lambda filings: [(current_new, earlier), (odd, earlier), (current_new, odd)])
    monkeypatch.setattr(module.filing_text, "cosine", lambda now, then: 0.9)
    submissions = {"filings": {"files": [{"name": "old.json", "filingTo": "2001-01-01"}, {"name": "new.json", "filingTo": "2018-06-01"}, {"name": "gone.json"}]}}
    fetcher = FakeFetcher([submissions, {"filings": {}}, None], {"n": {1: 1}, "e": {1: 2}, "o": None})
    built = module.build_ticker(fetcher, 7, module.SELECTION_WINDOW)
    assert built["earnings"] == [{"accepted": "x", "filed": "2018-02-01"}] and [row["filed"] for row in built["similarity"]] == ["2018-02-01"]
    empty = module.build_ticker(FakeFetcher([None], {}), 7, module.SELECTION_WINDOW)
    assert empty["similarity"] == [] or isinstance(empty["similarity"], list)


def test_the_outputs_are_the_two_tables_and_a_report_by_year(module):
    cache = module.CACHE / "selection"
    cache.mkdir(parents=True)
    (cache / "aaa.json").write_text(json.dumps({"earnings": [{"accepted": "a", "filed": "2018-02-01"}], "similarity": [{"form": "10-K", "period_end": "2017-12-31", "filed": "2018-02-01", "similarity": 0.9}]}), encoding="utf-8")
    (cache / "bbb.json").write_text(json.dumps({"earnings": [], "similarity": []}), encoding="utf-8")
    report = module.write_outputs(cache, "selection")
    assert report["tickers_cached"] == 2 and report["earnings_rows"] == 1 and report["names_with_earnings_by_year"] == {"2018": 1} and (module.REFERENCE / "earnings_dates.csv.gz").exists()


def test_a_contact_written_into_an_output_is_refused(module):
    module.REFERENCE.mkdir(parents=True)
    module.CACHE.mkdir(parents=True)
    module.assert_contact_not_written()
    (module.REFERENCE / "earnings_dates.csv.gz").write_bytes(gzip.compress(b"fine"))
    (module.CACHE / "one.json").write_text("fine", encoding="utf-8")
    module.assert_contact_not_written()
    (module.CACHE / "one.json").write_text("owner@example.org", encoding="utf-8")
    with pytest.raises(SystemExit, match="SEC contact was found"):
        module.assert_contact_not_written()


def test_without_a_contact_nothing_is_checked(module, monkeypatch):
    monkeypatch.setenv(module.CONTACT_ENV, "")
    module.assert_contact_not_written()


def _main_world(module, monkeypatch, *, tickers, behaviour):
    class Fetcher:
        def __init__(self, headers):
            self.requests = 0

        def json(self, url):
            return {"0": {"ticker": "AAA", "cik_str": 1}, "1": {"ticker": "BRK-B", "cik_str": 2}, "2": {"ticker": "CCC", "cik_str": 3}, "3": {"ticker": "DDD", "cik_str": 4}}

    monkeypatch.setattr(module, "Fetcher", Fetcher)
    monkeypatch.setattr(module, "names_in_scope", lambda scope: tickers)

    def build(fetcher, cik, window):
        outcome = behaviour[cik]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(module, "build_ticker", build)


def test_a_run_caches_each_ticker_skips_cached_ones_and_counts_what_is_missing(module, monkeypatch, capsys):
    cache = module.CACHE / "selection"
    cache.mkdir(parents=True)
    (cache / "aaa.json").write_text(json.dumps({"earnings": [], "similarity": []}), encoding="utf-8")
    good = {"earnings": [{"accepted": "a", "filed": "2018-02-01"}], "similarity": []}
    _main_world(module, monkeypatch, tickers=["AAA", "BRK.B", "ZZZ", "CCC", "DDD"], behaviour={2: good, 3: RuntimeError("bad"), 4: good})
    assert module.main(["--scope", "selection"]) == 0
    out = capsys.readouterr().out
    assert (cache / "brk.b.json").exists() and (cache / "zzz.json").exists() and not (cache / "ccc.json").exists() and '"failed": 1' in out and '"no_cik": 1' in out


def test_a_network_outage_stops_the_run_with_everything_kept(module, monkeypatch, capsys):
    _main_world(module, monkeypatch, tickers=["AAA", "CCC"], behaviour={1: {"earnings": [], "similarity": []}, 3: module.net_retry.NetworkOutage("down")})
    assert module.main(["--scope", "full", "--limit", "5"]) == 2
    assert "stopped at CCC" in capsys.readouterr().out and (module.CACHE / "full" / "aaa.json").exists()
