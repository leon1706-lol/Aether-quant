"""Tests for evaluation/backtest_audit.py (V5.5.0, Problems.md #127/#128): the
order-level audit of a finished Lean run. Runs are synthetic - built in code in
Lean's own JSON shape - so no backtest folder is needed. Conventions match
the rest of this repo: no test classes, module-level helpers, plain dicts."""

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from evaluation.backtest_audit import (
    audit_backtest_run,
    carried_book_members,
    classify_entries,
    pnl_by_entry_bucket,
    daily_equity_from_chart,
    exposure_summary,
    find_overlapping_orders,
    holding_period_histogram,
    load_backtest_run,
    load_book_history,
    pnl_and_fees_by_asset_class,
    select_run_book_history,
    sharpe_from_equity,
    summarize_book_history,
    teardown_status,
)

DAY0 = datetime(2019, 1, 1, tzinfo=timezone.utc)


def _iso(day: float) -> str:
    return (DAY0 + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(day: float) -> int:
    return int((DAY0 + timedelta(days=day)).timestamp())


def _order(order_id, symbol, created, closed, *, order_type=1, direction=0, status=3, security_type=1, filled=True):
    order = {
        "id": order_id,
        "symbol": {"value": symbol, "id": symbol + " 2T", "permtick": symbol},
        "createdTime": _iso(created),
        "time": _iso(created),
        "type": order_type,
        "direction": direction,
        "status": status,
        "securityType": security_type,
        "quantity": 10.0,
    }
    order["lastFillTime" if filled else "canceledTime"] = _iso(closed)
    return order


# ---------------------------------------------------------------- equity / Sharpe


def _equity_chart(values_by_day: list[float], intraday_noise: bool = False) -> dict:
    points = []
    for index, equity in enumerate(values_by_day):
        if intraday_noise:
            points.append([_epoch(index) + 3600, equity * 0.999, equity, equity, equity * 0.999])
        points.append([_epoch(index), equity, equity, equity, equity])
    return {"charts": {"Strategy Equity": {"series": {"Equity": {"values": points}}}}}


def test_daily_equity_keeps_the_last_point_per_day_even_with_intraday_points():
    chart = _equity_chart([100.0, 101.0, 102.0], intraday_noise=True)
    daily = daily_equity_from_chart(chart)
    assert [date for date, _ in daily] == ["2019-01-01", "2019-01-02", "2019-01-03"]
    # the intraday point (t + 1h) is the day's LAST point whatever the list order
    assert [value for _, value in daily] == [pytest.approx(100.0 * 0.999), pytest.approx(101.0 * 0.999), pytest.approx(102.0 * 0.999)]


def test_sharpe_with_a_risk_free_rate_is_lower_than_without():
    equity = [("d%d" % i, 100.0 * (1.0004 + 0.0006 * ((-1) ** i)) ** i) for i in range(1, 120)]
    no_rf = sharpe_from_equity(equity, 0.0)
    with_rf = sharpe_from_equity(equity, 0.02)
    assert no_rf is not None and with_rf is not None
    assert with_rf < no_rf  # Lean subtracts a risk-free rate; offline tools do not


def test_sharpe_is_none_when_undefined():
    assert sharpe_from_equity([], 0.0) is None
    assert sharpe_from_equity([("a", 100.0), ("b", 101.0)], 0.0) is None  # one return
    assert sharpe_from_equity([("a", 100.0), ("b", 100.0), ("c", 100.0)], 0.0) is None  # zero variance


def test_sharpe_matches_a_hand_computation():
    equity = [("a", 100.0), ("b", 101.0), ("c", 100.0), ("d", 102.0)]
    returns = [1 / 100, -1 / 101, 2 / 100]
    mean = sum(returns) / 3
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / 2)
    assert sharpe_from_equity(equity, 0.0) == pytest.approx(mean / std * math.sqrt(252))


def test_exposure_summary_reports_mean_and_max_per_series():
    result = {
        "charts": {
            "Exposure": {
                "series": {
                    "Forex - Short Ratio": {"values": [[1, -0.1], [2, -0.3], [3, None]]},
                    "Equity - Long Ratio": {"values": [[1, 0.02], [2, 0.04]]},
                    "Empty": {"values": []},
                }
            }
        }
    }
    summary = exposure_summary(result)
    assert summary["Forex - Short Ratio"]["mean"] == pytest.approx(-0.2)
    assert summary["Equity - Long Ratio"] == {"mean": pytest.approx(0.03), "max": 0.04, "peak": 0.04}
    # short series are negative: `max` is the useless -0.1, `peak` is the extreme to compare with a cap
    assert summary["Forex - Short Ratio"]["max"] == -0.1
    assert summary["Forex - Short Ratio"]["peak"] == -0.3
    assert "Empty" not in summary
    assert exposure_summary({}) == {}


# ---------------------------------------------------------------- overlapping orders


def test_overlapping_limit_orders_on_one_symbol_are_found():
    """The AMZN pattern: a new limit order submitted every bar while the
    previous one is still open."""
    orders = {
        "1": _order(1, "AMZN", 0, 5),
        "2": _order(2, "AMZN", 1, 6),
        "3": _order(3, "AMZN", 2, 7),
        "4": _order(4, "MSFT", 0, 1),
    }
    report = find_overlapping_orders(orders)
    assert report["num_overlapping_limit_pairs"] == 3  # (1,2) (1,3) (2,3)
    assert {tuple(pair["orders"]) for pair in report["overlapping_limit_pairs"]} == {("1", "2"), ("1", "3"), ("2", "3")}


def test_sequential_orders_and_opposite_directions_do_not_overlap():
    orders = {
        "1": _order(1, "AMZN", 0, 1),
        "2": _order(2, "AMZN", 1, 2),  # starts exactly when 1 closed
        "3": _order(3, "AMZN", 0, 5, direction=1),  # a sell is a different position intent
    }
    assert find_overlapping_orders(orders)["num_overlapping_pairs"] == 0


def test_limit_orders_open_longer_than_the_threshold_are_flagged():
    orders = {"1": _order(1, "HYG", 0, 18), "2": _order(2, "HYG", 30, 31), "3": _order(3, "SPY", 0, 40, order_type=4)}
    report = find_overlapping_orders(orders, max_open_days=5.0)
    assert report["num_limit_orders_open_too_long"] == 1  # only the limit order; market-on-open ignored
    assert report["limit_orders_open_too_long"][0]["symbol"] == "HYG"


def test_canceled_orders_are_windowed_by_their_cancel_time():
    orders = {
        "1": _order(1, "BA", 0, 3, status=5, filled=False),
        "2": _order(2, "BA", 1, 2),
    }
    assert find_overlapping_orders(orders)["num_overlapping_limit_pairs"] == 1


def test_orders_without_timestamps_are_skipped_not_fatal():
    report = find_overlapping_orders({"1": {"symbol": {"value": "X"}}, "2": _order(2, "X", 0, 1)})
    assert report["num_overlapping_pairs"] == 0


# ---------------------------------------------------------------- book membership


HISTORY = [
    {"date": "2019-01-08", "allocations": {"NKE": {"role": "long"}, "EURUSD": {"role": "short"}}},
    {"date": "2019-01-18", "allocations": {}, "gate_veto_reason": "rolling_ic_below_floor"},
    {"date": "2019-01-28", "allocations": {"FB": {"role": "long"}}},
]


def test_carried_book_is_the_latest_record_on_or_before_the_date():
    assert carried_book_members(HISTORY, "2019-01-07") is None
    assert carried_book_members(HISTORY, "2019-01-10") == frozenset({"NKE", "EURUSD"})
    assert carried_book_members(HISTORY, "2019-01-20") == frozenset()  # vetoed: no book
    assert carried_book_members(HISTORY, "2019-02-15") == frozenset({"FB"})


def _trade(symbol, order_ids, entry_day, exit_day, pnl=-10.0, fees=1.0):
    return {
        "symbols": [{"value": symbol}],
        "orderIds": order_ids,
        "entryTime": _iso(entry_day),
        "exitTime": _iso(exit_day),
        "profitLoss": pnl,
        "totalFees": fees,
    }


def test_entries_split_into_book_member_non_member_and_no_record_by_asset_class():
    orders = {
        "1": _order(1, "NKE", 8, 9),                       # created 2019-01-09: NKE is in the carried book
        "2": _order(2, "AAPL", 9, 10),                     # equity, not in the book -> legacy signal
        "3": _order(3, "EURUSD", 9, 10, security_type=4),  # forex book member
        "4": _order(4, "XOM", 2, 3),                       # before any record
        "5": _order(5, "TLT", 20, 21),                     # during the veto: no book
    }
    trades = [
        _trade("NKE", [1], 9, 20),
        _trade("AAPL", [2], 10, 20),
        _trade("EURUSD", [3], 10, 20),
        _trade("XOM", [4], 3, 20),
        _trade("TLT", [5], 21, 30),
    ]
    result = classify_entries(trades, orders, HISTORY)
    assert result["equity"] == {"book_member": 1, "non_member": 2, "no_book_record": 1}
    assert result["forex"] == {"book_member": 1}


def test_pnl_by_entry_bucket_splits_book_and_legacy_sleeve_net_of_fees():
    orders = {"1": _order(1, "NKE", 8, 9), "2": _order(2, "AAPL", 9, 10), "3": _order(3, "MSFT", 9, 10)}
    trades = [_trade("NKE", [1], 9, 20, pnl=100.0, fees=4.0), _trade("AAPL", [2], 10, 20, pnl=-30.0, fees=5.0), _trade("MSFT", [3], 10, 20, pnl=-10.0, fees=1.0)]
    result = pnl_by_entry_bucket(trades, orders, HISTORY)
    assert result["equity"]["book_member"] == {"trades": 1, "realized_pnl": 100.0, "fees": 4.0, "net_pnl": 96.0}
    assert result["equity"]["non_member"] == {"trades": 2, "realized_pnl": -40.0, "fees": 6.0, "net_pnl": -46.0}


def test_select_run_book_history_picks_one_run_out_of_the_cumulative_log():
    log = [{"date": "2019-01-02"}, {"date": "2019-01-12"}, {"date": "2019-01-02"}, {"date": "2019-01-22"}]
    assert [r["date"] for r in select_run_book_history(log, -1)] == ["2019-01-02", "2019-01-22"]
    assert [r["date"] for r in select_run_book_history(log, 0)] == ["2019-01-02", "2019-01-12"]
    assert select_run_book_history(log, 5) == []
    assert select_run_book_history([], -1) == []


def test_load_book_history_keeps_file_order_and_skips_corrupt_lines(tmp_path):
    path = tmp_path / "book_history.jsonl"
    path.write_text('{"date": "2019-02-01"}\nnot json\n\n{"date": "2019-01-01"}\n', encoding="utf-8")
    assert [r["date"] for r in load_book_history(path)] == ["2019-02-01", "2019-01-01"]  # NOT date-sorted
    assert load_book_history(tmp_path / "missing.jsonl") == []


# ---------------------------------------------------------------- holding / pnl / book summary / teardown


def test_holding_period_histogram_exposes_the_cooldown_cluster():
    trades = [_trade("A", [1], 0, 0.5), _trade("B", [2], 0, 14), _trade("C", [3], 0, 15.9), _trade("D", [4], 0, 40)]
    histogram = holding_period_histogram(trades)
    assert histogram == {"0-1d": 1, "11-15d": 2, "21d+": 1}


def test_pnl_and_fee_bps_are_reported_per_asset_class():
    orders = {"1": _order(1, "AMZN", 0, 1), "2": _order(2, "EURUSD", 0, 1, security_type=4)}
    trades = [_trade("AMZN", [1], 0, 5, pnl=-100.0), _trade("EURUSD", [2], 0, 5, pnl=-300.0), _trade("AMZN", [1], 6, 8, pnl=40.0)]
    events = [
        {"status": "filled", "symbolValue": "AMZN", "fillPrice": 4.0, "fillQuantity": 1000.0, "orderFeeAmount": 4.0},
        {"status": "submitted", "symbolValue": "AMZN", "fillPrice": 0.0, "fillQuantity": 0.0},
        {"status": "filled", "symbolValue": "EURUSD", "fillPrice": 1.1, "fillQuantity": 10000.0, "orderFeeAmount": 2.0},
    ]
    report = pnl_and_fees_by_asset_class(trades, orders, events)
    assert report["equity"]["realized_pnl"] == -60.0
    assert report["equity"]["fee_bps_per_fill"] == pytest.approx(10.0)  # 4 / (4*1000) = 10 bps: the sub-$5 price problem
    assert report["forex"]["realized_pnl"] == -300.0


def test_book_summary_counts_vetoes_and_member_fates_inside_the_window():
    records = [
        {"date": "2019-01-01", "allocations": {"A": {}}, "book_member_decisions": {
            "A": {"action": "trade", "reasons": ["topology_state=normal", "ok"]},
            "B": {"action": "reduce_risk", "reasons": ["kill_switch_rolling_sharpe_below_floor"]},
        }},
        {"date": "2019-01-11", "allocations": {}, "gate_veto_reason": "rolling_ic_below_floor"},
        {"date": "2019-01-21", "allocations": {}},
        {"date": "2020-01-01", "allocations": {"Z": {}}},  # outside the window
    ]
    summary = summarize_book_history(records, "2019-01-01", "2019-06-30")
    assert summary["num_rebalance_records"] == 3
    assert summary["num_engaged"] == 1
    assert summary["veto_reasons"] == {"rolling_ic_below_floor": 1, "none": 1}
    assert summary["member_decision_actions"] == {"trade": 1, "reduce_risk": 1}
    assert summary["member_decision_top_reasons"]["topology_state"] == 1  # grouped by name, not value


def test_teardown_status_reads_the_engine_log_markers():
    hung = (
        "TRACE:: PythonInitializer.Shutdown(): start\n"
        "ERROR:: Security.ExecuteWithTimeLimit(): Execution Security Error: Operation timed out\n"
        "ERROR:: Program.Exit(): Failed to shutdown python System.TimeoutException"
    )
    clean = "TRACE:: PythonInitializer.Shutdown(): start\nTRACE:: PythonInitializer.Shutdown(): ended"
    assert teardown_status(hung) == {"shutdown_ended": False, "timed_out": True, "failed_to_shutdown_python": True}
    assert teardown_status(clean) == {"shutdown_ended": True, "timed_out": False, "failed_to_shutdown_python": False}
    assert teardown_status("") == {"shutdown_ended": False, "timed_out": False, "failed_to_shutdown_python": False}


# ---------------------------------------------------------------- end to end on a synthetic run folder


def _write_run_folder(tmp_path):
    run_dir = tmp_path / "2026-01-01_00-00-00"
    run_dir.mkdir()
    result = _equity_chart([100000.0 + 50.0 * i * (1 if i % 3 else -1) for i in range(40)])
    result["charts"]["Exposure"] = {"series": {"Forex - Short Ratio": {"values": [[1, -0.5], [2, -0.1]]}}}
    result["statistics"] = {"Sharpe Ratio": "-1.0", "Net Profit": "-2.000%", "Total Orders": "3"}
    result["orders"] = {
        "1": _order(1, "AMZN", 0, 5),
        "2": _order(2, "AMZN", 1, 6),
        "3": _order(3, "EURUSD", 2, 3, security_type=4),
    }
    result["totalPerformance"] = {
        "closedTrades": [_trade("AMZN", [1], 5, 20), _trade("EURUSD", [3], 3, 4, pnl=-300.0)]
    }
    (run_dir / "1773747993.json").write_text(json.dumps(result), encoding="utf-8")
    (run_dir / "1773747993-order-events.json").write_text(json.dumps([]), encoding="utf-8")
    (run_dir / "log.txt").write_text("PythonInitializer.Shutdown(): ended", encoding="utf-8")
    return run_dir


def test_audit_backtest_run_end_to_end_on_a_synthetic_folder(tmp_path):
    run_dir = _write_run_folder(tmp_path)
    run = load_backtest_run(run_dir)
    assert run["run_id"] == "1773747993"
    audit = audit_backtest_run(run, [{"date": "2019-01-01", "allocations": {"AMZN": {}}}])
    assert audit["window"]["num_days"] == 40
    assert audit["orders"]["num_overlapping_limit_pairs"] == 1
    assert audit["entries_by_asset_class"]["equity"] == {"book_member": 1}
    assert audit["exposure"]["Forex - Short Ratio"]["mean"] == pytest.approx(-0.3)
    assert audit["teardown"]["shutdown_ended"] is True
    assert audit["pnl_and_fees"]["forex"]["realized_pnl"] == -300.0
    assert audit["sharpe"]["with_risk_free"] is not None
    json.dumps(audit)  # the whole report must be JSON-serializable


def test_load_backtest_run_requires_a_result_json(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_backtest_run(tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")  # non-numeric stems are not Lean results
    with pytest.raises(FileNotFoundError):
        load_backtest_run(tmp_path)


def test_audit_degrades_on_a_run_with_no_equity_curve(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "42.json").write_text(json.dumps({}), encoding="utf-8")
    audit = audit_backtest_run(load_backtest_run(run_dir), [])
    assert audit["window"] == {"start": None, "end": None, "num_days": 0}
    assert audit["sharpe"]["no_risk_free"] is None
    assert audit["orders"]["num_overlapping_pairs"] == 0
