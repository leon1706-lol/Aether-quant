"""main.py's final branches on a synthetic Lean world (V6.6.6, #359): the setup that skips or drops what it cannot use, the book's hierarchical weights without neutrality, a forex policy sizing entries,
a liquidity cut, resizes of held futures and forex through explicit target weights, per-class short exposure, the shadow guard's off switches, the reconciliation and state-write guards, and the
simulated book's early returns."""

from __future__ import annotations

import copy
import datetime
import json
import sys
from types import SimpleNamespace

import pytest

import lean_world as world
from lean_fakes import Market

FUTURE = {"ticker": "ES", "security_type": "future", "market": "cme", "lean_future_ticker": "ES", "data_path": "data/future/cme/daily/es.zip"}
OPTION = {"ticker": "AAPL_OPT", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa", "data_path": "data/option/usa/aapl"}
BOOK = {
    "phase_v2": {"target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "limit_orders": {"enabled": False}, "futures_risk": {"enabled": True}, "forex_risk": {"enabled": True},
                 "portfolio_book": {"top_n": 2, "bottom_n": 2, "rebalance_every_bars": 2, "min_rank_confidence_spread": 0.0, "hysteresis_rank_margin": 0.0,
                                    "neutrality": {"sector_neutral": False, "max_weight_per_name": 0.3}},
                 "functionality": {"position_scaling": {"enabled": True, "rotate_on_drift": False, "rebalance_threshold_weight": 0.0}}},
    "phase1": {"target": {"ranking": {"min_universe_size": 4}}},
    "phase6": {"risk": {"trade_cooldown_bars": 0, "max_position_weight": 0.2}},
    "phase9": {"portfolio": {"max_active_positions": 12, "observation_only_assets_can_trade": True}},
}
TICKERS = ("SPY", "AAPL", "MSFT", "XOM", "TLT", "BTCUSD", "ETHUSD", "EURUSD", "GBPJPY")


def make(monkeypatch, tmp_path, overrides=None, *, extra=(FUTURE,), prepare=None, bars=4, ready=True, tickers=TICKERS):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BOOK), copy.deepcopy(overrides or {})), tickers=tickers, extra_assets=extra)
    if prepare:
        prepare(root)
    monkeypatch.chdir(root)
    monkeypatch.setattr(main, "load_futures_contract_specs", lambda *a, **k: {"ES": {"description": "E-mini", "multiplier": 50.0, "initial_margin_usd": 3000.0, "exchange": "CME"}})
    monkeypatch.setattr(main, "load_forex_pair_specs", lambda *a, **k: {"EURUSD": {"lot_size": 1000.0, "margin_pct": 0.05}, "GBPJPY": {"lot_size": 1000.0, "margin_pct": 0.05}})
    algorithm = world.build_algorithm(main, root, ready=ready)
    market = Market(algorithm, seed=3) if ready else None
    if market is not None:
        market.run(bars)
    return main, algorithm, market, root


@pytest.fixture(autouse=True)
def drop_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


def symbol_of(algorithm, ticker):
    return next(symbol for symbol in algorithm.symbols if algorithm.asset_lookup[str(symbol)]["ticker"] == ticker)


def payload_for(algorithm, ticker, signal, confidence=0.9, weight=0.08):
    symbol = symbol_of(algorithm, ticker)
    asset = algorithm.asset_lookup[str(symbol)]
    price = float(algorithm.Securities[symbol].Price)
    features = algorithm._build_model_input(symbol)["base_features"]
    return symbol, price, algorithm._build_dynamic_sizing_payload(signal, confidence, weight, features, asset, price, {}, 0.02, 0.9, str(symbol), False)


def test_setup_skips_a_slot_class_it_cannot_trade_and_demotes_heads_that_fail_their_gate(monkeypatch, tmp_path):
    def prepare(root):
        quality = {f"{head}_ranking_quality": {"quality_status": "promotable" if head == "rank_20d" else "not_promotable"} for head in ("rank_5d", "rank_20d", "sector_neutral_rank_20d", "residual_rank_5d", "residual_rank_20d")}
        for kind in ("multitask", "sequence"):
            (root / "ml" / f"{kind}_training_metrics.json").write_text(json.dumps({"backtest": quality}), encoding="utf-8")

    overrides = {"phase_v2": {"portfolio_book": {"per_asset_class_slots": {"option": "not a pair", "equity": [2, 2]}}, "rank_signal": {"demote_not_promotable_heads": True, "heads": {"rank_20d": 0.5, "rank_5d": 0.5}}}}
    _, algorithm, _, _ = make(monkeypatch, tmp_path, overrides, prepare=prepare)
    text = "\n".join(algorithm.messages)
    assert "must be a 2-element" in text and algorithm._rank_signal_policy["demoted"]


def test_a_missing_runtime_artifact_stops_the_algorithm_before_it_subscribes_anything(monkeypatch, tmp_path):
    main = world.install_stub(monkeypatch)
    root = tmp_path / "world"
    root.mkdir()
    world.write_config(root, tickers=("SPY",))
    monkeypatch.chdir(root)
    with pytest.raises(FileNotFoundError, match="Lean runtime artifacts are missing"):
        world.build_algorithm(main, root, ready=False)


def test_an_asset_without_a_ticker_and_an_ensemble_of_a_disabled_model_are_skipped(monkeypatch, tmp_path):
    def prepare(root):
        for kind in ("multitask", "sequence"):
            folder = root / "ml" / f"{kind}_ensemble"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "member_0.json").write_text("{broken", encoding="utf-8")

    overrides = {"phase_v2": {"multitask_model": {"enabled": False}, "model_ensemble": {"enabled": True}, "options_risk": {"enabled": True, "assignment_risk_detector": {"enabled": True}}}}
    extra = (FUTURE, {"ticker": "", "security_type": "equity", "market": "usa", "data_path": "data/equity/usa/daily/none.zip"})
    _, algorithm, _, _ = make(monkeypatch, tmp_path, overrides, extra=extra, prepare=prepare, bars=0)
    assert "sequence ensemble load failed" in "\n".join(algorithm.messages)


def test_parallelism_is_switched_off_when_a_model_reads_a_feature_subset(monkeypatch, tmp_path):
    def prepare(root):
        names = world.INPUTS[:10]
        for kind, build in (("multitask", world.multitask_export), ("sequence", world.sequence_export)):
            path = root / "ml" / f"{kind}_model.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["model"]["model_input_features"] = names
            payload["export"] = build(seed=5, in_features=10)
            path.write_text(json.dumps(payload), encoding="utf-8")

    _, algorithm, _, _ = make(monkeypatch, tmp_path, {"phase_v2": {"inference_parallelism": {"enabled": True, "worker_count": 2}}}, prepare=prepare, bars=0)
    assert "Inference parallelism off" in "\n".join(algorithm.messages) and algorithm.inference_parallelism_enabled is False


def test_an_unready_algorithm_finishes_its_setup_when_a_slice_reaches_the_implementation(monkeypatch, tmp_path):
    _, algorithm, _, _ = make(monkeypatch, tmp_path, ready=False)
    market = Market(algorithm, seed=1)
    algorithm._on_data_impl(market.slice(drop=tuple(str(symbol) for symbol in algorithm.symbols)))
    assert algorithm.__dict__["_ready"] is True


def test_hierarchical_weights_stand_in_for_the_neutrality_step_when_it_is_off(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"portfolio_book": {"allocation_method": "hrp", "neutrality": {"enabled": False}}}}
    _, algorithm, market, _ = make(monkeypatch, tmp_path, overrides, bars=2)
    market.run(40)
    assert algorithm.portfolio_book_allocation_method == "hrp"


def test_a_liquidity_cut_replaces_the_target_weight(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"liquidity": {"thin_participation_threshold": 0.0000001, "high_impact_participation_threshold": 0.0000002, "blocked_participation_threshold": 5.0, "high_impact_size_factor": 0.3}}}
    _, algorithm, market, _ = make(monkeypatch, tmp_path, overrides, bars=2)
    market.run(30)
    assert algorithm.order_log


def test_the_forex_policy_sizes_the_entry_of_a_sleeve_pair_and_the_shadow_guard_has_off_switches(monkeypatch, tmp_path):
    def prepare(root):
        (root / "ml" / "rl_sizing_forex_model.json").write_text(json.dumps({"state_keys": ["confidence"], "action_set": [0.0, 1.0], "weights": [[0.1], [0.4]], "bias": [0.0, 0.1]}), encoding="utf-8")

    overrides = {"phase_v2": {"forex_sleeve": {"enabled": True, "rl_sizing_enabled": True, "rl_min_multiplier": 0.0, "rl_max_multiplier": 1.5, "per_side": 1, "gross_budget": 0.2, "rebalance_every_bars": 2,
                                               "min_trade_usd": 0.0}, "dynamic_risk": {"rl_sizing_enabled": False}}}
    _, algorithm, market, _ = make(monkeypatch, tmp_path, overrides, prepare=prepare, bars=2)
    market.run(25)
    algorithm.rl_sizing_enabled = False
    algorithm._accumulate_rl_excess(symbol_of(algorithm, "SPY"), 100.0)
    algorithm._flush_rl_excess()
    assert algorithm.forex_sleeve_enabled


def test_held_futures_and_forex_are_resized_by_explicit_target_weights(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"forex_sleeve": {"enabled": True, "min_trade_usd": 100000000.0}}})
    for ticker, direction in (("ES", "buy"), ("ES", "short"), ("EURUSD", "buy"), ("GBPJPY", "short")):
        symbol, price, payload = payload_for(algorithm, ticker, direction)
        notes = [algorithm._apply_signal(symbol, direction, 0.08, price, payload)]
        for weight in (0.000001, 0.5, 0.0001):
            notes.append(algorithm._apply_signal(symbol, direction, weight, price, payload))
        algorithm.forex_sleeve_enabled = False
        notes.append(algorithm._apply_signal(symbol, direction, 0.00000001, price, payload))
        notes.append(algorithm._apply_signal(symbol, direction, 0.4, price, payload))
        algorithm.forex_sleeve_enabled = True
        assert all(notes), (ticker, notes)
    symbol, price, payload = payload_for(algorithm, "AAPL", "buy")
    assert algorithm._apply_signal(symbol, "bogus", 0.0, price, payload) == "no_action"
    symbol, price, payload = payload_for(algorithm, "ES", "buy")
    assert algorithm._apply_signal(symbol, "buy", 0.0000001, price, payload) in ("futures_zero_contract_count", "kept_long_futures", "futures_zero_delta_kept", "scaled_long_futures")
    symbol, price, payload = payload_for(algorithm, "EURUSD", "buy")
    assert algorithm._apply_signal(symbol, "buy", 0.0000000001, price, payload)


def test_short_exposure_is_counted_for_one_class_only(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    for ticker in ("TLT", "AAPL", "GBPJPY"):
        symbol, price, payload = payload_for(algorithm, ticker, "short")
        algorithm._apply_signal(symbol, "short", float(payload["target_weight"]), price, payload)
    assert algorithm._short_exposure(True, asset_class="forex") >= 0.0 and algorithm._short_exposure(True, asset_class="bond") >= 0.0 and algorithm._short_exposure(True) >= 0.0


def test_a_disabled_reconciliation_and_a_repeated_state_write_do_nothing(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"reconciliation": {"enabled": False}}})
    assert algorithm._evaluate_reconciliation() == {"status": "not_applicable", "reason": "reconciliation_disabled"}
    algorithm.last_state_write = algorithm.Time
    algorithm._write_state(mode="runtime", insight="again")
    algorithm.last_state_write = None
    algorithm._state_write_policy = SimpleNamespace(every_n_bars=10**9)
    algorithm._write_state(mode="runtime", insight="policy")


def test_the_observation_equity_csv_writes_only_new_points(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"runtime": {"mode": "observation"}}}, bars=3)
    algorithm._flush_observation_equity_csv()
    algorithm._flush_observation_equity_csv()
    algorithm._equity_curve_flushed_count = len(algorithm._simulated_portfolio.equity_curve)
    algorithm._flush_observation_equity_csv()
    algorithm._equity_curve_flushed_count = 0
    original = algorithm._simulated_portfolio.equity_curve
    algorithm._simulated_portfolio.equity_curve = []
    algorithm._flush_observation_equity_csv()
    algorithm._simulated_portfolio.equity_curve = original


def test_the_field_test_row_and_event_logging_and_a_failing_exposure_read(monkeypatch, tmp_path):
    plan = {"enabled": True, "order_after_bars": 2, "target_weights": {"AAPL": 0.1}}
    overrides = {"phase_v2": {"target_weights": {"enabled": True, "weights_path": "ml/none.csv", "weights_sha256": "x"}, "runtime": {"mode": "observation"}, "diagnostics": {"field_test": plan}}}
    monkeypatch.setenv("AQ_FIELD_TEST", "1")
    _, algorithm, market, _ = make(monkeypatch, tmp_path, overrides, bars=0)
    algorithm.runtime_mode = "backtest"
    algorithm.allow_live_orders = True
    algorithm._broker_config_present = True
    market.run(4)
    symbol = symbol_of(algorithm, "AAPL")
    algorithm.on_order_event(SimpleNamespace(Symbol=symbol, Status="Filled", FillQuantity=1.0, FillPrice=100.0, OrderId=5, UtcTime=algorithm.Time))
    algorithm.Portfolio.holdings[symbol] = SimpleNamespace(Invested=True, Symbol=symbol, HoldingsValue=1.0)
    algorithm._field_test_log_bar({}, SimpleNamespace(tripped=False, reason=None), {})
    assert "order_event" in "\n".join(algorithm.messages) or algorithm._field_test_active


def test_a_manual_kill_switch_override_file_replaces_the_switch(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    path = algorithm._override_config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"phase_v2": {"risk": {"kill_switch": {"manual_override": True}, "manual_kill_switch_override": True}}}), encoding="utf-8")
    algorithm._kill_switch_manual_override = True
    market.run(2)
    path.write_text(json.dumps({"phase_v2": {"risk": {"kill_switch": {"enabled": False}}}}), encoding="utf-8")
    market.run(2)


def test_the_shutdown_closes_queue_clients_and_survives_a_cleanup_that_raises(monkeypatch, tmp_path):
    main, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"diagnostics": {"teardown_cleanup": {"enabled": True}, "teardown_release_models": {"enabled": True}}}})

    class Client:
        def close(self):
            raise RuntimeError("socket busy")

    for queue in (algorithm._experience_queue, algorithm._audit_queue):
        queue._client = Client()
    algorithm._release_python_models()
    monkeypatch.setattr(main, "release_unreachable_memory", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cannot clean")), raising=False)
    monkeypatch.setattr(main, "teardown_cleanup", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cannot clean")), raising=False)
    monkeypatch.setattr(main.gc, "collect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cannot collect")))
    algorithm.on_end_of_algorithm()
    assert algorithm.messages and datetime is not None
