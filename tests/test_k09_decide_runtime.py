"""scripts/k09_decide.py's runtime (V6.6.6, #359): a session with no rankable name, and the whole command (membership, sectors, Yahoo closes, the weights file, the
optional ledger decision) with the data sources and the ledger stood in."""

from __future__ import annotations

import json
import sys

import pandas as pd
import pytest

from script_loader import load_script

SESSION = "2026-11-06"
DAYS = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2026-05-01", SESSION)]


@pytest.fixture
def module(monkeypatch, tmp_path):
    decide = load_script("k09_decide")
    monkeypatch.setattr(decide, "ROOT", tmp_path)
    return decide


def test_a_name_without_a_sector_or_price_is_not_ranked_and_nothing_is_held_without_names(module):
    known = pd.DataFrame({"AAA": [1.0, 2.0]}, index=["2026-11-05", SESSION])
    assert module.k09_weights(SESSION, known, pd.DataFrame(), pd.DataFrame(), ["AAA", "ZZZ"], {"AAA": "unknown"}) == {}
    assert module.k09_weights(SESSION, known, pd.DataFrame(), pd.DataFrame(), ["ZZZ"], {"ZZZ": "tech"}) == {}


def _world(module, monkeypatch, tmp_path, *, closes_for, ledger_row="row"):
    import cycle_decide
    import data_pipeline.edgar_facts as edgar_facts
    import data_pipeline.sp500_membership as membership
    import evaluation.research_cells as cells
    import forward_ledger

    reference = tmp_path / "data_wide" / "reference"
    reference.mkdir(parents=True, exist_ok=True)
    (reference / "sectors.json").write_text(json.dumps({"AAA": "tech", "BBB": "energy", "CCC": "unknown", "DDD": "tech"}), encoding="utf-8")
    monkeypatch.setattr(membership, "load_membership", lambda path: {"AAA": 1, "BBB": 1, "CCC": 1, "DDD": 1})
    monkeypatch.setattr(cells, "membership_mask", lambda members, sessions, names: pd.DataFrame({name: [name != "DDD"] for name in names}, index=sessions))
    monkeypatch.setattr(edgar_facts, "read_fundamentals", lambda path: pd.DataFrame())
    monkeypatch.setattr(forward_ledger, "session_for_outage", lambda now: SESSION)
    monkeypatch.setattr(forward_ledger, "yahoo_closes", closes_for)
    monkeypatch.setattr(module, "k09_weights", lambda session, known, extended, fundamentals, members, sectors: {"AAA": 0.1, "BBB": -0.1, "ZERO": 0.0})
    written = {}
    def write_decision(registry, generation, weights, ledger, session, created_at, source):
        written.update(generation=generation, session=session, weights=weights)
        return None if ledger_row is None else {"row": 1}

    monkeypatch.setattr(cycle_decide, "write_decision", write_decision)
    monkeypatch.setattr(cycle_decide, "read_weights", lambda path: {"AAA": 0.1})
    return written


def _closes(ticker, getter):
    if ticker == "BBB":
        raise ValueError("yahoo cannot serve this")
    return {day: 10.0 + index for index, day in enumerate(DAYS)}


def test_the_weights_of_the_session_are_written_beside_the_names_yahoo_could_not_serve(module, monkeypatch, tmp_path, capsys):
    _world(module, monkeypatch, tmp_path, closes_for=_closes)
    out = tmp_path / "out" / "k09.csv"
    monkeypatch.setattr(sys, "argv", ["k09_decide", "--out", str(out)])
    assert module.main() == 0
    frame = pd.read_csv(out)
    assert set(frame["ticker"]) == {"AAA", "BBB", "ZERO"} and f"{SESSION}: 3 weights (1 long, 1 short)" in capsys.readouterr().out


def test_a_session_without_closes_yet_is_not_decided(module, monkeypatch, tmp_path, capsys):
    _world(module, monkeypatch, tmp_path, closes_for=lambda ticker, getter: {day: 1.0 for day in DAYS[:-3]})
    monkeypatch.setattr(sys, "argv", ["k09_decide", "--out", str(tmp_path / "k09.csv"), "--session", SESSION])
    assert module.main() == 1 and f"no closes for {SESSION} yet" in capsys.readouterr().err and not (tmp_path / "k09.csv").exists()


def test_the_ledger_needs_a_generation_and_reports_whether_the_decision_was_new(module, monkeypatch, tmp_path, capsys):
    written = _world(module, monkeypatch, tmp_path, closes_for=_closes)
    out = str(tmp_path / "k09.csv")
    monkeypatch.setattr(sys, "argv", ["k09_decide", "--out", out, "--session", SESSION, "--ledger", str(tmp_path / "decisions.jsonl")])
    assert module.main() == 2 and "--ledger needs --generation" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["k09_decide", "--out", out, "--session", SESSION, "--ledger", str(tmp_path / "decisions.jsonl"), "--generation", "g0005"])
    assert module.main() == 0 and written["generation"] == "g0005" and "decision appended" in capsys.readouterr().out
    _world(module, monkeypatch, tmp_path, closes_for=_closes, ledger_row=None)
    assert module.main() == 0 and "already decided" in capsys.readouterr().out
