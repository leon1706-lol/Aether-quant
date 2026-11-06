"""Cross-module regressions of V6.6.0's audits (Problems.md #283 onward)."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from evaluation.alpha_proof import (
    alpha_proof_report,
    benchmark_daily_returns,
    fresh_sessions,
    measured_annualization,
    period_report,
    r_alpha1,
)
from evaluation.premia_research import annual_sharpe
from evaluation.target_weights_engine import MarketPanel, simulate_target_weights
from evaluation.trial_ledger import append_trial, deflation_inputs, legacy_trials, read_ledger
from execution.order_gate import resolve_order_permission, resolve_risk_exit_permission
from portfolio.premia_signals import align_score_table
from portfolio.target_weights import (
    TargetWeightsConfig,
    load_live_weight_file,
    names_to_exit_without_bars,
    next_unapplied_row,
    no_bar_exit_cost_usd,
    resolve_target_weights_config,
    update_missing_bars,
    write_weight_file,
    write_weights_sidecar,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=0.0, financing_enabled=False,
                             equity_fee_bps=0.0, equity_min_fee_usd=0.0, slippage_bps_by_class={})


def _panel(prices: dict[str, list[float]], dates: list[str], classes: dict[str, str] | None = None) -> MarketPanel:
    tickers = sorted(prices)
    closes = np.array([prices[ticker] for ticker in tickers], dtype=float).T
    return MarketPanel(dates, tickers, closes.copy(), closes, classes or dict.fromkeys(tickers, "equity"), set(dates))


# --- 2.2a: a long book's Sharpe is on excess returns ---------------------------------------------------------------


def test_strategy_excess_takes_the_risk_free_return_off_the_net_capital_invested():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=60)]
    panel = _panel({"SPY": [100.0 * 1.001 ** i for i in range(60)]}, dates)
    result = simulate_target_weights(
        {dates[0]: {"SPY": 1.0}}, panel, CONFIG, start=dates[0], end=dates[-1], rf_dates=[dates[0]], rf_rates=[36.5],
    )
    gap = (result["strategy"] - result["strategy_excess"]).iloc[5:]
    # 36.5% a year is 0.1% a calendar day; the book is about fully invested
    calendar_days = pd.Series([(pd.Timestamp(b) - pd.Timestamp(a)).days for a, b in zip(gap.index[:-1], gap.index[1:])], index=gap.index[1:])
    assert (gap.iloc[1:] / calendar_days).mean() == pytest.approx(0.001, rel=0.05)


def test_strategy_excess_equals_strategy_for_a_flat_book():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=30)]
    panel = _panel({"SPY": [100.0] * 30}, dates)
    result = simulate_target_weights({}, panel, CONFIG, start=dates[0], end=dates[-1], rf_dates=[dates[0]], rf_rates=[5.0])
    pd.testing.assert_series_equal(result["strategy"], result["strategy_excess"])


# --- 2.2c: annualisation -----------------------------------------------------------------------------------------


def test_session_sharpe_is_the_same_with_or_without_weekend_rows():
    rng = np.random.default_rng(3)
    sessions = pd.bdate_range("2020-01-01", periods=800)
    only_sessions = pd.Series(rng.normal(0.0005, 0.01, 800), index=sessions.strftime("%Y-%m-%d"))
    calendar = pd.date_range(sessions[0], sessions[-1]).strftime("%Y-%m-%d")
    with_weekends = only_sessions.reindex(calendar).fillna(0.0)
    labels = list(only_sessions.index)
    assert annual_sharpe(only_sessions, sessions=labels) == pytest.approx(annual_sharpe(with_weekends, sessions=labels))
    # the old fixed sqrt(365) on session rows read about 1.2 times too high
    assert annual_sharpe(only_sessions) / annual_sharpe(only_sessions, sessions=labels) == pytest.approx((365 / 252) ** 0.5)


def test_measured_annualization_needs_weekend_rows_to_keep_365():
    sessions = pd.bdate_range("2024-01-01", periods=40).strftime("%Y-%m-%d")
    calendar = pd.date_range("2024-01-01", periods=40).strftime("%Y-%m-%d")
    assert measured_annualization(sessions, fallback=365.0) == 252.0
    assert measured_annualization(calendar, fallback=365.0) == 365.0


# --- 2.2b: the fresh period is counted in sessions ----------------------------------------------------------------


def test_fresh_sessions_ignore_weekend_rows():
    calendar = pd.date_range("2026-11-03", periods=60).strftime("%Y-%m-%d")
    series = pd.Series(0.0, index=calendar)
    sessions = pd.bdate_range("2026-10-01", "2027-02-01").strftime("%Y-%m-%d")
    assert fresh_sessions(series, sessions) == 44  # 60 calendar days are not 60 sessions


def test_a_short_fresh_period_fails_no_clause():
    report = {"periods": {
        "full": {"alpha": {"t_hac": 2.5}, "dsr": 0.97}, "holdout": {"alpha": {"alpha_annual": 0.02}},
        "fresh": {"n": 7, "alpha": {"alpha_annual": -0.5}, "judgeable": False},
    }}
    assert r_alpha1(report)["failed"] == []


# --- 2.2e: the deflated Sharpe's two routes agree ------------------------------------------------------------------


def test_period_report_uses_ledger_inputs_when_given():
    from evaluation.alpha_proof import deflated_sharpe_from_inputs

    rng = np.random.default_rng(5)
    dates = pd.bdate_range("2020-01-01", periods=600).strftime("%Y-%m-%d")
    y = pd.Series(rng.normal(0.001, 0.01, 600), index=dates)
    deflation = {"N": 158, "var": 0.05}
    report = period_report(y, pd.DataFrame(), annualization=252.0, trial_sharpes=[0.1, 0.2, 5.0], deflation=deflation)
    expected = deflated_sharpe_from_inputs(y.to_numpy(), num_trials=158, trial_variance=0.05, annualization=252.0)
    assert report["dsr"] == expected["value"] and report["dsr_trials"] == 158


# --- 2.2f: N counts each trial once --------------------------------------------------------------------------------


def test_deflation_inputs_on_todays_files_count_128_trials():
    registry_path = ROOT / "ml" / "evaluation" / "trial_registry.json"
    ledger_path = ROOT / "ml" / "evaluation" / "v650" / "trial_ledger.jsonl"
    if not registry_path.exists() or not ledger_path.exists():
        pytest.skip("gitignored evaluation output")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = read_ledger(ledger_path)
    assert deflation_inputs(entries, registry, "selection")["N"] >= 128
    assert len(legacy_trials(registry)) == 78


def test_deflation_inputs_keep_a_phases_variance_to_its_own_window(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    for name, sharpe, window in (("a", 0.1, "v660_selection"), ("b", 0.9, "v660_selection"), ("c", 5.0, "other")):
        append_trial(ledger, trial_id=name, track="T", window=window, role="candidate", annualised_sharpe=sharpe, n_obs=10)
    registry = {"trials": [
        {"phase": "v640", "median_sharpe": 0.3}, {"phase": "v650", "median_sharpe": 9.0}, {"phase": "v660", "median_sharpe": 9.0},
    ]}
    inputs = deflation_inputs(read_ledger(ledger), registry, "v660_selection")
    assert inputs["N"] == 1 + 3  # one legacy trial, three in the ledger; the registry's copies of ledger trials don't count twice
    assert inputs["var"] == pytest.approx(0.32) and inputs["same_window_trials"] == 2


# --- 2.2g: a run's own data root and a complete benchmark table ---------------------------------------------------


def _write_lean_zip(path: Path, rows: list[tuple[str, float]], *, ticker: str) -> None:
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"{date.replace('-', '')} 00:00,{int(c * 10000)},{int(c * 10000)},{int(c * 10000)},{int(c * 10000)},1000" for date, c in rows)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{ticker}.csv", body)


def _crypto_row_zip(path: Path, rows: list[tuple[str, float]], *, ticker: str) -> None:
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"{date.replace('-', '')} 00:00,{c},{c},{c},{c},1000" for date, c in rows)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{ticker}.csv", body)


def test_benchmarks_before_btcs_first_bar_read_zero_not_nan(tmp_path):
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2013-01-01", periods=40)]
    _write_lean_zip(tmp_path / "wide" / "equity" / "usa" / "daily" / "spy.zip", [(d, 100.0 + i) for i, d in enumerate(dates)], ticker="spy")
    _crypto_row_zip(tmp_path / "wide" / "crypto" / "coinbase" / "daily" / "btcusd_trade.zip", [(d, 50.0 + i) for i, d in enumerate(dates[20:])], ticker="btcusd")
    config = {"phase1": {"universe": {"assets": [
        {"ticker": "SPY", "security_type": "equity", "market": "usa", "data_path": "data/equity/usa/daily/spy.zip"},
        {"ticker": "BTCUSD", "security_type": "crypto", "market": "coinbase", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"},
    ]}}}
    returns = benchmark_daily_returns(tmp_path, config, ("SPY", "BTCUSD"), start=dates[0], end=dates[-1], data_dir="wide", required=False)
    assert not returns.isna().any().any()
    assert len(returns) == 39 and (returns["BTCUSD"].iloc[:20] == 0.0).all() and returns["BTCUSD"].iloc[-1] != 0.0


def test_a_required_benchmark_missing_from_the_universe_raises(tmp_path):
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2013-01-01", periods=5)]
    _write_lean_zip(tmp_path / "data" / "equity" / "usa" / "daily" / "spy.zip", [(d, 100.0) for d in dates], ticker="spy")
    config = {"phase1": {"universe": {"assets": [
        {"ticker": "SPY", "security_type": "equity", "market": "usa", "data_path": "data/equity/usa/daily/spy.zip"},
    ]}}}
    with pytest.raises(ValueError, match="AGG"):
        benchmark_daily_returns(tmp_path, config, ("SPY", "AGG"), start=dates[0], end=dates[-1], required=True)


def test_closes_for_universe_reads_the_runs_own_root(tmp_path):
    from evaluation.lean_attribution import closes_for_universe

    dates = ["2013-01-02", "2013-01-03"]
    _write_lean_zip(tmp_path / "wide" / "equity" / "usa" / "daily" / "aaa.zip", [(d, 10.0) for d in dates], ticker="aaa")
    config = {"phase1": {"universe": {"assets": [
        {"ticker": "AAA", "security_type": "equity", "market": "usa", "data_path": "data/equity/usa/daily/aaa.zip"},
    ]}}}
    assert closes_for_universe(config, tmp_path, {"AAA"}, data_dir="wide")["AAA"]
    assert not closes_for_universe(config, tmp_path, {"AAA"}).get("AAA")


# --- 2.2d: a score table's late bars ------------------------------------------------------------------------------


def test_align_score_table_delays_only_the_classes_whose_bar_ends_later():
    table = pd.DataFrame({"AAA": [1.0, 2.0, 3.0], "BTCUSD": [1.0, 2.0, 3.0]}, index=["d1", "d2", "d3"])
    aligned = align_score_table(table, {"AAA": "equity", "BTCUSD": "crypto"})
    assert aligned["AAA"].tolist() == [1.0, 2.0, 3.0]
    assert np.isnan(aligned["BTCUSD"].iloc[0]) and aligned["BTCUSD"].tolist()[1:] == [1.0, 2.0]
    assert table["BTCUSD"].tolist() == [1.0, 2.0, 3.0]


# --- 2.2l: a held name whose bars stop ------------------------------------------------------------------------------


def test_missing_bars_count_only_for_held_names_and_reset_on_a_bar():
    missing = update_missing_bars({}, {"A": 5.0, "B": 0.0, "C": 3.0}, {"A": False, "B": False, "C": True})
    assert missing == {"A": 1}
    assert update_missing_bars(missing, {"A": 5.0}, {"A": False}) == {"A": 2}
    assert update_missing_bars({"A": 2}, {"A": 5.0}, {"A": True}) == {}


def test_names_to_exit_need_the_flag_and_the_count():
    config = TargetWeightsConfig(no_bar_exit=True, no_bar_exit_after=2)
    assert names_to_exit_without_bars({"A": 1, "B": 2, "C": 3}, config) == ["B", "C"]
    assert names_to_exit_without_bars({"B": 5}, TargetWeightsConfig()) == []


def test_no_bar_exit_cost_is_the_classes_haircut_on_the_position():
    config = resolve_target_weights_config({"no_bar_exit": True, "no_bar_haircut_by_class": {"equity": 0.1}})
    assert no_bar_exit_cost_usd(-10.0, 50.0, "equity", config) == pytest.approx(50.0)
    assert no_bar_exit_cost_usd(1.0, 100.0, "crypto", config) == pytest.approx(20.0)


def test_engine_closes_a_dead_name_at_its_last_close_less_the_haircut():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=12)]
    prices = {"AAA": [100.0] * 5 + [np.nan] * 7, "SPY": [100.0] * 12}
    panel = _panel(prices, dates)
    config = TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=0.0, financing_enabled=False, equity_fee_bps=0.0,
                                 equity_min_fee_usd=0.0, slippage_bps_by_class={}, no_bar_exit=True, no_bar_exit_after=2,
                                 no_bar_haircut_by_class={"equity": 0.10})
    result = simulate_target_weights({dates[0]: {"AAA": 0.5}}, panel, config, start=dates[0], end=dates[-1])
    assert [item.split(":")[1] for item in result["no_bar_exits"]] == ["AAA"]
    assert result["no_bar_exits"][0].split(":")[0] == dates[6]
    # half the book lost 10%
    assert result["nav"].iloc[-1] == pytest.approx(95_000.0, rel=1e-3)


def test_engine_without_the_flag_still_holds_a_dead_name():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=12)]
    panel = _panel({"AAA": [100.0] * 5 + [np.nan] * 7, "SPY": [100.0] * 12}, dates)
    result = simulate_target_weights({dates[0]: {"AAA": 0.5}}, panel, CONFIG, start=dates[0], end=dates[-1])
    assert result["no_bar_exits"] == [] and result["nav"].iloc[-1] == pytest.approx(100_000.0)


def test_an_equity_is_not_counted_missing_on_a_day_with_no_equity_session():
    dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-01-01", periods=10)]
    sessions = {d for d in dates if pd.Timestamp(d).dayofweek < 5}
    closes = np.array([[100.0 if d in sessions else np.nan for d in dates], [50.0] * 10]).T
    panel = MarketPanel(dates, ["AAA", "BTCUSD"], closes.copy(), closes, {"AAA": "equity", "BTCUSD": "crypto"}, sessions)
    config = TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=0.0, financing_enabled=False, equity_fee_bps=0.0,
                                 equity_min_fee_usd=0.0, slippage_bps_by_class={}, no_bar_exit=True, no_bar_exit_after=1)
    result = simulate_target_weights({dates[0]: {"AAA": 0.5}}, panel, config, start=dates[0], end=dates[-1])
    assert result["no_bar_exits"] == []


# --- 3.1: a lock takes risk off in every mode that can place orders ------------------------------------------------


@pytest.mark.parametrize("mode, live, broker, expected", [
    ("backtest", False, False, True), ("paper", True, True, True), ("live", True, True, True),
    ("observation", True, True, False), ("paper", False, True, False), ("live", True, False, False), ("weird", True, True, False),
])
def test_risk_exit_permission(mode, live, broker, expected):
    allowed, reason = resolve_risk_exit_permission(mode, live, broker)
    assert allowed is expected and reason.startswith("risk_exit:")
    assert resolve_order_permission(mode, live, broker, True)[0] is expected


def test_a_healthy_lock_still_stops_new_orders_in_paper():
    assert resolve_order_permission("paper", True, True, False)[0] is False


@pytest.fixture
def main_module():
    stub = ModuleType("AlgorithmImports")
    stub.QCAlgorithm = object
    stub.Slice = object
    stub.__all__ = ["QCAlgorithm", "Slice"]
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setitem(sys.modules, "AlgorithmImports", stub)
        sys.modules.pop("main", None)
        import main

        yield main
        sys.modules.pop("main", None)


class _Holding:
    def __init__(self, quantity):
        self.Quantity = quantity
        self.Invested = quantity != 0.0


class _Portfolio:
    def __init__(self, holdings, total=100_000.0):
        self._holdings = holdings
        self.TotalPortfolioValue = total
        self.CashBook = {"USD": SimpleNamespace(AddAmount=lambda amount: self.charges.append(amount))}
        self.charges = []

    def __getitem__(self, symbol):
        return self._holdings.get(symbol, _Holding(0.0))

    @property
    def Values(self):
        return [SimpleNamespace(Invested=h.Invested, Symbol=s) for s, h in self._holdings.items()]


def _algorithm(main_module, *, mode="paper", locked=True, equity_bar=True, holdings=None, config=None, bars=None):
    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    algorithm.target_weights_config = config or TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=0.0, financing_enabled=False)
    algorithm.runtime_mode = mode
    algorithm.allow_live_orders = True
    algorithm._broker_config_present = True
    algorithm.is_warming_up = False
    algorithm.is_equity_session_bar = equity_bar
    algorithm.trade_lock_active = locked
    algorithm._order_permission = lambda: resolve_order_permission(mode, True, True, not locked)
    algorithm._target_weights = {}
    algorithm._target_pending = {}
    algorithm._target_symbol_by_ticker = {"A": "A", "B": "B"}
    algorithm._target_class_by_ticker = {"A": "equity", "B": "crypto"}
    algorithm._target_lot_by_ticker = {"A": 1.0, "B": 0.001}
    algorithm._target_financing_date = None
    algorithm._target_missing_bars = {}
    algorithm._target_exited_without_bars = set()
    algorithm._target_applied_through = None
    algorithm._equity_symbols = ["A"]
    algorithm._cash_sweep_symbol = None
    algorithm.Time = datetime.datetime(2024, 1, 2, 16)
    algorithm.Portfolio = _Portfolio({key: _Holding(value) for key, value in (holdings or {}).items()})
    algorithm._open_order_quantity = lambda symbol: 0.0
    algorithm._target_usd_per_unit = lambda symbol: 100.0
    algorithm._update_cash_sweep = lambda: None
    algorithm.orders, algorithm.liquidated = [], []
    algorithm.MarketOrder = lambda symbol, quantity, tag="": algorithm.orders.append((symbol, quantity, tag))
    algorithm.Liquidate = lambda symbol=None, tag="": algorithm.liquidated.append(symbol)
    algorithm.Debug = lambda message: None
    return algorithm, SimpleNamespace(Bars=bars if bars is not None else {}, QuoteBars={})


@pytest.mark.parametrize("mode", ["paper", "live", "backtest"])
def test_a_tripped_target_book_closes_in_every_mode_that_can_place_orders(main_module, mode):
    algorithm, slice_ = _algorithm(main_module, mode=mode, holdings={"A": 10.0})
    algorithm._target_weights_tick(slice_)
    assert algorithm.liquidated == ["A"]


def test_observation_mode_places_nothing_under_a_lock(main_module):
    algorithm, slice_ = _algorithm(main_module, mode="observation", holdings={"A": 10.0})
    algorithm._target_weights_tick(slice_)
    assert algorithm.liquidated == [] and algorithm.orders == []


# --- 3.5: no buy under a lock, and crypto exits on its own bar ------------------------------------------------------


def test_a_lock_drops_a_pending_crypto_buy(main_module):
    algorithm, slice_ = _algorithm(main_module, equity_bar=False, bars={"B": object()})
    algorithm._target_pending = {"B": 0.1}
    algorithm._target_weights_tick(slice_)
    assert algorithm.orders == [] and algorithm._target_pending == {}


def test_a_lock_sends_crypto_exits_on_its_next_bar_not_the_equity_tick(main_module):
    algorithm, slice_ = _algorithm(main_module, holdings={"A": 10.0, "B": 2.0}, bars={"A": object()})
    algorithm._target_weights_tick(slice_)
    assert algorithm.liquidated == ["A"] and algorithm.orders == [] and algorithm._target_pending == {"B": 0.0}

    algorithm.is_equity_session_bar = False
    algorithm._target_weights_tick(SimpleNamespace(Bars={"B": object()}, QuoteBars={}))
    assert algorithm.orders == [("B", -2.0, "target_weights")]


# --- 3.2: a growing file in paper and live -------------------------------------------------------------------------


def test_next_unapplied_row_takes_the_newest_row_not_yet_applied():
    weights = {"2024-01-02": {"A": 0.1}, "2024-01-03": {"A": 0.2}, "2024-01-05": {"A": 0.3}}
    assert next_unapplied_row(weights, "2024-01-04", None) == ("2024-01-03", {"A": 0.2})
    assert next_unapplied_row(weights, "2024-01-04", "2024-01-03") is None
    assert next_unapplied_row(weights, "2024-01-06", "2024-01-03") == ("2024-01-05", {"A": 0.3})


def test_a_flat_row_is_a_decision_with_no_positions():
    assert next_unapplied_row({"2024-01-02": {"__FLAT__": 0.0}}, "2024-01-02", None) == ("2024-01-02", {})


def test_a_live_file_must_match_its_sidecar(tmp_path):
    path = tmp_path / "weights.csv"
    write_weight_file({"2024-01-02": {"A": 0.1}}, path)
    write_weights_sidecar(path)
    assert load_live_weight_file(path)["2024-01-02"]["A"] == pytest.approx(0.1)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("2024-01-03,A,0.2\n")
    with pytest.raises(ValueError):
        load_live_weight_file(path)


def test_premarket_tick_applies_a_row_appended_mid_run(main_module, tmp_path):
    config = TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=0.0, financing_enabled=False, live_reload=True, weights_path="weights.csv")
    algorithm, _ = _algorithm(main_module, mode="live", locked=False, config=config)
    algorithm.root_path = tmp_path
    path = tmp_path / "weights.csv"
    write_weight_file({"2024-01-01": {"A": 0.5}}, path)
    write_weights_sidecar(path)
    algorithm.Time = datetime.datetime(2024, 1, 2, 9, 25)

    algorithm._target_premarket_tick()
    assert algorithm.orders == [("A", 500.0, "target_weights")]

    algorithm._target_premarket_tick()
    assert len(algorithm.orders) == 1, "a row applies once"


def test_premarket_tick_holds_on_a_bad_file(main_module, tmp_path):
    config = TargetWeightsConfig(enabled=True, live_reload=True, weights_path="weights.csv")
    algorithm, _ = _algorithm(main_module, mode="live", locked=False, config=config)
    algorithm.root_path = tmp_path
    algorithm._target_premarket_tick()
    assert algorithm.orders == []


def test_premarket_tick_sends_nothing_under_a_lock(main_module, tmp_path):
    config = TargetWeightsConfig(enabled=True, live_reload=True, weights_path="weights.csv")
    algorithm, _ = _algorithm(main_module, mode="live", locked=True, config=config)
    algorithm.root_path = tmp_path
    algorithm._target_premarket_tick()
    assert algorithm.orders == []


def test_the_daily_tick_leaves_rows_to_premarket_on_a_live_reload_run(main_module):
    config = TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=0.0, financing_enabled=False, live_reload=True)
    algorithm, _ = _algorithm(main_module, mode="live", locked=False, config=config, bars={"A": SimpleNamespace(Time=datetime.datetime(2024, 1, 2))})
    algorithm._target_weights = {"2024-01-02": {"A": 0.5}}
    algorithm._target_weights_tick(SimpleNamespace(Bars={"A": SimpleNamespace(Time=datetime.datetime(2024, 1, 2))}, QuoteBars={}))
    assert algorithm.orders == []


# --- 3.3: a model's age says nothing about a rule's weights -------------------------------------------------------


def test_model_age_is_skipped_on_a_target_run_with_no_model(main_module):
    algorithm, _ = _algorithm(main_module, mode="live", locked=False)
    algorithm._rank_signal_policy = {"model_priority": ["sequence"]}
    algorithm.sequence_model_path = SimpleNamespace(exists=lambda: True, stat=lambda: SimpleNamespace(st_mtime=0.0))
    assert algorithm._model_age_days() is None

    algorithm.target_weights_config = TargetWeightsConfig(enabled=True, uses_model=True)
    assert algorithm._model_age_days() > 1000.0


# --- 2.2l in main.py ------------------------------------------------------------------------------------------------


def test_main_closes_a_name_whose_bars_stopped_and_charges_the_haircut(main_module):
    config = TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=0.0, financing_enabled=False, no_bar_exit=True, no_bar_exit_after=2,
                                 no_bar_haircut_by_class={"equity": 0.10})
    algorithm, _ = _algorithm(main_module, locked=False, mode="backtest", holdings={"A": 10.0}, config=config)
    no_bars = SimpleNamespace(Bars={}, QuoteBars={})

    algorithm._exit_target_names_without_bars(no_bars)
    assert algorithm.liquidated == [] and algorithm._target_missing_bars == {"A": 1}

    algorithm._exit_target_names_without_bars(no_bars)
    assert algorithm.liquidated == ["A"]
    assert algorithm.Portfolio.charges == [pytest.approx(-100.0)]


def test_main_does_not_count_an_equity_on_a_crypto_only_tick(main_module):
    config = TargetWeightsConfig(enabled=True, no_bar_exit=True, no_bar_exit_after=1)
    algorithm, _ = _algorithm(main_module, locked=False, mode="backtest", equity_bar=False, holdings={"A": 10.0}, config=config)
    algorithm._exit_target_names_without_bars(SimpleNamespace(Bars={}, QuoteBars={}))
    assert algorithm.liquidated == []


# --- 3.4: a non-sticky lock can clear ------------------------------------------------------------------------------


def test_risk_value_reads_the_real_book_while_locked_on_the_target_path(main_module):
    """`_refresh_risk_state` up to its first use of the value: a lock must not switch it to the simulated book, stuck at the start."""
    algorithm, _ = _algorithm(main_module, mode="paper", locked=True)
    algorithm.Portfolio.TotalPortfolioValue = 92_000.0
    algorithm._simulated_portfolio = SimpleNamespace(snapshot=lambda consume_realized_pnl=False: {"total_value": 100_000.0})
    algorithm._cash_sweep_symbol = "BIL"
    algorithm.cash_sweep_config = {"exclude_from_risk_controls": True}
    algorithm._cash_sweep_holding_profit = lambda: (0.0,)
    algorithm._risk_value_state = None
    seen = []

    class Stop(Exception):
        pass

    def capture(state, value, profit):
        seen.append(value)
        raise Stop

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(main_module, "advance_strategy_value", capture)
        with pytest.raises(Stop):
            algorithm._refresh_risk_state()
    assert seen == [92_000.0]


# --- 3.6 and 3.7: the daily route --------------------------------------------------------------------------------


def _daily_module():
    sys.path.insert(0, str(ROOT / "scripts"))
    import daily_target_weights

    return daily_target_weights


def test_append_row_writes_the_sidecar(tmp_path):
    module = _daily_module()
    path = tmp_path / "w.csv"
    assert module.append_row(path, "2024-01-02", {"A": 0.5}) is True
    assert load_live_weight_file(path)["2024-01-02"]["A"] == pytest.approx(0.5)


def _context(known_dates, closes):
    return SimpleNamespace(
        panel=SimpleNamespace(known=pd.DataFrame(index=known_dates)),
        market=SimpleNamespace(
            closes=np.array(closes, dtype=float), dates=known_dates, tickers=["A", "B"], asset_class={"A": "equity", "B": "crypto"},
        ),
    )


def test_a_missing_date_is_a_problem_not_a_quiet_no_op():
    module = _daily_module()
    context = _context(["2024-01-02"], [[1.0, 1.0]])
    assert "not a session" in module.data_problems(context, "2024-01-03")[0]


def test_stale_crypto_is_a_problem_fresh_data_is_not():
    module = _daily_module()
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    context = _context(dates, [[1.0, 1.0], [1.0, np.nan], [1.0, np.nan], [1.0, np.nan]])
    problems = module.data_problems(context, "2024-01-05")
    assert len(problems) == 1 and problems[0].startswith("crypto data is 3 days old")
    assert module.data_problems(_context(dates, [[1.0, 1.0]] * 4), "2024-01-05") == []


def test_extended_rows_never_rewrite_a_frozen_row():
    sys.path.insert(0, str(ROOT / "scripts"))
    from extend_frozen_weights import extended_rows

    frozen = {"2024-01-02": {"A": 0.5}, "2024-01-09": {"A": 0.6}}
    new = {"2024-01-02": {"A": 9.9}, "2024-01-09": {"A": 9.9}, "2024-01-16": {"A": 0.7}}
    out = extended_rows(frozen, new, "2024-01-09")
    assert out == {"2024-01-02": {"A": 0.5}, "2024-01-09": {"A": 0.6}, "2024-01-16": {"A": 0.7}}


# --- 2.2j and 2.2k: default-off training keys --------------------------------------------------------------------


def test_calendar_purge_catches_a_crypto_row_the_row_count_keeps():
    from train import purge_label_overlap, purge_label_overlap_calendar

    dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2021-12-01", periods=40)]
    splits = ["train"] * 31 + ["validation"] * 9  # validation begins 2022-01-01, every day a bar
    by_rows = purge_label_overlap(splits, 20)
    by_days = purge_label_overlap_calendar(splits, dates, 31)
    assert by_rows[10] == "train"
    assert by_days[10] == "purged" and by_days[0] == "purged"
    assert purge_label_overlap_calendar(splits, dates, 0) == splits


@pytest.mark.parametrize("target, ok", [
    ({"enabled": False}, True), ({"enabled": True}, False), ({"enabled": True, "velocity_decision": "off, by R-VEL1"}, True), ({}, True),
])
def test_paper_readiness_needs_a_velocity_decision_on_the_target_path(target, ok):
    from execution.paper_readiness import evaluate_velocity_decision

    assert evaluate_velocity_decision({"phase_v2": {"target_weights": target}})[0] is ok


def test_alpha_proof_report_names_its_data_root_in_its_signature():
    import inspect

    assert inspect.signature(alpha_proof_report).parameters["data_dir"].default == "data"
