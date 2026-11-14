"""scripts/v650_research.py's runtime (V6.6.6, #359): the rule-file guard, the context with its model scores, every stage (score, placebo, gate, combine) and
the command, with the context and the sleeve simulation stubbed."""

from __future__ import annotations

import hashlib
import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2012-01-02", periods=60)]
RULES = {"selection_windows": {"rule_sleeves": ["2012-01-02", "2012-02-15", "2012-03-20"], "ml_sleeves": ["2012-01-02", "2012-02-15", "2012-03-20"]}}


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("v650_research")
    out = tmp_path / "v650"
    out.mkdir()
    for name, value in (("OUT", out), ("SCORES", out / "selection_scores.json"), ("DAILY", out / "selection_daily.parquet"), ("PLACEBOS", out / "selection_placebos.json"),
                        ("GATE", out / "selection_gate.json"), ("LEDGER", out / "trial_ledger.jsonl"), ("ML_SCORES", out / "scores"), ("ROOT", tmp_path)):
        monkeypatch.setattr(research, name, value)
    text = json.dumps(RULES)
    (out / "rules.json").write_text(text, encoding="utf-8")
    (out / "rules.sha256").write_text(hashlib.sha256(text.encode("utf-8")).hexdigest() + "\n", encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    return research


class _AllTables(dict):
    def __contains__(self, key):
        return True


def _context(all_tables=False):
    known = pd.DataFrame(100.0 + np.arange(60)[:, None] + np.arange(3)[None, :], index=DATES, columns=["SPY", "AAA", "BBB"])
    panel = SimpleNamespace(known=known, asset_class={"SPY": "equity"}, fred={}, extras=_AllTables(existing=known) if all_tables else {"existing": known})
    return SimpleNamespace(panel=panel, settings=None, simulate=lambda rows, start, end: {"strategy": pd.Series(np.sin(np.arange(60)) * 0.01, index=DATES)})


def test_the_rule_file_is_guarded_and_the_selection_window_is_enforced(module):
    assert module.check_rules() == RULES
    assert module.window_of(next(spec for spec in module.ALL_SPECS if spec.track in ("T2", "T5")), RULES) == tuple(RULES["selection_windows"]["ml_sleeves"])
    assert module.window_of(next(spec for spec in module.ALL_SPECS if spec.track not in ("T2", "T5")), RULES)[0] == "2012-01-02"
    module.assert_selection_only("2012-01-01")
    with pytest.raises(SystemExit):
        module.assert_selection_only("2099-01-01")
    (module.OUT / "rules.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        module.check_rules()


def test_the_context_adds_model_score_tables_up_to_the_selection_end(module, monkeypatch):
    monkeypatch.setattr(module, "build_context", lambda root, config: _context())
    plain = module.load_context()
    assert set(plain.panel.extras) == {"existing"}
    module.ML_SCORES.mkdir()
    pd.DataFrame({"date": [DATES[0], DATES[1], "2099-01-01"], "ticker": ["AAA", "AAA", "AAA"], "score": [0.1, 0.2, 0.9]}).to_csv(module.ML_SCORES / "m1.csv", index=False)
    with_scores = module.load_context()
    assert "m1" in with_scores.panel.extras and with_scores.panel.extras["m1"]["AAA"].dropna().max() == 0.2


def test_json_helpers(module, tmp_path):
    assert module.read_json(tmp_path / "none.json", 5) == 5
    module.write_json(tmp_path / "x.json", {"a": 1})
    assert module.read_json(tmp_path / "x.json", None) == {"a": 1} and module._show(None).strip() == "n/a" and module._show(0.5).strip() == "0.50"


def test_scoring_skips_other_tracks_existing_scores_and_missing_tables(module, monkeypatch, capsys):
    context = _context(all_tables=True)
    monkeypatch.setattr(module, "load_context", lambda: context)
    daily = {0: pd.Series(np.cos(np.arange(60)) * 0.01, index=DATES)}
    monkeypatch.setattr(module, "score_sleeve", lambda spec, ctx, start, split, end: {"sharpe": 1.0, "sharpe_first_half": 0.9, "sharpe_second_half": 1.1, "max_drawdown": 0.1, "turnover": 2.0,
                                                                                    "mean_gross": 0.5, "daily": dict(daily)})
    tracks = sorted({spec.track for spec in module.ALL_SPECS})
    assert module.stage_score(SimpleNamespace(tracks=tracks[:1], force=False)) == 0
    first = json.loads(module.SCORES.read_text(encoding="utf-8"))
    assert first and module.DAILY.exists()
    assert module.stage_score(SimpleNamespace(tracks=tracks, force=False)) == 0
    context.panel.extras = {"existing": context.panel.known}
    assert module.stage_score(SimpleNamespace(tracks=tracks, force=True)) == 0
    assert "no table" in capsys.readouterr().out
    assert len(json.loads(module.SCORES.read_text(encoding="utf-8"))) >= len(first)
    assert module.stage_score(SimpleNamespace(tracks=tracks[:1], force=True)) == 0


def test_the_placebo_stage_tests_only_trials_that_passed_the_sharpe_clauses(module, monkeypatch):
    context = _context()
    monkeypatch.setattr(module, "load_context", lambda: context)
    first, second = module.ALL_SPECS[0], module.ALL_SPECS[1]
    module.write_json(module.SCORES, {first.id: {"sharpe": 1.0}, second.id: {"sharpe": 0.0}})
    monkeypatch.setattr(module, "passes_sharpe_clauses", lambda score: score["sharpe"] > 0.5)
    monkeypatch.setattr(module, "nulls_for", lambda spec: ["shuffle", "shift"])
    monkeypatch.setattr(module, "placebo_sharpes", lambda spec, ctx, mode, start, end, draws: [] if mode == "shift" else [0.1, 0.2, 0.3])
    monkeypatch.setattr(module, "placebo_p_value", lambda observed, sharpes: 0.04)
    assert module.stage_placebo(SimpleNamespace(draws=3, force=False, only=None, suffix="_a")) == 0
    done = json.loads((module.OUT / "selection_placebos_a.json").read_text(encoding="utf-8"))
    assert set(done) == {first.id} and done[first.id]["shuffle"]["draws"] == 3
    assert module.stage_placebo(SimpleNamespace(draws=3, force=False, only=None, suffix="_a")) == 0
    assert module.stage_placebo(SimpleNamespace(draws=3, force=True, only=["other"], suffix="_a")) == 0


def test_the_gate_merges_every_placebo_part(module, monkeypatch):
    first = module.ALL_SPECS[0]
    module.write_json(module.SCORES, {first.id: {"sharpe": 1.0}})
    pd.DataFrame({first.id: np.sin(np.arange(60)) * 0.01}, index=DATES).to_parquet(module.DAILY)
    module.write_json(module.OUT / "selection_placebos.json", {first.id: {"shuffle": {"p": 0.01}}})
    module.write_json(module.OUT / "selection_placebos_b.json", {first.id: {"shift": {"p": 0.02}}})
    monkeypatch.setattr(module, "selection_gate", lambda rows, p_values: {"survivors": [first.id for row in rows], "p": p_values})
    assert module.stage_gate(SimpleNamespace()) == 0
    gate = json.loads(module.GATE.read_text(encoding="utf-8"))
    assert gate["survivors"] == [first.id] and gate["unscored"] and "shift" in gate["p"][first.id]


def test_the_combination_scores_two_methods_over_the_survivors(module, monkeypatch, capsys):
    assert module.stage_combine(SimpleNamespace()) == 0 and "no survivor" in capsys.readouterr().out
    survivor = module.ALL_SPECS[0]
    module.write_json(module.GATE, {"survivors": [survivor.id]})
    context = _context()
    monkeypatch.setattr(module, "load_context", lambda: context)
    monkeypatch.setattr(module, "sleeve_signal", lambda spec, panel: panel.known)
    monkeypatch.setattr(module, "weights_for", lambda spec, ctx, signal, start, end, phase_offset: [{"AAA": 0.1}])
    monkeypatch.setattr(module, "combine_sleeves", lambda sleeves, panel, method, settings, start, end: [{"AAA": 0.1}])
    assert module.stage_combine(SimpleNamespace()) == 0
    result = json.loads((module.OUT / "selection_combination.json").read_text(encoding="utf-8"))
    assert set(result["results"]) == set(module.COMBINATION_IDS)


@pytest.mark.parametrize("argv,name", [(["score", "--tracks", "T3", "--force"], "score"), (["placebo", "--draws", "3", "--only", "a", "--suffix", "_x", "--force"], "placebo"),
                                       (["gate"], "gate"), (["combine"], "combine")])
def test_the_command_dispatches_each_stage(module, monkeypatch, argv, name):
    seen = []
    monkeypatch.setattr(module, f"stage_{name}", lambda args: seen.append(name) or 0)
    monkeypatch.setattr(sys, "argv", ["v650", *argv])
    assert module.main() == 0 and seen == [name]
