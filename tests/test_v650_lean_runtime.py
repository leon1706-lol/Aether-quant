"""scripts/v650_lean.py's runtime (V6.6.6, #359): the candidate and its weight files, the freeze, the verification and pool run lists, the R-LEAN19 judgement
over finished runs, and the command, with the context, the signals and the Lean results stubbed."""

from __future__ import annotations

import hashlib
import json
import sys
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2023-01-02", periods=40)]
RULES = {"windows": {"selection_lean": ["2020-01-01", "2020-12-31"], "verification": ["2023-07-01", "2024-06-30"], "long": ["2014-12-01", "2026-11-02"], "pre2013": ["2000-01-01", "2012-12-31"]}}


@pytest.fixture
def module(monkeypatch, tmp_path):
    lean = load_script("v650_lean")
    out = tmp_path / "v650"
    for name in ("weights", "run_configs"):
        (out / name).mkdir(parents=True)
    for name, value in (("OUT", out), ("FREEZE", out / "freeze.json"), ("LEDGER", out / "trial_ledger.jsonl"), ("GATE", out / "selection_gate.json"), ("ROOT", tmp_path),
                        ("WEIGHTS", out / "weights"), ("RUN_CONFIGS", out / "run_configs")):
        monkeypatch.setattr(lean, name, value)
    monkeypatch.setattr(lean, "check_rules", lambda: RULES)
    monkeypatch.setattr(lean, "target_path_config", lambda base, weights_path, weights_sha256, window: {"phase_v2": {"cash_sweep": {"enabled": True}}, "weights": weights_path})
    monkeypatch.setattr(lean, "write_weight_file", lambda rows, path: hashlib.sha256(str(len(rows)).encode()).hexdigest())
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"cash_sweep": {"enabled": True}}}), encoding="utf-8")
    monkeypatch.setitem(lean.SPECS, "w01", lean.ALL_SPECS[0])
    monkeypatch.setitem(lean.SPECS, "w02", lean.ALL_SPECS[1])
    return lean


def _context():
    known = pd.DataFrame(100.0 + np.arange(40)[:, None] + np.arange(3)[None, :], index=DATES, columns=["AAA", "BBB", "BTCUSD"])
    return SimpleNamespace(panel=SimpleNamespace(known=known, asset_class={"BTCUSD": "crypto"}), settings=None)


def _stub_signals(module, monkeypatch):
    monkeypatch.setattr(module, "sleeve_signal", lambda spec, panel: panel.known)
    monkeypatch.setattr(module, "null_signal", lambda signal, mode, seed, asset_class: signal)
    monkeypatch.setattr(module, "weights_for", lambda spec, context, signal, start, end, phase_offset: {"2023-07-03": {"AAA": 0.1}})
    monkeypatch.setattr(module, "combine_sleeves", lambda sleeves, panel, method, settings, start, end: {"2023-07-03": {"AAA": 0.2}})
    monkeypatch.setattr(module, "load_context", _context)


def _survivors(module, names):
    module.write_json(module.GATE, {"survivors": names})


def test_the_candidate_is_a_lone_survivor_or_the_better_combination(module):
    with pytest.raises(SystemExit, match="no survivor"):
        module.candidate_definition()
    _survivors(module, ["w01"])
    assert module.candidate_definition() == {"survivors": ["w01"], "method": None}
    _survivors(module, ["w01", "w02"])
    with pytest.raises(SystemExit, match="combine"):
        module.candidate_definition()
    module.write_json(module.OUT / "selection_combination.json", {"results": {"t6_inverse_vol": {"sharpe": 0.5}, "t6_hrp": {"sharpe": None}}})
    assert module.candidate_definition() == {"survivors": ["w01", "w02"], "method": "inverse_vol", "chosen": "t6_inverse_vol"}
    module.write_json(module.OUT / "selection_combination.json", {"results": {"t6_inverse_vol": {"sharpe": 0.5}, "t6_hrp": {"sharpe": 0.9}}})
    assert module.candidate_definition()["method"] == "hrp"


def test_candidate_rows_blend_sleeves_and_can_remove_their_skill(module, monkeypatch):
    _stub_signals(module, monkeypatch)
    context = _context()
    monkeypatch.setattr(module, "phase_offsets", lambda every, count: [0, 1, 2])
    monkeypatch.setattr(module, "nulls_for", lambda spec: ["time_shift"])
    one = {"survivors": ["w01"], "method": None}
    assert module.candidate_rows(one, context, start="a", end="b", phase_index=4, null_mode="time_shift", seed=1) == {"2023-07-03": {"AAA": 0.1}}
    both = {"survivors": ["w01", "w02"], "method": "hrp"}
    assert module.candidate_rows(both, context, start="a", end="b", phase_index=0, null_mode="asset_block")["2023-07-03"] == {"AAA": 0.2}


def test_a_run_gets_a_weight_file_a_frozen_config_and_optionally_a_data_root(module):
    summary = module.make_run("v650_x", {"d": {}}, ("2020-01-01", "2020-12-31"), {}, data_root="data_pre2013", sweep=False)
    config = json.loads((module.RUN_CONFIGS / "v650_x.json").read_text(encoding="utf-8"))
    assert summary["rows"] == 1 and config["phase_v2"]["cash_sweep"]["enabled"] is False and (module.RUN_CONFIGS / "v650_x.dataroot").read_text(encoding="utf-8").strip() == "data_pre2013"
    assert module.make_run("v650_y", {}, ("a", "b"), {})["name"] == "v650_y" and module._base() == {"phase_v2": {"cash_sweep": {"enabled": True}}}


def test_the_selection_run_and_the_freeze(module, monkeypatch, capsys):
    _stub_signals(module, monkeypatch)
    _survivors(module, ["w01"])
    assert module.stage_g2(SimpleNamespace()) == 0 and (module.RUN_CONFIGS / "v650_g2.json").exists()
    monkeypatch.setattr(module, "freeze_digest", lambda definition: {"candidate": definition, "code": {"a.py": "x"}})
    vault = types.ModuleType("vault_record")
    vault.record = lambda name, paths, values: {"ok": True, "name": name}
    monkeypatch.setitem(sys.modules, "vault_record", vault)
    assert module.stage_freeze(SimpleNamespace()) == 0 and module.FREEZE.exists()
    vault.record = lambda name, paths, values: {"ok": False}
    assert module.stage_freeze(SimpleNamespace()) == 1


def test_the_digest_names_every_file_of_the_code_it_freezes(module, tmp_path):
    for relative in ("portfolio/premia_signals.py", "portfolio/target_weights.py", "portfolio/financing.py", "evaluation/target_weights_engine.py", "evaluation/premia_research.py",
                     "scripts/v650_trials.py", "scripts/v650_lean.py", "main.py"):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(relative, encoding="utf-8")
    digest = module.freeze_digest({"survivors": ["w01"], "method": None})
    assert len(digest["code"]) == 8 and digest["candidate"]["survivors"] == ["w01"]


def test_a_changed_file_or_a_missing_freeze_stops_the_stages(module, monkeypatch):
    with pytest.raises(SystemExit, match="no freeze.json"):
        module.check_freeze()
    module.write_json(module.FREEZE, {"candidate": {"survivors": ["w01"]}, "code": {"a.py": "old"}})
    monkeypatch.setattr(module, "freeze_digest", lambda definition: {"code": {"a.py": "new"}})
    with pytest.raises(SystemExit, match="code changed"):
        module.check_freeze()
    monkeypatch.setattr(module, "freeze_digest", lambda definition: {"code": {"a.py": "old"}})
    assert module.check_freeze() == {"survivors": ["w01"]}


def test_the_pre2013_context_reads_its_manifest(module, tmp_path, monkeypatch):
    (tmp_path / "data_pre2013").mkdir()
    (tmp_path / "data_pre2013" / "pre2013_manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "universe_for_root", lambda base, manifest: {"universe": 1})
    monkeypatch.setattr(module, "build_context", lambda root, config, data_dir: ("context", data_dir))
    assert module.pre2013_context({}) == (("context", "data_pre2013"), {"universe": 1})


def _freeze(module, monkeypatch, survivors):
    module.write_json(module.FREEZE, {"candidate": {"survivors": survivors, "method": None}, "code": {}})
    monkeypatch.setattr(module, "freeze_digest", lambda definition: {"code": {}})
    _survivors(module, survivors)


def test_verification_writes_every_run_the_rule_asks_for(module, monkeypatch):
    _stub_signals(module, monkeypatch)
    _freeze(module, monkeypatch, ["w01"])
    monkeypatch.setattr(module, "phase_offsets", lambda every, count: [0])
    monkeypatch.setattr(module, "nulls_for", lambda spec: ["asset_block"])
    monkeypatch.setattr(module, "pre2013_context", lambda base: (_context(), {"universe": 1}))
    monkeypatch.setattr(module, "E4_DRAWS", 2)
    monkeypatch.setattr(module, "E5_DRAWS", 2)
    monkeypatch.setitem(module.SPECS, "w01", SimpleNamespace(rebalance_every=20, universe=("equity",)))
    assert module.stage_verify(SimpleNamespace()) == 0
    runs = json.loads((module.OUT / "verify_runs.json").read_text(encoding="utf-8"))
    assert {"v650_e2", "v650_e5", "v650_e5_null_00"} <= set(runs) and "v650_e1_p4" in runs and "v650_e4_null_b_01" in runs
    assert (module.OUT / "verify_run_list.txt").exists() and (module.RUN_CONFIGS / "v650_e5.dataroot").exists()


def test_a_candidate_of_crypto_sleeves_only_has_no_pre2013_runs(module, monkeypatch):
    _stub_signals(module, monkeypatch)
    _freeze(module, monkeypatch, ["w01", "w02"])
    module.write_json(module.FREEZE, {"candidate": {"survivors": ["w01", "w02"], "method": "hrp"}, "code": {}})
    monkeypatch.setattr(module, "phase_offsets", lambda every, count: [0])
    monkeypatch.setattr(module, "nulls_for", lambda spec: ["asset_block"])
    monkeypatch.setattr(module, "pre2013_context", lambda base: (_context(), {}))
    monkeypatch.setattr(module, "E4_DRAWS", 1)
    monkeypatch.setattr(module, "E5_DRAWS", 1)
    monkeypatch.setitem(module.SPECS, "w01", SimpleNamespace(rebalance_every=20, universe=("crypto",)))
    monkeypatch.setitem(module.SPECS, "w02", SimpleNamespace(rebalance_every=20, universe=("crypto",)))
    assert module.stage_verify(SimpleNamespace()) == 0
    runs = json.loads((module.OUT / "verify_runs.json").read_text(encoding="utf-8"))
    assert "v650_e5" not in runs
    monkeypatch.setitem(module.SPECS, "w02", SimpleNamespace(rebalance_every=20, universe=("equity",)))
    monkeypatch.setitem(module.SPECS, "w01", SimpleNamespace(rebalance_every=20, universe=("equity",)))
    assert module.stage_verify(SimpleNamespace()) == 0 and "v650_e5" in json.loads((module.OUT / "verify_runs.json").read_text(encoding="utf-8"))


def test_the_pool_runs_every_survivor_alone_and_the_combination(module, monkeypatch):
    _stub_signals(module, monkeypatch)
    _freeze(module, monkeypatch, ["w01", "w02"])
    monkeypatch.setattr(module, "phase_offsets", lambda every, count: [0])
    monkeypatch.setattr(module, "candidate_definition", lambda: {"survivors": ["w01", "w02"], "method": "hrp", "chosen": "t6_hrp"})
    assert module.stage_pool(SimpleNamespace()) == 0
    runs = json.loads((module.OUT / "pool_runs.json").read_text(encoding="utf-8"))
    assert "v650_pool_t6_hrp_long" in runs and "v650_pool_w01_p4" in runs
    monkeypatch.setattr(module, "candidate_definition", lambda: {"survivors": ["w01"], "method": None})
    assert module.stage_pool(SimpleNamespace()) == 0


def _lean_run(root, name, config, *, complete=True, sharpe="1.2"):
    run_dir = root / "backtests" / name
    run_dir.mkdir(parents=True)
    result = {"statistics": {"Sharpe Ratio": sharpe, "Annual Standard Deviation": "0.08", "Drawdown": "6.5%", "Net Profit": "12%", "Total Orders": "1,000", "Total Fees": "$50.00"}, "charts": {}}
    (run_dir / "1.json").write_text(json.dumps(result), encoding="utf-8")
    (run_dir / "log.txt").write_text(("PythonInitializer.Shutdown(): start\n" if complete else "Runtime Error\n"), encoding="utf-8")
    (root / "runs").mkdir(exist_ok=True)
    return run_dir


def test_lean_statistics_read_the_result_even_when_numbers_are_formatted_or_missing(module, tmp_path):
    run_dir = _lean_run(tmp_path, "run1", {})
    stats = module.lean_statistics(run_dir)
    assert stats["lean_sharpe"] == 1.2 and stats["drawdown_pct"] == 6.5 and stats["orders"] == 1000.0 and stats["fees"] == 50.0
    other = tmp_path / "backtests" / "run2"
    other.mkdir()
    (other / "2.json").write_text(json.dumps({"Statistics": {"Sharpe Ratio": "n/a"}}), encoding="utf-8")
    assert module.lean_statistics(other)["lean_sharpe"] is None


def test_a_strategy_series_is_the_nav_return_without_a_sweep_or_the_ex_tbill_return(module, tmp_path, monkeypatch):
    import evaluation.alpha_proof as alpha_proof

    run_dir = tmp_path / "backtests" / "run3"
    run_dir.mkdir(parents=True)
    stamps = [pd.Timestamp(day, tz="UTC").timestamp() for day in DATES[:5]]
    result = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": [[stamp, 1000.0 + 10 * index] for index, stamp in enumerate(stamps)]}}}}}
    (run_dir / "3.json").write_text(json.dumps(result), encoding="utf-8")
    assert len(module.strategy_series(run_dir, {"phase_v2": {"cash_sweep": {"enabled": False}}})) == 4
    assert len(module.strategy_series(run_dir, {"phase_v2": {"cash_sweep": {"enabled": True}}}, data_dir="data_pre2013")) == 4
    monkeypatch.setattr(alpha_proof, "strategy_daily_returns", lambda run, config, root: pd.Series([0.01, 0.02]))
    assert list(module.strategy_series(run_dir, {"phase_v2": {"cash_sweep": {"enabled": True}}})) == [0.01, 0.02]


def test_the_judgement_pools_phases_and_installs_only_what_clears_every_clause(module, tmp_path, monkeypatch):
    import evaluation.alpha_proof as alpha_proof

    status_lines = []
    for phase in range(5):
        name = f"v650_pool_w01_p{phase}"
        _lean_run(tmp_path, name, {})
        (module.RUN_CONFIGS / f"{name}.json").write_text(json.dumps({"phase_v2": {"cash_sweep": {"enabled": True}}}), encoding="utf-8")
        status_lines.append(f"LEAN_DONE {name} backtests/{name}")
    long_name = "v650_pool_w01_long"
    _lean_run(tmp_path, long_name, {})
    (module.RUN_CONFIGS / f"{long_name}.json").write_text(json.dumps({"phase_v2": {"cash_sweep": {"enabled": True}}}), encoding="utf-8")
    status_lines += [f"LEAN_DONE {long_name} backtests/{long_name}", "LEAN_DONE other backtests/other", "garbage", "LEAN_DONE ignored backtests/x"]
    status = tmp_path / "status.txt"
    status.write_text("\n".join(status_lines), encoding="utf-8")
    monkeypatch.setattr(module, "strategy_series", lambda run_dir, config, data_dir="data": pd.Series(np.sin(np.arange(40)) * 0.01, index=DATES))
    monkeypatch.setattr(alpha_proof, "benchmark_daily_returns", lambda root, config, start, end: pd.DataFrame({"SPY": np.cos(np.arange(40)) * 0.01}, index=DATES))
    monkeypatch.setattr(alpha_proof, "alpha_regression", lambda y, x: {"alpha_annual": 0.04, "t_hac": 2.5, "betas": {"SPY": 0.1}})
    monkeypatch.setattr(alpha_proof, "to_sessions", lambda series, index: series)
    monkeypatch.setattr(alpha_proof, "sharpe", lambda values, annualization: 1.4)
    module.write_json(module.OUT / "ablation_table.json", {"BT11 baseline": {"lean_sharpe": 0.1, "strategy_sharpe": 0.2}, "BT12 flag off": {}, "BT13 x": {"lean_sharpe": 0.3, "strategy_sharpe": 0.4, "annual_std": 0.08, "drawdown_pct": 5.0, "complete": True}})
    assert module.stage_judge(SimpleNamespace(status=str(status))) == 0
    report = json.loads((module.OUT / "r_lean19.json").read_text(encoding="utf-8"))
    assert report["verdict"]["best"] == "w01" and report["pool"]["w01"]["complete"] is True and "long_strategy_sharpe" in report["pool"]["w01"] and "BT13 x" in report["pool"]


def test_the_edge_rule_needs_every_clause(module):
    good = module.judge_edge([1.2, 1.1, 1.3, 1.0, 1.4], 3.5, 0.97, [0.1] * 40, [0.2] * 40, 1.2, 0.5, 0.02)
    assert good["verified"] is True and good["e1_median"] == 1.2
    bad = module.judge_edge([None, 1.0], None, None, [2.0] * 40, [2.0] * 3, 1.0, None, None)
    assert bad["verified"] is False and bad["e1_median"] is None and bad["beaten_by_null_a"] == 40
    unknown = module.judge_edge([1.0], 3.0, 0.96, [], [], None, 0.1, 0.1)
    assert unknown["beaten_by_null_a"] is None and unknown["clauses"]["E4"] is False


def test_the_fallback_installs_nothing_unless_the_best_clears_every_clause(module):
    baseline = {"lean_sharpe": 0.5, "strategy_sharpe": 0.5}
    winner = {"lean_sharpe": 0.9, "strategy_sharpe": 0.9, "annual_std": 0.08, "drawdown_pct": 8.0, "complete": True, "long_strategy_sharpe": 0.3}
    assert module.judge_fallback({"a": winner, "b": {**winner, "strategy_sharpe": None}}, baseline)["install"] == "a"
    assert module.judge_fallback({"a": {**winner, "drawdown_pct": 30.0}}, baseline)["install"] is None
    assert module.judge_fallback({}, baseline) == {"best": None, "install": None, "clauses": {}}


@pytest.mark.parametrize("argv,name", [(["g2"], "g2"), (["freeze"], "freeze"), (["verify"], "verify"), (["pool"], "pool"), (["judge", "--status", "s.txt"], "judge")])
def test_the_command_dispatches_each_stage(module, monkeypatch, argv, name):
    seen = []
    monkeypatch.setattr(module, f"stage_{name}", lambda args: seen.append(name) or 0)
    monkeypatch.setattr(sys, "argv", ["v650_lean", *argv])
    assert module.main() == 0 and seen == [name]
