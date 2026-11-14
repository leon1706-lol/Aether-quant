"""scripts/lean_smoke/main_option_order.py with stand-ins for Lean and for main.py (V6.6.6): the forced limit and market
orders, a chain with no decision, a warm-up, and an order that raises."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

from script_loader import load_script


class _Base:
    """What the smoke subclass reads from main.py's AetherQuantAlgorithm."""

    def __init__(self, chains, *, raise_on_order=False):
        self.lines, self.orders, self.base_events = [], [], []
        self.is_warming_up = False
        self.symbols = ["SPY", "AAPL_OPT", "QQQ_OPT"]
        self.asset_lookup = {
            "SPY": {"security_type": "equity"},
            "AAPL_OPT": {"security_type": "option", "underlying_ticker": "AAPL"},
            "QQQ_OPT": {"security_type": "option", "underlying_ticker": "QQQ"},
        }
        self.latest_options_chains_payload = chains
        self.Portfolio = SimpleNamespace(TotalPortfolioValue=100000.0)
        self.Transactions = SimpleNamespace(OrdersCount=0)
        self.limit_orders_enabled = True
        self.raise_on_order = raise_on_order

    def Debug(self, message):
        self.lines.append(message)

    def on_data(self, slice):
        pass

    def on_order_event(self, order_event):
        self.base_events.append(order_event)

    def _apply_option_multi_leg_order(self, symbol, key, decision, weight, price, is_long, reason):
        if self.raise_on_order:
            raise RuntimeError("broker said no")
        self.orders.append((decision.contracts, self.limit_orders_enabled))
        self.Transactions.OrdersCount += decision.contracts
        return "submitted"


class _Symbol:
    def __init__(self, kind, text="AAPL C"):
        self.SecurityType = kind
        self._text = text

    def __str__(self):
        return self._text


@pytest.fixture
def smoke(monkeypatch):
    lean = types.ModuleType("AlgorithmImports")
    lean.SecurityType = SimpleNamespace(Option="Option", Equity="Equity")
    aq_main = types.ModuleType("aq_main")
    aq_main.AetherQuantAlgorithm = _Base
    monkeypatch.setitem(sys.modules, "AlgorithmImports", lean)
    monkeypatch.setitem(sys.modules, "aq_main", aq_main)
    return load_script("lean_smoke/main_option_order")


def _messages(algorithm):
    return [json.loads(line[len("SMOKE_JSON "):]) for line in algorithm.lines]


def test_it_forces_one_limit_order_then_one_market_order_once(smoke, monkeypatch):
    legs = [SimpleNamespace(contract_symbol="C1"), SimpleNamespace(contract_symbol="C2")]
    decision = SimpleNamespace(strategy_name="bull_call_vertical", contracts=3, legs=legs)
    decisions = iter([None, decision])
    monkeypatch.setattr(smoke, "build_vertical_spread_position_sizing", lambda *args, **kwargs: next(decisions))
    monkeypatch.setattr(smoke.dataclasses, "replace", lambda item, **changes: SimpleNamespace(**{**vars(item), **changes}))
    chains = {"AAPL": [{"underlying_price": 190.0}], "QQQ": [{"underlying_price": None}]}
    algorithm = smoke.MainOptionOrderSmoke(chains)
    algorithm.symbols = ["SPY", "AAPL_OPT", "QQQ_OPT", "AAPL_OPT"]

    algorithm.on_data(None)
    algorithm.on_data(None)  # forced already: nothing more

    messages = _messages(algorithm)
    assert [message["kind"] for message in messages] == ["no_decision", "forced_order", "forced_market_order"]
    assert algorithm.orders == [(3, True), (1, False)] and algorithm.limit_orders_enabled is True
    assert messages[1]["legs"] == ["C1", "C2"] and messages[1]["orders_placed"] == 3 and messages[2]["orders_placed"] == 1


def test_warmup_or_no_chain_places_nothing(smoke):
    warming = smoke.MainOptionOrderSmoke({"AAPL": [{"underlying_price": 1.0}]})
    warming.is_warming_up = True
    warming.on_data(None)
    empty = smoke.MainOptionOrderSmoke(None)
    empty.on_data(None)
    assert warming.lines == [] and empty.lines == [] and warming.orders == []


def test_an_order_that_raises_is_reported_and_re_raised(smoke, monkeypatch):
    decision = SimpleNamespace(strategy_name="s", contracts=1, legs=[])
    monkeypatch.setattr(smoke, "build_vertical_spread_position_sizing", lambda *args, **kwargs: decision)
    algorithm = smoke.MainOptionOrderSmoke({"AAPL": [{"underlying_price": 5.0}]}, raise_on_order=True)
    with pytest.raises(RuntimeError, match="broker said no"):
        algorithm.on_data(None)
    assert _messages(algorithm) == [{"kind": "order_raised", "error": "RuntimeError: broker said no"}]


def test_option_fills_are_reported_and_other_fills_only_passed_on(smoke):
    algorithm = smoke.MainOptionOrderSmoke({})
    option_fill = SimpleNamespace(Symbol=_Symbol("Option"), Status="Filled", FillQuantity=2, FillPrice=1.5)
    algorithm.on_order_event(option_fill)
    algorithm.on_order_event(SimpleNamespace(Symbol=_Symbol("Equity")))
    assert len(algorithm.base_events) == 2
    assert _messages(algorithm) == [{"kind": "option_fill_event", "symbol": "AAPL C", "status": "Filled", "quantity": 2.0, "price": 1.5}]
