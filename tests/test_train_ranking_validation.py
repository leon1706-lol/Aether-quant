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
    aggregate_seed_ensemble_rank_ic,
    assess_ranking_quality,
    assess_ranking_quality_from_predictions,
    average_ensemble_predictions,
    bootstrap_ic_confidence_interval,
    compute_purged_cv_rank_ic_diagnostic,
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


# ---------------------------------------------------------------------------
# average_ensemble_predictions() (Stage 4 of the rank-pivot roadmap:
# seed-ensembling - see the function's own docstring for why this is
# PREDICTION averaging, never weight averaging)
# ---------------------------------------------------------------------------


def test_average_ensemble_predictions_two_seeds_is_elementwise_mean():
    seed_a = torch.tensor([0.2, 0.4, 0.6, 0.8])
    seed_b = torch.tensor([0.4, 0.6, 0.8, 1.0])

    ensembled = average_ensemble_predictions([seed_a, seed_b])

    assert torch.allclose(ensembled, torch.tensor([0.3, 0.5, 0.7, 0.9]))


def test_average_ensemble_predictions_three_seeds():
    seed_a = torch.tensor([1.0, 1.0])
    seed_b = torch.tensor([2.0, 4.0])
    seed_c = torch.tensor([3.0, 7.0])

    ensembled = average_ensemble_predictions([seed_a, seed_b, seed_c])

    assert torch.allclose(ensembled, torch.tensor([2.0, 4.0]))


def test_average_ensemble_predictions_single_seed_is_a_no_op():
    seed_a = torch.tensor([0.1, 0.5, 0.9])

    ensembled = average_ensemble_predictions([seed_a])

    assert torch.allclose(ensembled, seed_a)


def test_average_ensemble_predictions_is_deterministic():
    seeds = [torch.tensor([0.1, 0.2]), torch.tensor([0.3, 0.4]), torch.tensor([0.5, 0.6])]

    first_call = average_ensemble_predictions(seeds)
    second_call = average_ensemble_predictions(seeds)

    assert torch.equal(first_call, second_call)


def test_average_ensemble_predictions_empty_list_raises():
    with pytest.raises(ValueError):
        average_ensemble_predictions([])


def test_average_ensemble_predictions_order_independent():
    seed_a = torch.tensor([1.0, 2.0])
    seed_b = torch.tensor([3.0, 4.0])
    seed_c = torch.tensor([5.0, 6.0])

    forward_order = average_ensemble_predictions([seed_a, seed_b, seed_c])
    reverse_order = average_ensemble_predictions([seed_c, seed_b, seed_a])

    assert torch.allclose(forward_order, reverse_order)


# ---------------------------------------------------------------------------
# aggregate_seed_ensemble_rank_ic() (Stage 4 of the rank-pivot roadmap: the
# evaluation half of seed-ensembling, pairing average_ensemble_predictions()
# with compute_rank_ic())
# ---------------------------------------------------------------------------


def _rank_ic_dates_and_targets():
    """5 assets/date x 20 dates, base cross-sectional rank pattern repeated
    every date - same shape convention as this file's other end-to-end
    rank-IC tests above."""
    dates = np.array([d for day in range(1, 21) for d in [f"2020-01-{day:02d}"] * 5], dtype="datetime64[D]")
    base_targets = np.tile([1.0, 0.75, 0.5, 0.25, 0.0], 20)
    targets = torch.tensor(base_targets, dtype=torch.float32)
    return dates, targets, base_targets


def test_aggregate_seed_ensemble_rank_ic_structure_has_one_entry_per_seed():
    dates, targets, base_targets = _rank_ic_dates_and_targets()
    rng = np.random.default_rng(1)
    predictions_by_seed = {
        42: torch.tensor(base_targets + rng.normal(0.0, 0.05, size=len(base_targets)), dtype=torch.float32),
        43: torch.tensor(base_targets + rng.normal(0.0, 0.05, size=len(base_targets)), dtype=torch.float32),
        44: torch.tensor(base_targets + rng.normal(0.0, 0.05, size=len(base_targets)), dtype=torch.float32),
    }

    result = aggregate_seed_ensemble_rank_ic(predictions_by_seed, targets, dates, non_overlapping_stride=1)

    assert result["seeds"] == [42, 43, 44]
    assert set(result["per_seed_rank_ic"].keys()) == {"42", "43", "44"}
    for seed_ic in result["per_seed_rank_ic"].values():
        assert "mean_ic" in seed_ic and "t_stat" in seed_ic
    assert "mean_ic" in result["ensemble_rank_ic"]


def test_aggregate_seed_ensemble_rank_ic_single_seed_ensemble_matches_that_seed():
    # Averaging exactly one seed's predictions is a no-op (see
    # average_ensemble_predictions()'s own single-seed test) - the ensemble
    # IC must therefore be identical to that one seed's own IC.
    dates, targets, base_targets = _rank_ic_dates_and_targets()
    rng = np.random.default_rng(2)
    only_seed_predictions = torch.tensor(base_targets + rng.normal(0.0, 0.05, size=len(base_targets)), dtype=torch.float32)

    result = aggregate_seed_ensemble_rank_ic({42: only_seed_predictions}, targets, dates, non_overlapping_stride=1)

    assert result["ensemble_rank_ic"]["mean_ic"] == pytest.approx(result["per_seed_rank_ic"]["42"]["mean_ic"])


def test_aggregate_seed_ensemble_rank_ic_averaging_reduces_noise_variance():
    # The core claim ensembling makes: averaging several independently-
    # noisy-but-unbiased seeds around the same true signal should reduce
    # the ensemble's IC variability relative to the average of the
    # individual seeds' own variability - not necessarily raise every
    # single seed's mean_ic, but the ensemble's std_ic should be no worse
    # than a typical individual seed's.
    dates, targets, base_targets = _rank_ic_dates_and_targets()
    rng = np.random.default_rng(7)
    predictions_by_seed = {
        seed: torch.tensor(base_targets + rng.normal(0.0, 0.15, size=len(base_targets)), dtype=torch.float32)
        for seed in (42, 43, 44, 45, 46)
    }

    result = aggregate_seed_ensemble_rank_ic(predictions_by_seed, targets, dates, non_overlapping_stride=1)

    mean_individual_std = np.mean([ic["std_ic"] for ic in result["per_seed_rank_ic"].values()])
    assert result["ensemble_rank_ic"]["std_ic"] <= mean_individual_std


def test_aggregate_seed_ensemble_rank_ic_empty_raises():
    dates, targets, _ = _rank_ic_dates_and_targets()

    with pytest.raises(ValueError):
        aggregate_seed_ensemble_rank_ic({}, targets, dates)


# ---------------------------------------------------------------------------
# compute_purged_cv_rank_ic_diagnostic() (Stage 5 of the rank-pivot roadmap:
# the actual executed diagnostic behind phase1.target.ranking.purged_cv -
# purged_embargoed_folds() previously had zero call sites in production code)
# ---------------------------------------------------------------------------


def _purged_cv_dates_and_predictions(n_days: int = 40, assets_per_day: int = 5, noise_std: float = 0.05, seed: int = 5):
    dates = np.array(
        [
            d
            for day_offset in range(n_days)
            for d in [np.datetime64("2020-01-01") + np.timedelta64(day_offset, "D")] * assets_per_day
        ]
    )
    base_targets = np.tile(np.linspace(0.0, 1.0, assets_per_day), n_days)
    rng = np.random.default_rng(seed)
    predictions = torch.tensor(base_targets + rng.normal(0.0, noise_std, size=len(base_targets)), dtype=torch.float32)
    targets = torch.tensor(base_targets, dtype=torch.float32)
    return dates, predictions, targets


def test_compute_purged_cv_rank_ic_diagnostic_structure():
    dates, predictions, targets = _purged_cv_dates_and_predictions()

    result = compute_purged_cv_rank_ic_diagnostic(predictions, targets, dates, n_folds=5, horizon_days=1, embargo_days=1)

    assert result["n_folds_requested"] == 5
    assert result["n_folds_with_data"] == len(result["per_fold"])
    assert result["n_folds_with_data"] > 0
    for fold in result["per_fold"]:
        assert "fold" in fold and "mean_ic" in fold and "t_stat" in fold
    # A clean, strongly-correlated signal (small noise) should produce a
    # positive aggregate IC across folds.
    assert result["mean_ic_across_folds"] > 0.0


def test_compute_purged_cv_rank_ic_diagnostic_too_few_dates_is_empty_not_error():
    dates, predictions, targets = _purged_cv_dates_and_predictions(n_days=3, assets_per_day=5)

    result = compute_purged_cv_rank_ic_diagnostic(predictions, targets, dates, n_folds=5, horizon_days=1, embargo_days=0)

    assert result["per_fold"] == []
    assert result["n_folds_with_data"] == 0
    assert result["mean_ic_across_folds"] == 0.0
    assert result["any_fold_opposite_sign"] is False


def test_compute_purged_cv_rank_ic_diagnostic_detects_opposite_sign_folds():
    # Construct predictions that correlate POSITIVELY with targets in the
    # first half of the date range and NEGATIVELY in the second half - the
    # exact failure mode this diagnostic exists to catch (a signal that
    # only works in one training sub-period).
    n_days, assets_per_day = 40, 5
    dates = np.array(
        [
            d
            for day_offset in range(n_days)
            for d in [np.datetime64("2020-01-01") + np.timedelta64(day_offset, "D")] * assets_per_day
        ]
    )
    base_targets = np.tile(np.linspace(0.0, 1.0, assets_per_day), n_days)
    targets = torch.tensor(base_targets, dtype=torch.float32)

    flipped_targets = np.tile(np.linspace(1.0, 0.0, assets_per_day), n_days)
    first_half_days = n_days // 2 * assets_per_day
    predictions_array = np.concatenate([base_targets[:first_half_days], flipped_targets[first_half_days:]])
    predictions = torch.tensor(predictions_array, dtype=torch.float32)

    result = compute_purged_cv_rank_ic_diagnostic(predictions, targets, dates, n_folds=4, horizon_days=1, embargo_days=0)

    assert result["any_fold_opposite_sign"] is True
