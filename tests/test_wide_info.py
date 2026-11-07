"""EDGAR fundamentals, Form 4 trades, FINRA short volume, factor files and their builder, on fixtures: no network."""

from __future__ import annotations

import gzip
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_pipeline import edgar_facts, factor_library, finra_short_volume, sec_form345

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SESSIONS = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2019-01-01", "2019-12-31")]


def _facts():
    return {"facts": {
        "us-gaap": {
            "Assets": {"units": {"USD": [
                {"end": "2018-12-31", "filed": "2019-03-01", "form": "10-K", "val": 100.0},
                {"end": "2018-12-31", "filed": "2020-03-01", "form": "10-K", "val": 999.0},  # restated comparative
                {"end": "2019-06-30", "filed": "2019-08-01", "form": "10-Q", "val": 500.0},  # not annual
            ]}},
            "NetIncomeLoss": {"units": {"USD": [
                {"start": "2018-01-01", "end": "2018-12-31", "filed": "2019-03-01", "form": "10-K", "val": 10.0},
                {"start": "2018-10-01", "end": "2018-12-31", "filed": "2019-03-01", "form": "10-K", "val": 3.0},  # a quarter inside the 10-K
            ]}},
            "Revenues": {"units": {"USD": [{"start": "2018-01-01", "end": "2018-12-31", "filed": "2019-03-01", "form": "10-K", "val": 50.0}]}},
            "SalesRevenueNet": {"units": {"USD": [
                {"start": "2018-01-01", "end": "2018-12-31", "filed": "2019-03-01", "form": "10-K", "val": 77.0},
                {"start": "2017-01-01", "end": "2017-12-31", "filed": "2018-03-01", "form": "10-K", "val": 40.0},
            ]}},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2019-02-15", "filed": "2019-03-01", "form": "10-K", "val": 1000.0},
        ]}}},
    }}


def _flow_facts():
    """A calendar-year filer's cash flow: year-to-date in each 10-Q, with last year's comparative, and a standalone quarter that must not count."""
    def entry(start, end, filed, form, value):
        return {"start": start, "end": end, "filed": filed, "form": form, "val": value}

    return {"facts": {"us-gaap": {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            entry("2018-01-01", "2018-12-31", "2019-02-20", "10-K", 120.0),
            entry("2018-01-01", "2018-06-30", "2018-08-01", "10-Q", 50.0),
            entry("2019-01-01", "2019-06-30", "2019-08-01", "10-Q", 80.0),
            entry("2018-01-01", "2018-06-30", "2019-08-01", "10-Q", 55.0),  # a restated comparative, filed later: the first filing stands
            entry("2019-04-01", "2019-06-30", "2019-08-01", "10-Q", 41.0),  # standalone second quarter
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            entry("2018-01-01", "2018-12-31", "2019-02-20", "10-K", 100.0),
            entry("2018-01-01", "2018-06-30", "2018-08-01", "10-Q", 40.0),
            entry("2019-01-01", "2019-06-30", "2019-08-01", "10-Q", 70.0),
        ]}},
        "Assets": {"units": {"USD": [
            {"end": "2018-12-31", "filed": "2019-02-20", "form": "10-K", "val": 1000.0},
            {"end": "2019-06-30", "filed": "2019-08-01", "form": "10-Q", "val": 1100.0},
            {"end": "2019-06-30", "filed": "2020-08-01", "form": "10-Q", "val": 9999.0},
        ]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
            entry("2018-01-01", "2018-12-31", "2019-02-20", "10-K", 30.0),
        ]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            {"end": "2018-12-31", "filed": "2019-02-20", "form": "10-K", "val": 200.0},
        ]}},
    }}}


def _by_field(rows, field):
    return {row["period_end"]: row for row in rows if row["field"] == field}


def test_ttm_is_last_year_plus_this_ytd_less_the_comparative():
    rows = _by_field(edgar_facts.quarterly_ttm_rows(_flow_facts()), "ttm_operating_cash_flow")
    assert rows["2019-06-30"]["value"] == pytest.approx(120.0 + 80.0 - 50.0)
    assert rows["2018-12-31"]["value"] == pytest.approx(120.0)


def test_ttm_is_usable_only_from_its_latest_part():
    rows = _by_field(edgar_facts.quarterly_ttm_rows(_flow_facts()), "ttm_net_income")
    assert rows["2019-06-30"]["filed"] == "2019-08-01"
    assert rows["2019-06-30"]["value"] == pytest.approx(100.0 + 70.0 - 40.0)


def test_a_standalone_quarter_never_makes_a_ttm():
    durations = edgar_facts._first_filed_durations(_flow_facts(), "NetCashProvidedByUsedInOperatingActivities")
    alone = {key: row for key, row in durations.items() if key == ("2019-04-01", "2019-06-30")}
    assert edgar_facts._ttm_rows(alone) == []


def test_later_restatements_do_not_change_what_was_public():
    rows = _by_field(edgar_facts.quarterly_ttm_rows(_flow_facts()), "assets_q")
    assert rows["2019-06-30"]["value"] == 1100.0 and rows["2019-06-30"]["filed"] == "2019-08-01"
    cut = _flow_facts()
    cut["facts"]["us-gaap"]["Assets"]["units"]["USD"].pop()
    assert _by_field(edgar_facts.quarterly_ttm_rows(cut), "assets_q") == rows


def test_extended_rows_add_the_annual_fields():
    rows = edgar_facts.extended_rows(_flow_facts())
    assert _by_field(rows, "capex")["2018-12-31"]["value"] == 30.0
    assert _by_field(rows, "cash")["2018-12-31"]["value"] == 200.0
    assert not _by_field(rows, "rd_expense")


def test_fetch_extended_reports_names_sec_has_not_and_resumes(tmp_path):
    calls = []

    def get_json(url):
        calls.append(url)
        if url == edgar_facts.TICKERS_URL:
            return {"0": {"ticker": "AAA", "cik_str": 1}}
        return _flow_facts()

    rows, missing = edgar_facts.fetch_extended(["AAA", "GONE"], get_json, pause_seconds=0.0, cache_dir=tmp_path)
    assert missing == ["GONE"] and {row["ticker"] for row in rows} == {"AAA"}
    calls.clear()
    again, _ = edgar_facts.fetch_extended(["AAA"], get_json, pause_seconds=0.0, cache_dir=tmp_path)
    assert calls == [edgar_facts.TICKERS_URL] and again == rows


def test_extended_features_read_only_what_was_filed_by_then():
    from features.wide_panel import extended_info_features

    rows = pd.DataFrame([{"ticker": "AAA", **row} for row in edgar_facts.extended_rows(_flow_facts())])
    base = pd.DataFrame([{"ticker": "AAA", **row} for row in edgar_facts.fundamentals_rows({"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [{"end": "2018-12-31", "filed": "2019-02-20", "form": "10-K", "val": 1000.0}]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2018-12-31", "filed": "2019-02-20", "form": "10-K", "val": 600.0}]}},
        "LongTermDebt": {"units": {"USD": [{"end": "2018-12-31", "filed": "2019-02-20", "form": "10-K", "val": 300.0}]}},
    }}})])
    out = extended_info_features(SESSIONS, ["AAA"], extended=rows, fundamentals=base)
    assert np.isnan(out["accruals_ttm"].loc["2019-02-20", "AAA"]), "a filing shows a session after its date"
    assert out["accruals_ttm"].loc["2019-02-21", "AAA"] == pytest.approx((100.0 - 120.0) / 1000.0)
    assert out["accruals_ttm"].loc["2019-08-02", "AAA"] == pytest.approx((130.0 - 150.0) / 1100.0)
    assert out["noa"].loc["2019-02-21", "AAA"] == pytest.approx((600.0 + 300.0 - 200.0) / 1000.0)
    assert out["capex_growth"]["AAA"].isna().all(), "one year of capex has no growth"


def test_annual_first_filing_keeps_what_was_public_then():
    rows = edgar_facts.first_filings_annual(_facts(), "Assets")
    assert rows == [{"period_end": "2018-12-31", "filed": "2019-03-01", "form": "10-K", "value": 100.0}]


def test_a_quarter_inside_a_10k_is_not_a_year():
    rows = edgar_facts.first_filings_annual(_facts(), "NetIncomeLoss")
    assert [row["value"] for row in rows] == [10.0]


def test_shares_come_from_the_dei_taxonomy():
    rows = edgar_facts.fundamentals_rows(_facts())
    assert [row["value"] for row in rows if row["field"] == "shares_outstanding"] == [1000.0]


def test_an_earlier_tag_wins_a_year_and_a_later_one_fills_only_gaps():
    rows = [row for row in edgar_facts.fundamentals_rows(_facts()) if row["field"] == "revenue"]
    assert {row["period_end"]: row["value"] for row in rows} == {"2017-12-31": 40.0, "2018-12-31": 50.0}


@pytest.mark.parametrize("sic, sector", [
    (3571, "information_technology"), (7372, "information_technology"), (2834, "health_care"), (8062, "health_care"), (1311, "energy"),
    (2911, "energy"), (4911, "utilities"), (6021, "financials"), (6798, "real_estate"), (2000, "consumer_staples"), (5411, "consumer_staples"),
    (3711, "consumer_discretionary"), (5812, "consumer_discretionary"), (4813, "communication_services"), (2810, "materials"), (3721, "industrials"),
    (None, "unknown"), ("x", "unknown"), (0, "unknown"),
])
def test_sector_for_sic(sic, sector):
    assert edgar_facts.sector_for_sic(sic) == sector


def _rows(values):
    return pd.DataFrame([{"ticker": t, "field": f, "period_end": p, "filed": d, "form": "10-K", "value": v} for t, f, p, d, v in values])


def test_fundamentals_table_shows_a_filing_a_session_late_and_never_earlier():
    rows = _rows([("AAA", "assets", "2018-12-31", "2019-03-01", 100.0)])
    table = edgar_facts.fundamentals_table(rows, SESSIONS, ["AAA"], "assets")
    assert np.isnan(table.loc["2019-03-01", "AAA"]), "not on the filing date: it can arrive after the close"
    assert table.loc["2019-03-04", "AAA"] == 100.0 and table.loc["2019-12-31", "AAA"] == 100.0


def test_a_late_filing_of_an_older_year_does_not_replace_a_newer_one():
    rows = _rows([
        ("AAA", "assets", "2018-12-31", "2019-03-01", 100.0),
        ("AAA", "assets", "2017-12-31", "2019-06-03", 80.0),
    ])
    table = edgar_facts.fundamentals_table(rows, SESSIONS, ["AAA"], "assets")
    assert table.loc["2019-12-31", "AAA"] == 100.0


def test_market_cap_does_not_move_with_a_split_after_the_date():
    sessions = SESSIONS[:60]
    filed = sessions[5]
    rows = _rows([("AAA", "shares_outstanding", "2018-12-31", filed, 1000.0)])
    no_split = pd.DataFrame(columns=["ticker", "date", "ratio"], dtype=object)
    before = edgar_facts.market_cap_table(pd.DataFrame({"AAA": [10.0] * 60}, index=sessions), rows, no_split)
    # a 2-for-1 later on: Yahoo restates every earlier close, and the count as filed is restated by the same split
    split = pd.DataFrame({"ticker": ["AAA"], "date": [sessions[40]], "ratio": [2.0]})
    after = edgar_facts.market_cap_table(pd.DataFrame({"AAA": [5.0] * 60}, index=sessions), rows, split)
    assert before.loc[sessions[20], "AAA"] == pytest.approx(after.loc[sessions[20], "AAA"]) == pytest.approx(10_000.0)


def test_fetch_fundamentals_reports_names_sec_has_not_and_uses_the_cache(tmp_path):
    calls = []

    def get_json(url):
        calls.append(url)
        if url == edgar_facts.TICKERS_URL:
            return {"0": {"ticker": "AAA", "cik_str": 1}, "1": {"ticker": "BRK-B", "cik_str": 2}}
        if "submissions" in url:
            return {"sic": "3571"}
        return _facts()

    rows, sectors, missing = edgar_facts.fetch_fundamentals(["AAA", "BRK.B", "GONE"], get_json, pause_seconds=0.0, cache_dir=tmp_path)
    assert sectors == {"AAA": "information_technology", "BRK.B": "information_technology"} and missing == ["GONE"]
    assert {row["ticker"] for row in rows} == {"AAA", "BRK.B"}
    calls.clear()
    edgar_facts.fetch_fundamentals(["AAA"], get_json, pause_seconds=0.0, cache_dir=tmp_path)
    assert calls == [edgar_facts.TICKERS_URL], "a cached company isn't fetched again"
    assert edgar_facts.collect_cached_eps(["AAA", "GONE"], tmp_path) == []


def test_write_and_read_fundamentals(tmp_path):
    path = tmp_path / "f.csv.gz"
    edgar_facts.write_fundamentals([{"ticker": "AAA", "field": "assets", "period_end": "2018-12-31", "filed": "2019-03-01", "form": "10-K", "value": 1.5}], path)
    assert edgar_facts.read_fundamentals(path)["value"].tolist() == [1.5]


# --- Form 4 ----------------------------------------------------------------------------------------------------------


def _form345_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\tFILING_DATE\tISSUERTRADINGSYMBOL\nA1\t10-JAN-2020\taaa\nA2\t11-JAN-2020\tBBB\nA3\t12-JAN-2020\tZZZ\n")
        archive.writestr("REPORTINGOWNER.tsv", "ACCESSION_NUMBER\tRPTOWNERCIK\nA1\t100\nA1\t101\nA2\t200\nA3\t300\n")
        archive.writestr("NONDERIV_TRANS.tsv", (
            "ACCESSION_NUMBER\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\tTRANS_PRICEPERSHARE\n"
            "A1\t08-JAN-2020\tP\t10\t5\nA1\t08-JAN-2020\tA\t999\t5\nA2\t09-JAN-2020\tS\t20\t2\nA3\t09-JAN-2020\tP\t1\t1\nA2\t09-JAN-2020\tP\t\t\n"
        ))
    return buffer.getvalue()


def test_parse_quarter_keeps_priced_market_trades_by_filing_date():
    frame = sec_form345.parse_quarter(_form345_zip(), {"AAA", "BBB"})
    assert frame.to_dict("records") == [
        {"ticker": "AAA", "owner": "100", "filed": "2020-01-10", "traded": "2020-01-08", "code": "P", "value": 50.0},
        {"ticker": "BBB", "owner": "200", "filed": "2020-01-11", "traded": "2020-01-09", "code": "S", "value": 40.0},
    ]


def test_quarters_stop_at_the_end():
    assert sec_form345.quarters(2025, 2026, 1)[-1] == (2026, 1) and len(sec_form345.quarters(2025, 2026, 1)) == 5


def _trade(owner, traded, code="P", value=100.0, filed=None):
    return {"ticker": "AAA", "owner": owner, "filed": filed or traded, "traded": traded, "code": code, "value": value}


def test_routine_needs_the_same_month_in_each_of_three_prior_years():
    trades = pd.DataFrame([
        _trade("R", "2016-03-10"), _trade("R", "2017-03-10"), _trade("R", "2018-03-10"), _trade("R", "2019-03-10"),
        _trade("O", "2017-03-10"), _trade("O", "2019-03-10"),
    ])
    kept = sec_form345.opportunistic(trades)
    assert ("R", "2019-03-10") not in set(zip(kept["owner"], kept["traded"]))
    assert ("R", "2018-03-10") in set(zip(kept["owner"], kept["traded"])), "routine is only known from the fourth year"
    assert ("O", "2019-03-10") in set(zip(kept["owner"], kept["traded"]))


def test_a_later_trade_cannot_change_an_earlier_classification():
    early = pd.DataFrame([_trade("A", "2019-03-10")])
    later = pd.DataFrame([_trade("A", "2019-03-10"), _trade("A", "2020-03-10"), _trade("A", "2021-03-10"), _trade("A", "2022-03-10")])
    first = sec_form345.opportunistic(early)
    second = sec_form345.opportunistic(later)
    assert ("2019-03-10" in set(first["traded"])) and ("2019-03-10" in set(second["traded"]))


def test_insider_net_table_uses_the_filing_date_a_session_late_and_rolls_off():
    trades = pd.DataFrame([_trade("A", "2019-02-20", "P", 100.0, filed="2019-03-01"), _trade("B", "2019-02-20", "S", 30.0, filed="2019-03-01")])
    table = sec_form345.insider_net_table(trades, SESSIONS, ["AAA", "NOPE"], window_days=30)
    assert table.loc["2019-03-01", "AAA"] == 0.0
    assert table.loc["2019-03-04", "AAA"] == pytest.approx(70.0)
    assert table.loc["2019-05-15", "AAA"] == pytest.approx(0.0, abs=1e-9)
    assert (table["NOPE"] == 0.0).all()


def test_fetch_trades_skips_a_missing_quarter():
    frame = sec_form345.fetch_trades([(2020, 1), (2020, 2)], lambda url: _form345_zip() if "2020q1" in url else None, {"AAA"})
    assert len(frame) == 1


# --- FINRA -----------------------------------------------------------------------------------------------------------


def test_parse_day_keeps_wanted_names_and_skips_the_trailer():
    text = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20240102|AAA|40|0|100|B,Q,N\n20240102|BRK/B|10|0|40|N\n20240102|ZZZ|1|0|0|N\n20240102|OTH|1|0|2|N\n12345\n"
    ratios = finra_short_volume.parse_day(text, {"AAA": "AAA", "BRK/B": "BRK.B", "ZZZ": "ZZZ"})
    assert ratios == {"AAA": pytest.approx(0.4), "BRK.B": pytest.approx(0.25)}


def test_fetch_ratios_leaves_out_a_day_with_no_file():
    text = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20240102|AAA|40|0|100|N\n"
    frame = finra_short_volume.fetch_ratios(["2024-01-02", "2024-01-03"], lambda url: text if "20240102" in url else None, ["AAA"])
    assert list(frame.index) == ["2024-01-02"] and frame.loc["2024-01-02", "AAA"] == pytest.approx(0.4)


def test_short_ratio_is_a_session_late_and_a_gap_stays_empty():
    sessions = SESSIONS[:30]
    ratios = pd.DataFrame({"AAA": [0.5] * 20}, index=sessions[:20])
    table = finra_short_volume.short_ratio_table(ratios, sessions, ["AAA", "BBB"], window=5)
    assert np.isnan(table.iloc[4, 0]) and table.iloc[5, 0] == pytest.approx(0.5)
    # changing today's file must not change today's value
    changed = ratios.copy()
    changed.iloc[10, 0] = 0.9
    moved = finra_short_volume.short_ratio_table(changed, sessions, ["AAA", "BBB"], window=5)
    assert moved.iloc[10, 0] == table.iloc[10, 0] and moved.iloc[11, 0] != table.iloc[11, 0]
    assert table["BBB"].isna().all()


# --- factors ---------------------------------------------------------------------------------------------------------


def _french_zip(text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.csv", text)
    return buffer.getvalue()


def test_french_file_parses_only_dated_rows_and_marks_missing():
    text = "This file was created\n\n,Mkt-RF,SMB,RF\n20200102, 1.00, -0.50, 0.01\n20200103,-99.99, 0.25, 0.01\n\n Copyright 2026\n"
    frame = factor_library.parse_french_zip(_french_zip(text))
    assert list(frame.columns) == ["Mkt-RF", "SMB", "RF"]
    assert frame.loc["2020-01-02", "Mkt-RF"] == pytest.approx(0.01)
    assert np.isnan(frame.loc["2020-01-03", "Mkt-RF"]) and frame.loc["2020-01-03", "SMB"] == pytest.approx(0.0025)
    assert len(frame) == 2


def test_fetch_factors_survives_a_bad_aqr_workbook():
    five = _french_zip(",Mkt-RF,RF\n20200102,1.0,0.01\n")
    momentum = _french_zip(",Mom   \n20200102,0.5\n")

    def get(url):
        if url == factor_library.FRENCH_FIVE:
            return five
        if url == factor_library.FRENCH_MOMENTUM:
            return momentum
        raise OSError("down")

    frame = factor_library.fetch_factors(get)
    assert list(frame.columns) == ["Mkt-RF", "RF", "Mom"]
    assert frame.loc["2020-01-02", "Mom"] == pytest.approx(0.005)


# --- the builder's contact check --------------------------------------------------------------------------------------


def test_contact_leaks_look_inside_gzip_and_find_nothing_without_a_contact(tmp_path):
    import build_wide_info

    (tmp_path / "plain.txt").write_text("nothing here")
    with gzip.open(tmp_path / "hidden.csv.gz", "wt") as handle:
        handle.write("someone@example.com")
    assert build_wide_info.contact_leaks(tmp_path, "") == []
    assert [Path(hit).name for hit in build_wide_info.contact_leaks(tmp_path, "someone@example.com")] == ["hidden.csv.gz"]


def test_no_contact_means_no_sec_request(monkeypatch):
    import build_wide_info

    monkeypatch.delenv("AQ_SEC_CONTACT", raising=False)
    with pytest.raises(SystemExit):
        build_wide_info.sec_headers()


def test_the_edgar_user_agent_has_no_address_of_its_own():
    assert "@" not in edgar_facts.USER_AGENT
    assert "@" not in json.dumps(factor_library.AQR_QMJ)
