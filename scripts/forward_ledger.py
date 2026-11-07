"""Appends today's row to the forward ledger: the frozen rule's decision and what the held weights earned since the last session.

Runs on a bare GitHub runner (numpy, pandas, requests; no torch, no secrets) from `.github/workflows/forward-ledger.yml`. Crypto marks come
from Coinbase's public candles, and a bar is used only once it has closed, as `known_closes` requires. Equity sessions and SPY/AGG come from
Yahoo's chart API. A failed fetch writes a `no_data` row with the reason, never a skipped day.

    python scripts/forward_ledger.py --candidates ml/forward/candidates.json --ledger forward/ledger.jsonl
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.forward_ledger import (  # noqa: E402
    COST_BPS_BY_CLASS,
    append_row,
    decide,
    definition_sha256,
    has_session,
    is_rebalance,
    NoSessionToRecord,
    last_row_for,
    read_ledger,
    resolve_session,
    session_for_outage,
    session_return,
    turnover,
)

COINBASE_URL = "https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2y&interval=1d"
USER_AGENT = "AetherQuantResearch/6.6 (github.com/leon1706-lol/Aether-quant)"
BENCHMARK_SYMBOLS = ("SPY", "AGG")


def coinbase_closes(product: str, get_json: Callable[[str], object]) -> dict[str, float]:
    """{bar date: close}. A row is [time, low, high, open, close, volume], newest first, at most 300 rows."""
    rows = get_json(COINBASE_URL.format(product=product))
    return {datetime.datetime.fromtimestamp(int(row[0]), datetime.timezone.utc).strftime("%Y-%m-%d"): float(row[4]) for row in rows}


def crypto_closes_guarded(tickers, get_json: Callable[[str], object]) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Each coin's closes, one fetch at a time: a coin whose fetch fails gets an empty series (a NaN column) and is named, so one delisted product can't void every coin's session.
    A row is `no_data` only if a held name is among the failed ones, since `session_return` returns None for a held name with no mark."""
    closes: dict[str, dict[str, float]] = {}
    failed: list[str] = []
    for ticker in tickers:
        try:
            closes[ticker] = coinbase_closes(crypto_product(ticker), get_json)
        except Exception:
            closes[ticker] = {}
            failed.append(ticker)
    return closes, failed


def yahoo_closes(symbol: str, get_json: Callable[[str], object]) -> dict[str, float]:
    """The adjusted close, else the plain one, else on the newest bar the quote's own last price: for hours after the close Yahoo leaves that bar's closes
    empty, so reading the columns alone missed the very session the evening run exists to write."""
    result = get_json(YAHOO_URL.format(symbol=symbol))["chart"]["result"][0]
    indicators = result["indicators"]
    stamps = result["timestamp"]
    plain = ((indicators.get("quote") or [{}])[0].get("close")) or [None] * len(stamps)
    adjusted = ((indicators.get("adjclose") or [{}])[0].get("adjclose")) or [None] * len(stamps)
    day_of = lambda stamp: datetime.datetime.fromtimestamp(int(stamp), datetime.timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    closes = {}
    for stamp, adjusted_close, plain_close in zip(stamps, adjusted, plain):
        close = plain_close if adjusted_close is None else adjusted_close
        if close is not None:
            closes[day_of(stamp)] = float(close)
    meta = result.get("meta") or {}
    newest = day_of(stamps[-1]) if stamps else None
    if newest and newest not in closes and meta.get("regularMarketPrice") and meta.get("regularMarketTime") and day_of(meta["regularMarketTime"]) == newest:
        closes[newest] = float(meta["regularMarketPrice"])
    return closes


def crypto_product(ticker: str) -> str:
    return f"{ticker[:-3]}-USD"


def known_crypto(closes_by_ticker: dict[str, dict[str, float]], sessions: list[str]) -> pd.DataFrame:
    """Each session's marks: a coin's bar dated before the session, the same timing as `portfolio.premia_signals.known_closes`."""
    days = sorted({day for series in closes_by_ticker.values() for day in series})
    table = pd.DataFrame(closes_by_ticker).reindex(days).astype(float)
    return table.ffill().shift(1).reindex(pd.Index(table.index.union(sessions))).ffill().reindex(sessions)


def row_for(definition: dict, ledger_rows: list[dict], session: str, sessions: list[str], marks: pd.DataFrame, benchmarks: dict[str, float]) -> dict:
    """The payload of one session. Weights carry over between decision days; the return is what yesterday's weights earned."""
    name = str(definition["id"])
    previous_row = last_row_for(ledger_rows, name)
    held = dict((previous_row["payload"].get("weights") if previous_row else definition.get("initial_weights")) or {})
    rebalance = is_rebalance(sessions, session, anchor=str(definition["anchor_date"]), every=int(definition["rebalance_every"]))
    weights = decide(definition, marks.loc[:session], session) if rebalance else held
    earlier = [day for day in sessions if day < session]
    traded = turnover(held, weights) if rebalance else 0.0
    cost = COST_BPS_BY_CLASS.get(str(definition.get("cost_class", "crypto")), 0.0)
    earned = session_return(held, marks, earlier[-1], session, cost_bps=cost, traded=traded) if earlier else 0.0
    status = "ok" if earned is not None else "no_data"
    return {
        "status": status, "reason": None if status == "ok" else "a held name has no mark", "definition_sha256": definition_sha256(definition),
        "rebalance": rebalance, "weights": weights, "turnover": traded, "session_return": earned, "benchmarks": benchmarks,
        "data_sources": sorted(definition.get("data_sources") or []),
    }


def run(candidates_path: Path, ledger_path: Path, *, get_json: Callable[[str], object], now: datetime.datetime, session_override: str | None = None) -> list[dict]:
    """One row per candidate for the session, or none if already written: a rerun of the day appends nothing."""
    candidates = json.loads(Path(candidates_path).read_text(encoding="utf-8"))["candidates"]
    created_at = now.replace(microsecond=0).isoformat()
    written = []
    failure = None
    series: dict[str, dict[str, float]] = {}
    try:
        series = {symbol: yahoo_closes(symbol, get_json) for symbol in BENCHMARK_SYMBOLS}
    except Exception as error:  # a blocked fetch is a row, not a crash
        failure = f"Yahoo chart: {type(error).__name__}"
    sessions = sorted(series.get("SPY", {}))
    today = (session_override or session_for_outage(now)) if failure is not None else resolve_session(sessions, now.date().isoformat(), session_override)
    if today is None:
        raise NoSessionToRecord(f"{session_override or now.date().isoformat()} is not a session this run may write")
    benchmarks: dict[str, float] = {}
    if failure is None and len(sessions) >= 2:
        position = sessions.index(today)
        if position > 0:
            prior = sessions[position - 1]
            for symbol in BENCHMARK_SYMBOLS:
                before, after = series[symbol].get(prior), series[symbol].get(today)
                if before and after:
                    benchmarks[symbol] = after / before - 1.0

    for definition in candidates:
        name = str(definition["id"])
        rows = read_ledger(ledger_path)
        if has_session(rows, name, today):
            continue
        reason = failure
        if reason is None and definition.get("needs"):
            reason = f"needs {definition['needs']}, absent on this runner: run this row from the PC (RUNBOOK)"
        if reason is None:
            try:
                closes, failed = crypto_closes_guarded(definition["tickers"], get_json)
                decision_day = is_rebalance(sessions, today, anchor=str(definition["anchor_date"]), every=int(definition["rebalance_every"]))
                if failed and (len(failed) == len(definition["tickers"]) or decision_day):
                    # a decision must not silently leave a coin out: hold the weights, as a blocked source always has
                    raise RuntimeError(f"Coinbase fetch failed for {', '.join(sorted(failed))}")
                marks = known_crypto(closes, sessions)
                btc = marks["BTCUSD"] if "BTCUSD" in marks.columns else None
                if btc is not None and today in btc.index and sessions.index(today) > 0:
                    previous = btc.at[sessions[sessions.index(today) - 1]]
                    if np.isfinite(previous) and previous > 0.0 and np.isfinite(btc.at[today]):
                        benchmarks = {**benchmarks, "BTCUSD": float(btc.at[today]) / float(previous) - 1.0}
                payload = row_for(definition, rows, today, sessions, marks, benchmarks)
                if failed and payload["status"] != "ok":
                    payload["reason"] = f"{payload['reason']} (Coinbase fetch failed for {', '.join(sorted(failed))})"
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"[:200]
        if reason is not None:
            previous = last_row_for(rows, name)
            payload = {
                "status": "no_data", "reason": reason, "definition_sha256": definition_sha256(definition), "rebalance": False,
                "weights": (previous["payload"].get("weights") if previous else definition.get("initial_weights")) or {}, "turnover": 0.0, "session_return": None,
                "benchmarks": benchmarks, "data_sources": sorted(definition.get("data_sources") or []),
            }
        written.append(append_row(ledger_path, session=today, candidate=name, payload=payload, created_at=created_at))
    return written


def _get_json(url: str) -> object:
    import requests

    response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=30)
    response.raise_for_status()
    return response.json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", default=str(ROOT / "ml" / "forward" / "candidates.json"))
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--session", default=None, help="the session to write (default: today, UTC)")
    args = parser.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        written = run(Path(args.candidates), Path(args.ledger), get_json=_get_json, now=now, session_override=args.session)
    except NoSessionToRecord as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for row in written:
        payload = row["payload"]
        print(f"{payload['session']} {payload['candidate']}: {payload['status']} return {payload['session_return']} rebalance {payload['rebalance']} {payload.get('reason') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
