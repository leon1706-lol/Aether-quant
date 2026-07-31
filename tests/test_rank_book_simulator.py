import numpy as np
import pandas as pd
import pytest

from evaluation.rank_book_simulator import (
    RankBookSimulationResult,
    capacity_curve,
    simulate_rank_book,
    stress_test_costs,
    summarize_metric_stability,
)


def _synthetic_frame(num_tickers=20, num_days=60, seed=0):
    """A universe where each ticker has a fixed 'skill' score baked into
    BOTH its prediction and its forward return, so a well-formed book
    should show a genuine positive gross Sharpe - the known-IC fixture
    every other test in this file builds on."""
    rng = np.random.default_rng(seed)
    tickers = [f"T{i}" for i in range(num_tickers)]
    dates = pd.bdate_range("2020-01-01", periods=num_days)

    rows = []
    for date in dates:
        for index, ticker in enumerate(tickers):
            skill = (index - num_tickers / 2) / (num_tickers / 2)  # -1..1
            prediction = skill + rng.normal(0, 0.4)
            forward_return = skill * 0.003 + rng.normal(0, 0.01)
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "pred": prediction,
                    "target_return_1d": forward_return,
                    "liquidity_log_dollar_volume": np.log(1e7 + index * 1e6),
                }
            )
    return pd.DataFrame(rows)


def _base_kwargs(**overrides):
    kwargs = dict(
        prediction_column="pred",
        forward_return_column="target_return_1d",
        ticker_column="ticker",
        date_column="date",
        top_n=4,
        bottom_n=4,
        rebalance_every_bars=5,
        cost_bps_per_side=0.0,
        commission_bps=0.0,
        gross_exposure=1.0,
        dollar_neutral=True,
        sector_neutral=False,
        max_weight_per_name=0.5,
        min_universe_size=10,
    )
    kwargs.update(overrides)
    return kwargs


def test_known_ic_frame_produces_positive_gross_sharpe():
    frame = _synthetic_frame()
    result = simulate_rank_book(frame, **_base_kwargs())
    assert isinstance(result, RankBookSimulationResult)
    assert result.gross_sharpe > 0
    assert result.num_dates_used > 0


def test_zero_cost_makes_net_equal_gross_exactly():
    frame = _synthetic_frame()
    result = simulate_rank_book(frame, **_base_kwargs(cost_bps_per_side=0.0, commission_bps=0.0))
    assert result.net_sharpe == pytest.approx(result.gross_sharpe)
    assert result.net_total_return == pytest.approx(result.gross_total_return)
    assert result.cost_drag_annual_bps == pytest.approx(0.0)


def test_nonzero_cost_makes_net_sharpe_strictly_less_than_gross():
    frame = _synthetic_frame()
    result = simulate_rank_book(frame, **_base_kwargs(cost_bps_per_side=5.0, commission_bps=1.0))
    assert result.net_sharpe < result.gross_sharpe
    assert result.cost_drag_annual_bps > 0.0


def test_turnover_falls_monotonically_as_rebalance_cadence_slows():
    frame = _synthetic_frame()
    turnovers = [
        simulate_rank_book(frame, **_base_kwargs(rebalance_every_bars=n)).annualized_turnover
        for n in (1, 5, 20)
    ]
    assert turnovers[0] > turnovers[1] > turnovers[2]


def test_turnover_falls_as_hysteresis_margin_widens():
    frame = _synthetic_frame()
    tight = simulate_rank_book(frame, **_base_kwargs(hysteresis_rank_margin=0.0)).annualized_turnover
    loose = simulate_rank_book(frame, **_base_kwargs(hysteresis_rank_margin=0.5)).annualized_turnover
    assert loose <= tight


def test_thin_dates_are_skipped_not_zero_filled():
    frame = _synthetic_frame(num_tickers=5)
    result = simulate_rank_book(frame, **_base_kwargs(min_universe_size=1000))
    assert result.num_dates_used == 0
    assert result.net_sharpe == 0.0
    assert result.per_date == []


def test_empty_frame_after_nan_prediction_drop_returns_empty_result_never_raises():
    frame = _synthetic_frame(num_tickers=5, num_days=3)
    frame["pred"] = np.nan
    result = simulate_rank_book(frame, **_base_kwargs())
    assert result.num_dates_used == 0


def test_result_to_dict_shape():
    frame = _synthetic_frame(num_tickers=5, num_days=10)
    result = simulate_rank_book(frame, **_base_kwargs())
    payload = result.to_dict()
    assert set(payload) >= {
        "gross_sharpe", "net_sharpe", "gross_total_return", "net_total_return",
        "net_max_drawdown", "annualized_turnover", "cost_drag_annual_bps",
        "num_rebalances", "num_dates_used", "mean_names_long", "mean_names_short",
    }


def test_capacity_curve_sweeps_every_requested_top_n():
    frame = _synthetic_frame()
    result = capacity_curve(
        frame,
        participation_cap=0.01,
        base_kwargs=_base_kwargs(),
        top_n_sweep=[2, 4, 8],
    )
    assert [row["top_n"] for row in result["per_top_n"]] == [2, 4, 8]
    assert result["capacity_usd"] >= 0.0


def test_capacity_curve_binding_ticker_is_the_lowest_dollar_volume_held_name():
    frame = _synthetic_frame(num_tickers=20)
    result = capacity_curve(
        frame,
        participation_cap=0.01,
        base_kwargs=_base_kwargs(),
        top_n_sweep=[4],
    )
    # Ticker T0 has the smallest liquidity_log_dollar_volume by construction
    # and skill=-1 (extreme short candidate) - it should bind capacity.
    assert result["binding_ticker"] == "T0"


def test_stress_test_costs_degrades_net_sharpe_as_multiplier_rises():
    frame = _synthetic_frame()
    results = stress_test_costs(
        frame, base_kwargs=_base_kwargs(cost_bps_per_side=5.0, commission_bps=1.0), cost_multipliers=(1.0, 2.0, 3.0)
    )
    sharpes = [entry["net_sharpe"] for entry in results]
    assert sharpes[0] > sharpes[1] > sharpes[2]
    assert [entry["cost_multiplier"] for entry in results] == [1.0, 2.0, 3.0]


def test_summarize_metric_stability_reports_sign_flip_fraction_and_bootstrap():
    summary = summarize_metric_stability([0.10, 0.15, -0.05, 0.20], min_windows=3, max_sign_flip_fraction=0.5)
    assert summary["num_windows"] == 4
    assert summary["sign_flip_fraction"] == 0.25
    assert summary["stable"] is True
    assert "bootstrap" in summary


def test_summarize_metric_stability_fails_on_insufficient_windows():
    summary = summarize_metric_stability([0.1], min_windows=3, max_sign_flip_fraction=1.0)
    assert "insufficient_windows" in summary["failures"]
    assert summary["stable"] is False


def test_summarize_metric_stability_fails_on_excessive_sign_flips():
    summary = summarize_metric_stability([0.1, -0.1, 0.1, -0.1], min_windows=1, max_sign_flip_fraction=0.1)
    assert "sign_flip_fraction_above_gate" in summary["failures"]


def test_summarize_metric_stability_empty_series_never_raises():
    summary = summarize_metric_stability([], min_windows=1, max_sign_flip_fraction=1.0)
    assert summary["num_windows"] == 0
    assert summary["stable"] is False
    assert summary["failures"] == ["no_windows"]
