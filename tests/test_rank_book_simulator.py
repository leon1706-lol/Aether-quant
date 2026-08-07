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


# ---------------------------------------------------------------------------
# entry_lag_bars (V5.2.1, development/Problems.md) - a Daily-resolution
# market order fills at the NEXT bar's open, not the decision bar's close;
# this parameter makes the offline simulator stop implicitly assuming a
# same-bar fill.
# ---------------------------------------------------------------------------


def _two_ticker_frame():
    """Deterministic: A always ranks top, B always ranks bottom, so with
    top_n=bottom_n=1 the SAME book (A long, B short) forms on day 0 and is
    held unchanged thereafter (rebalance_every_bars=1000). Forward returns
    are distinct, large, and hand-computable per day."""
    dates = pd.bdate_range("2020-01-01", periods=3)
    returns = {"A": [0.10, 0.20, 0.30], "B": [-0.10, -0.20, -0.30]}
    rows = []
    for day_index, date in enumerate(dates):
        for ticker, rank in (("A", 1.0), ("B", 0.0)):
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "pred": rank,
                    "target_return_1d": returns[ticker][day_index],
                }
            )
    return pd.DataFrame(rows)


def _lag_test_kwargs(**overrides):
    kwargs = dict(
        prediction_column="pred",
        forward_return_column="target_return_1d",
        ticker_column="ticker",
        date_column="date",
        top_n=1,
        bottom_n=1,
        rebalance_every_bars=1000,
        cost_bps_per_side=0.0,
        commission_bps=0.0,
        gross_exposure=1.0,
        dollar_neutral=False,
        sector_neutral=False,
        max_weight_per_name=0.5,
        min_universe_size=2,
    )
    kwargs.update(overrides)
    return kwargs


def test_entry_lag_bars_zero_reproduces_default_behavior_exactly():
    frame = _two_ticker_frame()
    explicit = simulate_rank_book(frame, **_lag_test_kwargs(entry_lag_bars=0))
    implicit = simulate_rank_book(frame, **_lag_test_kwargs())
    assert explicit.per_date_net_return == implicit.per_date_net_return
    # Hand-computed: day0 A(+0.5)*0.10 + B(-0.5)*(-0.10) = 0.10.
    assert explicit.per_date_net_return[0] == pytest.approx(0.10)


def test_entry_lag_bars_one_excludes_only_the_first_days_return():
    frame = _two_ticker_frame()
    lagged = simulate_rank_book(frame, **_lag_test_kwargs(entry_lag_bars=1))
    # Day 0: no prior snapshot exists yet -> no position -> zero return,
    # even though the book was "selected" that same day.
    assert lagged.per_date_net_return[0] == pytest.approx(0.0)
    # Days 1-2: the position was held UNCHANGED from day 0 onward, so a
    # 1-bar lag makes no difference once it's already on - identical to
    # the unlagged case for these two dates specifically.
    unlagged = simulate_rank_book(frame, **_lag_test_kwargs(entry_lag_bars=0))
    assert lagged.per_date_net_return[1] == pytest.approx(unlagged.per_date_net_return[1])
    assert lagged.per_date_net_return[2] == pytest.approx(unlagged.per_date_net_return[2])
    assert lagged.per_date_net_return[1] == pytest.approx(0.20)
    assert lagged.per_date_net_return[2] == pytest.approx(0.30)


def test_entry_lag_bars_only_penalizes_changed_positions_not_held_ones():
    # Cumulative effect: lag=1 loses EXACTLY day 0's contribution and
    # nothing else, for a book that never rotates after entry.
    frame = _two_ticker_frame()
    lagged = simulate_rank_book(frame, **_lag_test_kwargs(entry_lag_bars=1))
    unlagged = simulate_rank_book(frame, **_lag_test_kwargs(entry_lag_bars=0))
    assert sum(unlagged.per_date_net_return) - sum(lagged.per_date_net_return) == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# min_commission_usd / assumed_portfolio_value_usd (V5.2.1) - an
# honestly-approximate per-order minimum-commission floor layered on the
# existing bps-of-turnover cost model.
# ---------------------------------------------------------------------------


def test_commission_floor_defaults_to_a_strict_no_op():
    frame = _synthetic_frame()
    baseline = simulate_rank_book(frame, **_base_kwargs())
    explicit_zero = simulate_rank_book(frame, **_base_kwargs(min_commission_usd=0.0, assumed_portfolio_value_usd=0.0))
    assert explicit_zero.cost_drag_annual_bps == pytest.approx(baseline.cost_drag_annual_bps)
    assert explicit_zero.net_sharpe == pytest.approx(baseline.net_sharpe)


def test_commission_floor_requires_both_inputs_configured():
    # A floor with no NAV to convert against (or vice versa) must not
    # divide-by-zero or silently apply a nonsensical charge - stays a no-op.
    frame = _synthetic_frame()
    baseline = simulate_rank_book(frame, **_base_kwargs())
    only_floor = simulate_rank_book(frame, **_base_kwargs(min_commission_usd=5.0, assumed_portfolio_value_usd=0.0))
    only_nav = simulate_rank_book(frame, **_base_kwargs(min_commission_usd=0.0, assumed_portfolio_value_usd=100_000.0))
    assert only_floor.cost_drag_annual_bps == pytest.approx(baseline.cost_drag_annual_bps)
    assert only_nav.cost_drag_annual_bps == pytest.approx(baseline.cost_drag_annual_bps)


def test_commission_floor_adds_exact_drag_on_the_only_rebalance_date():
    # A book that only ever rebalances once (rebalance_every_bars huge)
    # has a known, hand-computable names_traded == 2 (A entering long, B
    # entering short) on day 0 only - every later date has zero turnover,
    # so zero additional floor cost.
    frame = _two_ticker_frame()
    without_floor = simulate_rank_book(frame, **_lag_test_kwargs())
    with_floor = simulate_rank_book(
        frame, **_lag_test_kwargs(min_commission_usd=5.0, assumed_portfolio_value_usd=100_000.0)
    )
    expected_extra_cost = 2 * 5.0 / 100_000.0  # 2 names traded, $5 floor, $100k NAV
    assert without_floor.per_date_net_return[0] - with_floor.per_date_net_return[0] == pytest.approx(
        expected_extra_cost
    )
    # No further turnover after day 0 -> no further floor cost.
    assert with_floor.per_date_net_return[1] == pytest.approx(without_floor.per_date_net_return[1])
    assert with_floor.per_date_net_return[2] == pytest.approx(without_floor.per_date_net_return[2])


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


def test_capacity_curve_excludes_zero_volume_tickers_from_binding_search():
    # A held ticker with liquidity_log_dollar_volume == 0.0 (e.g. a forex
    # pair - Yahoo Finance reports no real Volume for FX, so log1p(close*
    # volume) is always exactly 0.0) must never win the "lowest dollar
    # volume" binding-ticker search - a true zero means "no real liquidity
    # signal," not "the most illiquid held name." T0 (extreme short
    # candidate, guaranteed to be held) gets its volume zeroed out here;
    # T1 (the next-lowest REAL volume among held names) must bind instead.
    frame = _synthetic_frame(num_tickers=20)
    frame.loc[frame["ticker"] == "T0", "liquidity_log_dollar_volume"] = 0.0
    result = capacity_curve(
        frame,
        participation_cap=0.01,
        base_kwargs=_base_kwargs(),
        top_n_sweep=[4],
    )
    assert result["binding_ticker"] != "T0"
    assert result["binding_ticker"] == "T1"
    assert result["capacity_usd"] > 0.0


def test_capacity_curve_falls_back_to_zero_when_every_held_ticker_lacks_real_volume():
    frame = _synthetic_frame(num_tickers=20)
    frame["liquidity_log_dollar_volume"] = 0.0
    result = capacity_curve(
        frame,
        participation_cap=0.01,
        base_kwargs=_base_kwargs(),
        top_n_sweep=[4],
    )
    assert result["binding_ticker"] is None
    assert result["capacity_usd"] == 0.0


def test_capacity_curve_inverts_log1p_with_expm1_not_exp():
    # liquidity_log_dollar_volume is a log1p(dollar_volume) value - its
    # correct inverse is expm1, not exp (development/Problems.md). Using a
    # small, exactly-checkable value makes the two functions' results
    # distinguishable (they converge for large inputs, where the +/-1 is
    # negligible - the earlier "lowest dollar volume" tests can't catch
    # this on their own for that reason). rebalance_every_bars is set
    # larger than num_days so the book never rotates past its first
    # rebalance - held_avg_dollar_volume's size is then deterministically
    # top_n+bottom_n==8, not an accumulated union across many rebalances.
    frame = _synthetic_frame(num_tickers=20)
    frame.loc[frame["ticker"] == "T0", "liquidity_log_dollar_volume"] = np.log1p(5.0)  # dollar_volume == 5.0
    result = capacity_curve(
        frame,
        participation_cap=1.0,
        base_kwargs=_base_kwargs(rebalance_every_bars=1000),
        top_n_sweep=[4],
    )
    assert result["binding_ticker"] == "T0"
    # capacity_usd = dollar_volume(binding) * participation_cap * num_held.
    # participation_cap=1.0 and num_held=8 (top_n=4 + bottom_n=4, one
    # rebalance only) here, so capacity_usd == dollar_volume(T0) * 8 ==
    # 40.0 with the correct expm1 inverse - exp(np.log1p(5.0)) would
    # instead give 6.0 * 8 = 48.0.
    assert result["capacity_usd"] == pytest.approx(40.0)


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
