"""Tests for evaluation/rank_signal_calibration.py (V5.1) - calibrating
phase_v2.portfolio_book.min_rank_confidence_spread from real data instead
of a guessed constant.
"""

import numpy as np
import pandas as pd
import pytest

from evaluation.rank_signal_calibration import (
    calibrate_book_confidence_spread,
    compute_blended_raw_scores,
)
from portfolio.book_construction import compute_confidence_spread


# ---------------------------------------------------------------------------
# compute_blended_raw_scores()
# ---------------------------------------------------------------------------


def _policy(**overrides):
    policy = {"heads": {"rank_20d": 1.0}, "model_priority": ["sequence", "multitask"]}
    policy.update(overrides)
    return policy


def test_compute_blended_raw_scores_prefers_sequence_then_falls_back_to_multitask():
    dataset = pd.DataFrame({"ticker": ["A", "B"]})
    predictions = {
        "sequence": {"rank_20d": np.array([0.8, np.nan])},
        "multitask": {"rank_20d": np.array([0.5, 0.3])},
    }
    scores = compute_blended_raw_scores(dataset, predictions, _policy())
    assert scores.iloc[0] == 0.8  # sequence available, wins model_priority
    assert scores.iloc[1] == 0.3  # sequence NaN this row, falls back to multitask


def test_compute_blended_raw_scores_nan_when_no_head_available():
    dataset = pd.DataFrame({"ticker": ["A"]})
    predictions = {
        "sequence": {"rank_20d": np.array([np.nan])},
        "multitask": {"rank_20d": np.array([np.nan])},
    }
    scores = compute_blended_raw_scores(dataset, predictions, _policy())
    assert np.isnan(scores.iloc[0])


def test_compute_blended_raw_scores_blends_two_heads_by_configured_weight():
    dataset = pd.DataFrame({"ticker": ["A"]})
    predictions = {"sequence": {"rank_20d": np.array([0.8]), "rank_5d": np.array([0.4])}}
    policy = _policy(heads={"rank_20d": 0.5, "rank_5d": 0.5})
    scores = compute_blended_raw_scores(dataset, predictions, policy)
    assert scores.iloc[0] == (0.8 + 0.4) / 2


# ---------------------------------------------------------------------------
# calibrate_book_confidence_spread()
# ---------------------------------------------------------------------------


def _dataset_frame():
    rows = []
    # 2020-01-01: wide, genuine dispersion.
    for ticker, score in [("A", 0.9), ("B", 0.7), ("C", 0.3), ("D", 0.1)]:
        rows.append({"date": "2020-01-01", "ticker": ticker, "raw_score": score})
    # 2020-01-02: compressed, near-constant dispersion (the bug this fix targets).
    for ticker, score in [("A", 0.61), ("B", 0.60), ("C", 0.59), ("D", 0.58)]:
        rows.append({"date": "2020-01-02", "ticker": ticker, "raw_score": score})
    # 2020-01-03: thin universe (single name) - must be excluded, not counted as 0.0.
    rows.append({"date": "2020-01-03", "ticker": "A", "raw_score": 0.5})
    return pd.DataFrame(rows)


def test_calibrate_book_confidence_spread_excludes_thin_universe_dates():
    result = calibrate_book_confidence_spread(
        _dataset_frame(), raw_score_column="raw_score", top_n=1, bottom_n=1, percentile=0.0
    )
    assert result["num_dates_used"] == 2
    assert result["num_dates_skipped_thin_universe"] == 1


def test_calibrate_book_confidence_spread_percentile_zero_is_the_minimum_observed_spread():
    result = calibrate_book_confidence_spread(
        _dataset_frame(), raw_score_column="raw_score", top_n=1, bottom_n=1, percentile=0.0
    )
    # 2020-01-01 spread: top pick A (0.9) vs bottom pick D (0.1) -> 0.8.
    # 2020-01-02 spread: top pick A (0.61) vs bottom pick D (0.58) -> 0.03.
    assert result["calibrated_min_rank_confidence_spread"] == pytest.approx(0.03)
    assert result["spread_distribution"]["min"] == pytest.approx(0.03)
    assert result["spread_distribution"]["max"] == pytest.approx(0.8)


def test_calibrate_book_confidence_spread_matches_compute_confidence_spread_directly():
    # Cross-check: the per-date value this function computes for the
    # compressed 2020-01-02 day must be reproducible by calling
    # compute_confidence_spread() directly on the same raw scores/selection -
    # the two can never disagree because they share the same function.
    raw_scores = {"A": 0.61, "B": 0.60, "C": 0.59, "D": 0.58}
    direct = compute_confidence_spread(["A"], ["D"], raw_scores, raw_scores)
    result = calibrate_book_confidence_spread(
        _dataset_frame(), raw_score_column="raw_score", top_n=1, bottom_n=1, percentile=0.0
    )
    assert result["calibrated_min_rank_confidence_spread"] == pytest.approx(direct)


def test_calibrate_book_confidence_spread_empty_dataset_never_raises():
    empty = pd.DataFrame({"date": [], "ticker": [], "raw_score": []})
    result = calibrate_book_confidence_spread(empty, raw_score_column="raw_score", top_n=1, bottom_n=1)
    assert result["calibrated_min_rank_confidence_spread"] == 0.0
    assert result["num_dates_used"] == 0
    assert result["spread_distribution"]["min"] is None


def test_calibrate_book_confidence_spread_nan_scores_excluded_from_a_date():
    rows = [
        {"date": "2020-01-01", "ticker": "A", "raw_score": 0.9},
        {"date": "2020-01-01", "ticker": "B", "raw_score": np.nan},
        {"date": "2020-01-01", "ticker": "C", "raw_score": 0.1},
    ]
    result = calibrate_book_confidence_spread(
        pd.DataFrame(rows), raw_score_column="raw_score", top_n=1, bottom_n=1, percentile=0.0
    )
    assert result["num_dates_used"] == 1
    assert result["calibrated_min_rank_confidence_spread"] == pytest.approx(0.8)
