"""features/wide_panel.py and portfolio/wide_signals.py. The look-ahead tests are the point: a signal cut at D equals row D uncut."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from features.wide_panel import PRICE_FEATURES, WideBars, growth_rows, info_features, long_frame, price_features, residual_daily, wide_label
from portfolio.wide_signals import crypto_tables, live_names_per_rebalance, rank_mean, wide_tables

DATES = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2015-01-01", periods=420)]
TICKERS = ["SPY", "AAA", "BBB", "CCC", "DDD"]
CUT = DATES[350]


def _bars(seed: int = 4) -> WideBars:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0004, 0.012, (len(DATES), len(TICKERS)))
    close = pd.DataFrame(100.0 * np.exp(np.cumsum(returns, axis=0)), index=DATES, columns=TICKERS)
    open_ = close.shift(1) * (1.0 + rng.normal(0.0, 0.002, close.shape))
    open_.iloc[0] = close.iloc[0]
    high = close * 1.01
    low = close * 0.99
    volume = pd.DataFrame(rng.uniform(1e6, 2e6, close.shape), index=DATES, columns=TICKERS)
    return WideBars(close, open_, high, low, volume, close * 1.1)


def _cut(bars: WideBars, date: str) -> WideBars:
    return WideBars(*[getattr(bars, name).loc[:date] for name in ("close", "open", "high", "low", "volume", "raw_close")])


def _future_changed(bars: WideBars, date: str) -> WideBars:
    out = WideBars(*[getattr(bars, name).copy() for name in ("close", "open", "high", "low", "volume", "raw_close")])
    after = out.close.index > date
    for frame in (out.close, out.open, out.high, out.low, out.raw_close):
        frame.loc[after] = frame.loc[after] * 3.0
    out.volume.loc[after] = out.volume.loc[after] * 7.0
    return out


@pytest.mark.parametrize("name", PRICE_FEATURES)
def test_no_price_feature_reads_the_future(name):
    bars = _bars()
    whole = price_features(bars)[name].loc[CUT]
    truncated = price_features(_cut(bars, CUT))[name].loc[CUT]
    changed = price_features(_future_changed(bars, CUT))[name].loc[CUT]
    pd.testing.assert_series_equal(whole, truncated, check_names=False)
    pd.testing.assert_series_equal(whole, changed, check_names=False)
    assert whole.notna().any(), "a feature that never has a value would pass any look-ahead test"


def test_residual_uses_a_beta_known_a_row_earlier():
    bars = _bars()
    residual = residual_daily(bars.close)
    changed = bars.close.copy()
    changed.loc[CUT:, "AAA"] = changed.loc[CUT:, "AAA"] * 1.5
    moved = residual_daily(changed)
    assert moved.loc[:DATES[349], "AAA"].equals(residual.loc[:DATES[349], "AAA"])


def _fundamentals():
    rows = []
    for ticker in ("AAA", "BBB", "CCC", "DDD"):
        for year in (2013, 2014, 2015):
            filed = f"{year + 1}-03-02"
            for field, value in (
                ("assets", 100.0 + year), ("equity", 50.0), ("gross_profit", 30.0), ("revenue", 60.0), ("cost_of_revenue", 30.0), ("net_income", 10.0),
                ("operating_cash_flow", 12.0), ("long_term_debt", 20.0), ("shares_outstanding", 1000.0 + year),
            ):
                rows.append({"ticker": ticker, "field": field, "period_end": f"{year}-12-31", "filed": filed, "form": "10-K", "value": value})
    return pd.DataFrame(rows)


def _info(raw: pd.DataFrame, fundamentals: pd.DataFrame, splits: pd.DataFrame, *, insiders=None, shorts=None, eps=None) -> dict:
    return info_features(list(raw.index), list(raw.columns), fundamentals=fundamentals, splits=splits, raw_close=raw, eps=eps, insider_trades=insiders, short_ratios=shorts)


NO_SPLITS = pd.DataFrame(columns=["ticker", "date", "ratio"], dtype=object)


@pytest.mark.parametrize("name", ["gp_assets", "roe", "cfo_assets", "accruals", "asset_growth", "net_issuance", "leverage", "book_to_market", "earnings_yield", "days_since_filing"])
def test_no_fundamental_feature_reads_a_later_filing(name):
    bars = _bars()
    fundamentals = _fundamentals()
    cut = "2016-02-15"  # before the fiscal 2015 filing of 2016-03-02
    early = fundamentals[fundamentals["filed"] <= cut]
    whole = _info(bars.raw_close, fundamentals, NO_SPLITS)[name].loc[cut]
    without_later = _info(bars.raw_close.loc[:cut], early, NO_SPLITS)[name].loc[cut]
    pd.testing.assert_series_equal(whole, without_later, check_names=False)
    assert whole.notna().any()


@pytest.mark.parametrize("name", ["book_to_market", "earnings_yield", "net_issuance"])
def test_a_later_split_does_not_change_what_was_known(name):
    """Yahoo restates every earlier close by a later split, and a count as filed is restated by the same split. A valuation built on
    an unrestated pair would move on news from the future."""
    bars = _bars()
    fundamentals = _fundamentals()
    day = "2016-06-01"
    split_date = "2016-07-01"
    raw_after = bars.raw_close.copy()
    raw_after["AAA"] = raw_after["AAA"] / 2.0
    splits = pd.DataFrame({"ticker": ["AAA"], "date": [split_date], "ratio": [2.0]})
    before = _info(bars.raw_close, fundamentals, NO_SPLITS)[name].loc[day, "AAA"]
    after = _info(raw_after, fundamentals, splits)[name].loc[day, "AAA"]
    assert after == pytest.approx(before)


def test_a_split_is_not_read_as_share_issuance():
    rows = pd.DataFrame([
        {"ticker": "AAA", "field": "shares_outstanding", "period_end": "2014-12-31", "filed": "2015-03-02", "form": "10-K", "value": 1000.0},
        {"ticker": "AAA", "field": "shares_outstanding", "period_end": "2015-12-31", "filed": "2016-03-02", "form": "10-K", "value": 2000.0},
    ])
    splits = pd.DataFrame({"ticker": ["AAA"], "date": ["2015-06-01"], "ratio": [2.0]})
    assert growth_rows(rows, "shares_outstanding", "net_issuance", splits)["value"].tolist() == [pytest.approx(0.0)]
    assert growth_rows(rows, "shares_outstanding", "net_issuance")["value"].tolist() == [pytest.approx(1.0)]


def test_insider_and_short_tables_are_a_session_late():
    bars = _bars()
    insiders = pd.DataFrame([{"ticker": "AAA", "owner": "1", "filed": "2016-06-01", "traded": "2016-05-28", "code": "P", "value": 1e6}])
    shorts = pd.DataFrame({"AAA": [0.5] * 200}, index=DATES[:200])
    out = _info(bars.raw_close, _fundamentals(), NO_SPLITS, insiders=insiders, shorts=shorts)
    assert out["insider_net_180"].loc["2016-06-01", "AAA"] == 0.0
    assert out["insider_net_180"].loc["2016-06-02", "AAA"] > 0.0
    assert np.isnan(out["short_ratio_20"].loc[DATES[9], "AAA"]) and out["short_ratio_20"].loc[DATES[10], "AAA"] == pytest.approx(0.5)


def test_label_is_centred_within_each_sector_and_runs_out_at_the_end():
    bars = _bars()
    sector = {"AAA": "tech", "BBB": "tech", "CCC": "energy", "DDD": "energy", "SPY": "benchmark"}
    label = wide_label(bars, sector, horizon=21)
    row = label.iloc[100]
    assert row[["AAA", "BBB"]].sum() == pytest.approx(0.0) and row[["CCC", "DDD"]].sum() == pytest.approx(0.0)
    assert label.iloc[-21:].isna().all().all(), "no label past the data"
    assert label.iloc[-22:-21].notna().any(axis=None)


def test_label_ignores_names_outside_its_sector():
    bars = _bars()
    sector = {"AAA": "tech", "BBB": "tech", "CCC": "energy", "DDD": "energy"}
    label = wide_label(bars, sector)
    changed = _bars()
    changed.close["DDD"] = changed.close["DDD"] * 5.0
    pd.testing.assert_series_equal(wide_label(changed, sector)["AAA"], label["AAA"])


def test_unknown_sector_is_never_labelled_or_framed():
    bars = _bars()
    sector = {"AAA": "tech", "BBB": "tech", "CCC": "unknown", "DDD": "unknown", "SPY": "unknown"}
    label = wide_label(bars, sector)
    assert label["CCC"].isna().all()
    member = pd.DataFrame(True, index=DATES, columns=TICKERS)
    frame = long_frame({"ret_5": price_features(bars)["ret_5"]}, label, sector, member)
    assert set(frame["ticker"]) == {"AAA", "BBB"} and frame["ret_5"].dtype == np.float32 and set(frame["sector"]) == {"tech"}


def test_long_frame_keeps_only_member_rows():
    bars = _bars()
    sector = {ticker: "tech" for ticker in TICKERS}
    label = wide_label(bars, sector)
    member = pd.DataFrame(False, index=DATES, columns=TICKERS)
    member.loc[DATES[10]:DATES[12], "AAA"] = True
    frame = long_frame({}, label, sector, member)
    assert frame["date"].tolist() == DATES[10:13] and set(frame["ticker"]) == {"AAA"}


# --- trial tables ----------------------------------------------------------------------------------------------------


def _features():
    bars = _bars()
    features = dict(price_features(bars))
    features.update(_info(bars.raw_close, _fundamentals(), NO_SPLITS))
    return features


def test_every_trial_table_is_masked_to_members():
    features = _features()
    member = pd.DataFrame(True, index=DATES, columns=TICKERS)
    member["BBB"] = False
    tables = wide_tables(features, member)
    assert {"w01", "w02", "w05", "w06", "w09", "w11", "w12", "w14", "w15"} <= set(tables)
    for trial, table in tables.items():
        assert table["BBB"].isna().all(), trial


def test_signs_point_the_way_the_literature_does():
    features = _features()
    member = pd.DataFrame(True, index=DATES, columns=TICKERS)
    tables = wide_tables(features, member)
    pd.testing.assert_frame_equal(tables["w12"], -features["beta_252"])
    pd.testing.assert_frame_equal(tables["w03"], -features["asset_growth"])
    pd.testing.assert_frame_equal(tables["w09"], features["resmom_252"])


def test_rank_mean_needs_its_minimum():
    a = pd.DataFrame({"X": [1.0, np.nan], "Y": [2.0, 2.0]})
    b = pd.DataFrame({"X": [np.nan, np.nan], "Y": [3.0, 3.0]})
    out = rank_mean([a, b], minimum=2)
    assert np.isnan(out.loc[0, "X"]) and np.isnan(out.loc[1, "X"]) and out.loc[0, "Y"] == pytest.approx(1.0)
    assert rank_mean([a, b], minimum=1).loc[0, "X"] == pytest.approx(0.5)


def test_crypto_tables_read_no_future_and_only_liquid_coins():
    rng = np.random.default_rng(9)
    coins = ["BTCUSD", "ETHUSD", "LUNAUSD", "SOLUSD"]
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.03, (len(DATES), 4)), axis=0)), index=DATES, columns=coins)
    funding = pd.DataFrame(rng.normal(0.0002, 0.0001, (len(DATES), 4)), index=DATES, columns=coins)
    liquid = pd.DataFrame(True, index=DATES, columns=coins)
    liquid["LUNAUSD"] = False
    whole = crypto_tables(known, funding, liquid)
    cut = crypto_tables(known.loc[:CUT], funding.loc[:CUT], liquid.loc[:CUT])
    for trial in ("c1", "c2", "c3", "c4"):
        pd.testing.assert_series_equal(whole[trial].loc[CUT], cut[trial].loc[CUT], check_names=False)
        assert whole[trial]["LUNAUSD"].isna().all(), trial
    assert whole["c3"].loc[CUT].notna().any()


def test_todays_funding_is_not_in_todays_signal():
    rng = np.random.default_rng(9)
    coins = ["BTCUSD", "ETHUSD"]
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.03, (len(DATES), 2)), axis=0)), index=DATES, columns=coins)
    funding = pd.DataFrame(0.0001, index=DATES, columns=coins)
    liquid = pd.DataFrame(True, index=DATES, columns=coins)
    changed = funding.copy()
    changed.loc[CUT, "ETHUSD"] = 0.5
    a = crypto_tables(known, funding, liquid)["c3"].loc[CUT, "ETHUSD"]
    b = crypto_tables(known, changed, liquid)["c3"].loc[CUT, "ETHUSD"]
    assert a == pytest.approx(b)


def test_crypto_tables_without_funding_skip_the_funding_trials():
    known = pd.DataFrame(100.0, index=DATES, columns=["BTCUSD", "ETHUSD"])
    liquid = pd.DataFrame(True, index=DATES, columns=["BTCUSD", "ETHUSD"])
    assert set(crypto_tables(known, None, liquid)) == {"c1", "c2"}


def test_live_names_report_an_empty_book():
    table = pd.DataFrame(np.nan, index=DATES[:40], columns=["A", "B"])
    assert live_names_per_rebalance(table, 20) == {"median": 0.0, "minimum": 0.0}
    table.iloc[:, 0] = 1.0
    assert live_names_per_rebalance(table, 20)["median"] == 1.0
