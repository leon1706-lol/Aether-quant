"""V6.3.0 round: the kill switch's release band (`risk.kill_switch.release_rolling_sharpe`, rule R-KILL) carries its state
through the offline simulator the way main.py carries `_kill_switch_rolling_sharpe_tripped`, and is a strict no-op when
unset - so the as-live scores of R-KILL measure the code Lean runs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.rank_book_simulator import simulate_rank_book
from risk.kill_switch import evaluate_kill_switch


def _frame(seed=5, signal_strength=-0.004) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [str(d.date()) for d in pd.bdate_range("2021-01-01", periods=140)]
    rows = []
    for date in dates:
        for ticker_index in range(30):
            score = float(rng.normal())
            rows.append({"date": date, "ticker": f"T{ticker_index:02d}", "pred": score,
                         "target_return_1d": score * signal_strength + float(rng.normal(0, 0.006))})
    return pd.DataFrame(rows)


def _run(frame, **kill_switch):
    config = {"enabled": True, "evaluation_bars": 20, "min_rolling_sharpe": -1.0, "min_return_std_for_sharpe": 0.0, **kill_switch}
    return simulate_rank_book(
        frame, prediction_column="pred", top_n=5, bottom_n=5, rebalance_every_bars=5, cost_bps_per_side=0.0,
        commission_bps=0.0, gross_exposure=1.0, dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.12,
        min_universe_size=20, entry_lag_bars=1, kill_switch_config=config,
    )


def test_an_unset_release_level_is_byte_identical():
    frame = _frame()
    baseline = _run(frame)
    explicit = _run(frame, release_rolling_sharpe=None)
    assert baseline.per_date_net_return == explicit.per_date_net_return
    assert baseline.kill_switch_locked_date_list == explicit.kill_switch_locked_date_list
    assert baseline.num_kill_switch_locked_dates > 0  # the fixture does reach the floor


def test_a_release_level_at_the_floor_changes_nothing_and_above_it_holds_longer():
    frame = _frame()
    baseline = _run(frame)
    at_floor = _run(frame, release_rolling_sharpe=-1.0)
    banded = _run(frame, release_rolling_sharpe=0.5)
    assert at_floor.kill_switch_locked_date_list == baseline.kill_switch_locked_date_list
    # the lock changes the book and so the later returns: the paths differ, the banded switch holds longer overall
    assert banded.num_kill_switch_locked_dates > baseline.num_kill_switch_locked_dates


def test_the_simulator_threads_the_band_like_a_bar_by_bar_replay():
    """Feeding evaluate_kill_switch its own previous verdict bar by bar (main.py's loop) reproduces the band's latch."""
    returns = [0.01, -0.012] * 15 + [-0.02] * 5 + [0.004, -0.004] * 10
    config = {"enabled": True, "evaluation_bars": 10, "min_rolling_sharpe": -1.0, "min_return_std_for_sharpe": 0.0,
              "release_rolling_sharpe": 0.0}
    tripped_last, latched = False, []
    for end in range(10, len(returns) + 1):
        decision = evaluate_kill_switch({"recent_bar_returns": returns[:end], "rolling_sharpe_tripped_last_bar": tripped_last}, config)
        tripped_last = decision.rolling_sharpe_tripped
        latched.append(decision.tripped)
    plain = [evaluate_kill_switch({"recent_bar_returns": returns[:end]}, dict(config, release_rolling_sharpe=None)).tripped
             for end in range(10, len(returns) + 1)]
    assert sum(latched) >= sum(plain)
    assert all(a or not b for a, b in zip(latched, plain))  # every plain trip is also a banded one
