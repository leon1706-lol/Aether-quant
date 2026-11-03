"""Which of the simulator's live-gate replicas trade differently from the engine? (V6.4.4, rule R-CAL5, Problems #249 lead)

R-CAL4 found the live-gate rung (resize threshold, entry cooldown, trailing stop) lowers the simulator's daily correlation
with Lean on every run. This module classifies the trades both sides made, so the mechanism that differs most is named:

  * Lean: every fill of a main-book ticker, aggregated per (date, ticker), against the position before it -> entry, exit,
    flip or resize (the order events carry no reason tag);
  * offline: the day-over-day change of the simulator's `weights_log` (its weights only move when it trades).

`trade_profile` counts each kind on and off live's rebalance dates and the sessions between consecutive trades of a ticker
(the cooldown's footprint); `compare_profiles` puts both sides next to each other with each kind's share of the total
absolute count gap. Pure; no I/O.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence

KINDS = ("entry", "exit", "flip", "resize")


def _kind(before: float, after: float, tolerance: float) -> str | None:
    if abs(after - before) <= tolerance:
        return None
    if abs(before) <= tolerance:
        return "entry"
    if abs(after) <= tolerance:
        return "exit"
    if (before > 0) != (after > 0):
        return "flip"
    return "resize"


def lean_trades(fills: Iterable, tickers: set[str] | None = None, *, tolerance: float = 1e-9) -> list[dict]:
    """[{date, ticker, kind}] from signed fills (`evaluation.lean_attribution.Fill`), one per (date, ticker)."""
    position: dict[str, float] = {}
    by_day: dict[tuple[str, str], float] = {}
    order: list[tuple[str, str]] = []
    for fill in fills:
        ticker = str(fill.ticker).upper()
        if tickers is not None and ticker not in tickers:
            continue
        key = (str(fill.date)[:10], ticker)
        if key not in by_day:
            by_day[key] = 0.0
            order.append(key)
        by_day[key] += float(fill.quantity)
    out = []
    for date, ticker in sorted(order):
        before = position.get(ticker, 0.0)
        after = before + by_day[(date, ticker)]
        position[ticker] = after
        kind = _kind(before, after, tolerance)
        if kind:
            out.append({"date": date, "ticker": ticker, "kind": kind})
    return out


def offline_trades(dates: Sequence[str], weights_log: Sequence[Mapping[str, float]], *, tolerance: float = 1e-9) -> list[dict]:
    """[{date, ticker, kind}] from the simulator's post-rebalance weights per date."""
    out, previous = [], {}
    for date, weights in zip(dates, weights_log):
        weights = weights or {}
        for ticker in sorted(set(previous) | set(weights)):
            kind = _kind(float(previous.get(ticker, 0.0)), float(weights.get(ticker, 0.0)), tolerance)
            if kind:
                out.append({"date": str(date)[:10], "ticker": str(ticker).upper(), "kind": kind})
        previous = dict(weights)
    return out


def trade_profile(trades: Sequence[Mapping], rebalance_dates: Iterable[str], session_dates: Sequence[str], *,
                  lag_sessions: int = 0) -> dict:
    """Counts per kind on / off the rebalance dates and the median sessions between a ticker's consecutive trades.
    `lag_sessions` counts a trade up to that many sessions after a rebalance date as on it (Lean fills a close decision at
    the next open, so its fills are dated one session later than the simulator's decision)."""
    ordered = sorted(str(date)[:10] for date in session_dates)
    position = {date: index for index, date in enumerate(ordered)}
    rebalance = set()
    for date in rebalance_dates:
        index = position.get(str(date)[:10])
        if index is None:
            rebalance.add(str(date)[:10])
            continue
        rebalance.update(ordered[index:index + lag_sessions + 1])
    counts = {kind: 0 for kind in KINDS}
    off = {kind: 0 for kind in KINDS}
    last_index: dict[str, int] = {}
    gaps: list[int] = []
    for trade in sorted(trades, key=lambda item: (item["date"], item["ticker"])):
        counts[trade["kind"]] += 1
        if trade["date"] not in rebalance:
            off[trade["kind"]] += 1
        index = position.get(trade["date"])
        if index is not None:
            if trade["ticker"] in last_index:
                gaps.append(index - last_index[trade["ticker"]])
            last_index[trade["ticker"]] = index
    return {"counts": counts, "off_rebalance": off, "total": sum(counts.values()),
            "median_sessions_between_trades": statistics.median(gaps) if gaps else None,
            "share_within_5_sessions": (sum(1 for gap in gaps if gap <= 5) / len(gaps)) if gaps else None}


def compare_profiles(lean: Mapping, offline: Mapping) -> dict:
    """Side by side per kind (all / off-rebalance), each kind's share of the summed absolute count gap, ranked."""
    rows, total_gap = {}, 0.0
    for kind in KINDS:
        for scope in ("counts", "off_rebalance"):
            gap = abs(int(offline[scope][kind]) - int(lean[scope][kind]))
            rows[f"{scope}.{kind}"] = {"lean": int(lean[scope][kind]), "offline": int(offline[scope][kind]), "abs_gap": gap}
            total_gap += gap
    for row in rows.values():
        row["gap_share"] = row["abs_gap"] / total_gap if total_gap else 0.0
    ranked = sorted(rows, key=lambda name: rows[name]["abs_gap"], reverse=True)
    return {"rows": rows, "ranked": ranked,
            "median_sessions_between_trades": {"lean": lean.get("median_sessions_between_trades"),
                                               "offline": offline.get("median_sessions_between_trades")},
            "share_within_5_sessions": {"lean": lean.get("share_within_5_sessions"), "offline": offline.get("share_within_5_sessions")}}
