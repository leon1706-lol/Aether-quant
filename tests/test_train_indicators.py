"""Tests for train.py's Phase 6 technical-indicator integration:
engineer_features()'s new rsi_14/atr_pct_14/bollinger_pctb_20/
volume_zscore_20/macd_histogram_norm/dist_52w_high columns, and
build_cross_sectional_momentum_rank_features(). The underlying pure
indicator formulas themselves are tested in tests/test_technical_indicators.py -
this file verifies train.py wires them in correctly (right windows, right
columns, no extra row drops), not the formulas again.
"""

import numpy as np
import pandas as pd
import pytest

from features.technical_indicators import (
    average_true_range_pct,
    bollinger_pctb,
    distance_from_52w_high,
    macd_histogram_normalized,
    relative_strength_index,
    volume_zscore,
)
from train import (
    LONG_LOOKBACK_WINDOW_BARS,
    build_cross_sectional_momentum_rank_features,
    engineer_features,
)


FEATURE_NAMES = [
    "close_to_close_return_1d",
    "close_to_close_return_5d",
    "close_to_close_return_20d",
    "rolling_volatility_5d",
    "rolling_volatility_20d",
    "momentum_5d",
    "momentum_20d",
    "high_low_range_pct",
    "open_close_range_pct",
    "volume_change_1d",
]
WINDOWS = {
    "training": {"start": "2020-01-01", "end": "2020-12-31"},
    "validation": {"start": "2021-01-01", "end": "2021-12-31"},
    "backtest": {"start": "2022-01-01", "end": "2022-12-31"},
}


def _synthetic_frame(n: int, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=n, freq="D"),
            "open": closes,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": rng.uniform(900.0, 1100.0, n),
        }
    )


# ---------------------------------------------------------------------------
# engineer_features() indicator columns
# ---------------------------------------------------------------------------


def test_engineer_features_adds_all_six_indicator_columns():
    frame = _synthetic_frame(40)

    engineered = engineer_features(frame, FEATURE_NAMES, WINDOWS)

    for column in ("rsi_14", "atr_pct_14", "bollinger_pctb_20", "volume_zscore_20", "macd_histogram_norm", "dist_52w_high"):
        assert column in engineered.columns
        assert engineered[column].isna().sum() == 0


def test_engineer_features_short_indicators_match_direct_function_calls():
    frame = _synthetic_frame(40)
    engineered = engineer_features(frame, FEATURE_NAMES, WINDOWS)

    closes = frame["close"].tolist()
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    volumes = frame["volume"].tolist()

    # Row 0 is always dropped (no previous close for its own return
    # features) - engineered.index no longer aligns 1:1 with frame's raw
    # row positions, so recompute against the ORIGINAL index via the
    # "date" column instead of assuming a fixed offset.
    for _, row in engineered.iterrows():
        raw_index = frame.index[frame["date"] == row["date"]][0]
        expected_rsi = relative_strength_index(closes[: raw_index + 1], period=14)
        expected_atr = average_true_range_pct(highs[: raw_index + 1], lows[: raw_index + 1], closes[: raw_index + 1], period=14)
        expected_bb = bollinger_pctb(closes[: raw_index + 1], period=20)
        expected_vz = volume_zscore(volumes[: raw_index + 1], period=20)
        assert row["rsi_14"] == pytest.approx(expected_rsi)
        assert row["atr_pct_14"] == pytest.approx(expected_atr)
        assert row["bollinger_pctb_20"] == pytest.approx(expected_bb)
        assert row["volume_zscore_20"] == pytest.approx(expected_vz)


def test_engineer_features_long_indicators_are_capped_to_long_lookback_window():
    # More rows than LONG_LOOKBACK_WINDOW_BARS so the cap actually matters -
    # the offline computation must slice to the same bounded window
    # main.py's self.symbol_long_windows (maxlen=260) would see, not use
    # unbounded full history.
    n = LONG_LOOKBACK_WINDOW_BARS + 50
    frame = _synthetic_frame(n)
    engineered = engineer_features(frame, FEATURE_NAMES, WINDOWS)

    closes = frame["close"].tolist()
    last_row = engineered.iloc[-1]
    # engineered's last surviving row is the SECOND-to-last raw row (n-2,
    # not n-1) - the true last raw row is always dropped too, since its
    # target_return_1d has no next-day close to shift(-1) from (same
    # "first and last row always dropped" rule every other feature in this
    # function already follows).
    raw_index = n - 2
    window_start = max(0, raw_index + 1 - LONG_LOOKBACK_WINDOW_BARS)
    expected_macd = macd_histogram_normalized(closes[window_start : raw_index + 1])
    expected_dist = distance_from_52w_high(closes[window_start : raw_index + 1], window=LONG_LOOKBACK_WINDOW_BARS)

    assert last_row["macd_histogram_norm"] == pytest.approx(expected_macd)
    assert last_row["dist_52w_high"] == pytest.approx(expected_dist)


def test_engineer_features_does_not_drop_extra_rows_for_new_indicators():
    # Neutral defaults mean no additional dropna beyond the pre-existing
    # first/last-row rule - same row count as before Phase 6 (row 0: no
    # previous close; last row: no next-day close for target_return_1d).
    frame = _synthetic_frame(30)

    engineered = engineer_features(frame, FEATURE_NAMES, WINDOWS)

    assert len(engineered) == 30 - 2


# ---------------------------------------------------------------------------
# build_cross_sectional_momentum_rank_features
# ---------------------------------------------------------------------------


def _momentum_frame(dates: list[str], momentum_values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates), "momentum_20d": momentum_values})


def test_build_cross_sectional_momentum_rank_features_best_performer_gets_top_rank():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {
        "BEST": _momentum_frame(dates, [0.1, 0.1, 0.1]),
        "MID": _momentum_frame(dates, [0.0, 0.0, 0.0]),
        "WORST": _momentum_frame(dates, [-0.1, -0.1, -0.1]),
    }

    result = build_cross_sectional_momentum_rank_features(asset_frames)

    assert (result["BEST"]["cs_momentum_rank_20"] == 1.0).all()
    assert np.allclose(result["WORST"]["cs_momentum_rank_20"].to_numpy(), 1 / 3)
    assert np.allclose(result["MID"]["cs_momentum_rank_20"].to_numpy(), 2 / 3)


def test_build_cross_sectional_momentum_rank_features_neutral_for_single_asset():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {"A": _momentum_frame(dates, [0.1, 0.05, -0.05])}

    result = build_cross_sectional_momentum_rank_features(asset_frames)

    assert (result["A"]["cs_momentum_rank_20"] == 0.5).all()


def test_build_cross_sectional_momentum_rank_features_no_nan_output_under_normal_usage():
    # momentum_20d itself is never NaN in the real pipeline
    # (engineer_features()'s adaptive lookback guarantees a value for
    # every row) - this checks the realistic multi-asset case never
    # produces NaN ranks either.
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {
        "A": _momentum_frame(dates, [0.1, 0.08, 0.05]),
        "B": _momentum_frame(dates, [0.0, 0.0, 0.0]),
        "C": _momentum_frame(dates, [-0.1, -0.05, -0.02]),
    }

    result = build_cross_sectional_momentum_rank_features(asset_frames)

    for frame in result.values():
        assert frame["cs_momentum_rank_20"].isna().sum() == 0
