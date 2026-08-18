"""Tests for portfolio/rolling_ic_gate.py (V5.3.5, development/Problems.md
#102). Conventions match tests/test_kill_switch.py's per-condition style
against evaluate_kill_switch() - this module's evaluate_rolling_ic_gate()
is its direct sibling.
"""

import pytest

from portfolio.rolling_ic_gate import compute_rolling_ic_state, evaluate_rolling_ic_gate


def _event(ticker: str, date: str, rank: float, close: float) -> dict:
    return {"ticker": ticker, "created_at": f"{date}T00:00:00Z", "resolved_predicted_rank_20d": rank, "close_price": close}


def _resolvable_buffer(ticker: str, num_days: int, ranks: list[float] | None = None, growth_per_day: float = 1.0) -> list[dict]:
    """A buffer with enough trailing history (horizon_days=20 plus
    num_days more) for every one of the first `num_days` origin dates to
    resolve - the minimum realistic shape compute_rolling_ic_state() needs
    to produce a non-degenerate reading. `growth_per_day` must differ
    between two tickers used together in the same test, or their realized
    returns tie on every date - rank_ic_from_arrays() correctly (and
    silently) drops any date where the realized-return side has no
    variance to rank, so an accidental tie across the whole fixture would
    make every date resolve to zero IC observations, not a real signal."""
    total = num_days + 20
    closes = [100.0 + index * growth_per_day for index in range(total)]
    rank_values = ranks if ranks is not None else [0.5] * total
    return [_event(ticker, f"2020-{1 + (day // 28):02d}-{1 + (day % 28):02d}", rank_values[day], closes[day]) for day in range(total)]


# ---------------------------------------------------------------------------
# compute_rolling_ic_state
# ---------------------------------------------------------------------------


def test_compute_rolling_ic_state_empty_buffer_returns_none_not_zero():
    state = compute_rolling_ic_state([], horizon_days=20, rolling_window_days=40)
    assert state == {"rolling_mean_ic": None, "num_resolved_dates": 0, "num_resolved_observations": 0}


def test_compute_rolling_ic_state_insufficient_horizon_returns_none():
    # Only 10 days of history - horizon_days=20 means nothing can resolve yet.
    buffer = [_event("AAPL", f"2020-01-{day:02d}", 0.5, 100.0 + day) for day in range(1, 11)]
    state = compute_rolling_ic_state(buffer, horizon_days=20, rolling_window_days=40)
    assert state["rolling_mean_ic"] is None
    assert state["num_resolved_dates"] == 0


def test_compute_rolling_ic_state_restricts_to_trailing_window_unique_dates():
    # Two tickers, DIFFERENT growth rates so realized returns actually
    # differ per date (see _resolvable_buffer()'s own note) - every origin
    # date then resolves with >=2 assets. 30 resolvable origin dates
    # total, but rolling_window_days=10 must only use the last 10.
    winner = _resolvable_buffer("WINNER", 30, ranks=[0.9] * 50, growth_per_day=2.0)
    loser = _resolvable_buffer("LOSER", 30, ranks=[0.1] * 50, growth_per_day=0.5)
    buffer = winner + loser

    state = compute_rolling_ic_state(buffer, horizon_days=20, rolling_window_days=10)

    assert state["num_resolved_dates"] == 10


def test_compute_rolling_ic_state_num_resolved_observations_reflects_window_not_full_buffer():
    winner = _resolvable_buffer("WINNER", 30, ranks=[0.9] * 50, growth_per_day=2.0)
    loser = _resolvable_buffer("LOSER", 30, ranks=[0.1] * 50, growth_per_day=0.5)
    buffer = winner + loser

    full_state = compute_rolling_ic_state(buffer, horizon_days=20, rolling_window_days=30)
    windowed_state = compute_rolling_ic_state(buffer, horizon_days=20, rolling_window_days=5)

    assert windowed_state["num_resolved_observations"] < full_state["num_resolved_observations"]


def test_compute_rolling_ic_state_min_names_per_date_excludes_thin_dates_from_aggregate():
    # Only 2 tickers resolve per date in this fixture - a 2-name date is
    # mathematically forced to +-1 IC regardless of real skill
    # (development/Problems.md #102, found via a real calibration run).
    # min_names_per_date=3 must exclude every date here, leaving nothing.
    winner = _resolvable_buffer("WINNER", 30, ranks=[0.9] * 50, growth_per_day=2.0)
    loser = _resolvable_buffer("LOSER", 30, ranks=[0.1] * 50, growth_per_day=0.5)
    buffer = winner + loser

    default_state = compute_rolling_ic_state(buffer, horizon_days=20, rolling_window_days=10)
    filtered_state = compute_rolling_ic_state(buffer, horizon_days=20, rolling_window_days=10, min_names_per_date=3)

    assert default_state["num_resolved_dates"] == 10
    assert filtered_state["num_resolved_dates"] == 0
    assert filtered_state["rolling_mean_ic"] is None


# ---------------------------------------------------------------------------
# evaluate_rolling_ic_gate
# ---------------------------------------------------------------------------


def test_disabled_never_vetoes_regardless_of_state():
    state = {"rolling_mean_ic": -0.9, "num_resolved_dates": 100, "num_resolved_observations": 500}
    result = evaluate_rolling_ic_gate(state, {"enabled": False, "min_rolling_mean_ic": 0.0})
    assert result["engaged"] is True
    assert result["reason"] == "rolling_ic_gate_disabled"


def test_default_config_missing_enabled_key_never_vetoes():
    state = {"rolling_mean_ic": -0.9, "num_resolved_dates": 100, "num_resolved_observations": 500}
    result = evaluate_rolling_ic_gate(state, {})
    assert result["engaged"] is True


def test_insufficient_resolved_dates_fails_open_not_a_false_veto():
    # A genuinely bad rolling IC, but not enough resolved dates yet - must
    # be treated as "gate not evaluated", never as "IC is bad".
    state = {"rolling_mean_ic": -0.9, "num_resolved_dates": 5, "num_resolved_observations": 10}
    result = evaluate_rolling_ic_gate(
        state, {"enabled": True, "min_rolling_mean_ic": 0.0, "min_resolved_dates_required": 40}
    )
    assert result["engaged"] is True
    assert result["reason"] == "rolling_ic_gate_insufficient_history"


def test_none_rolling_mean_ic_fails_open_even_with_enough_resolved_dates():
    # Defensive: num_resolved_dates alone should never be trusted over the
    # None-ness of rolling_mean_ic itself.
    state = {"rolling_mean_ic": None, "num_resolved_dates": 100, "num_resolved_observations": 500}
    result = evaluate_rolling_ic_gate(state, {"enabled": True, "min_rolling_mean_ic": 0.0, "min_resolved_dates_required": 40})
    assert result["engaged"] is True
    assert result["reason"] == "rolling_ic_gate_insufficient_history"


def test_rolling_ic_below_floor_vetoes():
    state = {"rolling_mean_ic": -0.05, "num_resolved_dates": 40, "num_resolved_observations": 200}
    result = evaluate_rolling_ic_gate(state, {"enabled": True, "min_rolling_mean_ic": 0.0, "min_resolved_dates_required": 40})
    assert result["engaged"] is False
    assert result["reason"] == "rolling_ic_below_floor"


def test_rolling_ic_above_floor_engages():
    state = {"rolling_mean_ic": 0.15, "num_resolved_dates": 40, "num_resolved_observations": 200}
    result = evaluate_rolling_ic_gate(state, {"enabled": True, "min_rolling_mean_ic": 0.0, "min_resolved_dates_required": 40})
    assert result["engaged"] is True
    assert result["reason"] == "rolling_ic_above_floor"


def test_unconfigured_min_rolling_mean_ic_defaults_to_never_below():
    # Enabling the gate without configuring a real floor must never
    # accidentally veto - matches risk/kill_switch.py's own
    # _NEVER_BELOW-sentinel-by-default guardrail.
    state = {"rolling_mean_ic": -0.99, "num_resolved_dates": 40, "num_resolved_observations": 200}
    result = evaluate_rolling_ic_gate(state, {"enabled": True, "min_resolved_dates_required": 40})
    assert result["engaged"] is True


def test_min_resolved_dates_required_defaults_to_rolling_window_days():
    state = {"rolling_mean_ic": -0.9, "num_resolved_dates": 39, "num_resolved_observations": 200}
    result = evaluate_rolling_ic_gate(state, {"enabled": True, "min_rolling_mean_ic": 0.0, "rolling_window_days": 40})
    assert result["engaged"] is True
    assert result["reason"] == "rolling_ic_gate_insufficient_history"


def test_observed_and_threshold_values_reported_for_every_branch():
    state = {"rolling_mean_ic": 0.15, "num_resolved_dates": 40, "num_resolved_observations": 200}
    result = evaluate_rolling_ic_gate(state, {"enabled": True, "min_rolling_mean_ic": 0.05, "min_resolved_dates_required": 40})
    assert result["observed_rolling_mean_ic"] == pytest.approx(0.15)
    assert result["min_rolling_mean_ic"] == pytest.approx(0.05)
    assert result["num_resolved_dates"] == 40
