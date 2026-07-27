"""Tests for train.py::build_alt_data_features_by_date() (development/
Problems.md #71) - real-data sibling of build_bond_features_by_date() (see
tests/test_train_bond_features.py), backed by
data_pipeline/fred_backfill.py's implied-volatility/financial-conditions
series. The lookahead test at the bottom of this file is the load-bearing
one: it protects against silently manufacturing fake alpha from an
unpublished observation.
"""

from datetime import date

import pandas as pd

from features import (
    FINANCIAL_CONDITIONS_CHANGE_NEUTRAL,
    IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL,
    IMPLIED_VOLATILITY_LEVEL_NEUTRAL,
    implied_vol_term_structure,
    implied_volatility_level,
)
from train import build_alt_data_features_by_date


def _price_frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates), "close": [100.0] * len(dates)})


def _fred_series(**overrides) -> dict:
    series = {
        "implied_volatility_vix": [],
        "implied_volatility_3m": [],
        "financial_conditions_nfci": [],
    }
    series.update(overrides)
    return series


def _row(year: int, month: int, day: int, value: float) -> dict:
    return {"date": date(year, month, day), "value": value}


def test_build_alt_data_features_by_date_adds_columns_to_every_asset_frame():
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]
    asset_frames = {"AAPL": _price_frame(dates), "BTCUSD": _price_frame(dates)}

    result = build_alt_data_features_by_date(asset_frames, {}, _fred_series())

    for ticker, frame in result.items():
        for name in ("alt_implied_volatility_level", "alt_implied_vol_term_structure", "alt_financial_conditions_change"):
            assert name in frame.columns
        assert len(frame) == len(asset_frames[ticker])


def test_build_alt_data_features_by_date_broadcasts_identically_across_tickers():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {"AAPL": _price_frame(dates), "BTCUSD": _price_frame(dates)}
    fred_series = _fred_series(
        implied_volatility_vix=[_row(2020, 1, 1, 15.0), _row(2020, 1, 2, 40.0), _row(2020, 1, 3, 20.0)],
    )

    result = build_alt_data_features_by_date(asset_frames, {}, fred_series)

    assert result["AAPL"]["alt_implied_volatility_level"].tolist() == result["BTCUSD"]["alt_implied_volatility_level"].tolist()


def test_build_alt_data_features_by_date_matches_hand_computation():
    dates = ["2020-01-05"]
    asset_frames = {"AAPL": _price_frame(dates)}
    fred_series = _fred_series(
        implied_volatility_vix=[_row(2020, 1, 1, 20.0)],
        implied_volatility_3m=[_row(2020, 1, 1, 22.0)],
    )

    result = build_alt_data_features_by_date(asset_frames, {}, fred_series)

    row = result["AAPL"].iloc[0]
    assert row["alt_implied_volatility_level"] == implied_volatility_level(20.0)
    assert row["alt_implied_vol_term_structure"] == implied_vol_term_structure(20.0, 22.0)


def test_build_alt_data_features_by_date_empty_fred_series_is_neutral_not_raise():
    dates = ["2020-01-05"]
    asset_frames = {"AAPL": _price_frame(dates)}

    result = build_alt_data_features_by_date(asset_frames, {}, _fred_series())

    row = result["AAPL"].iloc[0]
    assert row["alt_implied_volatility_level"] == IMPLIED_VOLATILITY_LEVEL_NEUTRAL
    assert row["alt_implied_vol_term_structure"] == IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL
    assert row["alt_financial_conditions_change"] == FINANCIAL_CONDITIONS_CHANGE_NEUTRAL


def test_build_alt_data_features_by_date_partial_series_neutral_defaults_only_missing_one():
    dates = ["2020-01-05"]
    asset_frames = {"AAPL": _price_frame(dates)}
    # VIX present, VXV absent - term structure should neutral-default
    # (needs both legs) but level should NOT (only needs VIX).
    fred_series = _fred_series(implied_volatility_vix=[_row(2020, 1, 1, 30.0)])

    result = build_alt_data_features_by_date(asset_frames, {}, fred_series)

    row = result["AAPL"].iloc[0]
    assert row["alt_implied_volatility_level"] == implied_volatility_level(30.0)
    assert row["alt_implied_vol_term_structure"] == IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL


def test_build_alt_data_features_by_date_config_lag_override_is_respected():
    dates = ["2020-03-23"]  # 3 days after the Friday NFCI observation below
    asset_frames = {"AAPL": _price_frame(dates)}
    fred_series = _fred_series(
        financial_conditions_nfci=[
            _row(2020, 2, 21, 0.10),
            _row(2020, 2, 28, 0.20),
            _row(2020, 3, 6, 0.30),
            _row(2020, 3, 13, 0.40),
            _row(2020, 3, 20, 0.90),
        ]
    )
    config_default_lag = {"phase1": {"features": {"alt_data_financial_conditions_change_periods": 4}}}
    # Default lag (7 days): 2020-03-23 - 7 = 2020-03-16, before the
    # 2020-03-20 observation was published - not yet visible.
    result_default = build_alt_data_features_by_date(asset_frames, config_default_lag, fred_series)
    assert result_default["AAPL"].iloc[0]["alt_financial_conditions_change"] == FINANCIAL_CONDITIONS_CHANGE_NEUTRAL

    # Override lag to 0 - the 2020-03-20 observation becomes immediately
    # visible, so 4-periods-back change = 0.90 - 0.10.
    config_zero_lag = {
        "phase1": {
            "features": {
                "alt_data_financial_conditions_change_periods": 4,
                "alt_data_publication_lag_days": {"financial_conditions_nfci": 0},
            }
        }
    }
    result_zero_lag = build_alt_data_features_by_date(asset_frames, config_zero_lag, fred_series)
    assert result_zero_lag["AAPL"].iloc[0]["alt_financial_conditions_change"] == 0.90 - 0.10


def test_build_alt_data_features_by_date_weekly_series_never_uses_unpublished_value():
    # The load-bearing lookahead test. NFCI is Friday-dated but released
    # the following Wednesday (+5 calendar days) - default lag is 7 (a
    # conservative superset). For every business day in the frame, the
    # feature must reflect only observations published strictly before
    # that decision date, never the observation dated on-or-just-before it
    # that hasn't actually been released yet.
    dates = [f"2020-03-{day:02d}" for day in range(16, 28)]  # 2020-03-16 .. 2020-03-27
    asset_frames = {"AAPL": _price_frame(dates)}
    fred_series = _fred_series(
        financial_conditions_nfci=[
            _row(2020, 2, 21, 0.10),
            _row(2020, 2, 28, 0.20),
            _row(2020, 3, 6, 0.30),
            _row(2020, 3, 13, 0.40),
            # The critical row: dated Friday 2020-03-20, but real-world
            # release is Wednesday 2020-03-25.
            _row(2020, 3, 20, 999.0),  # extreme sentinel value - must not leak early
        ]
    )

    result = build_alt_data_features_by_date(asset_frames, {}, fred_series)
    frame = result["AAPL"]

    # On every date strictly before the +7-day publication (i.e. before
    # 2020-03-27), the sentinel 999.0 observation must not have been used
    # to compute the change - the change value must equal what it would
    # be using only the 4 pre-sentinel observations (0.10, 0.20, 0.30, 0.40)
    # -> insufficient history (only 4 exist, periods_back=4 needs 5) -> neutral.
    for _, row in frame[frame["date"] < pd.Timestamp("2020-03-27")].iterrows():
        assert row["alt_financial_conditions_change"] == FINANCIAL_CONDITIONS_CHANGE_NEUTRAL, (
            f"date {row['date']} used an unpublished observation"
        )

    # On/after the publication date, the sentinel becomes visible and
    # participates in the change computation (dominates it, given its
    # magnitude) - proving the guard doesn't just permanently suppress it.
    published_rows = frame[frame["date"] >= pd.Timestamp("2020-03-27")]
    assert not published_rows.empty
    for _, row in published_rows.iterrows():
        assert row["alt_financial_conditions_change"] != FINANCIAL_CONDITIONS_CHANGE_NEUTRAL


def test_build_alt_data_features_by_date_change_endpoints_both_respect_publication_lag():
    # Both endpoints of the change computation must come from the SAME
    # lag-adjusted index - i.e. an unpublished "now" endpoint must not
    # silently fall back to an earlier value while still claiming a full
    # periods_back change (series_change_asof()'s single-bisect design
    # already guarantees this by construction; this test locks the
    # observable behavior in place).
    dates = ["2020-03-21"]  # one day after the Friday NFCI row, still unpublished under the default 7-day lag
    asset_frames = {"AAPL": _price_frame(dates)}
    fred_series = _fred_series(
        financial_conditions_nfci=[
            _row(2020, 2, 21, 0.10),
            _row(2020, 2, 28, 0.20),
            _row(2020, 3, 6, 0.30),
            _row(2020, 3, 13, 0.40),
            _row(2020, 3, 20, 0.90),
        ]
    )

    result = build_alt_data_features_by_date(asset_frames, {}, fred_series)

    # As of 2020-03-21, only 4 observations are published (0.10..0.40) -
    # a 4-periods-back change needs a 5th, so this must neutral-default,
    # not compute some partial/incorrect change using the unpublished 0.90.
    assert result["AAPL"].iloc[0]["alt_financial_conditions_change"] == FINANCIAL_CONDITIONS_CHANGE_NEUTRAL
