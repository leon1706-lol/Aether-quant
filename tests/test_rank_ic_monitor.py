"""Tests for performance/rank_ic_monitor.py (Phase 6 of the 5/10 -> 9/10
roadmap). Conventions match performance/triggers.py's test coverage: no
test classes, module-level helpers, plain dicts.
"""

import pytest

from performance.rank_ic_monitor import (
    compute_production_rank_ic,
    compute_realized_rank_ic_observations,
)


def _event(ticker: str, date: str, rank: float | None, close: float | None, mode: str = "backtest") -> dict:
    return {
        "ticker": ticker,
        "created_at": f"{date}T00:00:00Z",
        "resolved_predicted_rank_20d": rank,
        "close_price": close,
        "mode": mode,
    }


def _daily_events(ticker: str, closes: list[float], ranks: list[float], start_day: int = 1) -> list[dict]:
    return [
        _event(ticker, f"2020-01-{start_day + index:02d}", ranks[index], closes[index])
        for index in range(len(closes))
    ]


# ---------------------------------------------------------------------------
# compute_realized_rank_ic_observations
# ---------------------------------------------------------------------------


def test_compute_realized_rank_ic_observations_resolves_after_horizon_elapses():
    # 25 daily events for one ticker - horizon_days=20 means only the
    # first 5 (positions 0-4) have a position+20 still within range.
    closes = [100.0 + index for index in range(25)]
    ranks = [0.5] * 25
    events = _daily_events("AAPL", closes, ranks)

    observations = compute_realized_rank_ic_observations(events, horizon_days=20)

    assert len(observations) == 5
    assert observations[0]["ticker"] == "AAPL"
    assert observations[0]["origin_date"] == "2020-01-01"


def test_compute_realized_rank_ic_observations_computes_correct_realized_return():
    closes = [100.0] * 21  # position 0's close=100, position 20's close=100
    closes[20] = 110.0  # 20 trading days later, price rose 10%
    ranks = [0.5] * 21
    events = _daily_events("AAPL", closes, ranks)

    observations = compute_realized_rank_ic_observations(events, horizon_days=20)

    assert len(observations) == 1
    assert observations[0]["realized_return_20d"] == pytest.approx(0.10)


def test_compute_realized_rank_ic_observations_skips_events_missing_rank_or_close():
    events = [
        _event("AAPL", "2020-01-01", None, 100.0),  # missing rank
        _event("AAPL", "2020-01-02", 0.5, None),  # missing close
    ] + _daily_events("AAPL", [100.0] * 21, [0.5] * 21, start_day=3)

    observations = compute_realized_rank_ic_observations(events, horizon_days=20)

    # The two malformed events must never appear as an origin date.
    assert all(obs["origin_date"] not in {"2020-01-01", "2020-01-02"} for obs in observations)


def test_compute_realized_rank_ic_observations_cross_sectional_rank_per_origin_date():
    # Two tickers, same origin date, different realized returns.
    winner_closes = [100.0] * 21
    winner_closes[20] = 120.0  # +20%
    loser_closes = [100.0] * 21
    loser_closes[20] = 90.0  # -10%

    events = _daily_events("WINNER", winner_closes, [0.9] * 21) + _daily_events("LOSER", loser_closes, [0.1] * 21)

    observations = compute_realized_rank_ic_observations(events, horizon_days=20)

    winner_obs = next(obs for obs in observations if obs["ticker"] == "WINNER" and obs["origin_date"] == "2020-01-01")
    loser_obs = next(obs for obs in observations if obs["ticker"] == "LOSER" and obs["origin_date"] == "2020-01-01")
    # pandas .rank(pct=True) convention (same as
    # train.py::build_cross_sectional_rank_targets()): with n=2, the
    # minimum maps to 1/n=0.5, not 0.0.
    assert winner_obs["realized_rank_20d"] == 1.0
    assert loser_obs["realized_rank_20d"] == 0.5


def test_compute_realized_rank_ic_observations_empty_events_returns_empty():
    assert compute_realized_rank_ic_observations([], horizon_days=20) == []


def test_compute_realized_rank_ic_observations_no_events_meet_horizon_returns_empty():
    # Only 5 events for this ticker - none can resolve a 20-day-ahead close.
    events = _daily_events("AAPL", [100.0] * 5, [0.5] * 5)

    observations = compute_realized_rank_ic_observations(events, horizon_days=20)

    assert observations == []


def test_compute_realized_rank_ic_observations_zero_or_negative_origin_close_skipped():
    closes = [0.0] + [100.0] * 20
    ranks = [0.5] * 21
    events = _daily_events("AAPL", closes, ranks)

    observations = compute_realized_rank_ic_observations(events, horizon_days=20)

    assert all(obs["origin_date"] != "2020-01-01" for obs in observations)


# ---------------------------------------------------------------------------
# compute_production_rank_ic
# ---------------------------------------------------------------------------


def test_compute_production_rank_ic_empty_observations_is_degenerate_not_raise():
    result = compute_production_rank_ic([])

    assert result == {"mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0, "num_dates": 0, "ic_values": []}


def test_compute_production_rank_ic_perfect_correlation_gives_ic_of_one():
    observations = [
        {"origin_date": "2020-01-01", "resolved_predicted_rank_20d": 0.9, "realized_rank_20d": 1.0},
        {"origin_date": "2020-01-01", "resolved_predicted_rank_20d": 0.5, "realized_rank_20d": 0.5},
        {"origin_date": "2020-01-01", "resolved_predicted_rank_20d": 0.1, "realized_rank_20d": 0.0},
    ]

    result = compute_production_rank_ic(observations)

    assert result["mean_ic"] == pytest.approx(1.0)
