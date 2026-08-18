"""Day-by-day OFFLINE replay of `portfolio.rolling_ic_gate`'s two decision
functions against a historical dataset (V5.3.5, development/Problems.md
#102) - the direct sibling of `evaluation/kill_switch_replay.py`'s
day-by-day, no-lookahead, walk-forward structure, for this round's new
rolling-IC gate instead of the kill switch.

This is the critical pre-`main.py` checkpoint the V5.3.5 plan calls out:
run this against the historical dataset with `evaluation/
rolling_ic_gate_calibration.py`'s calibrated floor and confirm
disengagement concentrates in the three known bad eras (Apr-Sep 2019,
Dec 2019-Mar 2020, Jun-Sep 2020) rather than spreading uniformly across
the whole run - entirely offline, before `main.py` is touched at all. A
uniform reduction would mean this gate is just a redundant second
dispersion floor, not a genuine skill signal, and is the signal to stop
and revisit before A6 wires anything into the live path.

NO-LOOKAHEAD DISCIPLINE - the single most important property this module
has to get right: at each rebalance date, the event buffer passed to
`compute_rolling_ic_state()` is built from `evaluation.
rolling_ic_gate_calibration.build_event_buffer()` and then sliced to only
events dated on-or-before that date (the same technique, and the same
reason, that module's own docstring explains) - a decision "as of" date D
must never see a row dated after D, exactly matching what main.py's own
live in-memory buffer could possibly contain by that point in a real run.
"""

from __future__ import annotations

import bisect

from evaluation.rolling_ic_gate_calibration import build_event_buffer
from portfolio.rolling_ic_gate import compute_rolling_ic_state, evaluate_rolling_ic_gate

# development/Problems.md #102's own three named bad eras, found from this
# round's research into rolling IC vs. the model's per-era IC diagnostic
# (#71) - used only by summarize_rolling_ic_gate_replay()'s per-era
# breakdown, so the offline report can be read directly against them
# without a throwaway script re-deriving these boundaries by hand.
KNOWN_ERAS = {
    "era_0_good": ("2019-01-01", "2019-04-01"),
    "era_1_bad_apr_sep_2019": ("2019-04-01", "2019-09-01"),
    "era_2_bad_dec2019_mar2020": ("2019-12-01", "2020-03-01"),
    "era_3_bad_jun_sep_2020": ("2020-06-01", "2020-09-01"),
}


def replay_rolling_ic_gate_over_dataset(
    dataset,
    *,
    raw_score_column: str,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "close",
    rebalance_dates: list[str],
    horizon_days: int,
    rolling_window_days: int,
    gate_config: dict,
    min_names_per_date: int = 10,
) -> list[dict]:
    """Builds the full event buffer once (`build_event_buffer()`), then for
    each date in `rebalance_dates` (must already be sorted - callers own
    that, same convention as `rank_book_simulator.py`'s unique_dates loop;
    should be the SAME cadence a real book rebalance uses, not necessarily
    every calendar date, matching main.py's own gate-is-only-consulted-on-
    rebalance-bars design) slices the buffer to events dated <= that date
    and evaluates the gate exactly as `portfolio.book_construction.
    _select_book_group()` would.

    `min_names_per_date` (V5.3.5, development/Problems.md #102) - passed
    through to `compute_rolling_ic_state()`; defaults to 10 for the same
    reason `evaluation/rolling_ic_gate_calibration.py::
    calibrate_rolling_ic_floor()` does (see that function's own
    docstring) - a real replay run at this module's own default of 2
    showed the calibrated floor barely engaging during two of three known
    historically-bad eras, traced to thin-universe origin dates forcing
    spurious +-1.0 IC readings into the rolling mean.

    Returns one dict per rebalance date: {"date", "engaged", "reason",
    "observed_rolling_mean_ic", "min_rolling_mean_ic", "num_resolved_dates"}
    - `evaluate_rolling_ic_gate()`'s own result dict plus "date"."""
    events = build_event_buffer(
        dataset, raw_score_column=raw_score_column, ticker_column=ticker_column,
        date_column=date_column, close_column=close_column,
    )
    event_dates = [str(event["created_at"])[:10] for event in events]

    records = []
    for date in rebalance_dates:
        cutoff_index = bisect.bisect_right(event_dates, str(date))
        buffer_up_to_date = events[:cutoff_index]
        state = compute_rolling_ic_state(
            buffer_up_to_date, horizon_days=horizon_days, rolling_window_days=rolling_window_days,
            min_names_per_date=min_names_per_date,
        )
        result = evaluate_rolling_ic_gate(state, gate_config)
        records.append({"date": str(date), **result})

    return records


def _era_for_date(date: str) -> str | None:
    for era_name, (start, end) in KNOWN_ERAS.items():
        if start <= date < end:
            return era_name
    return None


def summarize_rolling_ic_gate_replay(records: list[dict]) -> dict:
    """Aggregate engaged/disengaged fractions overall and per known era
    (`KNOWN_ERAS` above), mirroring `evaluation/kill_switch_replay.py::
    summarize_kill_switch_replay()`'s aggregation shape. Dates outside
    every named era are still counted in `"overall"` but not attributed to
    any `"by_era"` entry - `KNOWN_ERAS` deliberately doesn't cover the
    whole historical window, only the four eras this round's research
    already characterized."""
    total_dates = len(records)
    disengaged = [record for record in records if not record["engaged"]]
    disengaged_by_floor = [record for record in records if record["reason"] == "rolling_ic_below_floor"]

    by_era: dict[str, dict] = {}
    for era_name in KNOWN_ERAS:
        era_records = [record for record in records if _era_for_date(record["date"]) == era_name]
        era_disengaged = [record for record in era_records if not record["engaged"]]
        by_era[era_name] = {
            "total_dates": len(era_records),
            "disengaged_days": len(era_disengaged),
            "disengaged_day_fraction": (len(era_disengaged) / len(era_records)) if era_records else None,
        }

    return {
        "overall": {
            "total_dates": total_dates,
            "disengaged_days": len(disengaged),
            "disengaged_day_fraction": (len(disengaged) / total_dates) if total_dates else 0.0,
            "disengaged_days_below_floor": len(disengaged_by_floor),
        },
        "by_era": by_era,
    }
