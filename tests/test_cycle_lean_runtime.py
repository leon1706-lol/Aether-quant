"""scripts/cycle_lean.py's runtime (V6.6.6, #359): the r03 weights, the blend identity, the frozen rule's rows, the three Lean configs of R-BLEND1 and R-BLEND2,
their verdicts and the command. Cells, panels, the simulator and the replays are stubbed; the file writing and the clauses are the script's own."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import ROOT, load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2015-01-02", periods=60)]


@pytest.fixture
def module(monkeypatch, tmp_path):
    cycle = load_script("cycle_lean")
    import v660_lean

    out = tmp_path / "v661"
    out.mkdir()
    (tmp_path / "run_configs").mkdir()
    for name, value in (("ROOT", tmp_path), ("OUT", out), ("WEIGHTS", out / "weights"), ("R03_FILE", out / "weights" / "r03_s.csv")):
        monkeypatch.setattr(cycle, name, value)
    monkeypatch.setattr(v660_lean, "RUN_CONFIGS", tmp_path / "run_configs")
    monkeypatch.setattr(v660_lean, "ROOT", tmp_path)
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "data_wide").mkdir()
    (tmp_path / "data_wide" / "wide_manifest.json").write_text("{}", encoding="utf-8")
    return cycle


def _cell():
    known = pd.DataFrame(100.0 + np.arange(60)[:, None] + np.arange(4)[None, :], index=DATES, columns=["AAA", "BBB", "CCC", "DDD"])
    tables = {name: known.rank(axis=1, pct=True) for name in ("w03", "w04", "w06")}
    panel = SimpleNamespace(known=known, extras=tables)
    context = SimpleNamespace(panel=panel)
    return SimpleNamespace(context=context, member=pd.DataFrame(True, index=DATES, columns=known.columns), features={"accruals_ttm": known.rank(axis=1, pct=True)})


def test_the_r03_weights_are_the_rank_mean_of_three_sleeves(module, monkeypatch, capsys):
    import evaluation.premia_research as premia
    import evaluation.wide_context as wide

    cell = _cell()
    monkeypatch.setattr(wide, "equity_cell", lambda root, base, name: cell)
    monkeypatch.setattr(premia, "weights_for", lambda spec, context, table, start, end, phase_offset: {DATES[5]: {"AAA": 0.1}})
    assert module.stage_r03() == 0 and module.R03_FILE.exists() and "r03" in cell.context.panel.extras


def test_a_blend_at_full_share_writes_the_rows_it_read(module, monkeypatch):
    import portfolio.target_weights as target_weights

    monkeypatch.setattr(target_weights, "load_weight_file", lambda path, sha: {DATES[5]: {"AAA": 0.1, target_weights.FLAT_TICKER: 0.9}, DATES[6]: {"BBB": 0.2}})
    module.WEIGHTS.mkdir(parents=True, exist_ok=True)
    report = module.blended_identity(module.WEIGHTS / "identity.csv")
    assert report["rows"] == 2 and len(report["sha256"]) == 64


def test_the_frozen_rule_runs_on_the_panel_crypto(module, monkeypatch, tmp_path):
    import portfolio.premia_signals as signals

    (tmp_path / "ml" / "forward").mkdir(parents=True)
    definition = {"id": "t3_crypto_trend_blend", "kind": "time_series", "family": "trend", "universe": ["crypto"], "rebalance_every": 20, "params": {}}
    (tmp_path / "ml" / "forward" / "candidates.json").write_text(json.dumps({"candidates": [{"id": "other"}, definition]}), encoding="utf-8")
    panel = SimpleNamespace(dates=DATES, tickers=["AAA"], closes=np.ones((60, 1)), asset_class={"AAA": "crypto"}, sessions=set(DATES))
    monkeypatch.setattr(signals, "known_closes", lambda *args: pd.DataFrame(1.0, index=DATES, columns=["AAA"]))
    monkeypatch.setattr(signals, "sleeve_signal", lambda spec, research: research.known if hasattr(research, "known") else None)
    monkeypatch.setattr(signals, "signal_to_weights", lambda signal, research, **kwargs: {DATES[3]: {"AAA": 0.2}})
    assert module.frozen_rule_rows(panel, start=DATES[0], end=DATES[-1]) == {DATES[3]: {"AAA": 0.2}}


def _make_world(module, monkeypatch, tmp_path, *, identity_ok=True, incumbent_rows=True):
    import build_wide_root
    import evaluation.generation_ledger as ledger
    import evaluation.target_weights_engine as engine
    import portfolio.target_weights as target_weights

    rows = {DATES[5]: {"AAA": 0.1}, DATES[6]: {"BBB": 0.2}}
    module.WEIGHTS.mkdir(parents=True, exist_ok=True)
    target_weights.write_weight_file(rows, module.R03_FILE)
    monkeypatch.setattr(module, "blended_identity", lambda path: (path.parent.mkdir(parents=True, exist_ok=True), path.write_text("x", encoding="utf-8"), {"rows": 2, "sha256": module.PINNED_SHA if identity_ok else "bad"})[2])
    monkeypatch.setattr(module, "frozen_rule_rows", lambda panel, start, end: {DATES[3]: {"AAA": 0.2}} if incumbent_rows else {DATES[3]: {}})
    monkeypatch.setattr(target_weights, "load_weight_file", lambda path, sha=None: rows)
    monkeypatch.setattr(build_wide_root, "wide_config", lambda base, manifest, tickers, keep_project_crypto: json.loads(json.dumps(base)))
    monkeypatch.setattr(engine, "load_market_panel", lambda root, config, data_dir: SimpleNamespace(sessions=set(DATES)))
    monkeypatch.setattr(ledger, "replay_handover", lambda sources, sessions, incumbent, successor, start, policy: {"rows": rows, "shares": {DATES[5]: {"t3": 1.0}}})
    return rows


def test_the_blend_configs_are_written_for_a_valid_identity_and_a_live_incumbent(module, monkeypatch, tmp_path, capsys):
    _make_world(module, monkeypatch, tmp_path)
    assert module.stage_make() == 0
    manifest = json.loads((module.OUT / "bl_manifest.json").read_text(encoding="utf-8"))
    assert {"v661_bl1", "v661_bl2", "shares"} <= set(manifest) and (tmp_path / "run_configs" / "v661_bl1.json").exists()


def test_a_changed_identity_or_an_empty_incumbent_stops_the_blend_configs(module, monkeypatch, tmp_path):
    _make_world(module, monkeypatch, tmp_path, identity_ok=False)
    with pytest.raises(SystemExit, match="changed the file"):
        module.stage_make()
    _make_world(module, monkeypatch, tmp_path, incumbent_rows=False)
    with pytest.raises(SystemExit, match="incumbent holds nothing"):
        module.stage_make()


def _three_world(module, monkeypatch, tmp_path, *, three_held=True):
    import build_wide_root
    import evaluation.generation_ledger as ledger
    import evaluation.premia_research as premia
    import evaluation.target_weights_engine as engine
    import evaluation.wide_context as wide
    import portfolio.financing as financing
    import portfolio.generation_blend as blend

    rows = _make_world(module, monkeypatch, tmp_path)
    monkeypatch.setattr(wide, "equity_cell", lambda root, base, name: _cell())
    monkeypatch.setattr(wide, "path_config", lambda base: {})
    monkeypatch.setattr(premia, "weights_for", lambda spec, context, table, start, end, phase_offset: {DATES[5]: {"CCC": 0.1}})
    monkeypatch.setattr(financing, "load_rate_series", lambda path: ([], []))
    monkeypatch.setattr(engine, "simulate_target_weights", lambda rows_, panel, config, **kwargs: {"strategy_excess": pd.Series(np.sin(np.arange(60)) * 0.01, index=DATES)})
    (tmp_path / "ml" / "generations").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ml" / "generations" / "policy.json").write_text(json.dumps({"glide": {"mode": "linear", "blend_every": 10}}), encoding="utf-8")
    shares = {DATES[10]: {"t3": 0.4, "r03": 0.3, "k09": 0.3}} if three_held else {DATES[10]: {"t3": 1.0, "r03": 0.0, "k09": 0.0}}
    monkeypatch.setattr(ledger, "replay_dynamic", lambda rows_by_generation, returns, sessions, **kwargs: {"rows": rows, "shares": shares, "scores": {}})
    assert build_wide_root is not None and blend is not None
    return rows


@pytest.mark.parametrize("three_held,code", [(True, 0), (False, 1)])
def test_the_three_generation_run_is_written_and_reports_whether_three_held_capital(module, monkeypatch, tmp_path, three_held, code):
    _three_world(module, monkeypatch, tmp_path, three_held=three_held)
    assert module.stage_make3() == code
    manifest = json.loads((module.OUT / "bl3_manifest.json").read_text(encoding="utf-8"))
    assert (manifest["run"]["rows_with_three_holders"] > 0) == three_held and manifest["policy"]["blend_every"] >= 10


def test_a_policy_that_is_already_dynamic_is_used_as_is(module, monkeypatch, tmp_path):
    _three_world(module, monkeypatch, tmp_path)
    (tmp_path / "ml" / "generations" / "policy.json").write_text(json.dumps({"glide": {"mode": "dynamic", "half_life_sessions": 21, "prior_sessions": 100.0, "blend_every": 7}}), encoding="utf-8")
    assert module.stage_make3() == 0
    assert json.loads((module.OUT / "bl3_manifest.json").read_text(encoding="utf-8"))["policy"]["half_life_sessions"] == 21


def test_the_blend_clauses_need_every_figure(module):
    engine = {"correlation": 0.995, "annual_gap_bps": 50.0, "fees_within_2pct": True}
    assert module.r_blend2(engine, 3)["passed"] is True
    assert module.r_blend2({**engine, "correlation": None}, 3)["passed"] is False and module.r_blend2(engine, 0)["passed"] is False
    assert module.r_blend2({**engine, "annual_gap_bps": None}, 1)["passed"] is False
    good_orders = {"equal": True, "fills_first": module.PIN_FILLS}
    assert module.r_blend1(engine, good_orders, module.PINNED_SHA)["passed"] is True
    assert module.r_blend1(engine, {**good_orders, "equal": False}, module.PINNED_SHA)["passed"] is False and module.r_blend1(engine, good_orders, "other")["passed"] is False


def test_the_verdict_stages_write_their_reports_and_exit_on_the_decision(module, monkeypatch, tmp_path):
    import v660_lean

    monkeypatch.setattr(v660_lean, "compare", lambda name, path: {"correlation": 0.995, "annual_gap_bps": 10.0, "fees_within_2pct": True})
    monkeypatch.setattr(v660_lean, "compare_orders", lambda a, b: {"equal": True, "fills_first": module.PIN_FILLS})
    module.WEIGHTS.mkdir(parents=True, exist_ok=True)
    (module.WEIGHTS / "identity.csv").write_bytes(b"x")
    assert module.stage_verdict("bl1", "bl2") == 1 and (module.OUT / "r_blend1.json").exists()
    (module.OUT / "bl3_manifest.json").write_text(json.dumps({"run": {"rows_with_three_holders": 4}}), encoding="utf-8")
    assert module.stage_verdict3("bl3") == 0 and json.loads((module.OUT / "r_blend2.json").read_text(encoding="utf-8"))["passed"] is True


def test_the_command_dispatches_each_stage(module, monkeypatch):
    seen = []
    for name in ("stage_r03", "stage_make", "stage_make3"):
        monkeypatch.setattr(module, name, lambda _n=name: seen.append(_n) or 0)
    monkeypatch.setattr(module, "stage_verdict", lambda a, b: seen.append(("verdict", a, b)) or 0)
    monkeypatch.setattr(module, "stage_verdict3", lambda a: seen.append(("verdict3", a)) or 0)
    for argv in (["r03"], ["make"], ["make3"], ["verdict", "x", "y"], ["verdict3", "z"]):
        monkeypatch.setattr(sys, "argv", ["cycle_lean", *argv])
        assert module.main() == 0
    assert seen == ["stage_r03", "stage_make", "stage_make3", ("verdict", "x", "y"), ("verdict3", "z")] and types is not None
