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
    reconcile_book_history_date,
    summarize_book_history_reconciliation,
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


# ---------------------------------------------------------------------------
# reconcile_book_history_date() / summarize_book_history_reconciliation()
# ---------------------------------------------------------------------------


def _allocation_entry(role, raw_rank_score, target_weight=None):
    return {
        "role": role,
        "book_role_multiplier": 1.0 if role == "long" else -1.0,
        "predicted_rank_20d": raw_rank_score,
        "rank_head": "blend",
        "raw_rank_score": raw_rank_score,
        "target_weight": target_weight,
        "sector": "Unknown",
    }


def _logged_record(date, allocations):
    return {"date": date, "allocations": allocations}


_RAW_SCORES = {"A": 0.9, "B": 0.7, "C": 0.3, "D": 0.1}  # natural top1/bottom1 -> long A, short D


def test_reconcile_book_history_date_exact_match():
    logged = _logged_record(
        "2020-01-01",
        {"A": _allocation_entry("long", 0.9, target_weight=0.5), "D": _allocation_entry("short", 0.1, target_weight=-0.5)},
    )
    result = reconcile_book_history_date(logged, _RAW_SCORES, top_n=1, bottom_n=1)

    assert result["symbols_matched"] == ["A", "D"]
    assert result["symbols_only_logged"] == []
    assert result["symbols_only_offline"] == []
    assert result["role_mismatches"] == []
    assert result["overlap_fraction"] == pytest.approx(1.0)
    assert result["per_symbol_deltas"]["A"]["raw_score_delta"] == pytest.approx(0.0)
    # naive offline equal weight for a single-name long leg is 1.0; logged was 0.5.
    assert result["per_symbol_deltas"]["A"]["weight_delta"] == pytest.approx(0.5 - 1.0)
    assert result["per_symbol_deltas"]["D"]["weight_delta"] == pytest.approx(-0.5 - (-1.0))


def test_reconcile_book_history_date_symbol_selection_divergence():
    # Live selected C as the short leg (e.g. hysteresis kept an incumbent);
    # natural offline re-derivation would pick D instead.
    logged = _logged_record(
        "2020-01-01",
        {"A": _allocation_entry("long", 0.9), "C": _allocation_entry("short", 0.3)},
    )
    result = reconcile_book_history_date(logged, _RAW_SCORES, top_n=1, bottom_n=1)

    assert result["symbols_matched"] == ["A"]
    assert result["symbols_only_logged"] == ["C"]
    assert result["symbols_only_offline"] == ["D"]
    assert result["role_mismatches"] == []
    assert result["overlap_fraction"] == pytest.approx(1 / 3)


def test_reconcile_book_history_date_role_mismatch():
    # Live recorded A as short even though its raw score is the highest -
    # offline's natural selection puts A on the long leg instead.
    logged = _logged_record(
        "2020-01-01",
        {"A": _allocation_entry("short", 0.9), "D": _allocation_entry("long", 0.1)},
    )
    result = reconcile_book_history_date(logged, _RAW_SCORES, top_n=1, bottom_n=1)

    assert set(result["symbols_matched"]) == {"A", "D"}
    assert result["role_mismatches"] == ["A", "D"]


def test_reconcile_book_history_date_missing_target_weight_never_crashes():
    logged = _logged_record(
        "2020-01-01",
        {"A": _allocation_entry("long", 0.9, target_weight=None), "D": _allocation_entry("short", 0.1, target_weight=None)},
    )
    result = reconcile_book_history_date(logged, _RAW_SCORES, top_n=1, bottom_n=1)

    assert result["per_symbol_deltas"]["A"]["weight_delta"] is None
    assert result["per_symbol_deltas"]["D"]["weight_delta"] is None
    assert result["per_symbol_deltas"]["A"]["raw_score_delta"] == pytest.approx(0.0)


def test_summarize_book_history_reconciliation_empty_list_never_raises():
    summary = summarize_book_history_reconciliation([])
    assert summary == {
        "num_dates": 0,
        "num_dates_exact_match": 0,
        "mean_overlap_fraction": None,
        "mean_raw_score_delta_abs": None,
        "mean_weight_delta_abs": None,
        "num_dates_with_weight_logged": 0,
        "num_symbols_only_logged_total": 0,
        "num_symbols_only_offline_total": 0,
    }


def test_summarize_book_history_reconciliation_aggregates_across_dates():
    exact_match = reconcile_book_history_date(
        _logged_record(
            "2020-01-01",
            {"A": _allocation_entry("long", 0.9, target_weight=0.5), "D": _allocation_entry("short", 0.1, target_weight=-0.5)},
        ),
        _RAW_SCORES,
        top_n=1,
        bottom_n=1,
    )
    divergent = reconcile_book_history_date(
        _logged_record("2020-01-02", {"A": _allocation_entry("long", 0.9), "C": _allocation_entry("short", 0.3)}),
        _RAW_SCORES,
        top_n=1,
        bottom_n=1,
    )

    summary = summarize_book_history_reconciliation([exact_match, divergent])

    assert summary["num_dates"] == 2
    assert summary["num_dates_exact_match"] == 1
    assert summary["num_dates_with_weight_logged"] == 1  # only the first date logged non-None weights
    assert summary["mean_raw_score_delta_abs"] == pytest.approx(0.0)
    assert summary["num_symbols_only_logged_total"] == 1  # "C" on 2020-01-02
    assert summary["num_symbols_only_offline_total"] == 1  # "D" on 2020-01-02
    assert summary["mean_overlap_fraction"] == pytest.approx((1.0 + 1 / 3) / 2)
