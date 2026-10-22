"""V6.4.0 (lead L9): bootstrap of a sleeve's round-trip P&L."""

from __future__ import annotations

import pytest

from evaluation.trade_bootstrap import (
    bootstrap_mean_pnl, leave_one_name_out, pnl_by_name, repeatable, round_trips_from_closed_trades, top_k_share,
)


def _trade(ticker, pnl, fees=0.0, entry_price=100.0, quantity=10.0, entry="2024-03-01T20:00:00Z"):
    return {"symbols": [{"value": ticker}], "profitLoss": pnl, "totalFees": fees, "entryPrice": entry_price, "quantity": quantity,
            "entryTime": entry}


def test_round_trips_are_net_of_fees_and_filtered_by_ticker():
    run = {"result": {"totalPerformance": {"closedTrades": [
        _trade("BTCUSD", 50.0, fees=2.0), _trade("DOGEUSD", -10.0, fees=1.0),
        {"symbols": [{"value": "A"}, {"value": "B"}], "profitLoss": 5.0},
    ]}}}
    trades = round_trips_from_closed_trades(run)
    assert [(t["ticker"], t["pnl"]) for t in trades] == [("BTCUSD", 48.0), ("DOGEUSD", -11.0)]  # the combo is skipped
    assert trades[0]["notional"] == 1000.0 and trades[0]["entry"] == "2024-03-01"
    assert [t["ticker"] for t in round_trips_from_closed_trades(run, {"BTCUSD"})] == ["BTCUSD"]
    assert round_trips_from_closed_trades({}) == []


def test_bootstrap_interval_excludes_zero_for_steady_wins_and_straddles_it_for_noise():
    steady = bootstrap_mean_pnl([10.0, 12.0, 9.0, 11.0, 10.5, 9.5, 11.5, 10.0] * 3, n=2000)
    assert steady["ci_low"] > 0.0 and steady["p_mean_le_0"] == 0.0
    noisy = bootstrap_mean_pnl([100.0, -100.0, 90.0, -95.0, 5.0, -4.0], n=2000)
    assert noisy["ci_low"] < 0.0 < noisy["ci_high"]
    assert bootstrap_mean_pnl([1.0])["ci_low"] is None and bootstrap_mean_pnl([])["mean"] is None


def test_bootstrap_is_deterministic_for_a_seed():
    assert bootstrap_mean_pnl([1, -2, 3, 4, -1], n=500, seed=3) == bootstrap_mean_pnl([1, -2, 3, 4, -1], n=500, seed=3)


def test_top_k_share():
    assert top_k_share([100.0, 10.0, 10.0, -20.0], 1) == pytest.approx(100.0 / 100.0)
    assert top_k_share([5.0, 5.0], 1) == pytest.approx(0.5)
    assert top_k_share([-1.0, -2.0], 1) is None and top_k_share([], 1) is None


def test_leave_one_name_out_and_the_repeatable_verdict():
    trades = [{"ticker": "BTC", "pnl": 100.0}, {"ticker": "BTC", "pnl": 50.0}, {"ticker": "ETH", "pnl": 20.0}, {"ticker": "LTC", "pnl": -5.0}]
    totals = pnl_by_name(trades)
    assert totals == {"BTC": 150.0, "ETH": 20.0, "LTC": -5.0}
    assert leave_one_name_out(totals) == {"BTC": 15.0, "ETH": 145.0, "LTC": 170.0}
    assert repeatable({"ci_low": 1.0}, leave_one_name_out(totals)) is True
    lucky = {"BTC": 150.0, "ETH": -20.0}
    assert repeatable({"ci_low": 1.0}, leave_one_name_out(lucky)) is False  # without BTC the sleeve loses
    assert repeatable({"ci_low": -1.0}, {"x": 1.0}) is False and repeatable({"ci_low": None}, {}) is False
