"""Phase 6 of the 5/10 -> 9/10 roadmap: production rank-IC decay
monitoring - closes a real gap. `rank_20d` is the one signal in this
codebase with a statistically significant backtest result (see
risk/position_sizing.py::rank_sizing_multiplier()'s docstring: sequence
model mean IC 0.073, t-stat 4.40 on the full series), but rank-IC was
never monitored in production at all before this - only computed offline
into `*_training_metrics.json` by train.py::compute_rank_ic().

The outcome-resolution shape here is genuinely different from every
existing trigger in performance/triggers.py: those all operate on
already-resolved experience events (the outcome - drawdown, win/loss,
confidence - is known at the moment the event was recorded). Rank-IC
can't be scored until the prediction's realized 20-trading-day forward
return is known - a "wait for the future, then join back" shape. This
module is that outcome-resolution job: given a stream of experience
events (each optionally carrying `resolved_predicted_rank_20d`/
`close_price`, see experience/redis_queue.py::build_experience_event()),
it self-joins each prediction against the SAME ticker's close ~20 TRADING
days later (not 20 calendar days - positional, within that ticker's own
event sequence, matching train.py::engineer_features()'s target_return_20d
convention of a row-indexed shift, not a calendar-day one - this
correctly respects each ticker's own trading calendar, e.g. crypto
trading every day vs. equities/bonds only on business days), computes the
realized forward return, then cross-sectionally ranks all tickers'
realized returns per origin date - reusing train.py::_rank_ic_from_arrays()'s
exact tested ranking/correlation core (no torch dependency needed here,
this module never imports torch).
"""

from __future__ import annotations

import bisect
from collections import defaultdict

import numpy as np
import pandas as pd

from train import _rank_ic_from_arrays


def compute_realized_rank_ic_observations(events: list[dict], horizon_days: int = 20) -> list[dict]:
    """Resolves each event's `resolved_predicted_rank_20d` against its own
    ticker's close price `horizon_days` TRADING days later (i.e.
    `horizon_days` positions ahead in that ticker's own date-sorted event
    sequence). Events missing either `resolved_predicted_rank_20d` or
    `close_price` (model unavailable/still warming up that bar), or whose
    horizon hasn't elapsed yet (not enough future events for that ticker),
    are silently skipped - never raises. `created_at` is truncated to its
    date component (`"YYYY-MM-DDTHH:MM:SSZ"[:10]`), matching
    experience/redis_queue.py::build_experience_event()'s ISO-8601 format.

    Returns one dict per resolved observation:
    `{"ticker", "origin_date", "mode", "resolved_predicted_rank_20d",
    "realized_return_20d", "realized_rank_20d"}` - the last field is the
    per-origin-date cross-sectional percentile rank of `realized_return_20d`
    (pandas `.rank(pct=True)`, same convention as
    train.py::build_cross_sectional_rank_targets()'s target-side ranking),
    computed once every usable event has been resolved."""
    usable = [
        event
        for event in events
        if event.get("resolved_predicted_rank_20d") is not None and event.get("close_price") is not None
    ]
    if not usable:
        return []

    dated_closes_by_ticker: dict[str, list[tuple]] = defaultdict(list)
    for event in usable:
        origin_date = str(event["created_at"])[:10]
        dated_closes_by_ticker[event["ticker"]].append((origin_date, float(event["close_price"])))
    for ticker, dated_closes in dated_closes_by_ticker.items():
        dated_closes.sort(key=lambda entry: entry[0])

    resolved: list[dict] = []
    for event in usable:
        ticker = event["ticker"]
        origin_date = str(event["created_at"])[:10]
        dated_closes = dated_closes_by_ticker[ticker]
        dates_only = [entry[0] for entry in dated_closes]
        position = bisect.bisect_left(dates_only, origin_date)
        if position >= len(dated_closes) or dates_only[position] != origin_date:
            continue

        future_position = position + horizon_days
        if future_position >= len(dated_closes):
            continue

        origin_close = dated_closes[position][1]
        _future_date, future_close = dated_closes[future_position]
        if origin_close <= 0:
            continue

        resolved.append(
            {
                "ticker": ticker,
                "origin_date": origin_date,
                "mode": event.get("mode"),
                "resolved_predicted_rank_20d": float(event["resolved_predicted_rank_20d"]),
                "realized_return_20d": future_close / origin_close - 1.0,
            }
        )

    if not resolved:
        return []

    frame = pd.DataFrame(resolved)
    frame["realized_rank_20d"] = frame.groupby("origin_date")["realized_return_20d"].rank(pct=True)
    return frame.to_dict(orient="records")


def compute_production_rank_ic(observations: list[dict], non_overlapping_stride: int = 1) -> dict:
    """Runs train.py::_rank_ic_from_arrays() over
    compute_realized_rank_ic_observations()'s output - the production
    equivalent of train.py::compute_rank_ic(), sharing its exact tested
    core (plain numpy arrays, no torch dependency)."""
    if not observations:
        return {"mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0, "num_dates": 0, "ic_values": []}

    predictions = np.array([observation["resolved_predicted_rank_20d"] for observation in observations])
    targets = np.array([observation["realized_rank_20d"] for observation in observations])
    dates = np.array([observation["origin_date"] for observation in observations])
    return _rank_ic_from_arrays(predictions, targets, dates, non_overlapping_stride=non_overlapping_stride)
