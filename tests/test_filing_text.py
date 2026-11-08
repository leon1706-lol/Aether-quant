"""data_pipeline/filing_text.py on fixtures: no network, and the text of a filing is never kept (V6.6.4)."""

from __future__ import annotations

import pytest

from data_pipeline import filing_text as ft


def test_tokens_strip_tags_entities_and_short_words():
    assert ft.tokens("<p>The  Company&nbsp;reports <b>Revenue</b> of 12 USD, up 3%.</p>") == ["the", "company", "reports", "revenue", "usd"]
    assert ft.tokens("") == [] and ft.tokens(None) == []


def test_hashed_counts_are_stable_and_count_repeats():
    first = ft.hashed_counts(["alpha", "beta", "alpha"])
    assert first == ft.hashed_counts(["alpha", "beta", "alpha"])
    assert sorted(first.values()) == [1, 2]
    assert ft.hashed_counts(["alpha"], buckets=1 << 18) == ft.hashed_counts(["alpha"])
    assert list(ft.hashed_counts(["alpha"]).keys())[0] == int.from_bytes(__import__("hashlib").blake2b(b"alpha", digest_size=4).digest(), "big") % (1 << 18)


def test_cosine_by_hand_and_the_empty_cases():
    assert ft.cosine({1: 1, 2: 1}, {1: 1, 2: 1}) == pytest.approx(1.0)
    assert ft.cosine({1: 1}, {2: 1}) == 0.0
    assert ft.cosine({1: 3, 2: 4}, {1: 4, 2: 3}) == pytest.approx(24.0 / 25.0)
    assert ft.cosine({}, {1: 1}) is None and ft.cosine({1: 1}, {}) is None


def _submissions():
    return {"filings": {"recent": {
        "accessionNumber": ["0001", "0002", "0003", "0004", "0005"],
        "filingDate": ["2020-02-20", "2019-02-21", "2020-05-01", "2020-04-28", "2019-05-02"],
        "acceptanceDateTime": ["2020-02-20T16:30:00.000Z", "2019-02-21T17:10:00.000Z", "2020-05-01T20:05:00.000Z", "2020-04-28T12:01:00.000Z", "2019-05-02T20:00:00.000Z"],
        "form": ["10-K", "10-K", "10-Q", "8-K", "10-Q"],
        "primaryDocument": ["a20.htm", "a19.htm", "q20.htm", "e.htm", "q19.htm"],
        "items": ["", "", "", "2.02,9.01", ""],
        "reportDate": ["2019-12-31", "2018-12-31", "2020-03-31", "2020-04-28", "2019-03-31"],
    }}}


def test_merge_pages_orders_by_filing_date_and_dedupes():
    older = {"accessionNumber": ["0002", "0009"], "filingDate": ["2019-02-21", "2018-02-20"], "form": ["10-K", "10-K"], "primaryDocument": ["a19.htm", "a18.htm"], "reportDate": ["2018-12-31", "2017-12-31"]}
    rows = ft.merge_pages([_submissions(), older])
    assert [row["accessionNumber"] for row in rows] == ["0009", "0002", "0005", "0001", "0004", "0003"]


def test_earnings_rows_keep_only_item_202_eight_ks():
    rows = ft.earnings_rows(ft.merge_pages([_submissions()]))
    assert rows == [{"accepted": "2020-04-28T12:01:00.000Z", "filed": "2020-04-28"}]


def test_each_filing_pairs_with_the_same_form_a_year_earlier_and_never_a_later_one():
    pairs = ft.prior_year_pairs(ft.merge_pages([_submissions()]))
    named = {(current["accessionNumber"], earlier["accessionNumber"]) for current, earlier in pairs}
    assert named == {("0001", "0002"), ("0003", "0005")}


def test_similarity_rows_compute_one_cosine_per_pair_and_skip_unreadable_filings():
    filings = ft.merge_pages([_submissions()])
    counts = {"a20.htm": {1: 3, 2: 4}, "a19.htm": {1: 4, 2: 3}, "q20.htm": {1: 1}, "q19.htm": None}
    rows = ft.similarity_rows(filings, lambda row: counts.get(row["primaryDocument"]))
    assert len(rows) == 1 and rows[0]["form"] == "10-K" and rows[0]["filed"] == "2020-02-20" and rows[0]["similarity"] == pytest.approx(24.0 / 25.0)
    assert set(rows[0]) == {"form", "period_end", "filed", "similarity"}, "no filing text in a row"
