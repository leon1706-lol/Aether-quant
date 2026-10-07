"""As-live inputs for `rank_book_simulator` (V5.5.0, Problems.md #128).

The idealized offline rank book scored well while real Lean backtests lost
money. A read-only trace of both paths found the simulator differed from
`main.py` in ways that all flatter the offline number: a different rank head,
a 0.05 (not 0.15) sector cap, hysteresis in raw-score (not percentile) units,
no confidence-spread / rolling-IC gates, a vetoed book that LIQUIDATES instead
of holding, equal (not confidence-weighted) weights, forex/crypto decided on
the same day's row instead of the previous bar, and a flat cost model.

This module turns a config + dataset into the keyword arguments that make
`simulate_rank_book()` mirror the live path, WITHOUT changing the idealized
default. Everything here is pure (pandas/numpy/stdlib, no torch) - same
contract as the rest of the `evaluation` package.
"""

from __future__ import annotations

import bisect

import pandas as pd

from evaluation.rolling_ic_gate_calibration import build_event_buffer
from portfolio.rolling_ic_gate import compute_rolling_ic_state, evaluate_rolling_ic_gate

# Asset classes whose bar lands AFTER the equity-session tick (forex 19:00/20:00,
# crypto ~midnight UTC): live decides them on the previous day's bar
# (main.py on_data() "borrowed bar" path), so offline must too.
LATE_BAR_ASSET_CLASSES = frozenset({"forex", "crypto"})


def lag_predictions_for_tickers(
    frame: pd.DataFrame,
    *,
    prediction_column: str,
    tickers: set[str] | frozenset[str],
    ticker_column: str = "ticker",
    date_column: str = "date",
) -> pd.DataFrame:
    """Return a copy of `frame` where, for each ticker in `tickers`, the
    prediction on date D is the prediction made on that ticker's PREVIOUS
    row (the first row becomes NaN and is dropped by the simulator). The
    forward return column is deliberately left alone: the return is still
    earned from D, but it is ranked on information that is one bar stale."""
    lagged = frame.sort_values([ticker_column, date_column]).copy()
    mask = lagged[ticker_column].astype(str).isin(set(map(str, tickers)))
    shifted = lagged.groupby(ticker_column)[prediction_column].shift(1)
    lagged.loc[mask, prediction_column] = shifted[mask]
    return lagged.sort_index()


def make_rolling_ic_gate_fn(
    frame: pd.DataFrame,
    *,
    raw_score_column: str,
    gate_config: dict,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "close",
):
    """A date -> gate-result callable for `rolling_ic_gate_fn`. Builds the
    event buffer ONCE and, per call, slices it to events dated <= that date
    (no lookahead - same technique as evaluation/rolling_ic_gate_replay.py)
    before evaluating main.py's own `evaluate_rolling_ic_gate()`. Results are
    cached because a retry-after-veto simulation asks about many dates."""
    events = build_event_buffer(
        frame,
        raw_score_column=raw_score_column,
        ticker_column=ticker_column,
        date_column=date_column,
        close_column=close_column,
    )
    event_dates = [str(event["created_at"])[:10] for event in events]
    config = dict(gate_config)
    config["enabled"] = True
    cache: dict[str, dict] = {}

    def gate_fn(date: str) -> dict:
        key = str(date)[:10]
        if key not in cache:
            cutoff = bisect.bisect_right(event_dates, key)
            state = compute_rolling_ic_state(
                events[:cutoff],
                horizon_days=int(config.get("horizon_days", 20)),
                rolling_window_days=int(config.get("rolling_window_days", 40)),
                min_names_per_date=int(config.get("min_names_per_date", 10)),
            )
            cache[key] = evaluate_rolling_ic_gate(state, config)
        return cache[key]

    return gate_fn


def build_candidate_metadata(
    asset_class_by_ticker: dict[str, str],
    trading_eligible_by_ticker: dict[str, bool],
) -> dict[str, dict]:
    """{ticker: {"asset_class", "trading_eligible"}} - the per-symbol fields
    main.py hands build_rank_based_book(), instead of the simulator's
    default of forcing every row eligible with no asset class."""
    tickers = set(asset_class_by_ticker) | set(trading_eligible_by_ticker)
    return {
        ticker: {
            "asset_class": asset_class_by_ticker.get(ticker),
            "trading_eligible": bool(trading_eligible_by_ticker.get(ticker, True)),
        }
        for ticker in tickers
    }


def build_as_live_kwargs(
    base_kwargs: dict,
    *,
    book_config: dict,
    exits_config: dict,
    max_position_weight: float,
    candidate_metadata: dict[str, dict],
    rolling_ic_gate_fn=None,
) -> dict:
    """base_kwargs (idealized, from `phase1...net_performance`) + the live
    overrides, read from `phase_v2.portfolio_book` / `phase_v2.exits` - the
    ONE config source live uses (the idealized run reads net_performance, a
    second source that had drifted: sector cap 0.05 vs 0.15)."""
    neutrality = book_config.get("neutrality", {})
    kwargs = dict(base_kwargs)
    kwargs.update(
        top_n=int(book_config.get("top_n", base_kwargs.get("top_n", 6))),
        bottom_n=int(book_config.get("bottom_n", base_kwargs.get("bottom_n", 6))),
        rebalance_every_bars=int(book_config.get("rebalance_every_bars", base_kwargs.get("rebalance_every_bars", 10))),
        hysteresis_rank_margin=float(book_config.get("hysteresis_rank_margin", 0.0)),
        dollar_neutral=bool(neutrality.get("dollar_neutral", base_kwargs.get("dollar_neutral", True))),
        sector_neutral=bool(neutrality.get("sector_neutral", base_kwargs.get("sector_neutral", True))),
        gross_exposure=float(neutrality.get("gross_exposure_cap", base_kwargs.get("gross_exposure", 1.0))),
        max_weight_per_name=float(neutrality.get("max_weight_per_name", base_kwargs.get("max_weight_per_name", 0.12))),
        sector_max_net_weight=float(neutrality.get("sector_max_net_weight", 0.15)),
        entry_lag_bars=1,
        candidate_metadata_by_ticker=candidate_metadata,
        normalize_to_percentile=True,
        min_rank_confidence_spread=float(book_config.get("min_rank_confidence_spread", 0.0)),
        rolling_ic_gate_fn=rolling_ic_gate_fn,
        live_weighting=True,
        max_position_weight=float(max_position_weight),
        hold_positions_on_veto=True,
        retry_rebalance_after_veto=True,
        max_holding_dates=(
            int(exits_config["max_holding_bars"])
            if exits_config.get("enabled", False) and exits_config.get("max_holding_bars") is not None
            else None
        ),
    )
    return kwargs
