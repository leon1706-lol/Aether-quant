"""V6.2.0 round file (todo lead 3, rule R-STAGGER): the staggered tranche book - shared phase / size helpers and the offline
sum of phase-shifted sub-books with a whole-portfolio kill switch."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.rank_book_simulator import RankBookSimulationResult, simulate_rank_book
from evaluation.tranche_book import combine_tranche_results, simulate_tranche_book, tranche_kwargs
from portfolio.book_construction import (
    combine_tranche_weights,
    should_rebalance_this_bar,
    tranche_book_params,
    tranche_offsets,
)


def test_a_zero_offset_is_the_old_cadence_and_offsets_shift_it():
    for bar in range(1, 60):
        assert should_rebalance_this_bar(bar, 20, True, phase_offset=0) == should_rebalance_this_bar(bar, 20, True)
    assert [bar for bar in range(1, 45) if should_rebalance_this_bar(bar, 20, True, phase_offset=10)] == [11, 31]
    assert should_rebalance_this_bar(5, 20, False, phase_offset=10)  # no book yet: always
    assert tranche_offsets(20, 1) == [0] and tranche_offsets(20, 2) == [0, 10] and tranche_offsets(20, 4) == [0, 5, 10, 15]


def test_each_tranche_holds_its_share_and_the_book_is_their_sum():
    assert tranche_book_params(6, 6, 1.0, 2, 12) == {"top_n": 3, "bottom_n": 3, "gross_exposure_cap": 0.5,
                                                    "max_active_positions": 6}
    assert tranche_book_params(6, 0, 1.0, 4)["bottom_n"] == 0
    assert tranche_book_params(6, 6, 1.0, 1, 12) == {"top_n": 6, "bottom_n": 6, "gross_exposure_cap": 1.0,
                                                    "max_active_positions": 12}
    assert combine_tranche_weights([{"A": 0.1, "B": -0.1}, {"A": -0.1, "C": 0.2}]) == {"B": -0.1, "C": 0.2}


def _frame(num_tickers: int = 14, num_days: int = 60, seed: int = 9) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for day in pd.bdate_range("2024-01-02", periods=num_days):
        for index in range(num_tickers):
            skill = (index - num_tickers / 2) / num_tickers
            rows.append({"date": day.strftime("%Y-%m-%d"), "ticker": f"T{index}", "pred": skill + rng.normal(0, 0.3),
                         "target_return_1d": skill * 0.002 + rng.normal(0, 0.004), "close": 100.0})
    return pd.DataFrame(rows)


def _kwargs(**overrides):
    kwargs = dict(
        prediction_column="pred", forward_return_column="target_return_1d", ticker_column="ticker", date_column="date",
        top_n=4, bottom_n=4, rebalance_every_bars=10, cost_bps_per_side=5.0, commission_bps=1.0, gross_exposure=1.0,
        dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.5, min_universe_size=5, rebalance_counter_start=3,
    )
    kwargs.update(overrides)
    return kwargs


def test_one_tranche_is_the_plain_simulator():
    frame = _frame()
    assert simulate_tranche_book(frame, tranches=1, **_kwargs()) == simulate_rank_book(frame, **_kwargs())


def test_sub_books_get_their_phase_size_and_the_legacy_signal_only_once():
    subs = tranche_kwargs(_kwargs(max_active_positions=12, legacy_component={"x": 1}), 2)
    assert [sub["rebalance_counter_start"] for sub in subs] == [3, (3 - 5) % 10]
    assert all(sub["top_n"] == 2 and sub["bottom_n"] == 2 and sub["gross_exposure"] == 0.5 for sub in subs)
    assert [sub["max_active_positions"] for sub in subs] == [6, 6]
    assert subs[0]["legacy_component"] == {"x": 1} and subs[1]["legacy_component"] is None


def test_each_tranches_kill_switch_sees_the_other_tranches():
    calls = []

    def fake(frame, **kwargs):
        calls.append(kwargs)
        value = 0.01 if kwargs["rebalance_counter_start"] == 3 else -0.02
        return RankBookSimulationResult(0, 0, 0, 0, 0, 0, 0, 1, 2, 1, 1, per_date_net_return=[value, value],
                                        per_date=["2024-01-02", "2024-01-03"])

    result = simulate_tranche_book(None, tranches=2, simulate=fake,
                                   **_kwargs(kill_switch_config={"enabled": True}, kill_switch_extra_returns={"2024-01-02": 0.5}))
    second_pass = calls[2:]
    assert second_pass[0]["kill_switch_extra_returns"] == {"2024-01-02": pytest.approx(0.48), "2024-01-03": pytest.approx(-0.02)}
    assert second_pass[1]["kill_switch_extra_returns"] == {"2024-01-02": pytest.approx(0.51), "2024-01-03": pytest.approx(0.01)}
    assert result.per_date_net_return == [pytest.approx(-0.01), pytest.approx(-0.01)]


def test_the_combined_result_is_the_sum_and_a_real_run_works():
    a = RankBookSimulationResult(0, 0, 0, 0, 0, 1.0, 10.0, 2, 2, 2, 2, per_date_net_return=[0.01, 0.02], per_date=["d1", "d2"],
                                 per_date_component_returns={"main_book": {"d1": 0.01}})
    b = RankBookSimulationResult(0, 0, 0, 0, 0, 2.0, 5.0, 1, 2, 1, 1, per_date_net_return=[0.0, -0.01], per_date=["d1", "d2"],
                                 per_date_component_returns={"main_book": {"d1": 0.02}})
    combined = combine_tranche_results([a, b])
    assert combined.per_date_net_return == [pytest.approx(0.01), pytest.approx(0.01)]
    assert combined.annualized_turnover == 3.0 and combined.cost_drag_annual_bps == 15.0 and combined.num_rebalances == 3
    assert combined.net_total_return == pytest.approx(1.01 * 1.01 - 1)
    assert combined.per_date_component_returns == {"main_book": {"d1": pytest.approx(0.03)}}
    frame = _frame()
    real = simulate_tranche_book(frame, tranches=2, **_kwargs())
    assert real.num_dates_used == simulate_rank_book(frame, **_kwargs()).num_dates_used
    with pytest.raises(ValueError):
        simulate_tranche_book(frame, tranches=2, **_kwargs(cash_sweep={"x": 1}))
