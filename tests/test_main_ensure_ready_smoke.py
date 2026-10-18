"""Smoke test: main.py's `initialize()` + `_ensure_ready()` against the REAL config and model artifacts.

V5.5.0's first backtest attempt died on bar 1 with `type object 'datetime.time' has no attribute
'perf_counter'`: `from AlgorithmImports import *` exports Lean's `time` (datetime.time), silently
replacing the stdlib module main.py had imported. The wiring tests never ran `_ensure_ready()` (it loads
every model and derives ~hundreds of config values), and their stub did not export `time`, so nothing
caught it. This test closes both gaps: the stub below exports `time` exactly as Lean does, and the whole
first-bar setup path runs against what `aq backtest` would really load.

Skipped when `ml/` artifacts or `config.json` are absent (a fresh CI checkout - ml/ is gitignored).
Everything not stdlib is faked permissively; no Lean, Docker, Redis or Postgres is needed (the queues
degrade with a connection warning, exactly as they do in the test suite elsewhere).

Conventions match the rest of this repo: no test classes, module-level helpers."""

from __future__ import annotations

import datetime
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("config.json", "ml/feature_schema.json", "ml/scaler_stats.json")

pytestmark = pytest.mark.skipif(
    not all((ROOT / name).exists() for name in REQUIRED),
    reason="needs config.json and trained ml/ artifacts (gitignored, absent on a fresh checkout)",
)


class _PermissiveQCAlgorithm:
    """Stands in for QCAlgorithm's very large public surface: any PUBLIC attribute is a MagicMock.
    Private attributes must really be set by main.py, so a typo there still fails."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = MagicMock(name=name)
        object.__setattr__(self, name, value)
        return value


@pytest.fixture(scope="module")
def algorithm():
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = _PermissiveQCAlgorithm
    stub.Slice = object  # evaluated at def time by main.py's annotations on Python < 3.14 (CI runs 3.11)
    stub.time = datetime.time  # Lean's star import exports this and shadows the stdlib `time` module
    patcher = pytest.MonkeyPatch()
    patcher.setitem(sys.modules, "AlgorithmImports", stub)
    patcher.delitem(sys.modules, "main", raising=False)
    patcher.chdir(ROOT)
    import main  # noqa: PLC0415 - must come after the stub is installed

    instance = main.AetherQuantAlgorithm()
    instance._write_state = lambda *args, **kwargs: None  # never write visualization/state.json from a test
    instance.Debug = lambda message: None
    instance.Log = lambda message: None
    instance.Time = datetime.datetime(2019, 1, 2)

    for _ in range(80):  # Lean-only names main.py reaches during setup get a stand-in on first NameError
        try:
            if "_initialized_once" not in instance.__dict__:
                instance.initialize()
                instance.__dict__["_initialized_once"] = True
            instance._ensure_ready()
            break
        except NameError as error:
            match = re.search(r"name '(\w+)' is not defined", str(error))
            if not match:
                raise
            main.__dict__[match.group(1)] = MagicMock(name=match.group(1))
    else:  # pragma: no cover
        raise AssertionError("setup kept raising NameError")
    yield instance
    sys.modules.pop("main", None)
    patcher.undo()


def test_first_bar_setup_completes_with_lean_exporting_its_own_time(algorithm):
    assert algorithm.__dict__["_ready"] is True


def test_the_v550_config_blocks_were_read_into_real_values(algorithm):
    assert algorithm.legacy_sleeve_config["enabled"] is True
    assert 0.0 < algorithm.legacy_sleeve_config["max_weight_per_name"] <= algorithm.legacy_sleeve_config["max_gross_exposure"]
    assert algorithm.book_weight_floor_fraction == pytest.approx(0.5)
    assert algorithm.forex_cap_to_book_weight is True
    assert algorithm.max_forex_short_exposure <= algorithm.max_short_exposure
    assert algorithm._liquidity_slippage_source == "per_side"
    assert isinstance(algorithm._timing_probe.summary()["sections"], dict)  # empty while the probe flag is off


def test_the_new_per_symbol_state_containers_exist_before_the_first_bar(algorithm):
    for name in ("_last_formed_book_allocations", "_book_owned_symbols", "_limit_order_kept_flag", "_crypto_bar_probe_counts"):
        assert name in algorithm.__dict__, name


def test_the_benchmark_follows_the_daily_spy_subscription(algorithm):
    # A Symbol would make Lean add its own internal HOURLY benchmark feed (a local zip that ends 2021-03-31 gave a flat
    # line); a function reads the daily subscription's own price.
    algorithm.set_benchmark.assert_called_once()
    (benchmark,), _kwargs = algorithm.set_benchmark.call_args
    assert callable(benchmark)
    algorithm.securities[algorithm.ticker_to_symbol["SPY"]].price = 123.5
    assert benchmark(datetime.datetime(2024, 1, 2)) == 123.5


def test_v610_first_bar_reads_the_probe_ranges_and_the_rank_signal_fallback_flag(algorithm):
    assert algorithm.crypto_bar_probe_date_ranges == []  # shipped config: count-only probe
    assert "demotion_fallback" in algorithm._rank_signal_policy


def test_on_data_runs_setup_before_its_timing_probe_exists_and_records_the_whole_tick(algorithm):
    algorithm.__dict__["_ready"] = False
    algorithm.__dict__.pop("_timing_probe", None)
    slice_stub = types.SimpleNamespace(Bars={})  # no bars: the tick returns right after setup

    algorithm.on_data(slice_stub)

    assert algorithm.__dict__["_ready"] is True
    assert "on_data_total" not in algorithm._timing_probe.summary()["sections"]  # probe off in the shipped config
    algorithm._timing_probe.enabled = True
    algorithm.on_data(slice_stub)
    assert algorithm._timing_probe.summary()["sections"]["on_data_total"]["calls"] == 1
    algorithm._timing_probe.enabled = False


def test_a_live_seed_ensemble_matches_the_single_model_when_its_members_are_identical(algorithm):
    import copy

    inputs = [0.1] * len(algorithm.multitask_feature_schema["model_input_names"])
    single = algorithm._run_multitask_model(inputs)
    assert single is not None
    algorithm.multitask_ensemble = [copy.deepcopy(algorithm.multitask_model) for _ in range(3)]
    try:
        ensembled = algorithm._run_multitask_model(inputs)
    finally:
        algorithm.multitask_ensemble = []
    assert set(ensembled) == set(single)
    for head, value in single.items():
        assert ensembled[head] == pytest.approx(value, abs=1e-12)


def test_the_installed_models_read_the_full_input_vector_and_a_subset_member_reads_its_own(algorithm):
    import copy

    assert algorithm._multitask_input_index is None and algorithm._sequence_input_index is None  # V6.2.0: unchanged
    names = list(algorithm.model_input_names)
    member = copy.deepcopy(algorithm.multitask_model)
    assert algorithm._resolve_input_index("member", member) is None
    member["model"] = dict(member.get("model", {}), model_input_features=names[:3] + ["not_a_live_feature"])
    assert algorithm._resolve_input_index("member", member) is False


class _Holding:
    def __init__(self, symbol, quantity=0.0, price=100.0, net_profit=0.0, unrealized=0.0):
        self.Symbol, self.Quantity, self.NetProfit, self.UnrealizedProfit = symbol, quantity, net_profit, unrealized
        self.AveragePrice = price - 0.5  # bought half a dollar below today's price
        self.HoldingsValue = quantity * price
        self.Invested = quantity != 0.0


class _Portfolio:
    def __init__(self, holdings, total):
        self._holdings, self.TotalPortfolioValue = holdings, total

    def __getitem__(self, symbol):
        return self._holdings.setdefault(symbol, _Holding(symbol))

    @property
    def Values(self):
        return list(self._holdings.values())


def _sweep_world(algorithm, monkeypatch, *, held_long=0.2, sweep_quantity=0.0):
    """One long equity of `held_long` x NAV, the T-bill sweep at `sweep_quantity` shares, prices 100, NAV 100k."""
    config = dict(algorithm.config)
    config["phase_v2"] = dict(config["phase_v2"], cash_sweep=dict(config["phase_v2"]["cash_sweep"], enabled=True))
    monkeypatch.setattr(algorithm, "config", config)
    monkeypatch.setattr(algorithm, "ticker_to_symbol", {"AAA": "AAA"})
    sweep_security = types.SimpleNamespace(symbol="BIL", fee_model=None, set_slippage_model=lambda model: None)
    monkeypatch.setattr(algorithm, "add_equity", lambda ticker, resolution: sweep_security)
    for name in ("cash_sweep_config", "_cash_sweep_symbol", "_cash_sweep_key", "_cash_sweep_state", "_cash_sweep_other_budget",
                 "_cash_sweep_neutral_budget", "_risk_value_state"):
        monkeypatch.setattr(algorithm, name, getattr(algorithm, name, None), raising=False)  # restored after the test
    algorithm._setup_cash_sweep()
    holdings = {"AAA": _Holding("AAA", quantity=held_long * 1000), "BIL": _Holding("BIL", quantity=sweep_quantity, net_profit=40.0,
                                                                                unrealized=10.0)}
    monkeypatch.setattr(algorithm, "Portfolio", _Portfolio(holdings, 100_000.0))
    monkeypatch.setattr(algorithm, "Securities", {"AAA": types.SimpleNamespace(Price=100.0), "BIL": types.SimpleNamespace(Price=100.0)})
    monkeypatch.setattr(algorithm, "symbols", ["AAA"])
    monkeypatch.setattr(algorithm, "asset_lookup", {"AAA": {"security_type": "equity", "ticker": "AAA"}})
    monkeypatch.setattr(algorithm, "Transactions", types.SimpleNamespace(GetOpenOrderTickets=lambda symbol: []))
    monkeypatch.setattr(algorithm, "is_equity_session_bar", True)
    monkeypatch.setattr(algorithm, "is_warming_up", False)
    monkeypatch.setattr(algorithm, "runtime_mode", "backtest")
    monkeypatch.setattr(algorithm, "_book_target_weights", {})
    monkeypatch.setattr(algorithm, "_last_book_allocations", {})
    orders = []
    monkeypatch.setattr(algorithm, "MarketOrder", lambda symbol, quantity, tag="": orders.append((symbol, quantity, tag)))
    return orders


def test_the_cash_sweep_buys_up_to_both_limits_and_stays_out_of_the_strategy(algorithm, monkeypatch):
    from portfolio.cash_sweep import cash_sweep_target_weight, margin_fraction, strategy_reserve

    orders = _sweep_world(algorithm, monkeypatch)
    assert algorithm._cash_sweep_key == "BIL" and "BIL" not in algorithm.asset_lookup
    algorithm._update_cash_sweep()
    reserve = strategy_reserve(  # the book is empty, so the next session is a rebalance attempt
        rebalance_next=True, book_gross_cap=algorithm.book_gross_exposure_cap, max_short_exposure=algorithm.max_short_exposure,
        formed_long=0.0, formed_short=0.0, book_long=0.0, book_short=0.0,
        other_budget_remaining=algorithm._cash_sweep_other_budget, neutral_budget=algorithm._cash_sweep_neutral_budget,
    )
    expected = cash_sweep_target_weight(long_weight=0.2, short_weight=0.0, margin_used=margin_fraction([("equity", 0.2)]),
                                        reserve=reserve, config=algorithm.cash_sweep_config)
    assert 0.0 < expected < algorithm.cash_sweep_config["max_weight"]
    assert orders == [("BIL", int(expected * 100_000 / 100.0), "cash_sweep")]
    # the risk controls read the strategy without the sweep's carry, and the position count ignores it
    # realized 40 net of fees; the mark is quantity x (price - average price), never Lean's fee-adjusted UnrealizedProfit
    assert algorithm._cash_sweep_holding_profit() == (40.0, 0.0)
    algorithm.Portfolio._holdings["BIL"] = _Holding("BIL", quantity=200.0, net_profit=40.0, unrealized=-999.0)
    assert algorithm._cash_sweep_holding_profit() == (40.0, 100.0)
    algorithm.Portfolio._holdings["BIL"] = _Holding("BIL", quantity=0.0, net_profit=40.0)
    monkeypatch.setattr(algorithm, "_pending_entries_this_bar", set())
    algorithm.Portfolio._holdings["BIL"] = _Holding("BIL", quantity=500.0)
    assert algorithm._active_position_count(orders_allowed=True) == 1


def test_a_sweep_already_near_target_is_left_alone_and_the_drawdown_liquidation_keeps_it(algorithm, monkeypatch):
    orders = _sweep_world(algorithm, monkeypatch, sweep_quantity=0.0)
    algorithm._update_cash_sweep()
    first = orders[0][1]
    orders.clear()
    _sweep_world(algorithm, monkeypatch, sweep_quantity=first)
    algorithm._update_cash_sweep()
    assert orders == []
    liquidated = []
    monkeypatch.setattr(algorithm, "Liquidate", lambda symbol=None: liquidated.append(symbol))
    algorithm._liquidate_strategy_positions()
    assert liquidated == ["AAA"]


def test_the_sweep_is_subscribed_exactly_when_the_config_enables_it(algorithm):
    enabled = bool(algorithm.config["phase_v2"].get("cash_sweep", {}).get("enabled"))
    assert (algorithm._cash_sweep_symbol is not None) is enabled
    assert algorithm.cash_sweep_config["ticker"] not in algorithm.ticker_to_symbol  # never a universe asset
    if not enabled:
        assert algorithm._cash_sweep_holding_profit() == (0.0, 0.0)
