"""evaluation/premia_research.py: the scoring and the rule R-SLEEVE2 as code."""

import numpy as np
import pandas as pd
import pytest

from evaluation.premia_research import (
    annual_sharpe,
    max_drawdown,
    nulls_for,
    passes_sharpe_clauses,
    phase_offsets,
    placebo_p_value,
    selection_gate,
)
from portfolio.premia_signals import DIRECT, TS, XS, SleeveSpec


def _score(name, sharpe=1.0, first=0.6, second=0.6, seed=0):
    rng = np.random.default_rng(seed)
    daily = pd.Series(rng.normal(0.001, 0.01, size=300), index=pd.bdate_range("2020-01-01", periods=300).strftime("%Y-%m-%d"))
    return {"id": name, "sharpe": sharpe, "sharpe_first_half": first, "sharpe_second_half": second, "daily": {0: daily}}


PASS = {"a": 0.01, "b": 0.01}


def test_annual_sharpe_and_short_or_flat_series():
    rng = np.random.default_rng(0)
    series = pd.Series(rng.normal(0.001, 0.01, size=400))
    expected = series.mean() / series.std(ddof=1) * np.sqrt(365.0)
    assert annual_sharpe(series) == pytest.approx(expected)
    assert annual_sharpe(pd.Series([0.1] * 5)) is None
    assert annual_sharpe(pd.Series([0.0] * 50)) is None


def test_max_drawdown():
    assert max_drawdown(pd.Series([0.1, -0.5, 0.2])) == pytest.approx(0.5)
    assert max_drawdown(pd.Series(dtype=float)) == 0.0


def test_phase_offsets_spread_over_the_rebalance_period():
    assert phase_offsets(20) == [0, 4, 8, 12, 16]
    assert phase_offsets(5) == [0, 1, 2, 3, 4]
    assert phase_offsets(1) == [0]


def test_nulls_depend_on_the_sleeve_kind():
    assert nulls_for(SleeveSpec("x", "T", XS, "f", (), 5)) == ("asset_block", "time_shift")
    assert nulls_for(SleeveSpec("x", "T", TS, "f", (), 5)) == ("sign_block", "time_shift")
    assert nulls_for(SleeveSpec("x", "T", DIRECT, "f", (), 5)) == ("sign_block", "time_shift")


def test_placebo_p_value_counts_the_observation_and_ties():
    assert placebo_p_value(2.0, [0.0, 1.0, 3.0]) == pytest.approx(2.0 / 4.0)
    assert placebo_p_value(1.0, [1.0]) == pytest.approx(1.0)
    assert placebo_p_value(9.0, [0.0] * 199) == pytest.approx(1.0 / 200.0)
    assert placebo_p_value(None, [0.0]) == 1.0
    assert placebo_p_value(1.0, []) == 1.0


@pytest.mark.parametrize("sharpe,first,second,expected", [
    (0.50, 0.40, 0.40, True),
    (0.49, 0.40, 0.40, False),
    (0.50, 0.39, 0.40, False),
    (0.50, 0.40, 0.39, False),
    (None, 0.40, 0.40, False),
    (0.50, None, 0.40, False),
])
def test_sharpe_clauses_are_the_rule_text(sharpe, first, second, expected):
    assert passes_sharpe_clauses({"sharpe": sharpe, "sharpe_first_half": first, "sharpe_second_half": second}) is expected


def test_gate_requires_every_placebo():
    gate = selection_gate([_score("x")], {"x": {"a": 0.01, "b": 0.06}})
    assert gate["survivors"] == []
    assert gate["failed"]["x"] == "placebo"


def test_gate_treats_missing_placebos_as_a_failure():
    assert selection_gate([_score("x")], {})["failed"]["x"] == "placebo"


def test_gate_keeps_the_better_of_two_correlated_sleeves():
    gate = selection_gate([_score("low", sharpe=0.9, seed=1), _score("high", sharpe=1.2, seed=1)], {"low": PASS, "high": PASS})
    assert gate["survivors"] == ["high"]
    assert gate["failed"]["low"] == "correlated"


def test_gate_keeps_uncorrelated_sleeves_up_to_the_budget_by_sharpe():
    scores = [_score(f"s{i}", sharpe=1.0 + i / 10.0, seed=i) for i in range(7)]
    gate = selection_gate(scores, {f"s{i}": PASS for i in range(7)})
    assert gate["survivors"] == ["s6", "s5", "s4", "s3", "s2"]
    assert gate["failed"]["s0"] == "budget"


def test_gate_with_no_pass_returns_no_survivors():
    assert selection_gate([_score("x", sharpe=0.1)], {"x": PASS}) == {"survivors": [], "failed": {"x": "sharpe"}}
