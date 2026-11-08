"""The forward record of every generation, and the capital they share (V6.6.1). A new file on the `forward-ledger` branch, hash-chained, one Action run a session.

`evaluation/forward_ledger.py`'s chain stays as it is, since a changed rule would start a new record. It also credits a crypto decision one bar the real book never earns: a decision at D's
close uses the mark from D's midnight, and its order fills at D's bar close, so the weights only earn from the next session on. This file lags each class to its real fill, so
compare generations here, and never a figure from here with one from there.

A generation's return is its own, as if it held the whole book, at the cost of its own trades: conservative, since a blend nets positions. The blended book's true return comes from the engine or
Lean, never from a sum of these.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from audit.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain
from evaluation.alpha_decay import DecayConfig, decay_state
from evaluation.forward_ledger import COST_BPS_BY_CLASS, is_rebalance, judge_candidate, read_ledger, turnover
from evaluation.generation_registry import AdmissionEvidence, Generation, share_cap
from portfolio.generation_blend import (
    EW_HALF_LIFE_SESSIONS,
    GlidePolicy,
    blend_due,
    blend_generation_rows,
    dynamic_generation_shares,
    ew_sharpe,
    ew_update,
    shrunk_sharpe,
    update_generation_shares,
)
from portfolio.premia_signals import ResearchPanel, SleeveSpec, WeightSettings, signal_to_weights, sleeve_signal

SESSION_EVENT = "generation_session"
ALLOCATION_EVENT = "generation_allocation"
ALLOCATION_ID = "__allocation__"
FILL_LAG_SESSIONS = {"crypto": 2, "forex": 2, "equity": 1, "bond": 1}
DEFAULT_LAG = 1
DEFAULT_COST_BPS = 4.5
MIN_COVERAGE = 0.98
GUARD_MAX_DRAWDOWN = 0.15


def decide_generation(definition: Mapping, panel: ResearchPanel, date: str) -> dict[str, float]:
    """The frozen rule's weights at `date`. Unlike `forward_ledger.decide`, it passes a score table and `top_k` through, so a cross-sectional rule can't silently become a different one."""
    spec = SleeveSpec(
        str(definition["id"]), "forward", str(definition["kind"]), str(definition["family"]), tuple(definition["universe"]),
        int(definition["rebalance_every"]), dict(definition.get("params") or {}),
    )
    settings = WeightSettings(**(definition.get("settings") or {}))
    if spec.family == "crypto_signal":
        # round 4C's trial, computed from the marks (portfolio/crypto_signals.py forward_table); every other family is untouched
        from portfolio.crypto_signals import forward_table

        table = forward_table(spec.params["signal"], panel.known)
        panel = ResearchPanel(panel.known, panel.asset_class, panel.fred, {**panel.extras, "observer": table})
        spec = SleeveSpec(spec.id, spec.track, spec.kind, "external_score", spec.universe, spec.rebalance_every, {"table": "observer", "top_k": spec.params.get("top_k")})
    rows = signal_to_weights(sleeve_signal(spec, panel), panel, kind=spec.kind, rebalance_every=1, settings=settings, start=date, end=date, top_k=spec.params.get("top_k"))
    return {ticker: float(weight) for ticker, weight in rows.get(date, {}).items()}


def session_return_covered(
    held: Mapping[str, float], marks: pd.DataFrame, previous: str, date: str, *, classes: Mapping[str, str], traded: Mapping[str, float],
    cost_by_class: Mapping[str, float] = COST_BPS_BY_CLASS, min_coverage: float = MIN_COVERAGE,
) -> dict:
    """What the held weights earned between two marks, less the cost of what traded. One delisted holding doesn't blank every row until the next decision: the rest counts while
    at least `min_coverage` of the gross has a mark. Below that the session is `no_data`, never a guess."""
    gross = covered = earned = 0.0
    for ticker, weight in held.items():
        size = abs(float(weight))
        gross += size
        if ticker not in marks.columns:
            continue
        before, after = marks.at[previous, ticker], marks.at[date, ticker]
        if np.isfinite(before) and np.isfinite(after) and before > 0.0:
            covered += size
            earned += float(weight) * (float(after) / float(before) - 1.0)
    coverage = covered / gross if gross > 0.0 else 1.0
    if coverage < min_coverage:
        return {"session_return": None, "coverage": coverage, "reason": f"marks cover {coverage:.3f} of the gross, under {min_coverage}"}
    cost = sum(abs(float(amount)) * float(cost_by_class.get(classes.get(ticker), DEFAULT_COST_BPS)) / 1e4 for ticker, amount in traded.items())
    return {"session_return": earned - cost, "coverage": coverage, "reason": None}


def rows_for(rows: Sequence[Mapping], generation: str) -> list[dict]:
    return [row["payload"] for row in rows if row["payload"].get("candidate") == generation]


def _lagged(mine: Sequence[Mapping], lag: int, initial: Mapping[str, float]) -> Mapping[str, float]:
    """What was decided `lag` sessions ago. Before the record starts, the rule's frozen starting weights."""
    if lag <= 0:
        raise ValueError("a decision can't earn the bar it was made on")
    return (mine[-lag].get("decided") or {}) if len(mine) >= lag else initial


def held_by_lag(mine: Sequence[Mapping], classes: Mapping[str, str], initial: Mapping[str, float], *, lags: Mapping[str, int] = FILL_LAG_SESSIONS) -> dict[str, float]:
    """The weights in place at this session's start, class by class: each class holds what it decided as long ago as its order takes to fill."""
    out: dict[str, float] = {}
    needed = {int(lags.get(name, DEFAULT_LAG)) for name in set(classes.values())} | {DEFAULT_LAG}
    for lag in needed:
        row = _lagged(mine, lag, initial)
        for ticker, weight in row.items():
            if int(lags.get(classes.get(ticker), DEFAULT_LAG)) == lag:
                out[ticker] = float(weight)
    return out


def row_for_generation(
    generation: Generation, rows: Sequence[Mapping], session: str, sessions: Sequence[str], marks: pd.DataFrame, benchmarks: Mapping[str, float], *,
    decision: Mapping[str, float] | None = None, definition_sha: str = "",
) -> dict:
    """One session's payload. A rule with no `needs` decides here, on the runner; one with `needs` reads the `decision` a host dated earlier."""
    definition = generation.definition
    mine = rows_for(rows, generation.id)
    classes = dict(definition.get("asset_class") or {})
    initial = dict(definition.get("initial_weights") or {})
    held = held_by_lag(mine, classes, initial)
    before = held_by_lag(mine[:-1], classes, initial) if mine else dict(initial)
    last_decided = dict((mine[-1].get("decided") if mine else initial) or {})
    if generation.needs:
        decided, rebalance = (dict(decision), True) if decision is not None else (last_decided, False)
    else:
        rebalance = is_rebalance(sessions, session, anchor=str(definition["anchor_date"]), every=int(definition["rebalance_every"]))
        decided = decide_generation(definition, ResearchPanel(marks.loc[:session], classes, {}, {}), session) if rebalance else last_decided
    earlier = [day for day in sessions if day < session]
    traded = {ticker: float(held.get(ticker, 0.0)) - float(before.get(ticker, 0.0)) for ticker in set(held) | set(before)}
    if earlier:
        result = session_return_covered(held, marks, earlier[-1], session, classes=classes, traded=traded)
    else:
        result = {"session_return": 0.0, "coverage": 1.0, "reason": None}
    return {
        "status": "ok" if result["session_return"] is not None else "no_data", "reason": result["reason"], "definition_sha256": definition_sha, "rebalance": rebalance, "decided": decided,
        "held": held, "turnover": turnover(before, held), "coverage": result["coverage"], "session_return": result["session_return"], "benchmarks": dict(benchmarks),
        "data_sources": sorted(definition.get("data_sources") or []),
    }


def no_data_row(generation: Generation, rows: Sequence[Mapping], *, reason: str, benchmarks: Mapping[str, float], definition_sha: str = "") -> dict:
    """A failed fetch is a row with its reason, never a gap. The held weights don't change."""
    mine = rows_for(rows, generation.id)
    decided = (mine[-1].get("decided") if mine else generation.definition.get("initial_weights")) or {}
    return {
        "status": "no_data", "reason": str(reason)[:200], "definition_sha256": definition_sha, "rebalance": False, "decided": dict(decided), "held": dict(mine[-1].get("held") or {}) if mine else {},
        "turnover": 0.0, "coverage": None, "session_return": None, "benchmarks": dict(benchmarks), "data_sources": sorted(generation.definition.get("data_sources") or []),
    }


def append_event(path: Path, *, event: str, session: str, candidate: str, payload: Mapping, created_at: str) -> dict:
    """Links a row to the chain. The session is in the hashed payload, so rewriting a date breaks it."""
    rows = read_ledger(path)
    previous = rows[-1]["hash"] if rows else GENESIS_HASH
    body = {"session": session, "candidate": candidate, **payload}
    row = {"prev_hash": previous, "event_type": event, "created_at": created_at, "payload": body}
    row["hash"] = compute_entry_hash(previous, event, created_at, body)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def _max_drawdown(values: Sequence[float]) -> float:
    if not len(values):
        return 0.0
    curve = np.cumprod(1.0 + np.asarray(values, dtype=float))
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))[1:]
    return float(1.0 - (curve / peak).min())


def generation_state(generation: Generation, mine: Sequence[Mapping], *, config: DecayConfig | None = None, guard_max_drawdown: float = GUARD_MAX_DRAWDOWN) -> dict:
    """The decay report, with the guard first: a drawdown past the owner's ceiling is `tripped`, whatever the statistic says, and it latches."""
    returns = [float(row["session_return"]) for row in mine if row.get("status") == "ok" and row.get("session_return") is not None]
    previous = next((row["state"] for row in reversed(mine) if row.get("state")), "healthy")
    report = decay_state(returns, expected_sharpe=float(generation.expected_sharpe), previous="healthy" if previous == "tripped" else previous, config=config)
    drawdown = _max_drawdown(returns)
    tripped = previous == "tripped" or drawdown >= guard_max_drawdown
    return {"state": "tripped" if tripped else report.state, "statistic": report.statistic, "ew_sharpe": report.ew_sharpe, "sessions": report.sessions, "max_drawdown": drawdown, "reason": report.reason}


def judge_generations(rows: Sequence[Mapping]) -> dict:
    """Chain first: a broken chain makes every figure meaningless."""
    valid, broken_at = verify_chain(list(rows))
    report: dict = {"chain_valid": valid, "first_broken_row": broken_at, "rows": len(rows)}
    if not valid:
        return report
    names = sorted({row["payload"].get("candidate") for row in rows if row["payload"].get("candidate") != ALLOCATION_ID})
    report["generations"] = {name: judge_candidate(rows, name) for name in names}
    allocations = [row["payload"] for row in rows if row["payload"].get("candidate") == ALLOCATION_ID]
    report["latest_allocation"] = allocations[-1] if allocations else None
    return report


def evidence_for(generation: Generation, judged: Mapping, *, incumbent_returns: Mapping[str, float] | None, own_returns: Mapping[str, float], holdouts_spent: bool, state: Mapping) -> AdmissionEvidence:
    """The admission rule's inputs from the record, with the flags a round's verdict set. The mean difference is on sessions both have."""
    admission = generation.admission or {}
    difference = None
    if incumbent_returns:
        shared = sorted(set(own_returns) & set(incumbent_returns))
        if shared:
            difference = float(np.mean([own_returns[day] - incumbent_returns[day] for day in shared]))
    rows = int(judged.get("rows") or 0)
    alpha = judged.get("alpha") or {}
    t = alpha.get("t_hac")
    record = record_of(own_returns.values() if isinstance(own_returns, Mapping) else own_returns, prior=float(generation.expected_sharpe))
    return AdmissionEvidence(
        selection_pass=bool(admission.get("selection_pass")), hold_pass=bool(admission.get("hold_pass")), edge_pass=bool(admission.get("edge_pass")), holdouts_spent=holdouts_spent,
        forward_ok_sessions=int(judged.get("sessions") or 0), no_data_share=(float(judged.get("no_data_sessions") or 0) / rows) if rows else 0.0, mean_diff_vs_incumbent=difference,
        guard_tripped=state.get("state") == "tripped", decay_state=str(state.get("state") or "healthy"), forward_alpha_t=None if t is None or not math.isfinite(float(t)) else float(t),
        score=shrunk_sharpe(record["ew_sharpe"], record["sessions"], record["prior"], GlidePolicy().prior_sessions) if record["sessions"] else None,
    )


def record_of(returns, *, prior: float) -> dict:
    """What the allocator reads about one generation: its exponentially weighted Sharpe, its sessions of record, and what it claimed at admission."""
    state = (0.0, 0.0, 0.0, 0)
    for value in returns:
        state = ew_update(state, value, EW_HALF_LIFE_SESSIONS)
    return {"ew_sharpe": ew_sharpe(state), "sessions": state[3], "prior": float(prior)}


def allocation_row(
    generations: Mapping[str, Generation], shares_before: Mapping[str, float], states: Mapping[str, Mapping], caps: Mapping[str, float], rows_by_generation: Mapping[str, Mapping[str, float]],
    policy: GlidePolicy, *, decided_today: bool, sessions_since_blend: int, records: Mapping[str, Mapping] | None = None,
) -> dict:
    """Today's shares, by the policy's mode, and a blended row when one is due. A row retargets every name, so it isn't written daily."""
    stages = {name: generation.stage for name, generation in generations.items()}
    labels = {name: str(state.get("state") or "healthy") for name, state in states.items()}
    if policy.mode == "dynamic":
        shares = dynamic_generation_shares(shares_before, stages, labels, records or {}, caps, policy)
    else:
        shares = update_generation_shares(shares_before, stages, labels, caps, policy)
    moved_off = any(float(shares_before.get(name, 0.0)) > 0.0 and shares.get(name, 0.0) == 0.0 for name in generations)
    due = blend_due(decided_today=decided_today, sessions_since_blend=int(sessions_since_blend), guard_tripped=moved_off, policy=policy)
    return {
        "status": "allocation", "shares_before": {name: float(value) for name, value in shares_before.items()}, "shares": shares, "tbills": max(0.0, 1.0 - sum(shares.values())), "stages": stages,
        "states": labels, "caps": {name: float(value) for name, value in caps.items()}, "blend_due": due, "sessions_since_blend": 0 if due else int(sessions_since_blend),
        "blended": blend_generation_rows(rows_by_generation, shares) if due else None,
    }


def replay_handover(
    rows_by_generation: Mapping[str, Mapping[str, Mapping[str, float]]], sessions: Sequence[str], *, incumbent: str, successor: str, start: str, policy: GlidePolicy,
) -> dict:
    """The blended weight file a handover would have written: `incumbent` holds the book until `start`, then the ladder moves it to `successor`. Uses the running functions, so a
    backtest of this file tests what would trade. {"rows": {date: weights}, "shares": {date: shares}}."""
    shares = {incumbent: 1.0, successor: 0.0}
    latest: dict[str, Mapping[str, float]] = {incumbent: {}, successor: {}}
    rows: dict[str, dict[str, float]] = {}
    path: dict[str, dict[str, float]] = {}
    since = 0
    for session in sessions:
        decided = False
        for name in (incumbent, successor):
            row = rows_by_generation[name].get(session)
            if row is not None:
                latest[name] = row
                decided = decided or shares.get(name, 0.0) > 0.0
        stages = {incumbent: "active", successor: "ramping" if session >= start else "shadow"}
        before = dict(shares)
        shares = update_generation_shares(shares, stages, {}, {}, policy)
        since += 1
        moved_off = before.get(incumbent, 0.0) > 0.0 and shares.get(incumbent, 0.0) == 0.0
        if blend_due(decided_today=decided, sessions_since_blend=since, guard_tripped=moved_off, policy=policy):
            rows[session] = blend_generation_rows(latest, shares)
            path[session] = dict(shares)
            since = 0
    return {"rows": rows, "shares": path}


def replay_dynamic(
    rows_by_generation: Mapping[str, Mapping[str, Mapping[str, float]]], returns_by_generation: Mapping[str, Mapping[str, float]], sessions: Sequence[str], *,
    born: Mapping[str, str], priors: Mapping[str, float], policy: GlidePolicy, initial: Mapping[str, float] | None = None,
) -> dict:
    """The blended file the `dynamic` mode would have written, reading only returns known by each session. Used by the running functions, so a backtest of it tests what would trade.
    {"rows", "shares", "scores"}, with `shares` and `scores` on each session a row is written."""
    names = list(rows_by_generation)
    shares = {name: float((initial or {}).get(name, 0.0)) for name in names}
    latest: dict[str, Mapping[str, float]] = {name: {} for name in names}
    states = {name: (0.0, 0.0, 0.0, 0) for name in names}
    rows: dict[str, dict[str, float]] = {}
    path: dict[str, dict[str, float]] = {}
    scores: dict[str, dict[str, float]] = {}
    since = 0
    for session in sessions:
        decided = False
        for name in names:
            row = rows_by_generation[name].get(session)
            if row is not None:
                latest[name] = row
                decided = decided or (shares.get(name, 0.0) > 0.0 and session >= born[name])
            value = returns_by_generation[name].get(session)
            if value is not None and session >= born[name]:
                states[name] = ew_update(states[name], value, EW_HALF_LIFE_SESSIONS)
        stages = {name: "active" if session >= born[name] else "shadow" for name in names}
        records = {name: {"ew_sharpe": ew_sharpe(states[name]), "sessions": states[name][3], "prior": float(priors[name])} for name in names}
        before = dict(shares)
        shares = dynamic_generation_shares(shares, stages, {}, records, {}, policy)
        since += 1
        moved_off = any(before.get(name, 0.0) > 0.0 and shares.get(name, 0.0) == 0.0 for name in names)
        if blend_due(decided_today=decided, sessions_since_blend=since, guard_tripped=moved_off, policy=policy):
            rows[session] = blend_generation_rows(latest, shares)
            path[session] = dict(shares)
            scores[session] = {name: shrunk_sharpe(records[name]["ew_sharpe"], records[name]["sessions"], records[name]["prior"], policy.prior_sessions) for name in names}
            since = 0
    return {"rows": rows, "shares": path, "scores": scores}


def caps_for(generations: Mapping[str, Generation], evidence: Mapping[str, AdmissionEvidence], policy: GlidePolicy) -> dict[str, float]:
    return {name: share_cap(generation, evidence[name], policy.tier2_paper_cap) for name, generation in generations.items()}
