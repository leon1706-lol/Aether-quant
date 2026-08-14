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


def _build_reconciliation_result(
    logged_record: dict,
    offline_allocations: dict,
    raw_scores_by_symbol: dict[str, float],
) -> dict:
    """V5.2.3 (development/Problems.md #91) - the diff/shaping core shared
    by `reconcile_book_history_date()` (independent per-date, no
    hysteresis) and `replay_book_history_reconciliation()` (walk-forward,
    hysteresis-replayed): given one logged record and an ALREADY-COMPUTED
    offline `build_rank_based_book()` result for that same date, produces
    the reconciliation dict both callers return. Extracted so the two
    reconciliation modes can never silently disagree on what counts as a
    match/mismatch - see reconcile_book_history_date()'s own docstring for
    the full field-by-field contract this returns (unchanged by this
    refactor)."""
    logged_allocations = logged_record.get("allocations", {})
    logged_long = {symbol for symbol, entry in logged_allocations.items() if entry.get("role") == "long"}
    logged_short = {symbol for symbol, entry in logged_allocations.items() if entry.get("role") == "short"}

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
    must carry that caveat, never over-read a mismatch as necessarily a
    bug. `replay_book_history_reconciliation()` below is the hysteresis-
    aware alternative (V5.2.3) when a caller has the FULL date-sorted log,
    not just one record.

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
    when both sides are empty (nothing to compare, not a 0% overlap).

    V5.3.1 (development/Problems.md #91/#97): `trading_eligible` used to
    be hardcoded `True` for every symbol here, regardless of whether the
    real live run actually considered it eligible that date - now read
    from `logged_record["universe"][symbol]["trading_eligible"]` when
    that data is present (`phase_v2.diagnostics.book_history.
    include_full_universe` was on for the run that produced this log),
    the SAME real per-date eligibility main.py's own book construction
    used (main.py:2768). Falls back to `True` (today's exact prior
    behavior, byte-identical) for any symbol missing from `"universe"` or
    for a log with no `"universe"` key at all - never a KeyError."""
    universe = logged_record.get("universe") or {}
    normalized = cross_sectional_rank_scores(raw_scores_by_symbol)
    candidates = {
        symbol: {
            "predicted_rank_20d": rank,
            "trading_eligible": universe.get(symbol, {}).get("trading_eligible", True),
        }
        for symbol, rank in normalized.items()
    }
    offline_allocations = build_rank_based_book(
        candidates,
        top_n=top_n,
        bottom_n=bottom_n,
        min_rank_confidence_spread=0.0,
        spread_check_ranks=raw_scores_by_symbol,
    )
    return _build_reconciliation_result(logged_record, offline_allocations, raw_scores_by_symbol)


def replay_book_history_reconciliation(
    logged_records: list[dict],
    raw_scores_by_date: dict[str, dict[str, float]],
    *,
    top_n: int,
    bottom_n: int,
    hysteresis_rank_margin: float = 0.0,
) -> list[dict]:
    """V5.2.3 (development/Problems.md #91) - the hysteresis-aware
    alternative to calling `reconcile_book_history_date()` independently
    per date. `reconcile_book_history_date()` always passes
    `previous_allocations=None`, so it cannot tell "the live book
    genuinely diverged" apart from "the live book correctly held an
    incumbent a from-scratch reselection wouldn't naturally pick" - this
    function replays offline's OWN walk-forward selection across
    `logged_records` (must already be date-sorted - not re-sorted here,
    same precondition `evaluation/model_predictions.py::build_sequence_windows()`
    already places on its own caller), carrying a `held_allocations` dict
    forward exactly the way `evaluation/rank_book_simulator.py::_simulate_rank_book_core()`
    and `main.py`'s own `_last_book_allocations` both already do: computed
    with the STILL-OLD `held_allocations` as `previous_allocations`, then
    overwritten from THAT SAME call's own output (never from the logged
    record - offline's own history, not live's) before the next date.

    `hysteresis_rank_margin=0.0` reproduces `build_rank_based_book()`'s
    own no-op default, so passing it unset degrades to (a slower way of
    computing) `reconcile_book_history_date()`'s independent-per-date
    result for every date except that `held_allocations` is still seeded
    from offline's own prior date rather than nothing - only truly
    identical when `hysteresis_rank_margin` is also 0.0 everywhere.

    Cold-start caveat: `held_allocations` starts EMPTY at the first
    record in `logged_records`, regardless of how long the live book's
    true incumbency history was before that date - early results in the
    returned list are more likely to show a "divergence" that is really
    just this function's own cold start, not live's. A caller printing
    this should say so, not just print the raw numbers.

    Returns a list of `_build_reconciliation_result()`-shaped dicts, one
    per record in `logged_records`, in the same order. A `logged_record`
    with no matching entry in `raw_scores_by_date` (e.g. that date fell
    outside a caller's re-inference window) is skipped entirely - not a
    KeyError, and `held_allocations` simply carries through unchanged to
    the next date it CAN compute, the same "missing day doesn't reset
    state" behavior a live gap in trading data would also produce."""
    held_allocations: dict = {}
    results: list[dict] = []
    for logged_record in logged_records:
        date = logged_record.get("date")
        raw_scores_by_symbol = raw_scores_by_date.get(date)
        if raw_scores_by_symbol is None:
            continue

        # V5.3.1 (development/Problems.md #91/#97) - reads real per-date
        # trading_eligible from the logged "universe" payload when
        # available, same as reconcile_book_history_date() above (see its
        # docstring); falls back to True (unchanged prior behavior) when
        # absent.
        universe = logged_record.get("universe") or {}
        normalized = cross_sectional_rank_scores(raw_scores_by_symbol)
        candidates = {
            symbol: {
                "predicted_rank_20d": rank,
                "trading_eligible": universe.get(symbol, {}).get("trading_eligible", True),
            }
            for symbol, rank in normalized.items()
        }
        offline_allocations = build_rank_based_book(
            candidates,
            top_n=top_n,
            bottom_n=bottom_n,
            min_rank_confidence_spread=0.0,
            spread_check_ranks=raw_scores_by_symbol,
            previous_allocations=held_allocations or None,
            hysteresis_rank_margin=hysteresis_rank_margin,
        )
        results.append(_build_reconciliation_result(logged_record, offline_allocations, raw_scores_by_symbol))
        held_allocations = offline_allocations

    return results


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


def summarize_universe_snapshot_by_security_type(logged_records: list[dict]) -> dict:
    """V5.2.3 (development/Problems.md #91) - aggregates the OPTIONAL
    `"universe"` key `build_book_history_record()` adds when
    `phase_v2.diagnostics.book_history.include_full_universe` was on for
    the run that produced `logged_records` (V5.2.2 logs, and any V5.2.3
    log written with the toggle still off, simply have no `"universe"`
    key on any record - this function reads straight off the log's own
    data, no re-inference or model loading needed, so it is always cheap
    to attempt).

    Exists to answer, directly from data, the question code-reading alone
    could not settle: does a `security_type` that's absent from every
    live book (e.g. crypto/FX, Problems.md #91) sit there because it
    never gets a usable feature/score (`feature_ready` false), or because
    it gets a real score that's simply never extreme enough to be
    selected (`feature_ready` true, `mean_raw_rank_score` unremarkable)?

    Per `security_type`: `num_symbol_dates` (raw count of (symbol, date)
    observations seen for it - NOT unique symbols), `mean_raw_rank_score`
    (over only the observations where `raw_rank_score` is not None -
    never averages a missing score in as 0), `feature_ready_rate`,
    `trading_eligible_rate`.

    Returns `{"num_dates_with_universe_data": int, "by_security_type":
    {security_type: {...}}}`. `num_dates_with_universe_data` is 0 (and
    `by_security_type` is `{}`) when no record in `logged_records` carries
    a `"universe"` key at all - callers must check this before reading
    `by_security_type`, since a 0 there means "toggle was off for this
    log", not "every security type had zero observations". Never raises
    on an empty or all-missing-universe input."""
    dates_with_universe_data = 0
    observations_by_security_type: dict[str, list[dict]] = {}

    for logged_record in logged_records:
        universe = logged_record.get("universe")
        if not universe:
            continue
        dates_with_universe_data += 1
        for signal in universe.values():
            security_type = signal.get("security_type") or "unknown"
            observations_by_security_type.setdefault(security_type, []).append(signal)

    by_security_type: dict[str, dict] = {}
    for security_type, observations in observations_by_security_type.items():
        raw_scores = [obs["raw_rank_score"] for obs in observations if obs.get("raw_rank_score") is not None]
        num_observations = len(observations)
        by_security_type[security_type] = {
            "num_symbol_dates": num_observations,
            "mean_raw_rank_score": float(np.mean(raw_scores)) if raw_scores else None,
            "feature_ready_rate": (
                sum(1 for obs in observations if obs.get("feature_ready")) / num_observations
                if num_observations > 0
                else None
            ),
            "trading_eligible_rate": (
                sum(1 for obs in observations if obs.get("trading_eligible")) / num_observations
                if num_observations > 0
                else None
            ),
        }

    return {
        "num_dates_with_universe_data": dates_with_universe_data,
        "by_security_type": by_security_type,
    }


def summarize_universe_presence_by_symbol(logged_records: list[dict]) -> dict:
    """V5.3.1 (development/Problems.md #91/#97) - `visualization/
    book_history.jsonl` is a cumulative, NEVER-rotated log: every real
    backtest run's records get appended to the same file, one after
    another, forever. Averaging a per-symbol statistic across the whole
    file (as an earlier round of this investigation did, finding "FX/crypto
    absent from the universe on 32% of dates") silently mixes many
    different runs together - a genuine, now-fixed gap in one old run can
    look like a smaller, still-live problem once diluted into the average
    of several newer, clean runs. This function segments `logged_records`
    into contiguous runs FIRST (a run boundary is detected wherever the
    date sequence goes backwards - `record["date"] < previous_record["date"]`,
    since a single real backtest always logs forward in time), then
    computes each symbol's universe-absence rate PER RUN, so a stale run's
    numbers can never dilute a fresh run's, and a genuine regression in
    the MOST RECENT run (`result["runs"][-1]`) is always visible on its
    own, not averaged away.

    Absence here means "not a key in that date's `universe` payload at
    all" (main.py's `signals` dict, main.py:2761-2772 - the SAME data that
    also feeds real book candidacy, main.py:1735-1736's `continue` gate -
    see development/Problems.md #97 for why this is a real book-
    construction signal, not merely a diagnostic one). Only symbols that
    appear in the universe payload on AT LEAST one date within a run are
    scored for that run (an unrelated ticker that's never in ANY
    universe snapshot isn't "100% absent", it's simply out of scope).

    Same "log carries no data, degrade to zeros" contract as
    summarize_universe_snapshot_by_security_type() - a `logged_records`
    with no `"universe"` key anywhere returns `{"num_runs_detected": 0,
    "runs": []}`, never raises.

    Returns `{"num_runs_detected": int, "runs": [{"start_date", "end_date",
    "num_records", "absence_rate_by_symbol": {symbol: float}}, ...]}`,
    runs in the same chronological order as `logged_records` itself."""
    runs: list[list[dict]] = []
    current_run: list[dict] = []
    previous_date: str | None = None
    for record in logged_records:
        date = record.get("date")
        if previous_date is not None and date is not None and date < previous_date:
            if current_run:
                runs.append(current_run)
            current_run = []
        current_run.append(record)
        previous_date = date if date is not None else previous_date

    if current_run:
        runs.append(current_run)

    run_summaries: list[dict] = []
    for run_records in runs:
        universe_records = [record for record in run_records if record.get("universe")]
        num_records = len(universe_records)
        if num_records == 0:
            continue

        all_symbols: set[str] = set()
        for record in universe_records:
            all_symbols.update(record["universe"].keys())

        absence_rate_by_symbol = {
            symbol: 1.0 - (sum(1 for record in universe_records if symbol in record["universe"]) / num_records)
            for symbol in all_symbols
        }

        run_summaries.append(
            {
                "start_date": universe_records[0].get("date"),
                "end_date": universe_records[-1].get("date"),
                "num_records": num_records,
                "absence_rate_by_symbol": absence_rate_by_symbol,
            }
        )

    return {"num_runs_detected": len(run_summaries), "runs": run_summaries}


def summarize_book_member_diversion(logged_records: list[dict]) -> dict:
    """V5.2.6 (development/Problems.md) - aggregates the OPTIONAL
    `"book_member_decisions"` key `build_book_history_record()` adds when
    `phase_v2.diagnostics.book_history.include_decisions` was on for the
    run that produced `logged_records` - mirrors
    `summarize_universe_snapshot_by_security_type()`'s own shape and
    "log carries no data, degrade to zeros" contract exactly.

    Exists to replace hypothesis with measurement: `book_allocations`
    alone can never show whether a book-selected symbol actually became
    a real trade, or was silently diverted to `simulate`/`reduce_risk`/
    `retrain_candidate` by a risk/execution gate downstream of selection
    (development/Problems.md - the crypto/FX zero-order-execution
    finding, and the live-risk-gate-vs-offline-evaluator gap). Per-run,
    NOT per-date - a single aggregate is more useful here than a per-date
    breakdown, since the question is "how much, in total, across this
    whole run" rather than "on which specific date".

    Returns `{"num_records_with_decisions": int, "total_book_member_dates":
    int, "action_counts": {action: count}, "reason_counts": {reason: count}}`.
    `num_records_with_decisions` is 0 (and both count dicts are `{}`) when
    no record in `logged_records` carries a `"book_member_decisions"` key
    at all - callers must check this before reading the counts, same as
    `num_dates_with_universe_data`'s own convention above. Never raises on
    an empty or all-missing-decisions input."""
    num_records_with_decisions = 0
    total_book_member_dates = 0
    action_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}

    for logged_record in logged_records:
        decisions = logged_record.get("book_member_decisions")
        if not decisions:
            continue
        num_records_with_decisions += 1
        for decision in decisions.values():
            total_book_member_dates += 1
            action = decision.get("action") or "unknown"
            action_counts[action] = action_counts.get(action, 0) + 1
            for reason in decision.get("reasons", []) or []:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "num_records_with_decisions": num_records_with_decisions,
        "total_book_member_dates": total_book_member_dates,
        "action_counts": action_counts,
        "reason_counts": reason_counts,
    }
