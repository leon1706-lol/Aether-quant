"""evaluation/target_weights_engine.py: fills, currencies, costs and locks, on small hand-computable panels."""

import numpy as np
import pytest

from evaluation.target_weights_engine import MarketPanel, coinbase_taker_bps, default_fee_usd, simulate_target_weights
from portfolio.target_weights import TargetWeightsConfig

FREE = TargetWeightsConfig(
    enabled=True, min_weight_change=0.0, min_trade_usd=0.0, forex_min_trade_usd=0.0, equity_fee_bps=0.0, equity_min_fee_usd=0.0,
    slippage_bps_by_class={"equity": 0.0, "bond": 0.0, "forex": 0.0, "crypto": 0.0}, financing_enabled=False,
)


def _no_fee(asset_class, notional, date, config):
    return 0.0


def _panel(tickers, opens, closes, classes, sessions=None):
    dates = [f"2024-01-{day:02d}" for day in range(1, len(opens) + 1)]
    return MarketPanel(dates, tickers, np.array(opens, dtype=float), np.array(closes, dtype=float), classes, set(sessions if sessions is not None else dates))


def _run(weights, panel, config=FREE, **kwargs):
    return simulate_target_weights(weights, panel, config, start=panel.dates[0], end=panel.dates[-1], fee_fn=kwargs.pop("fee_fn", _no_fee), **kwargs)


def test_an_equity_decision_fills_at_the_next_sessions_open():
    panel = _panel(["A"], [[10.0], [11.0], [13.0]], [[10.0], [12.0], [14.0]], {"A": "equity"})
    result = _run({"2024-01-01": {"A": 1.0}}, panel)

    # 10,000 shares at the open of day 2 (11.0): up 1.0 by that close and 2.0 more on day 3
    assert result["nav"].iloc[1] == pytest.approx(110_000.0)
    assert result["nav"].iloc[2] == pytest.approx(130_000.0)


def test_a_crypto_decision_fills_at_the_close_of_the_bar_dated_that_day():
    panel = _panel(["B"], [[10.0], [10.0], [10.0]], [[10.0], [20.0], [30.0]], {"B": "crypto"})
    result = _run({"2024-01-01": {"B": 1.0}}, panel)

    # Filled at the close of the bar dated day 1, as day 2 begins. Each label shows the bar that ended as it began, so the move
    # of the bar dated day 2 (10 -> 20) appears on day 3, as in Lean's daily sample.
    assert result["nav"].iloc[1] == pytest.approx(100_000.0)
    assert result["nav"].iloc[2] == pytest.approx(200_000.0)


def test_a_crypto_decision_waits_for_a_fresh_bar():
    panel = _panel(["B"], [[10.0], [10.0], [np.nan], [20.0], [40.0], [40.0]], [[10.0], [10.0], [np.nan], [20.0], [40.0], [40.0]], {"B": "crypto"})
    result = _run({"2024-01-03": {"B": 1.0}}, panel)

    # no bar dated day 3: the order fills at the close of the bar dated day 4 (20.0), and only 20 -> 40 is earned
    assert result["nav"].iloc[4] == pytest.approx(100_000.0)
    assert result["nav"].iloc[5] == pytest.approx(200_000.0)


def test_crypto_is_long_only():
    panel = _panel(["B"], [[10.0], [10.0], [10.0]], [[10.0], [10.0], [5.0]], {"B": "crypto"})
    result = _run({"2024-01-01": {"B": -1.0}}, panel)
    assert result["nav"].iloc[-1] == pytest.approx(100_000.0)


def test_a_usd_base_pair_earns_its_pnl_in_the_quote_currency():
    panel = _panel(["USDJPY"], [[100.0], [100.0], [100.0], [100.0]], [[100.0], [100.0], [125.0], [125.0]], {"USDJPY": "forex"})
    result = _run({"2024-01-01": {"USDJPY": 1.0}}, panel)

    # 100,000 USD bought at 100: at 125 the book is +100,000 USD - 10,000,000 JPY, worth +20,000 USD
    assert result["nav"].iloc[-1] == pytest.approx(120_000.0)


def test_a_flat_row_closes_positions():
    panel = _panel(["A"], [[10.0]] * 4, [[10.0], [10.0], [10.0], [20.0]], {"A": "equity"})
    result = _run({"2024-01-01": {"A": 1.0}, "2024-01-02": {}}, panel)
    assert result["nav"].iloc[-1] == pytest.approx(100_000.0)


def test_slippage_and_fees_cost_what_they_should():
    config = TargetWeightsConfig(
        enabled=True, min_weight_change=0.0, min_trade_usd=0.0, equity_fee_bps=10.0, equity_min_fee_usd=0.0,
        slippage_bps_by_class={"equity": 10.0}, financing_enabled=False,
    )
    panel = _panel(["A"], [[100.0]] * 3, [[100.0]] * 3, {"A": "equity"})
    result = simulate_target_weights({"2024-01-01": {"A": 0.5}}, panel, config, start=panel.dates[0], end=panel.dates[-1])

    # 500 shares at 100.10 marked at 100 = -50; fee 10 bps on 50,050 = -50.05
    assert result["nav"].iloc[-1] == pytest.approx(100_000.0 - 50.0 - 50.05)
    assert result["fees"] == pytest.approx(50.05)


def test_financing_is_charged_on_a_levered_book():
    config = TargetWeightsConfig(
        enabled=True, min_weight_change=0.0, min_trade_usd=0.0, equity_fee_bps=0.0, equity_min_fee_usd=0.0,
        slippage_bps_by_class={"equity": 0.0}, financing_enabled=True, margin_spread_bps=100.0,
    )
    panel = _panel(["A"], [[10.0]] * 4, [[10.0]] * 4, {"A": "equity"})
    result = simulate_target_weights(
        {"2024-01-01": {"A": 2.0}}, panel, config, start=panel.dates[0], end=panel.dates[-1], fee_fn=_no_fee,
        rf_dates=["2020-01-01"], rf_rates=[4.0],
    )
    assert result["financing"] < 0.0
    # 100,000 of debit at 5% for sessions 2, 3 and 4 (the position exists from the open of session 2)
    assert result["financing"] == pytest.approx(-3.0 * 100_000.0 * 5.0 / 100.0 / 360.0, rel=0.02)


def test_the_drawdown_lock_closes_the_book_and_stops_trading():
    panel = _panel(["A"], [[10.0]] * 6, [[10.0], [10.0], [5.0], [5.0], [20.0], [20.0]], {"A": "equity"})
    result = _run({"2024-01-01": {"A": 1.0}, "2024-01-05": {"A": 1.0}}, panel, max_total_drawdown=0.2)

    assert result["locked_on"] == "2024-01-03"
    # closed at the next open of 10 (no further P&L on this stylised panel), and the later row is ignored
    assert result["nav"].iloc[3] == result["nav"].iloc[4] == result["nav"].iloc[5]


def test_sweep_earns_and_is_excluded_from_the_strategy_return():
    panel = _panel(
        ["A", "BIL"], [[10.0, 100.0], [10.0, 100.0], [10.0, 100.0], [10.0, 110.0]],
        [[10.0, 100.0], [10.0, 100.0], [10.0, 100.0], [10.0, 110.0]], {"A": "equity", "BIL": "cash_sweep"},
    )
    sweep = {"enabled": True, "max_weight": 0.9, "min_trade_weight": 0.05, "cash_buffer": 0.02, "margin_buffer": 0.1, "margin_leverage": 2.0}
    result = _run({}, panel, sweep_config=sweep)

    assert result["nav"].iloc[-1] > 100_000.0
    assert result["strategy"].abs().sum() == pytest.approx(0.0, abs=1e-12)
    assert result["total"].iloc[-1] > 0.0


def test_coinbase_schedule_and_default_fees():
    assert coinbase_taker_bps("2018-01-01") == 30.0
    assert coinbase_taker_bps("2019-06-01") == 25.0
    assert coinbase_taker_bps("2019-10-08") == 80.0
    assert coinbase_taker_bps("2024-01-01") == 80.0
    assert default_fee_usd("crypto", 1000.0, "2024-01-01", FREE) == pytest.approx(8.0)
    assert default_fee_usd("forex", 1000.0, "2024-01-01", FREE) == pytest.approx(2.0)
    assert default_fee_usd("forex", 0.0, "2024-01-01", FREE) == 0.0


def test_turnover_is_a_share_of_the_nav_the_book_actually_had():
    # Buys $100k at 10; the price doubles, so NAV is $200k when it sells half ($100k). $200k traded on a mean NAV above the starting $100k.
    opens = [[10.0], [10.0], [20.0], [20.0]]
    closes = [[10.0], [20.0], [20.0], [20.0]]
    result = _run({"2024-01-01": {"A": 1.0}, "2024-01-03": {"A": 0.5}}, _panel(["A"], opens, closes, {"A": "equity"}))

    nav = result["nav"]
    years = len(nav) / 365.25
    assert nav.mean() > 100_000.0
    assert result["turnover"] == pytest.approx(200_000.0 / nav.mean() / years)
