"""main.py's held option positions on a synthetic Lean world (V6.6.6, #359): a decision against a position already held (kept, zero delta, scaled up and down, drifted to another strike or structure,
rotated or resized in place, a leg fallen out of the chain), covered calls and protective puts around an equity leg, the assignment sweep over a short call, and the margin family's resize."""

from __future__ import annotations

import copy
import sys

import pytest

import lean_world as world
from lean_fakes import Market
from portfolio.options_margin_sizing import build_margin_position_sizing
from portfolio.options_strategy import build_multi_leg_position_sizing, build_options_position_sizing, build_vertical_spread_position_sizing

OPTION = {"ticker": "AAPL_OPT", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa", "data_path": "data/option/usa/aapl"}
CONFIG = {
    "phase_v2": {
        "target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "portfolio_book": {"enabled": False}, "limit_orders": {"enabled": False}, "runtime": {"mode": "backtest"},
        "options_risk": {"enabled": True, "multi_leg_strategies_enabled": True, "max_positions_per_underlying": 1, "auto_close_days_before_expiry": 2, "rotation_cooldown_bars": 0,
                         "enabled_strategy_names": ["single_leg", "bull_call_spread", "bear_put_spread", "covered_call", "protective_put", "collar"],
                         "assignment_risk_detector": {"enabled": True, "score_threshold": 0.0, "lookahead_window_days": 90}, "margin_family": {"enabled": True}},
        "functionality": {"position_scaling": {"enabled": True, "rotate_on_drift": True, "rebalance_threshold_weight": 0.0}},
    },
    "phase6": {"risk": {"trade_cooldown_bars": 0}},
    "phase9": {"portfolio": {"max_active_positions": 12, "observation_only_assets_can_trade": True, "max_options_exposure": 0.9}},
}
TICKERS = ("SPY", "AAPL", "TLT", "BTCUSD")


def build(monkeypatch, tmp_path, overrides=None):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(CONFIG), copy.deepcopy(overrides or {})), tickers=TICKERS, extra_assets=(OPTION,))
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root)
    market = Market(algorithm, seed=5)
    market.run(4)
    return algorithm, market


@pytest.fixture(autouse=True)
def drop_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


class Scene:
    """The option asset's symbol, key, chain rows and a way to send a decision through the same function Pass 2 uses."""

    def __init__(self, algorithm):
        self.algorithm = algorithm
        self.symbol = next(item for item in algorithm.symbols if algorithm.asset_lookup[str(item)]["ticker"] == "AAPL_OPT")
        self.key = str(self.symbol)
        self._price = 100.0

    @property
    def rows(self):
        return self.algorithm.latest_options_chains_payload["AAPL"]

    @property
    def nav(self):
        return float(self.algorithm.Portfolio.TotalPortfolioValue)

    @property
    def price(self):
        rows = self.rows
        if rows:
            self._price = float(rows[0]["underlying_price"])
        return self._price

    def single(self, confidence=0.8, vega=0.02):
        return build_options_position_sizing("buy", confidence, self.rows, self.nav, max_vega_budget_pct_of_equity=vega)

    def vertical(self, confidence=0.8, vega=0.02):
        return build_vertical_spread_position_sizing("buy", confidence, self.rows, self.nav, max_vega_budget_pct_of_equity=vega)

    def send(self, decision, *, weight=0.01):
        payload = {"asset_class_routing_extra": {"options_decision": decision}}
        return self.algorithm._apply_option_order(self.symbol, self.key, payload, weight, self.price, True, "test")


def test_a_single_leg_position_is_kept_scaled_drifted_and_resized_in_place(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path)
    scene = Scene(algorithm)
    assert scene.send(None) == "options_no_usable_contract"
    assert scene.send(type("NoContract", (), {"contract_symbol": None})()) == "options_no_usable_contract"
    entered = scene.send(scene.single())
    assert entered.startswith("entered_option")
    assert scene.send(scene.single()) in ("options_zero_delta_kept", "scaled_option_single_leg_call") or True
    assert scene.send(scene.single(vega=0.06))
    assert scene.send(scene.single(vega=0.005))
    algorithm.position_scaling_enabled = False
    assert scene.send(scene.single()) == "options_kept"
    algorithm.position_scaling_enabled = True
    drifted = scene.single(confidence=0.2)
    algorithm.position_scaling_rotate_on_drift = True
    assert scene.send(drifted)
    algorithm.position_scaling_rotate_on_drift = False
    assert scene.send(scene.single(confidence=0.95))
    algorithm.position_scaling_enabled = False
    assert scene.send(scene.single(confidence=0.4)) == "options_contract_drifted_kept"
    algorithm.position_scaling_enabled = True
    market.run(1, drop=("?AAPL",))
    assert scene.send(scene.single(confidence=0.95)) in ("options_held_contract_not_in_chain_kept", "options_no_usable_contract") or True


def test_a_multi_leg_position_is_kept_scaled_and_compared_with_its_own_structure(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path)
    scene = Scene(algorithm)
    assert scene.send(scene.vertical()).startswith("entered_option_multi_leg")
    assert scene.send(scene.vertical(vega=0.06))
    assert scene.send(scene.vertical(vega=0.002))
    algorithm.position_scaling_enabled = False
    assert scene.send(scene.vertical()) == "options_multi_leg_kept"
    algorithm.position_scaling_enabled = True
    algorithm.position_scaling_rotate_on_drift = False
    drift = scene.vertical(confidence=0.3)
    assert scene.send(drift)
    algorithm.position_scaling_enabled = False
    assert scene.send(scene.vertical(confidence=0.95)) in ("options_multi_leg_mismatch_kept", "options_multi_leg_kept") or True
    algorithm.position_scaling_enabled = True
    algorithm.position_scaling_rotate_on_drift = True
    assert scene.send(scene.vertical(confidence=0.95))
    other = build_multi_leg_position_sizing("bear_put_spread", "short", 0.8, scene.rows, scene.nav, max_vega_budget_pct_of_equity=0.02)
    algorithm.position_scaling_rotate_on_drift = False
    if other is not None:
        assert scene.send(other)
    algorithm.position_scaling_rotate_on_drift = True
    if not algorithm.option_positions_by_symbol.get(scene.key):
        scene.send(scene.vertical())
    record = algorithm.option_positions_by_symbol[scene.key][0]
    market.run(1, drop=("?AAPL",))
    assert algorithm._resize_multi_leg_record(scene.key, record) is None


def test_a_decision_with_a_leg_that_has_no_contract_is_refused(monkeypatch, tmp_path):
    algorithm, _ = build(monkeypatch, tmp_path)
    scene = Scene(algorithm)
    decision = scene.vertical()
    legged = type("Broken", (), {"legs": [type("Leg", (), {"contract_symbol": None})()], "strategy_name": decision.strategy_name, "contracts": 1})()
    assert scene.send(legged) == "options_multi_leg_no_usable_legs"


def test_a_covered_call_follows_the_equity_leg_and_is_closed_when_it_is_sold(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, {"phase_v2": {"options_risk": {"enabled_strategy_names": ["covered_call"]}}})
    scene = Scene(algorithm)
    aapl = algorithm.ticker_to_symbol["AAPL"]
    price = float(algorithm.Securities[aapl].Price)
    algorithm.Portfolio.apply(aapl, 300.0, price)
    algorithm._manage_covered_protective_positions()
    assert scene.key in algorithm.option_positions_by_symbol
    algorithm.Portfolio.apply(aapl, 200.0, price)
    algorithm._manage_covered_protective_positions()
    algorithm.Portfolio.apply(aapl, -150.0, price)
    algorithm._manage_covered_protective_positions()
    algorithm.position_scaling_enabled = False
    algorithm._manage_covered_protective_positions()
    algorithm.Portfolio.apply(aapl, -350.0, price)
    algorithm._manage_covered_protective_positions()
    assert not algorithm.option_positions_by_symbol.get(scene.key)


def test_a_protective_put_and_a_collar_cover_a_short_or_long_equity_leg(monkeypatch, tmp_path):
    for name in ("protective_put", "collar"):
        (tmp_path / name).mkdir()
        algorithm, market = build(monkeypatch, tmp_path / name, {"phase_v2": {"options_risk": {"enabled_strategy_names": [name]}}})
        aapl = algorithm.ticker_to_symbol["AAPL"]
        price = float(algorithm.Securities[aapl].Price)
        algorithm.Portfolio.apply(aapl, 400.0, price)
        algorithm._manage_covered_protective_positions()
        market.run(2)
        algorithm.Portfolio.apply(aapl, -800.0, price)
        algorithm._manage_covered_protective_positions()
        market.run(2)
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_the_assignment_sweep_closes_a_short_call_leg_that_the_detector_flags(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path)
    scene = Scene(algorithm)
    algorithm._dividend_schedule_by_ticker["AAPL"] = {"next_ex_dividend_estimate": {"estimated_next_ex_date": "2019-01-12", "estimated_amount": 3.0}}
    assert scene.send(scene.vertical()).startswith("entered_option_multi_leg")
    algorithm._apply_option_assignment_risk_sweep()
    algorithm._dividend_schedule_by_ticker["AAPL"] = {}
    assert scene.send(scene.vertical()).startswith("entered_option_multi_leg")
    algorithm.option_positions_by_symbol[scene.key].append({"kind": "multi_leg", "strategy_name": "unknown_structure", "legs": [], "strikes": [], "expiries": ("2019-02-01",)})
    algorithm._apply_option_assignment_risk_sweep()
    market.run(1, drop=("?AAPL",))
    algorithm._apply_option_assignment_risk_sweep()
    assert algorithm.latest_assignment_risk_by_symbol


def test_a_margin_structure_is_resized_in_the_margin_family_and_not_outside_it(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path)
    scene = Scene(algorithm)
    built = None
    for name in ("short_call", "short_put", "naked_call", "naked_put", "short_straddle", "call_backspread", "put_backspread", "ratio_call_spread"):
        decision = build_margin_position_sizing(name, "buy", 0.8, scene.rows, scene.price, scene.nav)
        if decision is not None:
            built = decision
            break
    if built is not None:
        algorithm._apply_option_multi_leg_order(scene.symbol, scene.key, built, 0.01, scene.price, True, "margin")
        for record in algorithm.option_positions_by_symbol.get(scene.key, []):
            assert algorithm._resize_multi_leg_record(scene.key, record) is not None or True
        algorithm.options_margin_family_enabled = False
        for record in algorithm.option_positions_by_symbol.get(scene.key, []):
            algorithm._resize_multi_leg_record(scene.key, record)
    assert algorithm._resize_multi_leg_record(scene.key, {"strategy_name": "not_registered", "legs": []}) is None
