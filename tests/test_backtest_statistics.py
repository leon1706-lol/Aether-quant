"""Tests for evaluation/backtest_statistics.py (V6.3.0): each AFML ch. 14 formula on hand-computed inputs, then the
whole assembly on a synthetic six-day Lean run (one stock bet, one T-bill sweep holding) whose every number is known."""

from __future__ import annotations

import io
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evaluation.backtest_statistics import (
    _duration_days,
    bet_starts,
    classification_scores,
    compute_backtest_statistics,
    deflated_sharpe_ratio,
    drawdown_episodes,
    expected_max_sharpe,
    hhi_concentration,
    information_ratio,
    monthly_counts,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)


def test_hhi_is_zero_when_even_and_one_when_concentrated():
    assert hhi_concentration([1.0, 1.0, 1.0, 1.0]) == pytest.approx(0.0)
    assert hhi_concentration([5.0, 0.0, 0.0]) == pytest.approx(1.0)
    # w = 1/6, 2/6, 3/6 -> sum w^2 = 14/36; (14/36 - 1/3) / (2/3) = 1/12
    assert hhi_concentration([1.0, 2.0, 3.0]) == pytest.approx(1.0 / 12.0)


def test_hhi_needs_more_than_two_observations():
    assert hhi_concentration([1.0, 2.0]) is None
    assert hhi_concentration([]) is None


def test_drawdown_episodes_close_on_a_new_high_and_leave_the_last_one_open():
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]
    episodes = drawdown_episodes(dates, [100.0, 110.0, 99.0, 105.0, 120.0, 108.0])
    assert len(episodes) == 2
    first, last = episodes
    assert first["depth"] == pytest.approx(0.1)
    assert (first["start"], first["end"], first["days_under_water"], first["open"]) == ("2024-01-02", "2024-01-05", 3, False)
    assert last["depth"] == pytest.approx(0.1)
    assert (last["start"], last["end"], last["open"]) == ("2024-01-05", "2024-01-06", True)


def test_drawdown_episodes_empty_on_a_rising_curve():
    assert drawdown_episodes(["2024-01-01", "2024-01-02"], [1.0, 2.0]) == []


def test_sharpe_and_information_ratio_annualise_with_the_given_period():
    returns = [0.01, -0.005, 0.02, 0.0]
    mean = sum(returns) / 4
    std = math.sqrt(sum((value - mean) ** 2 for value in returns) / 3)
    assert sharpe_ratio(returns, 365) == pytest.approx(mean / std * math.sqrt(365))
    assert information_ratio(returns, returns, 365) is None  # zero active risk
    assert sharpe_ratio([0.01, 0.01], 365) is None


def test_probabilistic_sharpe_is_one_half_for_a_zero_mean_symmetric_series():
    assert probabilistic_sharpe_ratio([0.01, -0.01] * 50) == pytest.approx(0.5)
    assert probabilistic_sharpe_ratio([0.012, -0.01] * 50) > 0.5
    assert probabilistic_sharpe_ratio([0.0, 0.0, 0.0]) is None


def test_expected_max_sharpe_matches_the_worked_value():
    # N = 100 trials, V[SR] = 0.5: sqrt(0.5) * (0.4228 * Z(0.99) + 0.5772 * Z(1 - 1/(100 e))) = 1.789
    assert expected_max_sharpe(100, 0.5) == pytest.approx(1.789, abs=0.005)
    assert expected_max_sharpe(1, 0.5) is None
    assert expected_max_sharpe(10, 0.0) is None


def test_deflated_sharpe_is_below_the_plain_psr_and_needs_trials():
    returns = [0.004, -0.002, 0.003, -0.001] * 100
    result = deflated_sharpe_ratio(returns, [0.2, 0.5, -0.1, 0.9, 0.3], periods_per_year=365)
    assert result["num_trials"] == 5
    assert result["value"] < probabilistic_sharpe_ratio(returns)
    missing = deflated_sharpe_ratio(returns, [0.4])
    assert missing["value"] is None and "fewer than 2" in missing["reason"]


def test_classification_scores_and_log_loss():
    scores = classification_scores([1, 0, 1, 1], [1, 0, 0, 1], [0.9, 0.1, 0.4, 0.8])
    assert scores["accuracy"] == pytest.approx(0.75)
    assert scores["precision"] == pytest.approx(1.0)
    assert scores["recall"] == pytest.approx(2.0 / 3.0)
    assert scores["f1"] == pytest.approx(0.8)
    expected = (math.log(0.9) * 2 + math.log(0.4) + math.log(0.8)) / 4
    assert scores["neg_log_loss"] == pytest.approx(expected)
    assert classification_scores([1, 0], [1, 1])["neg_log_loss"] is None
    assert classification_scores([], []) == {"n": 0}


def test_bet_starts_count_openings_and_flips():
    positions = {
        "2024-01-01": {"A": 10.0},
        "2024-01-02": {"A": 10.0},
        "2024-01-03": {"A": -5.0},
        "2024-01-04": {"A": 0.0},
        "2024-01-05": {"A": 3.0},
    }
    assert bet_starts(positions) == [("2024-01-01", "A", 1), ("2024-01-03", "A", -1), ("2024-01-05", "A", 1)]


def test_monthly_counts_include_empty_months():
    assert monthly_counts(["2024-01-05", "2024-01-20", "2024-03-01"], "2024-01-01", "2024-04-30") == [2, 0, 1, 0]
    assert monthly_counts([], "2023-12-15", "2024-01-02") == [0, 0]


def test_duration_parser_reads_lean_timespans():
    assert _duration_days("1.00:00:00") == pytest.approx(1.0)
    assert _duration_days("12:00:00") == pytest.approx(0.5)
    assert _duration_days("496.04:00:00") == pytest.approx(496 + 4 / 24)
    assert _duration_days(None) is None


# ---------------------------------------------------------------- the whole assembly on a synthetic run

DATES = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]
AAA = [(100.0, 100.0), (100.0, 101.0), (101.0, 102.0), (102.0, 104.0), (103.5, 103.0), (103.0, 105.0)]  # (open, close)
BIL = [(50.0, 50.0), (50.1, 50.1), (50.2, 50.2), (50.3, 50.3), (50.4, 50.4), (50.5, 50.5)]


def _stamp(day: str, hour: int = 20) -> float:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=timezone.utc).timestamp()


def _write_zip(path: Path, bars) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"{day.replace('-', '')} 00:00,{int(o * 10000)},{int(max(o, c) * 10000)},{int(min(o, c) * 10000)},{int(c * 10000)},1000"
        for day, (o, c) in zip(DATES, bars)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{path.stem}.csv", rows)
    path.write_bytes(buffer.getvalue())


def _event(order_id: int, symbol: str, day: str, quantity: float, price: float) -> dict:
    return {"orderId": order_id, "orderEventId": order_id, "symbolValue": symbol, "status": "filled", "time": _stamp(day),
            "fillQuantity": quantity, "fillPrice": price, "orderFeeAmount": 1.0, "direction": "buy" if quantity > 0 else "sell"}


@pytest.fixture
def synthetic(tmp_path):
    _write_zip(tmp_path / "data" / "equity" / "usa" / "daily" / "aaa.zip", AAA)
    _write_zip(tmp_path / "data" / "equity" / "usa" / "daily" / "bil.zip", BIL)
    config = {
        "runtime": {"trading_days_per_year": 365},
        "phase1": {"universe": {"assets": [
            {"ticker": "AAA", "security_type": "equity", "asset_class": "equity", "data_path": "data/equity/usa/daily/aaa.zip"},
        ]}},
        "phase_v2": {"cash_sweep": {"ticker": "BIL", "data_path": "data/equity/usa/daily/bil.zip"}},
    }
    nav = [1000.0, 1010.0, 1005.0, 1020.0, 1015.0, 1030.0]
    result = {
        "statistics": {"Sharpe Ratio": "0.5", "Total Fees": "$3.00", "Start Equity": "1000", "End Equity": "1030"},
        "charts": {
            "Strategy Equity": {"series": {"Equity": {"values": [[_stamp(d), v, v, v, v] for d, v in zip(DATES, nav)]}}},
            "Benchmark": {"series": {"Benchmark": {"values": [[_stamp(d), 400.0 + 3 * i + (i % 2)] for i, d in enumerate(DATES)]}}},
        },
        "orders": {
            "1": {"securityType": 1, "type": 0}, "2": {"securityType": 1, "type": 0}, "3": {"securityType": 1, "type": 0},
        },
        "totalPerformance": {"closedTrades": [
            {"symbols": [{"value": "AAA"}], "entryTime": "2024-01-02T20:00:00Z", "entryPrice": 100.0, "quantity": 10.0,
             "direction": 0, "profitLoss": 30.0, "totalFees": 2.0, "duration": "3.00:00:00"},
        ]},
    }
    events = [_event(1, "BIL", "2024-01-01", 5.0, 50.0), _event(2, "AAA", "2024-01-02", 10.0, 100.0),
              _event(3, "AAA", "2024-01-05", -10.0, 103.0)]
    run = {"result": result, "order_events": events, "engine_log": "", "run_id": "1"}
    book_history = [{"date": "2024-01-01", "allocations": {"AAA": {"role": "long"}}}]
    return run, config, tmp_path, book_history


def _rows(stats: dict, section: str) -> dict:
    return {row["metric"]: row for row in stats["sections"][section]}


def test_assembly_splits_the_sweep_out_of_pnl_and_turnover(synthetic):
    run, config, root, history = synthetic
    stats = compute_backtest_statistics(run, config, root, run_name="synthetic", book_history=history)
    assert stats["status"] == "OK"
    performance = _rows(stats, "performance")
    # BIL: bought 5 @ 50 (fee 1), +0.1 a day for five days -> +2.5 - 1 = +1.5 carry
    assert performance["PnL from the T-bill sweep (carry)"]["portfolio"] == pytest.approx(1.5)
    assert performance["PnL"]["portfolio"] == pytest.approx(30.0)
    assert performance["PnL"]["strategy"] == pytest.approx(28.5)
    assert performance["PnL from long positions (closed bets, net of fees)"]["strategy"] == pytest.approx(28.0)
    assert performance["Hit ratio (closed bets net of fees)"]["strategy"] == pytest.approx(1.0)
    assert performance["Average return from hits"]["strategy"] == pytest.approx(0.028)
    shortfall = _rows(stats, "shortfall")
    assert shortfall["Traded notional"]["portfolio"] == pytest.approx(2280.0)
    assert shortfall["Traded notional"]["strategy"] == pytest.approx(2030.0)
    assert shortfall["Broker fees"]["portfolio"] == pytest.approx(3.0)
    assert shortfall["Broker fees"]["strategy"] == pytest.approx(2.0)
    # the AAA sale filled at 103 against a 103.5 open: 10 x 0.5 = 5 USD adverse, in bps of the covered notional
    slippage_usd = 0.5 / 103.5 * 1030.0
    assert shortfall["Average slippage per turnover (bps vs the bar's open)"]["portfolio"] == pytest.approx(slippage_usd / 2280.0 * 1e4)


def test_assembly_general_characteristics(synthetic):
    run, config, root, history = synthetic
    general = _rows(compute_backtest_statistics(run, config, root, run_name="synthetic", book_history=history), "general")
    assert general["Time range"]["portfolio"] == "2024-01-01 to 2024-01-06"
    assert general["Maximum dollar position"]["strategy"] == pytest.approx(1040.0)
    assert "AAA on 2024-01-04" in general["Maximum dollar position"]["reason"]
    assert general["Ratio of longs (share of bets)"]["strategy"] == pytest.approx(1.0)
    assert general["Average holding period (days, notional-weighted)"]["strategy"] == pytest.approx(3.0)
    assert general["Correlation to underlying (SPY, daily)"]["portfolio"] is not None


def test_assembly_attribution_and_classification(synthetic):
    run, config, root, history = synthetic
    stats = compute_backtest_statistics(run, config, root, run_name="synthetic", book_history=history)
    classes = {row["class"]: row for row in stats["sections"]["attribution"]["classes"]}
    assert set(classes) == {"equity", "cash_sweep"}
    assert classes["cash_sweep"]["net_pnl"] == pytest.approx(1.5)
    assert classes["equity"]["fees"] == pytest.approx(2.0)
    lean_book = stats["sections"]["classification"][0]
    assert lean_book["n"] == 0 or lean_book["accuracy"] is not None  # six bars cannot resolve a 20-bar horizon
    assert "probability" in lean_book["reason"] or "history" in lean_book["reason"]


def test_assembly_reports_missing_curve_instead_of_numbers(synthetic):
    run, config, root, _ = synthetic
    run["result"]["charts"]["Strategy Equity"]["series"]["Equity"]["values"] = []
    assert compute_backtest_statistics(run, config, root, run_name="empty")["status"] == "no equity curve"
