"""The last unreached branches of features/ (V6.6.6, #359)."""

from __future__ import annotations

import pytest

import features.options_greeks as greeks
from features.options_greeks import baw_american_price


def _european(spot, strike, t, r, q, vol, right):
    return greeks.bs_price(spot, strike, t, r, vol, q, right)


def test_an_american_call_without_a_dividend_or_a_put_without_a_rate_is_the_european_price():
    assert baw_american_price(100.0, 100.0, 1.0, 0.05, 0.0, 0.3, "call") == _european(100.0, 100.0, 1.0, 0.05, 0.0, 0.3, "call")
    assert baw_american_price(100.0, 100.0, 1.0, 0.0, 0.0, 0.3, "put") == _european(100.0, 100.0, 1.0, 0.0, 0.0, 0.3, "put")


def test_deep_in_the_money_options_are_worth_their_intrinsic_value():
    assert baw_american_price(1000.0, 100.0, 1.0, 0.05, 0.05, 0.3, "call") == 900.0
    assert baw_american_price(10.0, 100.0, 1.0, 0.05, 0.0, 0.3, "put") == 90.0


def test_a_search_that_does_not_converge_in_time_falls_back_to_the_european_price():
    args = (80.0, 100.0, 1.0, 0.05, 0.0, 0.3, "put")
    assert baw_american_price(*args, max_iterations=1, tolerance=1e-15) == _european(*args)


def test_an_exact_zero_or_a_same_sign_residual_is_handled(monkeypatch):
    put = (95.0, 100.0, 1.0, 0.05, 0.0, 0.3, "put")
    monkeypatch.setattr(greeks, "_normal_cdf", lambda x: 1.0)  # with no dividend the matching term vanishes

    def priced(other):
        return lambda spot, strike, t, r, vol, q, right: 7.0 if spot == 95.0 else other(spot, strike)

    monkeypatch.setattr(greeks, "bs_price", priced(lambda spot, strike: -1000.0))  # the residual is positive at both bounds
    assert baw_american_price(*put) == 7.0
    monkeypatch.setattr(greeks, "bs_price", priced(lambda spot, strike: strike - spot))  # exactly zero at the lower bound
    assert baw_american_price(*put) >= 7.0
    monkeypatch.setattr(greeks, "bs_price", priced(lambda spot, strike: strike - spot + (1e-3 if spot < strike / 2 else 0.0)))  # zero at the upper bound only
    assert baw_american_price(*put) == 5.0, "spot below the critical price: exercised at once"


def test_a_put_has_a_theta_and_an_unsolvable_price_has_no_implied_volatility():
    assert isinstance(greeks.theta(100.0, 100.0, 1.0, 0.05, 0.3, 0.02, "put"), float)
    fair = greeks.bs_price(100.0, 100.0, 1.0, 0.05, 0.3, 0.0, "call")
    assert greeks.implied_volatility(fair, 100.0, 100.0, 1.0, 0.05, 0.0, "call") == pytest.approx(0.3, abs=1e-4)
    assert greeks.implied_volatility(99.0, 100.0, 100.0, 1.0, 0.05, 0.0, "call") is None, "above the price at 500% volatility"
    assert greeks.implied_volatility(fair, 100.0, 100.0, 1.0, 0.05, 0.0, "call", max_iterations=1, tolerance=1e-15) is None


def test_duration_beta_helpers_refuse_non_finite_data_and_keep_the_scalar_path():
    import numpy as np

    from features import bond_features as bonds

    ys = [0.001 * ((i * 7) % 5 - 2) for i in range(60)]
    xs = [0.0004 * ((i * 3) % 7 - 3) for i in range(60)]
    assert bonds._vector_duration_beta([*ys[:-1], float("inf")], xs, 5) is bonds._USE_SCALAR
    assert bonds.duration_beta_from_arrays(np.array([*ys[:-1], np.inf]), np.array(xs), 5) is None
    assert bonds.resolve_bond_duration_beta_mode({"bond_duration_beta": {"mode": "rolling", "lookback": "many"}}) == ("rolling", bonds.BOND_DURATION_BETA_LOOKBACK)


@pytest.mark.parametrize("function", ["analytic_modified_duration", "analytic_convexity"])
def test_analytic_bond_measures_return_none_for_missing_or_degenerate_inputs(function, monkeypatch):
    from features import bond_features as bonds

    measure = getattr(bonds, function)
    assert measure(0.04, 0.05, 10.0) is not None
    assert measure(None, 0.05, 10.0) is None and measure(0.04, 0.05, 0.0) is None
    assert measure(-2.5, 0.05, 10.0) is None, "a period yield of -1 or worse has no price"
    assert measure(0.04, 0.05, 0.01) is None, "less than one coupon period"
    assert bonds._bond_cash_flows(0.05, 0.0, 2) == []
    monkeypatch.setattr(bonds, "_bond_cash_flows", lambda *args, **kwargs: [0.0, 0.0])
    assert measure(0.04, 0.05, 10.0) is None, "a bond worth nothing has no duration"


def test_momentum_and_cross_section_helpers_degrade_on_thin_or_flat_data():
    import math

    from features import fx_signals
    from features.cross_asset_timing import momentum_from_closes, returns_from_closes

    assert fx_signals.ts_momentum_score([1.0, 1.1], lookbacks=(1,), vol_window=1) is None, "one return is not a volatility"
    assert fx_signals.ts_momentum_score([1.0] * 70, lookbacks=(60,)) is None, "no volatility"
    assert fx_signals._zscores({"A": 1.0}) == {"A": 0.0} and fx_signals._zscores({"A": 1.0, "B": 1.0}) == {"A": 0.0, "B": 0.0}
    assert fx_signals._zscores({"A": 1.0, "B": 3.0, "C": None, "D": math.nan}) == pytest.approx({"A": -math.sqrt(0.5), "B": math.sqrt(0.5)})
    assert momentum_from_closes([1.0]) is None and momentum_from_closes([0.0, 1.0]) is None
    assert returns_from_closes([0.0, 1.0, 2.0]) == [1.0]


def test_the_forex_calendar_is_read_only_when_asked(tmp_path):
    import json

    from features.cross_asset_timing import resolve_forex_lean_holidays

    assert resolve_forex_lean_holidays({}) == frozenset() and resolve_forex_lean_holidays({"phase1": {"features": {"forex_lean_holidays": False}}}) == frozenset()
    (tmp_path / "data" / "market-hours").mkdir(parents=True)
    (tmp_path / "data" / "market-hours" / "market-hours-database.json").write_text(json.dumps({"entries": {"Forex-oanda-[*]": {"holidays": ["12/25/2023"]}}}), encoding="utf-8")
    assert isinstance(resolve_forex_lean_holidays({"phase1": {"features": {"forex_lean_holidays": True}}}, tmp_path), frozenset)


def test_label_purging_and_folds_skip_unlabelled_rows_and_empty_folds():
    import numpy as np

    from features.training_splits import purge_label_overlap_calendar, purged_embargoed_folds

    dates = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"]
    assert purge_label_overlap_calendar(["train", None, "validation", "backtest"], dates, 5) == ["purged", None, "purged", "backtest"]
    stamps = np.array(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05", "2020-01-06"], dtype="datetime64[D]")
    folds = purged_embargoed_folds(stamps, n_folds=3, horizon_days=1, embargo_days=0)
    assert folds and all(len(train) and len(validation) for train, validation in folds)
    assert purged_embargoed_folds(stamps, n_folds=3, horizon_days=100, embargo_days=100) == [], "everything purged: no usable fold"


def test_a_degenerate_residualisation_returns_the_returns_unchanged(monkeypatch):
    import numpy as np

    from features.asof_beta_labels import cross_sectional_residualize

    returns = np.array([0.01, -0.02, 0.03])
    design = np.column_stack([np.ones(3), np.array([1.0, 2.0, 3.0])])
    assert cross_sectional_residualize(returns, design[:0]) is returns and cross_sectional_residualize(returns[:1], design[:1]) is not None
    assert cross_sectional_residualize(returns, np.zeros((3, 2))) is returns, "rank 0"
    assert cross_sectional_residualize(np.array([0.01, np.inf, 0.03]), design) is not None

    def singular(*args, **kwargs):
        raise np.linalg.LinAlgError("did not converge")

    monkeypatch.setattr(np.linalg, "lstsq", singular)
    assert cross_sectional_residualize(returns, design) is returns


def test_the_cross_sectional_settings_ignore_what_is_not_a_number():
    from features.cross_sectional_inputs import _finite, resolve_cross_sectional_inputs

    assert resolve_cross_sectional_inputs({"enabled": True, "min_group_size": "many"})["min_group_size"] == 5
    assert _finite("x") is None and _finite(float("inf")) is None and _finite("2.5") == 2.5
    assert resolve_cross_sectional_inputs({"enabled": False}) is None and resolve_cross_sectional_inputs(None) is None
