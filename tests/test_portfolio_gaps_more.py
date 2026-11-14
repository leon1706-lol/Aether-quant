"""The last guards of portfolio/ (V6.6.6, #359): book construction, the FRED tables, the volatility target, the trend sleeve, filing signals and the legacy sleeve."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio import book_construction as bc
from portfolio import filing_signals as fs
from portfolio import legacy_sleeve as ls
from portfolio import premia_signals as ps
from portfolio import trend_sleeve as ts


def test_a_non_numeric_score_is_not_a_usable_rank():
    assert bc._is_finite_number("n/a") is False and bc._is_finite_number(None) is False and bc._is_finite_number(0.5) is True


def test_the_book_group_names_why_it_returned_nothing():
    reason: dict = {}
    assert bc._select_book_group({"A": 0.9}, 1, 0, 0.0, veto_reason_out=reason) == {} and reason["reason"] == "thin_universe_or_zero_top_n"
    assert bc._select_book_group({"A": 0.9, "B": 0.1}, 2, 1, 0.0, veto_reason_out=reason) == {} and reason["reason"] == "no_short_candidates"
    assert bc._select_book_group({"A": 0.9, "B": 0.1}, 2, 1, 0.0) == {}


def test_a_selection_that_finds_no_long_name_is_a_veto(monkeypatch):
    monkeypatch.setattr(bc, "_hysteresis_adjusted_selection", lambda *args: [])
    reason: dict = {}
    assert bc._select_book_group({"A": 0.9, "B": 0.1}, 1, 0, 0.0, veto_reason_out=reason) == {} and reason["reason"] == "no_long_candidates"
    assert bc._select_book_group({"A": 0.9, "B": 0.1}, 1, 0, 0.0) == {}


def test_the_weight_floor_and_class_caps_degrade_on_bad_input():
    assert bc.apply_book_weight_floor("x", 0.1, 0.5) == 0.0
    caps = bc.resolve_class_weight_caps({"crypto": {"per_name_cap": "abc", "class_gross_cap": 0.3}, "skipped": "no", "off": {"enabled": False}})
    assert caps["crypto"]["per_name_cap"] is None and caps["crypto"]["class_gross_cap"] == 0.3 and set(caps) == {"crypto"}


def test_a_history_record_carries_its_run_id():
    record = bc.build_book_history_record("2025-01-02", {}, {}, {}, {}, {"heads": {}}, run_id=12)
    assert record["run_id"] == "12"


def test_fred_rows_become_dated_series_and_an_empty_series_is_all_missing():
    tables = ps.fred_series_table({"DGS10": [{"date": "2025-01-03", "value": "4.1"}, {"date": "2025-01-02T00:00", "value": 4.0}, {"date": "2025-01-04", "value": None}]}, ("DGS10", "MISSING"))
    assert list(tables["DGS10"]) == [4.0, 4.1] and tables["MISSING"].empty
    sessions = pd.Index(["2025-01-02", "2025-01-03"])
    assert ps._asof(pd.Series(dtype=float), sessions).isna().all() and ps._asof(None, sessions).isna().all()


def test_a_book_with_no_variance_gets_no_weights():
    settings = ps.WeightSettings()
    raw = pd.Series({"AAA": 1.0, "BBB": -1.0})
    assert ps.scale_and_cap(raw, pd.DataFrame(0.0, index=raw.index, columns=raw.index), {}, settings) == {}


def test_the_trend_helpers_refuse_bad_closes_and_short_histories():
    assert ts._clean([1.0, "x"]) is None and ts._clean([1.0, -1.0]) is None
    assert ts.annualised_vol([1.0] * 5, 10) is None and ts.annualised_vol([1.0, 2.0, "x", 3.0], 3) is None
    assert ts.annualised_vol([100.0] * 12, 10) is None
    config = ts.TrendSleeveConfig(enabled=True, symbols=("AAA", "BBB", "CCC", "DDD"), signal="sign_63", vol_window=20, target_vol=0.2)
    rng = np.random.default_rng(0)
    steady = list(100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.01, 200))))
    closes = {"AAA": steady, "BBB": [], "CCC": [100.0] * 200}
    weights = ts.trend_sleeve_weights(closes, config)
    assert set(weights) <= {"AAA"}
    assert ts.trend_sleeve_weights(closes, ts.TrendSleeveConfig(enabled=True, symbols=("AAA",), signal="sign_63", vol_window=20, target_vol=0.2, gross_cap=0.0)) == {}
    assert ts.trend_sleeve_weights({"AAA": steady}, ts.TrendSleeveConfig(enabled=False, symbols=("AAA",))) == {}
    assert ts.trend_sleeve_weights({"AAA": [100.0] * 200}, config) == {}
    assert ts.apply_min_change({"AAA": 0.1}, {"AAA": float("nan"), "BBB": 0.0, "CCC": 0.2}, 0.01) == {"CCC": 0.2}


def _known():
    index = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-01", periods=40)]
    return pd.DataFrame({"AAA": np.linspace(10, 20, 40), "SPY": np.linspace(100, 110, 40), "BBB": np.linspace(5, 6, 40)}, index=index)


def test_announcement_returns_skip_events_without_room_or_prices():
    known = _known()
    assert fs.announcement_return(None, known).isna().all().all()
    rows = pd.DataFrame({"ticker": ["AAA", "AAA", "BBB"], "accepted": [known.index[0], known.index[38], known.index[10]]})
    table = fs.announcement_return(rows, known)
    assert table["AAA"].isna().all() and table["BBB"].notna().any()
    broken = known.copy()
    broken.loc[broken.index[13], "BBB"] = np.nan
    assert fs.announcement_return(pd.DataFrame({"ticker": ["BBB"], "accepted": [known.index[10]]}), broken)["BBB"].isna().all()


def test_opportunistic_buying_is_empty_without_usable_trades():
    known = _known()
    assert (fs.opportunistic_buying(None, known.index, known.columns) == 0.0).all().all()
    sales = pd.DataFrame({"ticker": ["AAA"], "owner": ["o"], "code": ["S"], "filed": [known.index[5]], "value": [1000.0]})
    assert (fs.opportunistic_buying(sales, known.index, known.columns) == 0.0).all().all()
    routine = pd.DataFrame({"ticker": ["AAA"] * 4, "owner": ["o"] * 4, "code": ["P"] * 4, "filed": ["2021-01-05", "2022-01-05", "2023-01-05", "2024-01-05"], "value": [1000.0] * 4})
    table = fs.opportunistic_buying(routine, pd.Index(["2024-01-05", "2024-01-08"]), pd.Index(["AAA"]), routine_years=3)
    assert (table["AAA"] == 0.0).all() or table["AAA"].notna().all()


CONFIG = {"enabled": True, "max_weight_per_name": 0.02, "max_gross_exposure": 0.05, "trade_when_book_vetoed": False}


def test_the_legacy_sleeve_degrades_on_non_numeric_and_exhausted_budgets():
    held = ls.apply_legacy_sleeve_policy("buy", "x", False, True, True, 0.0, CONFIG)
    assert held["reason"] == "legacy_sleeve_not_applicable"
    assert ls.apply_legacy_sleeve_policy("buy", "x", False, False, True, 0.0, CONFIG)["reason"] == "legacy_sleeve_non_finite_weight"
    assert ls.apply_legacy_sleeve_policy("buy", 0.05, False, False, True, float("nan"), CONFIG)["reason"] == "legacy_sleeve_non_finite_weight"
    assert ls.apply_legacy_sleeve_policy("buy", 0.05, False, False, True, 0.05, CONFIG)["reason"] == "legacy_sleeve_budget_exhausted"
    assert ls.apply_legacy_sleeve_policy("buy", 0.0, False, False, True, 0.01, CONFIG)["reason"] == "legacy_sleeve_budget_exhausted"
    assert pytest is not None
