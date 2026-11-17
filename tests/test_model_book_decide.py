"""scripts/model_book_decide.py: a session's holding as `ticker,weight`, refused on the pins, stale data or stale scores (V6.6.9, audit item 11)."""

from __future__ import annotations

import pytest

from script_loader import fake_module, load_script, run_script


@pytest.fixture
def decide(monkeypatch, tmp_path):
    module = load_script("model_book_decide")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path / "v669")
    (tmp_path / "ml" / "generations").mkdir(parents=True)
    monkeypatch.setattr(module.rnd, "load_round_context", lambda root, sources, end=None: "ctx")
    monkeypatch.setattr(module.rnd, "check_freeze", lambda out: {"candidate": "b03"})
    monkeypatch.setattr(module, "artifact_problems", lambda ml_dir, path: [])
    fake_module(monkeypatch, "daily_target_weights", data_problems=lambda context, date: [])
    monkeypatch.setattr(module.rnd, "score_problem", lambda context, session: None)
    monkeypatch.setattr(module.rnd, "decide_row", lambda context, frozen, session, verification=None: {"SPY": 0.05, "TLT": -0.01})
    return module


def test_long_sources_name_the_combined_score_files(decide):
    assert {name: path.name for name, path in decide.long_sources().items()} == {"ml_a1": "long_a1.csv", "ml_a2": "long_a2.csv", "ml_a3": "long_a3.csv"}


def test_a_decision_is_written_as_ticker_and_weight(decide, tmp_path, capsys):
    out = tmp_path / "cycle" / "g0006.csv"
    assert decide.main(["--session", "2026-11-13", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").splitlines() == ["ticker,weight", "SPY,0.05", "TLT,-0.01"]
    assert "2 weights" in capsys.readouterr().out


def test_a_changed_model_file_stale_data_or_stale_scores_refuse(decide, monkeypatch, tmp_path, capsys):
    out = str(tmp_path / "x.csv")
    monkeypatch.setattr(decide, "artifact_problems", lambda ml_dir, path: ["gating_model.json does not match its pin"])
    assert decide.main(["--session", "2026-11-13", "--out", out]) == 1 and "pinned ones" in capsys.readouterr().err
    monkeypatch.setattr(decide, "artifact_problems", lambda ml_dir, path: [])
    fake_module(monkeypatch, "daily_target_weights", data_problems=lambda context, date: ["crypto data is 9 days old"])
    assert decide.main(["--session", "2026-11-13", "--out", out]) == 1 and "9 days old" in capsys.readouterr().err
    fake_module(monkeypatch, "daily_target_weights", data_problems=lambda context, date: [])
    monkeypatch.setattr(decide.rnd, "score_problem", lambda context, session: "the newest ml_a1 score is 20 days older")
    assert decide.main(["--session", "2026-11-13", "--out", out]) == 1 and "20 days older" in capsys.readouterr().err
    assert not (tmp_path / "x.csv").exists()


def test_a_session_before_the_first_decision_is_refused(decide, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(decide.rnd, "decide_row", lambda context, frozen, session, verification=None: None)
    assert decide.main(["--session", "2023-06-01", "--out", str(tmp_path / "x.csv")]) == 1 and "before the book's first decision" in capsys.readouterr().err


def test_the_ledger_needs_a_generation_and_records_the_decision_once(decide, monkeypatch, tmp_path, capsys):
    out = str(tmp_path / "g.csv")
    assert decide.main(["--session", "2026-11-13", "--out", out, "--ledger", str(tmp_path / "decisions.jsonl")]) == 2
    appended = []
    fake_module(monkeypatch, "cycle_decide", read_weights=lambda path: {"SPY": 0.05},
                write_decision=lambda registry, generation, weights, ledger, **kwargs: appended.append((generation, weights, kwargs["session"])) or {"ok": 1})
    assert decide.main(["--session", "2026-11-13", "--out", out, "--ledger", str(tmp_path / "decisions.jsonl"), "--generation", "g0006"]) == 0
    assert appended == [("g0006", {"SPY": 0.05}, "2026-11-13")] and "decision appended" in capsys.readouterr().out
    fake_module(monkeypatch, "cycle_decide", read_weights=lambda path: {}, write_decision=lambda *args, **kwargs: None)
    assert decide.main(["--session", "2026-11-13", "--out", out, "--ledger", str(tmp_path / "decisions.jsonl"), "--generation", "g0006"]) == 0
    assert "already decided" in capsys.readouterr().out


def test_run_as_a_script_it_needs_its_arguments(monkeypatch, capsys):
    assert run_script("model_book_decide", [], monkeypatch) == 2
    assert "required" in capsys.readouterr().err
