"""`on_data()` itself on the shipped path, across several sessions (V6.6.4).

`tests/test_main_wiring.py` drives `_target_weights_tick` and the order methods one at a time, so `on_data()` / `_on_data_impl` had only ever run with an empty slice. This drives the real entry
point on a minimal Lean stub for a week of sessions: the algorithm's orders must be exactly what the pure function the offline simulator uses (`portfolio.target_weights.rebalance_deltas`) says for the
holdings it has at that moment, a trade lock must stop new risk and flatten the book, and a tick with no bars or a stale decision must neither crash nor trade. It needs no `ml/` artifact, so it runs on CI.

It is NOT a Lean simulator: nothing here proves fill timing or Lean API semantics (the owner-run backtest and the DinD Codespace do).
"""

from __future__ import annotations

import datetime
import sys
import types
from types import SimpleNamespace

import pytest

from portfolio.target_weights import TargetWeightsConfig, rebalance_deltas


@pytest.fixture(scope="module")
def main_module():
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = type("QCAlgorithm", (), {})
    stub.Slice = object
    stub.time = datetime.time
    stub.Exception = type("ClrException", (Exception,), {})
    patcher = pytest.MonkeyPatch()
    patcher.setitem(sys.modules, "AlgorithmImports", stub)
    patcher.delitem(sys.modules, "main", raising=False)
    import main  # noqa: PLC0415

    yield main
    sys.modules.pop("main", None)
    patcher.undo()


PRICES = {"A": 100.0, "C": 50.0}
CLASSES = {"A": "equity", "C": "equity"}


class _Holdings:
    def __init__(self, total: float):
        self.TotalPortfolioValue = total
        self.quantity = {"A": 0.0, "C": 0.0}
        self.CashBook = {"USD": SimpleNamespace(AddAmount=lambda amount: None)}
        self.Values = []

    def __getitem__(self, symbol):
        return SimpleNamespace(Quantity=self.quantity.get(str(symbol), 0.0), HoldingsValue=0.0, AveragePrice=0.0, Invested=self.quantity.get(str(symbol), 0.0) != 0.0)


def _algorithm(main_module, weights, *, total=100_000.0):
    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    algorithm._ready = True
    algorithm._timing_probe = SimpleNamespace(start=lambda: 0, stop=lambda name, started: None)
    algorithm.target_weights_config = TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=0.0, financing_enabled=False, no_bar_exit=False)
    algorithm.is_warming_up = False
    algorithm.is_equity_session_bar = True
    algorithm.bar_index = 0
    algorithm.trade_lock_active = False
    algorithm._pending_entries_this_bar = set()
    algorithm._refresh_risk_state = lambda: None
    algorithm._liquidate_positions_for_disabled_asset_classes = lambda: None
    algorithm._order_permission = lambda: (True, "ok")
    algorithm.runtime_mode = "backtest"
    algorithm.allow_live_orders = False
    algorithm._broker_config_present = False
    algorithm._target_weights = weights
    algorithm._target_pending = {}
    algorithm._target_symbol_by_ticker = {"A": "A", "C": "C"}
    algorithm._target_class_by_ticker = dict(CLASSES)
    algorithm._target_lot_by_ticker = {"A": 1.0, "C": 1.0}
    algorithm._target_financing_date = None
    algorithm._target_exited_without_bars = set()
    algorithm._target_missing_bars = {}
    algorithm._equity_symbols = ["A", "C"]
    algorithm.Time = datetime.datetime(2024, 1, 2, 16)
    algorithm.Portfolio = _Holdings(total)
    algorithm._open_order_quantity = lambda symbol: 0.0
    algorithm._target_usd_per_unit = lambda symbol: PRICES[str(symbol)]
    algorithm.calls, algorithm.orders = [], []
    algorithm._update_cash_sweep = lambda: algorithm.calls.append("sweep")

    def liquidate():
        algorithm.calls.append("liquidate")
        for symbol, quantity in list(algorithm.Portfolio.quantity.items()):
            if quantity:
                algorithm.orders.append((symbol, -quantity, "liquidate"))
                algorithm.Portfolio.quantity[symbol] = 0.0

    algorithm._liquidate_strategy_positions = liquidate

    def market_order(symbol, quantity, tag=""):
        algorithm.orders.append((symbol, quantity, tag))
        algorithm.Portfolio.quantity[symbol] = algorithm.Portfolio.quantity.get(symbol, 0.0) + quantity

    algorithm.MarketOrder = market_order
    return algorithm


def _slice(day: str, tickers=("A", "C")):
    stamp = datetime.datetime.fromisoformat(day)
    return SimpleNamespace(Bars={ticker: SimpleNamespace(Time=stamp, IsFillForward=False) for ticker in tickers}, QuoteBars={})


def _expected(algorithm, row):
    held = {t: algorithm.Portfolio.quantity[t] for t in ("A", "C") if t in row or algorithm.Portfolio.quantity[t] != 0.0}
    values = {t: PRICES[t] for t in held}
    deltas = rebalance_deltas(
        held, values, algorithm.Portfolio.TotalPortfolioValue, {t: w for t, w in row.items() if t in held}, algorithm.target_weights_config,
        lot_size=algorithm._target_lot_by_ticker, class_by_ticker=algorithm._target_class_by_ticker,
    )
    return [(ticker, delta, "target_weights") for ticker, delta in deltas]


DAYS = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
ROWS = {
    "2024-01-02": {"A": 0.30, "C": 0.20},
    "2024-01-03": {"A": 0.30, "C": 0.20},
    "2024-01-04": {"A": 0.10, "C": 0.40},
    "2024-01-05": {"C": 0.40},
    "2024-01-08": {},
}


def test_a_week_of_on_data_places_exactly_the_orders_the_pure_rebalance_function_says(main_module):
    algorithm = _algorithm(main_module, ROWS)
    for day in DAYS:
        algorithm.Time = datetime.datetime.fromisoformat(day + "T16:00:00")
        before = len(algorithm.orders)
        expected = _expected(algorithm, ROWS[day])
        algorithm.on_data(_slice(day))
        assert algorithm.orders[before:] == expected, day
    assert all(quantity == 0.0 for quantity in algorithm.Portfolio.quantity.values()), "the last row is empty, so the book is flat"
    assert algorithm.bar_index == len(DAYS), "one equity session bar per day"
    assert algorithm.calls.count("sweep") == len(DAYS)


def test_the_first_day_buys_the_weights_it_was_given(main_module):
    algorithm = _algorithm(main_module, ROWS)
    algorithm.on_data(_slice("2024-01-02"))
    assert ("A", 300.0, "target_weights") in algorithm.orders and ("C", 400.0, "target_weights") in algorithm.orders


def test_a_trade_lock_stops_new_risk_flattens_the_book_and_the_file_resumes_after_it_clears(main_module):
    algorithm = _algorithm(main_module, ROWS)
    algorithm.on_data(_slice("2024-01-02"))
    held = dict(algorithm.Portfolio.quantity)
    assert held["A"] > 0.0
    algorithm.trade_lock_active = True
    algorithm.Time = datetime.datetime(2024, 1, 3, 16)
    algorithm.on_data(_slice("2024-01-03"))
    assert algorithm.calls[-2:] == ["liquidate", "sweep"] and all(tag != "target_weights" for _, _, tag in algorithm.orders[-2:]), "no new target order while locked"
    assert all(quantity == 0.0 for quantity in algorithm.Portfolio.quantity.values())
    algorithm.trade_lock_active = False
    algorithm.Time = datetime.datetime(2024, 1, 4, 16)
    algorithm.on_data(_slice("2024-01-04"))
    assert algorithm.Portfolio.quantity["C"] > 0.0, "the file is read again once the lock clears"


def test_a_tick_with_no_bars_does_nothing_and_does_not_crash(main_module):
    algorithm = _algorithm(main_module, ROWS)
    algorithm.on_data(SimpleNamespace(Bars={}, QuoteBars={}))
    assert algorithm.orders == [] and algorithm.calls == [] and algorithm.bar_index == 0


def test_a_day_with_no_row_in_the_file_holds_what_is_held(main_module):
    algorithm = _algorithm(main_module, {"2024-01-02": {"A": 0.30}})
    algorithm.on_data(_slice("2024-01-02"))
    held = dict(algorithm.Portfolio.quantity)
    algorithm.Time = datetime.datetime(2024, 1, 9, 16)
    algorithm.on_data(_slice("2024-01-09"))
    assert algorithm.Portfolio.quantity == held


def test_observation_mode_never_orders_through_on_data(main_module):
    algorithm = _algorithm(main_module, ROWS)
    algorithm._order_permission = lambda: (False, "observation_mode_no_real_orders")
    for day in DAYS:
        algorithm.on_data(_slice(day))
    assert algorithm.orders == [] and algorithm.Portfolio.quantity == {"A": 0.0, "C": 0.0}
