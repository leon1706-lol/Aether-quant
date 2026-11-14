"""scripts/lean_calibration.py's runtime (V6.6.6, #359): the live book weights, their comparison, the topology inputs, the window config, the whole
variant ladder of one window (with a Lean run and as a prediction) and the command. The harness and the Lean attribution are stubbed; the ladder,
the bucketing and the verdict are the script's own."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import ROOT, load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2020-01-02", periods=12)]


@pytest.fixture
def module(monkeypatch, tmp_path):
    calibration = load_script("lean_calibration")
    monkeypatch.setattr(calibration, "ROOT_DIR", tmp_path)
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    return calibration


def _config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def test_live_weights_are_the_formed_book_positions_over_nav(module, monkeypatch):
    import evaluation.backtest_audit as audit
    import evaluation.lean_attribution as attribution

    config = {"phase1": {"universe": {"assets": [{"ticker": "AAA", "asset_class": "equity"}, {"ticker": "BBB", "security_type": "bond"}, {"ticker": "CCC", "asset_class": "equity"}]}}}
    pnl = {DATES[0]: {"AAA": {"position": 2.0}, "BBB": {"position": 1.0}, "CCC": {"position": 0.0}}, DATES[1]: {"AAA": {"position": 2.0}, "ZZZ": {"position": 1.0}}, DATES[2]: {"AAA": {"position": 2.0}}}
    monkeypatch.setattr(attribution, "fills_from_order_events", lambda events: [SimpleNamespace(ticker="AAA")])
    monkeypatch.setattr(audit, "daily_equity_from_chart", lambda result: [(DATES[0], 1000.0), (DATES[1], 2000.0)])
    monkeypatch.setattr(attribution, "closes_for_universe", lambda config_, root, tickers: {"AAA": {DATES[0]: 10.0, DATES[1]: 20.0}, "BBB": {DATES[0]: 1.0}})
    monkeypatch.setattr(attribution, "daily_ticker_pnl", lambda fills, closes, dates: pnl)
    monkeypatch.setattr(attribution, "formed_book_by_date", lambda history, dates: {DATES[0]: frozenset({"AAA", "BBB", "CCC"}), DATES[1]: frozenset({"AAA", "ZZZ"})})
    weights = module.live_book_weights({"order_events": [], "result": {}}, [], config)
    assert weights[DATES[0]] == {"AAA": 0.02} and weights[DATES[1]] == {"AAA": 0.02} and weights[DATES[2]] == {}
    monkeypatch.setattr(audit, "daily_equity_from_chart", lambda result: [])
    assert module.live_book_weights({"order_events": [], "result": {}}, [], config)[DATES[0]] == {"AAA": 20.0}


def test_weights_are_compared_where_the_offline_book_holds_them(module):
    live = {DATES[1]: {"AAA": 0.5, "BBB": 0.5}, DATES[2]: {}}
    offline = [{"AAA": 0.5}, {}, {"AAA": 0.1}, {"AAA": 0.1}]
    result = module.compare_weights(live, DATES[:4], offline)
    assert result["weight_l1"] == pytest.approx(0.25) and result["name_overlap"] == pytest.approx(0.5) and result["live_gross"] == pytest.approx(0.5)
    assert module.compare_weights({}, DATES[:3], offline) == {"weight_l1": None, "name_overlap": None, "live_gross": None, "offline_gross": None}


def test_a_window_passes_only_with_all_three_clauses(module):
    good = {"daily_correlation": 0.6, "annual_return_gap": -0.01, "decision_agreement": 0.9}
    assert module.window_passes(good) is True
    for key, value in (("daily_correlation", 0.4), ("annual_return_gap", 0.05), ("decision_agreement", 0.5), ("daily_correlation", None)):
        assert module.window_passes({**good, key: value}) is False


def test_the_topology_inputs_are_looked_up_by_date_and_symbol(module, monkeypatch, tmp_path):
    import evaluation.model_predictions as predictions

    ml = tmp_path / "ml"
    ml.mkdir()
    for name in ("topology_model.json", "topology_feature_schema.json", "multitask_model.json"):
        (ml / name).write_text("{}", encoding="utf-8")
    (ml / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": ["a"]}), encoding="utf-8")
    seen = {}
    monkeypatch.setattr(predictions, "predict_heads", lambda frame, model, names, heads, **kwargs: {"direction": [0.5]})
    stub = types.ModuleType("topology_sizing_research")
    stub.topology_inputs_by_row = lambda frame, model, schema, probabilities, distance, temperature, min_confidence: seen.update(temperature=temperature, confidence=min_confidence) or {("2020-01-02", "AAA"): {"m": 1.0}}
    monkeypatch.setitem(sys.modules, "topology_sizing_research", stub)
    lookup = module.topology_inputs_fn_for(SimpleNamespace(frame=None), {"phase_v2": {"topology_learning": {"temperature": 0.5}}})
    assert lookup("AAA", "2020-01-02 00:00") == {"m": 1.0} and lookup("BBB", "2020-01-02") is None and seen["temperature"] == 0.5 and seen["confidence"] == 0.2


def test_the_calibrated_overrides_and_the_topology_switch(module):
    harness = SimpleNamespace(min_commission_usd_by_ticker={"AAA": 1.0}, initial_cash=1000.0, topology_inputs_fn=None, _mechanisms={"x": 1})
    assert module.calibrated_overrides(harness, phase=3)["rebalance_counter_start"] == 3
    function = lambda symbol, date: None  # noqa: E731
    module.use_topology(harness, function)
    assert harness.topology_inputs_fn is function and harness._mechanisms == {}
    harness._mechanisms["y"] = 2
    module.use_topology(harness, function)
    assert harness._mechanisms == {"y": 2}
    module.use_topology(harness, None)
    assert harness.topology_inputs_fn is None


def test_a_window_reads_the_runs_own_config_when_it_kept_one(module, monkeypatch, tmp_path):
    import evaluation.lean_attribution as attribution

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"own": True}), encoding="utf-8")
    monkeypatch.setattr(attribution, "run_config_path", lambda run_dir, root: snapshot)
    assert module.window_config({"run_dir": "backtests/x"}, {"default": True}) == {"own": True}
    monkeypatch.setattr(attribution, "run_config_path", lambda run_dir, root: None)
    assert module.window_config({"run_dir": "backtests/x"}, {"default": True}) == {"default": True}
    assert module.window_config({"run_dir": None}, {"default": True}) == {"default": True}


class FakeHarness:
    def __init__(self, splits, dataset_path, config, legacy_probability_path, gate_warmup_days):
        self.session_dates = list(DATES)
        self.min_commission_usd_by_ticker = {"AAA": 1.0}
        self.initial_cash = 100000.0
        self.frame = None
        self.topology_inputs_fn = None
        self._mechanisms = {"cached": 1}
        self.calls = []

    def v610_mechanisms(self, config, legacy=True, extra_returns=None):
        return {"mechanism": legacy, "extra": extra_returns is not None}

    def as_live(self, gate="on", log_weights=False, **overrides):
        self.calls.append((gate, dict(overrides)))
        dates = list(DATES)
        returns = [0.001 * (1 if index % 2 else -1) for index in range(len(dates))]
        log = [{"date": date, "engaged": index % 3 != 0, "locked": index == 5, "reason": "gate"} for index, date in enumerate(dates)]
        components = {"main_book": {date: value for date, value in zip(dates, returns)}} if gate == "on" else {}
        return SimpleNamespace(per_date=dates, per_date_net_return=returns, weights_log=[{"AAA": 0.5} for _ in dates], rebalance_log=log, per_date_component_returns=components)


def _window_world(module, monkeypatch, tmp_path, with_run):
    import evaluation.backtest_audit as audit
    import evaluation.lean_attribution as attribution

    stub = types.ModuleType("as_live_levers")
    stub.AsLiveHarness = FakeHarness
    monkeypatch.setitem(sys.modules, "as_live_levers", stub)
    monkeypatch.setattr(module, "topology_inputs_fn_for", lambda harness, config: (lambda symbol, date: None))
    if not with_run:
        return
    history_dir = tmp_path / "visualization" / "book_history"
    history_dir.mkdir(parents=True)
    history = history_dir / "h.jsonl"
    records = [{"date": DATES[index], "allocations": {"AAA": 1.0}} for index in (1, 4, 7)] + [{"date": DATES[9], "allocations": {}}, {"date": DATES[3], "gate_veto_reason": "thin_universe_or_zero_top_n"}]
    history.write_text("\n".join(json.dumps(record) for record in records) + "\n\n", encoding="utf-8")
    monkeypatch.setattr(attribution, "find_book_history_for_run", lambda run_dir, folder: history)
    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: {"result": {}, "order_events": []})
    daily = {date: {"main_book": 5.0 * (1 if index % 2 else -1), "legacy": 1.0, "bond_sleeve": 2.0} for index, date in enumerate(DATES)}
    monkeypatch.setattr(attribution, "attribute_run", lambda run, history_, config, root, period: {"daily_components": daily, "daily_equity": [(DATES[0], 1000.0)], "components": {"main_book": {"net": 12.345}, "legacy": {"net": 1.0}}})
    monkeypatch.setattr(module, "live_book_weights", lambda run, history_, config: {date: {"AAA": 0.4} for date in DATES})


def test_a_window_with_a_lean_run_is_laddered_and_compared(module, monkeypatch, tmp_path, capsys):
    _window_world(module, monkeypatch, tmp_path, with_run=True)
    window = {"name": "w", "run_dir": "backtests/x", "start": DATES[1], "end": DATES[-2], "splits": ("backtest",)}
    monkeypatch.setattr(module, "window_config", lambda window_, default: default)
    report = module.run_window(window, tmp_path / "d.csv", _config(), rcal2=True, extra_ladder={"custom": {"base": "calibrated", "gate": "off"}, "other": {"min_rank_confidence_spread": 0.1}})
    variants = report["variants"]
    assert {"v580", "phase", "next_open", "min_fee", "live_gates", "calibrated", "replay", "calibrated_ungated", "v610_member_pass", "v610_mechanisms", "v610", "v610_replay", "v610_ungated", "custom", "other"} <= set(variants)
    row = variants["calibrated"]
    assert "daily_correlation" in row and row["decision_agreement"] is not None and "component_compare" in row and "weight_l1" in row
    assert "component_compare" not in variants["calibrated_ungated"] and report["live_decision_counts"]["engaged"] == 3 and report["lean_components"]["main_book"] == 12.35


def test_a_prediction_window_has_no_lean_comparison(module, monkeypatch, tmp_path):
    _window_world(module, monkeypatch, tmp_path, with_run=False)
    window = {"name": "p", "run_dir": None, "start": DATES[1], "end": DATES[-2], "splits": ("backtest",)}
    monkeypatch.setattr(module, "window_config", lambda window_, default: default)
    report = module.run_window(window, tmp_path / "d.csv", _config(), rcal2=True)
    row = report["variants"]["v610"]
    assert row["offline_sharpe"] is not None and "offline_component_daily_returns" in row and "daily_correlation" not in row
    assert "offline_component_daily_returns" not in report["variants"]["calibrated_ungated"]
    empty = module.run_window({**window, "start": "2030-01-01", "end": "2030-02-01"}, tmp_path / "d.csv", _config())
    assert empty["variants"]["v580"]["offline_net_return_window"] is None and empty["variants"]["v580"]["offline_sharpe"] is None


def _fake_report(passing):
    row = {"daily_correlation": 0.9 if passing else 0.1, "annual_return_gap": 0.0, "decision_agreement": 1.0}
    return {"variants": {"calibrated": row, "v610": row}}


@pytest.mark.parametrize("argv,passing,variant,branch", [
    (["--window", "w=backtests/x@2020-01-02..2020-02-01:backtest"], True, "calibrated", "A"),
    (["--rcal2", "--components", "main_book"], False, "v610", "B"),
    (["--rcal3"], True, "v610", "A"),
])
def test_the_command_judges_every_window_with_the_ladders_verdict(module, monkeypatch, tmp_path, capsys, argv, passing, variant, branch):
    seen = []
    monkeypatch.setattr(module, "run_window", lambda window, dataset, config, components, **kwargs: seen.append((window["name"], components, kwargs["rcal2"])) or _fake_report(passing))
    out = tmp_path / "out" / "calibration.json"
    monkeypatch.setattr(sys, "argv", ["lean_calibration", "--out", str(out), *argv])
    assert module.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["verdict"]["variant"] == variant and written["verdict"]["branch"] == branch and seen


def test_the_prediction_command_writes_no_verdict_and_a_missing_window_is_an_error(module, monkeypatch, tmp_path):
    monkeypatch.setattr(module, "run_window", lambda window, dataset, config, components, **kwargs: _fake_report(True))
    out = tmp_path / "prediction.json"
    monkeypatch.setattr(sys, "argv", ["lean_calibration", "--predict", "--window", "bt=@2020-01-02..2020-02-01:backtest", "--out", str(out)])
    assert module.main() == 0 and json.loads(out.read_text(encoding="utf-8"))["verdict"] is None
    monkeypatch.setattr(sys, "argv", ["lean_calibration", "--out", str(out)])
    with pytest.raises(SystemExit):
        module.main()
    assert np is not None
