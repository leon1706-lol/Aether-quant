"""data_pipeline/cftc_cot.py and data_pipeline/edgar_facts.py: parsing and, above all, point-in-time timing. No network."""

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from data_pipeline.cftc_cot import (
    change_by_session,
    fetch_years,
    fx_pair_scores,
    macro_scores,
    parse_annual_text,
    parse_zip_bytes,
    read_positioning,
    write_positioning,
)
from data_pipeline.edgar_facts import (
    CONTACT_ENV,
    USER_AGENT,
    fetch_eps,
    quarterly_first_filings,
    read_eps,
    read_splits,
    split_adjusted_eps,
    standardised_surprises,
    surprise_table,
    user_agent,
    write_eps,
    write_splits,
)

HEADER = "Market and Exchange Names,As of Date in Form YYYY-MM-DD,Open Interest (All),Noncommercial Positions-Long (All),Noncommercial Positions-Short (All)\n"
ROW = '"EURO FX - CHICAGO MERCANTILE EXCHANGE",2024-01-02,1000,600,200\n'


def _zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("annual.txt", text)
    return buffer.getvalue()


def test_parse_keeps_known_markets_and_publishes_three_days_later():
    rows = parse_annual_text(HEADER + ROW + '"WHEAT - CHICAGO BOARD OF TRADE",2024-01-02,1000,1,1\n')
    assert rows == [{"report_date": "2024-01-02", "publication_date": "2024-01-05", "market": "EUR", "net_pct_oi": pytest.approx(0.4)}]


def test_parse_drops_zero_open_interest_and_bad_rows():
    assert parse_annual_text(HEADER + '"EURO FX - CHICAGO MERCANTILE EXCHANGE",2024-01-02,0,1,1\n') == []
    assert parse_annual_text(HEADER + '"EURO FX - CHICAGO MERCANTILE EXCHANGE",not-a-date,10,1,1\n') == []


def test_zip_and_fetch_with_an_injected_fetcher():
    assert parse_zip_bytes(_zip(HEADER + ROW))[0]["market"] == "EUR"
    assert fetch_years([2024], fetch_fn=lambda url: _zip(HEADER + ROW))[0]["market"] == "EUR"


def test_write_and_read_round_trip(tmp_path):
    path = tmp_path / "cot.csv"
    write_positioning(parse_annual_text(HEADER + ROW), path)
    assert read_positioning(path)["net_pct_oi"].iloc[0] == pytest.approx(0.4)


def _positioning(values, market="EUR", start="2024-01-02"):
    reports = pd.date_range(start, periods=len(values), freq="7D")
    return pd.DataFrame({
        "report_date": reports.strftime("%Y-%m-%d"),
        "publication_date": (reports + pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
        "market": market,
        "net_pct_oi": values,
    })


def test_a_report_is_first_usable_on_the_session_after_its_publication():
    positioning = _positioning([0.1, 0.5])
    sessions = ["2024-01-05", "2024-01-08", "2024-01-12", "2024-01-15"]
    change = change_by_session(positioning, sessions, weeks=1)

    # the change exists from the second report, published Friday 2024-01-12: unknown that day, known on the 15th
    assert np.isnan(change.loc["2024-01-12", "EUR"])
    assert change.loc["2024-01-15", "EUR"] == pytest.approx(0.4)


def test_fx_pair_score_is_base_minus_quote_with_the_dollar_at_zero():
    change = pd.DataFrame({"EUR": [0.3], "GBP": [0.1]}, index=["2024-01-08"])
    scores = fx_pair_scores(change, ["EURUSD", "USDEUR", "EURGBP"])
    assert scores.loc["2024-01-08", "EURUSD"] == pytest.approx(0.3)
    assert scores.loc["2024-01-08", "USDEUR"] == pytest.approx(-0.3)
    assert scores.loc["2024-01-08", "EURGBP"] == pytest.approx(0.2)


def test_macro_scores_are_directions():
    change = pd.DataFrame({"SPX": [0.3], "UST10": [-0.1]}, index=["2024-01-08"])
    scores = macro_scores(change)
    assert scores.loc["2024-01-08", "SPY"] == 1.0
    assert scores.loc["2024-01-08", "TLT"] == -1.0


def _fact(start, end, filed, value):
    return {"start": start, "end": end, "filed": filed, "val": value}


def test_only_standalone_quarters_and_their_first_filing_are_kept():
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        _fact("2023-01-01", "2023-03-31", "2023-05-01", 1.0),
        _fact("2023-01-01", "2023-03-31", "2024-05-01", 9.0),  # restated a year later: must not replace what was public
        _fact("2023-01-01", "2023-06-30", "2023-08-01", 2.0),  # year to date
        _fact("2023-01-01", "2023-12-31", "2024-02-01", 4.0),  # annual
    ]}}}}}
    assert quarterly_first_filings(facts) == [
        {"period_start": "2023-01-01", "period_end": "2023-03-31", "filed": "2023-05-01", "eps": 1.0}
    ]


def test_missing_tags_and_empty_facts_give_nothing():
    assert quarterly_first_filings({}) == []
    assert quarterly_first_filings({"facts": {"us-gaap": {"Assets": {}}}}) == []


def test_fetch_reports_unknown_and_failing_tickers_without_guessing():
    def get_json(url):
        if "company_tickers" in url:
            return {"0": {"ticker": "AAA", "cik_str": 1}, "1": {"ticker": "BBB", "cik_str": 2}}
        if "CIK0000000002" in url:
            raise RuntimeError("boom")
        return {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [_fact("2023-01-01", "2023-03-31", "2023-05-01", 1.0)]}}}}}

    rows, missing = fetch_eps(["AAA", "BBB", "CCC"], get_json=get_json, pause_seconds=0.0)
    assert [row["ticker"] for row in rows] == ["AAA"]
    assert missing == ["BBB", "CCC"]


def test_user_agent_names_no_person_unless_the_run_sets_a_contact(monkeypatch):
    assert "@" not in USER_AGENT
    monkeypatch.delenv(CONTACT_ENV, raising=False)
    assert user_agent() == USER_AGENT
    monkeypatch.setenv(CONTACT_ENV, "someone@example.org")
    assert user_agent().endswith("someone@example.org")


def test_a_renamed_ticker_resolves_through_its_alias():
    def get_json(url):
        if "company_tickers" in url:
            return {"0": {"ticker": "META", "cik_str": 7}}
        assert "CIK0000000007" in url
        return {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [_fact("2023-01-01", "2023-03-31", "2023-05-01", 1.0)]}}}}}

    rows, missing = fetch_eps(["FB"], get_json=get_json, pause_seconds=0.0)
    assert [row["ticker"] for row in rows] == ["FB"]
    assert missing == []


def _quarters(ends, eps, ticker="AAA", lag_days=30):
    ends = pd.to_datetime(ends)
    return pd.DataFrame({
        "ticker": ticker,
        "period_start": (ends - pd.Timedelta(days=90)).strftime("%Y-%m-%d"),
        "period_end": ends.strftime("%Y-%m-%d"),
        "filed": (ends + pd.Timedelta(days=lag_days)).strftime("%Y-%m-%d"),
        "eps": eps,
    })


def test_a_change_is_against_the_same_quarter_a_year_earlier_even_with_q4_missing():
    # three quarters a year, the common case: "four rows back" would be 15-18 months earlier
    ends = [f"{year}-{month}" for year in range(2018, 2024) for month in ("03-31", "06-30", "09-30")]
    eps = (1.0 + 0.3 * np.sin(np.arange(len(ends)) * 1.7)).tolist()
    changes = np.array(eps[3:]) - np.array(eps[:-3])  # three rows back is the same quarter a year earlier

    surprises = standardised_surprises(_quarters(ends, eps))

    expected = changes[-1] / np.std(changes[-9:-1], ddof=1)
    assert surprises[-1] == pytest.approx(expected)
    assert np.isnan(surprises[:3]).all()


def test_a_zero_spread_gives_no_signal_rather_than_an_infinity():
    ends = [f"{year}-{month}" for year in range(2018, 2024) for month in ("03-31", "06-30", "09-30")]
    assert np.isnan(standardised_surprises(_quarters(ends, [float(index) for index in range(len(ends))]))).all()


def test_a_quarter_with_no_year_earlier_match_has_no_signal():
    ends = ["2020-03-31", "2020-06-30", "2021-09-30", "2021-12-31"]
    assert np.isnan(standardised_surprises(_quarters(ends, [1.0, 2.0, 3.0, 4.0]))).all()


def test_a_figure_filed_later_is_not_used_for_an_earlier_filing():
    frame = _eps_history()
    base = standardised_surprises(frame)
    late = frame.copy()
    late.loc[0, "filed"] = "2030-01-01"  # the year-earlier quarter for row 4 is not public yet
    changed = standardised_surprises(late)

    assert np.isfinite(base).any()
    assert np.isnan(changed[4])
    # the spread of a later row no longer counts that row's change either, because it was not filed by then
    assert np.isfinite(changed[-1])


def test_a_split_does_not_read_as_a_miss():
    ends = pd.date_range("2018-03-31", periods=24, freq="QE")
    earnings = 2.0 + 0.1 * np.sin(np.arange(24))
    filed = ends + pd.Timedelta(days=30)
    split_day = "2022-06-01"
    stated = np.where(filed.strftime("%Y-%m-%d") < split_day, earnings * 4.0, earnings)
    eps = _quarters(ends, stated)
    splits = pd.DataFrame({"ticker": ["AAA"], "date": [split_day], "ratio": [4.0]})

    raw = standardised_surprises(eps)
    adjusted = standardised_surprises(split_adjusted_eps(eps, splits))

    assert np.nanmin(raw) < -3.0
    assert np.isfinite(adjusted).sum() >= 10
    assert np.nanmax(np.abs(adjusted)) < 3.0


def test_a_later_split_leaves_the_surprises_unchanged():
    eps = _eps_history()
    later = pd.DataFrame({"ticker": ["AAA"], "date": ["2030-01-01"], "ratio": [7.0]})
    assert np.allclose(standardised_surprises(split_adjusted_eps(eps, later)), standardised_surprises(eps), equal_nan=True)


def test_a_ticker_with_no_split_keeps_its_figures_and_the_split_file_round_trips(tmp_path):
    eps = _eps_history()
    other = pd.DataFrame({"ticker": ["BBB"], "date": ["2021-01-01"], "ratio": [2.0]})
    assert split_adjusted_eps(eps, other)["eps"].tolist() == eps["eps"].tolist()
    path = tmp_path / "splits.csv"
    write_splits([{"ticker": "BBB", "date": "2021-01-01", "ratio": 2.0}], path)
    assert read_splits(path)["ratio"].iloc[0] == 2.0


def test_write_and_read_eps_round_trip(tmp_path):
    path = tmp_path / "eps.csv"
    write_eps([{"ticker": "AAA", "period_start": "2023-01-01", "period_end": "2023-03-31", "filed": "2023-05-01", "eps": 1.5}], path)
    assert read_eps(path)["eps"].iloc[0] == 1.5


def _eps_history():
    quarters = pd.date_range("2020-03-31", periods=14, freq="QE")
    return pd.DataFrame({
        "ticker": "AAA",
        "period_start": (quarters - pd.Timedelta(days=90)).strftime("%Y-%m-%d"),
        "period_end": quarters.strftime("%Y-%m-%d"),
        "filed": (quarters + pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
        "eps": [1.0, 1.1, 0.9, 1.2, 1.1, 1.3, 1.0, 1.4, 1.2, 1.5, 1.1, 1.6, 1.4, 3.0],
    })


def test_a_surprise_is_unknown_on_the_filing_day_and_known_the_next_session():
    eps = _eps_history()
    filed = eps["filed"].iloc[-1]
    sessions = pd.bdate_range("2023-01-01", "2024-03-29").strftime("%Y-%m-%d").tolist()
    table = surprise_table(eps, sessions, ["AAA"], hold_sessions=5)
    after = [day for day in sessions if day > filed]

    if filed in sessions:
        before_value = table.loc[filed, "AAA"]
        assert before_value != table.loc[after[0], "AAA"]
    assert np.isfinite(table.loc[after[0], "AAA"])
    assert table.loc[after[0], "AAA"] > 0.0
    assert np.isnan(table.loc[after[5], "AAA"])


def test_surprise_table_ignores_tickers_outside_the_columns():
    table = surprise_table(_eps_history(), ["2024-01-02"], ["ZZZ"], hold_sessions=5)
    assert table["ZZZ"].isna().all()
