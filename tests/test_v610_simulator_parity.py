"""V6.1.0 round file (rule R-CAL2, Problems.md #190): the simulator replicates the live mechanisms the V6 Lean runs
showed it missing - the daily member pass between rebalances, the whole-portfolio kill switch, weekend accrual, the
legacy probability signal, the position cap - and counts exit costs on a rebalance date."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.rank_book_simulator import _cap_new_entries, simulate_rank_book
from portfolio.legacy_sleeve import resolve_legacy_sleeve_config


def _frame(num_tickers: int = 12, num_days: int = 30, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=num_days)]
    rows = []
    for day_index, date in enumerate(dates):
        for index in range(num_tickers):
            skill = (index - num_tickers / 2) / num_tickers
            close = 100.0 * (1 + 0.01 * day_index * skill)
            rows.append({
                "date": date, "ticker": f"T{index}", "pred": skill + rng.normal(0, 0.05),
                "target_return_1d": skill * 0.002 + rng.normal(0, 0.002), "close": close,
            })
    return pd.DataFrame(rows)


def _kwargs(**overrides):
    kwargs = dict(
        prediction_column="pred", forward_return_column="target_return_1d", ticker_column="ticker", date_column="date",
        top_n=3, bottom_n=3, rebalance_every_bars=5, cost_bps_per_side=5.0, commission_bps=1.0, gross_exposure=1.0,
        dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.5, min_universe_size=5,
    )
    kwargs.update(overrides)
    return kwargs


def test_the_new_options_default_to_the_v6_result():
    frame = _frame()
    old = simulate_rank_book(frame, **_kwargs())
    new = simulate_rank_book(frame, **_kwargs(mid_cycle_member_updates=False, accrue_skipped_dates=False,
                                              kill_switch_extra_returns=None, legacy_component=None, max_active_positions=None))
    assert old.per_date_net_return == new.per_date_net_return
    assert new.per_date_component_returns == {}


def test_exit_costs_on_a_rebalance_date_are_charged():
    # max hold 5 = the cadence: every member's age exit lands on a rebalance date
    result = simulate_rank_book(_frame(), **_kwargs(max_holding_dates=5, hold_positions_on_veto=True))
    years = result.num_dates_used / 252
    rate_bps = 5.0 + 1.0
    assert result.cost_drag_annual_bps * years == pytest.approx(result.annualized_turnover * years * rate_bps, rel=1e-9)


def test_a_member_blocked_on_the_rebalance_day_enters_on_the_next_session_with_mid_cycle_updates():
    frame = _frame()
    first_date = sorted(frame["date"].unique())[0]

    def weight_fn(*, symbol, date, base_weight, held_weight, **_):
        return held_weight if date == first_date else base_weight  # e.g. the net-edge gate fails on day one only

    common = _kwargs(member_weight_fn=weight_fn, hold_positions_on_veto=True)
    off = simulate_rank_book(frame, **common)
    on = simulate_rank_book(frame, **common, mid_cycle_member_updates=True)
    assert off.mean_names_long < on.mean_names_long
    assert on.num_rebalances == off.num_rebalances  # mid-cycle dates are not rebalances
    assert on.per_date_net_return[0] == off.per_date_net_return[0]


def test_after_a_veto_there_is_no_book_between_rebalances():
    frame = _frame()

    def veto_all(date):
        return {"engaged": False, "reason": "rolling_ic_below_floor"}

    result = simulate_rank_book(frame, **_kwargs(rolling_ic_gate_fn=veto_all, hold_positions_on_veto=True,
                                                 mid_cycle_member_updates=True))
    assert result.mean_names_long == 0.0 and result.mean_names_short == 0.0


def test_skipped_weekend_dates_accrue_into_the_previous_return():
    frame = _frame(num_days=10)
    weekend = pd.DataFrame([{"date": "2024-01-06", "ticker": "T11", "pred": 1.0, "target_return_1d": 0.05, "close": 1.0}])
    with_weekend = pd.concat([frame, weekend], ignore_index=True)
    base = simulate_rank_book(frame, **_kwargs())
    accrued = simulate_rank_book(with_weekend, **_kwargs(accrue_skipped_dates=True))
    friday = base.per_date.index("2024-01-05")
    held_t11 = 0.5 / 3  # T11 is a long member of the equal-weight book (gross 1.0, 3 per side)
    assert accrued.per_date == base.per_date
    assert accrued.per_date_net_return[friday] - base.per_date_net_return[friday] == pytest.approx(held_t11 * 0.05, rel=0.25)


def test_the_kill_switch_reads_returns_from_outside_the_book():
    frame = _frame(num_days=40)
    dates = sorted(frame["date"].unique())
    config = {"enabled": True, "evaluation_bars": 5, "min_bars_for_sharpe": 5, "min_rolling_sharpe": -1.0,
              "min_return_std_for_sharpe": 0.0}
    calm = simulate_rank_book(frame, **_kwargs(kill_switch_config=config))
    stressed = simulate_rank_book(frame, **_kwargs(
        kill_switch_config=config, kill_switch_extra_returns={date: -0.01 + 0.001 * (i % 3) for i, date in enumerate(dates)}
    ))
    assert stressed.num_kill_switch_locked_dates > calm.num_kill_switch_locked_dates
    # the extra P&L is read by the kill switch only, never booked as this simulation's return
    assert len(stressed.per_date_net_return) == len(calm.per_date_net_return)


def _legacy(probability_column="prob", **overrides):
    component = {
        "probability_column": probability_column,
        "sleeve_config": resolve_legacy_sleeve_config({"enabled": True, "max_gross_exposure": 0.05, "max_weight_per_name": 0.02}),
        "signal": {"decision_threshold": 0.51, "buy_threshold": 0.52, "sell_threshold": 0.50, "band_enabled": False,
                   "band_window": 60, "band_min_observations": 20, "band_percentile": 0.25, "max_position_weight": 0.12},
        "asset_classes": ("equity",), "weight_fn": None, "max_holding_dates": None, "trailing_stop_pct": None,
    }
    component.update(overrides)
    return component


def test_the_legacy_signal_buys_non_members_within_the_sleeve_budget():
    frame = _frame()
    # T5 / T6 sit in the middle of the ranking (never members); the legacy model likes them
    frame["prob"] = np.where(frame["ticker"].isin(["T5", "T6"]), 0.60, 0.505)
    metadata = {f"T{i}": {"asset_class": "equity", "trading_eligible": True} for i in range(12)}
    result = simulate_rank_book(frame, **_kwargs(candidate_metadata_by_ticker=metadata, hold_positions_on_veto=True,
                                                 legacy_component=_legacy()))
    legacy = result.per_date_component_returns["legacy"]
    assert set(legacy) == set(result.per_date)
    book = result.per_date_component_returns["main_book"]
    total = [book[date] + legacy[date] for date in result.per_date]
    assert total == pytest.approx(result.per_date_net_return)
    assert any(value != 0.0 for value in legacy.values())


def test_no_legacy_entry_while_the_book_is_vetoed_and_a_sell_closes_the_position():
    frame = _frame()
    frame["prob"] = np.where(frame["ticker"] == "T5", 0.60, 0.505)
    metadata = {f"T{i}": {"asset_class": "equity", "trading_eligible": True} for i in range(12)}
    vetoed = simulate_rank_book(frame, **_kwargs(
        candidate_metadata_by_ticker=metadata, hold_positions_on_veto=True, legacy_component=_legacy(),
        rolling_ic_gate_fn=lambda date: {"engaged": False, "reason": "rolling_ic_below_floor"},
    ))
    assert all(value == 0.0 for value in vetoed.per_date_component_returns["legacy"].values())


def test_new_entries_respect_the_position_cap_in_conviction_order():
    new = {"A": 0.1, "B": -0.1, "C": 0.1, "H": 0.1}
    held = {"H": 0.1}
    ranks = {"A": 0.9, "B": 0.05, "C": 0.6, "H": 0.7}
    assert _cap_new_entries(new, held, ranks, 3) == {"H": 0.1, "B": -0.1, "A": 0.1}
    assert _cap_new_entries(new, held, ranks, 0) == {"H": 0.1}


def _member_fn(use_live_analyzer):
    import json
    from pathlib import Path

    from evaluation.live_parity import build_live_member_weight_fn

    config = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
    return build_live_member_weight_fn(config, security_type_by_ticker={"AAA": "equity"}, nav=100_000.0,
                                       use_live_analyzer=use_live_analyzer), config


def _row(**overrides):
    row = {"close": 100.0, "volume": 5_000_000.0, "rolling_volatility_20d": 0.015, "liquidity_spread_proxy": 0.0005,
           "regime_risk_off": 0.0, "regime_risk_on": 1.0, "regime_signal_risk_score": 0.3, "regime_signal_confidence": 0.8,
           "topology_risk_normal": 1.0, "topology_risk_isolated": 0.0, "topology_risk_elevated": 0.0,
           "topology_correlation_strength": 0.7}
    row.update(overrides)
    return row


@pytest.mark.parametrize("use_live_analyzer", [False, True])
def test_risk_off_blocks_a_member_only_at_the_configured_severity(use_live_analyzer):
    fn, config = _member_fn(use_live_analyzer)
    assert config["phase_v2"]["regime_detection"]["risk_off_override_min_severity"] == 0.55
    common = dict(symbol="AAA", date="2024-01-02", base_weight=0.08, held_weight=0.0, predicted_rank=0.95)
    mild = fn(**common, row=_row(regime_risk_off=1.0, regime_risk_on=0.0, regime_signal_risk_score=-0.2))
    severe = fn(**common, row=_row(regime_risk_off=1.0, regime_risk_on=0.0, regime_signal_risk_score=-0.7))
    assert severe == 0.0
    assert mild == fn(**common, row=_row())


def test_the_live_analyzer_holds_an_isolated_member_and_sizes_a_legacy_entry():
    fn, _config = _member_fn(True)
    common = dict(symbol="AAA", date="2024-01-02", base_weight=0.08, held_weight=0.0, predicted_rank=0.95)
    assert fn(**common, row=_row()) > 0.0
    assert fn(**common, row=_row(topology_risk_normal=0.0, topology_risk_isolated=1.0, topology_correlation_strength=0.1)) == 0.0
    legacy = fn(symbol="AAA", date="2024-01-02", base_weight=0.11, held_weight=0.0, predicted_rank=None, confidence=0.3,
                is_book_selected=False, row=_row())
    assert legacy > 0.0


def test_late_bar_symbols_enter_the_rolling_ic_event_buffer_twice_per_date_as_live_records_them():
    from evaluation.live_parity import with_live_event_duplicates
    from evaluation.rolling_ic_gate_calibration import build_event_buffer

    frame = pd.DataFrame({
        "date": ["2024-01-02"] * 3, "ticker": ["AAA", "BTCUSD", "ETHUSD"], "score": [0.1, 0.2, 0.3], "close": [10.0, 20.0, 30.0],
    })
    doubled = with_live_event_duplicates(frame, {"BTCUSD", "ETHUSD"})
    assert sorted(doubled["ticker"]) == ["AAA", "BTCUSD", "BTCUSD", "ETHUSD", "ETHUSD"]
    assert len(build_event_buffer(doubled, raw_score_column="score")) == 5
    assert with_live_event_duplicates(frame, None) is frame and with_live_event_duplicates(frame, set()) is frame
    assert with_live_event_duplicates(frame, {"ZZZ"}) is frame  # nothing to duplicate
