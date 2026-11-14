"""evaluation/research_round.py's stages (V6.6.6, #359): score, placebo, gate, PBO, hold and report, with the sleeve simulation stubbed.
The orchestration runs for real: what is written, what is skipped, what is refused."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import evaluation.research_round as rr
from evaluation.research_cells import CELLS
from test_research_round import DATES, TICKERS, _Cell, _payload, _table


def _spec(tmp_path, *, cell="S", trials=None, **extra):
    payload = {**_payload(tmp_path), "cell": cell, **extra}
    if trials is not None:
        payload["trials"] = trials
    path = tmp_path / "round.json"
    rr.write_rules(payload, path)
    return rr.load_round(path)


def _score(sharpe=1.0):
    daily = pd.Series(np.random.default_rng(1).normal(0.0005, 0.01, len(DATES)), index=DATES)
    return {"sharpe": sharpe, "sharpe_first_half": 0.9, "sharpe_second_half": 1.1, "turnover": 2.0, "daily": {0: daily, 1: daily}}


@pytest.fixture
def stubbed(monkeypatch):
    calls = []
    monkeypatch.setattr(rr, "score_sleeve", lambda sleeve, context, **kwargs: calls.append(("score", sleeve.id)) or _score())
    monkeypatch.setattr(rr, "live_names_per_rebalance", lambda signal, every: {"median": 200.0})
    return calls


def _cell(spec):
    cell = _Cell()
    cell.cell = CELLS[spec.cell]
    cell.context.config = SimpleNamespace()
    return cell


def test_the_json_helpers_create_their_folder(tmp_path):
    rr._write_json(tmp_path / "deep" / "x.json", {"a": 1})
    assert rr._read_json(tmp_path / "deep" / "x.json", None) == {"a": 1}


def test_a_fama_macbeth_trial_needs_all_its_features(tmp_path, monkeypatch):
    import evaluation.walk_forward_linear as linear

    spec = _spec(tmp_path, trials={"fm": {"kind": "pooled", "builder": "fama_macbeth_ridge", "signs": {"f": 1.0}, "kappa": 3, "ridge": 2.0}, "fm2": {"kind": "pooled", "builder": "fama_macbeth_ridge", "signs": {"f": 1.0, "missing": -1.0}}})
    cell = _cell(spec)
    seen = {}
    monkeypatch.setattr(linear, "fama_macbeth_ridge", lambda features, label, signs, start, kappa, ridge: seen.update(kappa=kappa, ridge=ridge) or features["f"])
    table = rr.trial_table(spec, "fm", cell, {}, score_dir=tmp_path)
    assert seen == {"kappa": 3, "ridge": 2.0} and table[TICKERS[0]].isna().all()
    with pytest.raises(KeyError, match="not in this cell"):
        rr.trial_table(spec, "fm2", cell, {}, score_dir=tmp_path)


def test_spec_top_k_and_a_composite_whose_part_did_not_run(tmp_path):
    spec = _spec(tmp_path, trials={"a": {"kind": "pooled", "top_k": 5, "recipe": {"op": "single", "parts": ["f"], "signs": {"f": 1.0}}}, "b": {"kind": "pooled", "recipe": {"op": "rank_mean", "parts": ["a", "ghost"]}}, "ghost": {"kind": "pooled", "score_file": "ghost"}})
    assert rr.spec_of(spec, "a", ("tech",)).params == {"table": "a", "top_k": 5}
    assert rr.trial_table(spec, "b", _cell(spec), {}, score_dir=tmp_path) is None
    assert rr.universe_for(spec, "a")[0]


def test_a_min_weight_band_replaces_the_context_config():
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class Config:
        min_weight_change: float = 0.0

    @dataclasses.dataclass(frozen=True)
    class Context:
        config: Config

    context = Context(Config())
    assert rr._trial_context(context, {}) is context
    assert rr._trial_context(context, {"min_weight_change": 0.02}).config.min_weight_change == 0.02


def test_the_selection_cell_is_free_only(tmp_path, monkeypatch):
    import evaluation.wide_context as wide

    spec = _spec(tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    seen = []
    monkeypatch.setattr(wide, "equity_cell", lambda root, base, name, with_info: seen.append(("equity", name, with_info)) or "cell")
    monkeypatch.setattr(wide, "crypto_cell", lambda root, base, name: seen.append(("crypto", name)) or "cell")
    assert rr._load_selection_cell(spec, tmp_path) == "cell" and seen == [("equity", "S", True)]
    crypto = _spec(tmp_path / "c", cell="CS")
    assert rr._load_selection_cell(crypto, tmp_path) == "cell" and seen[-1] == ("crypto", "CS")
    held = rr.RoundSpec(**{**spec.__dict__, "cell": "V3"})
    with pytest.raises(PermissionError, match="free cells only"):
        rr._load_selection_cell(held, tmp_path)


def test_scoring_runs_each_trial_once_and_saves_as_it_goes(tmp_path, stubbed):
    spec = _spec(tmp_path, trials={"a1": {"kind": "pooled", "rebalance_every": 20, "recipe": {"op": "single", "parts": ["f"], "signs": {"f": -1.0}}, "gate": None},
                                   "a2": {"kind": "pooled", "score_file": "nothere"}, "a3": {"kind": "pooled", "recipe": {"op": "single", "parts": ["f"], "signs": {"f": 1.0}}}})
    cell = _cell(spec)
    lines = []
    ic = lambda signal, label, start, end, min_names: {"nonoverlap_t": 2.5, "mean_ic": 0.03}  # noqa: E731
    scores = rr.stage_score(spec, cell=cell, score_dir=tmp_path, only=("a1", "a2"), ic_fn=ic, emit=lines.append)
    assert set(scores) == {"a1"} and any("a2: no table yet" in line for line in lines) and "a3" not in scores
    assert scores["a1"]["ic"]["nonoverlap_t"] == 2.5 and scores["a1"]["live_names"]["median"] == 200.0
    again = rr.stage_score(spec, cell=cell, score_dir=tmp_path, ic_fn=ic, emit=lines.append)
    assert set(again) == {"a1", "a3"} and [c for c in stubbed if c[0] == "score"].count(("score", "a1")) == 1
    forced = rr.stage_score(spec, cell=cell, score_dir=tmp_path, force=True, ic_fn=ic, emit=lines.append)
    assert set(forced) == {"a1", "a3"} and [c for c in stubbed if c[1] == "a1"].count(("score", "a1")) == 2
    assert len(rr.read_ledger(spec.ledger)) >= 2 and (rr._paths(spec)["daily"]).exists()


def test_scoring_reads_the_ic_by_family_and_honours_no_ic_and_a_missing_label(tmp_path, stubbed, monkeypatch):
    import evaluation.wide_context as wide

    trials = {"a1": {"kind": "pooled", "recipe": {"op": "single", "parts": ["f"], "signs": {"f": 1.0}}}, "a2": {"kind": "pooled", "recipe": {"op": "single", "parts": ["f"], "signs": {"f": 1.0}}}}
    spec = _spec(tmp_path, trials=trials, no_ic_clause=["a2"])
    cell = _cell(spec)
    scores = rr.stage_score(spec, cell=cell, score_dir=tmp_path, ic_fn=lambda *a, **k: {"nonoverlap_t": 1.0}, emit=lambda line: None)
    assert scores["a2"]["ic"] is None and scores["a1"]["ic"] == {"nonoverlap_t": 1.0}
    cell.label = None
    nolabel = _spec(tmp_path / "n", trials=trials)
    assert rr.stage_score(nolabel, cell=cell, score_dir=tmp_path, ic_fn=lambda *a, **k: 1 / 0, emit=lambda line: None)["a1"]["ic"] is None
    crypto = _spec(tmp_path / "c", cell="CS", trials=trials)
    monkeypatch.setattr(wide, "crypto_ic", lambda signal, known, start, end, min_names: {"nonoverlap_t": 3.0})
    cell.cell = CELLS["CS"]
    assert rr.stage_score(crypto, cell=cell, score_dir=tmp_path, emit=lambda line: None)["a1"]["ic"] == {"nonoverlap_t": 3.0}


def test_scoring_defaults_to_the_wide_context_ic(tmp_path, stubbed, monkeypatch):
    import evaluation.wide_context as wide

    spec = _spec(tmp_path, trials={"a1": {"kind": "pooled", "recipe": {"op": "single", "parts": ["f"], "signs": {"f": 1.0}}}})
    monkeypatch.setattr(wide, "signal_ic_t", lambda signal, label, start, end, min_names: {"nonoverlap_t": 4.0})
    assert rr.stage_score(spec, cell=_cell(spec), score_dir=tmp_path, emit=lambda line: None)["a1"]["ic"] == {"nonoverlap_t": 4.0}


def test_placebos_run_only_for_trials_that_clear_the_earlier_clauses(tmp_path, monkeypatch):
    spec = _spec(tmp_path, trials={"a1": {"kind": "pooled", "recipe": {"op": "single", "parts": ["f"], "signs": {"f": 1.0}}}, "a2": {"kind": "pooled", "score_file": "nothere"}})
    cell = _cell(spec)
    lines = []
    assert rr.stage_placebo(spec, cell=cell, score_dir=tmp_path, emit=lines.append) == {} and "none" in lines[0]
    good = {"sharpe": 1.0, "sharpe_first_half": 1.0, "sharpe_second_half": 1.0, "live_names": {"median": 500.0}, "ic": {"nonoverlap_t": 3.0}}
    monkeypatch.setattr(rr, "passes_sharpe_clauses", lambda score: True)
    rr._write_json(rr._paths(spec)["scores"], {"a1": good})
    monkeypatch.setattr(rr, "nulls_for", lambda sleeve: ["shuffle", "shift"])
    monkeypatch.setattr(rr, "placebo_sharpes", lambda sleeve, context, mode, start, end, draws: [] if mode == "shift" else [0.1, 0.2, 0.3])
    monkeypatch.setattr(rr, "placebo_p_value", lambda observed, sharpes: 0.04)
    done = rr.stage_placebo(spec, cell=cell, score_dir=tmp_path, draws=3, emit=lines.append)
    assert done["a1"]["shuffle"]["draws"] == 3 and done["a1"]["shift"]["median"] is None
    monkeypatch.setattr(rr, "placebo_sharpes", lambda *a, **k: 1 / 0)
    assert rr.stage_placebo(spec, cell=cell, score_dir=tmp_path, emit=lines.append) == done
    with pytest.raises(ZeroDivisionError):
        rr.stage_placebo(spec, cell=cell, score_dir=tmp_path, force=True, emit=lines.append)


def test_the_gate_counts_unrun_trials_and_pbo_reads_prior_rounds(tmp_path, monkeypatch):
    spec = _spec(tmp_path, prior_daily=["prior.parquet"], prior_columns=["old"], pbo_blocks=4)
    pd.DataFrame({"old": np.random.default_rng(1).normal(size=len(DATES))}, index=DATES).to_parquet(tmp_path / "prior.parquet")
    monkeypatch.setattr(rr, "selection_gate", lambda rows, p_values: {"survivors": [], "failed": []})
    gate = rr.stage_gate(spec)
    assert gate["unscored"] == ["a1", "a2", "a3"] and gate["counted_without_a_score"] == ["a1", "a2", "a3"]
    pd.DataFrame({name: np.random.default_rng(i).normal(size=len(DATES)) for i, name in enumerate(["a1", "a2"])}, index=DATES).to_parquet(rr._paths(spec)["daily"])
    monkeypatch.setattr(rr.CELLS["S"].__class__, "start", property(lambda self: DATES[0]), raising=False) if False else None
    import evaluation.pbo as pbo

    monkeypatch.setattr(pbo, "probability_of_backtest_overfitting", lambda matrix, blocks, periods_per_year: {"pbo": 0.3})
    monkeypatch.setitem(rr.CELLS, "S", SimpleNamespace(start=DATES[0], end=DATES[-1], universe="equity"))
    report = rr.stage_pbo(spec, root=tmp_path)
    assert report["pbo"] == 0.3 and report["num_trials"] == 3 and report["absent"] == ["a3"] and rr._paths(spec)["pbo"].exists()


def test_a_report_names_survivors_the_pbo_stop_and_the_alpha_figures(tmp_path):
    spec = _spec(tmp_path, disclosures=["one"])
    paths = rr._paths(spec)
    assert rr.stage_report(spec)["stopped_at"].startswith("zero trials survived")
    series = pd.Series(np.random.default_rng(2).normal(0.001, 0.01, 500))
    pd.DataFrame({"a1": series}).to_parquet(paths["daily"])
    rr._write_json(paths["scores"], {"a1": {"sharpe": 1.0, "ic": {"nonoverlap_t": 2.0, "mean_ic": 0.1}}, "a2": {"sharpe": 0.5}})
    rr._write_json(paths["gate"], {"survivors": ["a1"], "unscored": []})
    stopped = rr.stage_report(spec, alpha_fn=lambda s: {"t_hac": 2.5, "alpha_annual": 0.04})
    assert "PBO None" in stopped["stopped_at"] and stopped["trials"]["a1"]["excluded_alpha_sharpe_95"] is not None and stopped["trials"]["a2"].get("alpha_t") is None
    rr._write_json(paths["pbo"], {"pbo": 0.2})
    passed = rr.stage_report(spec, alpha_fn=lambda s: {"t_hac": None})
    assert passed["verdict"] == "survivors reach the freeze" and passed["trials"]["a1"]["alpha_t"] is None and passed["disclosures"] == ["one"]


class _HoldCell:
    def __init__(self, simulate):
        self.cell = SimpleNamespace(start=DATES[0], end=DATES[-1])
        self.features = {"f": _table(1)}
        self.tables = {}
        self.member = pd.DataFrame(True, index=DATES, columns=TICKERS)
        self.sectors = {}
        self.label = _table(3)
        self.context = SimpleNamespace(panel=SimpleNamespace(known=_table(2), extras={}), config=SimpleNamespace(), simulate=simulate, sessions_for=lambda sleeve: 252)


def test_the_one_read_of_the_holdouts_records_before_it_opens_anything(tmp_path, monkeypatch):
    import evaluation.premia_research as premia
    import evaluation.wide_context as wide

    trials = {"a1": {"kind": "pooled", "recipe": {"op": "single", "parts": ["f"], "signs": {"f": 1.0}}}, "a2": {"kind": "pooled", "recipe": {"op": "rank_mean", "parts": ["a1", "x"]}}, "a3": {"kind": "pooled", "score_file": "nothere"}}
    spec = _spec(tmp_path, trials=trials)
    freeze, digest = tmp_path / "freeze_a1.json", "d1"
    monkeypatch.setattr(rr, "freeze_digest_of", lambda path: digest)
    series = pd.Series(np.random.default_rng(3).normal(0.001, 0.01, 200))
    monkeypatch.setattr(premia, "weights_for", lambda sleeve, context, table, start, end, phase_offset: "weights")
    monkeypatch.setattr(premia, "annual_sharpe", lambda s, sessions: 0.7)
    cells = {name: _HoldCell(lambda weights, start, end: {"strategy_excess": series}) for name in ("V1", "V2", "V3")}
    ledger = tmp_path / "holdouts.jsonl"
    with pytest.raises(PermissionError, match="not this candidate's"):
        rr.stage_hold(spec, "a1", root=tmp_path, freeze_path=tmp_path / "other.json", digest=digest, holdout_ledger=ledger, created_at="t", score_dir=tmp_path)
    verdict = rr.stage_hold(spec, "a1", root=tmp_path, freeze_path=freeze, digest=digest, holdout_ledger=ledger, created_at="2026-11-13T00:00:00+00:00", score_dir=tmp_path,
                            read_cell=lambda name: cells[name], alpha_fn=lambda s: {"t_hac": 2.4})
    assert verdict["passed"] is True and rr.holdouts_spent(ledger) == ["V1", "V2", "V3"] and (spec.out_dir / "r_hold1_a1.json").exists()
    assert rr._is_part_of(spec, "a2", "a1") and not rr._is_part_of(spec, "a1", "a2")
    missing = rr.stage_hold(spec, "a3", root=tmp_path, freeze_path=tmp_path / "freeze_a3.json", digest=digest, holdout_ledger=tmp_path / "second.jsonl", created_at="t",
                            score_dir=tmp_path, read_cell=lambda name: cells[name])
    assert missing["reads"]["V1"]["reason"] == "no table on this cell" and missing["passed"] is False
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    opened = []
    monkeypatch.setattr(wide, "equity_cell", lambda root, base, name, freeze_path, freeze_digest: opened.append(name) or cells[name])
    rr.stage_hold(spec, "a1", root=tmp_path, freeze_path=freeze, digest=digest, holdout_ledger=tmp_path / "third.jsonl", created_at="t", score_dir=tmp_path)
    assert opened == ["V1", "V2", "V3"]
    crypto = _spec(tmp_path / "c", cell="CS", trials=trials)
    monkeypatch.setattr(wide, "crypto_cell", lambda root, base, name, freeze_path, freeze_digest: cells["V1"])
    result = rr.stage_hold(crypto, "a1", root=tmp_path, freeze_path=freeze, digest=digest, holdout_ledger=tmp_path / "fourth.jsonl", created_at="t", score_dir=tmp_path)
    assert result["rule"] == "R-HOLD1 (crypto)" and json.loads((crypto.out_dir / "r_hold1_a1.json").read_text(encoding="utf-8"))["rule"] == "R-HOLD1 (crypto)"
