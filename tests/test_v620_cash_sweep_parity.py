"""V6.2.0 round file: the T-bill cash sweep in the offline simulator - off by default, carry as its own component, the
kill switch blind to it, and the same sizing rule main.py applies (portfolio/cash_sweep.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.rank_book_simulator import _cash_sweep_step, simulate_rank_book
from portfolio.cash_sweep import cash_sweep_target_weight, margin_fraction, resolve_cash_sweep_config, strategy_reserve


def _frame(num_tickers: int = 12, num_days: int = 40, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=num_days)]
    rows = []
    for date in dates:
        for index in range(num_tickers):
            skill = (index - num_tickers / 2) / num_tickers
            rows.append({"date": date, "ticker": f"T{index}", "pred": skill + rng.normal(0, 0.05),
                         "target_return_1d": skill * 0.002 + rng.normal(0, 0.004), "close": 100.0})
    return pd.DataFrame(rows)


def _kwargs(**overrides):
    kwargs = dict(
        prediction_column="pred", forward_return_column="target_return_1d", ticker_column="ticker", date_column="date",
        top_n=3, bottom_n=3, rebalance_every_bars=5, cost_bps_per_side=5.0, commission_bps=1.0, gross_exposure=1.0,
        dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.5, min_universe_size=5,
    )
    kwargs.update(overrides)
    return kwargs


def _sweep(frame, daily=0.00018):
    return {
        "returns_by_date": {date: daily for date in frame["date"].unique()},
        "config": resolve_cash_sweep_config({"enabled": True}),
        "book_gross_cap": 1.0, "max_short_exposure": 0.3, "other_budget": 0.05, "neutral_budget": 0.1, "min_commission_usd": 1.0,
    }


def test_without_a_sweep_the_simulator_is_unchanged():
    frame = _frame()
    assert simulate_rank_book(frame, **_kwargs()).per_date_net_return == \
        simulate_rank_book(frame, **_kwargs(cash_sweep=None)).per_date_net_return


def test_the_sweep_adds_its_carry_as_a_component_and_the_book_is_untouched():
    frame = _frame()
    base = simulate_rank_book(frame, **_kwargs())
    swept = simulate_rank_book(frame, **_kwargs(cash_sweep=_sweep(frame)))
    carry = swept.per_date_component_returns["cash_sweep"]
    assert sum(carry.values()) > 0.0
    for date, before, after in zip(base.per_date, base.per_date_net_return, swept.per_date_net_return):
        assert after == pytest.approx(before + carry[date], abs=1e-15)
    assert swept.net_total_return > base.net_total_return


def test_the_kill_switch_reads_the_strategy_without_the_carry():
    frame = _frame()
    kill_switch = {"enabled": True, "min_rolling_sharpe": 0.5, "evaluation_bars": 5, "max_consecutive_losses": 999,
                   "max_drawdown_velocity_pct_per_bar": 1.0}
    base = simulate_rank_book(frame, **_kwargs(kill_switch_config=kill_switch, hold_positions_on_veto=True))
    big_carry = simulate_rank_book(frame, **_kwargs(kill_switch_config=kill_switch, hold_positions_on_veto=True,
                                                    cash_sweep=_sweep(frame, daily=0.01)))
    assert big_carry.kill_switch_locked_date_list == base.kill_switch_locked_date_list
    leaky = _sweep(frame, daily=0.01)
    leaky["config"] = dict(leaky["config"], exclude_from_risk_controls=False)
    counted = simulate_rank_book(frame, **_kwargs(kill_switch_config=kill_switch, hold_positions_on_veto=True, cash_sweep=leaky))
    assert counted.num_kill_switch_locked_dates <= base.num_kill_switch_locked_dates


def test_one_step_sizes_the_sweep_exactly_as_the_live_rule():
    sweep = _sweep(pd.DataFrame({"date": ["2024-01-02"]}))
    sweep["security_type_by_ticker"] = {"BTCUSD": "crypto"}
    book = {"A": 0.25, "B": -0.2}
    legacy = {"BTCUSD": 0.03}
    earned, weight = _cash_sweep_step(sweep, 0.5, date="2024-01-02", is_session=True, book_weights=book, legacy_weights=legacy,
                                      rebalance_next=True, formed_weights=book, pv_for_costs=100_000.0)
    reserve = strategy_reserve(rebalance_next=True, book_gross_cap=1.0, max_short_exposure=0.3, formed_long=0.25,
                               formed_short=0.2, book_long=0.25, book_short=0.2, other_budget_remaining=0.05,
                               neutral_budget=0.1)
    live = cash_sweep_target_weight(long_weight=0.28, short_weight=0.2,
                                    margin_used=margin_fraction([("equity", 0.25), ("equity", -0.2), ("crypto", 0.03)]),
                                    reserve=reserve, config=sweep["config"])
    assert weight == pytest.approx(live)
    assert earned == pytest.approx(0.5 * 0.00018 - sweep["_last_cost"])
    held, unchanged = _cash_sweep_step(sweep, live, date="2024-01-03", is_session=False, book_weights=book,
                                       legacy_weights=legacy, rebalance_next=True, formed_weights=book, pv_for_costs=1e5)
    assert unchanged == live and sweep["_last_cost"] == 0.0


def test_the_kwarg_builder_reads_the_live_config_and_the_zip(tmp_path):
    import zipfile

    from evaluation.live_parity import build_cash_sweep_kwarg

    path = tmp_path / "bil.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bil.csv", "20240102 00:00,1000000,1,1,1000000,1\n20240103 00:00,1000000,1,1,1000100,1\n")
    config = {
        "phase1": {"universe": {"assets": [{"ticker": "BTCUSD", "security_type": "crypto"}]}},
        "phase9": {"portfolio": {"max_short_exposure": 0.25}},
        "phase_v2": {"cash_sweep": {"enabled": False, "data_path": "bil.zip"},
                     "legacy_sleeve": {"enabled": True, "max_gross_exposure": 0.05},
                     "bond_sleeve": {"enabled": False, "gross_budget": 0.1},
                     "portfolio_book": {"neutrality": {"gross_exposure_cap": 0.8}}},
    }
    assert build_cash_sweep_kwarg(config, tmp_path) is None  # off in the config
    built = build_cash_sweep_kwarg(config, tmp_path, force_enabled=True)
    assert built["returns_by_date"] == {"2024-01-02": pytest.approx(0.0001)}
    assert built["other_budget"] == pytest.approx(0.05) and built["neutral_budget"] == 0.0 and built["book_gross_cap"] == 0.8
    assert built["max_short_exposure"] == 0.25 and built["security_type_by_ticker"] == {"BTCUSD": "crypto"}
