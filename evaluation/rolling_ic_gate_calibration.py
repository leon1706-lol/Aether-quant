"""Calibrates `phase_v2.rolling_ic_gate.min_rolling_mean_ic` from real data
(V5.3.5, development/Problems.md #102) - the same "derive the number,
don't guess it" discipline `aq evaluate --calibrate-book-spread` already
established for `min_rank_confidence_spread`, applied to this round's new
gate so its shipped floor is never a hand-guessed constant either.

Deliberately reuses, never re-derives: `portfolio.rolling_ic_gate.
compute_rolling_ic_state()` (the exact aggregation the live gate and
`evaluation/rolling_ic_gate_replay.py` both call) and `evaluation.
rank_ic_core.resolve_realized_rank_ic_observations()` beneath it. A
calibrated floor computed here can never silently disagree with what the
live gate means by "rolling IC," because it is the same code, not a
parallel approximation.

WALK-FORWARD, NOT A SINGLE FULL-HISTORY READING: naively calling
`compute_rolling_ic_state()` once on the dataset's entire event history
would let observations whose resolution only became known LATE in the
dataset leak into a rolling-window reading nominally "as of" an EARLIER
sample date - a real lookahead bug, since `resolve_realized_rank_ic_observations()`
resolves every observation using the full buffer's own future close
prices, not bounded to any particular "as of" date. This module avoids
that by sampling a strided sequence of dates and, at each one, slicing
the event buffer to only events dated on-or-before that sample date
before calling `compute_rolling_ic_state()` - exactly what a live buffer
would contain by that date, never more. `evaluation/rolling_ic_gate_replay.py`
shares this same buffer-slicing discipline (see that module's own
docstring) since it needs the identical no-lookahead guarantee for a
different purpose (a per-date engagement decision instead of a
calibration distribution).

`sample_stride_days=5` (not every single date) keeps this an O(num_samples
x average_buffer_size) offline computation rather than O(num_dates^2) -
acceptable for a tool run once, by hand, never on any per-bar live path.
"""

from __future__ import annotations

import bisect

import numpy as np
import pandas as pd

from portfolio.rolling_ic_gate import compute_rolling_ic_state

_ROLLING_IC_DISTRIBUTION_PERCENTILES = {"p10": 0.10, "p25": 0.25, "median": 0.50, "p75": 0.75}

# Same sentinel value as portfolio.rolling_ic_gate's own (private,
# module-local) _NEVER_BELOW - kept as an independent local copy rather
# than a cross-module import of a private name, matching how
# risk/kill_switch.py's own _NEVER_BELOW is never imported elsewhere
# either. Only meaningful as "the gate's own never-trips floor value";
# never compared against the other module's copy directly.
_NEVER_BELOW = -1e12


def build_event_buffer(
    dataset: pd.DataFrame,
    *,
    raw_score_column: str,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "close",
) -> list[dict]:
    """Converts `dataset` into the flat, date-sorted event-dict shape
    `compute_rolling_ic_state()`/`resolve_realized_rank_ic_observations()`
    expect - the offline equivalent of main.py's Pass 1c buffer append,
    reused by both this module and `evaluation/rolling_ic_gate_replay.py`
    so the two tools can never disagree about what an "event" is. Rows
    missing either the raw score or the close price are skipped (mirrors
    `resolve_realized_rank_ic_observations()`'s own "model still warming
    up" skip contract), never fabricated."""
    ordered = dataset.sort_values(date_column, kind="stable")
    events: list[dict] = []
    for ticker, date, score, close in zip(
        ordered[ticker_column], ordered[date_column], ordered[raw_score_column], ordered[close_column]
    ):
        if score is None or (isinstance(score, float) and np.isnan(score)):
            continue
        if close is None or (isinstance(close, float) and np.isnan(close)):
            continue
        events.append(
            {
                "ticker": str(ticker),
                "created_at": f"{date}T00:00:00Z",
                "resolved_predicted_rank_20d": float(score),
                "close_price": float(close),
            }
        )
    return events


def calibrate_rolling_ic_floor(
    dataset: pd.DataFrame,
    *,
    raw_score_column: str,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "close",
    horizon_days: int,
    rolling_window_days: int,
    percentile: float = 0.10,
    sample_stride_days: int = 5,
    min_names_per_date: int = 10,
) -> dict:
    """Walk-forward: at every `sample_stride_days`-th unique date in
    `dataset`, computes the rolling IC state a live buffer would have had
    by that date (event buffer sliced to <= that date, via
    `build_event_buffer()` + `compute_rolling_ic_state()`), collects every
    non-None `rolling_mean_ic` reading into a distribution, and returns
    the `percentile`-th quantile as the calibrated floor.

    Sample dates before enough history has accumulated (compute_rolling_ic_state()
    returns `rolling_mean_ic=None`) are EXCLUDED from the distribution, not
    counted as a 0.0 reading - a cold-start gap is missing data, not
    evidence of zero skill.

    `min_names_per_date` (V5.3.5, development/Problems.md #102) - passed
    through to `compute_rolling_ic_state()`. Defaults to 10, well above
    `compute_rolling_ic_state()`'s own pure-function default of 2: a real
    run against this project's historical dataset found the p10-percentile
    floor dominated by spurious +-1.0 readings from origin dates where
    only 2-3 names had resolved (thin-universe/model-warmup dates,
    mathematically forced to an extreme correlation regardless of real
    skill) - excluding them here is what makes the resulting distribution
    represent genuine cross-sectional skill rather than early-history
    noise. See evaluation.rank_ic_core.rank_ic_from_arrays()'s own
    docstring for the full mechanism.

    Returns:
        {"calibrated_min_rolling_mean_ic": float,
         "percentile": float,
         "num_samples_used": int,
         "num_samples_skipped_insufficient_history": int,
         "rolling_ic_distribution": {"min", "p10", "p25", "median", "p75", "max"}}

    An empty/all-thin dataset returns calibrated_min_rolling_mean_ic=_NEVER_BELOW
    (portfolio.rolling_ic_gate's own "gate never trips" sentinel) and an
    all-None distribution, never raises."""
    events = build_event_buffer(
        dataset, raw_score_column=raw_score_column, ticker_column=ticker_column,
        date_column=date_column, close_column=close_column,
    )
    if not events:
        return {
            "calibrated_min_rolling_mean_ic": _NEVER_BELOW,
            "percentile": percentile,
            "num_samples_used": 0,
            "num_samples_skipped_insufficient_history": 0,
            "rolling_ic_distribution": {"min": None, "p10": None, "p25": None, "median": None, "p75": None, "max": None},
        }

    event_dates = [str(event["created_at"])[:10] for event in events]
    unique_dates = sorted(set(event_dates))
    sample_dates = unique_dates[::sample_stride_days] if sample_stride_days > 0 else unique_dates

    readings: list[float] = []
    num_samples_skipped_insufficient_history = 0
    for sample_date in sample_dates:
        cutoff_index = bisect.bisect_right(event_dates, sample_date)
        buffer_up_to_date = events[:cutoff_index]
        state = compute_rolling_ic_state(
            buffer_up_to_date, horizon_days=horizon_days, rolling_window_days=rolling_window_days,
            min_names_per_date=min_names_per_date,
        )
        if state["rolling_mean_ic"] is None:
            num_samples_skipped_insufficient_history += 1
            continue
        readings.append(state["rolling_mean_ic"])

    if not readings:
        return {
            "calibrated_min_rolling_mean_ic": _NEVER_BELOW,
            "percentile": percentile,
            "num_samples_used": 0,
            "num_samples_skipped_insufficient_history": num_samples_skipped_insufficient_history,
            "rolling_ic_distribution": {"min": None, "p10": None, "p25": None, "median": None, "p75": None, "max": None},
        }

    readings_array = np.array(readings, dtype=np.float64)
    distribution = {"min": float(np.min(readings_array)), "max": float(np.max(readings_array))}
    for name, quantile in _ROLLING_IC_DISTRIBUTION_PERCENTILES.items():
        distribution[name] = float(np.quantile(readings_array, quantile))

    return {
        "calibrated_min_rolling_mean_ic": float(np.quantile(readings_array, percentile)),
        "percentile": percentile,
        "num_samples_used": len(readings),
        "num_samples_skipped_insufficient_history": num_samples_skipped_insufficient_history,
        "rolling_ic_distribution": distribution,
    }
