"""Today's row for every generation in `ml/generations/registry.json`, and the capital they share (V6.6.1).

Runs on a bare GitHub runner (numpy, pandas, requests; no torch, no secrets) from `.github/workflows/research-cycle.yml`. Marks come from Coinbase's public candles and Yahoo's chart API. A failed
fetch writes a `no_data` row with the reason, never a skipped day; a rerun of a day appends nothing. A generation with `needs` is marked here and decided on a host, by `scripts/cycle_decide.py`.

    python scripts/cycle_daily.py --ledger forward/generations.jsonl [--session 2026-11-06] [--decisions forward/decisions.jsonl] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from forward_ledger import BENCHMARK_SYMBOLS, _get_json, crypto_closes_guarded, known_crypto, yahoo_closes  # noqa: E402

from evaluation.forward_ledger import NoSessionToRecord, definition_sha256, read_ledger, resolve_session, session_for_outage  # noqa: E402
from evaluation.generation_ledger import (  # noqa: E402
    ALLOCATION_EVENT,
    ALLOCATION_ID,
    SESSION_EVENT,
    allocation_row,
    append_event,
    caps_for,
    evidence_for,
    generation_state,
    judge_generations,
    no_data_row,
    record_of,
    row_for_generation,
    rows_for,
)
from evaluation.generation_registry import Generation, load_registry  # noqa: E402
from portfolio.generation_blend import resolve_glide_policy  # noqa: E402

TRACKED_STAGES = ("shadow", "ramping", "active", "fading", "winding_down")
MAX_DECISION_AGE_EXTRA_SESSIONS = 5
MAX_YAHOO_NAMES = 700


def marks_for(generation: Generation, sessions: list[str], get_json: Callable[[str], object], *, pause: Callable[[], None] = lambda: None) -> pd.DataFrame:
    """Session x ticker marks, per class: crypto from Coinbase, a bar being known only once it has closed; equities from Yahoo. A name with no price yet is a NaN column: coverage decides."""
    classes = generation.definition.get("asset_class") or {}
    crypto_names = [ticker for ticker in generation.definition.get("tickers") or [] if classes.get(ticker) == "crypto"]
    crypto, failed = crypto_closes_guarded(crypto_names, get_json)
    if crypto_names and len(failed) == len(crypto_names):
        raise RuntimeError(f"Coinbase fetch failed for every coin: {', '.join(sorted(failed))}")  # a part failure leaves NaN columns, which the 98% coverage rule turns into no_data
    others = {}
    for ticker in generation.definition.get("tickers") or []:
        if classes.get(ticker) != "crypto":
            if len(others) >= MAX_YAHOO_NAMES:
                raise ValueError("too many names to mark from one runner")
            others[ticker] = yahoo_closes(ticker, get_json)
            pause()
    frames = []
    if crypto:
        frames.append(known_crypto(crypto, sessions))
    if others:
        frames.append(pd.DataFrame(others).astype(float).reindex(sessions))
    return pd.concat(frames, axis=1) if frames else pd.DataFrame(index=sessions)


def latest_decision(rows: list[dict], generation: str, sessions: list[str], session: str, every: int) -> tuple[dict | None, str | None]:
    """A host's newest decision dated before this session. (decision, why not). A stale one stops being used, and the record says so."""
    mine = [row["payload"] for row in rows if row["payload"].get("candidate") == generation and row["payload"].get("session", "9") <= session]
    if not mine:
        return None, "no decision from a host yet"
    last = mine[-1]
    age = len([day for day in sessions if last["session"] < day <= session])
    if age > every + MAX_DECISION_AGE_EXTRA_SESSIONS:
        return None, f"the newest decision is {age} sessions old (limit {every + MAX_DECISION_AGE_EXTRA_SESSIONS})"
    return (dict(last.get("decided") or {}) if last["session"] == session else None), None


def run(
    registry_path: Path, policy_path: Path, ledger_path: Path, *, get_json: Callable[[str], object], now: datetime.datetime, session_override: str | None = None, decisions_path: Path | None = None,
    holdouts_spent: bool = False, pause: Callable[[], None] = lambda: None,
) -> list[dict]:
    """One row per tracked generation and one allocation row, or none if already written."""
    generations = {name: generation for name, generation in load_registry(registry_path).items() if generation.stage in TRACKED_STAGES}
    policy_raw = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    policy = resolve_glide_policy(policy_raw.get("glide"))
    created_at = now.replace(microsecond=0).isoformat()
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
    if failure is None and sessions.index(today) > 0:
        prior = sessions[sessions.index(today) - 1]
        for symbol in BENCHMARK_SYMBOLS:
            before, after = series[symbol].get(prior), series[symbol].get(today)
            if before and after:
                benchmarks[symbol] = after / before - 1.0
    written: list[dict] = []
    rows = read_ledger(ledger_path)
    decisions = read_ledger(decisions_path) if decisions_path and Path(decisions_path).exists() else []
    if any(row["payload"].get("session") == today and row["payload"].get("candidate") == ALLOCATION_ID for row in rows):
        return written
    decided_today = False
    for name, generation in sorted(generations.items()):
        if any(row["payload"].get("session") == today and row["payload"].get("candidate") == name for row in rows):
            continue
        sha = definition_sha256(generation.definition)
        reason, decision = failure, None
        if reason is None and generation.needs:
            decision, reason = latest_decision(decisions, name, sessions, today, int(generation.definition.get("rebalance_every", 20)))
        if reason is None:
            try:
                marks = marks_for(generation, sessions, get_json, pause=pause)
                btc = marks["BTCUSD"] if "BTCUSD" in marks.columns else None
                if btc is not None and sessions.index(today) > 0:
                    before = btc.at[sessions[sessions.index(today) - 1]]
                    if np.isfinite(before) and before > 0.0 and np.isfinite(btc.at[today]):
                        benchmarks = {**benchmarks, "BTCUSD": float(btc.at[today]) / float(before) - 1.0}
                payload = row_for_generation(generation, rows, today, sessions, marks, benchmarks, decision=decision, definition_sha=sha)
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"
        if reason is not None:
            payload = no_data_row(generation, rows, reason=reason, benchmarks=benchmarks, definition_sha=sha)
        state = generation_state(generation, [*rows_for(rows, name), payload], guard_max_drawdown=float(policy_raw.get("guard_max_drawdown", 0.15)))
        payload = {**payload, "state": state["state"], "decay": {key: state[key] for key in ("statistic", "ew_sharpe", "sessions", "max_drawdown", "reason")}}
        decided_today = decided_today or bool(payload["rebalance"])
        row = append_event(ledger_path, event=SESSION_EVENT, session=today, candidate=name, payload=payload, created_at=created_at)
        written.append(row)
        rows.append(row)
    written.append(_allocate(generations, rows, ledger_path, policy, policy_raw, today, created_at, decided_today=decided_today, holdouts_spent=holdouts_spent))
    return written


def _allocate(generations, rows, ledger_path, policy, policy_raw, today, created_at, *, decided_today: bool, holdouts_spent: bool) -> dict:
    judged = judge_generations(rows)
    previous = [row["payload"] for row in rows if row["payload"].get("candidate") == ALLOCATION_ID]
    if previous:
        before = dict(previous[-1]["shares"])
        since = int(previous[-1].get("sessions_since_blend") or 0) + 1
    else:
        before = {name: 1.0 for name, generation in generations.items() if generation.stage == "active"}
        total = sum(before.values())
        before = {name: value / total for name, value in before.items()} if total > 0.0 else {}
        since = 0
    returns = {
        name: {row["session"]: float(row["session_return"]) for row in rows_for(rows, name) if row.get("status") == "ok" and row.get("session_return") is not None}
        for name in generations
    }
    incumbent = max(before, key=lambda name: before[name]) if before else None
    states, evidence = {}, {}
    for name, generation in generations.items():
        mine = rows_for(rows, name)
        states[name] = {"state": mine[-1].get("state", "healthy") if mine else "healthy"}
        evidence[name] = evidence_for(
            generation, (judged.get("generations") or {}).get(name, {}), incumbent_returns=returns.get(incumbent) if incumbent != name else None, own_returns=returns[name],
            holdouts_spent=holdouts_spent, state=states[name],
        )
    caps = caps_for(generations, evidence, policy)
    latest = {name: (rows_for(rows, name)[-1].get("decided") or {}) if rows_for(rows, name) else {} for name in generations}
    records = {name: record_of([returns[name][day] for day in sorted(returns[name])], prior=float(generation.expected_sharpe)) for name, generation in generations.items()}
    payload = allocation_row(
        generations, {name: before.get(name, 0.0) for name in generations}, states, caps, latest, policy, decided_today=decided_today, sessions_since_blend=since, records=records,
    )
    payload["chain_valid"] = judged["chain_valid"]
    return append_event(ledger_path, event=ALLOCATION_EVENT, session=today, candidate=ALLOCATION_ID, payload=payload, created_at=created_at)


def summary_lines(written: list[dict], ledger_path: Path) -> list[str]:
    """What a person needs from today's run, for the job summary."""
    report = judge_generations(read_ledger(ledger_path))
    lines = [f"Chain valid: {report['chain_valid']}, {report['rows']} rows", "", "| Generation | Status | Return | State | Sessions | Sharpe |", "|---|---|---|---|---|---|"]
    for row in written:
        payload = row["payload"]
        if payload["candidate"] == ALLOCATION_ID:
            continue
        judged = (report.get("generations") or {}).get(payload["candidate"]) or {}
        lines.append(f"| {payload['candidate']} | {payload['status']} | {payload.get('session_return')} | {payload.get('state')} | {judged.get('sessions')} | {judged.get('sharpe')} |")
    allocation = report.get("latest_allocation")
    if allocation:
        lines += ["", f"Shares: {allocation['shares']}; T-bills {allocation['tbills']:.3f}; blended row due: {allocation['blend_due']}"]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", default=str(ROOT / "ml" / "generations" / "registry.json"))
    parser.add_argument("--policy", default=str(ROOT / "ml" / "generations" / "policy.json"))
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--decisions", default=None)
    parser.add_argument("--session", default=None, help="the session to write (default: today, UTC)")
    parser.add_argument("--dry-run", action="store_true", help="compute on a temporary copy of the ledger, leaving it as it is")
    args = parser.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc)
    ledger = Path(args.ledger)
    if args.dry_run:
        import shutil
        import tempfile

        scratch = Path(tempfile.mkdtemp()) / "generations.jsonl"
        if ledger.exists():
            shutil.copyfile(ledger, scratch)
        ledger = scratch
    spent = (ROOT / "ml" / "generations" / "holdout_ledger.jsonl").exists()
    try:
        written = run(Path(args.registry), Path(args.policy), ledger, get_json=_get_json, now=now, session_override=args.session, decisions_path=Path(args.decisions) if args.decisions else None, holdouts_spent=spent)
    except NoSessionToRecord as error:
        print(f"error: {error}", file=sys.stderr)
        return 0 if args.dry_run else 1
    lines = summary_lines(written, ledger) if ledger.exists() else ["nothing written"]
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    report = judge_generations(read_ledger(ledger)) if ledger.exists() else {"chain_valid": True}
    return 0 if report["chain_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
