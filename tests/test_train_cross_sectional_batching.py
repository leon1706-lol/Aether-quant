"""Tests for train.py's V5.1 Phase 3 (item 1) cross-sectional date batching:
build_cross_sectional_date_batches(), build_date_group_ids(),
CrossSectionalDateBatchSampler. Pure numpy - no torch model needed."""

import numpy as np

from train import CrossSectionalDateBatchSampler, build_cross_sectional_date_batches, build_date_group_ids


def _dates(*counts_per_date):
    """Builds a dates array with `counts_per_date[i]` rows of date i."""
    return np.array(
        [f"2020-01-{day + 1:02d}" for day, count in enumerate(counts_per_date) for _ in range(count)]
    )


# ---------------------------------------------------------------------------
# build_cross_sectional_date_batches
# ---------------------------------------------------------------------------


def test_every_batch_contains_only_whole_dates():
    dates = _dates(10, 10, 10, 10)
    batches = build_cross_sectional_date_batches(dates, batch_dates=2, min_group_size=5, shuffle=False, seed=0)

    for batch in batches:
        batch_dates = set(dates[batch])
        for date_value in batch_dates:
            # Every row of this date, anywhere in the full array, must be
            # present in this same batch - a date is never split across
            # two batches.
            expected_indices = set(np.where(dates == date_value)[0])
            actual_indices = set(batch[dates[batch] == date_value])
            assert expected_indices == actual_indices


def test_thin_dates_are_dropped_not_zero_filled():
    dates = _dates(10, 3, 10)  # middle date has only 3 rows
    batches = build_cross_sectional_date_batches(dates, batch_dates=3, min_group_size=5, shuffle=False, seed=0)

    all_rows = np.concatenate(batches) if batches else np.array([], dtype=np.int64)
    assert len(all_rows) == 20  # 10 + 10, the thin date's 3 rows excluded
    kept_dates = set(dates[all_rows])
    assert "2020-01-02" not in kept_dates


def test_batch_dates_of_1_yields_one_date_per_batch():
    dates = _dates(5, 5, 5)
    batches = build_cross_sectional_date_batches(dates, batch_dates=1, min_group_size=1, shuffle=False, seed=0)

    assert len(batches) == 3
    for batch in batches:
        assert len(set(dates[batch])) == 1


def test_seeded_shuffle_is_deterministic():
    dates = _dates(5, 5, 5, 5, 5)
    batches_a = build_cross_sectional_date_batches(dates, batch_dates=2, min_group_size=1, shuffle=True, seed=7)
    batches_b = build_cross_sectional_date_batches(dates, batch_dates=2, min_group_size=1, shuffle=True, seed=7)

    for batch_a, batch_b in zip(batches_a, batches_b):
        assert np.array_equal(batch_a, batch_b)


def test_different_seeds_produce_different_date_order():
    dates = _dates(5, 5, 5, 5, 5, 5, 5, 5)
    batches_a = build_cross_sectional_date_batches(dates, batch_dates=1, min_group_size=1, shuffle=True, seed=1)
    batches_b = build_cross_sectional_date_batches(dates, batch_dates=1, min_group_size=1, shuffle=True, seed=2)

    order_a = [dates[batch][0] for batch in batches_a]
    order_b = [dates[batch][0] for batch in batches_b]
    assert order_a != order_b


def test_shuffle_false_keeps_sorted_date_order():
    dates = _dates(5, 5, 5)
    # Deliberately construct out of order to prove sorting happens.
    shuffled_input = np.concatenate([dates[10:], dates[:10]])
    batches = build_cross_sectional_date_batches(shuffled_input, batch_dates=1, min_group_size=1, shuffle=False, seed=0)

    order = [shuffled_input[batch][0] for batch in batches]
    assert order == sorted(order)


def test_empty_dates_returns_no_batches():
    assert build_cross_sectional_date_batches(np.array([]), batch_dates=2, min_group_size=1, shuffle=False, seed=0) == []


def test_negative_batch_dates_treated_as_one():
    dates = _dates(3, 3)
    batches = build_cross_sectional_date_batches(dates, batch_dates=-5, min_group_size=1, shuffle=False, seed=0)
    assert len(batches) == 2


# ---------------------------------------------------------------------------
# build_date_group_ids
# ---------------------------------------------------------------------------


def test_build_date_group_ids_assigns_dense_ids_in_sorted_date_order():
    dates = _dates(2, 3, 1)
    group_ids = build_date_group_ids(dates)

    assert list(group_ids[:2]) == [0, 0]
    assert list(group_ids[2:5]) == [1, 1, 1]
    assert list(group_ids[5:6]) == [2]


def test_build_date_group_ids_same_date_always_same_id_regardless_of_position():
    dates = np.array(["2020-01-02", "2020-01-01", "2020-01-02", "2020-01-01"])
    group_ids = build_date_group_ids(dates)

    assert group_ids[0] == group_ids[2]
    assert group_ids[1] == group_ids[3]
    assert group_ids[0] != group_ids[1]


# ---------------------------------------------------------------------------
# CrossSectionalDateBatchSampler
# ---------------------------------------------------------------------------


def test_sampler_iterates_the_same_batches_build_cross_sectional_date_batches_would():
    dates = _dates(5, 5, 5, 5)
    sampler = CrossSectionalDateBatchSampler(dates, batch_dates=2, min_group_size=1, shuffle=False, seed=3)

    expected = build_cross_sectional_date_batches(dates, batch_dates=2, min_group_size=1, shuffle=False, seed=3)
    actual = list(sampler)

    assert len(actual) == len(expected)
    for actual_batch, expected_batch in zip(actual, expected):
        assert actual_batch == expected_batch.tolist()


def test_sampler_len_matches_iteration_count():
    dates = _dates(5, 5, 5, 5, 5)
    sampler = CrossSectionalDateBatchSampler(dates, batch_dates=2, min_group_size=1, shuffle=False, seed=0)
    assert len(sampler) == len(list(sampler))


def test_sampler_set_epoch_changes_shuffle_order():
    dates = _dates(5, 5, 5, 5, 5, 5, 5, 5)
    sampler = CrossSectionalDateBatchSampler(dates, batch_dates=1, min_group_size=1, shuffle=True, seed=0)

    sampler.set_epoch(0)
    epoch_0_batches = list(sampler)
    sampler.set_epoch(1)
    epoch_1_batches = list(sampler)

    assert epoch_0_batches != epoch_1_batches


def test_sampler_same_epoch_reproduces_same_batches():
    dates = _dates(5, 5, 5, 5, 5, 5)
    sampler = CrossSectionalDateBatchSampler(dates, batch_dates=1, min_group_size=1, shuffle=True, seed=0)

    sampler.set_epoch(2)
    first = list(sampler)
    sampler.set_epoch(2)
    second = list(sampler)

    assert first == second
