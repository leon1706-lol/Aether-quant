"""V6.4.0 (lead L11, rule R-L11): Lean's logged book-call probabilities against the offline head."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from evaluation.backtest_statistics import _classification_section, lean_book_calls
from evaluation.classification_parity import TOLERANCE, lean_vs_offline_classification, offline_probability_map


def _calls(probabilities, truth):
    n = len(truth)
    return {"truth": list(truth), "predicted": [1] * n, "probability": list(probabilities),
            "dates": [f"2024-01-{index + 1:02d}" for index in range(n)], "tickers": ["AAA"] * n}


def _offline(calls, values):
    return {(day, ticker): value for day, ticker, value in zip(calls["dates"], calls["tickers"], values)}


def test_identical_probabilities_are_within_tolerance():
    calls = _calls([0.7, 0.4, 0.6, 0.3], [1, 0, 1, 0])
    result = lean_vs_offline_classification(calls, _offline(calls, [0.7, 0.4, 0.6, 0.3]))
    assert result["n_matched"] == 4
    assert result["within_tolerance"] is True
    assert result["deltas"]["median_abs_probability_gap"] == 0.0
    assert result["lean"]["accuracy"] == pytest.approx(1.0)


def test_a_probability_gap_beyond_tolerance_fails():
    calls = _calls([0.7, 0.4, 0.6, 0.3], [1, 0, 1, 0])
    result = lean_vs_offline_classification(calls, _offline(calls, [0.6, 0.5, 0.5, 0.4]))
    assert result["within_tolerance"] is False
    assert result["checks"]["median_abs_probability_gap"] is False
    assert result["deltas"]["max_abs_probability_gap"] == pytest.approx(0.1)


def test_rows_missing_either_probability_are_dropped_and_counted():
    calls = _calls([0.7, None, 0.6], [1, 0, 1])
    offline = _offline(calls, [0.7, 0.4, float("nan")])
    result = lean_vs_offline_classification(calls, offline)
    assert (result["n_calls"], result["n_matched"]) == (3, 1)
    assert (result["missing_lean_probability"], result["missing_offline_probability"]) == (1, 1)


def test_no_matched_row_gives_no_verdict():
    calls = _calls([None, None], [1, 0])
    result = lean_vs_offline_classification(calls, {})
    assert result["within_tolerance"] is None and result["lean"] is None and result["reason"]


def test_tolerance_is_the_pre_registered_one():
    assert TOLERANCE == {"accuracy": 0.01, "neg_log_loss": 0.01, "median_abs_probability_gap": 0.005}


def test_offline_probability_map_keeps_finite_values_and_normalises_keys():
    frame = pd.DataFrame({"date": ["2024-01-02 00:00:00", "2024-01-03"], "ticker": ["aaa", "BBB"], "p": [0.5, float("nan")]})
    assert offline_probability_map(frame, "p") == {("2024-01-02", "AAA"): 0.5}


def _history(probability):
    return [{"date": "2024-01-02", "allocations": {"AAA": {"role": "long"}, "BBB": {"role": "short"}},
             "member_probabilities": {"AAA": {"direction_prob_multitask": probability, "probability_up": 0.9},
                                      "BBB": {"direction_prob_multitask": 0.25}}}]


def _closes():
    days = [f"2024-01-{day:02d}" for day in range(1, 29)]
    up = {day: 100.0 + index for index, day in enumerate(days)}
    down = {day: 100.0 - index for index, day in enumerate(days)}
    closes = {"AAA": up, "BBB": down}
    return closes, {ticker: sorted(series) for ticker, series in closes.items()}


def test_lean_book_calls_carry_the_logged_probability():
    closes, ordered = _closes()
    calls = lean_book_calls(_history(0.8), closes, ordered)
    assert calls["tickers"] == ["AAA", "BBB"]
    assert calls["truth"] == [1, 0] and calls["predicted"] == [1, 0]
    assert calls["probability"] == [0.8, 0.25]


def test_classification_section_fills_log_loss_only_when_every_call_has_a_probability():
    closes, ordered = _closes()
    full = _classification_section(_history(0.8), closes, ordered, None)[0]
    assert full["reason"] is None
    assert full["neg_log_loss"] == pytest.approx((math.log(0.8) + math.log(0.75)) / 2)
    partial = _classification_section(_history(None), closes, ordered, None)[0]
    assert partial["neg_log_loss"] is None and "1 of 2" in partial["reason"]
    none_logged = _classification_section([{"date": "2024-01-02", "allocations": {"AAA": {"role": "long"}}}], closes, ordered, None)[0]
    assert none_logged["reason"] == "no probability is logged per book call"
