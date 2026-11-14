"""scripts/v660_research.py's runtime (V6.6.6, #359): the rule-file guard, the cells, every stage (score, placebo, gate, PBO, combine, blend, R-VEL1) and the
command, with the cells and the sleeve simulation stubbed. The rules, the files and the decisions are the script's own."""

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
TICKERS = ["SPY", "AAA", "BBB", "BTCUSD", "ETHUSD", "LTCUSD"]


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("v660_research")
    out = tmp_path / "v660"
    out.mkdir()
    for name, value in (("OUT", out), ("RULES", out / "rules.json"), ("RULES_SHA", out / "rules.sha256"), ("SCORES", out / "selection_scores.json"), ("DAILY", out / "selection_daily.parquet"),
                        ("GATE", out / "selection_gate.json"), ("LEDGER", out / "trial_ledger.jsonl"), ("ML_SCORES", out / "scores"), ("ROOT", tmp_path)):
        monkeypatch.setattr(research, name, value)
    payload = json.dumps({"rules": 1}).encode("utf-8")
    research.RULES.write_bytes(payload)
    research.RULES_SHA.write_text(hashlib.sha256(payload).hexdigest() + "\n", encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"phase1": {}}), encoding="utf-8")
    return research


def _cell(module, universe="equity", name="S"):
    known = pd.DataFrame(100.0 + np.arange(60)[:, None] + np.arange(6)[None, :], index=DATES, columns=TICKERS)
    panel = SimpleNamespace(known=known, extras={}, asset_class={})
    context = SimpleNamespace(panel=panel, market=SimpleNamespace(sessions=DATES), settings=None, simulate=lambda rows, start, end: {"strategy_excess": pd.Series(np.sin(np.arange(60)) * 0.01, index=DATES), "strategy": pd.Series(np.sin(np.arange(60)) * 0.01, index=DATES)})
    cell = SimpleNamespace(universe=universe, name=name, start=DATES[0], end=DATES[-1], split=DATES[30])
    return SimpleNamespace(cell=cell, context=context, member=pd.DataFrame(True, index=DATES, columns=TICKERS), tables={}, label=known.pct_change())


def test_the_rule_file_must_match_its_recorded_hash_and_selection_never_reads_a_held_cell(module):
    assert module.check_rules() == {"rules": 1}
    module.RULES_SHA.write_text("0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        module.check_rules()
    module.assert_selection_only("2012-01-01")
    with pytest.raises(SystemExit):
        module.assert_selection_only("2099-01-01")


def test_json_helpers_and_the_base_config(module, tmp_path):
    assert module.read_json(tmp_path / "none.json", "default") == "default"
    module.write_json(tmp_path / "x.json", {"a": 1})
    assert module.read_json(tmp_path / "x.json", None) == {"a": 1} and module.base_config() == {"phase1": {}}


def test_a_score_file_becomes_a_session_by_ticker_table(module):
    assert module.score_table("m1", DATES, TICKERS) is None
    module.ML_SCORES.mkdir()
    pd.DataFrame({"date": [DATES[0], DATES[0]], "ticker": ["AAA", "BBB"], "score": [0.1, 0.2]}).to_csv(module.ML_SCORES / "m1.csv", index=False)
    table = module.score_table("m1", DATES, TICKERS)
    assert table.loc[DATES[0], "BBB"] == 0.2 and table.shape == (60, 6)


def test_cells_carry_the_extra_tables_their_universe_needs(module, monkeypatch):
    module.ML_SCORES.mkdir()
    pd.DataFrame({"date": [DATES[0]], "ticker": ["AAA"], "score": [0.1]}).to_csv(module.ML_SCORES / "m2.csv", index=False)
    cells = {"S": _cell(module), "CS": _cell(module, "crypto", "CS")}
    monkeypatch.setattr(module, "equity_cell", lambda root, base, name: cells["S"])
    monkeypatch.setattr(module, "crypto_cell", lambda root, base, name: cells["CS"])
    specs = [spec for spec in module.ALL_SPECS if module.cell_of(spec) in ("S", "CS")][:40]
    loaded = module.load_cells(specs)
    assert "e3" in cells["S"].context.panel.extras and "m2" in cells["S"].tables and set(loaded) <= {"S", "CS"}
    if "CS" in loaded:
        assert "c5" in cells["CS"].tables
    core = module.core_trend_table(cells["S"].context.panel.known)
    assert core.loc[:, ~core.columns.isin(module.CRYPTO_CORE)].isna().all().all()


def test_a_signal_needs_its_score_table_and_the_ic_clause_has_its_exemptions(module, monkeypatch):
    cell = _cell(module)
    external = next(spec for spec in module.ALL_SPECS if spec.family == "external_score")
    assert module._signal_for(external, cell) is None
    cell.context.panel.extras[external.params["table"]] = cell.context.panel.known
    monkeypatch.setattr(module, "sleeve_signal", lambda spec, panel: panel.known)
    assert module._signal_for(external, cell) is not None
    monkeypatch.setattr(module, "signal_ic_t", lambda signal, label, start, end, min_names: {"nonoverlap_t": 3.0})
    ordinary = next(spec for spec in module.ALL_SPECS if spec.id not in module.NO_IC_CLAUSE and module.cell_of(spec) == "S")
    assert module._ic_clause(ordinary, cell, cell.context.panel.known) == {"nonoverlap_t": 3.0}
    cell.label = None
    assert module._ic_clause(ordinary, cell, cell.context.panel.known) is None
    exempt = next(iter(module.NO_IC_CLAUSE))
    spec = next(spec for spec in module.ALL_SPECS if spec.id == exempt)
    assert module._ic_clause(spec, cell, cell.context.panel.known) is None and module.crypto_ic(spec, cell, None) is None


def test_the_crypto_ic_uses_the_shared_helper(module, monkeypatch):
    import evaluation.wide_context as wide

    monkeypatch.setattr(wide, "crypto_ic", lambda signal, known, start, end, min_names: {"nonoverlap_t": 2.5})
    ordinary = next(spec for spec in module.ALL_SPECS if spec.id not in module.NO_IC_CLAUSE)
    assert module.crypto_ic(ordinary, _cell(module, "crypto", "CS"), None) == {"nonoverlap_t": 2.5}


def _score_stub(monkeypatch, module, sharpe=1.0):
    cell = _cell(module)
    monkeypatch.setattr(module, "load_cells", lambda specs: {name: cell for name in ("S", "CS", "CV")})
    monkeypatch.setattr(module, "_signal_for", lambda spec, cell_: cell_.context.panel.known if spec.id != "w02" else None)
    monkeypatch.setattr(module, "live_names_per_rebalance", lambda table, every: {"median": 10.0, "minimum": 5.0})
    monkeypatch.setattr(module, "score_sleeve", lambda spec, context, **kwargs: {"sharpe": sharpe, "sharpe_first_half": 0.9, "sharpe_second_half": 1.1, "turnover": 2.0,
                                                                                  "daily": {0: pd.Series(np.cos(np.arange(60)) * 0.01, index=DATES), 1: pd.Series(0.0, index=DATES)}})
    monkeypatch.setattr(module, "_ic_clause", lambda spec, cell_, signal: {"nonoverlap_t": 3.0})
    monkeypatch.setattr(module, "crypto_ic", lambda spec, cell_, signal: {"nonoverlap_t": 2.0})
    monkeypatch.setattr(module, "assert_selection_only", lambda end: None)
    return cell


def test_scoring_runs_each_trial_once_and_reports_the_ones_without_a_table(module, monkeypatch, capsys):
    _score_stub(monkeypatch, module)
    args = SimpleNamespace(only=["w01", "w02", "w03"], force=False)
    assert module.stage_score(args) == 0
    scores = json.loads(module.SCORES.read_text(encoding="utf-8"))
    assert set(scores) == {"w01", "w03"} and "has no table yet" in capsys.readouterr().out and module.DAILY.exists()
    assert module.stage_score(args) == 0
    crypto = next(spec for spec in module.ALL_SPECS if module.cell_of(spec) == "CS")
    monkeypatch.setattr(module, "ALL_SPECS", [crypto])
    cell = _cell(module, "crypto", "CS")
    monkeypatch.setattr(module, "load_cells", lambda specs: {"CS": cell})
    monkeypatch.setattr(module, "live_names_per_rebalance", lambda table, every: {"median": 0.0, "minimum": 0.0})
    assert module.stage_score(SimpleNamespace(only=None, force=True)) == 0
    assert "ranks only 0 names" in capsys.readouterr().out and "ic" in json.loads(module.SCORES.read_text(encoding="utf-8"))[crypto.id]


def test_the_earlier_clauses_check_sharpe_live_names_and_the_ic(module, monkeypatch):
    monkeypatch.setattr(module, "passes_sharpe_clauses", lambda score: score.get("ok", True))
    good = {"live_names": {"median": 1000.0}, "ic": {"nonoverlap_t": 3.0}}
    assert module.passes_earlier_clauses("w01", "W", good) is True
    assert module.passes_earlier_clauses("w01", "W", {**good, "ok": False}) is False
    assert module.passes_earlier_clauses("w01", "W", {**good, "live_names": {"median": 0.0}}) is False
    assert module.passes_earlier_clauses("w01", "W", {**good, "ic": {"nonoverlap_t": 1.0}}) is False
    assert module.passes_earlier_clauses("w01", "W", {"live_names": {"median": 1000.0}}) is False
    exempt = next(iter(module.NO_IC_CLAUSE))
    assert module.passes_earlier_clauses(exempt, "W", {"live_names": {"median": 1000.0}}) is True
    assert module._why_failed("w01", "W", {"live_names": {"median": 0.0}}) == "live_names"
    monkeypatch.setattr(module, "passes_sharpe_clauses", lambda score: False)
    assert module._why_failed("w01", "W", good) == "sharpe"
    monkeypatch.setattr(module, "passes_sharpe_clauses", lambda score: True)
    assert module._why_failed("w01", "W", good) == "ic"
    assert module._show(None).strip() == "n/a" and module._show(1.234).strip() == "1.23"


def test_the_placebo_stage_tests_the_trials_that_reached_it(module, monkeypatch):
    cell = _cell(module)
    monkeypatch.setattr(module, "load_cells", lambda specs: {"S": cell})
    assert module.stage_placebo(SimpleNamespace(only=None, draws=3, suffix="", force=False)) == 0
    module.write_json(module.SCORES, {"w01": {"sharpe": 1.0, "live_names": {"median": 1000.0}, "ic": {"nonoverlap_t": 3.0}}, "w03": {"sharpe": 0.1}})
    monkeypatch.setattr(module, "passes_sharpe_clauses", lambda score: score["sharpe"] > 0.5)
    monkeypatch.setattr(module, "nulls_for", lambda spec: ["shuffle", "shift"])
    monkeypatch.setattr(module, "placebo_sharpes", lambda spec, context, mode, start, end, draws: [] if mode == "shift" else [0.1, 0.2, 0.3])
    monkeypatch.setattr(module, "placebo_p_value", lambda observed, sharpes: 0.04)
    assert module.stage_placebo(SimpleNamespace(only=["w01"], draws=3, suffix="_a", force=False)) == 0
    done = json.loads((module.OUT / "selection_placebos_a.json").read_text(encoding="utf-8"))
    assert done["w01"]["shuffle"]["draws"] == 3 and done["w01"]["shift"]["median"] is None and (module.OUT / "trial_ledger_a_placebos.jsonl").exists()
    assert module.stage_placebo(SimpleNamespace(only=["w01"], draws=3, suffix="_a", force=False)) == 0
    assert module.stage_placebo(SimpleNamespace(only=["nothere"], draws=3, suffix="_a", force=True)) == 0


def test_the_gate_names_survivors_failures_and_unscored_trials(module, monkeypatch, capsys):
    module.write_json(module.SCORES, {"w01": {"sharpe": 1.0, "live_names": {"median": 1000.0}, "ic": {"nonoverlap_t": 3.0}}, "w03": {"sharpe": 0.1, "live_names": {"median": 1000.0}}})
    pd.DataFrame({"w01": np.sin(np.arange(60)) * 0.01}, index=DATES).to_parquet(module.DAILY)
    module.write_json(module.OUT / "selection_placebos.json", {"w01": {"shuffle": {"p": 0.01}}})
    monkeypatch.setattr(module, "passes_sharpe_clauses", lambda score: score["sharpe"] > 0.5)
    monkeypatch.setattr(module, "selection_gate", lambda rows, p_values: {"survivors": [row["id"] for row in rows], "failed": []})
    assert module.stage_gate(SimpleNamespace()) == 0
    gate = json.loads(module.GATE.read_text(encoding="utf-8"))
    assert gate["survivors"] == ["w01"] and gate["failed_earlier_clauses"] == {"w03": "sharpe"} and "w02" in gate["unscored"]


def test_pbo_reads_the_daily_returns_of_the_registered_columns(module, monkeypatch, capsys):
    import evaluation.pbo as pbo

    frame = pd.DataFrame({name: np.sin(np.arange(60) + index) * 0.01 for index, name in enumerate(module.PBO_COLUMNS[:3])}, index=DATES)
    frame.to_parquet(module.DAILY)
    monkeypatch.setitem(module.CELLS, "S", SimpleNamespace(start=DATES[0], end=DATES[-1], universe="equity"))
    monkeypatch.setattr(pbo, "probability_of_backtest_overfitting", lambda matrix, blocks, periods_per_year: {"pbo": 0.3, "extra": 1})
    assert module.stage_pbo(SimpleNamespace()) == 0
    report = json.loads((module.OUT / "selection_pbo.json").read_text(encoding="utf-8"))
    assert report["pbo"] == 0.3 and report["num_trials"] == 3 and report["extra"] == 1


def test_the_combination_needs_an_equity_survivor_and_scores_two_methods(module, monkeypatch, capsys):
    assert module.stage_combine(SimpleNamespace()) == 0 and "no survivor" in capsys.readouterr().out
    module.write_json(module.GATE, {"survivors": ["c1"]})
    assert module.stage_combine(SimpleNamespace()) == 0 and "no equity survivor" in capsys.readouterr().out
    module.write_json(module.GATE, {"survivors": ["w01"]})
    cell = _cell(module)
    monkeypatch.setattr(module, "load_cells", lambda specs: {"S": cell})
    monkeypatch.setattr(module, "sleeve_signal", lambda spec, panel: panel.known)
    monkeypatch.setattr(module, "weights_for", lambda spec, context, signal, start, end, phase_offset: [{"EQ0": 0.1}])
    monkeypatch.setattr(module, "combine_sleeves", lambda sleeves, panel, method, settings, start, end: [{"EQ0": 0.1}])
    monkeypatch.setitem(module.CELLS, "S", SimpleNamespace(start=DATES[0], end=DATES[-1], split=DATES[30], universe="equity", name="S"))
    cell.cell = module.CELLS["S"]
    assert module.stage_combine(SimpleNamespace()) == 0
    combination = json.loads((module.OUT / "selection_combination.json").read_text(encoding="utf-8"))
    assert set(combination["results"]) == set(module.COMBINATION_IDS) and combination["equity_survivors"] == ["w01"]


def test_the_blend_averages_the_ranks_of_the_parts_it_has(module, capsys):
    assert module.stage_blend(SimpleNamespace()) == 1 and "needs two parts" in capsys.readouterr().out
    module.ML_SCORES.mkdir()
    for name, values in (("m2", [0.1, 0.9]), ("m4", [0.2, 0.8])):
        pd.DataFrame({"date": [DATES[0]] * 2, "ticker": ["AAA", "BBB"], "score": values}).to_csv(module.ML_SCORES / f"{name}.csv", index=False)
    assert module.stage_blend(SimpleNamespace()) == 0
    blend = pd.read_csv(module.ML_SCORES / "m5.csv")
    assert list(blend["ticker"]) == ["AAA", "BBB"] and blend["score"].iloc[1] > blend["score"].iloc[0]


def test_the_velocity_study_adopts_a_lock_only_when_it_cuts_the_worst_week(module, monkeypatch, capsys):
    import evaluation.premia_research as premia
    import portfolio.target_weights as target_weights

    monkeypatch.setattr(premia, "build_context", lambda root, base: SimpleNamespace(simulate=None))
    monkeypatch.setattr(target_weights, "load_weight_file", lambda path: [])
    calls = []

    def simulate(weights, start, end, max_drawdown_velocity=None, max_total_drawdown=None):
        calls.append(max_drawdown_velocity)
        scale = 1.0 if max_drawdown_velocity is None else 0.5
        return {"strategy": pd.Series(np.sin(np.arange(60)) * 0.02 * scale, index=DATES), "locked_on": None if max_drawdown_velocity is None else DATES[50]}

    monkeypatch.setattr(premia, "build_context", lambda root, base: SimpleNamespace(simulate=simulate))
    assert module.stage_vel(SimpleNamespace()) == 0
    report = json.loads((module.OUT / "r_vel1.json").read_text(encoding="utf-8"))
    assert calls[0] is None and report["adopted_k"] is None and report["decision"] == "velocity stays off, by rule"

    def never_locks(weights, start, end, max_drawdown_velocity=None, max_total_drawdown=None):
        scale = 1.0 if max_drawdown_velocity is None else 0.5
        return {"strategy": pd.Series(np.sin(np.arange(60)) * 0.02 * scale, index=DATES), "locked_on": None}

    monkeypatch.setattr(premia, "build_context", lambda root, base: SimpleNamespace(simulate=never_locks))
    assert module.stage_vel(SimpleNamespace()) == 0
    assert json.loads((module.OUT / "r_vel1.json").read_text(encoding="utf-8"))["adopted_k"] == 5


def test_the_command_dispatches_each_stage(module, monkeypatch):
    seen = []
    for name in ("score", "placebo", "gate", "pbo", "combine", "vel", "blend"):
        monkeypatch.setattr(module, f"stage_{name}", lambda args, _n=name: seen.append(_n) or 0)
    for argv in (["score", "--only", "w01", "--force"], ["placebo", "--draws", "5", "--suffix", "_b"], ["gate"], ["pbo"], ["combine"], ["vel"], ["blend"]):
        monkeypatch.setattr(sys, "argv", ["v660", *argv])
        assert module.main() == 0
    assert seen == ["score", "placebo", "gate", "pbo", "combine", "vel", "blend"]
