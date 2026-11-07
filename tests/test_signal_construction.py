"""portfolio/signal_construction.py and the pooled book kind of portfolio/premia_signals.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.premia_research import nulls_for
from portfolio.premia_signals import POOLED, TS, XS, SleeveSpec, _raw_weights
from portfolio.signal_construction import MIN_RESIDUAL_NAMES, build_table, residualise_signal

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2015-01-01", periods=30)]
TICKERS = [f"T{number:03d}" for number in range(60)]
SECTORS = {ticker: ("tech" if number < 40 else "energy") for number, ticker in enumerate(TICKERS)}


def _table(seed: int = 1) -> pd.DataFrame:
    return pd.DataFrame(np.random.default_rng(seed).normal(size=(len(DATES), len(TICKERS))), index=DATES, columns=TICKERS)


def test_pooled_weights_are_neutral_in_each_class_and_follow_its_breadth():
    row = _table().iloc[0]
    raw = _raw_weights(row, POOLED, row.abs(), SECTORS)
    tech, energy = raw[[t for t in TICKERS if SECTORS[t] == "tech"]], raw[[t for t in TICKERS if SECTORS[t] == "energy"]]
    assert abs(tech.sum()) < 1e-12 and abs(energy.sum()) < 1e-12
    assert tech.abs().sum() == pytest.approx(2.0 * energy.abs().sum(), rel=0.05)


def test_within_class_ranks_and_time_series_are_untouched_by_the_new_kind():
    row = _table().iloc[0]
    xs = _raw_weights(row, XS, row.abs(), SECTORS)
    for sector in ("tech", "energy"):
        members = xs[[ticker for ticker in TICKERS if SECTORS[ticker] == sector]]
        assert members.abs().sum() == pytest.approx(1.0)
    ts = _raw_weights(row, TS, row.abs(), SECTORS)
    pd.testing.assert_series_equal(ts.sort_index(), (row / row.abs()).sort_index(), check_names=False)


def test_a_pooled_sleeve_gets_a_ranking_null():
    spec = SleeveSpec("k", "W", POOLED, "external_score", ("tech",), 20, {"table": "k"})
    assert nulls_for(spec) == ("asset_block", "time_shift")


def test_residual_is_orthogonal_to_the_exposure():
    table, exposure = _table(1), _table(2)
    residual = residualise_signal(table + exposure, {"size": exposure}, SECTORS)
    for date in DATES:
        ranked = exposure.loc[date].rank(pct=True)
        assert abs(np.corrcoef(residual.loc[date], ranked)[0, 1]) < 1e-8


def test_residual_of_a_date_ignores_every_other_date():
    table, exposure = _table(1), _table(2)
    whole = residualise_signal(table, {"size": exposure}, SECTORS)
    changed = table.copy()
    changed.iloc[20:] = changed.iloc[20:] * -7.0
    moved = residualise_signal(changed, {"size": exposure}, SECTORS)
    pd.testing.assert_series_equal(whole.iloc[10], moved.iloc[10])


def test_too_few_names_is_nan_never_the_raw_signal():
    table, exposure = _table(1), _table(2)
    table.iloc[3, MIN_RESIDUAL_NAMES - 5:] = np.nan
    assert residualise_signal(table, {"size": exposure}, SECTORS).iloc[3].isna().all()


def test_build_table_recipes():
    tables = {"a": _table(1), "b": _table(2)}
    pd.testing.assert_frame_equal(build_table({"op": "single", "parts": ["a"], "signs": {"a": -1.0}}, tables), -tables["a"])
    mean = build_table({"op": "rank_mean", "parts": ["a", "b"]}, tables)
    assert mean.notna().all().all()
    member = pd.DataFrame(True, index=DATES, columns=TICKERS)
    member[TICKERS[0]] = False
    masked = build_table({"op": "single", "parts": ["a"]}, tables, member)
    assert masked[TICKERS[0]].isna().all() and masked[TICKERS[1]].notna().all()
    residual = build_table({"op": "residualise", "parts": ["a"], "exposures": ["b"]}, tables, sectors=SECTORS)
    assert residual.notna().all().all()


@pytest.mark.parametrize("recipe", [
    {"op": "single", "parts": ["missing"]},
    {"op": "rank_mean", "parts": ["a", "missing"]},
    {"op": "residualise", "parts": ["a"], "exposures": ["missing"]},
])
def test_a_missing_part_is_an_error_not_a_different_trial(recipe):
    with pytest.raises(KeyError):
        build_table(recipe, {"a": _table(1)}, sectors=SECTORS)


def test_an_unknown_recipe_is_an_error():
    with pytest.raises(ValueError):
        build_table({"op": "fit_everything", "parts": ["a"]}, {"a": _table(1)})
