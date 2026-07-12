import inspect
import json

from experience import SimulatedPortfolioState, build_experience_event


def _minimal_build_experience_event_kwargs(portfolio: dict) -> dict:
    return {
        "mode": "observation",
        "symbol": "AAPL R735QTJ8XC9X",
        "ticker": "AAPL",
        "signal": "buy",
        "action": "simulate",
        "execution_note": "simulated_entered_long:observation_mode_no_real_orders",
        "probability_up": 0.62,
        "confidence": 0.31,
        "target_weight": 0.1,
        "regime": {},
        "moe_gating": {},
        "topology": {},
        "liquidity": {},
        "market_analysis": {"action": "simulate", "reasons": ["observation_only_asset_directional_signal_simulate_instead"]},
        "portfolio": portfolio,
    }


def test_enter_long_updates_cash_and_holdings():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)

    portfolio.enter_long("AAPL", close_price=100.0, target_weight=0.25, bar_index=1)

    assert portfolio.holdings["AAPL"]["quantity"] == 25.0
    assert portfolio.cash == 10_000.0 - 2_500.0
    assert portfolio.cumulative_turnover == 2_500.0


def test_enter_long_with_negative_target_weight_opens_a_short():
    # Phase 3 of the 5/10 -> 9/10 roadmap (portfolio/book_construction.py):
    # enter_long() despite its name is already sign-generic
    # (simulate_fill()'s notional = target_weight * equity), so main.py's
    # new "short" signal branch reuses it directly for the simulated-mode
    # path rather than adding a redundant enter_short() method. Locks in
    # that this pre-existing genericity is real, not assumed.
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)

    portfolio.enter_long("AAPL", close_price=100.0, target_weight=-0.25, bar_index=1)

    assert portfolio.holdings["AAPL"]["quantity"] == -25.0
    # Shorting credits cash (selling borrowed shares), not debits it.
    assert portfolio.cash == 10_000.0 + 2_500.0
    assert portfolio.cumulative_turnover == 2_500.0


def test_short_position_realizes_correct_pnl_sign_on_exit():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)
    portfolio.enter_long("AAPL", close_price=100.0, target_weight=-0.25, bar_index=1)

    # Price fell after shorting - a short position should PROFIT.
    portfolio.exit("AAPL", close_price=90.0, bar_index=2)

    snapshot = portfolio.snapshot()
    assert snapshot["last_realized_pnl"] == -25.0 * (90.0 - 100.0)
    assert snapshot["last_realized_pnl"] == 250.0


def test_exit_realizes_pnl_and_flattens_position():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)
    portfolio.enter_long("AAPL", close_price=100.0, target_weight=0.25, bar_index=1)

    portfolio.exit("AAPL", close_price=110.0, bar_index=2)

    assert "AAPL" not in portfolio.holdings
    snapshot = portfolio.snapshot()
    assert snapshot["last_realized_pnl"] == 25.0 * (110.0 - 100.0)
    assert portfolio.cash == 10_000.0 - 2_500.0 + 25.0 * 110.0


def test_exit_on_flat_position_is_a_no_op():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)

    portfolio.exit("AAPL", close_price=110.0, bar_index=1)

    assert portfolio.cash == 10_000.0
    assert portfolio.snapshot()["last_realized_pnl"] is None


def test_liquidate_all_flattens_every_symbol():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)
    portfolio.enter_long("AAPL", close_price=100.0, target_weight=0.25, bar_index=1)
    portfolio.enter_long("MSFT", close_price=50.0, target_weight=0.25, bar_index=1)

    portfolio.liquidate_all(bar_index=2)

    assert portfolio.holdings == {}
    assert portfolio.snapshot()["holdings_value"] == 0.0


def test_snapshot_shape_matches_build_experience_event_portfolio_contract():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)
    portfolio.enter_long("AAPL", close_price=100.0, target_weight=0.25, bar_index=1)

    snapshot = portfolio.snapshot()

    for key in ("total_value", "cash", "current_drawdown"):
        assert key in snapshot
    assert snapshot["simulated"] is True

    event = build_experience_event(**_minimal_build_experience_event_kwargs(snapshot))
    json.dumps(event)  # must round-trip without raising


def test_snapshot_consumes_realized_pnl_by_default():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)
    portfolio.enter_long("AAPL", close_price=100.0, target_weight=0.25, bar_index=1)
    portfolio.exit("AAPL", close_price=110.0, bar_index=2)

    first_snapshot = portfolio.snapshot()
    second_snapshot = portfolio.snapshot()

    assert first_snapshot["last_realized_pnl"] is not None
    assert second_snapshot["last_realized_pnl"] is None


def test_mark_to_market_updates_drawdown_and_peak_equity():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)
    portfolio.enter_long("AAPL", close_price=100.0, target_weight=0.25, bar_index=1)

    portfolio.mark_to_market({"AAPL": 120.0}, bar_index=2)
    up_snapshot = portfolio.snapshot()
    assert up_snapshot["peak_equity"] > 10_000.0
    assert up_snapshot["current_drawdown"] == 0.0

    portfolio.mark_to_market({"AAPL": 90.0}, bar_index=3)
    down_snapshot = portfolio.snapshot()
    assert down_snapshot["current_drawdown"] < 0.0
    assert down_snapshot["peak_equity"] == up_snapshot["peak_equity"]


def test_mark_to_market_with_multi_symbol_dict_produces_exactly_one_equity_curve_entry():
    """Regression guard for the equity-curve cadence fix in main.py::on_data():
    a single mark_to_market() call carrying every symbol's price for the bar
    must append exactly one equity_curve entry that reflects all of them,
    not one entry per symbol."""
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)
    portfolio.enter_long("AAPL", close_price=100.0, target_weight=0.25, bar_index=1)
    portfolio.enter_long("MSFT", close_price=50.0, target_weight=0.25, bar_index=1)
    entries_before = len(portfolio.equity_curve)

    portfolio.mark_to_market({"AAPL": 120.0, "MSFT": 55.0}, bar_index=2)

    assert len(portfolio.equity_curve) == entries_before + 1
    assert portfolio.position_value("AAPL") == 25.0 * 120.0
    assert portfolio.position_value("MSFT") == 50.0 * 55.0


def test_position_value_reflects_latest_mark_to_market_price():
    portfolio = SimulatedPortfolioState(initial_cash=10_000.0)
    portfolio.enter_long("AAPL", close_price=100.0, target_weight=0.25, bar_index=1)

    assert portfolio.position_value("AAPL") == 2_500.0

    portfolio.mark_to_market({"AAPL": 120.0}, bar_index=2)
    assert portfolio.position_value("AAPL") == 25.0 * 120.0
    assert portfolio.position_value("MSFT") == 0.0


def test_never_calls_out_to_real_portfolio_or_broker():
    signature = inspect.signature(SimulatedPortfolioState.__init__)
    assert list(signature.parameters.keys()) == ["self", "initial_cash"]

    source = inspect.getsource(SimulatedPortfolioState)
    for forbidden in ("QCAlgorithm", "self.Portfolio", "SetHoldings", "Liquidate("):
        assert forbidden not in source
