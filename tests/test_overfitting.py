"""evaluation/overfitting.py (V6.6.5, #345): MinTRL (Bailey & López de Prado 2012) and the haircut Sharpe (Harvey & Liu 2015)."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest

from evaluation.overfitting import haircut_sharpe, minimum_track_record_length, pbo
from evaluation.pbo import probability_of_backtest_overfitting


def test_min_trl_matches_the_closed_form_on_a_symmetric_two_point_series():
    # +-a with equal counts shifted by mu: skew 0 and raw kurtosis 1 exactly, so MinTRL = 1 + (z / SR)^2 for target 0
    values = np.array([0.011, -0.009] * 500)
    sr = values.mean() / values.std(ddof=1)
    centred = values - values.mean()
    kurt = np.mean(centred**4) / np.mean(centred**2) ** 2
    z = NormalDist().inv_cdf(0.95)
    expected = 1 + (1 + (kurt - 1) / 4 * sr**2) * (z / sr) ** 2
    assert math.isclose(minimum_track_record_length(values), expected, rel_tol=1e-12)
    assert math.isclose(kurt, 1.0, rel_tol=1e-9)


def test_min_trl_grows_with_the_target_and_is_infinite_when_unreachable():
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, 2000)
    low = minimum_track_record_length(returns, target_sharpe=0.0)
    high = minimum_track_record_length(returns, target_sharpe=1.0)
    assert 0 < low < high
    assert minimum_track_record_length(-np.abs(returns)) == math.inf
    assert math.isnan(minimum_track_record_length([0.01, 0.01, 0.01]))
    assert math.isnan(minimum_track_record_length([0.01]))


def test_haircut_sharpe_one_trial_has_no_haircut_and_more_trials_cut_more():
    single = haircut_sharpe(1.0, 252 * 10, 1, method="bonferroni")
    assert math.isclose(single["haircut_sharpe"], 1.0, rel_tol=1e-9) and abs(single["haircut"]) < 1e-9
    cuts = [haircut_sharpe(1.0, 252 * 10, m, method="bonferroni")["haircut"] for m in (1, 10, 100, 1000)]
    assert cuts == sorted(cuts)
    bhy = haircut_sharpe(1.0, 252 * 10, 50, method="bhy")["haircut"]
    bonferroni = haircut_sharpe(1.0, 252 * 10, 50, method="bonferroni")["haircut"]
    holm = haircut_sharpe(1.0, 252 * 10, 50, method="holm")["haircut"]
    assert bhy >= bonferroni and math.isclose(holm, bonferroni)


def test_haircut_sharpe_t_stat_and_p_value():
    out = haircut_sharpe(0.8, 252 * 5, 20, periods_per_year=252)
    assert math.isclose(out["t_stat"], 0.8 * math.sqrt(5))
    assert math.isclose(out["p_value"], 2 * (1 - NormalDist().cdf(0.8 * math.sqrt(5))))
    assert 0 <= out["haircut_sharpe"] <= 0.8
    assert haircut_sharpe(-0.5, 1000, 10)["haircut"] == 1.0
    assert haircut_sharpe(0.5, 0, 10)["haircut_sharpe"] == 0.0
    with pytest.raises(ValueError):
        haircut_sharpe(1.0, 100, 10, method="sidak")  # type: ignore[arg-type]


def test_pbo_is_the_cscv_function():
    assert pbo is probability_of_backtest_overfitting
