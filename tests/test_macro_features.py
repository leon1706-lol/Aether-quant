import math

from features.macro_features import (
    CREDIT_SPREAD_NEUTRAL,
    CRYPTO_RISK_APPETITE_NEUTRAL,
    YIELD_CURVE_SLOPE_NEUTRAL,
    credit_spread_proxy,
    crypto_risk_appetite_proxy,
    yield_curve_slope_proxy,
)


def test_yield_curve_slope_proxy_is_long_minus_short_momentum():
    assert yield_curve_slope_proxy(0.05, 0.01) == 0.04
    assert yield_curve_slope_proxy(0.01, 0.05) == -0.04


def test_yield_curve_slope_proxy_neutral_when_long_missing():
    assert yield_curve_slope_proxy(None, 0.01) == YIELD_CURVE_SLOPE_NEUTRAL


def test_yield_curve_slope_proxy_neutral_when_short_missing():
    assert yield_curve_slope_proxy(0.05, None) == YIELD_CURVE_SLOPE_NEUTRAL


def test_yield_curve_slope_proxy_neutral_when_both_missing():
    assert yield_curve_slope_proxy(None, None) == YIELD_CURVE_SLOPE_NEUTRAL


def test_credit_spread_proxy_is_high_yield_minus_investment_grade_momentum():
    assert math.isclose(credit_spread_proxy(0.02, 0.05), -0.03)
    assert math.isclose(credit_spread_proxy(0.05, 0.02), 0.03)


def test_credit_spread_proxy_neutral_when_high_yield_missing():
    assert credit_spread_proxy(None, 0.02) == CREDIT_SPREAD_NEUTRAL


def test_credit_spread_proxy_neutral_when_investment_grade_missing():
    assert credit_spread_proxy(0.02, None) == CREDIT_SPREAD_NEUTRAL


def test_crypto_risk_appetite_proxy_passes_through_momentum():
    assert crypto_risk_appetite_proxy(0.12) == 0.12
    assert crypto_risk_appetite_proxy(-0.08) == -0.08


def test_crypto_risk_appetite_proxy_neutral_when_missing():
    assert crypto_risk_appetite_proxy(None) == CRYPTO_RISK_APPETITE_NEUTRAL
