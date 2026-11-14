"""scripts/lean_smoke/main_option_scenarios.py against stand-ins for Lean and for main.py (V6.6.6, #359): the four scenarios (scale, all43, arb, assign), the wait for a
first decision, a step that raises, and the end-of-run reports."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import types
from types import SimpleNamespace

import pytest

from script_loader import SCRIPTS, load_script

ROWS = [{"underlying_price": 190.0, "expiry": "2014-07-19"}, {"underlying_price": 190.0, "expiry": "2014-08-16"}]


@dataclasses.dataclass
class Decision:
    contracts: int = 5
    margin_requirement: float = 1000.0
    strategy_name: str = "bull_call_spread"

    def to_dict(self):
        return {"strategy_name": self.strategy_name}


class Base:
    def __init__(self):
        self.lines, self.liquidated, self.sweeps, self.ends = [], [], 0, 0
        self.is_warming_up = False
        self.symbols = ["SPY", "AAPL_OPT"]
        self.asset_lookup = {"SPY": {"security_type": "equity"}, "AAPL_OPT": {"security_type": "option", "underlying_ticker": "AAPL"}}
        self.latest_options_chains_payload = {"AAPL": list(ROWS)}
        self.option_positions_by_symbol = {}
        self.Portfolio = SimpleNamespace(TotalMarginUsed=0.0, TotalPortfolioValue=100000.0, Cash=500.0, Values=[SimpleNamespace(Symbol="AAPL_OPT", Invested=True), SimpleNamespace(Symbol="SPY", Invested=False)])
        self.Transactions = SimpleNamespace(OrdersCount=0)
        self.Time = SimpleNamespace(date=lambda: "2014-06-10")
        self.limit_orders_enabled = True
        self.raise_label = None
        self.latest_assignment_risk_by_symbol = {"AAPL_OPT": 0.4}
        self.options_arbitrage_detector_enabled = True
        self.options_arbitrage_min_mispricing_bps = 5.0
        self.options_risk_tier_preference = "vega_budget"
        for name in ("options_target_delta_at_full_confidence", "options_max_vega_budget_pct_of_equity", "options_short_leg_delta_offset", "options_margin_target_utilization",
                     "options_margin_max_utilization", "options_margin_pct_of_underlying_value", "options_margin_min_pct_of_underlying_value", "options_risk_free_rate"):
            setattr(self, name, 0.1)
        self.options_max_positions_per_underlying = 1
        self.options_auto_close_days_before_expiry = 3
        self.CurrentSlice = None
        self.base_events = []

    def Debug(self, message):
        self.lines.append(message)

    def on_data(self, slice):
        pass

    def on_order_event(self, order_event):
        self.base_events.append(order_event)

    def on_end_of_algorithm(self):
        self.ends += 1

    def _apply_option_multi_leg_order(self, symbol, key, decision, weight, price, is_long, label):
        if label == self.raise_label:
            raise RuntimeError(f"{label} refused")
        self.Transactions.OrdersCount += 1
        self.Portfolio.TotalMarginUsed += 100.0
        self.option_positions_by_symbol.setdefault(key, []).append({"kind": "multi_leg", "strategy_name": decision.strategy_name, "contracts": decision.contracts})
        return "submitted"

    def _liquidate_option_record(self, key, record):
        self.liquidated.append(key)
        self.option_positions_by_symbol[key].remove(record)

    def _apply_option_assignment_risk_sweep(self):
        self.sweeps += 1


class _Symbol:
    def __init__(self, kind):
        self.SecurityType = kind


@pytest.fixture
def smoke(monkeypatch):
    lean = types.ModuleType("AlgorithmImports")
    lean.SecurityType = SimpleNamespace(Option="Option")
    aq_main = types.ModuleType("aq_main")
    aq_main.AetherQuantAlgorithm = Base
    monkeypatch.setitem(sys.modules, "AlgorithmImports", lean)
    monkeypatch.setitem(sys.modules, "aq_main", aq_main)
    module = load_script("lean_smoke/main_option_scenarios")
    monkeypatch.setattr(module, "build_vertical_spread_position_sizing", lambda *args, **kwargs: Decision())
    monkeypatch.setattr(module, "build_multi_leg_position_sizing", lambda *args, **kwargs: Decision(strategy_name="multi"))
    monkeypatch.setattr(module, "build_margin_position_sizing", lambda *args, **kwargs: Decision(strategy_name="margin"))
    return module


def _messages(algorithm):
    return [json.loads(line[len("SMOKE_JSON "):]) for line in algorithm.lines]


def test_the_scenario_comes_from_the_file_next_to_the_script_or_defaults_to_scale(smoke, monkeypatch, tmp_path):
    assert smoke.SCENARIO == "scale"
    (tmp_path / "scenario.txt").write_text("arb\n", encoding="utf-8")
    copy = tmp_path / "main_option_scenarios.py"
    copy.write_text((SCRIPTS / "lean_smoke" / "main_option_scenarios.py").read_text(encoding="utf-8"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("scenarios_with_file", copy)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SCENARIO == "arb"


def test_no_step_runs_in_warmup_or_without_a_chain(smoke):
    warming = smoke.OptionScenario()
    warming.is_warming_up = True
    warming.on_data(None)
    empty = smoke.OptionScenario()
    empty.latest_options_chains_payload = {}
    empty.on_data(None)
    assert warming.lines == [] and empty.lines == [] and warming.limit_orders_enabled is True


def test_the_scale_scenario_runs_its_steps_once_and_reports_a_refused_one(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "SCENARIO", "scale")
    algorithm = smoke.OptionScenario()
    algorithm.raise_label = "scale_down"
    algorithm.on_data(None)
    algorithm.on_data(None)
    kinds = [(message["kind"], message.get("step")) for message in _messages(algorithm)]
    assert ("step", "enter") in kinds and ("step_raised", "scale_down") in kinds and kinds[-1][0] == "final" and kinds.count(("step", "enter")) == 1
    assert algorithm.limit_orders_enabled is False and algorithm.options_max_positions_per_underlying == 2


def test_the_scale_scenario_reports_a_missing_straddle_or_strangle(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "SCENARIO", "scale")
    monkeypatch.setattr(smoke, "build_multi_leg_position_sizing", lambda *args, **kwargs: None)
    algorithm = smoke.OptionScenario()
    algorithm.on_data(None)
    results = {message["step"]: message["result"] for message in _messages(algorithm) if message["kind"] == "step"}
    assert results["second_position_under_cap_2"] == "no straddle decision" and results["third_position_at_cap"] == "no strangle decision"


def test_it_waits_for_the_first_bar_a_decision_builds_on(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "SCENARIO", "scale")
    monkeypatch.setattr(smoke, "build_vertical_spread_position_sizing", lambda *args, **kwargs: None)
    algorithm = smoke.OptionScenario()
    for _ in range(5):
        algorithm.on_data(None)
    waits = [message for message in _messages(algorithm) if message["kind"] == "no_decision_yet"]
    assert len(waits) == 3 and algorithm._steps_done is False


def _registry(monkeypatch, smoke):
    registry = {"vega_one": SimpleNamespace(risk_tier="vega_budget"), "margin_one": SimpleNamespace(risk_tier="margin"), "later": SimpleNamespace(risk_tier="margin"),
                "broken": SimpleNamespace(risk_tier="vega_budget"), "plain": SimpleNamespace(risk_tier="margin")}
    monkeypatch.setattr(smoke, "MULTI_LEG_STRATEGY_REGISTRY", registry)
    return registry


def test_the_all_structures_scenario_builds_each_one_and_keeps_trying_the_rest(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "SCENARIO", "all43")
    _registry(monkeypatch, smoke)
    state = {"later_ready": False}

    def margin(name, side, confidence, rows, price, nav):
        if name == "later" and not state["later_ready"]:
            return None
        if name == "plain":
            return SimpleNamespace(strategy_name="plain")
        return Decision(strategy_name=name)

    def vega(name, side, confidence, rows, nav, max_vega_budget_pct_of_equity):
        if name == "broken":
            raise ValueError("no legs here")
        return Decision(strategy_name=name)

    monkeypatch.setattr(smoke, "build_margin_position_sizing", margin)
    monkeypatch.setattr(smoke, "build_multi_leg_position_sizing", vega)
    algorithm = smoke.OptionScenario()
    algorithm.on_data(None)
    assert algorithm._remaining == ["later"] and set(algorithm._built) == {"vega_one", "margin_one", "broken", "plain"} and algorithm._built["broken"]["raised"].startswith("ValueError")
    assert algorithm.liquidated and algorithm.option_positions_by_symbol["AAPL_OPT"] == []
    state["later_ready"] = True
    algorithm.on_data(None)
    assert algorithm._remaining == []
    algorithm.on_data(None)
    algorithm.on_end_of_algorithm()
    kinds = [message["kind"] for message in _messages(algorithm)]
    assert "coverage" in kinds and kinds[-1] == "end" and algorithm.ends == 1


def test_the_arbitrage_scenario_routes_with_and_without_the_detector(smoke, monkeypatch):
    import risk.asset_class_router as router

    monkeypatch.setattr(smoke, "SCENARIO", "arb")
    monkeypatch.setattr(smoke, "MULTI_LEG_STRATEGY_REGISTRY", {"box_spread": SimpleNamespace(risk_tier="unreachable_arbitrage"), "straddle": SimpleNamespace(risk_tier="vega_budget")})
    seen = []

    def route(names, side, confidence, rows, nav, price, regime, preference, flag, **kwargs):
        seen.append(kwargs["arbitrage_detector_enabled"])
        return (Decision(strategy_name="box_spread"), {"mispricing_bps": 9.0}) if kwargs["arbitrage_detector_enabled"] else None

    monkeypatch.setattr(router, "route_multi_leg_option_sizing", route)
    algorithm = smoke.OptionScenario()
    algorithm._build_options_chains_payload = lambda current_slice: {"AAPL": []}
    algorithm.on_data(None)
    messages = _messages(algorithm)
    results = {message["step"]: message["result"] for message in messages if message["kind"] == "step"}
    assert seen == [True, False] and results["detector_on_as_configured"]["routed"] == "box_spread" and results["detector_off_for_contrast"] == {"routed": None}
    assert messages[-1] == {"scenario": "arb", "kind": "payload", "built": True, "underlyings": ["AAPL"]}
    bare = smoke.OptionScenario()
    bare._steps_done = False
    bare.on_data(None)
    assert _messages(bare)[-1]["built"] is False and _messages(bare)[-1]["underlyings"] is None


def test_the_assignment_scenario_enters_sweeps_and_holds_to_expiry(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "SCENARIO", "assign")
    algorithm = smoke.OptionScenario()
    algorithm.option_positions_by_symbol = {}
    algorithm.on_data(None)
    messages = _messages(algorithm)
    assert algorithm.sweeps == 1 and algorithm.options_auto_close_days_before_expiry == -1 and messages[-1]["kind"] == "held_to_expiry"
    monkeypatch.setattr(smoke, "build_multi_leg_position_sizing", lambda *args, **kwargs: None)
    empty = smoke.OptionScenario()
    # the first probe needs a decision too, so reach the scenario directly
    empty._scenario_assign("AAPL_OPT", "AAPL_OPT", ROWS, 1000.0)
    assert {message["result"] for message in _messages(empty) if message["kind"] == "step" and message["step"] == "enter_short_call_structure"} == {"no decision"}


def test_a_non_all43_end_reports_only_the_end_and_a_base_without_the_hook_is_fine(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "SCENARIO", "scale")
    algorithm = smoke.OptionScenario()
    algorithm.on_end_of_algorithm()
    assert [message["kind"] for message in _messages(algorithm)] == ["end"] and _messages(algorithm)[0]["holdings"] == ["AAPL_OPT"] and algorithm.ends == 1
    monkeypatch.delattr(Base, "on_end_of_algorithm")
    plain = smoke.OptionScenario()
    plain.on_end_of_algorithm()
    assert plain.ends == 0 and len(plain.lines) == 1


def test_option_fills_are_reported_and_other_fills_only_passed_on(smoke):
    algorithm = smoke.OptionScenario()
    algorithm.on_order_event(SimpleNamespace(Symbol=_Symbol("Option"), Status="Filled", FillQuantity=1, FillPrice=2.5, Message="ok"))
    algorithm.on_order_event(SimpleNamespace(Symbol=_Symbol("Equity")))
    assert len(algorithm.base_events) == 2 and [message["kind"] for message in _messages(algorithm)] == ["option_event"]
