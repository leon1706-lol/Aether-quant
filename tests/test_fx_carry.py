"""features/fx_carry.py (V5.7.0): the 3-month rate differential of a forex pair, lag-aware and 0.0 elsewhere."""

from datetime import date

import pytest

from features.fx_carry import (
    CURRENCY_RATE_SERIES,
    FX_CARRY_FEATURE_NAME,
    FX_RATE_PUBLICATION_LAG_DAYS,
    fx_carry_3m,
    split_forex_ticker,
)


def _series(**levels):
    """{key: [{"date", "value"}]} from {key: [(date, value), ...]}"""
    return {key: [{"date": day, "value": value} for day, value in rows] for key, rows in levels.items()}


FRED = _series(
    treasury_3mo=[(date(2020, 1, 2), 1.50), (date(2020, 3, 2), 0.50)],
    interbank_3m_jpy=[(date(2020, 1, 1), -0.10), (date(2020, 3, 1), -0.05)],
    interbank_3m_aud=[(date(2020, 1, 1), 0.90), (date(2020, 3, 1), 0.60)],
)


def test_feature_name_and_currency_table_are_consistent():
    assert FX_CARRY_FEATURE_NAME == "fx_carry_3m"
    assert set(CURRENCY_RATE_SERIES) == {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}
    assert FX_RATE_PUBLICATION_LAG_DAYS["treasury_3mo"] == 0 and FX_RATE_PUBLICATION_LAG_DAYS["interbank_3m_eur"] == 45


@pytest.mark.parametrize("ticker,expected", [("EURUSD", ("EUR", "USD")), ("audjpy", ("AUD", "JPY")), ("BTCUSD", None), ("AAPL", None), ("EURXXX", None)])
def test_split_forex_ticker(ticker, expected):
    assert split_forex_ticker(ticker) == expected


def test_carry_is_base_rate_minus_quote_rate():
    value = fx_carry_3m("AUDJPY", "forex", date(2020, 3, 1) , FRED)
    # the 2020-03-01 monthly rates are not usable yet (45 days); the January observations are
    assert value == pytest.approx(0.90 - (-0.10))
    assert fx_carry_3m("AUDJPY", "forex", date(2020, 5, 1), FRED) == pytest.approx(0.60 - (-0.05))


def test_usd_leg_uses_the_daily_bill_without_a_lag():
    assert fx_carry_3m("AUDUSD", "forex", date(2020, 2, 20), FRED) == pytest.approx(0.90 - 1.50)
    assert fx_carry_3m("AUDUSD", "forex", date(2020, 3, 2), FRED) == pytest.approx(0.90 - 0.50)


def test_a_monthly_observation_is_never_used_before_its_publication_lag():
    # 2020-01-01 AUD rate becomes usable on 2020-02-15; before that no rate exists -> 0.0, not a guess
    assert fx_carry_3m("AUDJPY", "forex", date(2020, 2, 14), FRED) == 0.0
    assert fx_carry_3m("AUDJPY", "forex", date(2020, 2, 15), FRED) != 0.0


def test_non_forex_unknown_pairs_and_missing_series_are_zero():
    assert fx_carry_3m("AAPL", "equity", date(2020, 6, 1), FRED) == 0.0
    assert fx_carry_3m("BTCUSD", "forex", date(2020, 6, 1), FRED) == 0.0
    assert fx_carry_3m("EURUSD", "forex", date(2020, 6, 1), FRED) == 0.0  # no EUR series cached
    assert fx_carry_3m("AUDJPY", "forex", date(2020, 6, 1), {}) == 0.0


def test_lag_overrides_are_honoured():
    assert fx_carry_3m("AUDJPY", "forex", date(2020, 1, 20), FRED, {"interbank_3m_aud": 0, "interbank_3m_jpy": 0}) == pytest.approx(1.0)
