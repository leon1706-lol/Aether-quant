"""evaluation/alpha_behaviour.py (V6.6.10, R-ALPHA1): on synthetic panels whose answer is known."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from evaluation import alpha_behaviour as ab


def _panel(seed=0, sessions=300, names=12, signal=0.004):
    """Closes whose next-day return is `signal` times a persistent score, plus noise: the score predicts, and a stale score less so."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2020-01-01", periods=sessions)
    tickers = [f"T{i:02d}" for i in range(names)]
    base = rng.normal(size=names)
    score = pd.DataFrame([base + rng.normal(scale=0.3, size=names) for _ in range(sessions)], index=index, columns=tickers)
    returns = signal * score.shift(0) + rng.normal(scale=0.01, size=(sessions, names))
    closes = (1.0 + returns.shift(1).fillna(0.0)).cumprod() * 100.0
    return score, closes


def test_forward_returns_and_the_daily_ic():
    closes = pd.DataFrame({"A": [1.0, 2.0, 4.0], "B": [1.0, 1.0, 1.0]})
    assert ab.forward_returns(closes, 1)["A"].tolist()[:2] == [1.0, 1.0] and math.isnan(ab.forward_returns(closes, 1)["A"].iloc[-1])
    scores = pd.DataFrame({"A": [1.0, 2.0], "B": [2.0, 1.0], "C": [3.0, 3.0]})
    outcome = pd.DataFrame({"A": [1.0, 3.0], "B": [2.0, 2.0], "C": [3.0, 1.0]})
    ic = ab.session_rank_ic(scores, outcome, min_names=3)
    assert ic.iloc[0] == pytest.approx(1.0) and ic.iloc[1] == pytest.approx(-0.5)
    assert ab.session_rank_ic(scores, outcome, min_names=4).isna().all()
    flat = pd.DataFrame({"A": [1.0], "B": [1.0], "C": [1.0]})
    assert ab.session_rank_ic(flat, outcome.iloc[:1], min_names=2).isna().all(), "no spread: no IC"


def test_a_predictive_score_has_a_positive_term_structure_and_a_half_life():
    score, closes = _panel()
    term = ab.ic_term_structure(score, closes, horizons=(1, 5, 20))
    assert term[1]["mean_ic"] > 0.1 and term[1]["t_hac"] > 2 and term[20]["n"] > 0
    assert ab.ic_summary(pd.Series([np.nan]), lags=0) == {"mean_ic": None, "t_hac": None, "n": 0}
    profile = ab.ic_lag_profile(score, closes, step=5, lags=4)
    assert set(profile) == {0, 5, 10, 15}


def test_half_life_from_a_decaying_profile_and_the_cases_it_refuses():
    assert ab.half_life({0: 0.08, 5: 0.04, 10: 0.02}) == pytest.approx(5.0)
    assert ab.half_life({0: -0.01, 5: 0.02}) is None
    assert ab.half_life({0: 0.05, 5: None}) is None
    assert ab.half_life({0: 0.02, 5: 0.04}) is None, "a rising IC has no half-life"


def test_ic_by_group_and_by_period():
    score, closes = _panel(names=10)
    groups = {ticker: ("equity" if int(ticker[1:]) < 5 else "crypto") for ticker in score.columns}
    outcome = ab.forward_returns(closes, 1)
    by_class = ab.ic_by_group(score, outcome, groups)
    assert set(by_class) == {"crypto", "equity"} and by_class["equity"]["mean_ic"] > 0
    ic = ab.session_rank_ic(score, outcome)
    labels = pd.Series(["a" if i % 2 else "b" for i in range(len(ic))], index=ic.index)
    assert set(ab.ic_by_period(ic, labels)) == {"a", "b"}


def test_the_spread_after_costs_pays_for_turnover():
    score, closes = _panel()
    cheap = ab.spread_after_costs(score, closes, horizon=5, cost_bps=0.0)
    dear = ab.spread_after_costs(score, closes, horizon=5, cost_bps=50.0)
    assert cheap["gross_annual"] > 0 and cheap["net_annual"] == pytest.approx(cheap["gross_annual"]) and dear["net_annual"] < cheap["net_annual"]
    assert 0 < cheap["turnover"] <= 1.0
    weights = ab.rank_weights(score)
    assert weights.sum(axis=1).abs().max() < 1e-12 and weights.abs().sum(axis=1).iloc[0] == pytest.approx(1.0)
    empty = ab.spread_after_costs(score.iloc[:0], closes.iloc[:0], horizon=5)
    assert empty["rebalances"] == 0 and empty["gross_annual"] is None


def test_a_score_that_is_a_factor_has_no_residual_alpha():
    score, _ = _panel()
    exposure = ab.premia_exposure(score, {"same": score, "noise": score.sample(frac=1.0, axis=1, random_state=1).set_axis(score.columns, axis=1)})
    assert exposure["betas"]["same"] == pytest.approx(1.0, abs=1e-6) and exposure["r_squared"] == pytest.approx(1.0) and exposure["sessions"] == len(score)
    assert exposure["residual"].abs().max().max() < 1e-9
    thin = ab.premia_exposure(score.iloc[:, :3], {"same": score.iloc[:, :3]})
    assert thin["sessions"] == 0 and thin["betas"]["same"] is None and thin["r_squared"] is None
    constant = ab.premia_exposure(pd.DataFrame(1.0, index=score.index[:2], columns=score.columns), {"f": score.iloc[:2]})
    assert constant["r_squared"] == 0.0


def test_breadth_and_the_whole_report():
    score, closes = _panel(sessions=200, names=10)
    groups = {ticker: ("equity" if int(ticker[1:]) < 5 else "bond") for ticker in score.columns}
    assert ab.breadth(score) == {"mean_names": 10.0}
    assert ab.breadth(score, groups)["by_group"] == {"bond": 5.0, "equity": 5.0}
    regimes = pd.Series(["calm"] * 100 + ["storm"] * 100, index=score.index)
    report = ab.alpha_report(score, closes, groups=groups, factors={"momentum": closes.pct_change(20)}, regimes=regimes, horizon=5)
    assert set(report) >= {"term_structure", "half_life_sessions", "by_class", "by_year", "spread", "premia", "residual_ic", "breadth", "by_regime"}
    assert "residual" not in report["premia"] and report["residual_ic"]["n"] > 0
    assert "by_regime" not in ab.alpha_report(score, closes, groups=groups, factors={"momentum": closes.pct_change(20)}, horizon=5)
