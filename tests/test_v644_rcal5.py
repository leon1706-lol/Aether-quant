"""scripts/v644_rcal5.py (V6.6.6): the gate-replica audit per window and R-CAL5's score, with the calibration path stubbed."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from script_loader import ROOT, fake_module, load_script


def test_main_book_tickers_leave_out_the_sweep_and_bonds():
    module = load_script("v644_rcal5")
    config = {"phase_v2": {"cash_sweep": {"ticker": "bil"}}, "phase1": {"universe": {"assets": [
        {"ticker": "SPY", "security_type": "equity"}, {"ticker": "BIL", "security_type": "equity"}, {"ticker": "AGG", "asset_class": "bond", "security_type": "equity"},
        {"ticker": "btcusd", "security_type": "crypto"}, {"ticker": "EURUSD", "security_type": "forex"},
    ]}}}
    assert module.main_book_tickers(config) == {"SPY", "BTCUSD"}
    assert module.main_book_tickers({"phase_v2": {}, "phase1": config["phase1"]}) == {"SPY", "BTCUSD"}


def test_the_verdict_mirrors_r_cal4():
    module = load_script("v644_rcal5")
    base = {"bt5": 0.80, "bt7": 0.92, "bt8": 0.95}
    assert module.verdict("c", base, {"bt5": 0.91, "bt7": 0.93, "bt8": 0.96})["branch"] == "A"
    assert module.verdict("c", base, {"bt5": None, "bt7": 0.93, "bt8": 0.96})["adopted"] is False


@pytest.fixture
def stubs(tmp_path, monkeypatch):
    history = tmp_path / "book.jsonl"
    history.write_text(json.dumps({"date": "2024-01-02"}) + "\n\n", encoding="utf-8")

    class Harness:
        def __init__(self, splits, dataset_path, config):
            self.session_dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
            self.min_commission_usd_by_ticker, self.initial_cash = {}, 1e5
            self._mechanisms = {"x": 1}

        def v610_mechanisms(self, config, legacy):
            return {"legacy": legacy}

        def as_live(self, **kwargs):
            return SimpleNamespace(per_date=["2023-12-29", "2024-01-02"], weights_log=[{}, {"SPY": 0.1}])

    fake_module(monkeypatch, "as_live_levers", AsLiveHarness=Harness)
    window = {"name": "bt5", "run_dir": "backtests/x", "start": "2024-01-01", "end": "2024-01-31", "splits": ("backtest",)}
    fake_module(
        monkeypatch, "lean_calibration", parse_window=lambda text: window, window_config=lambda window, config: config,
        live_decisions=lambda history, start, end: {"2024-01-02": {}}, rebalance_phase=lambda first, sessions, every: 0,
        topology_inputs_fn_for=lambda harness, config: None, ANALYZER_INCLUDE=(), BOOK_COMPONENTS="c",
        run_window=lambda window, dataset, config, components, extra_ladder, rcal2: {"variants": {"v610_mechanisms": {"daily_correlation": 0.8}, **{
            name: {"daily_correlation": 0.9, "disagreement": []} for name in extra_ladder}}},
    )
    import evaluation.backtest_audit as audit
    import evaluation.gate_replica_audit as replica
    import evaluation.lean_attribution as attribution

    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: {"order_events": []})
    monkeypatch.setattr(attribution, "find_book_history_for_run", lambda run_dir, folder: history)
    monkeypatch.setattr(attribution, "fills_from_order_events", lambda events: [])
    monkeypatch.setattr(replica, "offline_trades", lambda dates, weights: [{"date": dates[0]}])
    monkeypatch.setattr(replica, "lean_trades", lambda fills, tickers: [{"date": "2024-01-02"}, {"date": "2025-01-01"}])
    monkeypatch.setattr(replica, "trade_profile", lambda trades, rebalances, sessions, lag_sessions=0: {"trades": len(trades)})
    monkeypatch.setattr(replica, "compare_profiles", lambda lean, offline: {"rows": {"a": 1}, "ranked": ["a"], "median_sessions_between_trades": 3})
    return window


def test_the_audit_compares_lean_and_offline_trades_in_the_window(stubs):
    module = load_script("v644_rcal5")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    result = module.audit_window("bt5=...", ROOT / "x.csv", config)
    assert result["lean"] == {"trades": 1} and result["offline"] == {"trades": 1} and result["live_rebalance_dates"] == 1


def test_main_audits_and_scores(stubs, tmp_path, monkeypatch, capsys):
    module = load_script("v644_rcal5")
    monkeypatch.setattr(module, "OUT_DIR", tmp_path)
    monkeypatch.setattr(module.sys, "argv", ["x", "audit", "--windows", "bt5"])
    assert module.main() == 0 and (tmp_path / "gate_replica_audit.json").exists()
    monkeypatch.setattr(module.sys, "argv", ["x", "score", "--candidate", 'c1={"k": 1}'])
    assert module.main() == 0
    result = json.loads((tmp_path / "r_cal5_result.json").read_text(encoding="utf-8"))
    assert result["results"]["c1"]["adopted"] is True and "disagreement" not in result["rows"]["bt5"]["c1"] and "R-CAL5:" in capsys.readouterr().out
