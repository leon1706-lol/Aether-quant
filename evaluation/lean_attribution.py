"""Daily P&L of a finished Lean run, rebuilt per ticker and per component (V6.0.0, todo lead 2).

The offline as-live simulator is only useful if it predicts what Lean does, and V5.8.0's BT1 showed a daily return
correlation of 0.02 between them. This module rebuilds the Lean side in the simulator's own terms so the two can be
compared day by day:

  * every fill from `<id>-order-events.json` (signed quantity, price, fee, limit or market),
  * end-of-day positions and their mark-to-market P&L against the Lean data zips' daily closes (forex P&L converted from
    the quote currency to USD with the zips' own rates),
  * each ticker-day assigned to a component: the main book (members of the last FORMED book in the book-history log;
    live holds the book through a vetoed rebalance), the legacy signal (an equity/crypto position outside it), the bond
    and forex sleeves (by config asset class), crypto split into the core pairs and the capped graduates (a crypto
    position outside the book is `legacy_crypto`),
  * per rebalance date, what the live gates decided (engaged / vetoed and why) for the decision-agreement check.

A daily fill's event time is the END of the bar it filled in (equity 16:00 New York = 20:00 UTC, crypto and forex the
next 00:00 UTC), so its bar date is the UTC date one second earlier. Pure functions plus thin zip/JSON readers.
"""

from __future__ import annotations

import bisect
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

LEAN_EQUITY_PRICE_SCALE = 1.0 / 10_000.0
COMPONENTS = ("main_book", "legacy", "legacy_crypto", "bond_sleeve", "forex_sleeve", "crypto_core", "crypto_graduate")


@dataclass(frozen=True)
class Fill:
    date: str
    ticker: str
    quantity: float
    price: float
    fee: float
    is_limit: bool


def fills_from_order_events(events: list[dict]) -> list[Fill]:
    """Filled (or partially filled) events in time order; quantity is signed (buy > 0)."""
    fills = []
    for event in sorted(events, key=lambda item: (float(item.get("time", 0.0)), int(item.get("orderEventId", 0) or 0))):
        if str(event.get("status", "")).lower() not in {"filled", "partiallyfilled"}:
            continue
        quantity = float(event.get("fillQuantity") or 0.0)
        price = float(event.get("fillPrice") or 0.0)
        if quantity == 0.0 or price <= 0.0:
            continue
        bar_end = datetime.fromtimestamp(float(event["time"]) - 1.0, tz=timezone.utc)
        fills.append(
            Fill(
                date=bar_end.date().isoformat(),
                ticker=str(event.get("symbolValue") or event.get("symbol", "")).upper(),
                quantity=quantity,
                price=price,
                fee=abs(float(event.get("orderFeeAmount") or 0.0)),
                is_limit=event.get("limitPrice") not in (None, 0, 0.0),
            )
        )
    return fills


def read_daily_closes(zip_path: Path, price_scale: float = 1.0) -> dict[str, float]:
    """{YYYY-MM-DD: close} of a Lean daily zip (missing file -> {})."""
    path = Path(zip_path)
    if not path.exists():
        return {}
    closes: dict[str, float] = {}
    with zipfile.ZipFile(path) as archive:
        member = next((name for name in archive.namelist() if name.endswith(".csv")), None)
        if member is None:
            return {}
        for line in archive.read(member).decode("utf-8", errors="replace").splitlines():
            fields = line.split(",")
            if len(fields) < 5 or len(fields[0]) < 8:
                continue
            try:
                closes[f"{fields[0][:4]}-{fields[0][4:6]}-{fields[0][6:8]}"] = float(fields[4]) * price_scale
            except ValueError:
                continue
    return closes


def closes_for_universe(config: dict, root: Path, tickers: set[str]) -> dict[str, dict[str, float]]:
    """Daily closes of `tickers` (plus the forex rates needed to convert quote currencies) from their config zips."""
    assets = {str(asset["ticker"]).upper(): asset for asset in config["phase1"]["universe"]["assets"]}
    wanted = set(tickers)
    for ticker in tickers:
        if assets.get(ticker, {}).get("security_type") == "forex":
            wanted.update(name for name in assets if assets[name].get("security_type") == "forex")
    closes = {}
    for ticker in wanted:
        asset = assets.get(ticker)
        if asset is None:
            continue
        scale = LEAN_EQUITY_PRICE_SCALE if asset.get("security_type") == "equity" else 1.0
        closes[ticker] = read_daily_closes(Path(root) / asset["data_path"], scale)
    return closes


def _value_asof(series: dict[str, float], sorted_dates: list[str], date: str) -> float | None:
    position = bisect.bisect_right(sorted_dates, date) - 1
    return series[sorted_dates[position]] if position >= 0 else None


def quote_to_usd_rate(ticker: str, date: str, closes: dict[str, dict[str, float]], sorted_dates: dict[str, list[str]]) -> float:
    """USD per one unit of a forex pair's quote currency on `date` (1.0 for XXXUSD and every non-forex ticker)."""
    if len(ticker) != 6 or ticker.endswith("USD"):
        return 1.0
    quote = ticker[3:]
    direct, inverse = f"{quote}USD", f"USD{quote}"
    if direct in closes:
        value = _value_asof(closes[direct], sorted_dates[direct], date)
        return float(value) if value else 1.0
    if inverse in closes:
        value = _value_asof(closes[inverse], sorted_dates[inverse], date)
        return 1.0 / float(value) if value else 1.0
    return 1.0


def daily_ticker_pnl(
    fills: list[Fill], closes: dict[str, dict[str, float]], dates: list[str], forex_tickers: set[str] = frozenset()
) -> dict[str, dict[str, dict]]:
    """{date: {ticker: {"pnl": gross USD P&L, "fee": USD, "position": end-of-day quantity, "fills": n, "limit_fills": n,
    "notional": traded USD}}} over `dates` (sorted). A position carried into a date earns quantity x (close - previous
    close); a fill earns quantity x (close - fill price) on its own date. Prices missing on a date carry the last one."""
    sorted_dates = {ticker: sorted(series) for ticker, series in closes.items()}
    fills_by_date: dict[str, list[Fill]] = defaultdict(list)
    for fill in fills:
        fills_by_date[fill.date].append(fill)
    positions: dict[str, float] = defaultdict(float)
    last_close: dict[str, float] = {}
    out: dict[str, dict[str, dict]] = {}
    wanted_dates = set(dates)
    calendar = sorted(wanted_dates | set(fills_by_date))
    for date in calendar:
        day: dict[str, dict] = {}
        tickers = {ticker for ticker, quantity in positions.items() if quantity != 0.0} | {fill.ticker for fill in fills_by_date.get(date, [])}
        for ticker in tickers:
            series = closes.get(ticker, {})
            close = series.get(date)
            if close is None:
                close = _value_asof(series, sorted_dates.get(ticker, []), date) if series else None
            rate = quote_to_usd_rate(ticker, date, closes, sorted_dates) if ticker in forex_tickers else 1.0
            entry = {"pnl": 0.0, "fee": 0.0, "position": 0.0, "fills": 0, "limit_fills": 0, "notional": 0.0}
            held = positions[ticker]
            if held != 0.0 and close is not None and ticker in last_close:
                entry["pnl"] += held * (close - last_close[ticker]) * rate
            for fill in fills_by_date.get(date, []):
                if fill.ticker != ticker:
                    continue
                if close is not None:
                    entry["pnl"] += fill.quantity * (close - fill.price) * rate
                entry["fee"] += fill.fee
                entry["fills"] += 1
                entry["limit_fills"] += int(fill.is_limit)
                entry["notional"] += abs(fill.quantity * fill.price) * rate
                positions[ticker] += fill.quantity
            if abs(positions[ticker]) < 1e-12:
                positions[ticker] = 0.0
            entry["position"] = positions[ticker]
            if close is not None:
                last_close[ticker] = close
            day[ticker] = entry
        if date in wanted_dates or day:
            out[date] = day
    return out


def formed_book_by_date(book_history: list[dict], dates: list[str]) -> dict[str, frozenset[str]]:
    """Members of the last FORMED (non-empty) book on or before each date; live holds it through a vetoed rebalance."""
    records = sorted((record for record in book_history if record.get("allocations")), key=lambda record: record["date"])
    record_dates = [record["date"] for record in records]
    out = {}
    for date in dates:
        position = bisect.bisect_right(record_dates, date) - 1
        out[date] = frozenset(records[position]["allocations"]) if position >= 0 else frozenset()
    return out


def component_of(ticker: str, asset_class: str, members: frozenset[str], core_crypto: set[str]) -> str:
    if asset_class == "bond":
        return "bond_sleeve"
    if asset_class == "forex":
        return "forex_sleeve"
    if asset_class == "crypto":
        if ticker not in members:
            return "legacy_crypto"
        return "crypto_core" if ticker in core_crypto else "crypto_graduate"
    return "main_book" if ticker in members else "legacy"


def component_daily_pnl(
    ticker_pnl: dict[str, dict[str, dict]], class_by_ticker: dict[str, str], members_by_date: dict[str, frozenset[str]],
    core_crypto: set[str],
) -> dict[str, dict[str, dict]]:
    """{date: {component: {"pnl", "fee", "fills", "limit_fills", "notional"}}}. A position is assigned on each day by the
    book in force that day, so a member that leaves the book becomes legacy only if it is still held."""
    out: dict[str, dict[str, dict]] = {}
    for date, day in ticker_pnl.items():
        members = members_by_date.get(date, frozenset())
        components: dict[str, dict] = {}
        for ticker, entry in day.items():
            name = component_of(ticker, class_by_ticker.get(ticker, "equity"), members, core_crypto)
            bucket = components.setdefault(name, {"pnl": 0.0, "fee": 0.0, "fills": 0, "limit_fills": 0, "notional": 0.0})
            for key in bucket:
                bucket[key] += entry[key]
        out[date] = components
    return out


def rebalance_decisions(book_history: list[dict], start: str | None = None, end: str | None = None) -> dict[str, dict]:
    """{date: {"engaged": bool, "reason": veto reason or None, "members": n}} for each live rebalance record in the window
    (warm-up records whose universe was not ready are dropped: they carry `thin_universe_or_zero_top_n`)."""
    out = {}
    for record in sorted(book_history, key=lambda item: item.get("date", "")):
        date = record.get("date", "")
        if (start and date < start) or (end and date > end):
            continue
        reason = record.get("gate_veto_reason")
        out[date] = {"engaged": bool(record.get("allocations")), "reason": reason, "members": len(record.get("allocations") or {})}
    return out


def fee_bps_by_route(ticker_pnl: dict[str, dict[str, dict]], class_by_ticker: dict[str, str], fills: list[Fill],
                     closes_rate=None) -> dict[str, dict]:
    """Per asset class and route (limit / market): fills, fees and fee per traded notional in bps."""
    totals: dict[str, dict] = defaultdict(lambda: {"fills": 0, "fee": 0.0, "notional": 0.0})
    for fill in fills:
        key = f"{class_by_ticker.get(fill.ticker, 'equity')}/{'limit' if fill.is_limit else 'market'}"
        bucket = totals[key]
        bucket["fills"] += 1
        bucket["fee"] += fill.fee
        rate = closes_rate(fill) if closes_rate else 1.0
        bucket["notional"] += abs(fill.quantity * fill.price) * rate
    return {
        key: dict(value, fee_bps=(value["fee"] / value["notional"] * 1e4) if value["notional"] else None)
        for key, value in sorted(totals.items())
    }


def reconcile_with_equity_curve(component_pnl: dict[str, dict[str, dict]], daily_equity: list[tuple[str, float]]) -> dict:
    """Rebuilt net P&L against Lean's own equity curve: total difference and the correlation of daily changes."""
    import numpy as np

    rebuilt = {date: sum(entry["pnl"] - entry["fee"] for entry in day.values()) for date, day in component_pnl.items()}
    lean = {date: equity - previous for (_, previous), (date, equity) in zip(daily_equity, daily_equity[1:])}
    common = sorted(set(rebuilt) & set(lean))
    total_rebuilt = sum(rebuilt.values())
    total_lean = daily_equity[-1][1] - daily_equity[0][1] if len(daily_equity) > 1 else 0.0
    correlation = None
    if len(common) > 2:
        a = np.array([rebuilt[date] for date in common])
        b = np.array([lean[date] for date in common])
        if a.std() > 0 and b.std() > 0:
            correlation = float(np.corrcoef(a, b)[0, 1])
    return {"rebuilt_net_usd": total_rebuilt, "lean_net_usd": total_lean, "difference_usd": total_rebuilt - total_lean,
            "daily_change_correlation": correlation, "days_compared": len(common)}


def equity_at(result: dict, moment: datetime) -> float | None:
    """Lean's portfolio value at the last chart point at or before `moment` (UTC)."""
    points = result.get("charts", {}).get("Strategy Equity", {}).get("series", {}).get("Equity", {}).get("values", [])
    stamp = moment.timestamp()
    best = None
    for point in points:
        if float(point[0]) <= stamp and (best is None or float(point[0]) >= float(best[0])):
            best = point
    return float(best[-1]) if best is not None else None


def lean_period_net(result: dict, start: str, end: str) -> float | None:
    """Lean's net P&L over the bars dated start..end: the 00:00 UTC chart points bracket every class's bars (equity closes
    at 20:00 UTC, a crypto/forex bar ends at 00:00 UTC), so a period edge never splits a bar."""
    from datetime import timedelta

    opening = equity_at(result, datetime.fromisoformat(start).replace(tzinfo=timezone.utc))
    closing = equity_at(result, datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1))
    if opening is None or closing is None:
        return None
    return closing - opening


def attribute_run(
    run: dict, book_history: list[dict], config: dict, root: Path, *, period: tuple[str, str] | None = None,
    core_crypto: set[str] | None = None,
) -> dict:
    """The whole attribution for one loaded run (`evaluation.backtest_audit.load_backtest_run`)."""
    from evaluation.backtest_audit import daily_equity_from_chart

    class_by_ticker = {
        str(asset["ticker"]).upper(): str(asset.get("asset_class") or asset.get("security_type"))
        for asset in config["phase1"]["universe"]["assets"]
    }
    if core_crypto is None:
        caps = (config.get("phase_v2", {}).get("class_weight_caps", {}) or {}).get("crypto", {}) or {}
        core_crypto = {str(ticker).upper() for ticker in caps.get("exempt", [])}
    fills = fills_from_order_events(run["order_events"])
    daily_equity = daily_equity_from_chart(run["result"])
    dates = [date for date, _ in daily_equity]  # the whole run: a period is cut AFTER the marks are rebuilt
    tickers = {fill.ticker for fill in fills}
    closes = closes_for_universe(config, root, tickers)
    forex = {ticker for ticker, kind in class_by_ticker.items() if kind == "forex"}
    ticker_pnl = daily_ticker_pnl(fills, closes, dates, forex)
    if period:
        ticker_pnl = {date: day for date, day in ticker_pnl.items() if period[0] <= date <= period[1]}
        before = [(date, value) for date, value in daily_equity if date < period[0]][-1:]  # the period's opening value
        daily_equity = before + [(date, value) for date, value in daily_equity if period[0] <= date <= period[1]]
    members = formed_book_by_date(book_history, sorted(ticker_pnl))
    components = component_daily_pnl(ticker_pnl, class_by_ticker, members, core_crypto)
    totals = {name: {"pnl": 0.0, "fee": 0.0, "fills": 0, "limit_fills": 0, "notional": 0.0} for name in COMPONENTS}
    for day in components.values():
        for name, entry in day.items():
            for key in totals[name]:
                totals[name][key] += entry[key]
    for entry in totals.values():
        entry["net"] = entry["pnl"] - entry["fee"]
    sorted_closes = {ticker: sorted(series) for ticker, series in closes.items()}
    in_period = [fill for fill in fills if not period or period[0] <= fill.date <= period[1]]
    routes = fee_bps_by_route(
        ticker_pnl, class_by_ticker, in_period,
        closes_rate=lambda fill: quote_to_usd_rate(fill.ticker, fill.date, closes, sorted_closes) if fill.ticker in forex else 1.0,
    )
    return {
        "period": list(period) if period else None,
        "components": totals,
        "fees_by_route": routes,
        "reconciliation": _reconciliation(components, daily_equity, run["result"], period),
        "rebalances": rebalance_decisions(book_history, *(period or (None, None))),
        "daily_components": {date: {name: round(entry["pnl"] - entry["fee"], 6) for name, entry in day.items()}
                             for date, day in sorted(components.items())},
        "daily_equity": daily_equity,
    }


def _reconciliation(components: dict, daily_equity: list, result: dict, period: tuple[str, str] | None) -> dict:
    report = reconcile_with_equity_curve(components, daily_equity)
    if period:
        lean_net = lean_period_net(result, period[0], period[1])
        if lean_net is not None:
            report["lean_net_usd"] = lean_net
            report["difference_usd"] = report["rebuilt_net_usd"] - lean_net
    return report


def find_book_history_for_run(run_dir: Path, book_history_dir: Path) -> Path | None:
    """The per-run book-history file (`<UTC start>.jsonl`) that started closest to the run folder's own timestamp
    (`YYYY-MM-DD_HH-MM-SS`, local time): runs are hours apart, the time-zone offset is not."""
    try:
        started = datetime.strptime(Path(run_dir).name[:19], "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None
    best, best_gap = None, None
    for path in Path(book_history_dir).glob("*.jsonl"):
        try:
            stamp = datetime.strptime(path.stem, "%Y%m%dT%H%M%SZ")
        except ValueError:
            continue
        gap = abs((stamp - started).total_seconds())
        if best_gap is None or gap < best_gap:
            best, best_gap = path, gap
    return best if best_gap is not None and best_gap <= 12 * 3600 else None
