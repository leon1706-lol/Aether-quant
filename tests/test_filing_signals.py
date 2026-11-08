"""portfolio/filing_signals.py: hand-computed cases, and the rule that nothing at or after a session informs it (V6.6.4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio import filing_signals as fs

SESSIONS = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2018-01-01", "2021-12-31")]
INDEX = pd.Index(SESSIONS)
NAMES = pd.Index(["AAA", "BBB", "SPY"])


def _row(table: pd.DataFrame, day: str) -> pd.Series:
    return table.loc[day]


def test_a_filing_is_visible_from_the_session_after_its_date_and_not_before():
    rows = pd.DataFrame({"ticker": ["AAA"], "filed": ["2020-01-06"], "similarity": [0.9]})
    table = fs.similarity_table(rows, INDEX, NAMES, max_age=130)
    assert np.isnan(_row(table, "2020-01-06")["AAA"]), "the session of the filing itself must not see it"
    assert _row(table, "2020-01-07")["AAA"] == 0.9 and _row(table, "2020-01-08")["AAA"] == 0.9
    assert table["BBB"].isna().all()


def test_a_filing_on_a_weekend_is_seen_on_monday():
    rows = pd.DataFrame({"ticker": ["AAA"], "filed": ["2020-01-04"], "similarity": [0.5]})  # a Saturday
    table = fs.similarity_table(rows, INDEX, NAMES)
    assert np.isnan(_row(table, "2020-01-03")["AAA"]) and _row(table, "2020-01-06")["AAA"] == 0.5


def test_a_newer_filing_replaces_the_older_and_an_old_one_expires():
    rows = pd.DataFrame({"ticker": ["AAA", "AAA"], "filed": ["2020-01-06", "2020-04-06"], "similarity": [0.9, 0.4]})
    table = fs.similarity_table(rows, INDEX, NAMES, max_age=130)
    assert _row(table, "2020-03-02")["AAA"] == 0.9 and _row(table, "2020-04-07")["AAA"] == 0.4
    assert np.isnan(_row(table, "2020-12-01")["AAA"]), "after max_age sessions with nothing newer there is no signal"


def test_a_filing_changed_after_a_session_changes_nothing_before_it():
    rows = pd.DataFrame({"ticker": ["AAA", "AAA"], "filed": ["2019-06-03", "2020-06-01"], "similarity": [0.7, 0.2]})
    later = rows.copy()
    later.loc[1, ["filed", "similarity"]] = ["2020-06-02", 0.99]
    pd.testing.assert_frame_equal(fs.similarity_table(rows, INDEX, NAMES).loc[:"2020-06-01"], fs.similarity_table(later, INDEX, NAMES).loc[:"2020-06-01"])


def test_empty_and_unknown_inputs_give_an_all_nan_table():
    empty = pd.DataFrame({"ticker": [], "filed": [], "similarity": []})
    assert fs.similarity_table(empty, INDEX, NAMES).isna().all().all()
    stranger = pd.DataFrame({"ticker": ["ZZZ"], "filed": ["2020-01-06"], "similarity": [0.9]})
    assert fs.similarity_table(stranger, INDEX, NAMES).isna().all().all()
    assert fs.announcement_proximity(None, INDEX, NAMES).isna().all().all()


def test_announcement_proximity_flags_the_sessions_before_the_expected_date():
    rows = pd.DataFrame({"ticker": ["AAA"], "accepted": ["2019-03-11T20:05:00"]})  # expected 52 weeks later: Monday 2020-03-09
    table = fs.announcement_proximity(rows, INDEX, NAMES, window_days=14)
    assert np.isnan(_row(table, "2019-03-11")["AAA"]), "unmeasurable until the session after the first announcement"
    assert _row(table, "2019-03-12")["AAA"] == 0.0 and _row(table, "2019-12-02")["AAA"] == 0.0
    flagged = table.index[table["AAA"] == 1.0]
    assert list(flagged) == SESSIONS[SESSIONS.index("2020-03-09") - 10:SESSIONS.index("2020-03-09")], "14 calendar days before a Monday is ten sessions"
    assert _row(table, "2020-03-09")["AAA"] == 0.0 and table["BBB"].isna().all()


def test_an_expected_date_beyond_the_last_session_flags_only_the_sessions_inside_its_window():
    index = pd.Index(SESSIONS[:SESSIONS.index("2019-12-31") + 1])
    rows = pd.DataFrame({"ticker": ["AAA"], "accepted": ["2019-01-10T20:00:00"]})  # expected 2020-01-09, beyond the index
    table = fs.announcement_proximity(rows, index, NAMES, window_days=14)
    flagged = list(table.index[table["AAA"] == 1.0])
    assert flagged == ["2019-12-26", "2019-12-27", "2019-12-30", "2019-12-31"], "12-26 is exactly 14 days before 2020-01-09; the window is cut at the end of the index, not stretched"
    assert table.loc["2019-12-25", "AAA"] == 0.0


def test_announcement_proximity_reads_nothing_from_the_future():
    first = pd.DataFrame({"ticker": ["AAA"], "accepted": ["2019-03-11T20:05:00"]})
    both = pd.DataFrame({"ticker": ["AAA", "AAA"], "accepted": ["2019-03-11T20:05:00", "2020-06-08T20:05:00"]})
    a, b = fs.announcement_proximity(first, INDEX, NAMES), fs.announcement_proximity(both, INDEX, NAMES)
    pd.testing.assert_frame_equal(a.loc[:"2020-06-08"], b.loc[:"2020-06-08"])


def test_announcement_return_is_the_abnormal_move_held_after_it_completes():
    index = pd.Index([day.strftime("%Y-%m-%d") for day in pd.bdate_range("2020-01-01", periods=120)])
    aaa, spy = np.full(120, 100.0), np.full(120, 400.0)
    aaa[22:] = 110.0  # the announcement day is index 20 (2020-01-29): close of day 20 is known in row 21
    spy[22:] = 404.0
    known = pd.DataFrame({"AAA": aaa, "SPY": spy}, index=index)
    rows = pd.DataFrame({"ticker": ["AAA"], "accepted": [index[20]]})
    table = fs.announcement_return(rows, known, days=3, decay=10)
    assert table["AAA"].iloc[:23].isna().all(), "blank until the reaction days have passed"
    assert table["AAA"].iloc[23] == pytest.approx(110.0 / 100.0 - 404.0 / 400.0)
    assert table["AAA"].iloc[32] == pytest.approx(table["AAA"].iloc[23]) and np.isnan(table["AAA"].iloc[33])
    assert table["SPY"].isna().all()


def test_announcement_return_changes_nothing_before_it_is_complete():
    index = pd.Index([day.strftime("%Y-%m-%d") for day in pd.bdate_range("2020-01-01", periods=120)])
    base = pd.DataFrame({"AAA": np.linspace(100, 130, 120), "SPY": np.linspace(400, 420, 120)}, index=index)
    changed = base.copy()
    changed.iloc[60:] *= 2.0
    rows = pd.DataFrame({"ticker": ["AAA"], "accepted": [index[58]]})
    pd.testing.assert_frame_equal(fs.announcement_return(rows, base).iloc[:61], fs.announcement_return(rows, changed).iloc[:61])


def test_same_month_seasonality_reads_only_earlier_years():
    months = pd.period_range("2012-01", "2021-12", freq="M")
    rng = np.random.default_rng(0)
    steps = np.where(months.month == 1, 0.10, rng.normal(0.0, 0.005, len(months)))
    monthly = 100.0 * np.cumprod(1.0 + steps)
    days = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2012-01-02", "2021-12-31")]
    known = pd.DataFrame({"AAA": pd.Series(monthly, index=months).reindex(pd.PeriodIndex(pd.to_datetime(days), freq="M")).to_numpy()}, index=days)
    table = fs.same_month_seasonality(known, years=7, min_years=5)
    assert table["AAA"].loc["2021-01-15"] == pytest.approx(0.10, abs=1e-9)
    assert table["AAA"].loc["2021-07-15"] != table["AAA"].loc["2021-01-15"]
    assert table["AAA"].loc[:"2016-12-31"].isna().all(), "fewer than min_years of earlier Januaries: no signal"
    changed = known.copy()
    changed.loc["2021-06-01":] *= 3.0
    pd.testing.assert_frame_equal(table.loc[:"2021-05-31"], fs.same_month_seasonality(changed, years=7, min_years=5).loc[:"2021-05-31"])


def test_opportunistic_buying_drops_the_routine_buyer_and_ignores_sales():
    trades = pd.DataFrame({
        "ticker": ["AAA"] * 7 + ["BBB"],
        "owner": ["R", "R", "R", "R", "N", "N", "N", "N"],
        "code": ["P", "P", "P", "P", "P", "S", "P", "P"],
        "filed": ["2017-01-10", "2018-01-10", "2019-01-10", "2020-01-10", "2020-01-12", "2020-01-13", "2020-02-20", "2020-01-10"],
        "value": [1e5, 1e5, 1e5, 1e5, 2e5, 9e9, 3e5, 4e5],
    })
    table = fs.opportunistic_buying(trades, INDEX, NAMES, routine_years=3, window=63)
    on = "2020-02-21"
    assert table.loc[on, "AAA"] == pytest.approx(np.log1p(2e5 + 3e5)), "the routine January buyer and the sale are out; the other owner's purchases count"
    assert table.loc[on, "BBB"] == pytest.approx(np.log1p(4e5)) and table.loc["2020-01-10", "AAA"] == 0.0
    assert table.loc["2020-07-15", "AAA"] == 0.0, "a purchase leaves the window after 63 sessions"


def test_opportunistic_buying_changes_nothing_before_a_later_filing():
    base = pd.DataFrame({"ticker": ["AAA"], "owner": ["N"], "code": ["P"], "filed": ["2020-02-20"], "value": [1e5]})
    more = pd.concat([base, pd.DataFrame({"ticker": ["AAA"], "owner": ["N"], "code": ["P"], "filed": ["2020-03-20"], "value": [9e9]})], ignore_index=True)
    pd.testing.assert_frame_equal(fs.opportunistic_buying(base, INDEX, NAMES).loc[:"2020-03-20"], fs.opportunistic_buying(more, INDEX, NAMES).loc[:"2020-03-20"])


def test_cash_profitability_is_cash_flow_over_assets_as_last_filed():
    funda = pd.DataFrame({
        "ticker": ["AAA", "AAA", "AAA", "BBB"], "field": ["assets", "ttm_operating_cash_flow", "ttm_operating_cash_flow", "assets"],
        "filed": ["2020-02-03", "2020-02-03", "2020-05-04", "2020-02-03"], "value": [1000.0, 100.0, 150.0, 500.0],
    })
    table = fs.cash_profitability(funda, INDEX, NAMES)
    assert table.loc["2020-02-04", "AAA"] == pytest.approx(0.10) and table.loc["2020-05-05", "AAA"] == pytest.approx(0.15)
    assert np.isnan(table.loc["2020-02-03", "AAA"]) and table["BBB"].isna().all(), "no cash flow, no ratio"


def test_term_credit_timing_is_on_only_when_both_conditions_hold():
    index = pd.Index(SESSIONS[:400])
    known = pd.DataFrame({"SPY": np.linspace(100, 120, 400), "AAA": 1.0}, index=index)
    fred = pd.DataFrame({"treasury_10yr": 3.0, "treasury_3mo": 1.0, "credit_spread_baa10y": 2.0}, index=index)
    fred.iloc[300:, 2] = 3.5  # credit widens above its median
    fred.iloc[350:, 1] = 4.0  # curve inverts
    table = fs.term_credit_timing(fred, known)
    assert table["SPY"].iloc[250] == 1.0 and table["SPY"].iloc[310] == 0.0 and table["SPY"].iloc[360] == 0.0 and table["AAA"].isna().all()
    assert fs.term_credit_timing(fred.drop(columns="treasury_3mo"), known).isna().all().all()
    assert table["SPY"].iloc[:50].isna().all()


def test_fred_series_are_carried_over_weekends_and_read_a_session_late():
    index = pd.Index(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    series = {"treasury_10yr": pd.Series({"2020-01-02": 1.8, "2020-01-03": 1.9, "2020-01-07": 2.1})}
    table = fs.fred_as_known(series, index, keys=("treasury_10yr", "treasury_3mo"))
    assert np.isnan(table.loc["2020-01-02", "treasury_10yr"]), "a mark is not known on its own day"
    assert table.loc["2020-01-03", "treasury_10yr"] == 1.8 and table.loc["2020-01-06", "treasury_10yr"] == 1.9
    assert table.loc["2020-01-07", "treasury_10yr"] == 1.9, "the 7th's own mark is read on the 8th"
    assert table["treasury_3mo"].isna().all()


def test_cross_asset_trend_is_the_twelve_minus_one_month_sign():
    index = pd.Index(SESSIONS[:400])
    known = pd.DataFrame({"UP": 100.0 * 1.001 ** np.arange(400), "DOWN": 100.0 * 0.999 ** np.arange(400), "SPY": 1.0}, index=index)
    table = fs.cross_asset_trend(known, ["UP", "DOWN", "MISSING"])
    assert table["UP"].iloc[-1] == 1.0 and table["DOWN"].iloc[-1] == 0.0 and table["UP"].iloc[:252].isna().all() and table["SPY"].isna().all()
    changed = known.copy()
    changed.iloc[300:] *= 5.0
    pd.testing.assert_frame_equal(table.iloc[:300], fs.cross_asset_trend(changed, ["UP", "DOWN", "MISSING"]).iloc[:300])
