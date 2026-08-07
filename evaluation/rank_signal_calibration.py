"""Calibrates `phase_v2.portfolio_book.min_rank_confidence_spread` from
real data (V5.1, development/Problems.md) - the same "derive the number,
don't guess it" discipline `aq evaluate --calibrate-edge` already
established for `phase_v2.costs.edge_bps_per_rank_unit`.

Deliberately reuses, never re-derives: `portfolio.rank_signal.select_raw_rank_score()`
(the exact blend formula main.py's live Pass 1c applies),
`portfolio.rank_signal.cross_sectional_rank_scores()` (the exact
normalization main.py applies before book selection), and
`portfolio.book_construction.build_rank_based_book()` +
`compute_confidence_spread()` (the exact selection and gate-comparison
main.py's live book uses). A calibrated threshold computed here can never
silently disagree with what the live gate would have done on the same
historical day, because it is the same code, not a parallel
approximation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from portfolio.book_construction import build_rank_based_book, compute_confidence_spread
from portfolio.rank_signal import cross_sectional_rank_scores, select_raw_rank_score

_SPREAD_DISTRIBUTION_PERCENTILES = {"p10": 0.10, "p25": 0.25, "median": 0.50, "p75": 0.75}


def compute_blended_raw_scores(
    dataset: pd.DataFrame,
    predictions_by_model_head: dict[str, dict[str, np.ndarray]],
    policy: dict,
) -> pd.Series:
    """Row-by-row call into select_raw_rank_score() - one call per row,
    exactly mirroring main.py's Pass 1c (one blend per symbol per bar).

    `predictions_by_model_head` is `{"sequence": {"rank_20d": arr,
    "rank_5d": arr}, "multitask": {...}}` - each array is row-index-aligned
    with `dataset` (predict_head()'s own return shape), one entry per head
    the caller actually loaded predictions for. A model absent from this
    dict is treated as unavailable that row (select_raw_rank_score()'s own
    "model still warming up" contract), never a KeyError.

    Returns a float Series aligned to dataset.index; NaN wherever
    select_raw_rank_score() returns (None, "no_rank_available") for that
    row (every configured head missing a value)."""
    num_rows = len(dataset)
    scores = np.full(num_rows, np.nan, dtype=np.float64)

    for row_index in range(num_rows):
        payload_by_model: dict[str, dict[str, float] | None] = {}
        for model_name, head_arrays in predictions_by_model_head.items():
            payload: dict[str, float] = {}
            for head_name, values in head_arrays.items():
                value = values[row_index]
                if value is not None and not (isinstance(value, float) and np.isnan(value)):
                    payload[head_name] = float(value)
            payload_by_model[model_name] = payload or None

        score, _source = select_raw_rank_score(
            payload_by_model.get("sequence"), payload_by_model.get("multitask"), policy
        )
        if score is not None:
            scores[row_index] = score

    return pd.Series(scores, index=dataset.index)


def calibrate_book_confidence_spread(
    dataset: pd.DataFrame,
    *,
    raw_score_column: str,
    ticker_column: str = "ticker",
    date_column: str = "date",
    top_n: int,
    bottom_n: int,
    percentile: float = 0.10,
) -> dict:
    """Per date (sorted): normalizes that date's raw scores exactly as
    main.py's Pass 1 does (cross_sectional_rank_scores()), selects the
    natural top_n/bottom_n split with NO gate and NO hysteresis
    (build_rank_based_book(..., min_rank_confidence_spread=0.0,
    previous_allocations=None) - hysteresis is deliberately not replayed
    here: this measures each day's independent natural dispersion, not one
    particular incumbency-dependent walk through history), then computes
    that selection's confidence spread via the SAME compute_confidence_spread()
    the live gate calls.

    Dates where selection comes back empty (fewer than 2 eligible names,
    or one side has nothing to select at all) are EXCLUDED from the
    distribution, not counted as a 0.0-spread day - a thin-universe date is
    missing data, not evidence of low conviction.

    Returns:
        {"calibrated_min_rank_confidence_spread": float,
         "percentile": float,
         "num_dates_used": int,
         "num_dates_skipped_thin_universe": int,
         "spread_distribution": {"min", "p10", "p25", "median", "p75", "max"}}

    An empty/all-thin dataset returns calibrated_min_rank_confidence_spread=0.0
    (the gate's own "always engage" no-op value) and an all-None
    distribution, never raises."""
    spreads: list[float] = []
    num_dates_skipped_thin_universe = 0

    for _date, group in dataset.groupby(date_column, sort=True):
        raw_scores = {
            str(ticker): float(score)
            for ticker, score in zip(group[ticker_column], group[raw_score_column])
            if score is not None and not (isinstance(score, float) and np.isnan(score))
        }
        normalized = cross_sectional_rank_scores(raw_scores)
        if not normalized:
            num_dates_skipped_thin_universe += 1
            continue

        candidates = {
            symbol: {"predicted_rank_20d": rank, "trading_eligible": True} for symbol, rank in normalized.items()
        }
        allocations = build_rank_based_book(
            candidates,
            top_n=top_n,
            bottom_n=bottom_n,
            min_rank_confidence_spread=0.0,
            spread_check_ranks=raw_scores,
        )
        if not allocations:
            num_dates_skipped_thin_universe += 1
            continue

        long_symbols = [symbol for symbol, allocation in allocations.items() if allocation.role == "long"]
        short_symbols = [symbol for symbol, allocation in allocations.items() if allocation.role == "short"]
        spread = compute_confidence_spread(long_symbols, short_symbols, raw_scores, normalized)
        if spread is not None:
            spreads.append(spread)
        else:
            num_dates_skipped_thin_universe += 1

    if not spreads:
        return {
            "calibrated_min_rank_confidence_spread": 0.0,
            "percentile": percentile,
            "num_dates_used": 0,
            "num_dates_skipped_thin_universe": num_dates_skipped_thin_universe,
            "spread_distribution": {"min": None, "p10": None, "p25": None, "median": None, "p75": None, "max": None},
        }

    spread_array = np.array(spreads, dtype=np.float64)
    distribution = {"min": float(np.min(spread_array)), "max": float(np.max(spread_array))}
    for name, quantile in _SPREAD_DISTRIBUTION_PERCENTILES.items():
        distribution[name] = float(np.quantile(spread_array, quantile))

    return {
        "calibrated_min_rank_confidence_spread": float(np.quantile(spread_array, percentile)),
        "percentile": percentile,
        "num_dates_used": len(spreads),
        "num_dates_skipped_thin_universe": num_dates_skipped_thin_universe,
        "spread_distribution": distribution,
    }
