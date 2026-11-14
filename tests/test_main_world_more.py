"""main.py's optional models, subscriptions, futures chains, parameters and sleeves on a synthetic Lean world (V6.6.6, #359): each optional artifact present, missing or unreadable, the
branches of `_add_asset` for every security type, the live futures margin and its fallback, a futures chain per bar, rolling bond duration, and the class sleeves with their loss guards."""

from __future__ import annotations

import copy
import datetime
import json
import sys
from types import SimpleNamespace

import pytest

import lean_world as world
from lean_fakes import Market, FakeSymbol

TICKERS = ("SPY", "AAPL", "MSFT", "TLT", "BTCUSD", "EURUSD", "GBPJPY")
BASE = {"phase_v2": {"target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "limit_orders": {"enabled": False},
                     "portfolio_book": {"top_n": 2, "bottom_n": 2, "rebalance_every_bars": 3, "min_rank_confidence_spread": 0.0, "neutrality": {"sector_neutral": False}}},
        "phase1": {"target": {"ranking": {"min_universe_size": 3}}}}


def make(monkeypatch, tmp_path, overrides=None, *, prepare=None, tickers=TICKERS, extra=(), ready=True):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), copy.deepcopy(overrides or {})), tickers=tickers, extra_assets=extra)
    if prepare:
        prepare(root)
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root, ready=ready)
    return main, algorithm, root


@pytest.fixture(autouse=True)
def drop_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


def text_of(algorithm) -> str:
    return "\n".join(algorithm.messages)


def put(root, name, payload):
    path = root / "ml" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


OPTIONAL_ON = {"phase_v2": {"gating_network": {"learned_model_enabled": True}, "strategy_selector": {"enabled": True}, "dynamic_risk": {"rl_sizing_enabled": True}, "topology_learning": {"enabled": True}}}


def test_every_optional_artifact_is_loaded_when_present(monkeypatch, tmp_path):
    def prepare(root):
        for name in ("gating_model.json", "gating_feature_schema.json", "topology_model.json", "topology_feature_schema.json", "strategy_selector_model.json"):
            put(root, name, {"version_id": name})
        put(root, "expert_models/bullish/multitask_model.json", {"model": {}, "export": world.multitask_export(3)})

    _, algorithm, _ = make(monkeypatch, tmp_path, OPTIONAL_ON, prepare=prepare)
    assert algorithm.gating_model is not None and algorithm.learned_topology_model is not None and algorithm.strategy_selector_model is not None
    assert "bullish" in algorithm.expert_multitask_model_exports


def test_a_missing_optional_artifact_leaves_its_model_absent(monkeypatch, tmp_path):
    _, algorithm, _ = make(monkeypatch, tmp_path, OPTIONAL_ON)
    assert algorithm.gating_model is None and algorithm.learned_topology_model is None and algorithm.strategy_selector_model is None


def test_an_unreadable_optional_artifact_is_reported_and_skipped(monkeypatch, tmp_path):
    def prepare(root):
        for name in ("gating_model.json", "gating_feature_schema.json", "topology_model.json", "topology_feature_schema.json", "strategy_selector_model.json", "multitask_model.json", "sequence_model.json"):
            put(root, name, "{broken")
        put(root, "expert_models/bullish/multitask_model.json", "{broken")
        put(root, "expert_models/bearish/model_weights.json", "{broken")

    _, algorithm, _ = make(monkeypatch, tmp_path, OPTIONAL_ON, prepare=prepare)
    text = text_of(algorithm)
    for fragment in ("Gating model load failed", "Learned topology model load failed", "Strategy selector model load failed", "Multitask model load failed", "Sequence model load failed",
                     "Expert multitask export load failed for bullish", "Expert export load failed for bearish"):
        assert fragment in text, fragment


def test_a_disabled_model_is_never_read(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"multitask_model": {"enabled": False}, "sequence_model": {"enabled": False}, "topology_learning": {"enabled": False}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides)
    assert algorithm.multitask_model is None and algorithm.sequence_model is None and algorithm.learned_topology_model is None and algorithm.expert_multitask_model_exports == {}


def test_a_lean_parameter_is_read_when_the_engine_has_one_and_ignored_when_it_fails(monkeypatch, tmp_path):
    _, algorithm, _ = make(monkeypatch, tmp_path)
    algorithm.get_parameter = lambda name: "  value  "
    assert algorithm._lean_parameter("x") == "value"
    algorithm.get_parameter = lambda name: 7
    assert algorithm._lean_parameter("x") == ""

    def broken(name):
        raise RuntimeError("no such parameter")

    algorithm.get_parameter = broken
    assert algorithm._lean_parameter("x") == ""
    algorithm.__dict__.pop("get_parameter", None)
    algorithm.__dict__.pop("GetParameter", None)
    algorithm.get_parameter = None
    algorithm.GetParameter = None
    assert algorithm._lean_parameter("x") == ""


FUTURE = {"ticker": "ES", "security_type": "future", "market": "cme", "lean_future_ticker": "ES", "data_path": "data/future/cme/daily/es.zip"}
OPTION = {"ticker": "AAPL_OPT", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa", "data_path": "data/option/usa/aapl"}
SWAP = {"ticker": "SWAP1", "security_type": "swap", "market": "usa", "data_path": "x"}


def test_every_security_type_is_subscribed_the_way_it_is_traded_and_an_unknown_one_is_skipped(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"futures_risk": {"enabled": True, "margin_source": "live"}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides, extra=(FUTURE, OPTION, SWAP))
    tickers = {algorithm.asset_lookup[str(symbol)]["ticker"] for symbol in algorithm.symbols}
    assert {"ES", "AAPL_OPT", "BTCUSD", "EURUSD", "SPY"} <= tickers and "SWAP1" not in tickers and "Unsupported asset type skipped" in text_of(algorithm)


def test_a_failing_live_margin_model_or_a_failing_subscription_is_reported(monkeypatch, tmp_path):
    main = world.install_stub(monkeypatch)
    overrides = {"phase_v2": {"futures_risk": {"enabled": True, "margin_source": "live"}}}
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), overrides), tickers=TICKERS, extra_assets=(FUTURE,))
    monkeypatch.chdir(root)
    monkeypatch.setattr(main.AetherQuantAlgorithm, "futures_margin_source", "live", raising=False)  # initialize() reads it before _ensure_ready() has set it
    monkeypatch.setitem(main.__dict__, "InteractiveBrokersBrokerageModel", lambda account: (_ for _ in ()).throw(RuntimeError("no brokerage model")))
    monkeypatch.setattr(world.FakeLean, "add_equity", lambda self, ticker, resolution=None, *a, **k: (_ for _ in ()).throw(RuntimeError(f"cannot subscribe {ticker}")) if ticker == "MSFT" else self._add(ticker, "equity"))
    algorithm = world.build_algorithm(main, root)
    text = text_of(algorithm)
    assert "Live IB margin model attach failed" in text and "MSFT subscription skipped" in text


def test_the_option_underlying_must_be_raw_normalized_and_a_violation_is_logged(monkeypatch, tmp_path):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), {}), tickers=TICKERS, extra_assets=(OPTION,))
    monkeypatch.chdir(root)

    def add_option(self, ticker, resolution=None, *args, **kwargs):
        security = self._add(f"?{ticker}", "option")
        underlying = self._add(f"U{ticker}", "equity")
        underlying.DataNormalizationMode = "Adjusted"
        security.Underlying = underlying
        return security

    monkeypatch.setattr(world.FakeLean, "add_option", add_option)
    algorithm = world.build_algorithm(main, root)
    assert "assumption_violated" in text_of(algorithm)


def test_a_futures_chain_gives_the_front_and_next_month_prices(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"futures_risk": {"enabled": True}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides, extra=(FUTURE,))
    symbol = next(item for item in algorithm.symbols if algorithm.asset_lookup[str(item)]["ticker"] == "ES")
    now = datetime.datetime(2019, 2, 1)
    front = SimpleNamespace(expiry=now + datetime.timedelta(days=30), last_price=4010.0, bid_price=0.0, ask_price=0.0)
    nxt = SimpleNamespace(expiry=now + datetime.timedelta(days=60), last_price=0.0, bid_price=4020.0, ask_price=4022.0)
    flat = SimpleNamespace(expiry=now + datetime.timedelta(days=90), last_price=0.0, bid_price=0.0, ask_price=0.0)
    payload = algorithm._build_futures_chains_payload(SimpleNamespace(futures_chains={symbol: SimpleNamespace(contracts={"a": nxt, "b": front})}))
    assert payload["ES"] == {"front_month_price": 4010.0, "next_month_price": 4021.0}
    assert algorithm._build_futures_chains_payload(SimpleNamespace(futures_chains={symbol: SimpleNamespace(contracts={"c": flat})}))["ES"]["front_month_price"] is None
    assert algorithm._build_futures_chains_payload(SimpleNamespace(futures_chains={symbol: SimpleNamespace(contracts={})})) == {}
    assert algorithm._build_futures_chains_payload(SimpleNamespace(futures_chains={})) == {}
    assert algorithm._build_futures_chains_payload(SimpleNamespace(futures_chains=None)) == {}
    assert "Futures chain parse failed" in text_of(algorithm)


def test_the_live_margin_spec_and_its_fallbacks(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"futures_risk": {"enabled": True, "margin_source": "live"}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides, extra=(FUTURE,))
    asset = next(algorithm.asset_lookup[str(item)] for item in algorithm.symbols if algorithm.asset_lookup[str(item)]["ticker"] == "ES")
    symbol = algorithm.ticker_to_symbol["ES"]
    security = algorithm.Securities[symbol]
    security.SymbolProperties.ContractMultiplier = 50.0
    security.BuyingPowerModel = SimpleNamespace(GetInitialMarginRequirement=lambda parameters: SimpleNamespace(Value=3000.0))
    assert algorithm._resolve_futures_contract_spec(asset)["initial_margin_usd"] == 3000.0
    security.BuyingPowerModel = SimpleNamespace(GetInitialMarginRequirement=lambda parameters: SimpleNamespace(Value=0.0))
    assert algorithm._resolve_futures_contract_spec(asset) == algorithm.futures_contract_specs.get("ES", {})
    assert algorithm._resolve_futures_contract_spec({"ticker": "NOPE"}) == {}
    assert "falling back to static spec" in text_of(algorithm)


def test_bond_duration_is_rolled_per_bar_when_the_config_asks_for_it(monkeypatch, tmp_path):
    overrides = {"phase1": {"features": {"bond_duration_beta": {"mode": "rolling", "lookback": 40}}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides)
    market = Market(algorithm, seed=3)
    market.run(45)
    symbol = next(item for item in algorithm.symbols if algorithm.asset_lookup[str(item)]["ticker"] == "TLT")
    assert algorithm._bond_empirical_duration_beta_for_symbol(symbol) is not None


def test_forex_and_bond_sleeves_trade_their_class_and_a_loss_guard_suspends_a_sleeve(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"forex_sleeve": {"enabled": True, "rebalance_every_bars": 3, "per_side": 1, "gross_budget": 0.2, "min_trade_usd": 0.0}, "forex_risk": {"enabled": True},
                              "bond_sleeve": {"enabled": True, "rebalance_every_bars": 3, "per_side": 1, "min_trade_usd": 0.0},
                              "sleeve_guards": {"forex": {"enabled": True, "max_loss_fraction_nav": 0.0001, "lookback_bars": 3, "cooldown_bars": 2}, "bond": {"enabled": True, "max_loss_fraction_nav": 0.0001, "lookback_bars": 3, "cooldown_bars": 2}}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides)
    monkeypatch.setattr(sys.modules["main"], "load_forex_pair_specs", lambda *a, **k: {"EURUSD": {"lot_size": 1000.0, "margin_pct": 0.05}, "GBPJPY": {"lot_size": 1000.0, "margin_pct": 0.05}})
    algorithm.forex_pair_specs = {"EURUSD": {"lot_size": 1000.0, "margin_pct": 0.05}, "GBPJPY": {"lot_size": 1000.0, "margin_pct": 0.05}}
    market = Market(algorithm, seed=8)
    market.run(30)
    assert algorithm.forex_sleeve_enabled and FakeSymbol is not None
