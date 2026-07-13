"""Tests for train.py::build_derivatives_macro_features_by_date() -
third cross-asset macro sibling to build_macro_features_by_date()/
build_bond_features_by_date() (see tests/test_train_macro_features.py and
tests/test_train_bond_features.py).

Two groups of tests:
- Neutral-default group (below): with an empty/no-op config (or a config
  with no futures/options assets configured), every date's lookup
  correctly resolves to the documented neutral default (0.0) for every
  asset - the honest, correct behavior for "no derivatives data
  configured," not a bug.
- Real-computation group: with actual future/option assets configured
  (family_ticker-grouped futures, strike/expiry/right-tagged options),
  the function computes real term structure / put-call ratio / IV skew
  from the asset frames' own close/volume columns, reusing
  features/options_greeks.py's Black-Scholes IV solver + greeks.
"""

from datetime import date

import pandas as pd

from features.derivatives_macro_features import DERIVATIVES_MACRO_FEATURE_NAMES
from features.options_greeks import bs_price
from train import build_derivatives_macro_features_by_date


def _frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates)})


# ---------------------------------------------------------------------------
# Neutral-default group
# ---------------------------------------------------------------------------


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


def test_build_derivatives_macro_features_by_date_single_futures_family_member_is_neutral():
    # A family needs >= 2 members (front + next) - a single fetched
    # contract can't produce a term structure on its own.
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {"ES_FRONT": pd.DataFrame({"date": pd.to_datetime(dates), "close": [100.0, 101.0, 102.0]})}
    config = {"phase1": {"universe": {"assets": [{"ticker": "ES_FRONT", "asset_class": "future", "family_ticker": "ES"}]}}}

    result = build_derivatives_macro_features_by_date(asset_frames, config)

    assert (result["ES_FRONT"]["futures_term_structure_slope"] == 0.0).all()


# ---------------------------------------------------------------------------
# Real-computation group
# ---------------------------------------------------------------------------


def _config(assets: list[dict], risk_free_rate: float = 0.045) -> dict:
    return {
        "phase1": {"universe": {"assets": assets}},
        "phase_v2": {"options_risk": {"risk_free_rate": risk_free_rate}},
    }


def test_build_derivatives_macro_features_by_date_futures_term_structure_contango():
    dates = pd.to_datetime([f"2026-01-{day:02d}" for day in range(1, 6)])
    front = pd.DataFrame({"date": dates, "close": [100.0, 100.5, 101.0, 101.5, 102.0]})
    next_month = pd.DataFrame({"date": dates, "close": [102.0, 102.5, 103.0, 103.5, 104.0]})
    asset_frames = {"ES_FRONT": front, "ES_NEXT": next_month}
    config = _config(
        [
            {"ticker": "ES_FRONT", "asset_class": "future", "family_ticker": "ES", "contract_month": "202603"},
            {"ticker": "ES_NEXT", "asset_class": "future", "family_ticker": "ES", "contract_month": "202606"},
        ]
    )

    result = build_derivatives_macro_features_by_date(asset_frames, config)

    # next-month consistently ~2% above front-month -> positive (contango) slope every date.
    assert (result["ES_FRONT"]["futures_term_structure_slope"] > 0.0).all()


def test_build_derivatives_macro_features_by_date_futures_term_structure_backwardation():
    dates = pd.to_datetime([f"2026-01-{day:02d}" for day in range(1, 4)])
    front = pd.DataFrame({"date": dates, "close": [102.0, 102.5, 103.0]})
    next_month = pd.DataFrame({"date": dates, "close": [100.0, 100.5, 101.0]})
    asset_frames = {"CL_FRONT": front, "CL_NEXT": next_month}
    config = _config(
        [
            {"ticker": "CL_FRONT", "asset_class": "future", "family_ticker": "CL", "contract_month": "202603"},
            {"ticker": "CL_NEXT", "asset_class": "future", "family_ticker": "CL", "contract_month": "202606"},
        ]
    )
    config["phase1"]["features"] = {"derivatives_reference_tickers": {"futures_term_structure": "CL"}}

    result = build_derivatives_macro_features_by_date(asset_frames, config)

    assert (result["CL_FRONT"]["futures_term_structure_slope"] < 0.0).all()


def test_build_derivatives_macro_features_by_date_options_put_call_ratio_and_iv_skew_real_bs():
    dates = pd.to_datetime([f"2026-01-{day:02d}" for day in range(1, 6)])
    spy_spot = [500.0, 501.0, 502.0, 503.0, 504.0]
    expiry = "2026-06-19"
    call_prices = [
        bs_price(spot, 510, (date.fromisoformat(expiry) - d.date()).days / 365.0, 0.045, 0.20, 0.0, "call")
        for spot, d in zip(spy_spot, dates)
    ]
    put_prices = [
        bs_price(spot, 490, (date.fromisoformat(expiry) - d.date()).days / 365.0, 0.045, 0.20, 0.0, "put")
        for spot, d in zip(spy_spot, dates)
    ]
    asset_frames = {
        "SPY": pd.DataFrame({"date": dates, "close": spy_spot}),
        "SPY_500C": pd.DataFrame({"date": dates, "close": call_prices, "volume": [100.0] * 5}),
        "SPY_490P": pd.DataFrame({"date": dates, "close": put_prices, "volume": [300.0] * 5}),
    }
    config = _config(
        [
            {"ticker": "SPY", "asset_class": "equity"},
            {"ticker": "SPY_500C", "asset_class": "option", "underlying_ticker": "SPY", "strike": 510, "expiry": expiry, "right": "call"},
            {"ticker": "SPY_490P", "asset_class": "option", "underlying_ticker": "SPY", "strike": 490, "expiry": expiry, "right": "put"},
        ]
    )

    result = build_derivatives_macro_features_by_date(asset_frames, config)

    # put volume (300) > call volume (100) -> positive put-heavy skew, every date.
    ratios = result["SPY"]["options_put_call_ratio"].tolist()
    assert all(ratio > 0.0 for ratio in ratios)
    assert all(abs(ratio - 0.5) < 1e-9 for ratio in ratios)  # (300-100)/(300+100)

    # both contracts priced off the SAME 0.20 input vol -> IV solver should
    # round-trip to ~0.20 on both sides, netting to ~0 skew.
    skews = result["SPY"]["options_implied_vol_skew"].tolist()
    assert all(abs(skew) < 1e-3 for skew in skews)


def test_build_derivatives_macro_features_by_date_options_skew_reflects_real_vol_smirk():
    # Puts priced with materially higher IV than calls -> positive skew,
    # the standard equity "smirk" direction.
    dates = pd.to_datetime(["2026-01-02"])
    expiry = "2026-06-19"
    time_to_expiry_years = (date.fromisoformat(expiry) - date(2026, 1, 2)).days / 365.0
    put_price = bs_price(500.0, 490, time_to_expiry_years, 0.045, 0.28, 0.0, "put")
    call_price = bs_price(500.0, 510, time_to_expiry_years, 0.045, 0.18, 0.0, "call")
    asset_frames = {
        "SPY": pd.DataFrame({"date": dates, "close": [500.0]}),
        "SPY_500C": pd.DataFrame({"date": dates, "close": [call_price], "volume": [50.0]}),
        "SPY_490P": pd.DataFrame({"date": dates, "close": [put_price], "volume": [50.0]}),
    }
    config = _config(
        [
            {"ticker": "SPY", "asset_class": "equity"},
            {"ticker": "SPY_500C", "asset_class": "option", "underlying_ticker": "SPY", "strike": 510, "expiry": expiry, "right": "call"},
            {"ticker": "SPY_490P", "asset_class": "option", "underlying_ticker": "SPY", "strike": 490, "expiry": expiry, "right": "put"},
        ]
    )

    result = build_derivatives_macro_features_by_date(asset_frames, config)

    assert result["SPY"]["options_implied_vol_skew"].iloc[0] > 0.05  # ~0.28 - 0.18


def test_build_derivatives_macro_features_by_date_options_missing_metadata_skipped_not_raised():
    dates = pd.to_datetime(["2026-01-02"])
    asset_frames = {
        "SPY": pd.DataFrame({"date": dates, "close": [500.0]}),
        "SPY_BAD": pd.DataFrame({"date": dates, "close": [5.0], "volume": [10.0]}),
    }
    # Missing strike/expiry/right entirely - must be skipped, not crash.
    config = _config([{"ticker": "SPY", "asset_class": "equity"}, {"ticker": "SPY_BAD", "asset_class": "option", "underlying_ticker": "SPY"}])

    result = build_derivatives_macro_features_by_date(asset_frames, config)

    assert result["SPY"]["options_put_call_ratio"].iloc[0] == 0.0
    assert result["SPY"]["options_implied_vol_skew"].iloc[0] == 0.0
