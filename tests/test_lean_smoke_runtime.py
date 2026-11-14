"""The Lean smoke algorithms of scripts/lean_smoke/ and scripts/lean_teardown_smoke/ against a stand-in for Lean's `AlgorithmImports` (V6.6.6, #359): the futures
margin calls, the teardown algorithm, the structure walk with its detectors, and the three config writers' commands."""

from __future__ import annotations

import datetime
import json
import sys
import types
from types import SimpleNamespace

import pytest

from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY
from script_loader import ROOT, load_script, run_script


class QCAlgorithm:
    def __init__(self):
        self.lines, self.orders, self.holdings, self.liquidated = [], [], [], 0
        self.time = datetime.datetime(2014, 6, 6, 10, 0)
        self.is_warming_up = False
        self.securities = {}
        self.portfolio = SimpleNamespace(total_margin_used=5.0, invested=False)

    def set_start_date(self, *args):
        pass

    set_end_date = set_cash = set_start_date

    def debug(self, message):
        self.lines.append(message)

    def liquidate(self):
        self.liquidated += 1

    def set_holdings(self, symbol, weight):
        self.holdings.append((symbol, weight))


def _lean(monkeypatch, **extra):
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = QCAlgorithm
    stub.Resolution = SimpleNamespace(MINUTE="minute", DAILY="daily")
    stub.timedelta = datetime.timedelta
    for name, value in extra.items():
        setattr(stub, name, value)
    monkeypatch.setitem(sys.modules, "AlgorithmImports", stub)
    return stub


def _messages(algorithm):
    return [json.loads(line[len("SMOKE_JSON "):]) for line in algorithm.lines]


def test_the_teardown_algorithm_buys_spy_once_it_has_data(monkeypatch):
    _lean(monkeypatch)
    module = load_script("lean_teardown_smoke/main")
    algorithm = module.TeardownSmoke()
    algorithm.add_equity = lambda ticker, resolution: SimpleNamespace(symbol="SPY")
    algorithm.initialize()
    algorithm.on_data(SimpleNamespace(contains_key=lambda symbol: False))
    algorithm.on_data(SimpleNamespace(contains_key=lambda symbol: True))
    algorithm.portfolio.invested = True
    algorithm.on_data(SimpleNamespace(contains_key=lambda symbol: True))
    assert algorithm.holdings == [("SPY", 1.0)]


class _Chain(list):
    pass


def _futures_world(monkeypatch, *, margin_raises=False):
    class Model:
        def __init__(self, account):
            pass

        def get_buying_power_model(self, future):
            return "power"

    class Power:
        def GetInitialMarginRequirement(self, parameters):
            if margin_raises:
                raise ValueError("no margin model")
            return SimpleNamespace(Value=-12500.0)

    _lean(monkeypatch, InteractiveBrokersBrokerageModel=Model, AccountType=SimpleNamespace(MARGIN="margin"), InitialMarginParameters=lambda security, quantity: (security, quantity))
    module = load_script("lean_smoke/futures_margin")
    algorithm = module.FuturesMarginSmoke()
    future = SimpleNamespace(symbol="ES", set_filter=lambda *args: None, set_buying_power_model=lambda model: None)
    algorithm.add_future = lambda root, resolution: future
    algorithm.market_order = lambda symbol, quantity: SimpleNamespace(status="Filled")
    algorithm.initialize()
    contract = SimpleNamespace(symbol="ESZ3", expiry=datetime.date(2013, 12, 20))
    later = SimpleNamespace(symbol="ESH4", expiry=datetime.date(2014, 3, 20))
    algorithm.securities = {"ESZ3": SimpleNamespace(price=1700.0, SymbolProperties=SimpleNamespace(ContractMultiplier=50), BuyingPowerModel=Power())}
    return algorithm, contract, later


def test_the_futures_smoke_reports_the_margin_main_py_would_read(monkeypatch):
    algorithm, contract, later = _futures_world(monkeypatch)
    algorithm.on_data(SimpleNamespace(future_chains={}))
    algorithm.on_data(SimpleNamespace(future_chains={"ES": []}))
    assert algorithm.lines == []
    algorithm.on_data(SimpleNamespace(future_chains={"ES": [later, contract]}))
    algorithm.on_data(SimpleNamespace(future_chains={"ES": [contract]}))
    (message,) = _messages(algorithm)
    assert message["contract"] == "ESZ3" and message["multiplier"] == 50.0 and message["initial_margin"] == -12500.0 and message["order_status"] == "Filled" and "spec" in message


def test_a_margin_model_that_raises_is_reported_not_raised(monkeypatch):
    algorithm, contract, _ = _futures_world(monkeypatch, margin_raises=True)
    algorithm.on_data(SimpleNamespace(future_chains={"ES": [contract]}))
    assert "ValueError: no margin model" in _messages(algorithm)[0]["raised"]


# --- option_structures -------------------------------------------------------------------------------------------------------------------------------


class _Strategies:
    def __getattr__(self, name):
        return lambda canonical, *args: (name, canonical, args)


@pytest.fixture
def structures(monkeypatch):
    _lean(monkeypatch, OptionRight=SimpleNamespace(CALL="call", PUT="put"), OptionStrategies=_Strategies())
    module = load_script("lean_smoke/option_structures")
    algorithm = module.OptionStructuresSmoke()
    algorithm.add_equity = lambda ticker, resolution: SimpleNamespace(symbol="AAPL")
    algorithm.add_option = lambda ticker, resolution: SimpleNamespace(symbol="AAPL_CANON", set_filter=lambda *args: None)
    algorithm.initialize()
    algorithm.securities = {"AAPL": SimpleNamespace(price=100.0)}
    return module, algorithm


def _contract(strike, right, bid, ask, *, last=0.0, expiry=datetime.datetime(2014, 7, 19)):
    return SimpleNamespace(symbol=f"C{strike}{right}", strike=strike, right=right, bid_price=bid, ask_price=ask, last_price=last, expiry=expiry, volume=10, open_interest=20)


def test_the_chain_becomes_rows_with_greeks_and_unusable_contracts_are_dropped(structures, monkeypatch):
    module, algorithm = structures
    chain = [
        _contract(100.0, "call", 2.4, 2.6), _contract(100.0, "put", 0.0, 0.0, last=2.0), _contract(100.0, "put", 0.0, 0.0), _contract(95.0, "call", 0.01, 0.02),
        _contract(100.0, "call", 2.4, 2.6, expiry=datetime.datetime(2014, 6, 6)),
    ]
    real = module.implied_volatility
    monkeypatch.setattr(module, "implied_volatility", lambda **kwargs: None if kwargs["strike"] == 95.0 else real(**kwargs))
    rows = algorithm.rows_from(chain)
    assert [row["right"] for row in rows] == ["call", "put"] and rows[0]["iv"] > 0 and "delta" in rows[0]
    algorithm.securities["AAPL"].price = 0.0
    assert algorithm.rows_from(chain) == []


def test_every_registered_structure_is_built_through_its_factory(structures):
    module, algorithm = structures
    assert len(MULTI_LEG_STRATEGY_REGISTRY) >= 43
    for name, spec in MULTI_LEG_STRATEGY_REGISTRY.items():
        expiries = {}
        legs = {}
        for index, leg in enumerate(spec.legs):
            expiry = expiries.setdefault(leg.expiry_role, f"2014-07-{19 + len(expiries)}")
            legs[leg.role] = {"strike": 100.0 + index, "expiry": expiry}
        built = algorithm.build(name, legs)
        assert built[0] == spec.factory_name and built[1] == "AAPL_CANON"


def test_the_detectors_run_on_the_rows_and_a_raising_one_is_reported(structures, monkeypatch):
    module, algorithm = structures
    calls = []

    def signal(name, rows, today, rate, minimum, dividend_payments=None):
        calls.append(name)
        if name == "conversion":
            raise ValueError("bad chain")
        return name == "box_spread"

    monkeypatch.setattr(module, "select_arbitrage_signal", signal)
    monkeypatch.setattr(module, "select_single_leg_contract", lambda rows, delta, right: {"underlying_price": 100.0, "strike": 90.0, "bid": 11.0, "ask": 11.4})
    algorithm.run_detectors([{"x": 1}])
    payload = _messages(algorithm)[0]
    assert payload["arbitrage"]["box_spread"] is True and payload["arbitrage"]["conversion"].startswith("raised ValueError") and payload["assignment"]["strike"] == 90.0
    algorithm.lines.clear()
    monkeypatch.setattr(module, "select_single_leg_contract", lambda rows, delta, right: None)
    algorithm.run_detectors([{"x": 1}])
    assert _messages(algorithm)[0]["assignment"] == {}


def _row_world(structures, monkeypatch):
    module, algorithm = structures
    monkeypatch.setattr(algorithm, "rows_from", lambda chain: list(chain))
    monkeypatch.setattr(algorithm, "run_detectors", lambda rows: algorithm.report({"kind": "detectors"}))
    return module, algorithm


def _slice(chain):
    return SimpleNamespace(option_chains={"AAPL_CANON": chain} if chain is not None else {})


def test_a_structure_is_ordered_reported_and_liquidated_a_bar_later(structures, monkeypatch):
    module, algorithm = _row_world(structures, monkeypatch)
    algorithm.queue = [("bull_call_spread", 0.4)]
    ticket = SimpleNamespace(status="Filled", get_most_recent_order_response=lambda: SimpleNamespace(error_message=""))
    monkeypatch.setattr(module, "select_strategy_legs", lambda name, rows, delta: {"legs": 1})
    monkeypatch.setattr(algorithm, "build", lambda name, legs: "strategy")
    algorithm.buy = lambda strategy, quantity: [ticket]
    algorithm.on_data(_slice(None))
    algorithm.is_warming_up = True
    algorithm.on_data(_slice([{"r": 1}]))
    algorithm.is_warming_up = False
    algorithm.on_data(_slice([]))
    assert algorithm.lines == []
    algorithm.on_data(_slice([{"r": 1}]))
    assert algorithm.current[0] == "bull_call_spread" and algorithm.detectors_done is True
    algorithm.on_data(_slice([{"r": 1}]))
    assert algorithm.liquidated == 1 and algorithm.current is None and algorithm.results["bull_call_spread"]["status"] == "ordered"
    algorithm.on_data(_slice([{"r": 1}]))
    algorithm.on_end_of_algorithm()
    assert _messages(algorithm)[-1]["kind"] == "summary"


def test_a_structure_without_legs_is_retried_at_other_deltas_then_given_up(structures, monkeypatch):
    module, algorithm = _row_world(structures, monkeypatch)
    algorithm.queue = [("iron_condor", 0.4)]
    monkeypatch.setattr(module, "select_strategy_legs", lambda name, rows, delta: None)
    for _ in range(len(module.RETRY_DELTAS) + 1):
        algorithm.on_data(_slice([{"r": 1}]))
    assert algorithm.results["iron_condor"] == {"status": "no_legs_on_this_chain"} and algorithm.queue == []


def test_an_order_that_raises_is_recorded_and_unreached_structures_are_marked(structures, monkeypatch):
    module, algorithm = _row_world(structures, monkeypatch)
    algorithm.queue = [("straddle", 0.4), ("strangle", 0.4)]
    monkeypatch.setattr(module, "select_strategy_legs", lambda name, rows, delta: {"legs": 1})
    monkeypatch.setattr(algorithm, "build", lambda name, legs: (_ for _ in ()).throw(RuntimeError("no such factory")))
    algorithm.on_data(_slice([{"r": 1}]))
    algorithm.on_end_of_algorithm()
    assert algorithm.results["straddle"]["status"] == "raised" and algorithm.results["strangle"] == {"status": "not_reached"}


# --- the three config writers' commands ----------------------------------------------------------------------------------------------------------


def _lean_json(tmp_path):
    path = tmp_path / "lean.json"
    path.write_text(json.dumps({"data-folder": "x", "environments": {"live-paper": {"live-mode": True, "data-queue-handler": ["old"]}, "backtesting": {}}}), encoding="utf-8")
    return path


def test_the_field_test_config_command_writes_the_launcher_and_the_project_config(monkeypatch, tmp_path):
    lean = _lean_json(tmp_path)
    project = tmp_path / "config.json"
    project.write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "launcher.json"
    assert run_script("lean_smoke/make_field_test_config", ["--lean-json", str(lean), "--out", str(out), "--project-config", str(project)], monkeypatch) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "live-paper-fake" in written["environments"] and json.loads(project.read_text(encoding="utf-8"))["phase_v2"]["diagnostics"]["field_test"]


def test_the_live_plumbing_config_command_trims_the_project_to_a_few_names(monkeypatch, tmp_path):
    lean = _lean_json(tmp_path)
    project = tmp_path / "config.json"
    project.write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "launcher.json"
    assert run_script("lean_smoke/make_live_plumbing_config", ["--lean-json", str(lean), "--out", str(out), "--project-config", str(project)], monkeypatch) == 0
    tickers = {asset["ticker"] for asset in json.loads(project.read_text(encoding="utf-8"))["phase1"]["universe"]["assets"]}
    assert tickers <= {"BTCUSD", "ETHUSD", "SOLUSD", "SPY", "TLT"} and json.loads(project.read_text(encoding="utf-8"))["runtime"]["mode"] == "paper"


def test_the_option_config_command_writes_one_scenarios_config(monkeypatch, tmp_path, capsys):
    out = tmp_path / "option.json"
    assert run_script("lean_smoke/make_option_main_config", ["--out", str(out), "--scenario", "assign"], monkeypatch) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["phase_v2"]["options_risk"]["assignment_risk_detector"]["enabled"] is True and str(out) in capsys.readouterr().out
