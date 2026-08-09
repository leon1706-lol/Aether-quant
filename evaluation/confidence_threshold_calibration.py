"""Calibrates `phase6.risk.min_confidence_to_trade` (and, when book
selection data is available, `phase6.risk.min_confidence_to_trade_book_selected`)
from real data (V5.2.6, development/Problems.md) - the same "derive the
number, don't guess it" discipline `aq evaluate --calibrate-edge` and
`aq evaluate --calibrate-book-spread` already established for
`phase_v2.costs.edge_bps_per_rank_unit` and
`phase_v2.portfolio_book.min_rank_confidence_spread`.

Deliberately reuses, never re-derives: `portfolio.rank_signal.cross_sectional_rank_scores()`
(the exact normalization main.py applies before book selection) and
`portfolio.book_construction.build_rank_based_book()` (the exact
top_n/bottom_n selection main.py's live book uses, for the book-selected
split) and `analyzer.market_analyzer.compute_trade_metric()` (the exact
confidence-metric formula the live gate compares against
min_confidence_to_trade). A calibrated threshold computed here can never
silently disagree with what the live gate would have done on the same
historical day, because it is the same code, not a parallel
approximation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analyzer.market_analyzer import compute_trade_metric
from portfolio.book_construction import build_rank_based_book
from portfolio.rank_signal import cross_sectional_rank_scores

_CONFIDENCE_DISTRIBUTION_PERCENTILES = {"p10": 0.10, "p25": 0.25, "median": 0.50, "p75": 0.75}


def _empty_distribution() -> dict:
    return {"min": None, "p10": None, "p25": None, "median": None, "p75": None, "max": None}


def _percentile_of_paying_confidence(confidences: list[float], percentile: float) -> tuple[float, dict]:
    if not confidences:
        return 0.0, _empty_distribution()
    array = np.array(confidences, dtype=np.float64)
    distribution = {"min": float(np.min(array)), "max": float(np.max(array))}
    for name, quantile in _CONFIDENCE_DISTRIBUTION_PERCENTILES.items():
        distribution[name] = float(np.quantile(array, quantile))
    return float(np.quantile(array, percentile)), distribution


def calibrate_confidence_threshold(
    dataset: pd.DataFrame,
    *,
    raw_score_column: str,
    forward_return_column: str,
    ticker_column: str = "ticker",
    date_column: str = "date",
    top_n: int,
    bottom_n: int,
    round_trip_cost_fraction: float = 0.001,
    percentile: float = 0.10,
) -> dict:
    """Per date (sorted): normalizes that date's raw scores exactly as
    main.py's Pass 1 does (`cross_sectional_rank_scores()`), computes each
    symbol's book-member confidence via the SAME formula main.py uses for
    a book-selected symbol (`min(1.0, abs(normalized_rank - 0.5) * 2.0)` -
    see main.py's Pass 2, `confidence = min(1.0, abs(book_allocation.predicted_rank_20d - 0.5) * 2.0)`),
    and separately determines whether that date's natural top_n/bottom_n
    selection (`build_rank_based_book()`, no gate, no hysteresis - same
    "measure each day's independent natural dispersion" reasoning
    `calibrate_book_confidence_spread()` already uses) would have picked
    each symbol, for the book-selected/non-book-selected split.

    A row "would have been worth taking" when its DIRECTIONAL realized
    edge clears round_trip_cost_fraction: `direction = 1 if
    normalized_rank >= 0.5 else -1`, `realized_edge = direction *
    forward_return - round_trip_cost_fraction`. The calibrated threshold
    is the given percentile of confidence AMONG ONLY the rows that
    actually paid - the same "percentile of a real, achieved distribution,
    not a guess" discipline `calibrate_book_confidence_spread()` already
    established, applied to confidence instead of spread.

    Returns:
        {"calibrated_min_confidence_to_trade": float,
         "calibrated_min_confidence_to_trade_book_selected": float,
         "percentile": float,
         "num_rows_used": int,
         "num_rows_used_book_selected": int,
         "num_dates_skipped_thin_universe": int,
         "confidence_distribution": {...},
         "confidence_distribution_book_selected": {...}}

    An empty/all-thin dataset returns both calibrated values as 0.0 (the
    gate's own "always trade" no-op value) and all-None distributions,
    never raises."""
    paying_confidences: list[float] = []
    paying_confidences_book_selected: list[float] = []
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
        book_allocations = build_rank_based_book(
            candidates,
            top_n=top_n,
            bottom_n=bottom_n,
            min_rank_confidence_spread=0.0,
            spread_check_ranks=raw_scores,
        )
        book_selected_symbols = set(book_allocations.keys())

        forward_return_by_ticker = {
            str(ticker): float(value)
            for ticker, value in zip(group[ticker_column], group[forward_return_column])
            if value is not None and not (isinstance(value, float) and np.isnan(value))
        }

        for symbol, normalized_rank in normalized.items():
            forward_return = forward_return_by_ticker.get(symbol)
            if forward_return is None:
                continue
            confidence = compute_trade_metric(
                confidence=min(1.0, abs(normalized_rank - 0.5) * 2.0),
                regime_confidence=0.0,
                topology={},
                liquidity={},
                use_composite_signal_score=False,
            )
            direction = 1.0 if normalized_rank >= 0.5 else -1.0
            realized_edge = direction * forward_return - round_trip_cost_fraction
            if realized_edge > 0.0:
                paying_confidences.append(confidence)
                if symbol in book_selected_symbols:
                    paying_confidences_book_selected.append(confidence)

    calibrated_general, distribution_general = _percentile_of_paying_confidence(paying_confidences, percentile)
    calibrated_book_selected, distribution_book_selected = _percentile_of_paying_confidence(
        paying_confidences_book_selected, percentile
    )

    return {
        "calibrated_min_confidence_to_trade": calibrated_general,
        "calibrated_min_confidence_to_trade_book_selected": calibrated_book_selected,
        "percentile": percentile,
        "num_rows_used": len(paying_confidences),
        "num_rows_used_book_selected": len(paying_confidences_book_selected),
        "num_dates_skipped_thin_universe": num_dates_skipped_thin_universe,
        "confidence_distribution": distribution_general,
        "confidence_distribution_book_selected": distribution_book_selected,
    }
