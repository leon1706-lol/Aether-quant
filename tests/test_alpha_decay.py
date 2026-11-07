"""evaluation/alpha_decay.py: the detector and its limits."""

from __future__ import annotations

import math

import numpy as np
import pytest

from evaluation.alpha_decay import DecayConfig, average_run_lengths, cusum_lower, cusum_path, decay_state


def _returns(sharpe: float, sessions: int, seed: int = 1, vol: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(sharpe / math.sqrt(252.0) * vol, vol, sessions)


def test_the_statistic_rests_at_zero_so_old_gains_can_not_hide_a_new_loss():
    good = _returns(3.0, 500)
    path = cusum_path(good, expected_sharpe=0.0)
    assert path.min() == 0.0 and (path >= 0.0).all()
    bad = np.concatenate([good, _returns(-6.0, 250, seed=2)])
    assert cusum_lower(bad, expected_sharpe=0.0, threshold=8.0) > 0.5


def test_flat_returns_have_no_alarm():
    assert cusum_lower(np.zeros(100), expected_sharpe=1.0, threshold=8.0) == 0.0


def test_too_few_sessions_keeps_the_state():
    report = decay_state(_returns(-5.0, 30), expected_sharpe=1.0, previous="watch")
    assert report.state == "watch" and "minimum" in report.reason


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_non_finite_evidence_keeps_the_state(value):
    returns = _returns(0.0, 100)
    returns[50] = value
    report = decay_state(returns, expected_sharpe=1.0, previous="decaying")
    assert report.state == "decaying" and "non-finite" in report.reason


def test_a_generation_earning_what_it_should_stays_healthy():
    assert decay_state(_returns(1.0, 500), expected_sharpe=0.5).state == "healthy"


def test_a_collapse_walks_through_the_states():
    states = []
    previous = "healthy"
    series = np.concatenate([_returns(1.0, 100), _returns(-8.0, 1000, seed=2)])
    for end in range(100, len(series), 20):
        previous = decay_state(series[:end], expected_sharpe=1.0, previous=previous).state
        states.append(previous)
    assert states[0] == "healthy" and states[-1] == "dead"
    first = {state: states.index(state) for state in ("watch", "decaying", "dead")}
    assert first["watch"] < first["decaying"] < first["dead"]


def test_a_state_does_not_flicker_on_one_good_week():
    config = DecayConfig()
    series = _returns(-8.0, 400, seed=3)
    report = decay_state(series, expected_sharpe=1.0, previous="healthy", config=config)
    assert report.state in ("decaying", "dead")
    week = np.concatenate([series, np.full(5, 0.05)])
    assert decay_state(week, expected_sharpe=1.0, previous="decaying", config=config).state in ("decaying", "dead")


def test_dead_stays_dead():
    good = _returns(5.0, 300, seed=4)
    assert decay_state(good, expected_sharpe=0.0, previous="dead").state == "dead"


def test_a_lower_state_returns_after_a_long_recovery():
    good = _returns(5.0, 300, seed=4)
    assert decay_state(good, expected_sharpe=0.0, previous="watch").state == "healthy"


def test_run_lengths_show_the_tradeoff():
    report = average_run_lengths(expected_sharpe=1.0, paths=200, horizon=1260, seed=3)
    assert report["median_detection_sessions"] < report["median_false_alarm_sessions"]
    assert 0.0 <= report["false_alarm_within_1y"] <= report["false_alarm_within_5y"] <= 1.0
    assert report["detected_within_1y"] <= report["detected_within_2y"]
