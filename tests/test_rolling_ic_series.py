"""evaluation.rolling_ic_series must reproduce portfolio.rolling_ic_gate.compute_rolling_ic_state on every date."""

from __future__ import annotations

import bisect

import numpy as np
import pandas as pd
import pytest

from evaluation.live_parity import make_rolling_ic_gate_fn
from evaluation.rolling_ic_gate_calibration import build_event_buffer
from evaluation.rolling_ic_series import make_rolling_ic_state_fn
from portfolio.rolling_ic_gate import compute_rolling_ic_state, evaluate_rolling_ic_gate


def _mixed_calendar_frame(seed: int = 3, periods: int = 220) -> pd.DataFrame:
    """Equity (weekdays), crypto (7 days) and forex (Sun-Fri) tickers: resolutions land on different dates per class."""
    rng = np.random.default_rng(seed)
    rows = []
    all_days = pd.date_range("2019-01-01", periods=periods, freq="D")
    calendars = {
        "equity": [d for d in all_days if d.dayofweek < 5],
        "crypto": list(all_days),
        "forex": [d for d in all_days if d.dayofweek != 5],
    }
    tickers = {"equity": [f"E{i:02d}" for i in range(14)], "crypto": ["C1", "C2", "C3"], "forex": ["F1", "F2", "F3", "F4"]}
    for kind, names in tickers.items():
        for name in names:
            close = 100.0
            for day in calendars[kind]:
                close *= 1.0 + rng.normal(0, 0.01)
                rows.append({"ticker": name, "date": day.strftime("%Y-%m-%d"), "close": close, "pred": rng.normal() + 0.0})
    return pd.DataFrame(rows)


def _reference(events, key, **kwargs):
    event_dates = [str(event["created_at"])[:10] for event in events]
    return compute_rolling_ic_state(events[: bisect.bisect_right(event_dates, key)], **kwargs)


def _assert_same(actual, expected):
    assert actual["num_resolved_dates"] == expected["num_resolved_dates"]
    assert actual["num_resolved_observations"] == expected["num_resolved_observations"]
    if expected["rolling_mean_ic"] is None:
        assert actual["rolling_mean_ic"] is None
    else:
        assert actual["rolling_mean_ic"] == pytest.approx(expected["rolling_mean_ic"], abs=1e-12)


@pytest.mark.parametrize("horizon,window,min_names", [(5, 10, 10), (20, 40, 10), (5, 8, 2), (3, 0, 2)])
def test_series_equals_compute_rolling_ic_state_on_every_date(horizon, window, min_names):
    events = build_event_buffer(_mixed_calendar_frame(), raw_score_column="pred")
    state_fn = make_rolling_ic_state_fn(
        events, horizon_days=horizon, rolling_window_days=window, min_names_per_date=min_names
    )
    dates = sorted({str(event["created_at"])[:10] for event in events})
    for key in dates[:: 3]:
        _assert_same(
            state_fn(key),
            _reference(events, key, horizon_days=horizon, rolling_window_days=window, min_names_per_date=min_names),
        )


def test_series_equals_the_live_bounded_buffer():
    """Live keeps a deque of len(symbols) * (window + horizon + 20) events; the oldest are never in the trailing window."""
    frame = _mixed_calendar_frame()
    events = build_event_buffer(frame, raw_score_column="pred")
    horizon, window = 5, 10
    maxlen = frame["ticker"].nunique() * (window + horizon + 20)
    event_dates = [str(event["created_at"])[:10] for event in events]
    state_fn = make_rolling_ic_state_fn(events, horizon_days=horizon, rolling_window_days=window, min_names_per_date=10)
    for key in sorted(set(event_dates))[40::7]:
        cutoff = bisect.bisect_right(event_dates, key)
        bounded = compute_rolling_ic_state(
            events[max(0, cutoff - maxlen) : cutoff], horizon_days=horizon, rolling_window_days=window, min_names_per_date=10
        )
        _assert_same(state_fn(key), bounded)


def test_series_ignores_unusable_events_and_handles_empty_input():
    empty = make_rolling_ic_state_fn([], horizon_days=5, rolling_window_days=10)("2019-02-01")
    assert empty == {"rolling_mean_ic": None, "num_resolved_dates": 0, "num_resolved_observations": 0}
    events = build_event_buffer(_mixed_calendar_frame(periods=90), raw_score_column="pred")
    noisy = events + [{"ticker": "E00", "created_at": "2019-03-01T00:00:00Z", "resolved_predicted_rank_20d": None, "close_price": 1.0}]
    noisy.sort(key=lambda event: event["created_at"][:10])
    reference = make_rolling_ic_state_fn(events, horizon_days=5, rolling_window_days=10, min_names_per_date=10)
    candidate = make_rolling_ic_state_fn(noisy, horizon_days=5, rolling_window_days=10, min_names_per_date=10)
    _assert_same(candidate("2019-03-20"), reference("2019-03-20"))


def test_gate_fn_with_shared_state_matches_per_floor_gates():
    frame = _mixed_calendar_frame(periods=150)
    config = {"horizon_days": 5, "rolling_window_days": 10, "min_resolved_dates_required": 5, "min_names_per_date": 10}
    events = build_event_buffer(frame, raw_score_column="pred")
    state_fn = make_rolling_ic_state_fn(events, horizon_days=5, rolling_window_days=10, min_names_per_date=10)
    for floor in (-0.5, 0.0, 0.05):
        shared = make_rolling_ic_gate_fn(
            frame, raw_score_column="pred", gate_config=dict(config, min_rolling_mean_ic=floor), state_fn=state_fn
        )
        for key in sorted(frame["date"].unique())[30::11]:
            reference = evaluate_rolling_ic_gate(
                _reference(events, key, horizon_days=5, rolling_window_days=10, min_names_per_date=10),
                dict(config, min_rolling_mean_ic=floor, enabled=True),
            )
            result = shared(key)
            assert result["engaged"] == reference["engaged"] and result["reason"] == reference["reason"]
