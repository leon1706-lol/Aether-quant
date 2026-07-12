"""Tests for train.py::build_macro_features_by_date() (Phase 1b of the
5/10 -> 9/10 roadmap) - offline/runtime parity is with
main.py::_build_macro_payload(), which reuses the identical pure functions
from features/macro_features.py (see tests/test_macro_features.py for
those), so this file focuses on the per-date reference-ticker lookup and
broadcast logic that's unique to the offline dataset-build path.
"""

import numpy as np
import pandas as pd

from train import MACRO_FEATURE_NAMES, build_macro_features_by_date


def _momentum_frame(dates: list[str], momentum_20d: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates), "momentum_20d": momentum_20d})


def test_build_macro_features_by_date_adds_columns_to_every_asset_frame():
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]
    asset_frames = {
        "TLT": _momentum_frame(dates, [0.05, 0.05, 0.05, 0.05, 0.05]),
        "SHY": _momentum_frame(dates, [0.01, 0.01, 0.01, 0.01, 0.01]),
        "HYG": _momentum_frame(dates, [0.02, 0.02, 0.02, 0.02, 0.02]),
        "LQD": _momentum_frame(dates, [0.04, 0.04, 0.04, 0.04, 0.04]),
        "BTCUSD": _momentum_frame(dates, [0.20, 0.20, 0.20, 0.20, 0.20]),
        "AAPL": _momentum_frame(dates, [0.03, 0.03, 0.03, 0.03, 0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    for ticker, frame in result.items():
        for name in MACRO_FEATURE_NAMES:
            assert name in frame.columns
        assert len(frame) == len(asset_frames[ticker])


def test_build_macro_features_by_date_broadcasts_identically_across_tickers():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {
        "TLT": _momentum_frame(dates, [0.05, 0.06, 0.07]),
        "SHY": _momentum_frame(dates, [0.01, 0.01, 0.01]),
        "AAPL": _momentum_frame(dates, [0.03, 0.03, 0.03]),
        "SPY": _momentum_frame(dates, [0.02, 0.02, 0.02]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    # AAPL and SPY have no relation to the TLT/SHY reference tickers, but
    # both must see the exact same global macro state each date.
    pd.testing.assert_series_equal(
        result["AAPL"]["macro_yield_curve_slope_proxy"].reset_index(drop=True),
        result["SPY"]["macro_yield_curve_slope_proxy"].reset_index(drop=True),
        check_names=False,
    )


def test_build_macro_features_by_date_yield_curve_slope_matches_hand_computation():
    dates = ["2020-01-01"]
    asset_frames = {
        "TLT": _momentum_frame(dates, [0.05]),
        "SHY": _momentum_frame(dates, [0.01]),
        "AAPL": _momentum_frame(dates, [0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert np.isclose(result["AAPL"]["macro_yield_curve_slope_proxy"].iloc[0], 0.04)


def test_build_macro_features_by_date_credit_spread_matches_hand_computation():
    dates = ["2020-01-01"]
    asset_frames = {
        "HYG": _momentum_frame(dates, [0.02]),
        "LQD": _momentum_frame(dates, [0.05]),
        "AAPL": _momentum_frame(dates, [0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert np.isclose(result["AAPL"]["macro_credit_spread_proxy"].iloc[0], -0.03)


def test_build_macro_features_by_date_crypto_risk_appetite_matches_hand_computation():
    dates = ["2020-01-01"]
    asset_frames = {
        "BTCUSD": _momentum_frame(dates, [0.15]),
        "AAPL": _momentum_frame(dates, [0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert np.isclose(result["AAPL"]["macro_crypto_risk_appetite_proxy"].iloc[0], 0.15)


def test_build_macro_features_by_date_missing_reference_ticker_is_neutral_not_raise():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    # No TLT/SHY/HYG/LQD/BTCUSD at all in this universe subset.
    asset_frames = {
        "AAPL": _momentum_frame(dates, [0.03, 0.03, 0.03]),
        "SPY": _momentum_frame(dates, [0.02, 0.02, 0.02]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert (result["AAPL"]["macro_yield_curve_slope_proxy"] == 0.0).all()
    assert (result["AAPL"]["macro_credit_spread_proxy"] == 0.0).all()
    assert (result["AAPL"]["macro_crypto_risk_appetite_proxy"] == 0.0).all()


def test_build_macro_features_by_date_nan_momentum_treated_as_missing():
    dates = ["2020-01-01", "2020-01-02"]
    asset_frames = {
        "TLT": _momentum_frame(dates, [np.nan, 0.05]),
        "SHY": _momentum_frame(dates, [0.01, 0.01]),
        "AAPL": _momentum_frame(dates, [0.03, 0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert result["AAPL"]["macro_yield_curve_slope_proxy"].iloc[0] == 0.0
    assert np.isclose(result["AAPL"]["macro_yield_curve_slope_proxy"].iloc[1], 0.04)


def test_build_macro_features_by_date_asof_holds_last_known_value_on_thin_dates():
    # TLT/SHY only trade on weekdays; AAPL/SPY share those dates in this
    # fixture too, but a real universe also has crypto-only weekend rows -
    # the reference ticker's momentum must hold forward from its last
    # known trading date, not go NaN/neutral on the very next calendar day.
    reference_dates = ["2020-01-01", "2020-01-03"]
    all_dates = ["2020-01-01", "2020-01-02", "2020-01-03"]
    asset_frames = {
        "TLT": _momentum_frame(reference_dates, [0.05, 0.07]),
        "SHY": _momentum_frame(reference_dates, [0.01, 0.01]),
        "BTCUSD": _momentum_frame(all_dates, [0.10, 0.11, 0.12]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    # 2020-01-02: no new TLT/SHY row, but the 2020-01-01 value should
    # still apply (as-of, not NaN/neutral).
    middle_row = result["BTCUSD"][result["BTCUSD"]["date"] == pd.Timestamp("2020-01-02")].iloc[0]
    assert np.isclose(middle_row["macro_yield_curve_slope_proxy"], 0.04)


def test_build_macro_features_by_date_respects_config_reference_ticker_override():
    dates = ["2020-01-01"]
    asset_frames = {
        "IEF": _momentum_frame(dates, [0.09]),
        "SHY": _momentum_frame(dates, [0.01]),
        "AAPL": _momentum_frame(dates, [0.03]),
    }
    config = {"phase1": {"features": {"macro_reference_tickers": {"long_duration": "IEF"}}}}

    result = build_macro_features_by_date(asset_frames, config)

    assert np.isclose(result["AAPL"]["macro_yield_curve_slope_proxy"].iloc[0], 0.08)
