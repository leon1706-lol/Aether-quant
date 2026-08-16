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
    replay_book_history_reconciliation,
    segment_logged_records_by_run,
    summarize_book_history_reconciliation,
    summarize_book_member_diversion,
    summarize_universe_presence_by_symbol,
    summarize_universe_snapshot_by_security_type,
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


def _logged_record_with_universe(date, allocations, universe):
    return {"date": date, "allocations": allocations, "universe": universe}


def test_reconcile_book_history_date_uses_logged_trading_eligible_when_present():
    # _RAW_SCORES = {"A": 0.9, "B": 0.7, "C": 0.3, "D": 0.1} - D (lowest)
    # is offline's natural bottom1/short pick. Marking D ineligible in the
    # logged universe must exclude it, falling through to the next-lowest
    # eligible name, C.
    logged = _logged_record_with_universe(
        "2020-01-01",
        {"A": _allocation_entry("long", 0.9), "D": _allocation_entry("short", 0.1)},
        {"D": {"trading_eligible": False}},
    )
    result = reconcile_book_history_date(logged, _RAW_SCORES, top_n=1, bottom_n=1)

    assert "D" not in result["offline_symbols"]["short"]
    assert result["offline_symbols"]["short"] == ["C"]


def test_reconcile_book_history_date_defaults_to_eligible_when_universe_absent():
    # No "universe" key at all - byte-identical to pre-fix behavior
    # (every symbol trading_eligible=True).
    logged = _logged_record(
        "2020-01-01",
        {"A": _allocation_entry("long", 0.9), "C": _allocation_entry("short", 0.3)},
    )
    result = reconcile_book_history_date(logged, _RAW_SCORES, top_n=1, bottom_n=1)

    assert result["offline_symbols"]["short"] == ["D"]  # unaffected - D still wins naturally


def test_reconcile_book_history_date_defaults_to_eligible_when_symbol_missing_from_universe():
    # "universe" is present but doesn't mention every symbol - missing
    # symbols still default to eligible, not silently excluded.
    logged = _logged_record_with_universe(
        "2020-01-01",
        {"A": _allocation_entry("long", 0.9), "D": _allocation_entry("short", 0.1)},
        {"A": {"trading_eligible": True}},  # C, D not mentioned at all
    )
    result = reconcile_book_history_date(logged, _RAW_SCORES, top_n=1, bottom_n=1)

    assert result["offline_symbols"]["short"] == ["D"]


def test_replay_book_history_reconciliation_uses_per_date_logged_trading_eligible():
    logged_records = [
        _logged_record_with_universe(
            "2020-01-01", {"A": _allocation_entry("long", 0.9), "C": _allocation_entry("short", 0.3)}, {"D": {"trading_eligible": False}}
        ),
        _logged_record_with_universe(
            "2020-01-02", {"A": _allocation_entry("long", 0.9), "D": _allocation_entry("short", 0.1)}, {}
        ),
    ]
    raw_scores_by_date = {"2020-01-01": _RAW_SCORES, "2020-01-02": _RAW_SCORES}

    results = replay_book_history_reconciliation(logged_records, raw_scores_by_date, top_n=1, bottom_n=1)

    # Date 1: D excluded (ineligible that date) -> offline's natural
    # bottom1 pick falls through to C.
    assert results[0]["offline_symbols"]["short"] == ["C"]
    # Date 2: no universe data logged that date -> D defaults back to
    # eligible and (hysteresis_rank_margin=0.0, no incumbency tolerance)
    # is re-picked as the natural bottom1 - confirms the exclusion is
    # per-date, not carried across dates via held_allocations.
    assert results[1]["offline_symbols"]["short"] == ["D"]


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


# ---------------------------------------------------------------------------
# replay_book_history_reconciliation()
# ---------------------------------------------------------------------------


def test_replay_book_history_reconciliation_reproduces_independent_mode_at_zero_margin():
    # hysteresis_rank_margin=0.0 is build_rank_based_book()'s own no-op
    # default - the replay must degrade to exactly what independent
    # per-date reconciliation already produces for the SAME dates.
    logged_records = [
        _logged_record(
            "2020-01-01",
            {"A": _allocation_entry("long", 0.9, target_weight=0.5), "D": _allocation_entry("short", 0.1, target_weight=-0.5)},
        ),
    ]
    raw_scores_by_date = {"2020-01-01": _RAW_SCORES}

    replayed = replay_book_history_reconciliation(logged_records, raw_scores_by_date, top_n=1, bottom_n=1)
    independent = reconcile_book_history_date(logged_records[0], _RAW_SCORES, top_n=1, bottom_n=1)

    assert replayed == [independent]


def test_replay_book_history_reconciliation_hysteresis_resolves_a_mismatch_independent_mode_flags():
    # Day 1: natural selection is long A / short D, and the live book
    # logs exactly that - held_allocations after day 1 (offline's OWN
    # replay, not the log) becomes {A: long, D: short}.
    #
    # Day 2: raw scores flip so B's percentile rank (1.0) now exceeds A's
    # (0.75) - a from-scratch reselection would swap to B. The live book
    # (logged) instead kept A, exactly what hysteresis_rank_margin=0.3
    # should also do here (cutoff=1.0, keep incumbent A since
    # 0.75 >= 1.0 - 0.3). Independent per-date reconciliation (no
    # previous_allocations) can't see this and flags a false mismatch;
    # the replay, carrying offline's own day-1 selection forward, must
    # NOT flag it.
    day1_scores = {"A": 0.9, "B": 0.7, "C": 0.3, "D": 0.1}
    day2_scores = {"A": 0.7, "B": 0.9, "C": 0.3, "D": 0.1}
    logged_records = [
        _logged_record(
            "2020-01-01",
            {"A": _allocation_entry("long", 0.9), "D": _allocation_entry("short", 0.1)},
        ),
        _logged_record(
            "2020-01-02",
            {"A": _allocation_entry("long", 0.7), "D": _allocation_entry("short", 0.1)},
        ),
    ]
    raw_scores_by_date = {"2020-01-01": day1_scores, "2020-01-02": day2_scores}

    # Independent mode flags day 2 as a divergence: A only-logged, B only-offline.
    independent_day2 = reconcile_book_history_date(logged_records[1], day2_scores, top_n=1, bottom_n=1)
    assert independent_day2["symbols_only_logged"] == ["A"]
    assert independent_day2["symbols_only_offline"] == ["B"]

    # The replay, at a large enough margin, correctly resolves it.
    replayed = replay_book_history_reconciliation(
        logged_records, raw_scores_by_date, top_n=1, bottom_n=1, hysteresis_rank_margin=0.3
    )
    assert len(replayed) == 2
    assert replayed[1]["symbols_matched"] == ["A", "D"]
    assert replayed[1]["symbols_only_logged"] == []
    assert replayed[1]["symbols_only_offline"] == []


def test_replay_book_history_reconciliation_skips_dates_missing_from_raw_scores_by_date():
    logged_records = [
        _logged_record("2020-01-01", {"A": _allocation_entry("long", 0.9), "D": _allocation_entry("short", 0.1)}),
        _logged_record("2020-01-02", {"A": _allocation_entry("long", 0.9), "D": _allocation_entry("short", 0.1)}),
    ]
    # Only day 1 has raw scores available (e.g. day 2 fell outside a
    # caller's re-inference window) - day 2 must be skipped, not KeyError.
    raw_scores_by_date = {"2020-01-01": _RAW_SCORES}

    replayed = replay_book_history_reconciliation(logged_records, raw_scores_by_date, top_n=1, bottom_n=1)

    assert len(replayed) == 1
    assert replayed[0]["date"] == "2020-01-01"


# ---------------------------------------------------------------------------
# summarize_universe_snapshot_by_security_type()
# ---------------------------------------------------------------------------


def _universe_record(date, universe):
    return {"date": date, "allocations": {}, "universe": universe}


def test_summarize_universe_snapshot_no_universe_data_never_raises():
    logged_records = [_logged_record("2020-01-01", {})]  # no "universe" key at all
    summary = summarize_universe_snapshot_by_security_type(logged_records)
    assert summary == {"num_dates_with_universe_data": 0, "by_security_type": {}}


def test_summarize_universe_snapshot_empty_list_never_raises():
    assert summarize_universe_snapshot_by_security_type([]) == {
        "num_dates_with_universe_data": 0,
        "by_security_type": {},
    }


def test_summarize_universe_snapshot_aggregates_by_security_type():
    logged_records = [
        _universe_record(
            "2020-01-01",
            {
                "AAPL": {"raw_rank_score": 0.6, "feature_ready": True, "reason": None, "trading_eligible": True, "security_type": "equity"},
                "BTCUSD": {"raw_rank_score": 0.9, "feature_ready": True, "reason": None, "trading_eligible": True, "security_type": "crypto"},
                "EURUSD": {"raw_rank_score": None, "feature_ready": False, "reason": "Need 2 bars, have 1", "trading_eligible": True, "security_type": "forex"},
            },
        ),
        _universe_record(
            "2020-01-02",
            {
                "AAPL": {"raw_rank_score": 0.4, "feature_ready": True, "reason": None, "trading_eligible": True, "security_type": "equity"},
                "BTCUSD": {"raw_rank_score": 0.8, "feature_ready": True, "reason": None, "trading_eligible": True, "security_type": "crypto"},
            },
        ),
    ]

    summary = summarize_universe_snapshot_by_security_type(logged_records)

    assert summary["num_dates_with_universe_data"] == 2
    assert summary["by_security_type"]["equity"]["num_symbol_dates"] == 2
    assert summary["by_security_type"]["equity"]["mean_raw_rank_score"] == pytest.approx((0.6 + 0.4) / 2)
    assert summary["by_security_type"]["equity"]["feature_ready_rate"] == pytest.approx(1.0)
    assert summary["by_security_type"]["crypto"]["mean_raw_rank_score"] == pytest.approx((0.9 + 0.8) / 2)
    # forex only ever appears once, with a None score - never averaged in as 0.
    assert summary["by_security_type"]["forex"]["num_symbol_dates"] == 1
    assert summary["by_security_type"]["forex"]["mean_raw_rank_score"] is None
    assert summary["by_security_type"]["forex"]["feature_ready_rate"] == pytest.approx(0.0)


def test_summarize_universe_snapshot_dates_without_universe_key_are_not_counted():
    logged_records = [
        _universe_record(
            "2020-01-01",
            {"AAPL": {"raw_rank_score": 0.6, "feature_ready": True, "reason": None, "trading_eligible": True, "security_type": "equity"}},
        ),
        _logged_record("2020-01-02", {}),  # no "universe" key - toggle was presumably off that day
    ]
    summary = summarize_universe_snapshot_by_security_type(logged_records)
    assert summary["num_dates_with_universe_data"] == 1


# ---------------------------------------------------------------------------
# summarize_universe_presence_by_symbol() (V5.3.1)
# ---------------------------------------------------------------------------


def _universe_with_symbols(symbols):
    """Minimal universe payload: just the keys, with a fixed body - only
    key presence/absence matters to summarize_universe_presence_by_symbol()."""
    return {symbol: {"raw_rank_score": 0.5, "feature_ready": True, "trading_eligible": True, "security_type": "equity"} for symbol in symbols}


# ---------------------------------------------------------------------------
# segment_logged_records_by_run()
# ---------------------------------------------------------------------------


def test_segment_logged_records_by_run_empty_list_returns_empty():
    assert segment_logged_records_by_run([]) == []


def test_segment_logged_records_by_run_single_run_returns_one_segment():
    logged_records = [_logged_record(f"2020-01-{i:02d}", {}) for i in (1, 2, 3)]

    segments = segment_logged_records_by_run(logged_records)

    assert len(segments) == 1
    assert segments[0] == logged_records


def test_segment_logged_records_by_run_two_runs_split_on_date_decrease():
    run_0 = [_logged_record("2020-01-01", {}), _logged_record("2020-01-02", {})]
    run_1 = [_logged_record("2020-01-01", {}), _logged_record("2020-01-02", {}), _logged_record("2020-01-03", {})]
    logged_records = run_0 + run_1

    segments = segment_logged_records_by_run(logged_records)

    assert len(segments) == 2
    assert segments[0] == run_0
    assert segments[1] == run_1


def test_segment_logged_records_by_run_missing_date_folds_into_open_run():
    # A record with no "date" key must never itself trigger a boundary,
    # and must not reset previous_date either - the run stays open across it.
    logged_records = [
        _logged_record("2020-01-01", {}),
        {"allocations": {}},  # no "date" key at all
        _logged_record("2020-01-02", {}),
    ]

    segments = segment_logged_records_by_run(logged_records)

    assert len(segments) == 1
    assert segments[0] == logged_records


def test_summarize_universe_presence_empty_list_never_raises():
    assert summarize_universe_presence_by_symbol([]) == {"num_runs_detected": 0, "runs": []}


def test_summarize_universe_presence_no_universe_data_never_raises():
    logged_records = [_logged_record("2020-01-01", {})]
    assert summarize_universe_presence_by_symbol(logged_records) == {"num_runs_detected": 0, "runs": []}


def test_summarize_universe_presence_single_run_computes_absence_rate():
    logged_records = [
        _universe_record("2020-01-01", _universe_with_symbols(["AAPL", "BTCUSD"])),
        _universe_record("2020-01-02", _universe_with_symbols(["AAPL"])),  # BTCUSD absent this date
        _universe_record("2020-01-03", _universe_with_symbols(["AAPL"])),  # BTCUSD absent this date
    ]

    result = summarize_universe_presence_by_symbol(logged_records)

    assert result["num_runs_detected"] == 1
    run = result["runs"][0]
    assert run["num_records"] == 3
    assert run["absence_rate_by_symbol"]["AAPL"] == pytest.approx(0.0)
    assert run["absence_rate_by_symbol"]["BTCUSD"] == pytest.approx(2 / 3)


def test_summarize_universe_presence_segments_by_run_via_date_decrease():
    # Two runs concatenated in one log file: dates go 01-01, 01-02, then
    # BACK to 01-01 - a real date-decrease, the run-boundary signal.
    logged_records = [
        _universe_record("2020-01-01", _universe_with_symbols(["BTCUSD"])),  # run 0: BTCUSD present here
        _universe_record("2020-01-02", {}),  # run 0, no universe data logged that date
        _universe_record("2020-01-01", _universe_with_symbols(["AAPL"])),  # run 1 starts - BTCUSD now absent
        _universe_record("2020-01-02", _universe_with_symbols(["AAPL"])),
    ]

    result = summarize_universe_presence_by_symbol(logged_records)

    assert result["num_runs_detected"] == 2
    run_0, run_1 = result["runs"]
    assert run_0["num_records"] == 1  # only the one universe-bearing record in run 0
    assert "BTCUSD" in run_0["absence_rate_by_symbol"]
    assert run_1["num_records"] == 2
    assert "BTCUSD" not in run_1["absence_rate_by_symbol"]  # never appeared in run 1's universe at all
    assert run_1["absence_rate_by_symbol"]["AAPL"] == pytest.approx(0.0)


def test_summarize_universe_presence_reproduces_the_real_run_segmented_finding():
    # Regression guard for the actual investigation this function shipped
    # to formalize: an old run where a symbol is 100% absent, followed by
    # a newer run where it's always present, must show up as two
    # DIFFERENT per-run absence rates (1.0, then 0.0) - never averaged
    # into one misleading 50% figure.
    old_run = [_universe_record(f"2019-01-{i:02d}", _universe_with_symbols(["AAPL"])) for i in range(1, 4)]
    new_run = [_universe_record(f"2019-01-{i:02d}", _universe_with_symbols(["AAPL", "BTCUSD"])) for i in range(1, 4)]
    logged_records = old_run + new_run

    result = summarize_universe_presence_by_symbol(logged_records)

    assert result["num_runs_detected"] == 2
    old_summary, new_summary = result["runs"]
    assert "BTCUSD" not in old_summary["absence_rate_by_symbol"]  # never seen at all in the old run
    assert new_summary["absence_rate_by_symbol"]["BTCUSD"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# summarize_book_member_diversion() (V5.2.6)
# ---------------------------------------------------------------------------


def _decisions_record(date, decisions):
    return {"date": date, "allocations": {}, "book_member_decisions": decisions}


def test_summarize_book_member_diversion_no_decision_data_never_raises():
    logged_records = [_logged_record("2020-01-01", {})]  # no "book_member_decisions" key at all
    summary = summarize_book_member_diversion(logged_records)
    assert summary == {
        "num_records_with_decisions": 0,
        "total_book_member_dates": 0,
        "action_counts": {},
        "reason_counts": {},
    }


def test_summarize_book_member_diversion_empty_list_never_raises():
    assert summarize_book_member_diversion([]) == {
        "num_records_with_decisions": 0,
        "total_book_member_dates": 0,
        "action_counts": {},
        "reason_counts": {},
    }


def test_summarize_book_member_diversion_counts_actions_and_reasons():
    logged_records = [
        _decisions_record(
            "2020-01-01",
            {
                "A": {"action": "trade", "reasons": ["trading_eligible_directional_signal_above_confidence_threshold"]},
                "B": {"action": "simulate", "reasons": ["liquidity_blocked_insufficient_volume_simulate_instead"]},
            },
        ),
        _decisions_record(
            "2020-01-02",
            {
                "A": {"action": "trade", "reasons": ["trading_eligible_directional_signal_above_confidence_threshold"]},
                "C": {"action": "reduce_risk", "reasons": ["risk_off_regime_overrides_directional_signal"]},
            },
        ),
    ]

    summary = summarize_book_member_diversion(logged_records)

    assert summary["num_records_with_decisions"] == 2
    assert summary["total_book_member_dates"] == 4
    assert summary["action_counts"] == {"trade": 2, "simulate": 1, "reduce_risk": 1}
    assert summary["reason_counts"]["trading_eligible_directional_signal_above_confidence_threshold"] == 2
    assert summary["reason_counts"]["liquidity_blocked_insufficient_volume_simulate_instead"] == 1
    assert summary["reason_counts"]["risk_off_regime_overrides_directional_signal"] == 1


def test_summarize_book_member_diversion_dates_without_decisions_key_are_not_counted():
    logged_records = [
        _decisions_record("2020-01-01", {"A": {"action": "trade", "reasons": []}}),
        _logged_record("2020-01-02", {}),  # no "book_member_decisions" key - toggle was presumably off
    ]
    summary = summarize_book_member_diversion(logged_records)
    assert summary["num_records_with_decisions"] == 1
    assert summary["total_book_member_dates"] == 1


def test_summarize_book_member_diversion_missing_action_degrades_to_unknown():
    logged_records = [_decisions_record("2020-01-01", {"A": {"reasons": []}})]
    summary = summarize_book_member_diversion(logged_records)
    assert summary["action_counts"] == {"unknown": 1}
