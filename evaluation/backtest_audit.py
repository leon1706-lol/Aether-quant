"""Order-level audit of a finished Lean backtest (V5.5.0, Problems.md #127/#128).

Lean's own statistics say HOW MUCH a run made; they cannot say WHAT it traded.
The 2026-08-27 backtest (Sharpe -2.51 against an offline book at ~+1) was only
explained by reading its fills by hand: equity gross ~3% of NAV, 121 of 155
equity entries from the old probability signal rather than the book, forex
sized outside the book up to 60% short, duplicate limit orders that never
timed out, and a Sharpe that differed by ~1.1 purely because Lean subtracts a
risk-free rate. This module is that reading, made repeatable: every number
the trace used, computed from the run folder alone (no Lean, no Docker).

Pure functions over parsed JSON/text plus one loader, so each metric is unit
tested on a synthetic run (tests/test_backtest_audit.py). stdlib only.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from evaluation.rank_signal_calibration import segment_logged_records_by_run

# Lean enums (QuantConnect.Orders / QuantConnect.SecurityType).
ORDER_STATUS_FILLED = 3
ORDER_STATUS_CANCELED = 5
ORDER_TYPE_LIMIT = 1
SECURITY_TYPE_NAMES = {1: "equity", 2: "option", 4: "forex", 5: "future", 7: "crypto"}
TRADE_DIRECTION_SHORT = 1

HOLDING_BUCKETS = ((0, 1, "0-1d"), (2, 5, "2-5d"), (6, 10, "6-10d"), (11, 15, "11-15d"), (16, 20, "16-20d"))


def _parse_time(value) -> datetime | None:
    """Lean writes ISO-8601 strings in orders/trades and epoch seconds in
    charts/order events."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _symbol_value(order: dict) -> str:
    symbol = order.get("symbol")
    if isinstance(symbol, dict):
        return str(symbol.get("value", ""))
    return str(symbol or "")


def _asset_class(order: dict) -> str:
    return SECURITY_TYPE_NAMES.get(int(order.get("securityType", 0) or 0), "other")


# ---------------------------------------------------------------- equity / Sharpe


def daily_equity_from_chart(result: dict) -> list[tuple[str, float]]:
    """(date, close equity) from the 'Strategy Equity' chart, last point per
    UTC day. The chart also carries intraday points, which would otherwise
    inflate the return count."""
    series = (
        result.get("charts", {}).get("Strategy Equity", {}).get("series", {}).get("Equity", {}).get("values", [])
    )
    last_by_day: dict[str, float] = {}
    for point in sorted(series, key=lambda candidate: candidate[0]):
        timestamp = _parse_time(point[0])
        close = point[-1] if isinstance(point, (list, tuple)) else None
        if timestamp is None or close is None:
            continue
        last_by_day[timestamp.date().isoformat()] = float(close)
    return sorted(last_by_day.items())


def sharpe_from_equity(
    daily_equity: list[tuple[str, float]], risk_free_annual: float = 0.0, trading_days: int = 252
) -> float | None:
    """Annualized Sharpe of daily equity returns. `risk_free_annual` is
    subtracted per day, exactly as Lean does with its own rate - the
    offline simulators subtract nothing, so the same curve scores ~1.1
    points differently at 1.3% annual volatility. None when undefined."""
    values = [equity for _, equity in daily_equity]
    returns = [b / a - 1.0 for a, b in zip(values, values[1:]) if a > 0.0]
    if len(returns) < 2:
        return None
    daily_rf = risk_free_annual / trading_days
    excess = [value - daily_rf for value in returns]
    mean = sum(excess) / len(excess)
    variance = sum((value - mean) ** 2 for value in excess) / (len(excess) - 1)
    if variance <= 0.0:
        return None
    return mean / math.sqrt(variance) * math.sqrt(trading_days)


def exposure_summary(result: dict) -> dict[str, dict[str, float]]:
    """Mean / max / peak of each series in Lean's 'Exposure' chart (long/short
    ratio per asset class, fraction of NAV). Short series are NEGATIVE, so
    `max` is 0.0 for them and says nothing about the cap; `peak` is the value
    of largest magnitude (the figure to compare with a short-exposure cap)."""
    summary: dict[str, dict[str, float]] = {}
    for name, series in result.get("charts", {}).get("Exposure", {}).get("series", {}).items():
        values = [float(point[1]) for point in series.get("values", []) if point[1] is not None]
        if values:
            summary[name] = {"mean": sum(values) / len(values), "max": max(values), "peak": max(values, key=abs)}
    return summary


# ---------------------------------------------------------------- orders


def find_overlapping_orders(orders: dict[str, dict], max_open_days: float = 5.0) -> dict:
    """Same-symbol, same-direction orders whose open windows overlap, and
    orders that stayed open longer than `max_open_days`.

    A window runs from createdTime to the fill (lastFillTime) or the cancel.
    Overlap on a LIMIT order is the V5.5.0 bug: a still-unfilled entry was
    re-submitted every bar without cancelling the previous ticket, so several
    could fill (AMZN: three orders, 689 shares, ~3x target)."""
    windows: dict[tuple[str, int], list[tuple[datetime, datetime, str, int]]] = defaultdict(list)
    open_too_long: list[dict] = []
    for order_id, order in orders.items():
        created = _parse_time(order.get("createdTime") or order.get("time"))
        closed = _parse_time(order.get("lastFillTime") or order.get("canceledTime"))
        if created is None or closed is None:
            continue
        symbol = _symbol_value(order)
        direction = int(order.get("direction", 0) or 0)
        order_type = int(order.get("type", 0) or 0)
        windows[(symbol, direction)].append((created, closed, str(order_id), order_type))
        open_days = (closed - created).total_seconds() / 86400.0
        if order_type == ORDER_TYPE_LIMIT and open_days > max_open_days:
            open_too_long.append({"symbol": symbol, "order_id": str(order_id), "open_days": round(open_days, 2)})

    overlapping_pairs: list[dict] = []
    for (symbol, _direction), entries in windows.items():
        entries.sort()
        for index, (created, closed, order_id, order_type) in enumerate(entries):
            for other_created, _other_closed, other_id, other_type in entries[index + 1:]:
                if other_created >= closed:
                    break
                overlapping_pairs.append(
                    {
                        "symbol": symbol,
                        "orders": [order_id, other_id],
                        "types": [order_type, other_type],
                    }
                )
    limit_pairs = [pair for pair in overlapping_pairs if ORDER_TYPE_LIMIT in pair["types"]]
    return {
        "num_overlapping_pairs": len(overlapping_pairs),
        "num_overlapping_limit_pairs": len(limit_pairs),
        "overlapping_limit_pairs": limit_pairs[:50],
        "num_limit_orders_open_too_long": len(open_too_long),
        "limit_orders_open_too_long": open_too_long[:50],
        "max_open_days_threshold": max_open_days,
    }


def carried_book_members(book_history: list[dict], on_date: str) -> frozenset[str] | None:
    """The book live was carrying on `on_date`: the allocations of the latest
    record dated <= on_date (a vetoed rebalance logs an EMPTY allocations
    dict, which correctly means 'no book'). None when there is no record."""
    chosen = None
    for record in book_history:
        if record.get("date", "") <= on_date:
            chosen = record
        else:
            break
    if chosen is None:
        return None
    return frozenset((chosen.get("allocations") or {}).keys())


def classify_entries(closed_trades: list[dict], orders: dict[str, dict], book_history: list[dict]) -> dict:
    """Per asset class: how many position openings were book members, how
    many were non-members (the old probability signal), and how many have no
    book record to compare against. `closed_trades` is Lean's
    totalPerformance.closedTrades; the entry's decision date is the
    createdTime of the trade's first order."""
    history = sorted(book_history, key=lambda record: record.get("date", ""))
    counts: dict[str, Counter] = defaultdict(Counter)
    for trade in closed_trades:
        symbols = trade.get("symbols") or []
        symbol = str(symbols[0].get("value", "")) if symbols else ""
        order_ids = trade.get("orderIds") or []
        first_order = orders.get(str(order_ids[0])) if order_ids else None
        asset_class = _asset_class(first_order) if first_order else "other"
        created = _parse_time((first_order or {}).get("createdTime")) or _parse_time(trade.get("entryTime"))
        members = carried_book_members(history, created.date().isoformat()) if created else None
        if members is None:
            bucket = "no_book_record"
        elif symbol in members:
            bucket = "book_member"
        else:
            bucket = "non_member"
        counts[asset_class][bucket] += 1
    return {asset_class: dict(counter) for asset_class, counter in sorted(counts.items())}


def holding_period_histogram(closed_trades: list[dict]) -> dict[str, int]:
    """Calendar days between entry and exit. A cluster at 14-15 days is the
    signature of exits blocked by `trade_cooldown_bars`."""
    histogram: Counter = Counter()
    for trade in closed_trades:
        entry, exit_time = _parse_time(trade.get("entryTime")), _parse_time(trade.get("exitTime"))
        if entry is None or exit_time is None:
            continue
        days = (exit_time - entry).total_seconds() / 86400.0
        label = "21d+"
        for low, high, name in HOLDING_BUCKETS:
            if low <= days < high + 1:
                label = name
                break
        histogram[label] += 1
    return dict(histogram)


def pnl_and_fees_by_asset_class(closed_trades: list[dict], orders: dict[str, dict], order_events: list[dict]) -> dict:
    """Realized P&L and fees per asset class, and fees in bps of traded
    notional per fill. Per-share fees on a mis-adjusted ~$4 price inflate
    this (16-49 bps per side in the 08-27 run), which is how the double
    split adjustment (Problems.md #128) shows up."""
    class_by_symbol = {_symbol_value(order): _asset_class(order) for order in orders.values()}
    pnl: dict[str, float] = defaultdict(float)
    for trade in closed_trades:
        symbols = trade.get("symbols") or []
        symbol = str(symbols[0].get("value", "")) if symbols else ""
        pnl[class_by_symbol.get(symbol, "other")] += float(trade.get("profitLoss", 0.0) or 0.0)

    fees: dict[str, float] = defaultdict(float)
    notional: dict[str, float] = defaultdict(float)
    for event in order_events:
        if event.get("status") != "filled":
            continue
        asset_class = class_by_symbol.get(str(event.get("symbolValue", "")), "other")
        fees[asset_class] += float(event.get("orderFeeAmount", 0.0) or 0.0)
        notional[asset_class] += abs(float(event.get("fillPrice", 0.0) or 0.0) * float(event.get("fillQuantity", 0.0) or 0.0))
    return {
        asset_class: {
            "realized_pnl": round(pnl.get(asset_class, 0.0), 2),
            "fees": round(fees.get(asset_class, 0.0), 2),
            "fee_bps_per_fill": (
                round(fees[asset_class] / notional[asset_class] * 1e4, 2) if notional.get(asset_class) else None
            ),
        }
        for asset_class in sorted(set(pnl) | set(fees))
    }


# ---------------------------------------------------------------- book history / logs


def summarize_book_history(book_history: list[dict], start_date: str | None, end_date: str | None) -> dict:
    """Gate vetoes and the fate of book members over the run's date window
    (book_history.jsonl accumulates across runs, so it must be windowed)."""
    records = [
        record
        for record in book_history
        if (start_date is None or record.get("date", "") >= start_date)
        and (end_date is None or record.get("date", "") <= end_date)
    ]
    veto_reasons = Counter(record.get("gate_veto_reason") or "none" for record in records if not record.get("allocations"))
    decisions: Counter = Counter()
    decision_reasons: Counter = Counter()
    for record in records:
        for decision in (record.get("book_member_decisions") or {}).values():
            decisions[str(decision.get("action", "unknown"))] += 1
            for reason in decision.get("reasons", []) or []:
                decision_reasons[str(reason).split("=")[0]] += 1
    return {
        "num_rebalance_records": len(records),
        "num_engaged": sum(1 for record in records if record.get("allocations")),
        "veto_reasons": dict(veto_reasons),
        "member_decision_actions": dict(decisions),
        "member_decision_top_reasons": dict(decision_reasons.most_common(10)),
    }


def teardown_status(engine_log_text: str) -> dict:
    """Did Lean's embedded interpreter shut down cleanly? Read from the ENGINE
    log (`<run>/log.txt`), never the algorithm log - #104 was wrongly marked
    clean from `<id>-log.txt`, which never records the teardown."""
    return {
        "shutdown_ended": bool(re.search(r"PythonInitializer\.Shutdown\(\): ended", engine_log_text)),
        "timed_out": "Operation timed out" in engine_log_text,
        "failed_to_shutdown_python": "Failed to shutdown python" in engine_log_text,
    }


# ---------------------------------------------------------------- orchestration


def load_backtest_run(run_dir: Path) -> dict:
    """Reads a Lean run folder. Missing optional files degrade to empty."""
    run_dir = Path(run_dir)
    candidates = [
        path
        for path in run_dir.glob("*.json")
        if re.fullmatch(r"\d+", path.stem)
    ]
    if not candidates:
        raise FileNotFoundError(f"no Lean result JSON (<id>.json) in {run_dir}")
    result_path = candidates[0]
    events_path = run_dir / f"{result_path.stem}-order-events.json"
    engine_log = run_dir / "log.txt"
    return {
        "result": json.loads(result_path.read_text(encoding="utf-8")),
        "order_events": json.loads(events_path.read_text(encoding="utf-8")) if events_path.exists() else [],
        "engine_log": engine_log.read_text(encoding="utf-8", errors="replace") if engine_log.exists() else "",
        "run_id": result_path.stem,
    }


def load_book_history(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    # File order is run order (the log is append-only and never rotated);
    # callers segment it with segment_logged_records_by_run().
    return records


def select_run_book_history(book_history: list[dict], run_index: int = -1) -> list[dict]:
    """book_history.jsonl accumulates EVERY backtest's records, so one date
    recurs across many runs (160 of 174 dates did, one in 8 runs - #99).
    Returns one run's records, date-sorted; run_index=-1 is the latest."""
    segments = segment_logged_records_by_run(book_history)
    if not segments:
        return []
    try:
        segment = segments[run_index]
    except IndexError:
        return []
    return sorted(segment, key=lambda record: record.get("date", ""))


def audit_backtest_run(
    run: dict,
    book_history: list[dict],
    *,
    risk_free_annual: float = 0.02,
    max_open_days: float = 5.0,
    book_run_index: int = -1,
) -> dict:
    """The full audit. `run` is load_backtest_run()'s dict; `book_history`
    is the raw (multi-run) log, of which `book_run_index` selects one run."""
    book_history = select_run_book_history(book_history, book_run_index)
    result = run["result"]
    orders = result.get("orders", {})
    closed_trades = result.get("totalPerformance", {}).get("closedTrades", [])
    equity = daily_equity_from_chart(result)
    start_date = equity[0][0] if equity else None
    end_date = equity[-1][0] if equity else None
    return {
        "run_id": run.get("run_id"),
        "window": {"start": start_date, "end": end_date, "num_days": len(equity)},
        "lean_statistics": {
            key: result.get("statistics", {}).get(key)
            for key in ("Sharpe Ratio", "Net Profit", "Drawdown", "Total Orders", "Total Fees")
        },
        "sharpe": {
            "no_risk_free": sharpe_from_equity(equity, 0.0),
            "with_risk_free": sharpe_from_equity(equity, risk_free_annual),
            "risk_free_annual_assumed": risk_free_annual,
        },
        "exposure": exposure_summary(result),
        "entries_by_asset_class": classify_entries(closed_trades, orders, book_history),
        "orders": find_overlapping_orders(orders, max_open_days=max_open_days),
        "holding_period_days": holding_period_histogram(closed_trades),
        "pnl_and_fees": pnl_and_fees_by_asset_class(closed_trades, orders, run.get("order_events", [])),
        "book": summarize_book_history(book_history, start_date, end_date),
        "teardown": teardown_status(run.get("engine_log", "")),
    }
