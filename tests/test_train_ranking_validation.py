"""Tests for train.py's Phase 2 (5/10 -> 9/10 roadmap) validation-rigor
additions: purged_embargoed_folds(), split_into_non_overlapping_eras(),
bootstrap_ic_confidence_interval(), assess_ranking_quality(), and the
assess_ranking_quality_from_predictions() orchestrator. See
development/Changelog.md for the promotion-criterion background these
close the gap on (rank_20d's non-overlapping-date t-stat of 1.20 not yet
independently significant vs. the full series' 4.40).

Conventions match the rest of this repo's train.py test coverage: no test
classes, module-level helpers, plain dicts/tensors.
"""

import numpy as np
import pandas as pd
import pytest
import torch

from train import (
    assess_ranking_quality,
    assess_ranking_quality_from_predictions,
    bootstrap_ic_confidence_interval,
    purged_embargoed_folds,
    split_into_non_overlapping_eras,
)


# ---------------------------------------------------------------------------
# bootstrap_ic_confidence_interval
# ---------------------------------------------------------------------------


def test_bootstrap_ic_confidence_interval_degenerate_with_fewer_than_two_values():
    result = bootstrap_ic_confidence_interval([0.05])

    assert result["lower_bound"] == 0.0
    assert result["upper_bound"] == 0.0
    assert result["n_resamples"] == 0
    assert result["num_observations"] == 1


def test_bootstrap_ic_confidence_interval_empty_is_degenerate_not_raise():
    result = bootstrap_ic_confidence_interval([])

    assert result["lower_bound"] == 0.0
    assert result["num_observations"] == 0


def test_bootstrap_ic_confidence_interval_bounds_bracket_the_mean():
    ic_values = [0.05, 0.03, 0.07, 0.02, 0.06, 0.04, 0.08, 0.01]

    result = bootstrap_ic_confidence_interval(ic_values, n_resamples=500)

    assert result["lower_bound"] <= result["mean_ic"] <= result["upper_bound"]
    assert result["num_observations"] == len(ic_values)


def test_bootstrap_ic_confidence_interval_is_deterministic_for_fixed_seed():
    ic_values = [0.05, -0.02, 0.07, 0.01, 0.03]

    first = bootstrap_ic_confidence_interval(ic_values, n_resamples=300, seed=7)
    second = bootstrap_ic_confidence_interval(ic_values, n_resamples=300, seed=7)

    assert first == second


def test_bootstrap_ic_confidence_interval_all_positive_values_gives_positive_lower_bound():
    ic_values = [0.05, 0.06, 0.04, 0.07, 0.05, 0.06, 0.05, 0.04, 0.06, 0.05]

    result = bootstrap_ic_confidence_interval(ic_values, n_resamples=1000)

    # Every observation is comfortably positive with low variance - the
    # resampled mean should never dip to/below zero.
    assert result["lower_bound"] > 0.0


def test_bootstrap_ic_confidence_interval_mixed_sign_wide_interval_crosses_zero():
    ic_values = [0.20, -0.20, 0.15, -0.15, 0.10, -0.10]

    result = bootstrap_ic_confidence_interval(ic_values, n_resamples=1000)

    assert result["lower_bound"] < 0.0 < result["upper_bound"]


# ---------------------------------------------------------------------------
# purged_embargoed_folds
# ---------------------------------------------------------------------------


def _daily_dates(n_days: int, start: str = "2020-01-01") -> np.ndarray:
    return pd.date_range(start, periods=n_days, freq="D").to_numpy()


def test_purged_embargoed_folds_returns_empty_when_fewer_unique_dates_than_folds():
    dates = _daily_dates(3)

    folds = purged_embargoed_folds(dates, n_folds=5, horizon_days=1)

    assert folds == []


def test_purged_embargoed_folds_produces_requested_fold_count():
    dates = _daily_dates(50)

    folds = purged_embargoed_folds(dates, n_folds=5, horizon_days=1)

    assert len(folds) == 5


def test_purged_embargoed_folds_train_and_validation_indices_are_disjoint():
    dates = _daily_dates(60)

    folds = purged_embargoed_folds(dates, n_folds=6, horizon_days=5, embargo_days=5)

    for train_indices, validation_indices in folds:
        assert set(train_indices.tolist()).isdisjoint(set(validation_indices.tolist()))


def test_purged_embargoed_folds_purges_rows_whose_forward_window_overlaps_validation():
    dates = _daily_dates(30)
    horizon_days = 5

    folds = purged_embargoed_folds(dates, n_folds=3, horizon_days=horizon_days, embargo_days=0)
    # Second fold's validation window starts right after the first fold -
    # the horizon_days rows immediately preceding it must be purged from
    # training (their own forward-return label would reach into it).
    _, validation_indices = folds[1]
    validation_start = dates[validation_indices[0]]
    purge_start = validation_start - pd.Timedelta(days=horizon_days)
    purged_dates = {d for d in dates if purge_start <= d < validation_start}
    train_indices, _ = folds[1]
    train_dates = set(dates[train_indices].tolist())

    assert not (purged_dates & train_dates)


def test_purged_embargoed_folds_embargoes_rows_immediately_after_validation():
    dates = _daily_dates(30)
    embargo_days = 4

    folds = purged_embargoed_folds(dates, n_folds=3, horizon_days=1, embargo_days=embargo_days)
    train_indices, validation_indices = folds[0]
    validation_end = dates[validation_indices[-1]]
    embargo_end = validation_end + pd.Timedelta(days=embargo_days)
    embargoed_dates = {d for d in dates if validation_end < d <= embargo_end}
    train_dates = set(dates[train_indices].tolist())

    assert not (embargoed_dates & train_dates)


def test_purged_embargoed_folds_zero_embargo_matches_pure_purge():
    dates = _daily_dates(40)

    folds_no_embargo = purged_embargoed_folds(dates, n_folds=4, horizon_days=3, embargo_days=0)

    assert len(folds_no_embargo) == 4
    for train_indices, validation_indices in folds_no_embargo:
        assert len(train_indices) > 0
        assert len(validation_indices) > 0


# ---------------------------------------------------------------------------
# split_into_non_overlapping_eras
# ---------------------------------------------------------------------------


def test_split_into_non_overlapping_eras_empty_dates_returns_empty():
    assert split_into_non_overlapping_eras(np.array([]), era_length_days=90) == []


def test_split_into_non_overlapping_eras_covers_full_range_without_gaps():
    dates = _daily_dates(200)

    eras = split_into_non_overlapping_eras(dates, era_length_days=90)

    assert eras[0][0] == dates.min()
    assert eras[-1][1] == dates.max()
    # Each era must start exactly one day after the previous one ends.
    for (_, prev_end), (next_start, _) in zip(eras, eras[1:]):
        assert next_start == prev_end + pd.Timedelta(days=1)


def test_split_into_non_overlapping_eras_last_era_may_be_shorter():
    dates = _daily_dates(100)

    eras = split_into_non_overlapping_eras(dates, era_length_days=90)

    assert len(eras) == 2
    first_length = (eras[0][1] - eras[0][0]).days + 1
    assert first_length == 90
    last_length = (eras[1][1] - eras[1][0]).days + 1
    assert last_length == 10


def test_split_into_non_overlapping_eras_single_era_when_range_shorter_than_era_length():
    dates = _daily_dates(30)

    eras = split_into_non_overlapping_eras(dates, era_length_days=90)

    assert len(eras) == 1
    assert eras[0] == (dates.min(), dates.max())


def test_split_into_non_overlapping_eras_accepts_plain_string_dates():
    # Regression test: real callers (assess_ranking_quality_from_predictions(),
    # fed train_multitask.py/train_sequence.py's frame["date"]) pass plain
    # string dates, not Timestamp/datetime64 - build_feature_dataset()
    # stringifies the date column before any trainer reads it. A prior
    # version of this function raised "can only concatenate str to str"
    # (era_start + Timedelta) when given raw strings - caught via a real
    # train_multitask.py run, not a synthetic unit test alone.
    string_dates = [f"2020-01-{day:02d}" for day in range(1, 31)] * 2  # duplicated, like one row per asset per date

    eras = split_into_non_overlapping_eras(string_dates, era_length_days=90)

    assert len(eras) == 1
    assert eras[0][0] == pd.Timestamp("2020-01-01")
    assert eras[0][1] == pd.Timestamp("2020-01-30")


# ---------------------------------------------------------------------------
# assess_ranking_quality
# ---------------------------------------------------------------------------


def _promotable_gate_config() -> dict:
    return {
        "phase1": {
            "target": {
                "ranking": {
                    "promotion_gate": {
                        "min_non_overlapping_t_stat": 2.0,
                        "min_bootstrap_ci_lower": 0.0,
                        "ranking_watchlist_margin": 0.3,
                    }
                }
            }
        }
    }


def test_assess_ranking_quality_promotable_when_all_gates_clear():
    non_overlapping_ic = {"mean_ic": 0.05, "t_stat": 3.0}
    bootstrap_result = {"lower_bound": 0.01, "upper_bound": 0.09}
    per_era_mean_ics = [0.04, 0.05, 0.06]

    result = assess_ranking_quality(non_overlapping_ic, bootstrap_result, per_era_mean_ics, _promotable_gate_config())

    assert result["quality_status"] == "promotable"
    assert result["promotion_eligible"] is True
    assert result["failures"] == []


def test_assess_ranking_quality_fails_on_low_t_stat():
    # Mirrors the real result this gate exists to catch: rank_20d's actual
    # non-overlapping-date t-stat was 1.20, well under the 2.0 bar.
    non_overlapping_ic = {"mean_ic": 0.073, "t_stat": 1.20}
    bootstrap_result = {"lower_bound": 0.01, "upper_bound": 0.09}
    per_era_mean_ics = [0.07, 0.08]

    result = assess_ranking_quality(non_overlapping_ic, bootstrap_result, per_era_mean_ics, _promotable_gate_config())

    assert "non_overlapping_t_stat_below_gate" in result["failures"]
    assert result["quality_status"] == "not_promotable"
    assert result["promotion_eligible"] is False


def test_assess_ranking_quality_fails_on_negative_bootstrap_lower_bound():
    non_overlapping_ic = {"mean_ic": 0.05, "t_stat": 3.0}
    bootstrap_result = {"lower_bound": -0.01, "upper_bound": 0.09}
    per_era_mean_ics = [0.04, 0.05]

    result = assess_ranking_quality(non_overlapping_ic, bootstrap_result, per_era_mean_ics, _promotable_gate_config())

    assert "bootstrap_ci_lower_bound_below_gate" in result["failures"]
    assert result["quality_status"] == "not_promotable"


def test_assess_ranking_quality_fails_on_single_opposite_sign_era():
    non_overlapping_ic = {"mean_ic": 0.05, "t_stat": 3.0}
    bootstrap_result = {"lower_bound": 0.01, "upper_bound": 0.09}
    per_era_mean_ics = [0.06, 0.07, -0.02]  # one era flips sign

    result = assess_ranking_quality(non_overlapping_ic, bootstrap_result, per_era_mean_ics, _promotable_gate_config())

    assert "era_sign_instability" in result["failures"]
    assert result["observed"]["num_opposite_sign_eras"] == 1
    assert result["quality_status"] == "not_promotable"


def test_assess_ranking_quality_watchlist_when_t_stat_near_gate():
    non_overlapping_ic = {"mean_ic": 0.05, "t_stat": 2.1}  # within watchlist_margin (0.3) of 2.0
    bootstrap_result = {"lower_bound": 0.01, "upper_bound": 0.09}
    per_era_mean_ics = [0.05, 0.05]

    result = assess_ranking_quality(non_overlapping_ic, bootstrap_result, per_era_mean_ics, _promotable_gate_config())

    assert result["quality_status"] == "watchlist"
    assert result["promotion_eligible"] is True  # watchlist still gating_eligible-equivalent
    assert "non_overlapping_t_stat_near_gate" in result["near_misses"]


def test_assess_ranking_quality_missing_config_falls_back_to_defaults():
    non_overlapping_ic = {"mean_ic": 0.05, "t_stat": 3.0}
    bootstrap_result = {"lower_bound": 0.01, "upper_bound": 0.09}

    result = assess_ranking_quality(non_overlapping_ic, bootstrap_result, [], {})

    assert result["thresholds"]["min_non_overlapping_t_stat"] == 2.0
    assert result["thresholds"]["min_bootstrap_ci_lower"] == 0.0


# ---------------------------------------------------------------------------
# assess_ranking_quality_from_predictions (orchestrator)
# ---------------------------------------------------------------------------


def test_assess_ranking_quality_from_predictions_end_to_end_promotable_signal():
    # A strong, but not perfectly deterministic, non-overlapping-date signal
    # across two eras should clear every gate. Perfect per-date correlation
    # every single day would give zero IC variance and an undefined (0.0)
    # t-stat - real noise is needed for a meaningful t-stat > 2.
    rng = np.random.default_rng(3)
    dates = np.array(
        [d for day in range(1, 41) for d in [f"2020-01-{day:02d}" if day <= 31 else f"2020-02-{day - 31:02d}"] * 5],
        dtype="datetime64[D]",
    )
    base_targets = np.tile([1.0, 0.75, 0.5, 0.25, 0.0], 40)
    noise = rng.normal(0.0, 0.05, size=len(base_targets))
    predictions = torch.tensor(base_targets + noise, dtype=torch.float32)
    targets = torch.tensor(base_targets, dtype=torch.float32)
    config = _promotable_gate_config()
    config["phase1"]["target"]["ranking"]["promotion_gate"]["era_length_days"] = 20

    result = assess_ranking_quality_from_predictions(
        predictions, targets, dates, non_overlapping_stride=1, config=config
    )

    assert result["quality_status"] == "promotable"
    assert result["observed"]["num_eras"] >= 2


def test_assess_ranking_quality_from_predictions_weak_noisy_signal_not_promotable():
    dates = np.array(
        [d for day in range(1, 11) for d in [f"2020-01-{day:02d}"] * 3],
        dtype="datetime64[D]",
    )
    rng = np.random.default_rng(0)
    predictions = torch.tensor(rng.uniform(0, 1, size=30), dtype=torch.float32)
    targets = torch.tensor(np.tile([1.0, 0.5, 0.0], 10), dtype=torch.float32)
    config = _promotable_gate_config()
    config["phase1"]["target"]["ranking"]["promotion_gate"]["era_length_days"] = 5

    result = assess_ranking_quality_from_predictions(
        predictions, targets, dates, non_overlapping_stride=1, config=config
    )

    assert result["quality_status"] == "not_promotable"


def test_assess_ranking_quality_from_predictions_accepts_plain_string_dates_from_a_dataframe():
    # Regression test for a real failure caught during the combined Phase
    # 1/2/5 retrain: train_multitask.py/train_sequence.py pass
    # np.asarray(frame["date"]) where frame["date"] holds plain Python
    # strings (build_feature_dataset() stringifies the date column before
    # any trainer reads it) - this produces a numpy `object` array of str,
    # NOT datetime64, unlike this file's other end-to-end tests above
    # (which use dtype="datetime64[D]" and never exercised this path).
    # Previously raised "can only concatenate str (not Timedelta) to str"
    # inside split_into_non_overlapping_eras().
    dates_series = pd.Series([f"2020-01-{day:02d}" for day in range(1, 21) for _ in range(3)])
    dates = np.asarray(dates_series)
    assert dates.dtype == object  # confirms this test reproduces the real shape, not datetime64

    rng = np.random.default_rng(1)
    base_targets = np.tile([1.0, 0.5, 0.0], 20)
    predictions = torch.tensor(base_targets + rng.normal(0.0, 0.05, size=len(base_targets)), dtype=torch.float32)
    targets = torch.tensor(base_targets, dtype=torch.float32)
    config = _promotable_gate_config()
    config["phase1"]["target"]["ranking"]["promotion_gate"]["era_length_days"] = 10

    result = assess_ranking_quality_from_predictions(
        predictions, targets, dates, non_overlapping_stride=1, config=config
    )

    assert result["quality_status"] in {"promotable", "watchlist", "not_promotable"}  # must not raise
