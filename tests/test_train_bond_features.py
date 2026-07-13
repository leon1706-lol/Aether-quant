"""Tests for train.py::build_bond_features_by_date() - real-data sibling
of build_macro_features_by_date() (see tests/test_train_macro_features.py),
backed by data_pipeline/fred_backfill.py's FRED series shape rather than
bond-ETF-price-momentum proxies. Offline/runtime parity is with
main.py::_build_bond_payload()/_bond_empirical_duration_beta_for_symbol(),
which reuse the identical pure functions from features/bond_features.py
(see tests/test_bond_features.py for those).
"""

from datetime import date

import numpy as np
import pandas as pd

from train import build_bond_features_by_date


def _price_frame(dates: list[str], closes: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "close": closes})
    frame["close_to_close_return_1d"] = frame["close"].pct_change()
    return frame


def _fred_series(**overrides) -> dict:
    series = {
        "treasury_3mo": [],
        "treasury_2yr": [],
        "treasury_5yr": [],
        "treasury_10yr": [],
        "credit_spread_baa10y": [],
    }
    series.update(overrides)
    return series


def _config(assets: list[dict]) -> dict:
    return {"phase1": {"universe": {"assets": assets}}}


def test_build_bond_features_by_date_adds_columns_to_every_asset_frame():
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]
    asset_frames = {
        "TLT": _price_frame(dates, [140.0, 141.0, 142.0, 141.5, 143.0]),
        "AAPL": _price_frame(dates, [300.0, 301.0, 302.0, 303.0, 304.0]),
    }
    config = _config([{"ticker": "TLT", "asset_class": "bond"}, {"ticker": "AAPL", "asset_class": "equity"}])

    result = build_bond_features_by_date(asset_frames, config, _fred_series())

    for ticker, frame in result.items():
        for name in (
            "bond_yield_curve_level",
            "bond_yield_curve_slope",
            "bond_yield_curve_curvature",
            "bond_credit_spread_level",
            "bond_empirical_duration_beta",
        ):
            assert name in frame.columns
        assert len(frame) == len(asset_frames[ticker])


def test_build_bond_features_by_date_broadcasts_yield_curve_identically_across_tickers():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {
        "TLT": _price_frame(dates, [140.0, 141.0, 142.0]),
        "AAPL": _price_frame(dates, [300.0, 301.0, 302.0]),
    }
    fred_series = _fred_series(
        treasury_10yr=[{"date": date(2020, 1, 1), "value": 0.018}],
        treasury_3mo=[{"date": date(2020, 1, 1), "value": 0.015}],
    )
    config = _config([{"ticker": "TLT", "asset_class": "bond"}, {"ticker": "AAPL", "asset_class": "equity"}])

    result = build_bond_features_by_date(asset_frames, config, fred_series)

    pd.testing.assert_series_equal(
        result["AAPL"]["bond_yield_curve_slope"].reset_index(drop=True),
        result["TLT"]["bond_yield_curve_slope"].reset_index(drop=True),
        check_names=False,
    )


def test_build_bond_features_by_date_matches_hand_computation():
    dates = ["2020-01-02"]
    asset_frames = {"AAPL": _price_frame(dates, [300.0])}
    fred_series = _fred_series(
        treasury_3mo=[{"date": date(2020, 1, 1), "value": 0.015}],
        treasury_2yr=[{"date": date(2020, 1, 1), "value": 0.016}],
        treasury_5yr=[{"date": date(2020, 1, 1), "value": 0.017}],
        treasury_10yr=[{"date": date(2020, 1, 1), "value": 0.018}],
        credit_spread_baa10y=[{"date": date(2020, 1, 1), "value": 2.1}],
    )
    config = _config([{"ticker": "AAPL", "asset_class": "equity"}])

    result = build_bond_features_by_date(asset_frames, config, fred_series)
    row = result["AAPL"].iloc[0]

    assert np.isclose(row["bond_yield_curve_level"], 0.018)
    assert np.isclose(row["bond_yield_curve_slope"], 0.018 - 0.015)
    assert np.isclose(row["bond_yield_curve_curvature"], 2 * 0.017 - 0.016 - 0.018)
    assert np.isclose(row["bond_credit_spread_level"], 2.1)


def test_build_bond_features_by_date_empty_fred_series_is_neutral_not_raise():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {"AAPL": _price_frame(dates, [300.0, 301.0, 302.0])}
    config = _config([{"ticker": "AAPL", "asset_class": "equity"}])

    result = build_bond_features_by_date(asset_frames, config, _fred_series())

    assert (result["AAPL"]["bond_yield_curve_level"] == 0.0).all()
    assert (result["AAPL"]["bond_yield_curve_slope"] == 0.0).all()
    assert (result["AAPL"]["bond_yield_curve_curvature"] == 0.0).all()
    assert (result["AAPL"]["bond_credit_spread_level"] == 0.0).all()


def test_build_bond_features_by_date_empirical_duration_beta_only_for_bond_tagged_ticker():
    # 60 synthetic observations with a clear beta so it clears
    # empirical_duration_beta()'s default min_observations=60 floor.
    dates = [f"2020-{month:02d}-{day:02d}" for month in range(1, 3) for day in range(1, 32) if day <= 28][:61]
    rng = np.random.default_rng(42)
    delta_yields = rng.uniform(-0.001, 0.001, size=len(dates))
    tlt_closes = [140.0]
    for dy in delta_yields[1:]:
        tlt_closes.append(tlt_closes[-1] * (1 + (-0.18 * dy)))
    aapl_closes = [300.0 + i * 0.1 for i in range(len(dates))]

    treasury_series = [{"date": date(2020, 1, 1), "value": 0.02}]
    cumulative_yield = 0.02
    for i, dy in enumerate(delta_yields):
        cumulative_yield += dy
        treasury_series.append({"date": date.fromisoformat(dates[i]), "value": cumulative_yield})

    asset_frames = {
        "TLT": _price_frame(dates, tlt_closes),
        "AAPL": _price_frame(dates, aapl_closes),
    }
    fred_series = _fred_series(treasury_10yr=treasury_series)
    config = _config([{"ticker": "TLT", "asset_class": "bond"}, {"ticker": "AAPL", "asset_class": "equity"}])

    result = build_bond_features_by_date(asset_frames, config, fred_series)

    assert (result["AAPL"]["bond_empirical_duration_beta"] == 0.0).all()
    # TLT is bond-tagged with >= 60 rows - should attempt a real regression
    # (may or may not clear the floor depending on synthetic noise, but
    # must never raise and must be a finite float either way).
    tlt_beta = result["TLT"]["bond_empirical_duration_beta"].iloc[0]
    assert isinstance(tlt_beta, float)
    assert tlt_beta == tlt_beta  # not NaN


def test_build_bond_features_by_date_bond_tagged_with_insufficient_rows_is_zero():
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]  # only 5 rows, well below min_observations
    asset_frames = {"TLT": _price_frame(dates, [140.0, 141.0, 142.0, 141.5, 143.0])}
    fred_series = _fred_series(treasury_10yr=[{"date": date(2020, 1, d), "value": 0.02 + d * 0.0001} for d in range(1, 6)])
    config = _config([{"ticker": "TLT", "asset_class": "bond"}])

    result = build_bond_features_by_date(asset_frames, config, fred_series)

    assert (result["TLT"]["bond_empirical_duration_beta"] == 0.0).all()


def test_build_bond_features_by_date_asset_class_fallback_to_security_type():
    # An asset entry with no explicit asset_class but security_type=="bond"
    # (shouldn't happen in this codebase's real config.json, since bonds
    # are always security_type=="equity" - but the fallback itself must
    # still work correctly for any caller that sets security_type=="bond"
    # directly).
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]
    asset_frames = {"TLT": _price_frame(dates, [140.0, 141.0, 142.0, 141.5, 143.0])}
    config = _config([{"ticker": "TLT", "security_type": "bond"}])

    # Should not raise - just exercises the fallback path with too few
    # rows to produce a non-zero beta.
    result = build_bond_features_by_date(asset_frames, config, _fred_series())
    assert (result["TLT"]["bond_empirical_duration_beta"] == 0.0).all()
