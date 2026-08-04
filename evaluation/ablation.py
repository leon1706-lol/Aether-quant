"""V5.1 Phase 5 (item 9): declarative ablation harness over the offline
rank-book simulator - "how much does each piece of the adaptive machinery
actually contribute", answered honestly. Only pieces genuinely represented
in the offline dataset/simulator get a real number; everything runtime-only
(the MoE gating blend, learned-topology sizing, rank-magnitude position
sizing, the portfolio-book selection process itself, the net-edge cost
gate) gets an explicit `{"status": "not_offline_measurable", "reason": ...}`
sentinel, never a fabricated comparison. A fabricated ablation number is
worse than an absent one - this repo's own convention of recording honest
negatives (development/Changelog.md) supports being blunt here.

Deliberately its own module, not folded into rank_book_simulator.py: this
module composes multiple simulate_rank_book() runs into one declarative
table; rank_book_simulator.py stays the single-run primitive both this
module and `aq evaluate --rank-book` build on.

Torch-free (see evaluation/__init__.py's docstring) - only imports
rank_book_simulator.py, itself pure numpy/pandas plus the pure
portfolio/book_construction.py and portfolio/book_neutrality.py.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .rank_book_simulator import simulate_rank_book

# Variants whose live-path mechanism has NO representation anywhere in the
# offline dataset or in simulate_rank_book() - "ablating" them here would
# either compare the baseline against itself (a mechanism that was never
# modeled offline in the first place) or would require runtime state this
# module structurally cannot see. Each reason is specific enough to explain
# to a reader why the number is genuinely absent, not just "not implemented
# yet".
NOT_OFFLINE_MEASURABLE_VARIANTS: dict[str, str] = {
    "no_gating": (
        "The MoE gating blend (moe/gating.py) drives probability_up/magnitude/"
        "volatility - none of those enter the rank book at all. Absent from "
        "the offline dataset; there is nothing to ablate."
    ),
    "no_topology_sizing": (
        "Topology-derived sizing (risk/position_sizing.py::topology_sizing_multiplier()) "
        "depends on per-bar learned-topology runtime state (confidence/disagreement) "
        "that is computed live in main.py and never written to the offline dataset."
    ),
    "no_rank_sizing": (
        "Rank-magnitude position sizing (risk/position_sizing.py::rank_sizing_multiplier()) "
        "is a LIVE-ONLY behavior driven by main.py's runtime confidence signal. "
        "simulate_rank_book() has never modeled it - every leg is already flat, "
        "equal-weighted offline (see _simulate_rank_book_core()'s own per_name = "
        "gross_exposure/2/len(leg) formula) - 'ablating' it here would compare the "
        "baseline against itself, not a real finding."
    ),
    "no_portfolio_book": (
        "The 'portfolio book' IS build_rank_based_book()'s cross-sectional top/"
        "bottom-N selection - the thing simulate_rank_book() exists to simulate. "
        "There is no simpler, non-book trading logic implemented anywhere offline "
        "to fall back to (main.py's non-book code path is a different, per-symbol-"
        "independent decision path with no offline dataset representation)."
    ),
    "no_net_edge_gate": (
        "The net-edge cost gate (execution/cost_model.py::build_net_edge_decision(), "
        "wired into analyzer/market_analyzer.py's Priority 6.5) is evaluated per-bar "
        "against live liquidity/order-value context main.py computes at runtime. "
        "simulate_rank_book() has no representation of liquidity or this gate at all."
    ),
    # "no_retraining" is handled separately by compare_static_vs_retrained()
    # below - it IS offline-measurable, but only from Phase 4's walk-forward
    # artifacts, not from a single simulate_rank_book() call the way every
    # other variant in ABLATION_VARIANTS is. See run_ablation()'s docstring.
}

# Variants that ARE offline-measurable: kwarg overrides applied on top of
# the caller's base_kwargs before calling simulate_rank_book(). Each one
# documents exactly which live mechanism it approximates, and the one
# respect in which it is only an approximation - never silently pretend
# the offline number is a perfect stand-in for the live behavior.
ABLATION_VARIANTS: dict[str, dict] = {
    "no_neutrality": {
        "dollar_neutral": False,
        "sector_neutral": False,
    },
    # Bypasses apply_book_neutrality()'s two constraint steps. The per-name
    # cap and gross-exposure cap (both still config-driven via base_kwargs)
    # are NOT part of "neutrality" in this codebase's own naming (see
    # portfolio/book_neutrality.py's own 4-step docstring) and stay active.
    "no_hysteresis": {
        "hysteresis_rank_margin": 0.0,
    },
    # build_rank_based_book()'s own documented no-op default - every
    # rebalance re-selects top/bottom-N purely by that bar's current rank,
    # no incumbent retention across rebalances.
    "no_cost_model": {
        "cost_bps_per_side": 0.0,
        "commission_bps": 0.0,
    },
    # Zeroes the SIMULATOR's own cost terms - the offline analogue of
    # execution/cost_model.py's round-trip cost estimate, simplified here to
    # a fixed bps rate rather than main.py's per-bar liquidity-derived one
    # (that per-bar estimate is itself absent from the offline dataset, the
    # same reason no_net_edge_gate above is not offline-measurable).
}


def simulate_static_baseline(
    frame: pd.DataFrame,
    *,
    forward_return_column: str = "target_return_1d",
    ticker_column: str = "ticker",
    date_column: str = "date",
    min_universe_size: int = 20,
    trading_days_per_year: int = 252,
) -> dict:
    """The "did the adaptive machinery add anything over just holding
    everything" reference point every other variant's delta is measured
    against. Equal-weight, long-only, buy-and-hold: the universe is fixed
    ONCE, on the first date with >= min_universe_size eligible names, and
    never rebalanced again (by construction, zero turnover and zero cost
    after the single initial buy - deliberately NOT re-equal-weighting the
    surviving membership each date, which would itself be a form of active
    rebalancing and defeat the point of a static reference).

    A ticker that later has a missing/NaN forward return on some date is
    simply excluded from that date's equal-weighted average (not
    renormalized against the full original count) - the same "skip, don't
    zero-fill" convention _simulate_rank_book_core() already follows for
    thin dates.

    Returns the SAME shape as RankBookSimulationResult.to_dict() (a plain
    dict, not the frozen dataclass itself, since this function has no
    turnover/rebalance concept to compute num_rebalances/annualized_turnover
    from - both are reported as 0)."""
    working = frame.dropna(subset=[forward_return_column]).copy()
    unique_dates = sorted(working[date_column].unique())

    initial_tickers: set | None = None
    net_returns: list[float] = []
    per_date_used: list = []
    names_held_series: list[int] = []

    for date in unique_dates:
        date_frame = working[working[date_column] == date]
        if initial_tickers is None:
            if len(date_frame) < min_universe_size:
                continue
            initial_tickers = set(date_frame[ticker_column])

        held_frame = date_frame[date_frame[ticker_column].isin(initial_tickers)]
        if held_frame.empty:
            continue
        bar_return = float(held_frame[forward_return_column].mean())
        net_returns.append(bar_return)
        per_date_used.append(str(date))
        names_held_series.append(len(held_frame))

    if not per_date_used:
        return {
            "gross_sharpe": 0.0, "net_sharpe": 0.0, "gross_total_return": 0.0,
            "net_total_return": 0.0, "net_max_drawdown": 0.0, "annualized_turnover": 0.0,
            "cost_drag_annual_bps": 0.0, "num_rebalances": 0, "num_dates_used": 0,
            "mean_names_long": 0.0, "mean_names_short": 0.0,
            "per_date_net_return": [], "per_date": [],
        }

    net_array = np.asarray(net_returns, dtype=float)
    cumprod = np.cumprod(1.0 + net_array)
    running_peak = np.maximum.accumulate(np.concatenate(([1.0], cumprod)))[1:]
    max_drawdown = float(np.min(cumprod / running_peak - 1.0))
    sharpe = 0.0
    if len(net_array) >= 2:
        std = float(net_array.std(ddof=1))
        if std > 0.0:
            sharpe = float(net_array.mean() / std) * math.sqrt(trading_days_per_year)

    return {
        "gross_sharpe": sharpe,
        "net_sharpe": sharpe,
        "gross_total_return": float(cumprod[-1] - 1.0),
        "net_total_return": float(cumprod[-1] - 1.0),
        "net_max_drawdown": max_drawdown,
        "annualized_turnover": 0.0,
        "cost_drag_annual_bps": 0.0,
        "num_rebalances": 1 if initial_tickers else 0,
        "num_dates_used": len(per_date_used),
        "mean_names_long": float(np.mean(names_held_series)) if names_held_series else 0.0,
        "mean_names_short": 0.0,
        "per_date_net_return": [float(v) for v in net_returns],
        "per_date": per_date_used,
    }


def run_ablation(frame: pd.DataFrame, base_kwargs: dict, variants: list[str]) -> dict:
    """Runs simulate_rank_book() once per requested variant (base_kwargs
    overridden per ABLATION_VARIANTS' declarative dict) on the SAME
    predictions and dates, plus simulate_static_baseline() if
    "static_baseline" is requested. Any requested variant in
    NOT_OFFLINE_MEASURABLE_VARIANTS or equal to "no_retraining" returns the
    honesty-contract sentinel instead of a number - "no_retraining" is
    offline-measurable, but only via compare_static_vs_retrained() below,
    which needs Phase 4 walk-forward artifacts this function does not
    receive (a single frame/base_kwargs pair cannot answer a
    trained-once-vs-retrained-per-window question).

    Returns {variant_name: {...RankBookSimulationResult shape...,
    "delta_vs_static_baseline": float} | {"status": "not_offline_measurable"
    | "unknown_variant", "reason": str}}."""
    results: dict[str, dict] = {}

    static_result = simulate_static_baseline(
        frame,
        forward_return_column=base_kwargs.get("forward_return_column", "target_return_1d"),
        ticker_column=base_kwargs.get("ticker_column", "ticker"),
        date_column=base_kwargs.get("date_column", "date"),
        min_universe_size=base_kwargs.get("min_universe_size", 20),
        trading_days_per_year=base_kwargs.get("trading_days_per_year", 252),
    )
    static_sharpe = static_result["net_sharpe"]
    if "static_baseline" in variants:
        results["static_baseline"] = {**static_result, "delta_vs_static_baseline": 0.0}

    for name in variants:
        if name == "static_baseline":
            continue
        if name == "no_retraining":
            results[name] = {
                "status": "not_offline_measurable",
                "reason": (
                    "Offline-measurable, but only via compare_static_vs_retrained() "
                    "against a Phase 4 walk-forward run's artifacts - run_ablation() "
                    "only has a single frame/base_kwargs pair, not per-window models."
                ),
            }
            continue
        if name in NOT_OFFLINE_MEASURABLE_VARIANTS:
            results[name] = {"status": "not_offline_measurable", "reason": NOT_OFFLINE_MEASURABLE_VARIANTS[name]}
            continue
        if name not in ABLATION_VARIANTS:
            results[name] = {"status": "unknown_variant", "reason": f"{name!r} is not a recognized ablation variant"}
            continue

        variant_kwargs = {**base_kwargs, **ABLATION_VARIANTS[name]}
        result = simulate_rank_book(frame, **variant_kwargs)
        results[name] = {**result.to_dict(), "delta_vs_static_baseline": result.net_sharpe - static_sharpe}

    return results


def compare_static_vs_retrained(
    frozen_net_performance_by_window: dict[int, dict],
    retrained_net_performance_by_window: dict[int, dict],
    *,
    min_windows: int = 2,
) -> dict:
    """The "no_retraining" ablation - pure comparison of two ALREADY-COMPUTED
    result sets, matching train.py::assess_net_performance_quality()'s own
    "assess what's given, never run a simulation itself" convention.

    frozen_net_performance_by_window: {window_index: <net_performance_by_window
    entry shape, "simulation" key with net_sharpe>} - window 0's model's OWN
    predictions run (via evaluation.predict_head() + run_net_performance_simulation(),
    by the caller) against every LATER window's own backtest frame, i.e.
    "what if we had never retrained past window 0".
    retrained_net_performance_by_window: the corresponding entries already
    in a Phase 4 walk_forward_summary.json's net_performance_by_window
    (window N's OWN freshly-trained model on window N's own data) - "what
    the walk-forward run actually did".

    Both dicts must share window_index keys for windows 1+ (window 0 is
    excluded from the comparison by construction - it IS the frozen model,
    comparing it against itself is not a retraining ablation). Returns
    {"status": "insufficient_windows", "reason": ...} when fewer than
    min_windows comparable windows are present in both dicts - never a
    fabricated delta from 0 or 1 windows."""
    comparable_windows = sorted(
        (set(frozen_net_performance_by_window) & set(retrained_net_performance_by_window)) - {0}
    )
    if len(comparable_windows) < min_windows:
        return {
            "status": "insufficient_windows",
            "reason": (
                f"need >= {min_windows} windows (excluding window 0, the frozen model itself) "
                f"present in both frozen and retrained result sets, found {len(comparable_windows)}"
            ),
        }

    per_window: list[dict] = []
    deltas: list[float] = []
    for window_index in comparable_windows:
        frozen_sharpe = float(frozen_net_performance_by_window[window_index]["simulation"]["net_sharpe"])
        retrained_sharpe = float(retrained_net_performance_by_window[window_index]["simulation"]["net_sharpe"])
        delta = retrained_sharpe - frozen_sharpe
        deltas.append(delta)
        per_window.append(
            {
                "window_index": window_index,
                "frozen_net_sharpe": frozen_sharpe,
                "retrained_net_sharpe": retrained_sharpe,
                "delta": delta,
            }
        )

    return {
        "status": "walk_forward_derived",
        "num_windows": len(comparable_windows),
        "per_window": per_window,
        "mean_delta_retrained_minus_frozen": float(np.mean(deltas)),
    }
