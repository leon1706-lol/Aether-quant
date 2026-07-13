"""Tests for train.py::build_derivatives_macro_features_by_date() -
third cross-asset macro sibling to build_macro_features_by_date()/
build_bond_features_by_date() (see tests/test_train_macro_features.py and
tests/test_train_bond_features.py). Since no futures/options tickers with
front/next-month or chain-aggregate shape exist in this offline training
pipeline yet, every date's lookup is expected to resolve to the documented
neutral default (0.0) for every asset - this file asserts exactly that
broadcast-ready, correct-when-empty behavior (see the function's own
docstring for why that's correct, not a bug).
"""

import pandas as pd

from features.derivatives_macro_features import DERIVATIVES_MACRO_FEATURE_NAMES
from train import build_derivatives_macro_features_by_date


def _frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates)})


def test_build_derivatives_macro_features_by_date_adds_all_columns():
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]
    asset_frames = {"AAPL": _frame(dates), "TLT": _frame(dates), "BTCUSD": _frame(dates)}

    result = build_derivatives_macro_features_by_date(asset_frames, {})

    for ticker, frame in result.items():
        for name in DERIVATIVES_MACRO_FEATURE_NAMES:
            assert name in frame.columns
        assert len(frame) == len(asset_frames[ticker])


def test_build_derivatives_macro_features_by_date_neutral_default_for_every_asset():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {"AAPL": _frame(dates), "SPY": _frame(dates)}

    result = build_derivatives_macro_features_by_date(asset_frames, {})

    for ticker in asset_frames:
        assert (result[ticker]["futures_term_structure_slope"] == 0.0).all()
        assert (result[ticker]["options_put_call_ratio"] == 0.0).all()
        assert (result[ticker]["options_implied_vol_skew"] == 0.0).all()


def test_build_derivatives_macro_features_by_date_broadcasts_identically_across_tickers():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {"AAPL": _frame(dates), "SPY": _frame(dates), "BTCUSD": _frame(dates)}

    result = build_derivatives_macro_features_by_date(asset_frames, {})

    pd.testing.assert_series_equal(
        result["AAPL"]["futures_term_structure_slope"].reset_index(drop=True),
        result["SPY"]["futures_term_structure_slope"].reset_index(drop=True),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        result["AAPL"]["options_put_call_ratio"].reset_index(drop=True),
        result["BTCUSD"]["options_put_call_ratio"].reset_index(drop=True),
        check_names=False,
    )


def test_build_derivatives_macro_features_by_date_never_raises_on_empty_universe():
    result = build_derivatives_macro_features_by_date({}, {})
    assert result == {}
