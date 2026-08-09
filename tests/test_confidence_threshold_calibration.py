"""Tests for evaluation/confidence_threshold_calibration.py (V5.2.6) -
calibrating phase6.risk.min_confidence_to_trade /
min_confidence_to_trade_book_selected from real data instead of a guessed
constant, mirroring calibrate_book_confidence_spread()'s own discipline
(see tests/test_rank_signal_calibration.py).

Rank values below are the REAL output of
portfolio.rank_signal.cross_sectional_rank_scores() for the given raw
scores (verified directly, not assumed) - ties/boundary handling there is
its own pandas-.rank(pct=True)-style formula, not the simpler
"(count_less + (count_equal+1)/2)/n" convention some other rank helpers
in this codebase use, so every fixture below is annotated with the actual
computed rank/confidence/direction rather than a guessed one.
"""

import pandas as pd
import pytest

from evaluation.confidence_threshold_calibration import calibrate_confidence_threshold


def _dataset_frame():
    rows = []
    # 2020-01-01: 4 names. cross_sectional_rank_scores({A:0.9,B:0.7,C:0.3,D:0.1})
    # == {A: 1.0, B: 0.75, C: 0.5, D: 0.25} (verified directly).
    # confidence = min(1, abs(rank-0.5)*2): A=1.0, B=0.5, C=0.0, D=0.5.
    # direction = +1 if rank>=0.5 else -1: A/B/C=+1 (C's rank is exactly
    # 0.5, the >= boundary), D=-1.
    # top_n=1/bottom_n=1 book-selects only A (long, highest rank) and D
    # (short, lowest rank) - B/C are scored but never book-selected.
    # forward_return chosen so every row's DIRECTIONAL edge is +0.05 at
    # cost=0.0 (i.e. every row "pays"):
    for ticker, score, forward_return in [
        ("A", 0.9, 0.05), ("B", 0.7, 0.05), ("C", 0.3, 0.05), ("D", 0.1, -0.05),
    ]:
        rows.append({"date": "2020-01-01", "ticker": ticker, "raw_score": score, "forward_return": forward_return})
    # 2020-01-02: thin universe (single name) - must be excluded.
    rows.append({"date": "2020-01-02", "ticker": "A", "raw_score": 0.5, "forward_return": 0.05})
    return pd.DataFrame(rows)


def test_calibrate_confidence_threshold_excludes_thin_universe_dates():
    result = calibrate_confidence_threshold(
        _dataset_frame(), raw_score_column="raw_score", forward_return_column="forward_return",
        top_n=1, bottom_n=1, round_trip_cost_fraction=0.0, percentile=0.0,
    )
    assert result["num_dates_skipped_thin_universe"] == 1


def test_calibrate_confidence_threshold_percentile_zero_is_the_minimum_paying_confidence():
    result = calibrate_confidence_threshold(
        _dataset_frame(), raw_score_column="raw_score", forward_return_column="forward_return",
        top_n=1, bottom_n=1, round_trip_cost_fraction=0.0, percentile=0.0,
    )
    # All 4 rows pay at cost=0.0; confidences are 1.0(A)/0.5(B)/0.0(C)/0.5(D).
    assert result["num_rows_used"] == 4
    assert result["calibrated_min_confidence_to_trade"] == pytest.approx(0.0)
    assert result["confidence_distribution"]["min"] == pytest.approx(0.0)
    assert result["confidence_distribution"]["max"] == pytest.approx(1.0)


def test_calibrate_confidence_threshold_book_selected_split_produces_two_thresholds():
    result = calibrate_confidence_threshold(
        _dataset_frame(), raw_score_column="raw_score", forward_return_column="forward_return",
        top_n=1, bottom_n=1, round_trip_cost_fraction=0.0, percentile=0.0,
    )
    # Only A (confidence 1.0) and D (confidence 0.5) are ever book-selected
    # (top_n=1/bottom_n=1) - the book-selected floor (min=0.5) is strictly
    # higher than the general one (dragged down by C's confidence 0.0,
    # which is never book-selected).
    assert result["num_rows_used_book_selected"] == 2
    assert result["calibrated_min_confidence_to_trade_book_selected"] == pytest.approx(0.5)
    assert result["calibrated_min_confidence_to_trade_book_selected"] > result["calibrated_min_confidence_to_trade"]


def test_calibrate_confidence_threshold_high_cost_excludes_all_rows():
    # A round-trip cost bigger than every row's edge (0.05) means nothing
    # "pays" - both distributions degrade to the empty/no-op result,
    # never raise.
    result = calibrate_confidence_threshold(
        _dataset_frame(), raw_score_column="raw_score", forward_return_column="forward_return",
        top_n=1, bottom_n=1, round_trip_cost_fraction=0.10, percentile=0.0,
    )
    assert result["num_rows_used"] == 0
    assert result["num_rows_used_book_selected"] == 0
    assert result["calibrated_min_confidence_to_trade"] == 0.0
    assert result["calibrated_min_confidence_to_trade_book_selected"] == 0.0
    assert result["confidence_distribution"]["min"] is None
    assert result["confidence_distribution_book_selected"]["min"] is None


def test_calibrate_confidence_threshold_empty_dataset_never_raises():
    empty = pd.DataFrame({"date": [], "ticker": [], "raw_score": [], "forward_return": []})
    result = calibrate_confidence_threshold(
        empty, raw_score_column="raw_score", forward_return_column="forward_return", top_n=1, bottom_n=1,
    )
    assert result["calibrated_min_confidence_to_trade"] == 0.0
    assert result["calibrated_min_confidence_to_trade_book_selected"] == 0.0
    assert result["num_rows_used"] == 0
    assert result["confidence_distribution"]["min"] is None


def test_calibrate_confidence_threshold_non_paying_rows_excluded_from_distribution():
    # cross_sectional_rank_scores({A:0.9,B:0.1}) == {A: 1.0, B: 0.5}
    # (verified directly) - A's direction is +1 (rank>=0.5), B's is also
    # +1 (rank exactly 0.5, the >= boundary).
    rows = [
        {"date": "2020-01-01", "ticker": "A", "raw_score": 0.9, "forward_return": -0.05},  # direction+1, edge=-0.05: does NOT pay
        {"date": "2020-01-01", "ticker": "B", "raw_score": 0.1, "forward_return": 0.05},   # direction+1, edge=+0.05: pays
    ]
    result = calibrate_confidence_threshold(
        pd.DataFrame(rows), raw_score_column="raw_score", forward_return_column="forward_return",
        top_n=1, bottom_n=1, round_trip_cost_fraction=0.0, percentile=0.0,
    )
    assert result["num_rows_used"] == 1
    # Only B paid, and B's own confidence (abs(0.5-0.5)*2) is 0.0 - proves
    # A's high confidence (1.0) never leaked into the distribution despite
    # A being the "better-looking" row on confidence alone.
    assert result["calibrated_min_confidence_to_trade"] == pytest.approx(0.0)
