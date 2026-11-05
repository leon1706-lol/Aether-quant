"""portfolio/financing.py: what a broker charges and Lean does not."""

import pytest

from portfolio.financing import daily_financing_usd, load_rate_series, rate_asof


def _amount(**overrides):
    kwargs = dict(long_usd=0.0, short_usd=0.0, nav=100_000.0, rf_annual_pct=4.0, days=1.0, margin_spread_bps=150.0, borrow_bps=25.0, fx_spread_bps=50.0)
    kwargs.update(overrides)
    return daily_financing_usd(**kwargs)


def test_unlevered_long_book_costs_nothing():
    assert _amount(long_usd=100_000.0) == 0.0


def test_debit_beyond_nav_is_charged_at_risk_free_plus_spread():
    assert _amount(long_usd=150_000.0) == pytest.approx(-50_000.0 * 5.5 / 100.0 / 360.0)


def test_short_proceeds_fund_longs_but_the_short_pays_borrow():
    amount = _amount(long_usd=100_000.0, short_usd=50_000.0)
    assert amount == pytest.approx(-50_000.0 * 25.0 / 1e4 / 360.0)


def test_long_base_earns_the_differential_less_the_spread():
    assert _amount(fx_positions=[(10_000.0, 2.0)]) == pytest.approx((200.0 - 50.0) / 360.0)


def test_short_base_pays_the_differential_and_the_spread():
    assert _amount(fx_positions=[(-10_000.0, 2.0)]) == pytest.approx((-200.0 - 50.0) / 360.0)


def test_days_scale_the_charge_and_zero_days_charge_nothing():
    assert _amount(long_usd=150_000.0, days=3.0) == pytest.approx(3.0 * _amount(long_usd=150_000.0))
    assert _amount(long_usd=150_000.0, days=0.0) == 0.0


def test_non_finite_inputs_never_produce_a_non_finite_charge():
    amount = _amount(long_usd=float("nan"), short_usd=float("inf"), rf_annual_pct=float("nan"), fx_positions=[(float("nan"), 1.0)])
    assert amount == amount and abs(amount) != float("inf")


def test_load_rate_series_and_asof(tmp_path):
    path = tmp_path / "rates.csv"
    path.write_text("DATE,PCREDIT8\n2020-01-01,2.5\n2021-01-01,bad\n2022-01-01,1.0\n")
    dates, rates = load_rate_series(path)

    assert dates == ["2020-01-01", "2022-01-01"]
    assert rate_asof(dates, rates, "2019-12-31") == 0.0
    assert rate_asof(dates, rates, "2021-06-01") == 2.5
    assert rate_asof(dates, rates, "2022-01-01") == 1.0


def test_load_rate_series_of_a_missing_file_is_empty(tmp_path):
    assert load_rate_series(tmp_path / "absent.csv") == ([], [])
