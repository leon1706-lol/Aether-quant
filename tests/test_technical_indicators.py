"""Tests for features/technical_indicators.py - the shared pure indicator
functions imported by both train.py::engineer_features() (offline) and
main.py::_build_model_input() (runtime). Conventions match the rest of
this repo's test coverage: no test classes, module-level helpers, plain
lists/dicts, closed-form/hand-verifiable fixtures.
"""

import pytest

from features.technical_indicators import (
    BOLLINGER_PCTB_NEUTRAL,
    CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL,
    DIST_52W_HIGH_NEUTRAL,
    MACD_HISTOGRAM_NEUTRAL,
    RSI_NEUTRAL,
    VOLUME_ZSCORE_NEUTRAL,
    average_true_range_pct,
    bollinger_pctb,
    cross_sectional_momentum_rank,
    distance_from_52w_high,
    macd_histogram_normalized,
    relative_strength_index,
    volume_zscore,
)


# ---------------------------------------------------------------------------
# relative_strength_index
# ---------------------------------------------------------------------------


def test_rsi_returns_neutral_with_insufficient_history():
    assert relative_strength_index([1.0, 2.0], period=14) == RSI_NEUTRAL


def test_rsi_is_100_when_every_change_is_a_gain():
    closes = [float(value) for value in range(1, 16)]  # 15 values, period=14, all +1 changes

    assert relative_strength_index(closes, period=14) == 100.0


def test_rsi_is_0_when_every_change_is_a_loss():
    closes = [float(value) for value in range(15, 0, -1)]  # all -1 changes

    assert relative_strength_index(closes, period=14) == 0.0


def test_rsi_is_neutral_when_no_changes_at_all():
    closes = [10.0] * 15

    assert relative_strength_index(closes, period=14) == RSI_NEUTRAL


def test_rsi_hand_computed_mixed_case():
    # period=2: changes are +1, -1 -> avg_gain=0.5, avg_loss=0.5, RS=1 -> RSI=50
    closes = [10.0, 11.0, 10.0]

    assert relative_strength_index(closes, period=2) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# average_true_range_pct
# ---------------------------------------------------------------------------


def test_atr_pct_returns_zero_with_insufficient_history():
    assert average_true_range_pct([1.0], [1.0], [1.0], period=14) == 0.0


def test_atr_pct_hand_computed():
    # period=1: single true range = max(high-low, |high-prev_close|, |low-prev_close|)
    highs = [10.0, 12.0]
    lows = [9.0, 10.0]
    closes = [9.5, 11.0]
    # true range = max(12-10, |12-9.5|, |10-9.5|) = max(2, 2.5, 0.5) = 2.5
    # atr_pct = 2.5 / 11.0
    assert average_true_range_pct(highs, lows, closes, period=1) == pytest.approx(2.5 / 11.0)


def test_atr_pct_zero_when_latest_close_is_zero():
    highs = [1.0, 1.0]
    lows = [1.0, 1.0]
    closes = [1.0, 0.0]

    assert average_true_range_pct(highs, lows, closes, period=1) == 0.0


# ---------------------------------------------------------------------------
# bollinger_pctb
# ---------------------------------------------------------------------------


def test_bollinger_pctb_neutral_with_insufficient_history():
    assert bollinger_pctb([1.0, 2.0], period=20) == BOLLINGER_PCTB_NEUTRAL


def test_bollinger_pctb_neutral_when_band_has_zero_width():
    assert bollinger_pctb([10.0] * 20, period=20) == BOLLINGER_PCTB_NEUTRAL


def test_bollinger_pctb_at_upper_band_is_one():
    # 19 fixed values plus a 20th chosen to land exactly on the upper band -
    # solved from the actual 19-value mean/std (not assumed), since a
    # 19 fixed values plus a 20th solved so it lands exactly on mean+2*std
    # of the FULL 20-value window (the 19 fixed values alone don't need to
    # be symmetric - the closed-form solve below accounts for however the
    # 20th value shifts the window's own mean/std).
    first_19 = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1, 9.9, 10.3, 10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1, 9.9]
    sum_19 = sum(first_19)
    sum_sq_19 = sum(value ** 2 for value in first_19)
    n = 20
    # mean = (sum_19 + x) / n; variance = sum_sq/n - mean^2; want x = mean + 2*std.
    # Solve numerically (closed-form is messy) via a short fixed-point iteration -
    # converges in a handful of steps for well-behaved inputs like this one.
    x = sum_19 / (n - 1)
    for _ in range(50):
        mean = (sum_19 + x) / n
        variance = (sum_sq_19 + x ** 2) / n - mean ** 2
        x = mean + 2 * (variance ** 0.5)
    window = first_19 + [x]

    result = bollinger_pctb(window, period=20)

    assert result == pytest.approx(1.0, abs=1e-4)


def test_bollinger_pctb_hand_computed_against_independently_recomputed_stats():
    window = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1, 9.9, 10.3, 10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1, 9.9, 12.0]
    mean = sum(window) / len(window)
    variance = sum((value - mean) ** 2 for value in window) / len(window)
    std = variance ** 0.5
    upper = mean + 2 * std
    lower = mean - 2 * std
    expected = (window[-1] - lower) / (upper - lower)

    assert bollinger_pctb(window, period=20) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# volume_zscore
# ---------------------------------------------------------------------------


def test_volume_zscore_neutral_with_insufficient_history():
    assert volume_zscore([100.0], period=20) == VOLUME_ZSCORE_NEUTRAL


def test_volume_zscore_neutral_when_flat_series():
    assert volume_zscore([100.0] * 20, period=20) == VOLUME_ZSCORE_NEUTRAL


def test_volume_zscore_hand_computed():
    # 19 values at 100, last value = 200 -> compute z manually.
    window = [100.0] * 19 + [200.0]
    mean = sum(window) / 20
    variance = sum((value - mean) ** 2 for value in window) / 20
    expected = (200.0 - mean) / (variance ** 0.5)

    assert volume_zscore(window, period=20) == pytest.approx(expected)


def test_volume_zscore_robust_to_a_single_extreme_outlier_on_later_bars():
    # Mirrors the real BTCUSD 2018-08-14 incident shape: one extreme spike
    # among otherwise-normal volumes. The CURRENT bar's z-score (if the
    # spike is the latest bar) is large but finite, not astronomically so
    # like the raw volume_change_1d ratio was.
    normal = [1000.0] * 19
    window = normal + [5_000_000.0]

    result = volume_zscore(window, period=20)

    assert result > 0  # correctly flags as anomalously high
    assert abs(result) < 1000  # but nowhere near the raw-ratio blowup magnitude


# ---------------------------------------------------------------------------
# cross_sectional_momentum_rank
# ---------------------------------------------------------------------------


def test_cross_sectional_momentum_rank_best_performer_gets_top_rank():
    momentum_by_symbol = {"BEST": 0.1, "MID": 0.0, "WORST": -0.1}

    assert cross_sectional_momentum_rank(momentum_by_symbol, "BEST") == pytest.approx(1.0)
    assert cross_sectional_momentum_rank(momentum_by_symbol, "WORST") == pytest.approx(1 / 3)
    assert cross_sectional_momentum_rank(momentum_by_symbol, "MID") == pytest.approx(2 / 3)


def test_cross_sectional_momentum_rank_handles_ties_with_average_rank():
    momentum_by_symbol = {"A": 0.05, "B": 0.05, "C": -0.05}

    # A and B tied for the top 2 positions -> average rank (2+3)/2/3 = 5/6
    assert cross_sectional_momentum_rank(momentum_by_symbol, "A") == pytest.approx(5 / 6)
    assert cross_sectional_momentum_rank(momentum_by_symbol, "B") == pytest.approx(5 / 6)


def test_cross_sectional_momentum_rank_neutral_when_symbol_missing_or_thin_universe():
    assert cross_sectional_momentum_rank({"A": 0.1}, "A") == CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL
    assert cross_sectional_momentum_rank({"A": 0.1, "B": 0.2}, "C") == CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL


# ---------------------------------------------------------------------------
# macd_histogram_normalized
# ---------------------------------------------------------------------------


def test_macd_histogram_neutral_with_insufficient_history():
    assert macd_histogram_normalized([1.0] * 10, fast=12, slow=26, signal=9) == MACD_HISTOGRAM_NEUTRAL


def test_macd_histogram_neutral_when_flat_series():
    # A perfectly flat series has fast EMA == slow EMA everywhere -> histogram is 0.
    closes = [50.0] * 40

    assert macd_histogram_normalized(closes, fast=12, slow=26, signal=9) == pytest.approx(0.0)


def test_macd_histogram_positive_for_a_strong_uptrend():
    closes = [50.0 + 0.5 * index for index in range(40)]

    result = macd_histogram_normalized(closes, fast=12, slow=26, signal=9)

    # A steady uptrend: fast EMA leads slow EMA upward -> positive histogram.
    assert result > 0


def test_macd_histogram_zero_when_latest_close_is_zero():
    closes = [1.0] * 39 + [0.0]

    assert macd_histogram_normalized(closes, fast=12, slow=26, signal=9) == MACD_HISTOGRAM_NEUTRAL


# ---------------------------------------------------------------------------
# distance_from_52w_high
# ---------------------------------------------------------------------------


def test_distance_from_52w_high_neutral_with_insufficient_history():
    assert distance_from_52w_high([10.0], window=252) == DIST_52W_HIGH_NEUTRAL


def test_distance_from_52w_high_zero_at_the_high():
    closes = [80.0, 90.0, 100.0]

    assert distance_from_52w_high(closes, window=252) == pytest.approx(0.0)


def test_distance_from_52w_high_negative_below_the_high():
    closes = [80.0, 100.0, 90.0]

    assert distance_from_52w_high(closes, window=252) == pytest.approx(90.0 / 100.0 - 1.0)


def test_distance_from_52w_high_only_considers_trailing_window():
    # An old, higher close outside the window must not suppress the ratio -
    # only the trailing `window` bars count as "52-week" history.
    closes = [200.0] + [90.0, 100.0]  # old high of 200, then a real window of [90, 100]

    result = distance_from_52w_high(closes, window=2)

    assert result == pytest.approx(0.0)  # 100 is the max within the trailing 2-bar window
