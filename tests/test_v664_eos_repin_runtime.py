"""scripts/v664_eos_repin.py's runtime (V6.6.6, #359): dropping the coin, the byte-for-byte reproduction of the installed weights, the five phase runs and the long run,
the description of a finished Lean run and the install of the median phase, in a temporary tree so the real config.json and weight file are never touched."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script

RULES = {"windows": {"verification": ["2023-07-01", "2024-06-30"], "long": ["2014-12-01", "2026-11-02"]}}
ROWS = {"2023-07-03": {"BTCUSD": 0.1}, "2023-07-10": {"ETHUSD": 0.2}}


def _config(*, with_eos=True, sha="x"):
    assets = [{"ticker": "BTCUSD"}, {"ticker": "ETHUSD"}] + ([{"ticker": "EOSUSD"}] if with_eos else [])
    return {"phase1": {"universe": {"assets": assets, "other": 1}, "windows": {}}, "phase_v2": {"target_weights": {"weights_sha256": sha, "weights_path": "ml/phase_weights.csv"}},
            "runtime": {"lean_window_override": {"start": "a", "end": "b"}}}


@pytest.fixture
def module(monkeypatch, tmp_path):
    repin = load_script("v664_eos_repin")
    for name, value in (("ROOT", tmp_path), ("OUT", tmp_path / "v664"), ("RUN_CONFIGS", tmp_path / "run_configs")):
        monkeypatch.setattr(repin, name, value)
    (tmp_path / "run_configs").mkdir()
    (tmp_path / "ml").mkdir()
    monkeypatch.setattr(repin, "check_rules", lambda: RULES)
    monkeypatch.setattr(repin, "load_context", lambda: SimpleNamespace())
    monkeypatch.setattr(repin, "candidate_rows", lambda definition, context, start, end, phase_index: ROWS)
    return repin


def test_dropping_the_coin_changes_only_the_asset_list(module):
    config = _config()
    dropped = module.drop_coin(config)
    assert [asset["ticker"] for asset in dropped["phase1"]["universe"]["assets"]] == ["BTCUSD", "ETHUSD"] and dropped["phase1"]["universe"]["other"] == 1 and len(config["phase1"]["universe"]["assets"]) == 3
    with pytest.raises(SystemExit, match="is not in config.json"):
        module.drop_coin(dropped)


def _installed(module, tmp_path, *, sha=None, with_eos=True):
    from portfolio.target_weights import write_weight_file

    real = write_weight_file(ROWS, tmp_path / "expected.csv")
    (tmp_path / "config.json").write_text(json.dumps(_config(with_eos=with_eos, sha=real if sha is None else sha)), encoding="utf-8")
    (tmp_path / module.INSTALLED_CANDIDATE).write_text(json.dumps({"phase_index": 4}), encoding="utf-8")
    return real


def test_the_installed_file_is_rebuilt_byte_for_byte_or_the_difference_is_reported(module, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "freeze_digest", lambda definition: {"code": {"main.py": "abc"}})
    _installed(module, tmp_path)
    assert module.stage_reproduce(SimpleNamespace()) == 0
    assert json.loads((module.OUT / "eos_reproduce.json").read_text(encoding="utf-8"))["identical"] is True
    _installed(module, tmp_path, sha="different")
    assert module.stage_reproduce(SimpleNamespace()) == 1
    _installed(module, tmp_path, with_eos=False)
    assert module.stage_reproduce(SimpleNamespace()) == 1 and "no longer lists EOSUSD" in capsys.readouterr().err


def test_the_runs_are_written_after_the_coin_leaves_the_config(module, monkeypatch, tmp_path, capsys):
    (tmp_path / "config.json").write_text(json.dumps(_config()), encoding="utf-8")
    monkeypatch.setattr(module, "make_run", lambda name, rows, window, base: {"name": name, "assets": len(base["phase1"]["universe"]["assets"])})
    assert module.stage_make(SimpleNamespace()) == 0
    runs = json.loads((module.OUT / "eos_repin_runs.json").read_text(encoding="utf-8"))
    assert len(runs) == module.PHASES + 1 and runs["v664_eos_long"]["assets"] == 2 and len(json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["phase1"]["universe"]["assets"]) == 2
    assert "config.json now lists 2 assets" in capsys.readouterr().out
    assert module.stage_make(SimpleNamespace()) == 0


def _finished_run(tmp_path, name, *, log="PythonInitializer.Shutdown(): start\n"):
    run_dir = tmp_path / "backtests" / name
    run_dir.mkdir(parents=True)
    (run_dir / "log.txt").write_text(log, encoding="utf-8")
    (tmp_path / "run_configs" / f"{name}.json").write_text(json.dumps(_config(with_eos=False)), encoding="utf-8")
    return run_dir


def _describe_world(module, monkeypatch):
    import evaluation.alpha_proof as alpha_proof

    monkeypatch.setattr(module, "strategy_series", lambda run_dir, config: pd.Series(np.sin(np.arange(30)) * 0.01, index=[day.strftime("%Y-%m-%d") for day in pd.bdate_range("2023-07-03", periods=30)]))
    monkeypatch.setattr(module, "lean_statistics", lambda run_dir: {"lean_sharpe": 1.0, "drawdown_pct": 5.0})
    monkeypatch.setattr(alpha_proof, "benchmark_daily_returns", lambda root, config, start, end: pd.DataFrame({"SPY": np.cos(np.arange(30)) * 0.01}, index=[day.strftime("%Y-%m-%d") for day in pd.bdate_range("2023-07-03", periods=30)]))
    monkeypatch.setattr(alpha_proof, "alpha_regression", lambda y, x: {"alpha_annual": 0.04, "t_hac": 2.1})
    monkeypatch.setattr(alpha_proof, "to_sessions", lambda series, index: series)
    monkeypatch.setattr(alpha_proof, "sharpe", lambda values, annualization: 0.9)


def test_a_finished_run_is_described_with_its_completion_and_lock_state(module, monkeypatch, tmp_path):
    _describe_world(module, monkeypatch)
    good = module.describe(_finished_run(tmp_path, "v664_eos_p0"))
    assert good["complete"] is True and good["locked"] is False and good["alpha_t"] == 2.1 and good["strategy_sharpe"] == 0.9 and good["run"] == "v664_eos_p0"
    bad = module.describe(_finished_run(tmp_path, "v664_eos_p1", log="Runtime Error\nkill_switch tripped\n"))
    assert bad["complete"] is False and bad["locked"] is True


def _install_world(module, monkeypatch, tmp_path, *, complete=True, weights_ok=True):
    (tmp_path / "ml" / "evaluation" / "v650").mkdir(parents=True, exist_ok=True)
    weights = tmp_path / "ml" / "phase_weights.csv"
    weights.write_text("date,ticker,weight\n", encoding="utf-8")
    sha = hashlib.sha256(weights.read_bytes()).hexdigest() if weights_ok else "stale"
    names = [f"v664_eos_p{phase}" for phase in range(module.PHASES)] + ["v664_eos_long"]
    for name in names:
        (tmp_path / "run_configs" / f"{name}.json").write_text(json.dumps(_config(with_eos=False, sha=sha)), encoding="utf-8")
    old = {f"p{phase}": {"lean_sharpe": 1.0, "strategy_sharpe": 0.5 + phase * 0.1, "drawdown_pct": 4.0} for phase in range(module.PHASES)}
    (tmp_path / "ml" / "evaluation" / "v650" / "r_lean19.json").write_text(json.dumps({"detail": {module.NAME: {"phases": old}}}), encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps(_config()), encoding="utf-8")
    monkeypatch.setattr(module, "describe", lambda run_dir: {"run": run_dir.name, "complete": complete or run_dir.name != "v664_eos_p1", "strategy_sharpe": 0.4 + 0.1 * (int(run_dir.name[-1]) if run_dir.name[-1].isdigit() else 0),
                                                              "lean_sharpe": 1.0, "drawdown_pct": 3.0})
    lines = [f"LEAN_DONE {name} backtests/{name}" for name in names]
    status = tmp_path / "status.txt"
    status.write_text("\n".join(lines) + "\nnoise\n", encoding="utf-8")
    return status


def test_the_median_phase_is_installed_beside_the_old_pin(module, monkeypatch, tmp_path, capsys):
    status = _install_world(module, monkeypatch, tmp_path)
    assert module.stage_install(SimpleNamespace(status=str(status))) == 0
    record = json.loads((module.OUT / "eos_repin.json").read_text(encoding="utf-8"))
    candidate = json.loads((tmp_path / module.INSTALLED_CANDIDATE).read_text(encoding="utf-8"))
    assert record["median_phase"] == "p2" and candidate["pinned_run"] == "v664_eos_p2" and (tmp_path / module.INSTALLED_WEIGHTS).exists()
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["runtime"]["lean_window_override"] is None and (tmp_path / "ml" / "evaluation" / "readme_lean_run.json").exists()
    assert record["median_strategy_sharpe_with_eos"] == pytest.approx(0.7)


def test_an_install_with_missing_unfinished_or_stale_runs_changes_nothing(module, monkeypatch, tmp_path, capsys):
    status = _install_world(module, monkeypatch, tmp_path)
    status.write_text("LEAN_DONE v664_eos_p0 backtests/v664_eos_p0\n", encoding="utf-8")
    assert module.stage_install(SimpleNamespace(status=str(status))) == 1 and "missing runs" in capsys.readouterr().err
    status = _install_world(module, monkeypatch, tmp_path, complete=False)
    assert module.stage_install(SimpleNamespace(status=str(status))) == 1 and "did not finish" in capsys.readouterr().err
    status = _install_world(module, monkeypatch, tmp_path, weights_ok=False)
    assert module.stage_install(SimpleNamespace(status=str(status))) == 1 and "is not the file the run froze" in capsys.readouterr().err
    assert not (tmp_path / module.INSTALLED_WEIGHTS).exists()


def test_the_command_dispatches_each_stage(module, monkeypatch):
    seen = []
    for name in ("stage_reproduce", "stage_make"):
        monkeypatch.setattr(module, name, lambda args, _n=name: seen.append(_n) or 0)
    monkeypatch.setattr(module, "stage_install", lambda args: seen.append(("install", args.status)) or 0)
    for argv in (["reproduce"], ["make"], ["install", "--status", "s.txt"]):
        assert module.main(argv) == 0
    assert seen == ["stage_reproduce", "stage_make", ("install", "s.txt")]
