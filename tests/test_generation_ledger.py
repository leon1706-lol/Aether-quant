"""evaluation/generation_ledger.py: real fill lags, partial coverage, the allocation row and the chain."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.forward_ledger import decide, read_ledger
from evaluation.generation_ledger import (
    ALLOCATION_EVENT,
    ALLOCATION_ID,
    SESSION_EVENT,
    allocation_row,
    append_event,
    decide_generation,
    evidence_for,
    generation_state,
    held_by_lag,
    judge_generations,
    no_data_row,
    record_of,
    replay_dynamic,
    replay_handover,
    row_for_generation,
    session_return_covered,
)
from evaluation.generation_registry import Generation
from portfolio.generation_blend import GlidePolicy
from portfolio.premia_signals import ResearchPanel

SESSIONS = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=400)]
DEFINITION = {
    "id": "t3", "kind": "time_series", "family": "crypto_trend", "universe": ["crypto"], "rebalance_every": 5, "params": {"lookback_a": 20, "lookback_b": 60, "lookback_c": 120},
    "tickers": ["BTCUSD", "ETHUSD"], "asset_class": {"BTCUSD": "crypto", "ETHUSD": "crypto"}, "anchor_date": SESSIONS[300], "cost_class": "crypto", "initial_weights": {"BTCUSD": 0.05}, "data_sources": ["coinbase"],
}
GENERATION = Generation(id="g1", kind="rule", tier="installed", stage="active", born=SESSIONS[0], procedure_sha256="p", definition=DEFINITION)
CLASSES = {"BTCUSD": "crypto", "AAA": "equity"}


def _marks(seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.02, (len(SESSIONS), 2)), axis=0))
    return pd.DataFrame(data, index=SESSIONS, columns=["BTCUSD", "ETHUSD"])


def _rows(tmp_path, sessions: int, *, generation: Generation = GENERATION, marks: pd.DataFrame | None = None, start: int = 301):
    path = tmp_path / "generations.jsonl"
    marks = _marks() if marks is None else marks
    for session in SESSIONS[start:start + sessions]:
        payload = row_for_generation(generation, read_ledger(path), session, SESSIONS, marks, {"SPY": 0.001}, definition_sha="d")
        append_event(path, event=SESSION_EVENT, session=session, candidate=generation.id, payload=payload, created_at=f"{session}T22:45:00+00:00")
    return path


def test_a_generation_decides_like_the_forward_ledger_for_the_same_rule():
    marks = _marks()
    panel = ResearchPanel(marks.loc[:SESSIONS[305]], DEFINITION["asset_class"], {}, {})
    assert decide_generation(DEFINITION, panel, SESSIONS[305]) == decide(DEFINITION, marks.loc[:SESSIONS[305]], SESSIONS[305])


def test_decide_generation_keeps_top_k_and_a_score_table():
    tickers = [f"T{index}" for index in range(12)]
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(np.random.default_rng(2).normal(0, 0.01, (200, 12)), axis=0)), index=SESSIONS[:200], columns=tickers)
    table = pd.DataFrame(np.tile(np.arange(12.0), (200, 1)), index=SESSIONS[:200], columns=tickers)
    definition = {"id": "x", "kind": "cross_sectional", "family": "external_score", "universe": ["tech"], "rebalance_every": 20, "params": {"table": "x", "top_k": 2}}
    panel = ResearchPanel(known, {ticker: "tech" for ticker in tickers}, {}, {"x": table})
    weights = decide_generation(definition, panel, SESSIONS[150])
    assert len(weights) == 4, "two long and two short: the forward ledger's decide would drop top_k here"


def test_a_crypto_decision_earns_only_from_its_real_fill():
    decided = [{"session": "d1", "decided": {"BTCUSD": 0.1}}, {"session": "d2", "decided": {"BTCUSD": 0.2}}, {"session": "d3", "decided": {"BTCUSD": 0.3}}]
    assert held_by_lag(decided, CLASSES, {"BTCUSD": 0.05}) == {"BTCUSD": 0.2}, "decided two sessions ago"
    assert held_by_lag(decided[:1], CLASSES, {"BTCUSD": 0.05}) == {"BTCUSD": 0.05}, "too early: still the starting weights"


def test_an_equity_decision_fills_next_session():
    decided = [{"session": "d1", "decided": {"AAA": 0.1}}, {"session": "d2", "decided": {"AAA": 0.2}}]
    assert held_by_lag(decided, CLASSES, {}) == {"AAA": 0.2}


def test_a_mixed_book_lags_each_class_on_its_own():
    decided = [{"session": "d1", "decided": {"AAA": 0.1, "BTCUSD": 0.1}}, {"session": "d2", "decided": {"AAA": 0.2, "BTCUSD": 0.2}}]
    assert held_by_lag(decided, CLASSES, {}) == {"AAA": 0.2, "BTCUSD": 0.1}


def test_a_session_earns_what_was_held_not_what_it_decided(tmp_path):
    marks = _marks()
    path = _rows(tmp_path, 6, marks=marks)
    rows = [row["payload"] for row in read_ledger(path)]
    row = rows[3]
    position = SESSIONS.index(row["session"])
    expected = sum(weight * (marks.at[SESSIONS[position], ticker] / marks.at[SESSIONS[position - 1], ticker] - 1.0) for ticker, weight in row["held"].items())
    cost = row["turnover"] * 90.0 / 1e4
    assert row["session_return"] == pytest.approx(expected - cost)
    assert rows[4]["rebalance"] is True and rows[3]["rebalance"] is False, "the anchor counts five sessions"


def test_one_delisted_name_does_not_blank_the_session():
    marks = pd.DataFrame({"A": [100.0, 110.0], "B": [100.0, np.nan]}, index=SESSIONS[:2])
    out = session_return_covered({"A": 0.99, "B": 0.01}, marks, SESSIONS[0], SESSIONS[1], classes={}, traded={})
    assert out["session_return"] == pytest.approx(0.099) and out["coverage"] == pytest.approx(0.99)


def test_too_little_coverage_is_no_data_not_a_guess():
    marks = pd.DataFrame({"A": [100.0, 110.0], "B": [100.0, np.nan]}, index=SESSIONS[:2])
    out = session_return_covered({"A": 0.5, "B": 0.5}, marks, SESSIONS[0], SESSIONS[1], classes={}, traded={})
    assert out["session_return"] is None and "under" in out["reason"]


def test_cost_is_per_class():
    marks = pd.DataFrame({"A": [100.0, 100.0]}, index=SESSIONS[:2])
    out = session_return_covered({"A": 1.0}, marks, SESSIONS[0], SESSIONS[1], classes={"A": "crypto", "E": "equity"}, traded={"A": 1.0, "E": 1.0})
    assert out["session_return"] == pytest.approx(-(90.0 + 4.5) / 1e4)


def test_a_failed_fetch_is_a_row_with_its_reason(tmp_path):
    path = _rows(tmp_path, 2)
    payload = no_data_row(GENERATION, read_ledger(path), reason="Yahoo chart: ConnectionError", benchmarks={})
    assert payload["status"] == "no_data" and payload["session_return"] is None and payload["reason"].startswith("Yahoo")


def test_a_host_decision_is_used_and_a_needing_generation_does_not_decide_itself():
    generation = Generation(id="g2", kind="model", tier="tier2", stage="shadow", born=SESSIONS[0], procedure_sha256="p", definition=DEFINITION, needs="fundamentals")
    marks = _marks()
    held = row_for_generation(generation, [], SESSIONS[301], SESSIONS, marks, {}, decision=None)
    assert held["rebalance"] is False and held["decided"] == DEFINITION["initial_weights"]
    fresh = row_for_generation(generation, [], SESSIONS[301], SESSIONS, marks, {}, decision={"ETHUSD": 0.02})
    assert fresh["rebalance"] is True and fresh["decided"] == {"ETHUSD": 0.02}


def test_a_tampered_row_is_caught(tmp_path):
    path = _rows(tmp_path, 3)
    assert judge_generations(read_ledger(path))["chain_valid"] is True
    rows = read_ledger(path)
    rows[1]["payload"]["session_return"] = 0.5
    assert judge_generations(rows)["chain_valid"] is False


def test_the_guard_trips_at_the_ceiling_and_latches():
    mine = [{"status": "ok", "session_return": -0.02} for _ in range(10)]
    assert generation_state(GENERATION, mine, guard_max_drawdown=0.15)["state"] == "tripped"
    recovered = [{"status": "ok", "session_return": 0.0, "state": "tripped"}] + [{"status": "ok", "session_return": 0.01} for _ in range(5)]
    assert generation_state(GENERATION, recovered, guard_max_drawdown=0.15)["state"] == "tripped"


def test_a_small_loss_does_not_trip_the_guard():
    mine = [{"status": "ok", "session_return": -0.001} for _ in range(10)]
    assert generation_state(GENERATION, mine, guard_max_drawdown=0.15)["state"] == "healthy"


def test_evidence_comes_from_the_record():
    generation = Generation(id="g2", kind="rule", tier="tier2", stage="shadow", born="x", procedure_sha256="p", admission={"selection_pass": True, "hold_pass": True})
    evidence = evidence_for(
        generation, {"rows": 10, "sessions": 9, "no_data_sessions": 1, "alpha": {"t_hac": 2.5}}, incumbent_returns={"a": 0.0, "b": 0.01}, own_returns={"a": 0.01, "b": 0.01, "c": 9.0}, holdouts_spent=True, state={"state": "healthy"},
    )
    assert evidence.selection_pass and evidence.hold_pass and evidence.holdouts_spent
    assert evidence.forward_ok_sessions == 9 and evidence.no_data_share == pytest.approx(0.1) and evidence.forward_alpha_t == 2.5
    assert evidence.mean_diff_vs_incumbent == pytest.approx(0.005), "only sessions both have"
    empty = evidence_for(generation, {}, incumbent_returns=None, own_returns={}, holdouts_spent=False, state={})
    assert empty.mean_diff_vs_incumbent is None and empty.forward_alpha_t is None


def test_an_allocation_writes_a_blended_row_only_when_due():
    generations = {"old": GENERATION, "new": Generation(id="new", kind="rule", tier="tier1", stage="ramping", born="x", procedure_sha256="p")}
    rows = {"old": {"BTCUSD": 0.1}, "new": {"ETHUSD": 0.2}}
    states = {"old": {"state": "healthy"}, "new": {"state": "healthy"}}
    caps = {"old": 1.0, "new": 1.0}
    held = allocation_row(generations, {"old": 0.7, "new": 0.3}, states, caps, rows, GlidePolicy(), decided_today=False, sessions_since_blend=3)
    assert held["blend_due"] is False and held["blended"] is None and held["sessions_since_blend"] == 3
    due = allocation_row(generations, {"old": 0.7, "new": 0.3}, states, caps, rows, GlidePolicy(), decided_today=True, sessions_since_blend=3)
    assert due["blend_due"] is True and due["sessions_since_blend"] == 0
    assert due["blended"]["BTCUSD"] == pytest.approx(due["shares"]["old"] * 0.1)


def test_a_guard_trip_forces_a_blended_row_today():
    generations = {"old": GENERATION}
    row = allocation_row(generations, {"old": 1.0}, {"old": {"state": "tripped"}}, {"old": 1.0}, {"old": {"BTCUSD": 0.1}}, GlidePolicy(), decided_today=False, sessions_since_blend=1)
    assert row["shares"]["old"] == 0.0 and row["blend_due"] is True and row["blended"] == {} and row["tbills"] == 1.0


def test_a_replayed_handover_moves_the_book_from_one_rule_to_the_other():
    days = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2016-01-04", periods=400)]
    old = {day: {"BTCUSD": 0.02} for day in days[::5]}
    new = {day: {"AAA": 0.03} for day in days[::20]}
    policy = GlidePolicy(glide_sessions=252)
    out = replay_handover({"old": old, "new": new}, days, incumbent="old", successor="new", start=days[100], policy=policy)
    before = [row for date, row in out["rows"].items() if date < days[100]]
    assert all(set(row) == {"BTCUSD"} and row["BTCUSD"] == pytest.approx(0.02) for row in before), "share 1.0 is the incumbent's own row"
    last = out["rows"][max(out["rows"])]
    assert set(last) == {"AAA"} and last["AAA"] == pytest.approx(0.03), "by the end the successor holds the whole book"
    shares = list(out["shares"].values())
    assert all(later["new"] >= earlier["new"] - 1e-12 for earlier, later in zip(shares, shares[1:]))
    assert len(out["rows"]) < len(days), "a row retargets every name, so it isn't written daily"


def _three_generations():
    days = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2016-01-04", periods=900)]
    rows = {"a": {day: {"BTCUSD": 0.02} for day in days[::5]}, "b": {day: {"AAA": 0.03} for day in days[::20]}, "c": {day: {"BBB": 0.01} for day in days[::20]}}
    rng = np.random.default_rng(6)
    returns = {name: {day: float(value) for day, value in zip(days, rng.normal(0.0006, 0.01, len(days)))} for name in rows}
    return days, rows, returns


def test_a_replay_holds_three_generations_and_reads_only_what_was_known():
    days, rows, returns = _three_generations()
    policy = GlidePolicy(mode="dynamic", half_life_sessions=63)
    born = {"a": days[0], "b": days[200], "c": days[400]}
    priors = {"a": 0.5, "b": 0.5, "c": 0.5}
    out = replay_dynamic(rows, returns, days, born=born, priors=priors, policy=policy, initial={"a": 1.0})
    assert any(sum(value >= policy.retire_share for value in shares.values()) >= 3 for shares in out["shares"].values())
    assert all(shares["b"] == 0.0 for date, shares in out["shares"].items() if date < born["b"]), "no share before it exists"
    assert all(abs(sum(row.values())) <= 1.0 for row in out["rows"].values())
    cut = days[600]
    later = {name: {day: (value if day <= cut else -0.5) for day, value in series.items()} for name, series in returns.items()}
    moved = replay_dynamic(rows, later, days, born=born, priors=priors, policy=policy, initial={"a": 1.0})
    assert {date: shares for date, shares in moved["shares"].items() if date <= cut} == {date: shares for date, shares in out["shares"].items() if date <= cut}


def test_an_allocation_row_follows_the_policys_mode():
    generations = {"old": GENERATION, "new": Generation(id="new", kind="rule", tier="tier1", stage="ramping", born="x", procedure_sha256="p")}
    rows = {"old": {"BTCUSD": 0.1}, "new": {"ETHUSD": 0.2}}
    states = {"old": {"state": "healthy"}, "new": {"state": "healthy"}}
    records = {"old": {"ew_sharpe": 0.5, "sessions": 500, "prior": 0.5}, "new": {"ew_sharpe": None, "sessions": 0, "prior": 0.5}}
    ladder = allocation_row(generations, {"old": 1.0, "new": 0.0}, states, {}, rows, GlidePolicy(), decided_today=False, sessions_since_blend=0, records=records)
    dynamic = allocation_row(generations, {"old": 1.0, "new": 0.0}, states, {}, rows, GlidePolicy(mode="dynamic"), decided_today=False, sessions_since_blend=0, records=records)
    assert ladder["shares"]["new"] == pytest.approx(0.30), "the ladder's entry jumps"
    assert 0.0 < dynamic["shares"]["new"] < 0.01, "the dynamic mode doesn't"


def test_the_record_is_what_the_allocator_reads():
    values = list(np.random.default_rng(1).normal(0.001, 0.01, 100))
    record = record_of(values, prior=0.3)
    assert record["sessions"] == 100 and record["prior"] == 0.3 and record["ew_sharpe"] is not None
    assert record_of([], prior=0.3) == {"ew_sharpe": None, "sessions": 0, "prior": 0.3}


def test_judging_skips_the_allocation_rows(tmp_path):
    path = _rows(tmp_path, 2)
    append_event(path, event=ALLOCATION_EVENT, session=SESSIONS[303], candidate=ALLOCATION_ID, payload={"status": "allocation", "shares": {"g1": 1.0}}, created_at="t")
    report = judge_generations(read_ledger(path))
    assert list(report["generations"]) == ["g1"] and report["latest_allocation"]["shares"] == {"g1": 1.0}
