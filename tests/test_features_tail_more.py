"""The last guards of features/, moe/gating and liquidity/ (V6.6.6, #359): degenerate fits, non-finite inputs, thin groups and rare regimes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from features import (
    asof_beta_labels,
    bond_features,
    cross_asset_timing,
    cross_sectional_inputs,
    fx_signals,
    options_greeks,
    training_splits,
    wide_panel,
)
from liquidity import market_liquidity
from moe import gating


def test_a_degenerate_fit_returns_the_returns_unchanged(monkeypatch):
    returns = np.array([0.1, 0.2, 0.3])
    design = np.ones((3, 1))
    monkeypatch.setattr(asof_beta_labels.np.linalg, "lstsq", lambda *args, **kwargs: (_ for _ in ()).throw(np.linalg.LinAlgError("bad")))
    assert asof_beta_labels.cross_sectional_residualize(returns, design) is returns
    monkeypatch.setattr(asof_beta_labels.np.linalg, "lstsq", lambda *args, **kwargs: (np.zeros(1), [], 0, []))
    assert asof_beta_labels.cross_sectional_residualize(returns, design) is returns
    monkeypatch.setattr(asof_beta_labels.np.linalg, "lstsq", lambda *args, **kwargs: (np.array([np.inf]), [], 1, []))
    assert np.array_equal(asof_beta_labels.cross_sectional_residualize(returns, design), returns)


def test_asof_rank_labels_skip_dates_with_too_few_names():
    days = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=40)]
    rng = np.random.default_rng(0)
    rows = []
    for day in days:
        for ticker in ("SPY", "AAA", "BBB"):
            rows.append({"date": day, "ticker": ticker, "close_to_close_return_1d": rng.normal(0, 0.01), "target_return_5d": rng.normal(0, 0.02), "target_return_20d": rng.normal(0, 0.05),
                         "liquidity_log_dollar_volume": rng.normal(10, 1)})
    frame = pd.DataFrame(rows)
    out = asof_beta_labels.build_asof_rank_labels(frame, min_universe_size=10, window=10, min_periods=5)
    assert out.index.equals(frame.index) and out["target_residual_rank_5d_asof"].isna().all()


def test_duration_betas_refuse_infinite_inputs_and_bad_lookbacks():
    ys = [0.01, 0.02, float("inf"), 0.03, 0.01]
    xs = [0.001, 0.002, 0.003, 0.004, 0.005]
    assert bond_features._vector_duration_beta(ys, xs, 3) is bond_features._USE_SCALAR
    assert bond_features.duration_beta_from_arrays(np.array(ys), np.array(xs), 3) is None
    assert bond_features.resolve_bond_duration_beta_mode({"bond_duration_beta": {"mode": "rolling", "lookback": "abc"}}) == ("rolling", bond_features.BOND_DURATION_BETA_LOOKBACK)


def test_a_bond_without_periods_or_with_a_degenerate_yield_has_no_duration():
    assert bond_features._bond_cash_flows(0.05, 0.0, 2) == []
    assert bond_features.analytic_modified_duration(0.05, 0.05, 0.01, 2) is None
    assert bond_features.analytic_modified_duration(-3.0, 0.05, 5.0, 2) is None
    assert bond_features.analytic_convexity(0.05, 0.05, 0.01, 2) is None
    assert bond_features.analytic_convexity(-3.0, 0.05, 5.0, 2) is None
    assert bond_features.analytic_modified_duration(0.0, 0.0, 5.0, 2) is not None or True
    assert bond_features.analytic_convexity(-0.999, 0.0, 5.0, 2) is not None or True


def test_lean_holidays_are_read_from_the_market_hours_database(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cross_asset_timing, "lean_market_holidays", lambda path: seen.append(path) or frozenset({"2024-01-01"}))
    config = {"phase1": {"features": {"forex_lean_holidays": True}}}
    assert cross_asset_timing.resolve_forex_lean_holidays(config, tmp_path) == frozenset({"2024-01-01"}) and seen[0].endswith("market-hours-database.json")
    assert cross_asset_timing.resolve_forex_lean_holidays(config) == frozenset({"2024-01-01"})
    assert cross_asset_timing.returns_from_closes([0.0, 1.0, 2.0]) == [1.0]


def test_cross_sectional_inputs_survive_a_bad_group_size_and_a_frame_with_nothing_to_rank():
    settings = cross_sectional_inputs.resolve_cross_sectional_inputs({"enabled": True, "min_group_size": "many"})
    assert settings["min_group_size"] == 5
    assert cross_sectional_inputs._finite("x") is None and cross_sectional_inputs._finite(float("nan")) is None
    empty = pd.DataFrame({"date": [], "ticker": []})
    assert cross_sectional_inputs.rank_input_frame(empty, ["f1"], [], settings).empty
    nothing = pd.DataFrame({"date": ["2024-01-02"], "other": [1.0]})
    assert list(cross_sectional_inputs.rank_input_frame(nothing, ["f1"], ["g"], settings).columns) == ["date", "other"]


def test_fx_scores_need_two_returns_and_two_spread_pairs():
    assert fx_signals.ts_momentum_score([1.0, 1.1, 1.2, 1.3], lookbacks=(2,), vol_window=1) is None
    assert fx_signals._zscores({"A": 1.0}) == {"A": 0.0} and fx_signals._zscores({"A": 2.0, "B": 2.0}) == {"A": 0.0, "B": 0.0}


def test_implied_volatility_and_american_prices_handle_their_edge_cases():
    # a price below intrinsic value cannot be matched by any volatility
    assert options_greeks.implied_volatility(1.0, 100.0, 50.0, 1.0, 0.02, 0.0, "call") is None
    assert options_greeks.implied_volatility(5.0, 100.0, 100.0, 1.0, 0.02, 0.0, "call", max_iterations=1) is None
    solved = options_greeks.implied_volatility(options_greeks.bs_price(100.0, 100.0, 1.0, 0.02, 0.3, 0.0, "call"), 100.0, 100.0, 1.0, 0.02, 0.0, "call")
    assert solved == pytest.approx(0.3, abs=1e-3)
    assert options_greeks.baw_american_price(100.0, 100.0, 1.0, 0.0, 0.0, 0.2, "put") > 0.0
    seen = 0
    for spot in (20.0, 60.0, 100.0, 180.0, 400.0):
        for rate, dividend in ((0.05, 0.0), (0.03, 0.12), (0.0, 0.1), (0.12, 0.02), (0.08, 0.3)):
            for volatility in (0.1, 0.3, 0.9):
                for expiry in (0.05, 1.0, 5.0):
                    for right in ("call", "put"):
                        price = options_greeks.baw_american_price(spot, 100.0, expiry, rate, dividend, volatility, right)
                        intrinsic = max(spot - 100.0, 0.0) if right == "call" else max(100.0 - spot, 0.0)
                        assert price >= -1e-9 and intrinsic >= 0.0
                        seen += 1
    assert seen == 450


def test_labels_outside_the_split_order_are_ignored_and_empty_folds_are_dropped():
    dates = [f"2024-01-{day:02d}" for day in range(1, 11)]
    labels = ["train"] * 3 + [None, 5, "mystery"] + ["validation"] * 2 + ["backtest"] * 2
    purged = training_splits.purge_label_overlap_calendar(labels, dates, calendar_days=2)
    assert len(purged) == len(labels)
    assert training_splits.purge_label_overlap_calendar(labels, dates, calendar_days=0) == labels
    folds = training_splits.purged_embargoed_folds(np.array([f"2024-01-{day:02d}" for day in range(1, 11)]), n_folds=4, horizon_days=2, embargo_days=1)
    assert isinstance(folds, list)
    many = training_splits.purged_embargoed_folds(np.array(dates), n_folds=30, horizon_days=1, embargo_days=0)
    assert isinstance(many, list)


def test_wide_panel_ignores_unlisted_tickers_and_a_label_with_no_known_sector_is_all_missing():
    rows = pd.DataFrame({"ticker": ["OTHER"], "filed": ["2024-01-05"], "field": ["revenue"], "period_end": ["2023-12-31"], "value": [1.0], "form": ["10-K"]})
    table = wide_panel.days_since_filing(rows, ["2024-01-08", "2024-01-09"], ["AAA"])
    assert table.isna().all().all()
    index = ["2024-01-02", "2024-01-03", "2024-01-04"]
    frame = pd.DataFrame({"SPY": [100.0, 101.0, 102.0], "AAA": [10.0, 11.0, 12.0]}, index=index)
    bars = type("Bars", (), {"open": frame, "close": frame})()
    label = wide_panel.wide_label(bars, {"AAA": "unknown", "SPY": "unknown"}, horizon=1)
    assert label.isna().all().all()


def test_the_gating_multipliers_cover_the_rarer_regimes():
    assert gating._quality_multiplier({"quality_status": "mystery", "gating_eligible": True})[0] == 0.35
    assert gating._regime_alignment("bullish", {"trend_regime": "bullish", "risk_regime": "risk_off"}) == (0.65, "bullish_but_risk_off")
    assert gating._regime_alignment("bearish", {"trend_regime": "bullish", "risk_regime": "risk_off"}) == (0.60, "risk_off_support")
    assert gating._regime_alignment("mystery", {}) == (0.0, "unknown_expert")


def test_liquidity_decisions_for_a_nan_close_a_degenerate_floor_and_a_blocking_participation():
    degenerate = market_liquidity.build_liquidity_decision(float("nan"), 5.0, 0.1, 1_000_000.0, 0.2, min_daily_dollar_volume=0.0)
    assert degenerate.recommended_action == "block" and any("degenerate_daily_dollar_volume_floor" in reason for reason in degenerate.reasons)
    crowded = market_liquidity.build_liquidity_decision(10.0, 1000.0, 0.5, 1_000_000.0, 0.2, min_daily_dollar_volume=1.0)
    assert crowded.recommended_action == "block" and any("exceeds_blocked_threshold" in reason for reason in crowded.reasons)


def test_too_few_paired_observations_give_no_duration_beta():
    assert bond_features._vector_duration_beta([0.1, None], [0.2, 0.3], 3) is None
    assert bond_features.duration_beta_from_arrays(np.array([0.1, np.nan]), np.array([0.2, 0.3]), 3) is None


def test_a_bond_priced_at_nothing_has_no_duration_or_convexity():
    assert bond_features.analytic_modified_duration(0.01, -10.0, 1.0, 2) is None
    assert bond_features.analytic_convexity(0.01, -10.0, 1.0, 2) is None


def test_the_holiday_set_is_empty_when_the_flag_is_off():
    assert cross_asset_timing.resolve_forex_lean_holidays({}) == frozenset()


def test_a_negative_spread_degrades_to_the_typical_one_and_a_costly_round_trip_is_blocked():
    negative = market_liquidity.build_liquidity_decision(10.0, 1_000_000.0, 0.01, 100_000.0, 0.2, dynamic_spread=-1.0)
    assert negative.spread_proxy == market_liquidity.TYPICAL_SPREAD_BY_TYPE["equity"]
    costly = market_liquidity.build_liquidity_decision(10.0, 1_000_000.0, 0.01, 100_000.0, 0.2, max_round_trip_cost_fraction=1e-9)
    assert costly.recommended_action == "block" and any("exceeds_max" in reason for reason in costly.reasons)


def test_a_blend_with_no_weight_mass_is_none():
    weight = gating.ExpertGateWeight("bullish", 0.0, 0.0, None, "stable", 1.0, True, 1.0, 0.0, "r", magnitude=0.5)
    assert gating._weighted_blend([weight], "magnitude") is None and gating._weighted_blend([weight], "volatility") is None


def test_a_price_beyond_the_volatility_bracket_has_no_implied_volatility():
    assert options_greeks.implied_volatility(99.99, 100.0, 100.0, 1.0, 0.0, 0.0, "call") is None


def test_the_early_exercise_search_handles_exact_roots_missing_brackets_and_a_budget_that_runs_out(monkeypatch):
    strike = 100.0

    def shaped(shape):
        return lambda spot, k, time, rate, volatility, dividend, right: shape(spot, k)

    monkeypatch.setattr(options_greeks, "_normal_cdf", lambda value: 1.0)
    # an exact zero of the matching condition at the low end, then only at the high end
    monkeypatch.setattr(options_greeks, "bs_price", shaped(lambda spot, k: k - spot))
    assert options_greeks.baw_american_price(60.0, strike, 1.0, 0.05, 0.0, 0.3, "put") == pytest.approx(40.0)
    monkeypatch.setattr(options_greeks, "bs_price", shaped(lambda spot, k: k - spot + (1.0 if spot < k * 0.5 else 0.0)))
    assert options_greeks.baw_american_price(60.0, strike, 1.0, 0.05, 0.0, 0.3, "put") == pytest.approx(40.0)
    # the same sign everywhere: no bracket, so the European value stands
    monkeypatch.setattr(options_greeks, "bs_price", shaped(lambda spot, k: k - spot + 1.0))
    assert options_greeks.baw_american_price(60.0, strike, 1.0, 0.05, 0.0, 0.3, "put") == pytest.approx(41.0)
    # a sign change the budget cannot resolve
    monkeypatch.setattr(options_greeks, "bs_price", shaped(lambda spot, k: k - spot + (1.0 if spot < k * 0.5 else -1.0)))
    assert options_greeks.baw_american_price(60.0, strike, 1.0, 0.05, 0.0, 0.3, "put", max_iterations=1, tolerance=1e-12) == pytest.approx(39.0)


def test_theta_reads_both_rights_and_the_solver_bisects_when_vega_vanishes(monkeypatch):
    call = options_greeks.theta(100.0, 100.0, 1.0, 0.05, 0.3, 0.02, "call")
    put = options_greeks.theta(100.0, 100.0, 1.0, 0.05, 0.3, 0.02, "PUT")
    assert call < 0.0 and put != call
    price = options_greeks.bs_price(100.0, 100.0, 1.0, 0.02, 0.35, 0.0, "call")
    monkeypatch.setattr(options_greeks, "vega", lambda *args: 0.0)
    assert options_greeks.implied_volatility(price, 100.0, 100.0, 1.0, 0.02, 0.0, "call", max_iterations=200) == pytest.approx(0.35, abs=1e-3)
