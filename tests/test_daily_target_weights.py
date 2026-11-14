"""scripts/daily_target_weights.py: a row computed with today's data equals the research file's row, and a date is written once."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from portfolio.premia_signals import TS, ResearchPanel, SleeveSpec, known_closes, signal_to_weights, sleeve_signal
from portfolio.target_weights import load_weight_file, weights_at_tick

_SPEC = importlib.util.spec_from_file_location(
    "daily_target_weights", Path(__file__).resolve().parent.parent / "scripts" / "daily_target_weights.py"
)
module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(module)

SPEC = SleeveSpec("trend", "T3", TS, "time_series_momentum", ("equity",), 5, {"lookback_a": 63})


def _context():
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2018-01-01", periods=400).strftime("%Y-%m-%d").tolist()
    tickers = ["A", "B", "C", "D", "E"]
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, size=(400, 5)), axis=0))
    classes = {ticker: "equity" for ticker in tickers}
    panel = ResearchPanel(known_closes(dates, tickers, closes, classes, set(dates)), classes)
    return SimpleNamespace(panel=panel)


def _candidate_rows(definition, context, *, start, end, phase_index):
    signal = sleeve_signal(SPEC, context.panel)
    return signal_to_weights(signal, context.panel, kind=SPEC.kind, rebalance_every=SPEC.rebalance_every, phase_offset=phase_index, start=start, end=end)


def test_daily_rows_equal_the_research_file():
    context = _context()
    start = str(context.panel.known.index[100])
    research = _candidate_rows({}, context, start=start, end=str(context.panel.known.index[-1]), phase_index=0)

    checked = 0
    for date in sorted(research)[5:30:6]:
        row = module.row_for_date({}, context, date, candidate_rows=_candidate_rows, history_start=start)
        assert row == pytest.approx(research[date])
        checked += 1
    assert checked >= 3


def _generations_ledger(tmp_path):
    from evaluation.generation_ledger import ALLOCATION_EVENT, ALLOCATION_ID, append_event

    path = tmp_path / "generations.jsonl"
    append_event(path, event=ALLOCATION_EVENT, session="2026-11-05", candidate=ALLOCATION_ID, payload={"status": "allocation", "shares": {"g1": 1.0}, "blended": {"BTCUSD": 0.02}}, created_at="t")
    append_event(path, event=ALLOCATION_EVENT, session="2026-11-06", candidate=ALLOCATION_ID, payload={"status": "allocation", "shares": {"g1": 1.0}, "blended": None}, created_at="t")
    append_event(path, event=ALLOCATION_EVENT, session="2026-11-09", candidate=ALLOCATION_ID, payload={"status": "allocation", "shares": {"g1": 0.0}, "blended": {}}, created_at="t")
    return path


def test_blended_rows_reach_the_file_a_live_run_reloads(tmp_path):
    from portfolio.target_weights import load_live_weight_file, next_unapplied_row

    ledger, out = _generations_ledger(tmp_path), tmp_path / "blended.csv"
    assert module.write_blended(ledger, out) == ["2026-11-05", "2026-11-09"], "a session with no row due writes none"
    weights = load_live_weight_file(out)
    assert next_unapplied_row(weights, "2026-11-06", None) == ("2026-11-05", {"BTCUSD": 0.02})
    assert next_unapplied_row(weights, "2026-11-10", "2026-11-05") == ("2026-11-09", {}), "flat is a decision, and it reaches the book"
    assert module.write_blended(ledger, out) == [], "a date is written once"


def test_a_broken_chain_stops_the_blend_before_any_order(tmp_path):
    ledger, out = _generations_ledger(tmp_path), tmp_path / "blended.csv"
    ledger.write_text(ledger.read_text(encoding="utf-8").replace('"BTCUSD": 0.02', '"BTCUSD": 0.99'), encoding="utf-8")
    with pytest.raises(ValueError, match="chain"):
        module.write_blended(ledger, out)
    assert not out.exists()


def test_a_date_that_is_no_rebalance_day_gives_no_row():
    context = _context()
    start = str(context.panel.known.index[100])
    off_day = str(context.panel.known.index[101])
    assert module.row_for_date({}, context, off_day, candidate_rows=_candidate_rows, history_start=start) is None


def test_row_for_date_leaves_the_full_panel_in_place():
    context = _context()
    original = context.panel
    module.row_for_date({}, context, str(original.known.index[200]), candidate_rows=_candidate_rows, history_start=str(original.known.index[100]))
    assert context.panel is original


def test_append_writes_a_date_once_and_the_file_loads(tmp_path):
    path = tmp_path / "live.csv"
    assert module.append_row(path, "2024-01-02", {"SPY": 0.5, "TLT": -0.25}) is True
    assert module.append_row(path, "2024-01-02", {"SPY": 0.9}) is False
    assert module.append_row(path, "2024-01-03", {}) is True

    weights = load_weight_file(path)
    assert weights_at_tick(weights, "2024-01-02") == {"SPY": 0.5, "TLT": -0.25}
    assert weights_at_tick(weights, "2024-01-03") == {}


def test_append_refuses_a_non_finite_weight(tmp_path):
    with pytest.raises(ValueError, match="non-finite"):
        module.append_row(tmp_path / "live.csv", "2024-01-02", {"SPY": float("nan")})
    assert not (tmp_path / "live.csv").exists()


def test_the_cli_decides_once_refuses_bad_data_and_writes_blended_rows(tmp_path, monkeypatch, capsys):
    import json
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import v650_lean
    import v650_research

    definition = tmp_path / "candidate.json"
    definition.write_text(json.dumps({"id": "t3"}), encoding="utf-8")
    out = tmp_path / "weights.csv"
    context = SimpleNamespace(panel=SimpleNamespace(known=pd.DataFrame(index=["2024-01-02", "2024-01-03"])))
    monkeypatch.setattr(v650_research, "load_context", lambda: context)
    monkeypatch.setattr(v650_lean, "candidate_rows", lambda *args, **kwargs: {})
    problems = iter([["BTCUSD has no bar on 2024-01-03"], [], [], []])
    monkeypatch.setattr(module, "data_problems", lambda context, date: next(problems))
    rows = iter([{"BTCUSD": 0.1}, {"BTCUSD": 0.1}, None])
    monkeypatch.setattr(module, "row_for_date", lambda definition, context, date, candidate_rows, history_start: next(rows))

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["daily_target_weights.py", *argv])
        return module.main()

    assert run("--candidate", str(definition), "--out", str(out)) == 1 and "refusing to decide" in capsys.readouterr().err
    assert run("--candidate", str(definition), "--out", str(out)) == 0 and "2024-01-03: wrote 1 weights" in capsys.readouterr().out
    assert run("--candidate", str(definition), "--out", str(out), "--date", "2024-01-03") == 0 and "already held" in capsys.readouterr().out
    assert run("--candidate", str(definition), "--out", str(out)) == 0 and "not a rebalance day" in capsys.readouterr().out
    monkeypatch.setattr(module, "write_blended", lambda ledger, out: ["2024-01-04"])
    assert run("--generations", "forward/generations.jsonl", "--out", str(out)) == 0 and "2024-01-04: wrote the blended row" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        run("--out", str(out))


def test_a_date_is_refused_when_it_is_no_session_or_a_class_has_gone_stale():
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
    closes = np.array([[1.0, 10.0], [1.0, 10.0], [1.0, np.nan], [1.0, np.nan], [1.0, np.nan]])
    market = SimpleNamespace(closes=closes, dates=dates, tickers=["SPY", "BTCUSD"], asset_class={"SPY": "equity", "BTCUSD": "crypto", "AGG": "bond"})
    context = SimpleNamespace(panel=SimpleNamespace(known=pd.DataFrame(index=dates)), market=market)
    assert module.data_problems(context, "2024-01-09") == ["2024-01-09 is not a session in the data (last is 2024-01-08)"]
    assert module.data_problems(context, "2024-01-08") == ["crypto data is 5 days old on 2024-01-08 (limit 2)"]
    assert module.data_problems(context, "2024-01-03") == []
