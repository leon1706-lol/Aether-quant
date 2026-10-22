"""V5.8.0 round file: live (main.py) vs offline (train.py / simulator) parity for this release's shared decisions.

Covers the point-in-time bond duration beta, grouped rank normalisation, the sleeve loss guard, the venue listing guard,
the slippage reference price and the bond sleeve wiring. main.py runs against the same minimal Lean stub as
tests/test_main_wiring.py.
"""

from __future__ import annotations

import datetime
import json
import math
import random
import sys
import types
from collections import deque
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from evaluation.rank_book_simulator import simulate_rank_book
from execution.order_gate import slippage_reference_price
from features.bond_features import resolve_bond_duration_beta_mode, rolling_duration_beta, rolling_duration_beta_series
from portfolio.rank_signal import grouped_cross_sectional_rank_scores, rank_group_by_symbol
from portfolio.sleeve_guard import SleeveGuardConfig
from risk.asset_class_router import asset_listed_on_venue, load_venue_listing_dates

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def main_module():
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = type("QCAlgorithm", (), {})
    stub.Slice = object
    stub.time = datetime.time
    patcher = pytest.MonkeyPatch()
    patcher.setitem(sys.modules, "AlgorithmImports", stub)
    patcher.delitem(sys.modules, "main", raising=False)
    import main  # noqa: PLC0415

    yield main
    sys.modules.pop("main", None)
    patcher.undo()


# ---------------------------------------------------------------- bond duration beta


def _bond_history(n=400, seed=2):
    rng = random.Random(seed)
    closes, levels = [100.0], [2.0]
    for _ in range(1, n):
        delta = rng.gauss(0, 0.05)
        levels.append(levels[-1] + delta)
        closes.append(closes[-1] * (1 - 0.07 * delta + rng.gauss(0, 0.002)))
    return closes, levels


def test_mode_defaults_to_the_pre_v580_full_history_slope():
    assert resolve_bond_duration_beta_mode(None) == ("full_history", 252)
    assert resolve_bond_duration_beta_mode({"bond_duration_beta": {"mode": "rolling", "lookback": 120}}) == ("rolling", 120)
    assert resolve_bond_duration_beta_mode({"bond_duration_beta": {"mode": "weird"}})[0] == "full_history"


def test_train_rolling_column_equals_main_live_value_on_every_row(main_module):
    import train

    closes, levels = _bond_history()
    dates = [datetime.date(2020, 1, 1) + timedelta(days=i) for i in range(len(closes))]
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "close": closes})
    frame["close_to_close_return_1d"] = frame["close"].pct_change()
    fred = {"treasury_10yr": [{"date": d, "value": v} for d, v in zip(dates, levels)]}
    config = {
        "phase1": {
            "features": {"bond_duration_beta": {"mode": "rolling"}},
            "universe": {"assets": [{"ticker": "TLT", "security_type": "equity", "asset_class": "bond", "bond_metadata": {}}]},
        }
    }
    built = train.build_bond_features_by_date({"TLT": frame}, config, fred)["TLT"]["bond_empirical_duration_beta"].tolist()

    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    algorithm.asset_lookup = {"TLT": {"asset_class": "bond", "security_type": "equity"}}
    algorithm.bond_duration_beta_mode, algorithm.bond_duration_beta_lookback = "rolling", 252
    algorithm._bond_rolling_beta_by_symbol = {}
    algorithm._bond_empirical_duration_beta_cache = {}
    algorithm.long_bar_history_size = 260
    algorithm.symbol_long_windows = {"TLT": deque(maxlen=260)}
    algorithm.symbol_treasury_10yr_history = {"TLT": deque(maxlen=260)}
    for index, (close, level) in enumerate(zip(closes, levels)):
        algorithm.bar_index = index
        algorithm.symbol_long_windows["TLT"].append(close)
        algorithm.symbol_treasury_10yr_history["TLT"].append(level)
        live = algorithm._bond_empirical_duration_beta_for_symbol("TLT")
        assert live == pytest.approx(built[index], rel=1e-9, abs=1e-12), index
    assert built[-1] != built[300]  # point-in-time: the value moves, it is not a per-ticker constant


def test_scalar_and_vectorised_rolling_beta_agree_with_holes():
    closes, levels = _bond_history(300)
    levels[50] = None
    closes[120] = None
    series = rolling_duration_beta_series(closes, levels, 100, 30)
    for index in range(len(closes)):
        scalar = rolling_duration_beta(closes[: index + 1], levels[: index + 1], 100, 30)
        assert (scalar is None) == (series[index] is None)
        if scalar is not None:
            assert scalar == pytest.approx(series[index], rel=1e-9)


# ---------------------------------------------------------------- grouped ranking


def test_grouped_normalisation_ranks_inside_each_group():
    groups = rank_group_by_symbol({"A": "equity", "B": "equity", "T": "bond", "H": "bond"}, {"bond": ["bond"]})
    ranks = grouped_cross_sectional_rank_scores({"A": 0.1, "B": 0.2, "T": 9.0, "H": 8.0}, groups)
    assert ranks == {"A": 0.5, "B": 1.0, "H": 0.5, "T": 1.0}


def _book_frame(days=30, seed=4):
    rng = np.random.default_rng(seed)
    rows = []
    for day in range(days):
        for name in range(24):
            kind = "bond" if name >= 16 else "equity"
            score = (10.0 + rng.normal()) if kind == "bond" else rng.normal()  # bond scores on another scale
            rows.append({"date": f"2024-{1 + day // 28:02d}-{1 + day % 28:02d}", "ticker": f"{kind}{name}",
                         "pred": score, "target_return_1d": rng.normal(0, 0.01)})
    return pd.DataFrame(rows)


def test_simulator_grouped_ranking_keeps_one_scale_from_crowding_out_the_other():
    frame = _book_frame()
    base = dict(prediction_column="pred", top_n=3, bottom_n=3, rebalance_every_bars=5, cost_bps_per_side=0.0,
                commission_bps=0.0, gross_exposure=1.0, dollar_neutral=True, sector_neutral=False,
                max_weight_per_name=0.5, min_universe_size=5, normalize_to_percentile=True)
    pooled = simulate_rank_book(frame, **base)
    groups = {f"bond{i}": "bond" for i in range(16, 24)}
    grouped = simulate_rank_book(frame, **base, rank_group_by_ticker=groups)
    assert pooled.num_rebalances == grouped.num_rebalances > 0
    assert pooled.per_date_net_return != grouped.per_date_net_return  # the ranking actually differs


# ---------------------------------------------------------------- sleeve guard in the simulator


def test_simulator_sleeve_guard_flattens_the_book_after_a_loss():
    rows = []
    for day in range(60):
        for name in range(10):
            loss = -0.02 if (name < 5 and 10 <= day < 20) else 0.0  # the longs (high scores) crash for 10 days
            rows.append({"date": f"d{day:03d}", "ticker": f"T{name}", "pred": 10 - name, "target_return_1d": loss})
    frame = pd.DataFrame(rows)
    base = dict(prediction_column="pred", top_n=5, bottom_n=5, rebalance_every_bars=1, cost_bps_per_side=0.0,
                commission_bps=0.0, gross_exposure=1.0, dollar_neutral=True, sector_neutral=False,
                max_weight_per_name=0.5, min_universe_size=5)
    unguarded = simulate_rank_book(frame, **base)
    guard = {"enabled": True, "max_loss_fraction_nav": 0.02, "lookback_bars": 20, "cooldown_bars": 10}
    guarded = simulate_rank_book(frame, **base, sleeve_guard_config=guard)
    assert guarded.num_sleeve_guard_suspended_dates > 0 and unguarded.num_sleeve_guard_suspended_dates == 0
    assert guarded.net_total_return > unguarded.net_total_return
    assert SleeveGuardConfig().enabled is False


# ---------------------------------------------------------------- venue listing guard


def test_listing_guard_live_function_and_simulator_agree(tmp_path):
    path = tmp_path / "listing.json"
    path.write_text('{"assets": {"XRPUSD": {"listed": "2019-02-25", "suspended": [["2021-01-19", "2023-07-13"]]}}}')
    dates = load_venue_listing_dates(path)
    assert not asset_listed_on_venue("XRPUSD", "2019-01-01", dates)
    assert asset_listed_on_venue("XRPUSD", datetime.date(2020, 6, 1), dates)
    assert not asset_listed_on_venue("XRPUSD", "2022-05-05", dates)
    assert asset_listed_on_venue("XRPUSD", "2023-07-13", dates) and asset_listed_on_venue("BTCUSD", "2010-01-01", dates)
    assert load_venue_listing_dates(tmp_path / "missing.json") == {}

    rows = [{"date": day, "ticker": t, "pred": score, "target_return_1d": 0.01 if t == "XRPUSD" else 0.0}
            for day in ("2022-05-02", "2022-05-03") for t, score in (("XRPUSD", 9.0), ("A", 1.0), ("B", 0.5), ("C", 0.0))]
    frame = pd.DataFrame(rows)
    base = dict(prediction_column="pred", top_n=1, bottom_n=1, rebalance_every_bars=1, cost_bps_per_side=0.0,
                commission_bps=0.0, gross_exposure=1.0, dollar_neutral=True, sector_neutral=False,
                max_weight_per_name=1.0, min_universe_size=2)
    free = simulate_rank_book(frame, **base)
    guarded = simulate_rank_book(frame, **base, venue_listing_dates=dates)
    assert free.net_total_return > 0 and guarded.net_total_return == 0.0  # the suspended pair cannot be the long


# ---------------------------------------------------------------- slippage reference (todo lead 3)


def test_reference_is_the_submit_price_only_for_immediate_fills():
    submitted = datetime.datetime(2024, 1, 2, 0, 0)
    assert slippage_reference_price(100.0, 98.0, submitted, submitted) == (100.0, "submit")
    assert slippage_reference_price(100.0, 98.0, submitted, submitted + timedelta(hours=14)) == (98.0, "fill_bar_open")
    assert slippage_reference_price(None, 98.0, submitted, submitted) == (98.0, "fill_bar_open")
    assert slippage_reference_price(100.0, 98.0) == (98.0, "fill_bar_open")


def test_main_auto_reference_measures_a_crypto_market_fill_from_its_submission(main_module):
    submitted = datetime.datetime(2024, 1, 2, 0, 0)
    order = SimpleNamespace(OrderSubmissionData=SimpleNamespace(LastPrice=100.0), CreatedTime=submitted)
    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    algorithm._expected_cost_by_symbol = {"LTCUSD": {"expected_cost_bps": 10.0}}
    algorithm.Securities = {"LTCUSD": SimpleNamespace(Open=96.0)}  # the bar open is hours before the fill
    algorithm.symbol_key_by_option_contract_symbol = {}
    algorithm.pending_limit_orders = {}
    algorithm._slippage_divergence_history = []
    algorithm._slippage_trace = deque(maxlen=20)
    algorithm.slippage_reference_mode = "auto"
    algorithm.Transactions = SimpleNamespace(GetOrderById=lambda order_id: order)
    event = SimpleNamespace(Status=SimpleNamespace(name="Filled"), Symbol="LTCUSD", FillPrice=100.05, FillQuantity=1.0,
                            OrderId=7, UtcTime=submitted)
    algorithm._track_slippage_divergence(event)
    assert algorithm._slippage_divergence_history == [pytest.approx(0.0, abs=1e-6)]  # 5 bps fill - 5 bps expected
    assert algorithm._slippage_trace[0]["reference"] == "submit" and algorithm._slippage_trace[0]["order_id"] == 7
    algorithm._expected_cost_by_symbol = {"LTCUSD": {"expected_cost_bps": 10.0}}
    algorithm.slippage_reference_mode = "fill_bar_open"
    algorithm._track_slippage_divergence(event)
    assert algorithm._slippage_divergence_history[-1] == pytest.approx((100.05 / 96.0 - 1) * 1e4 - 5.0, rel=1e-9)


# ---------------------------------------------------------------- bond sleeve wiring


def _bond_sleeve_algorithm(main_module, **overrides):
    from portfolio.class_sleeve import resolve_class_sleeve_config
    from portfolio.sleeve_guard import resolve_sleeve_guard_config

    bonds = ["TLT", "IEF", "SHY", "HYG", "LQD", "AGG"]
    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    attributes = dict(
        bond_sleeve_config=resolve_class_sleeve_config("bond", {"enabled": True, "per_side": 2, "gross_budget": 0.2}),
        bond_sleeve_enabled=True, _bond_sleeve_allocations={}, _bond_sleeve_formed={}, _bond_sleeve_weights={},
        forex_sleeve_enabled=False, forex_risk_enabled=False, _forex_sleeve_allocations={}, _forex_sleeve_weights={},
        asset_lookup={b: {"asset_class": "bond", "security_type": "equity"} for b in bonds} | {"AMZN": {"asset_class": "equity"}},
        bar_index=1, is_equity_session_bar=True, _is_trading_eligible=lambda symbol: True,
        sleeve_guard_configs={"bond": resolve_sleeve_guard_config({"enabled": True, "max_loss_fraction_nav": 0.01,
                                                                    "lookback_bars": 10, "cooldown_bars": 5})},
        symbols=bonds,
    )
    attributes.update(overrides)
    for name, value in attributes.items():
        setattr(algorithm, name, value)
    algorithm._sleeve_guard_state = {"bond": {"increments": deque(maxlen=11), "last_level": None, "suspended_until": None,
                                              "active": True, "reason": "", "drawdown": 0.0}}
    scores = dict(zip(bonds, [0.9, 0.8, 0.5, 0.45, 0.2, 0.1]))
    state = {b: {"raw_rank_score": s, "symbol": b} for b, s in scores.items()}
    state["AMZN"] = {"raw_rank_score": 0.99, "symbol": "AMZN"}
    return algorithm, state


def test_bond_sleeve_ranks_bonds_among_themselves_and_takes_them_out_of_the_main_pool(main_module):
    algorithm, state = _bond_sleeve_algorithm(main_module)
    algorithm._update_bond_sleeve(state)
    roles = {s: a.role for s, a in algorithm._bond_sleeve_allocations.items()}
    assert roles == {"TLT": "long", "IEF": "long", "LQD": "short", "AGG": "short"}
    assert sum(abs(w) for w in algorithm._bond_sleeve_weights.values()) == pytest.approx(0.2)
    assert algorithm._sleeve_class_for_asset({"asset_class": "bond"}) == "bond"
    assert algorithm._sleeve_class_for_asset({"asset_class": "equity"}) is None
    assert algorithm._sleeve_class_for_asset({"asset_class": "forex"}) is None  # forex trading off


def test_bond_sleeve_guard_suspends_the_sleeve_after_a_loss(main_module):
    algorithm, state = _bond_sleeve_algorithm(main_module)
    algorithm._update_bond_sleeve(state)
    levels = iter([0.0, -600.0, -1500.0])
    holdings = {}

    class _Portfolio:
        TotalPortfolioValue = 100_000.0

        def __getitem__(self, symbol):
            return holdings.get(symbol, SimpleNamespace(NetProfit=0.0, UnrealizedProfit=0.0))

    algorithm.Portfolio = _Portfolio()
    for bar in range(3):
        holdings["TLT"] = SimpleNamespace(NetProfit=0.0, UnrealizedProfit=next(levels))
        algorithm.bar_index = 10 + bar
        algorithm._update_sleeve_guards()
    assert algorithm._sleeve_guard_state["bond"]["active"] is False
    assert algorithm._bond_sleeve_allocations == {} and algorithm._bond_sleeve_weights == {}


def test_main_reads_the_shared_v580_functions():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    flat = " ".join(source.split())
    assert "grouped_cross_sectional_rank_scores( raw_scores_by_symbol, self._rank_group_by_symbol," in flat
    assert "asset_listed_on_venue(symbol_key" in source
    assert "evaluate_sleeve_guard(" in source and "rolling_duration_beta(" in source
    assert math.isfinite(1.0)


# ---------------------------------------------------------------- RL sizing offline hook + shadow guard


def _rl_model(prefer_index: int):
    from risk.rl_sizing import RL_SIZING_STATE_KEYS

    keys = list(RL_SIZING_STATE_KEYS)
    actions = [0.9, 1.0, 1.1]
    bias = [10.0 if index == prefer_index else 0.0 for index in range(3)]
    return {"state_keys": keys, "actions": actions, "weights": [[0.0] * len(keys) for _ in actions], "bias": bias,
            "mean": [0.0] * len(keys), "scale": [1.0] * len(keys)}


def _rl_row():
    from risk.rl_sizing import RL_SIZING_STATE_KEYS

    row = {key: 0.1 for key in RL_SIZING_STATE_KEYS if key != "confidence"}
    row.update(close=100.0, volume=5e6, rolling_volatility_20d=0.015, liquidity_spread_proxy=0.0005)
    return row


def _rl_config(guard=None):
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    risk = config["phase_v2"]["dynamic_risk"]
    risk.update(rl_sizing_enabled=True, min_rl_multiplier=0.9, max_rl_multiplier=1.1)
    if guard:
        risk["rl_shadow_guard"] = guard
    return config


def test_offline_member_weight_applies_the_live_rl_multiplier():
    from evaluation.live_parity import build_live_member_weight_fn

    config = _rl_config()
    plain = build_live_member_weight_fn(config, security_type_by_ticker={"AAA": "equity"}, rl_model=None)
    boosted = build_live_member_weight_fn(config, security_type_by_ticker={"AAA": "equity"}, rl_model=_rl_model(2))
    kwargs = dict(symbol="AAA", date="2024-01-02", base_weight=0.05, held_weight=0.05, predicted_rank=0.95, row=_rl_row())
    base, sized = plain(**kwargs), boosted(**kwargs)
    shrunk = build_live_member_weight_fn(config, security_type_by_ticker={"AAA": "equity"}, rl_model=_rl_model(0))(**kwargs)
    # the multiplier enters the live sizing chain before liquidity / net edge / floor (non-linear afterwards)
    assert shrunk != base and sized != base
    from risk.position_sizing import build_dynamic_position_sizing
    from risk.rl_sizing import build_rl_sizing_state

    common = dict(base_target_weight=0.05, confidence=0.9, rolling_volatility=0.015, max_position_weight=0.25)
    with_rl = build_dynamic_position_sizing(**common, rl_model=_rl_model(2), rl_state=build_rl_sizing_state(_rl_row(), 0.9),
                                            rl_sizing_enabled=True, min_rl_multiplier=0.9, max_rl_multiplier=1.1)
    assert with_rl.rl_multiplier == pytest.approx(1.1)


def test_offline_shadow_guard_switches_rl_off_after_it_costs_money():
    from evaluation.live_parity import build_live_member_weight_fn

    guard = {"enabled": True, "window_bars": 5, "tolerance_nav_fraction": 0.0001}
    returns = {"2024-01-02": {"AAA": -0.05}, "2024-01-03": {"AAA": -0.05}}
    fn = build_live_member_weight_fn(_rl_config(guard), security_type_by_ticker={"AAA": "equity"}, rl_model=_rl_model(2),
                                     daily_returns_by_date=returns)
    plain = build_live_member_weight_fn(_rl_config(guard), security_type_by_ticker={"AAA": "equity"}, rl_model=None)
    first = fn(symbol="AAA", date="2024-01-01", base_weight=0.05, held_weight=0.0, predicted_rank=0.95, row=_rl_row())
    later = fn(symbol="AAA", date="2024-01-03", base_weight=0.05, held_weight=first, predicted_rank=0.95, row=_rl_row())
    assert fn.rl_state["allows"] is False and len(fn.rl_state["history"]) == 2
    expected = plain(symbol="AAA", date="2024-01-03", base_weight=0.05, held_weight=first, predicted_rank=0.95, row=_rl_row())
    assert later == pytest.approx(expected, rel=1e-12)  # back to constant sizing


def test_main_rl_shadow_guard_accumulates_per_fresh_bar_and_flushes_per_tick(main_module):
    from risk.rl_sizing import resolve_rl_shadow_guard

    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    algorithm.rl_sizing_enabled = True
    algorithm.rl_shadow_guard = resolve_rl_shadow_guard({"enabled": True, "window_bars": 3, "tolerance_nav_fraction": 0.0001})
    algorithm._rl_excess_history = deque(maxlen=4)
    algorithm._rl_multiplier_by_symbol = {"AAA": 1.1}
    algorithm._rl_shadow_allows = True
    algorithm.symbol_long_windows = {"AAA": deque([100.0], maxlen=260)}
    algorithm.Portfolio = type("P", (), {"TotalPortfolioValue": 100_000.0,
                                         "__getitem__": lambda self, s: SimpleNamespace(Invested=True, HoldingsValue=11_000.0)})()
    algorithm._accumulate_rl_excess("AAA", 95.0)  # -5% on an RL-boosted 11% position
    algorithm._flush_rl_excess()
    expected = 0.11 * (1 - 1 / 1.1) * -0.05
    assert list(algorithm._rl_excess_history) == [pytest.approx(expected)]
    assert algorithm._rl_shadow_allows is False


# ---------------------------------------------------------------- batched flat inference (latency)


def test_cluster_uses_precomputed_flat_results_and_still_falls_back_per_symbol(main_module):
    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    calls = []
    algorithm._run_model = lambda inputs: calls.append("baseline") or 0.4
    algorithm._run_multitask_model = lambda inputs: calls.append("multitask") or {"direction": 0.6}
    algorithm._run_sequence_model = lambda symbol: {"direction": 0.5}
    algorithm._run_expert_models = lambda inputs: {}
    algorithm._run_expert_multitask_models = lambda inputs: ({}, {})
    precomputed = algorithm._run_inference_cluster_sequential(
        [0.0], "AAA", precomputed_baseline_probability=0.7, precomputed_multitask_result={"direction": 0.9}
    )
    assert calls == [] and precomputed["baseline_probability"] == 0.7 and precomputed["multitask_result"] == {"direction": 0.9}
    # a precomputed None (a failed multitask model) is a result too, not "missing"
    assert algorithm._run_inference_cluster_sequential([0.0], "AAA", precomputed_multitask_result=None)["multitask_result"] is None
    calls.clear()
    fallback = algorithm._run_inference_cluster_sequential([0.0], "AAA")
    assert calls == ["baseline", "multitask"] and fallback["baseline_probability"] == 0.4


# ---------------------------------------------------------------- class weight caps


def test_class_weight_caps_clip_names_scale_the_class_and_spare_the_exempt():
    from portfolio.book_construction import apply_class_weight_caps, resolve_class_weight_caps

    caps = resolve_class_weight_caps({"crypto": {"per_name_cap": 0.01, "class_gross_cap": 0.02, "exempt": ["BTCUSD"]},
                                      "bond": {"enabled": False, "per_name_cap": 0.001}, "forex": {}})
    assert set(caps) == {"crypto"}
    classes = {"BTCUSD": "crypto", "ETHUSD": "crypto", "ADAUSD": "crypto", "DOGEUSD": "crypto", "AAPL": "equity"}
    weights = {"BTCUSD": 0.08, "ETHUSD": 0.05, "ADAUSD": -0.05, "DOGEUSD": 0.004, "AAPL": 0.1}
    capped = apply_class_weight_caps(weights, classes, caps)
    assert capped["BTCUSD"] == 0.08 and capped["AAPL"] == 0.1  # exempt / other class untouched
    gross = abs(capped["ETHUSD"]) + abs(capped["ADAUSD"]) + abs(capped["DOGEUSD"])
    assert gross == pytest.approx(0.02) and capped["ETHUSD"] > 0 > capped["ADAUSD"]  # clipped to .01,.01,.004 then scaled
    assert weights["ETHUSD"] == 0.05  # input untouched
    assert apply_class_weight_caps(weights, classes, {}) == weights


def test_simulator_applies_the_class_caps_after_neutrality():
    rows = []
    for day in range(40):
        for index in range(12):
            rows.append({"date": f"d{day:03d}", "ticker": f"T{index}", "pred": 12.0 - index, "target_return_1d": 0.001 * (12 - index)})
    frame = pd.DataFrame(rows)
    metadata = {f"T{i}": {"asset_class": "crypto" if i in (0, 11) else "equity", "trading_eligible": True} for i in range(12)}
    base = dict(prediction_column="pred", top_n=3, bottom_n=3, rebalance_every_bars=5, cost_bps_per_side=0.0, commission_bps=0.0,
                gross_exposure=1.0, dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.5, min_universe_size=5,
                candidate_metadata_by_ticker=metadata)
    free = simulate_rank_book(frame, **base)
    capped = simulate_rank_book(frame, **base, class_weight_caps={"crypto": {"per_name_cap": 0.01, "class_gross_cap": None, "exempt": frozenset()}})
    assert capped.mean_gross_exposure < free.mean_gross_exposure


def test_crypto_graduates_guard_suspends_non_exempt_crypto_but_never_the_core(main_module):
    from portfolio.book_construction import resolve_class_weight_caps
    from portfolio.sleeve_guard import resolve_sleeve_guard_config

    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    algorithm.class_weight_caps = resolve_class_weight_caps({"crypto": {"per_name_cap": 0.01, "class_gross_cap": 0.05, "exempt": ["BTCUSD", "LTCUSD"]}})
    algorithm.asset_lookup = {s: {"asset_class": "crypto"} for s in ("BTCUSD", "LTCUSD", "ADAUSD", "DOGEUSD")} | {"AAPL": {"asset_class": "equity"}}
    algorithm.symbols = list(algorithm.asset_lookup)
    algorithm.forex_sleeve_enabled = algorithm.forex_risk_enabled = algorithm.bond_sleeve_enabled = False
    algorithm.sleeve_guard_configs = {"crypto_graduates": resolve_sleeve_guard_config({"enabled": True, "max_loss_fraction_nav": 0.01,
                                                                                         "lookback_bars": 10, "cooldown_bars": 5})}
    algorithm._sleeve_guard_state = {"crypto_graduates": {"increments": deque(maxlen=11), "last_level": None, "suspended_until": None,
                                                          "active": True, "reason": "", "drawdown": 0.0}}
    holdings = {}

    class _Portfolio:
        TotalPortfolioValue = 100_000.0

        def __getitem__(self, symbol):
            return holdings.get(symbol, SimpleNamespace(NetProfit=0.0, UnrealizedProfit=0.0))

    algorithm.Portfolio = _Portfolio()
    assert not algorithm._graduate_suspended("ADAUSD", algorithm.asset_lookup["ADAUSD"])
    for bar, loss in enumerate([0.0, -700.0, -1600.0]):
        holdings["BTCUSD"] = SimpleNamespace(NetProfit=-50_000.0, UnrealizedProfit=0.0)  # the core's P&L is ignored
        holdings["ADAUSD"] = SimpleNamespace(NetProfit=0.0, UnrealizedProfit=loss)
        algorithm.bar_index = 20 + bar
        algorithm._update_sleeve_guards()
    assert algorithm._graduate_suspended("ADAUSD", algorithm.asset_lookup["ADAUSD"])
    assert algorithm._graduate_suspended("DOGEUSD", algorithm.asset_lookup["DOGEUSD"])
    assert not algorithm._graduate_suspended("BTCUSD", algorithm.asset_lookup["BTCUSD"])
    assert not algorithm._graduate_suspended("AAPL", algorithm.asset_lookup["AAPL"])


def test_bond_sleeve_can_rank_by_momentum_like_the_research(main_module):
    from portfolio.class_sleeve import resolve_class_sleeve_config

    config = resolve_class_sleeve_config("bond", {"enabled": True, "per_side": 1, "gross_budget": 0.2, "signal": "ts_momentum"})
    assert config.signal == "ts_momentum" and resolve_class_sleeve_config("bond", {"signal": "weird"}).signal == "model_rank"
    algorithm, state = _bond_sleeve_algorithm(main_module, bond_sleeve_config=config)
    rising = [100.0 * (1.001 + 0.0004 * (i % 3)) ** i for i in range(200)]
    falling = [100.0 * (0.999 - 0.0004 * (i % 3)) ** i for i in range(200)]
    flat_noise = [100.0 + (0.3 if i % 2 else -0.3) for i in range(200)]
    algorithm.symbol_long_windows = {"TLT": deque(rising), "IEF": deque(falling), "SHY": deque(flat_noise),
                                     "HYG": deque(rising[:50]), "LQD": deque(flat_noise), "AGG": deque(falling)}
    # the model scores in `state` would pick TLT/IEF long; momentum must pick the rising names instead
    algorithm._update_bond_sleeve(state)
    roles = {s: a.role for s, a in algorithm._bond_sleeve_allocations.items()}
    assert roles.get("TLT") == "long" and roles.get("IEF") == "short" or roles.get("AGG") == "short"
    assert "HYG" not in roles  # fewer than 121 closes: no momentum score, left out rather than scored 0


def test_sleeve_guard_snapshot_is_json_safe_and_mirrors_the_runtime_state(main_module):
    import json

    algorithm, _state = _bond_sleeve_algorithm(main_module)
    algorithm._sleeve_guard_state["bond"].update(active=False, reason="sleeve_loss_guard_tripped", drawdown=-0.013, suspended_until=42)
    snapshot = algorithm._sleeve_guard_snapshot()
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert snapshot["bond"] == {"enabled": True, "active": False, "reason": "sleeve_loss_guard_tripped",
                                "drawdown": -0.013, "suspended_until_bar": 42}
