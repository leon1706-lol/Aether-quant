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


def reconcile_book_history_date(
    logged_record: dict,
    raw_scores_by_symbol: dict[str, float],
    *,
    top_n: int,
    bottom_n: int,
) -> dict:
    """V5.2.2 (development/Problems.md) - `aq evaluate --reconcile-book-history`'s
    per-date core: compares one `build_book_history_record()` log entry
    (portfolio/book_construction.py - what main.py's LIVE book actually
    selected that date, during a real Lean backtest) against a fresh
    offline re-derivation of what the SAME raw scores would naturally
    select today, with no gate and no hysteresis
    (build_rank_based_book(..., min_rank_confidence_spread=0.0,
    previous_allocations=None) - the exact same "independent natural
    selection" convention calibrate_book_confidence_spread() above
    already established).

    `previous_allocations=None` is deliberate, not an oversight: this
    cannot replay the live book's actual incumbency history from a single
    date's log entry, so a flagged mismatch here can mean either a real
    divergence OR "hysteresis correctly kept an incumbent that day's
    natural ranking alone wouldn't pick" - callers printing this result
    must carry that caveat, never over-read a mismatch as necessarily a bug.

    Weight comparison is best-effort and deliberately naive: offline has
    no access to the live per-symbol `confidence` value or the neutrality
    pass's inputs (both needed to reproduce main.py's real sizing formula),
    so `per_symbol_deltas[symbol]["weight_delta"]` is computed against a
    naive equal-weight baseline (`book_role_multiplier / count-on-that-role`),
    not the live formula - it measures how far the logged (post-neutrality,
    post-confidence-sizing) weight moved from a symmetric equal-weight
    book, not a reconstruction error. `None` whenever the logged record's
    own `target_weight` is `None` (neutrality was off for that run).

    Returns:
        {"date", "logged_symbols": {"long", "short"}, "offline_symbols":
         {"long", "short"}, "symbols_matched", "symbols_only_logged",
         "symbols_only_offline", "role_mismatches", "overlap_fraction",
         "per_symbol_deltas": {symbol: {"raw_score_delta", "weight_delta"}}}

    `overlap_fraction` is `symbols_matched / (logged | offline)`, `None`
    when both sides are empty (nothing to compare, not a 0% overlap)."""
    logged_allocations = logged_record.get("allocations", {})
    logged_long = {symbol for symbol, entry in logged_allocations.items() if entry.get("role") == "long"}
    logged_short = {symbol for symbol, entry in logged_allocations.items() if entry.get("role") == "short"}

    normalized = cross_sectional_rank_scores(raw_scores_by_symbol)
    candidates = {
        symbol: {"predicted_rank_20d": rank, "trading_eligible": True} for symbol, rank in normalized.items()
    }
    offline_allocations = build_rank_based_book(
        candidates,
        top_n=top_n,
        bottom_n=bottom_n,
        min_rank_confidence_spread=0.0,
        spread_check_ranks=raw_scores_by_symbol,
    )
    offline_long = {symbol for symbol, allocation in offline_allocations.items() if allocation.role == "long"}
    offline_short = {symbol for symbol, allocation in offline_allocations.items() if allocation.role == "short"}

    logged_all = logged_long | logged_short
    offline_all = offline_long | offline_short

    symbols_matched = sorted(logged_all & offline_all)
    symbols_only_logged = sorted(logged_all - offline_all)
    symbols_only_offline = sorted(offline_all - logged_all)
    role_mismatches = sorted(
        symbol for symbol in symbols_matched if (symbol in logged_long) != (symbol in offline_long)
    )

    union_size = len(logged_all | offline_all)
    overlap_fraction = (len(symbols_matched) / union_size) if union_size > 0 else None

    num_offline_long = len(offline_long)
    num_offline_short = len(offline_short)
    per_symbol_deltas: dict[str, dict] = {}
    for symbol in symbols_matched:
        logged_raw_score = logged_allocations[symbol].get("raw_rank_score")
        offline_raw_score = raw_scores_by_symbol.get(symbol)
        raw_score_delta = (
            offline_raw_score - logged_raw_score
            if logged_raw_score is not None and offline_raw_score is not None
            else None
        )

        logged_target_weight = logged_allocations[symbol].get("target_weight")
        if logged_target_weight is not None and symbol in offline_long and num_offline_long > 0:
            naive_offline_weight = 1.0 / num_offline_long
        elif logged_target_weight is not None and symbol in offline_short and num_offline_short > 0:
            naive_offline_weight = -1.0 / num_offline_short
        else:
            naive_offline_weight = None
        weight_delta = (
            logged_target_weight - naive_offline_weight
            if logged_target_weight is not None and naive_offline_weight is not None
            else None
        )

        per_symbol_deltas[symbol] = {"raw_score_delta": raw_score_delta, "weight_delta": weight_delta}

    return {
        "date": logged_record.get("date"),
        "logged_symbols": {"long": sorted(logged_long), "short": sorted(logged_short)},
        "offline_symbols": {"long": sorted(offline_long), "short": sorted(offline_short)},
        "symbols_matched": symbols_matched,
        "symbols_only_logged": symbols_only_logged,
        "symbols_only_offline": symbols_only_offline,
        "role_mismatches": role_mismatches,
        "overlap_fraction": overlap_fraction,
        "per_symbol_deltas": per_symbol_deltas,
    }


def summarize_book_history_reconciliation(per_date_results: list[dict]) -> dict:
    """Aggregates a list of reconcile_book_history_date() results (one per
    logged date) into a single report. An empty list returns a defined
    all-zero/None summary, never raises - the CLI orchestrator always calls
    this even when the log file turned out to contain zero usable dates.

    `mean_weight_delta_abs`/`num_dates_with_weight_logged` are computed
    only over dates that had at least one symbol with a non-None logged
    `target_weight` (neutrality was on for that run) - callers must report
    "weight deltas computed for N/M dates" rather than silently averaging
    the missing dates away as zero, per reconcile_book_history_date()'s own
    weight-comparison caveat."""
    num_dates = len(per_date_results)
    if num_dates == 0:
        return {
            "num_dates": 0,
            "num_dates_exact_match": 0,
            "mean_overlap_fraction": None,
            "mean_raw_score_delta_abs": None,
            "mean_weight_delta_abs": None,
            "num_dates_with_weight_logged": 0,
            "num_symbols_only_logged_total": 0,
            "num_symbols_only_offline_total": 0,
        }

    num_dates_exact_match = sum(
        1
        for result in per_date_results
        if not result["symbols_only_logged"] and not result["symbols_only_offline"] and not result["role_mismatches"]
    )
    overlap_fractions = [result["overlap_fraction"] for result in per_date_results if result["overlap_fraction"] is not None]
    raw_score_deltas = [
        abs(delta["raw_score_delta"])
        for result in per_date_results
        for delta in result["per_symbol_deltas"].values()
        if delta["raw_score_delta"] is not None
    ]
    weight_deltas = [
        abs(delta["weight_delta"])
        for result in per_date_results
        for delta in result["per_symbol_deltas"].values()
        if delta["weight_delta"] is not None
    ]
    num_dates_with_weight_logged = sum(
        1
        for result in per_date_results
        if any(delta["weight_delta"] is not None for delta in result["per_symbol_deltas"].values())
    )

    return {
        "num_dates": num_dates,
        "num_dates_exact_match": num_dates_exact_match,
        "mean_overlap_fraction": float(np.mean(overlap_fractions)) if overlap_fractions else None,
        "mean_raw_score_delta_abs": float(np.mean(raw_score_deltas)) if raw_score_deltas else None,
        "mean_weight_delta_abs": float(np.mean(weight_deltas)) if weight_deltas else None,
        "num_dates_with_weight_logged": num_dates_with_weight_logged,
        "num_symbols_only_logged_total": sum(len(result["symbols_only_logged"]) for result in per_date_results),
        "num_symbols_only_offline_total": sum(len(result["symbols_only_offline"]) for result in per_date_results),
    }
