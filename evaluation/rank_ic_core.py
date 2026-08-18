"""V5.3.5 (development/Problems.md #102) - the genuinely light, torch-free
core of this codebase's rank-IC pipeline (correlation math + realized-
outcome resolution + aggregation), extracted so `main.py`'s live/backtest
decision path can import it directly with zero risk of pulling in the
training stack.

Before this module existed, the only home for this logic was split
across `train.py::_rank_ic_from_arrays()` (imports `torch`/`sklearn` at
module scope) and `performance/rank_ic_monitor.py` (imports
`train._rank_ic_from_arrays`, and is itself imported transitively by
`performance/__init__.py` via `.trigger_worker` - so even `from
performance import anything` drags in the full training stack). `main.py`
already hit and documented this exact class of failure once
(development/Problems.md #16 - Lean's hard, non-configurable 90-second
`Initialize()` isolator timeout) and has a standing deferred-import
workaround for the `performance` package specifically because of it. A
new live rolling-IC gate (`portfolio/rolling_ic_gate.py`) needs this same
math available as a genuinely safe top-level import.

`train.py::_rank_ic_from_arrays()` and `performance/rank_ic_monitor.py`'s
two functions are now thin re-export aliases over this module - moved,
not duplicated. Every existing caller (train.py's own IC call sites,
performance/trigger_worker.py, and every test importing either) keeps
working unchanged.
"""

from __future__ import annotations

import bisect
from collections import defaultdict

import numpy as np
import pandas as pd


def rank_ic_from_arrays(
    predictions: np.ndarray,
    targets: np.ndarray,
    dates: np.ndarray,
    non_overlapping_stride: int = 1,
    min_names_per_date: int = 2,
) -> dict:
    """Per-date Spearman rank correlation ("rank-IC") between a model's raw
    rank_5d/20d prediction score and the realized cross-sectional rank
    target (target_rank_5d/20d - already a per-date percentile rank of
    forward return, see train.py::build_cross_sectional_rank_targets()).
    This is the standard evaluation metric for a cross-sectional/long-short
    signal: a mean rank-IC of 0.02-0.05 with a real t-stat is a genuine,
    monetizable edge in this literature.

    Spearman(A, B) = Pearson(rank(A), rank(B)); target_rank is already
    rank(realized return) rescaled to [0, 1] (a positive affine transform,
    which Pearson is invariant to), so only the model's own raw prediction
    needs an explicit per-date rank transform before a plain Pearson
    correlation against target_rank directly reproduces the true Spearman
    correlation between prediction and realized return.

    `non_overlapping_stride` (e.g. 5 for the 5d horizon, 20 for the 20d
    horizon) subsamples to every Nth unique date before computing -
    consecutive daily rows share most of their forward-return window, so
    the naive daily IC series is autocorrelated and its plain t-stat
    overstates significance; the non-overlapping subsample gives a more
    honest (if noisier, fewer-observation) significance check. Pass 1
    (default) for the full, autocorrelated series.

    `min_names_per_date` (V5.3.5, development/Problems.md #102) - default 2
    reproduces this function's original behavior exactly (train.py's/
    performance/rank_ic_monitor.py's existing callers are unaffected). A
    date with exactly 2 names is mathematically FORCED to a Pearson
    correlation of either +1 or -1 (two points always fit a line, tie
    aside) - a legitimate computation, but statistically uninformative,
    and it gets averaged into mean_ic with the exact same weight as a
    date with 100 names. portfolio/rolling_ic_gate.py's offline
    calibration/replay tools raise this well above 2 specifically because
    a walk-forward rolling-IC distribution's early, thin-universe dates
    were found (V5.3.5, real data) to produce spurious +-1 readings that
    dominate the low end of the distribution.

    Dates with fewer than `min_names_per_date` eligible (non-NaN target)
    assets, or zero variance on either side (e.g. every asset tied),
    contribute no IC value for that date (skipped, not a spurious 0.0 -
    which would misrepresent "undefined" as "no correlation")."""
    frame = pd.DataFrame({"date": np.asarray(dates), "prediction": predictions, "target_rank": targets})
    frame = frame.dropna(subset=["target_rank"])

    if non_overlapping_stride > 1:
        unique_dates = sorted(frame["date"].unique())
        keep_dates = set(unique_dates[::non_overlapping_stride])
        frame = frame[frame["date"].isin(keep_dates)]

    ic_values = []
    for _, group in frame.groupby("date"):
        if len(group) < min_names_per_date:
            continue
        prediction_rank = group["prediction"].rank(pct=True)
        if prediction_rank.nunique() < 2 or group["target_rank"].nunique() < 2:
            continue
        correlation = float(np.corrcoef(prediction_rank, group["target_rank"])[0, 1])
        if not np.isnan(correlation):
            ic_values.append(correlation)

    if not ic_values:
        return {"mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0, "num_dates": 0, "ic_values": []}

    ic_array = np.asarray(ic_values)
    mean_ic = float(ic_array.mean())
    std_ic = float(ic_array.std(ddof=1)) if len(ic_array) >= 2 else 0.0
    t_stat = float(mean_ic / (std_ic / np.sqrt(len(ic_array)))) if std_ic > 0 else 0.0
    return {
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "t_stat": t_stat,
        "num_dates": int(len(ic_array)),
        "ic_values": [float(value) for value in ic_values],
    }


def resolve_realized_rank_ic_observations(events: list[dict], horizon_days: int = 20) -> list[dict]:
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


def aggregate_rank_ic_observations(
    observations: list[dict], non_overlapping_stride: int = 1, min_names_per_date: int = 2
) -> dict:
    """Runs rank_ic_from_arrays() over resolve_realized_rank_ic_observations()'s
    output - shares the exact same tested correlation core every other IC
    metric in this codebase goes through. `min_names_per_date` - see
    rank_ic_from_arrays()'s own docstring; default 2 preserves this
    function's original behavior exactly."""
    if not observations:
        return {"mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0, "num_dates": 0, "ic_values": []}

    predictions = np.array([observation["resolved_predicted_rank_20d"] for observation in observations])
    targets = np.array([observation["realized_rank_20d"] for observation in observations])
    dates = np.array([observation["origin_date"] for observation in observations])
    return rank_ic_from_arrays(
        predictions, targets, dates, non_overlapping_stride=non_overlapping_stride, min_names_per_date=min_names_per_date
    )
