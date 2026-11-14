"""scripts/v660_verdict.py (V6.6.6): R-CRYPTO1, the per-trial verdict table and the price-break check, on stand-in cells.

The research path (cells, signals, the engine) has its own tests; here every heavy call is a stand-in, and the test checks
what this script does with the answers: which windows it reads, what it writes, and how it summarises each track."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script, run_script

SESSIONS = pd.date_range("2018-01-01", "2026-10-30", freq="7D").strftime("%Y-%m-%d")


@dataclasses.dataclass(frozen=True)
class _Config:
    equity_fee_bps: float = 1.0
    equity_min_fee_usd: float = 1.0
    slippage_bps_by_class: dict = dataclasses.field(default_factory=dict)
    financing_enabled: bool = True


def _series(seed):
    return pd.Series(np.random.default_rng(seed).normal(0.001, 0.01, len(SESSIONS)), index=SESSIONS)


def _context():
    known = pd.DataFrame(1.0, index=SESSIONS, columns=["BTCUSD", "DEADUSD"])
    return SimpleNamespace(
        panel=SimpleNamespace(known=known), settings="settings", market="market", config=_Config(), sweep={}, rf_dates=[], rf_rates=[],
        carry=lambda ticker, date: 0.0, sessions_for=lambda spec: list(SESSIONS),
        simulate=lambda weights, start, end: {"strategy_excess": _series(1), "strategy": _series(2), "no_bar_exits": [1], "gross": pd.Series([0.5, 0.7])},
    )


def _cell(universe="crypto", name="CS"):
    context = _context()
    return SimpleNamespace(context=context, member=context.panel.known.astype(bool), cell=SimpleNamespace(start="2018-01-01", split="2022-01-01", end="2023-06-30", universe=universe, name=name))


@pytest.fixture
def verdict(tmp_path, monkeypatch):
    module = load_script("v660_verdict")
    out = tmp_path / "v660"
    out.mkdir()
    (out / "rules.json").write_text("{}", encoding="utf-8")
    root = tmp_path / "root"
    (root / "data_crypto_wide").mkdir(parents=True)
    (root / "data_crypto_wide" / "crypto_wide_manifest.json").write_text(json.dumps({"coins": {"a": {"ticker": "BTCUSD", "last": "2026-10-30"}, "b": {"ticker": "DEADUSD", "last": "2022-05-01"}}}), encoding="utf-8")
    (root / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "FREEZE", out / "freeze_crypto1.json")
    monkeypatch.setattr(module, "check_rules", lambda: {})
    monkeypatch.setattr(module, "write_freeze", lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"))
    monkeypatch.setattr(module, "freeze_digest_of", lambda path: "digest")
    monkeypatch.setattr(module, "crypto_cell", lambda root, base, name, **kwargs: _cell(name=name))
    monkeypatch.setattr(module, "sleeve_signal", lambda spec, panel: panel.known.copy())
    monkeypatch.setattr(module, "signal_to_weights", lambda table, panel, **kwargs: {"2020-01-01": {ticker: 0.1 for ticker in table.columns if table[ticker].notna().any()}})
    monkeypatch.setattr(module, "simulate_target_weights", lambda weights, market, config, **kwargs: {"strategy_excess": _series(3), "fee": kwargs["fee_fn"]("crypto", 100.0, "d", config) + kwargs["fee_fn"]("equity", 100.0, "d", config)})
    monkeypatch.setattr(module, "benchmark_daily_returns", lambda root, config, tickers, **kwargs: pd.DataFrame({"SPY": _series(4)}))
    monkeypatch.setattr(module, "to_sessions", lambda series, index: series)
    monkeypatch.setattr(module, "alpha_regression", lambda series, bench: {"alpha_annual": 0.02, "t_hac": 1.5, "n": len(series)})
    return module, out


def test_crypto1_freezes_once_reads_side_b_and_writes_the_report(verdict):
    module, out = verdict
    report = module.report_crypto1()
    assert (out / "freeze_crypto1.json").exists() and report["rule"] == "R-CRYPTO1" and report["of_which_stopped_trading"] == 1
    assert report["no_bar_exits"] == 1 and report["alpha"]["n"] == len(SESSIONS) and report["control_same_rule_same_path"]["side"] == "A"
    assert report["sharpe_on_binance_fees_not_gating"] is not None
    assert json.loads((out / "r_crypto1.json").read_text(encoding="utf-8"))["names_ever_held"] == 2
    module.report_crypto1()  # the freeze exists now: it is not rewritten


def test_the_track_table_summarises_each_track(verdict, monkeypatch, capsys):
    module, out = verdict
    specs = [SimpleNamespace(id="c1", track="C"), SimpleNamespace(id="w1", track="W"), SimpleNamespace(id="w2", track="W"), SimpleNamespace(id="unscored", track="W")]
    (out / "selection_scores.json").write_text(json.dumps({"c1": {"sharpe": 0.4, "ic": {"mean_ic": 0.01}}, "w1": {"sharpe": 0.3}, "w2": {"sharpe": 0.2}}), encoding="utf-8")
    daily = pd.DataFrame({"c1": _series(5), "w1": _series(6), "w2": _series(7)})
    factors = pd.DataFrame({"MKT": _series(8)})
    monkeypatch.setattr(module.pd, "read_parquet", lambda path: factors if "factors" in str(path) else daily)
    monkeypatch.setattr(module, "ALL_SPECS", specs)
    monkeypatch.setattr(module, "load_cells", lambda specs: {"CS": _cell("crypto", "CS"), "S": _cell("equity", "S")})
    monkeypatch.setattr(module, "cell_of", lambda spec: "CS" if spec.track == "C" else "S")
    monkeypatch.setattr(module, "weights_for", lambda spec, context, signal, **kwargs: {})
    alphas = iter([{"alpha_annual": 0.01, "t_hac": 2.0, "n": 9}, {"alpha_annual": 0.0, "t_hac": None, "n": 9}, {"alpha_annual": 0.03, "t_hac": 0.5, "n": 9}])
    monkeypatch.setattr(module, "alpha_of", lambda series, data_dir: next(alphas))
    import evaluation.factor_spanning as spanning

    monkeypatch.setattr(spanning, "factor_alpha", lambda series, factors: {"alpha": 0.0})
    report = module.report_track_table()
    assert set(report["trials"]) == {"c1", "w1", "w2"} and "known_factor_alpha" in report["trials"]["w1"] and "known_factor_alpha" not in report["trials"]["c1"]
    assert report["by_track"]["W"]["best_by_alpha_t"] == "w2" and report["by_track"]["W"]["trials"] == 2
    assert report["trials"]["w1"]["excluded_alpha_sharpe_95"] is None and report["by_track"]["C"]["median_excluded"] is not None
    assert json.loads((out / "verdict_table.json").read_text(encoding="utf-8"))["note"].startswith("Selection cell only")
    monkeypatch.setattr(module, "alpha_of", lambda series, data_dir: {"t_hac": None})
    assert module.report_track_table()["by_track"]["W"]["median_excluded"] is None
    assert "c1" in capsys.readouterr().out


def test_breaks_rescore_without_the_spliced_coins(verdict, monkeypatch):
    module, out = verdict
    (out / "crypto_price_breaks.json").write_text(json.dumps({"breaks": {"DEADUSD": {}}}), encoding="utf-8")
    (out / "selection_scores.json").write_text(json.dumps({"c1": {"sharpe": 0.4, "sharpe_first_half": 0.3, "sharpe_second_half": 0.5}}), encoding="utf-8")
    (out / "r_crypto1.json").write_text(json.dumps({"sharpe": -0.06}), encoding="utf-8")
    monkeypatch.setattr(module, "ALL_SPECS", [SimpleNamespace(id="c1", track="C"), SimpleNamespace(id="w1", track="W")])
    monkeypatch.setattr(module, "load_cells", lambda specs: {"CS": _cell()})
    import evaluation.premia_research as research
    import v660_research

    monkeypatch.setattr(v660_research, "_signal_for", lambda spec, cell: cell.context.panel.known.copy())
    seen = []
    monkeypatch.setattr(research, "score_sleeve", lambda spec, context, signal, **kwargs: seen.append(signal) or {"daily": [], "sharpe": 0.1, "sharpe_first_half": 0.0, "sharpe_second_half": 0.2})
    report = module.report_breaks()
    assert report["coins"] == ["DEADUSD"] and report["trials"]["c1"]["without_those_coins"] == [0.1, 0.0, 0.2] and seen[0]["DEADUSD"].isna().all()
    assert report["r_crypto1_recorded"] == -0.06 and (out / "crypto_breaks_effect.json").exists()


def test_main_dispatches_each_stage(verdict, monkeypatch, capsys):
    module, _out = verdict
    monkeypatch.setattr(module, "report_crypto1", lambda: {"stage": "crypto1"})
    monkeypatch.setattr(module, "report_breaks", lambda: {"stage": "breaks"})
    monkeypatch.setattr(module, "report_track_table", lambda: {"by_track": {"stage": "report"}})
    for stage in ("crypto1", "breaks", "report"):
        monkeypatch.setattr(module.sys, "argv", ["x", stage])
        assert module.main() == 0
    out = capsys.readouterr().out
    assert all(f'"stage": "{stage}"' in out for stage in ("crypto1", "breaks", "report"))


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("v660_verdict", ["--help"], monkeypatch) == 0
    assert "crypto1" in capsys.readouterr().out
