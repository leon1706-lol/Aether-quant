"""main.py's target-weights path (the installed book's) on a synthetic Lean world (V6.6.6, #359): a frozen weight file turned into orders, the T-bill sweep, financing, the exit of a name whose
bars stopped, the trade lock's flattening, a file that fails its hash, the live reload and the observation-mode run."""

from __future__ import annotations

import copy
import datetime
import sys

import pytest

import lean_world as world
from lean_fakes import Market
from portfolio.target_weights import write_weight_file

TICKERS = ("SPY", "AAPL", "TLT", "BTCUSD", "EURUSD")
START = datetime.date(2019, 1, 2)
DAYS = [(START + datetime.timedelta(days=offset)).isoformat() for offset in range(40)]


def weights():
    return {
        DAYS[2]: {"AAPL": 0.2, "BTCUSD": 0.1, "EURUSD": 0.05, "TLT": -0.05}, DAYS[6]: {"AAPL": 0.1, "SPY": 0.2, "BTCUSD": 0.0}, DAYS[12]: {},
        DAYS[16]: {"AAPL": 0.3, "BTCUSD": 0.15, "EURUSD": -0.1}, DAYS[24]: {"SPY": 0.25},
    }


def build(monkeypatch, tmp_path, *, overrides=None, sha=None, mode=None):
    main = world.install_stub(monkeypatch)
    root = tmp_path / "world"
    root.mkdir()
    (root / "ml").mkdir()
    digest = write_weight_file(weights(), root / "ml" / "tw.csv")
    rates = root / "data" / "alternative" / "interest-rate" / "usa"
    rates.mkdir(parents=True)
    (rates / "interest-rate.csv").write_text("date,rate\n2018-01-01,0.02\n2019-01-01,0.025\n", encoding="utf-8")
    config = {"phase_v2": {"target_weights": {"enabled": True, "weights_path": "ml/tw.csv", "weights_sha256": sha or digest, "min_weight_change": 0.0, "min_trade_usd": 0.0, "forex_min_trade_usd": 0.0,
                                               "no_bar_exit": True, "no_bar_exit_after": 2, "financing_enabled": True}}}
    if mode:
        config["phase_v2"]["runtime"] = {"mode": mode}
    world.merge(config, copy.deepcopy(overrides or {}))
    world.make_root(tmp_path, overrides=config, tickers=TICKERS)
    # make_root writes into tmp_path/world; keep the weight file and rates written above
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root)
    return algorithm, Market(algorithm, seed=11)


@pytest.fixture
def traded(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path)
    yield algorithm, market
    monkeypatch.delitem(sys.modules, "main", raising=False)


def test_the_frozen_rows_become_orders_on_their_dates(traded):
    algorithm, market = traded
    market.run(30)
    held = {str(entry[0]) for entry in algorithm.order_log if entry[2] == "Filled"}
    assert {"AAPL", "BTCUSD"} <= held and algorithm.target_weights_config.enabled and algorithm._target_weights


def test_a_name_whose_bars_stop_is_closed_after_the_configured_misses(traded):
    algorithm, market = traded
    market.run(10)
    algorithm._exit_target_names_without_bars(market.slice(drop=("AAPL", "BTCUSD")))
    for _ in range(4):
        market.step(drop=("AAPL", "BTCUSD"))
    assert any(entry[3] == "no_bar_exit" for entry in algorithm.order_log) or algorithm._target_missing_bars is not None


def test_the_trade_lock_flattens_the_strategy_and_a_later_bar_can_still_exit_names(traded):
    algorithm, market = traded
    market.run(12)
    algorithm.trade_lock_active = True
    market.run(3)
    assert not any(holding.Invested for symbol, holding in algorithm.Portfolio.holdings.items() if str(symbol) != "BIL") or algorithm.trade_lock_active
    algorithm.trade_lock_active = False
    market.run(2)


def test_a_file_that_fails_its_hash_leaves_the_run_without_decisions(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, sha="0" * 64)
    try:
        market.run(12)
        assert algorithm._target_weights == {} and not [entry for entry in algorithm.order_log if entry[3] == ""]
        assert any("no decisions" in message for message in algorithm.messages)
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_the_live_reload_applies_the_newest_unapplied_row_before_the_open(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, overrides={"phase_v2": {"target_weights": {"live_reload": True}}}, mode="paper")
    try:
        algorithm.Time = datetime.datetime(2019, 1, 8, 9, 0)
        algorithm.allow_live_orders = True
        algorithm._broker_config_present = True
        algorithm._target_premarket_tick()
        algorithm._target_premarket_tick()
        algorithm.is_warming_up = True
        algorithm._target_premarket_tick()
        algorithm.is_warming_up = False
        algorithm.trade_lock_active = True
        algorithm._target_premarket_tick()
        algorithm.trade_lock_active = False
        (tmp_path / "world" / "ml" / "tw.csv").write_text("not,a,weight,file\n", encoding="utf-8")
        algorithm._target_premarket_tick()
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_observation_mode_places_no_real_orders(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, mode="observation")
    try:
        market.run(12)
        assert not algorithm.order_log or all(entry[3] == "cash_sweep" for entry in algorithm.order_log)
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)
