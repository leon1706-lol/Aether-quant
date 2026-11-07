"""A forward record that can't be backfilled (V6.6.0): each session's decision by a frozen rule, hash-chained, dated by GitHub.

A backtest can always be rerun until it looks good. A row committed by a scheduled Action on the day it was computed can't: the commit
time and the chain together show the decision came before the return it earned. `scripts/forward_ledger.py` appends a row a session;
`aq evaluate --forward-ledger` verifies the chain and judges it.

A candidate that needs a model or fresh fundamentals can't compute on a bare runner, and missing data can't be guessed: both log a
`no_data` row with the reason, never a silent gap.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from audit.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain
from evaluation.power_analysis import excluded_alpha_sharpe, minimum_detectable_alpha_sharpe
from portfolio.premia_signals import ResearchPanel, SleeveSpec, WeightSettings, signal_to_weights, sleeve_signal

EVENT_TYPE = "forward_session"
JUDGE_AT_SESSIONS = (60, 252)
STALE_WARNING_SESSIONS = 3
COST_BPS_BY_CLASS = {"crypto": 90.0, "equity": 4.5}
TRADING_DAYS = 252.0


def definition_sha256(definition: Mapping) -> str:
    return hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class NoSessionToRecord(RuntimeError):
    """The run found no session it may write (an override that is not a session, or an empty calendar). A scheduled run must fail loudly on this: a silent exit is how a record loses a session."""


def resolve_session(sessions: Sequence[str], now_date: str, override: str | None = None) -> str | None:
    """The session a run records. An override must be a real session. Otherwise the newest session on or before today, so a schedule delayed past midnight UTC, or a
    weekend dispatch, still records the session it was for. Never a future date, and never an older gap: only the newest session can be written."""
    if override:
        return override if override in sessions else None
    earlier = [day for day in sessions if day <= now_date]
    return max(earlier) if earlier else None


def session_for_outage(now: datetime.datetime) -> str:
    """With no calendar (the fetch failed), the last weekday whose US close has passed. Dating an outage row by the calendar day would let a run at 02:00 UTC use up that day's own session."""
    day = (now - datetime.timedelta(hours=21)).date()
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day.isoformat()


def is_rebalance(sessions: Sequence[str], date: str, *, anchor: str, every: int) -> bool:
    """Whether `date` is a decision day, counting sessions from the frozen file's last decision so the phase carries on unchanged."""
    if date <= anchor:
        return False
    after = [day for day in sessions if anchor < day <= date]
    return bool(after) and after[-1] == date and len(after) % int(every) == 0


def decide(definition: Mapping, known: pd.DataFrame, date: str) -> dict[str, float]:
    """The frozen rule's weights at `date`, through the research pipeline. `known` holds only what was public by that session's close."""
    spec = SleeveSpec(
        str(definition["id"]), "forward", str(definition["kind"]), str(definition["family"]), tuple(definition["universe"]),
        int(definition["rebalance_every"]), dict(definition.get("params") or {}),
    )
    panel = ResearchPanel(known, dict(definition["asset_class"]), {}, {})
    settings = WeightSettings(**(definition.get("settings") or {}))
    rows = signal_to_weights(sleeve_signal(spec, panel), panel, kind=spec.kind, rebalance_every=1, settings=settings, start=date, end=date)
    return {ticker: float(weight) for ticker, weight in rows.get(date, {}).items()}


def session_return(held: Mapping[str, float], marks: pd.DataFrame, previous: str, date: str, *, cost_bps: float, traded: float = 0.0) -> float | None:
    """What the weights held earned between two sessions' marks, less the cost of today's trade. None if a held name has no mark."""
    total = 0.0
    for ticker, weight in held.items():
        if ticker not in marks.columns:
            return None
        before, after = marks.at[previous, ticker], marks.at[date, ticker]
        if not (np.isfinite(before) and np.isfinite(after) and before > 0.0):
            return None
        total += float(weight) * (float(after) / float(before) - 1.0)
    return total - float(traded) * float(cost_bps) / 1e4


def turnover(before: Mapping[str, float], after: Mapping[str, float]) -> float:
    return sum(abs(float(after.get(ticker, 0.0)) - float(before.get(ticker, 0.0))) for ticker in set(before) | set(after))


def read_ledger(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_row(path: Path, *, session: str, candidate: str, payload: Mapping, created_at: str) -> dict:
    """Links a row to the chain and appends it. The row's own session is in the payload, so a rewrite of a date breaks the hash."""
    rows = read_ledger(path)
    previous = rows[-1]["hash"] if rows else GENESIS_HASH
    body = {"session": session, "candidate": candidate, **payload}
    row = {"prev_hash": previous, "event_type": EVENT_TYPE, "created_at": created_at, "payload": body}
    row["hash"] = compute_entry_hash(previous, EVENT_TYPE, created_at, body)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def last_row_for(rows: Sequence[dict], candidate: str) -> dict | None:
    return next((row for row in reversed(rows) if row["payload"].get("candidate") == candidate), None)


def has_session(rows: Sequence[dict], candidate: str, session: str) -> bool:
    return any(row["payload"].get("candidate") == candidate and row["payload"].get("session") == session for row in rows)


def _sharpe(values: np.ndarray) -> float | None:
    if len(values) < 2 or values.std(ddof=1) <= 0.0:
        return None
    return float(values.mean() / values.std(ddof=1) * math.sqrt(TRADING_DAYS))


def judge_candidate(rows: Sequence[dict], candidate: str) -> dict:
    """Sessions recorded, Sharpe, alpha t against the benchmarks each row carries, and what this many sessions can and can't show."""
    from evaluation.alpha_proof import alpha_regression

    mine = [row["payload"] for row in rows if row["payload"].get("candidate") == candidate]
    usable = [row for row in mine if row.get("status") == "ok" and row.get("session_return") is not None]
    returns = pd.Series({row["session"]: float(row["session_return"]) for row in usable}, dtype=float).sort_index()
    report: dict = {
        "candidate": candidate, "rows": len(mine), "sessions": int(len(returns)), "no_data_sessions": sum(1 for row in mine if row.get("status") != "ok"),
        "first": str(returns.index.min()) if len(returns) else None, "last": str(returns.index.max()) if len(returns) else None,
        "sharpe": _sharpe(returns.to_numpy()), "judgeable_at": list(JUDGE_AT_SESSIONS), "judgeable": len(returns) >= JUDGE_AT_SESSIONS[0],
        "fully_judgeable": len(returns) >= JUDGE_AT_SESSIONS[1],
    }
    years = len(returns) / TRADING_DAYS
    report["minimum_detectable_alpha_sharpe_at_t2"] = minimum_detectable_alpha_sharpe(years, 2.0) if years > 0 else None
    if len(returns) >= 20:
        benchmarks = pd.DataFrame({row["session"]: row.get("benchmarks") or {} for row in usable}).T.sort_index().astype(float)
        if not benchmarks.empty:
            alpha = alpha_regression(returns, benchmarks, annualization=TRADING_DAYS)
            report["alpha"] = alpha
            if alpha.get("t_hac") is not None:
                report["excluded_alpha_sharpe"] = excluded_alpha_sharpe(float(alpha["t_hac"]), years)
    return report


def judge_ledger(rows: Sequence[dict], *, today_sessions: Sequence[str] = ()) -> dict:
    """Chain check first: a broken chain makes every figure meaningless. `today_sessions` warns of a schedule that stopped."""
    valid, broken_at = verify_chain(list(rows))
    report: dict = {"chain_valid": valid, "first_broken_row": broken_at, "rows": len(rows)}
    if not valid:
        return report
    report["candidates"] = {name: judge_candidate(rows, name) for name in sorted({row["payload"].get("candidate") for row in rows})}
    if not rows:
        report["warning"] = "record not started: no row has been written yet (RUNBOOK: dispatch the workflow once)"
    if rows and today_sessions:
        last = max(row["payload"]["session"] for row in rows)
        behind = sum(1 for day in today_sessions if day > last)
        report["sessions_behind"] = behind
        if behind > STALE_WARNING_SESSIONS:
            report["warning"] = f"the last row is {behind} sessions old: GitHub disables a schedule after 60 days of no repo activity (RUNBOOK)"
    return report
