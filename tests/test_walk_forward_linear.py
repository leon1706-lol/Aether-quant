"""evaluation/walk_forward_linear.py: no look-ahead, and the sign prior holds."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.walk_forward_linear import MIN_SLOPE_MONTHS, fama_macbeth_ridge, monthly_slope

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2012-01-02", periods=700)]
TICKERS = [f"T{number:03d}" for number in range(80)]
START = DATES[30]


def _features(seed: int = 3) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    return {
        name: pd.DataFrame(rng.normal(size=(len(DATES), len(TICKERS))), index=DATES, columns=TICKERS)
        for name in ("good", "noise")
    }


def _label(features: dict[str, pd.DataFrame], seed: int = 5, strength: float = 1.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    raw = features["good"] * strength + rng.normal(size=(len(DATES), len(TICKERS)))
    return raw.rank(axis=1, pct=True) - 0.5


def _ic(score: pd.DataFrame, label: pd.DataFrame, start: str) -> float:
    dates = [date for date in score.index if date >= start]
    return float(np.mean([score.loc[date].corr(label.loc[date], method="spearman") for date in dates[::21]]))


def test_a_real_feature_earns_ic_and_the_score_starts_where_it_should():
    features = _features()
    label = _label(features)
    score = fama_macbeth_ridge(features, label, signs={"good": 1.0, "noise": 1.0}, start=START)
    assert score.loc[:DATES[29]].isna().all().all()
    assert score.loc[START].notna().all()
    assert _ic(score, label, DATES[500]) > 0.4


def test_the_label_after_the_decision_can_not_change_the_score():
    features = _features()
    label = _label(features)
    whole = fama_macbeth_ridge(features, label, signs={"good": 1.0, "noise": 1.0}, start=START)
    cut = DATES[500]
    changed = label.copy()
    # Every label a row at `cut` may not yet know: it ends after cut - purge, so it must not move the score.
    changed.iloc[500 - 21 - 21 + 1:] = -changed.iloc[500 - 21 - 21 + 1:] * 9.0
    moved = fama_macbeth_ridge(features, changed, signs={"good": 1.0, "noise": 1.0}, start=START)
    pd.testing.assert_series_equal(whole.loc[cut], moved.loc[cut])


def test_features_after_the_decision_can_not_change_the_score():
    features = _features()
    label = _label(features)
    whole = fama_macbeth_ridge(features, label, signs={"good": 1.0, "noise": 1.0}, start=START)
    cut = DATES[500]
    changed = {name: table.copy() for name, table in features.items()}
    for table in changed.values():
        table.iloc[501:] = table.iloc[501:] * -3.0
    moved = fama_macbeth_ridge(changed, label, signs={"good": 1.0, "noise": 1.0}, start=START)
    pd.testing.assert_series_equal(whole.loc[cut], moved.loc[cut])


def test_with_few_slopes_it_is_the_sign_composite():
    features = _features()
    label = _label(features)
    score = fama_macbeth_ridge(features, label, signs={"good": 1.0, "noise": -1.0}, start=START)
    date = DATES[50]  # far fewer than MIN_SLOPE_MONTHS monthly slopes have ended
    assert 50 / 21 < MIN_SLOPE_MONTHS
    ranks = {name: table.loc[date].rank(pct=True) - 0.5 for name, table in features.items()}
    pd.testing.assert_series_equal(score.loc[date], ranks["good"] - ranks["noise"], check_names=False)


def test_a_slope_against_the_prior_counts_as_zero():
    features = _features()
    label = _label(features)
    only_wrong = fama_macbeth_ridge({"good": features["good"]}, label, signs={"good": -1.0}, start=START)
    assert only_wrong.loc[DATES[600]].isna().all(), "no view, rather than a bet against what the slopes say"
    with_noise = fama_macbeth_ridge(features, label, signs={"good": -1.0, "noise": -1.0}, start=START)
    row = with_noise.loc[DATES[600]]
    if row.notna().any():
        # `good` carries no weight, so what is left is the noise feature's rank alone.
        assert abs(row.corr(features["noise"].loc[DATES[600]], method="spearman")) > 0.999


def test_a_missing_feature_is_an_error():
    features = _features()
    with pytest.raises(KeyError):
        fama_macbeth_ridge(features, _label(features), signs={"good": 1.0, "absent": 1.0}, start=START)


def test_a_slope_needs_enough_names():
    ranks = np.zeros((10, 2))
    assert monthly_slope(ranks, np.ones(10), ridge=1.0) is None


def test_a_missing_value_reads_as_the_middle_and_a_name_with_nothing_stays_unscored():
    features = _features()
    features["good"].iloc[:, 0] = np.nan
    features["noise"].iloc[:, 0] = np.nan
    features["good"].iloc[:, 1] = np.nan
    score = fama_macbeth_ridge(features, _label(features), signs={"good": 1.0, "noise": 1.0}, start=START)
    date = DATES[100]
    assert np.isnan(score.loc[date, TICKERS[0]]) and np.isfinite(score.loc[date, TICKERS[1]])
