"""Incremental rolling-IC state for offline tools (V5.7.0).

`portfolio.rolling_ic_gate.compute_rolling_ic_state()` re-resolves the WHOLE event history on every call, which made
every offline gate (`--as-live`, the lever script, the replay and calibration tools) cost minutes. Every observation
resolves exactly once (when its ticker's event `horizon_days` positions later appears), so the per-origin-date IC only
changes at the few dates where another ticker's observation of that origin resolves. This module computes those IC
versions once and answers "state as of date D" by a bisect, with the same semantics as the live function:

  * only events dated <= D exist, observations resolve per ticker by position (calendar-independent),
  * the realized rank is the percentile rank among the observations RESOLVED at D for that origin date,
  * the trailing window is the last `rolling_window_days` unique origin dates with >= 1 resolved observation,
  * dates under `min_names_per_date` or with zero variance contribute no IC.

The state does not depend on the gate floor, so one state function serves every floor variant.
Pure pandas/numpy, no I/O.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Callable

import numpy as np
import pandas as pd


def _origin_ic(predictions: np.ndarray, returns: np.ndarray, min_names_per_date: int) -> float | None:
    """IC of one origin date over the observations resolved so far (None when the date contributes nothing)."""
    if len(predictions) < min_names_per_date:
        return None
    realized_rank = pd.Series(returns).rank(pct=True)
    prediction_rank = pd.Series(predictions).rank(pct=True)
    if prediction_rank.nunique() < 2 or realized_rank.nunique() < 2:
        return None
    correlation = float(np.corrcoef(prediction_rank, realized_rank)[0, 1])
    return None if np.isnan(correlation) else correlation


def make_rolling_ic_state_fn(
    events: list[dict],
    *,
    horizon_days: int,
    rolling_window_days: int,
    min_names_per_date: int = 2,
) -> Callable[[str], dict]:
    """`events` is the date-sorted flat event list `compute_rolling_ic_state()` takes. Returns `state_at(date)` giving
    the same dict as `compute_rolling_ic_state(events_dated_<=_date, ...)`, cached per date."""
    usable = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("resolved_predicted_rank_20d") is not None and event.get("close_price") is not None
    ]
    dated_by_ticker: dict[str, list[str]] = defaultdict(list)
    close_by_ticker: dict[str, list[float]] = defaultdict(list)
    keyed: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for _index, event in usable:
        keyed[event["ticker"]].append((str(event["created_at"])[:10], float(event["close_price"])))
    for ticker, dated_closes in keyed.items():
        dated_closes.sort(key=lambda entry: entry[0])
        dated_by_ticker[ticker] = [entry[0] for entry in dated_closes]
        close_by_ticker[ticker] = [entry[1] for entry in dated_closes]

    # origin_date -> [(resolve_date, order, prediction, realized_return)]
    observations_by_origin: dict[str, list[tuple[str, int, float, float]]] = defaultdict(list)
    for order, (_index, event) in enumerate(usable):
        ticker = event["ticker"]
        origin_date = str(event["created_at"])[:10]
        dates = dated_by_ticker[ticker]
        position = bisect.bisect_left(dates, origin_date)
        if position >= len(dates) or dates[position] != origin_date:
            continue
        future_position = position + horizon_days
        if future_position >= len(dates):
            continue
        origin_close = close_by_ticker[ticker][position]
        if origin_close <= 0:
            continue
        observations_by_origin[origin_date].append(
            (
                dates[future_position],
                order,
                float(event["resolved_predicted_rank_20d"]),
                close_by_ticker[ticker][future_position] / origin_close - 1.0,
            )
        )

    origins = sorted(observations_by_origin)
    first_resolved: list[str] = []
    version_dates: list[list[str]] = []
    version_ic: list[list[float | None]] = []
    version_counts: list[list[int]] = []
    for origin in origins:
        observations = sorted(observations_by_origin[origin], key=lambda entry: (entry[0], entry[1]))
        distinct = sorted({entry[0] for entry in observations})
        ics: list[float | None] = []
        counts: list[int] = []
        for resolve_date in distinct:
            subset = sorted((entry for entry in observations if entry[0] <= resolve_date), key=lambda entry: entry[1])
            counts.append(len(subset))
            ics.append(
                _origin_ic(
                    np.array([entry[2] for entry in subset]), np.array([entry[3] for entry in subset]), min_names_per_date
                )
            )
        first_resolved.append(distinct[0])
        version_dates.append(distinct)
        version_ic.append(ics)
        version_counts.append(counts)

    cache: dict[str, dict] = {}
    empty = {"rolling_mean_ic": None, "num_resolved_dates": 0, "num_resolved_observations": 0}

    def state_at(date: str) -> dict:
        key = str(date)[:10]
        if key in cache:
            return cache[key]
        trailing: list[int] = []
        if rolling_window_days > 0:
            for position in range(len(origins) - 1, -1, -1):
                if first_resolved[position] <= key:
                    trailing.append(position)
                    if len(trailing) == rolling_window_days:
                        break
        if not trailing:
            cache[key] = dict(empty)
            return cache[key]
        ic_values: list[float] = []
        num_observations = 0
        for position in reversed(trailing):
            version = bisect.bisect_right(version_dates[position], key) - 1
            num_observations += version_counts[position][version]
            ic = version_ic[position][version]
            if ic is not None:
                ic_values.append(ic)
        if ic_values:
            state = {
                "rolling_mean_ic": float(np.asarray(ic_values).mean()),
                "num_resolved_dates": len(ic_values),
                "num_resolved_observations": num_observations,
            }
        else:
            state = {"rolling_mean_ic": None, "num_resolved_dates": 0, "num_resolved_observations": num_observations}
        cache[key] = state
        return state

    return state_at
