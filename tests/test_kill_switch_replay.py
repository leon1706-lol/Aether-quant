"""Tests for evaluation/kill_switch_replay.py - V5.2.8 (development/Problems.md #94)."""

from evaluation.kill_switch_replay import (
    _is_sticky_reason,
    replay_kill_switch_over_dataset,
    summarize_kill_switch_replay,
)


def _kill_switch_config(**overrides):
    config = {
        "enabled": True,
        "evaluation_bars": 3,
        "min_bars_for_sharpe": 3,
        "min_return_std_for_sharpe": 0.0,
        "min_rolling_sharpe": -1.0,
        "action": "trade_lock",
    }
    config.update(overrides)
    return config


_DATES = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"]


# ---------------------------------------------------------------------------
# _is_sticky_reason - byte-identical predicate to main.py:6178-6180
# ---------------------------------------------------------------------------


def test_is_sticky_reason_total_drawdown():
    assert _is_sticky_reason("total_drawdown_limit_breached") is True


def test_is_sticky_reason_kill_switch_prefix():
    assert _is_sticky_reason("kill_switch_rolling_sharpe_below_floor") is True
    assert _is_sticky_reason("kill_switch_drawdown_velocity_above_cap") is True


def test_is_sticky_reason_daily_drawdown_not_sticky():
    assert _is_sticky_reason("daily_drawdown_limit_breached") is False


def test_is_sticky_reason_none_not_sticky():
    assert _is_sticky_reason(None) is False


# ---------------------------------------------------------------------------
# replay_kill_switch_over_dataset - sticky-lock state machine
# ---------------------------------------------------------------------------


def test_replay_no_trips_on_flat_positive_returns():
    returns = {date: 0.001 for date in _DATES}
    records = replay_kill_switch_over_dataset(
        _DATES, returns, _kill_switch_config(), max_daily_drawdown_pct=0.03, max_total_drawdown_pct=0.12
    )
    assert len(records) == len(_DATES)
    assert all(not record["tripped"] for record in records)
    assert all(not record["would_be_locked"] for record in records)


def test_replay_total_drawdown_breach_is_sticky_and_stays_locked():
    """A single catastrophic-return date breaches total_drawdown_limit -
    a sticky reason - and must stay locked on every subsequent date
    (byte-identical to main.py:6178-6185's clearing condition), even
    though later returns are flat/positive."""
    returns = {
        "2020-01-01": 0.0,
        "2020-01-02": -0.5,
        "2020-01-03": 0.01,
        "2020-01-04": 0.01,
        "2020-01-05": 0.01,
    }
    records = replay_kill_switch_over_dataset(
        _DATES, returns, _kill_switch_config(enabled=False), max_daily_drawdown_pct=0.03, max_total_drawdown_pct=0.12
    )
    assert records[1]["would_be_locked"] is True
    assert records[1]["trade_lock_reason"] == "total_drawdown_limit_breached"
    # Stays locked every date after, despite positive returns.
    assert records[2]["would_be_locked"] is True
    assert records[3]["would_be_locked"] is True
    assert records[4]["would_be_locked"] is True
    assert records[4]["sticky_reason_active"] is True


def test_replay_daily_drawdown_breach_clears_next_session():
    """daily_drawdown_limit_breached is NOT sticky - must clear on the
    very next date even with no recovery in the return itself."""
    returns = {
        "2020-01-01": 0.0,
        "2020-01-02": -0.04,
        "2020-01-03": 0.0,
        "2020-01-04": 0.0,
        "2020-01-05": 0.0,
    }
    records = replay_kill_switch_over_dataset(
        _DATES, returns, _kill_switch_config(enabled=False), max_daily_drawdown_pct=0.03, max_total_drawdown_pct=0.5
    )
    assert records[1]["trade_lock_reason"] == "daily_drawdown_limit_breached"
    assert records[1]["would_be_locked"] is True
    # Not sticky - clears on the next date.
    assert records[2]["would_be_locked"] is False
    assert records[2]["trade_lock_reason"] is None


def test_replay_kill_switch_trip_is_sticky():
    """A kill_switch_* trip is sticky by the same rule as
    total_drawdown_limit_breached - must stay locked across subsequent
    flat/positive-return dates."""
    dates = [f"2020-01-{day:02d}" for day in range(1, 8)]
    returns = {date: -0.3 for date in dates[:3]}
    for date in dates[3:]:
        returns[date] = 0.02
    records = replay_kill_switch_over_dataset(
        dates,
        returns,
        _kill_switch_config(evaluation_bars=3, min_bars_for_sharpe=3, min_rolling_sharpe=-1.0),
        max_daily_drawdown_pct=1.0,
        max_total_drawdown_pct=1.0,
    )
    trip_index = next(i for i, record in enumerate(records) if record["tripped"])
    assert records[trip_index]["trade_lock_reason"].startswith("kill_switch_")
    # Every date after the trip stays locked, even with recovering returns.
    for record in records[trip_index + 1 :]:
        assert record["would_be_locked"] is True


def test_replay_missing_date_in_returns_defaults_to_zero_not_keyerror():
    records = replay_kill_switch_over_dataset(
        ["2020-01-01", "2020-01-02"],
        {"2020-01-01": 0.01},
        _kill_switch_config(),
        max_daily_drawdown_pct=0.03,
        max_total_drawdown_pct=0.12,
    )
    assert len(records) == 2
    assert records[1]["tripped"] is False


def test_replay_first_date_has_no_prior_state_and_does_not_raise():
    records = replay_kill_switch_over_dataset(
        ["2020-01-01"],
        {"2020-01-01": -0.02},
        _kill_switch_config(),
        max_daily_drawdown_pct=0.03,
        max_total_drawdown_pct=0.12,
    )
    assert len(records) == 1
    assert records[0]["would_be_locked"] is False


def test_replay_return_history_deque_respects_evaluation_bars_window():
    """Only the trailing evaluation_bars returns should ever feed the
    rolling-Sharpe calculation - a large negative return old enough to
    fall out of the window must stop influencing later trip decisions."""
    dates = [f"2020-01-{day:02d}" for day in range(1, 11)]
    returns = {date: 0.001 for date in dates}
    returns[dates[0]] = -0.9
    records = replay_kill_switch_over_dataset(
        dates,
        returns,
        _kill_switch_config(evaluation_bars=2, min_bars_for_sharpe=2, min_rolling_sharpe=-50.0),
        max_daily_drawdown_pct=1.0,
        max_total_drawdown_pct=1.0,
    )
    # By the last date, the catastrophic first-date return has long since
    # fallen out of a 2-bar window - no trip should still be attributable
    # to it this late.
    assert records[-1]["tripped"] is False


def test_replay_disabled_kill_switch_config_never_trips_but_drawdown_lock_still_applies():
    returns = {
        "2020-01-01": 0.0,
        "2020-01-02": -0.5,
        "2020-01-03": 0.01,
        "2020-01-04": 0.01,
        "2020-01-05": 0.01,
    }
    records = replay_kill_switch_over_dataset(
        _DATES, returns, _kill_switch_config(enabled=False), max_daily_drawdown_pct=0.03, max_total_drawdown_pct=0.12
    )
    assert all(not record["tripped"] for record in records)
    # The drawdown lock is a separate mechanism (risk_controls.py::
    # assess_drawdown_lock()) and stays active regardless of the kill
    # switch's own enabled flag.
    assert records[1]["would_be_locked"] is True


# ---------------------------------------------------------------------------
# summarize_kill_switch_replay
# ---------------------------------------------------------------------------


def test_summarize_kill_switch_replay_empty_input():
    summary = summarize_kill_switch_replay([])
    assert summary == {"total_dates": 0, "trip_count": 0, "locked_days": 0, "locked_day_fraction": 0.0}


def test_summarize_kill_switch_replay_counts_match_records():
    returns = {
        "2020-01-01": 0.0,
        "2020-01-02": -0.5,
        "2020-01-03": 0.01,
        "2020-01-04": 0.01,
        "2020-01-05": 0.01,
    }
    records = replay_kill_switch_over_dataset(
        _DATES, returns, _kill_switch_config(enabled=False), max_daily_drawdown_pct=0.03, max_total_drawdown_pct=0.12
    )
    summary = summarize_kill_switch_replay(records)
    assert summary["total_dates"] == 5
    assert summary["locked_days"] == sum(1 for record in records if record["would_be_locked"])
    assert summary["locked_day_fraction"] == summary["locked_days"] / summary["total_dates"]
