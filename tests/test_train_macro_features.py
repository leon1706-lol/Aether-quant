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
    """Closes whose window momentum at bar i (history < 21 bars: vs bar 0) equals momentum_20d[i]; bar 0 is the base."""
    closes = [100.0] + [100.0 * (1.0 + value) for value in momentum_20d[1:]]
    return pd.DataFrame({"date": pd.to_datetime(dates), "close": closes})


# A row sees the reference momentum of the bars BEFORE its own tick (Problems.md #135), so a hand-computed
# value lands one row after the bar that produced it. Equity rows tick at the equity close.

DAYS = [f"2020-01-{day:02d}" for day in range(1, 6)]


def test_build_macro_features_by_date_adds_columns_to_every_asset_frame():
    asset_frames = {
        "TLT": _momentum_frame(DAYS, [0.0, 0.05, 0.05, 0.05, 0.05]),
        "SHY": _momentum_frame(DAYS, [0.0, 0.01, 0.01, 0.01, 0.01]),
        "HYG": _momentum_frame(DAYS, [0.0, 0.02, 0.02, 0.02, 0.02]),
        "LQD": _momentum_frame(DAYS, [0.0, 0.04, 0.04, 0.04, 0.04]),
        "BTCUSD": _momentum_frame(DAYS, [0.0, 0.20, 0.20, 0.20, 0.20]),
        "AAPL": _momentum_frame(DAYS, [0.0, 0.03, 0.03, 0.03, 0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    for ticker, frame in result.items():
        for name in MACRO_FEATURE_NAMES:
            assert name in frame.columns
        assert len(frame) == len(asset_frames[ticker])


def test_build_macro_features_by_date_broadcasts_identically_across_tickers():
    dates = DAYS[:4]
    asset_frames = {
        "TLT": _momentum_frame(dates, [0.0, 0.05, 0.06, 0.07]),
        "SHY": _momentum_frame(dates, [0.0, 0.01, 0.01, 0.01]),
        "AAPL": _momentum_frame(dates, [0.0, 0.03, 0.03, 0.03]),
        "SPY": _momentum_frame(dates, [0.0, 0.02, 0.02, 0.02]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    pd.testing.assert_series_equal(
        result["AAPL"]["macro_yield_curve_slope_proxy"].reset_index(drop=True),
        result["SPY"]["macro_yield_curve_slope_proxy"].reset_index(drop=True),
        check_names=False,
    )


def test_build_macro_features_by_date_yield_curve_slope_matches_hand_computation():
    dates = DAYS[:3]
    asset_frames = {
        "TLT": _momentum_frame(dates, [0.0, 0.05, 0.05]),
        "SHY": _momentum_frame(dates, [0.0, 0.01, 0.01]),
        "AAPL": _momentum_frame(dates, [0.0, 0.03, 0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert result["AAPL"]["macro_yield_curve_slope_proxy"].iloc[0] == 0.0  # nothing before the first bar
    assert np.isclose(result["AAPL"]["macro_yield_curve_slope_proxy"].iloc[2], 0.04)


def test_build_macro_features_by_date_credit_spread_matches_hand_computation():
    dates = DAYS[:3]
    asset_frames = {
        "HYG": _momentum_frame(dates, [0.0, 0.02, 0.02]),
        "LQD": _momentum_frame(dates, [0.0, 0.05, 0.05]),
        "AAPL": _momentum_frame(dates, [0.0, 0.03, 0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert np.isclose(result["AAPL"]["macro_credit_spread_proxy"].iloc[2], -0.03)


def test_build_macro_features_by_date_crypto_risk_appetite_matches_hand_computation():
    dates = DAYS[:3]
    asset_frames = {
        "BTCUSD": _momentum_frame(dates, [0.0, 0.15, 0.15]),
        "AAPL": _momentum_frame(dates, [0.0, 0.03, 0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert np.isclose(result["AAPL"]["macro_crypto_risk_appetite_proxy"].iloc[2], 0.15)


def test_build_macro_features_by_date_missing_reference_ticker_is_neutral_not_raise():
    dates = DAYS[:3]
    asset_frames = {
        "AAPL": _momentum_frame(dates, [0.0, 0.03, 0.03]),
        "SPY": _momentum_frame(dates, [0.0, 0.02, 0.02]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert (result["AAPL"]["macro_yield_curve_slope_proxy"] == 0.0).all()
    assert (result["AAPL"]["macro_credit_spread_proxy"] == 0.0).all()
    assert (result["AAPL"]["macro_crypto_risk_appetite_proxy"] == 0.0).all()


def test_build_macro_features_by_date_non_finite_close_is_treated_as_missing():
    dates = DAYS[:4]
    tlt = _momentum_frame(dates, [0.0, 0.05, 0.05, 0.05])
    tlt.loc[2, "close"] = np.nan  # a corrupt bar must neutral-default the proxy, never inject NaN
    asset_frames = {
        "TLT": tlt,
        "SHY": _momentum_frame(dates, [0.0, 0.01, 0.01, 0.01]),
        "AAPL": _momentum_frame(dates, [0.0, 0.03, 0.03, 0.03]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    assert result["AAPL"]["macro_yield_curve_slope_proxy"].notna().all()
    assert np.isclose(result["AAPL"]["macro_yield_curve_slope_proxy"].iloc[2], 0.04)  # sees bar 1, before the NaN bar


def test_build_macro_features_by_date_asof_holds_last_known_value_on_thin_dates():
    # TLT/SHY only trade on weekdays; the crypto-only weekend row must hold their last known value.
    reference_dates = ["2020-01-01", "2020-01-02", "2020-01-04"]
    all_dates = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"]
    asset_frames = {
        "TLT": _momentum_frame(reference_dates, [0.0, 0.05, 0.07]),
        "SHY": _momentum_frame(reference_dates, [0.0, 0.01, 0.01]),
        "BTCUSD": _momentum_frame(all_dates, [0.0, 0.10, 0.11, 0.12]),
    }

    result = build_macro_features_by_date(asset_frames, {})

    # BTCUSD's 2020-01-03 bar closes at midnight after 01-03, so it sees TLT/SHY through 01-02 (no 01-03 row).
    row = result["BTCUSD"][result["BTCUSD"]["date"] == pd.Timestamp("2020-01-03")].iloc[0]
    assert np.isclose(row["macro_yield_curve_slope_proxy"], 0.04)


def test_build_macro_features_by_date_respects_config_reference_ticker_override():
    dates = DAYS[:3]
    asset_frames = {
        "IEF": _momentum_frame(dates, [0.0, 0.09, 0.09]),
        "SHY": _momentum_frame(dates, [0.0, 0.01, 0.01]),
        "AAPL": _momentum_frame(dates, [0.0, 0.03, 0.03]),
    }
    config = {"phase1": {"features": {"macro_reference_tickers": {"long_duration": "IEF"}}}}

    result = build_macro_features_by_date(asset_frames, config)

    assert np.isclose(result["AAPL"]["macro_yield_curve_slope_proxy"].iloc[2], 0.08)
