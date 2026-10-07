"""Cost-aware offline simulation of the cross-sectional rank book (V5.1
Phase 0). Reuses the EXACT selection/neutrality machinery main.py's live
decision path uses - portfolio.book_construction.build_rank_based_book()
and portfolio.book_neutrality.apply_book_neutrality() - so this module's
numbers are the offline mirror of live behavior, not an independently
re-derived approximation. Both of those are pure Python/dataclasses (no
torch, no pandas), so importing them here does not compromise this
package's torch-free contract (see evaluation/__init__.py's docstring).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace

import numpy as np
import pandas as pd

from portfolio.book_construction import (
    BookAllocation,
    build_book_raw_weights,
    build_rank_based_book,
    remember_formed_book,
)
from portfolio.book_neutrality import apply_book_neutrality
from portfolio.rank_signal import cross_sectional_rank_scores

DEFAULT_SECTOR_MAX_NET_WEIGHT = 0.05


@dataclass(frozen=True)
class RankBookSimulationResult:
    gross_sharpe: float
    net_sharpe: float
    gross_total_return: float
    net_total_return: float
    net_max_drawdown: float
    annualized_turnover: float
    cost_drag_annual_bps: float
    num_rebalances: int
    num_dates_used: int
    mean_names_long: float
    mean_names_short: float
    per_date_net_return: list = field(default_factory=list)
    per_date: list = field(default_factory=list)
    # V5.5.0 (as-live mode) - 0 / {} in the idealized default run.
    num_vetoed_rebalances: int = 0
    veto_reasons: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _annualized_sharpe(returns: np.ndarray, trading_days_per_year: int) -> float:
    """Same convention as train.py::compute_strategy_metrics() -
    (mean/std) * sqrt(trading_days_per_year) - kept identical so this
    simulator's Sharpe is directly comparable to every other Sharpe number
    already reported by this codebase."""
    if len(returns) < 2:
        return 0.0
    std = float(returns.std(ddof=1))
    if std <= 0.0:
        return 0.0
    return float(returns.mean() / std) * math.sqrt(trading_days_per_year)


def _empty_result(trading_days_per_year: int) -> RankBookSimulationResult:
    return RankBookSimulationResult(
        gross_sharpe=0.0,
        net_sharpe=0.0,
        gross_total_return=0.0,
        net_total_return=0.0,
        net_max_drawdown=0.0,
        annualized_turnover=0.0,
        cost_drag_annual_bps=0.0,
        num_rebalances=0,
        num_dates_used=0,
        mean_names_long=0.0,
        mean_names_short=0.0,
        per_date_net_return=[],
        per_date=[],
    )


def _simulate_rank_book_core(
    frame: pd.DataFrame,
    *,
    prediction_column: str,
    forward_return_column: str = "target_return_1d",
    ticker_column: str = "ticker",
    date_column: str = "date",
    top_n: int,
    bottom_n: int,
    rebalance_every_bars: int,
    cost_bps_per_side: float,
    commission_bps: float,
    gross_exposure: float,
    dollar_neutral: bool,
    sector_neutral: bool,
    sector_by_ticker: dict[str, str] | None = None,
    hysteresis_rank_margin: float = 0.0,
    max_weight_per_name: float,
    min_universe_size: int = 20,
    sector_max_net_weight: float = DEFAULT_SECTOR_MAX_NET_WEIGHT,
    trading_days_per_year: int = 252,
    entry_lag_bars: int = 0,
    min_commission_usd: float = 0.0,
    assumed_portfolio_value_usd: float = 0.0,
    impact_model_config: dict | None = None,
    candidate_metadata_by_ticker: dict[str, dict] | None = None,
    normalize_to_percentile: bool = False,
    min_rank_confidence_spread: float = 0.0,
    rolling_ic_gate_fn=None,
    live_weighting: bool = False,
    max_position_weight: float = 0.25,
    hold_positions_on_veto: bool = False,
    retry_rebalance_after_veto: bool = False,
    max_holding_dates: int | None = None,
) -> tuple[RankBookSimulationResult, dict[str, int]]:
    """The real implementation, shared by simulate_rank_book() (public,
    returns just the result) and capacity_curve() (needs held_days_by_ticker
    too, to estimate which held name is the liquidity bottleneck). See
    simulate_rank_book()'s docstring for the full parameter/behavior
    contract - this function is not itself part of the public API.

    Per date, in sorted order: dates with fewer than min_universe_size
    eligible (non-NaN prediction AND forward-return) rows are SKIPPED
    entirely (no selection, no return accrual) - same convention as
    train.py::build_cross_sectional_rank_targets()'s min_universe_size
    gate; the book silently carries over across a skipped date, as if it
    did not exist for accounting purposes. On a rebalance date (every
    rebalance_every_bars-th non-skipped date, first date always rebalances),
    predictions are handed to build_rank_based_book() (with hysteresis
    against the previous allocation) for top/bottom-N selection, each leg
    is equal-weighted to gross_exposure/2, then apply_book_neutrality()
    applies the sector/dollar/gross constraints. Cost
    (cost_bps_per_side + commission_bps, in bps) is charged on the turnover
    of that single rebalance event only - held-and-unchanged positions
    between rebalances accrue zero cost, matching main.py's own
    hold-until-next-rebalance contract (portfolio/book_construction.py::
    should_rebalance_this_bar()).

    entry_lag_bars (V5.2.1, development/Problems.md - default 0, today's
    exact behavior): a Daily-resolution market order decided off bar N's
    close fills at bar N+1's open, not bar N's close (main.py's own
    documented behavior) - this function previously credited a newly-
    selected position with that SAME date's forward return, an implicit
    zero-lag fill assumption no live system can achieve. When > 0, return
    accrual for a given date reads the book state as it stood
    entry_lag_bars dates EARLIER (a rolling snapshot history), not the
    state as of the current date's own rebalance - so a position selected
    today does not start earning return until entry_lag_bars dates from
    now, mirroring the live fill delay. Affects ONLY which return a held
    weight earns; turnover/cost accounting stays keyed to the unlagged
    rebalance transition (cost is incurred at order-submission time, not
    fill time). A position held unchanged across the lag window has an
    identical snapshot at both indices, so nothing is falsely penalized -
    only genuinely CHANGED positions are affected.

    min_commission_usd / assumed_portfolio_value_usd (default 0.0 - a
    no-op, today's exact bps-of-turnover-only cost model): an
    honestly-approximate per-order minimum-commission floor, layered on
    top of the existing cost_bps_per_side/commission_bps bps-of-turnover
    term. Real broker commissions are often floor-dominated for small
    orders (see execution/cost_model.py's own min_commission_usd), which a
    pure bps-of-notional model never captures. Requires an assumed NAV to
    convert a per-order dollar floor into a return-fraction - a deliberate
    approximation (uniform order size, fixed NAV across the whole run),
    not a precision claim, same "honestly-approximate" convention
    capacity_curve()'s own docstring uses. Only applied on rebalance
    dates, charged once per name whose weight actually changed.

    AS-LIVE MODE (V5.5.0, Problems.md #128) - the nine trailing keyword
    arguments above all default to the idealized behavior this function
    always had; `evaluation.live_parity.build_as_live_kwargs()` sets them to
    mirror main.py's live path (parity rule, AGENTS.md):
    - `normalize_to_percentile`: candidates are ranked by per-date
      cross-sectional percentile (what live hands the book), so the
      hysteresis margin means percentile points as live; the spread gate
      keeps seeing RAW scores (portfolio/book_construction.py contract).
    - `min_rank_confidence_spread` / `rolling_ic_gate_fn`: the two live
      vetoes (the gate fn maps a date string to evaluate_rolling_ic_gate()'s
      result dict, or None for "no opinion").
    - `candidate_metadata_by_ticker`: real `trading_eligible`/`asset_class`
      instead of forcing True/None.
    - `live_weighting`: build_book_raw_weights() confidence weights instead
      of equal weights (both feed apply_book_neutrality()).
    - `hold_positions_on_veto`: a vetoed rebalance HOLDS the existing book
      (live never liquidates on a veto - should_exit_non_selected_book_symbol)
      instead of flattening it; `retry_rebalance_after_veto` re-attempts on
      the next date as live does (its has_previous_allocation reads False).
    - `max_holding_dates`: live's `exits.max_holding_bars` age exit.
    - hysteresis anchors on the last NON-EMPTY book (remember_formed_book()),
      which a veto never erases.
    """
    sector_by_ticker = sector_by_ticker or {}
    candidate_metadata_by_ticker = candidate_metadata_by_ticker or {}
    as_live = bool(hold_positions_on_veto)
    formed_book: dict[str, BookAllocation] = {}
    last_rebalance_vetoed = False
    num_vetoed_rebalances = 0
    veto_reasons: dict[str, int] = {}
    entry_date_index_by_ticker: dict[str, int] = {}
    working = frame.dropna(subset=[prediction_column]).copy()
    unique_dates = sorted(working[date_column].unique())

    held_weights: dict[str, float] = {}
    held_allocations: dict[str, BookAllocation] = {}
    held_days_by_ticker: dict[str, int] = {}

    gross_returns: list[float] = []
    net_returns: list[float] = []
    per_date_used: list = []
    names_long_series: list[int] = []
    names_short_series: list[int] = []
    total_turnover = 0.0
    total_cost_return = 0.0
    num_rebalances = 0
    rebalance_counter = 0
    # V5.2.1 - one held_weights snapshot per processed date, appended AFTER
    # that date's own rebalance (if any) - see entry_lag_bars's docstring.
    weights_history: list[dict[str, float]] = []

    net_cumprod = 1.0
    gross_cumprod = 1.0
    net_running_peak = 1.0
    net_max_drawdown = 0.0

    for date in unique_dates:
        date_frame = working[working[date_column] == date]
        eligible = date_frame.dropna(subset=[forward_return_column])
        if len(eligible) < min_universe_size:
            continue

        is_rebalance = (rebalance_counter % max(1, rebalance_every_bars)) == 0
        if retry_rebalance_after_veto and last_rebalance_vetoed:
            is_rebalance = True
        rebalance_counter += 1
        cost_this_date = 0.0

        # V5.5.0 - live's `exits.max_holding_bars` age exit (as-live only).
        if max_holding_dates is not None and held_weights:
            date_index = rebalance_counter - 1
            expired = [
                symbol
                for symbol in held_weights
                if date_index - entry_date_index_by_ticker.get(symbol, date_index) >= max_holding_dates
            ]
            if expired:
                cost_this_date += (
                    sum(abs(held_weights[symbol]) for symbol in expired) * (cost_bps_per_side + commission_bps) / 1e4
                )
                total_turnover += sum(abs(held_weights[symbol]) for symbol in expired)
                held_weights = {symbol: weight for symbol, weight in held_weights.items() if symbol not in expired}
                held_allocations = {
                    symbol: allocation for symbol, allocation in held_allocations.items() if symbol not in expired
                }
                for symbol in expired:
                    entry_date_index_by_ticker.pop(symbol, None)

        if is_rebalance:
            raw_scores_by_ticker = {
                str(ticker): float(rank) for ticker, rank in zip(eligible[ticker_column], eligible[prediction_column])
            }
            candidate_ranks = (
                cross_sectional_rank_scores(raw_scores_by_ticker) if normalize_to_percentile else raw_scores_by_ticker
            )
            book_candidates = {
                ticker: {
                    "predicted_rank_20d": float(rank),
                    "trading_eligible": bool(candidate_metadata_by_ticker.get(ticker, {}).get("trading_eligible", True)),
                    "asset_class": candidate_metadata_by_ticker.get(ticker, {}).get("asset_class"),
                }
                for ticker, rank in candidate_ranks.items()
            }
            gate_result = rolling_ic_gate_fn(str(date)) if rolling_ic_gate_fn is not None else None
            veto_reason_out: dict[str, str] = {}
            # min_rank_confidence_spread defaults to 0.0 DELIBERATELY (as-live
            # mode passes the live gate value instead), not an
            # oversight: this simulator measures book QUALITY (what would
            # this rank prediction have earned, net of costs) uncapped by
            # the live entry gate's conviction filter - those are two
            # different questions. Do not "fix" this into reading
            # phase_v2.portfolio_book.min_rank_confidence_spread to try to
            # mirror live engagement; that number is calibrated
            # specifically for the RAW pre-normalization score scale
            # (aq evaluate --calibrate-book-spread, portfolio/rank_signal.py),
            # which this function's `prediction_column` is not guaranteed
            # to be (callers may pass an already-normalized column). A
            # healthy net_sharpe here is evidence the RANKING has value,
            # never evidence the live gate will engage on any given day.
            allocations = build_rank_based_book(
                book_candidates,
                top_n=top_n,
                bottom_n=bottom_n,
                min_rank_confidence_spread=min_rank_confidence_spread,
                previous_allocations=(formed_book if as_live else held_allocations) or None,
                hysteresis_rank_margin=hysteresis_rank_margin,
                spread_check_ranks=raw_scores_by_ticker if normalize_to_percentile else None,
                rolling_ic_gate_result=gate_result,
                veto_reason_out=veto_reason_out,
            )
            last_rebalance_vetoed = not allocations
            if not allocations:
                num_vetoed_rebalances += 1
                veto_key = veto_reason_out.get("reason", "empty_book")
                veto_reasons[veto_key] = veto_reasons.get(veto_key, 0) + 1
            formed_book = remember_formed_book(formed_book, allocations)

            if not allocations and hold_positions_on_veto:
                # Live parity: a vetoed rebalance leaves the existing book
                # untouched (no turnover, no cost, no new positions).
                new_weights = dict(held_weights)
            elif allocations:
                long_symbols = [symbol for symbol, allocation in allocations.items() if allocation.role == "long"]
                short_symbols = [symbol for symbol, allocation in allocations.items() if allocation.role == "short"]
                raw_weights: dict[str, float] = {}
                if live_weighting:
                    raw_weights = build_book_raw_weights(allocations, max_position_weight)
                else:
                    if long_symbols:
                        per_name = (gross_exposure / 2.0) / len(long_symbols)
                        raw_weights.update({symbol: per_name for symbol in long_symbols})
                    if short_symbols:
                        per_name = (gross_exposure / 2.0) / len(short_symbols)
                        raw_weights.update({symbol: -per_name for symbol in short_symbols})

                new_weights, _diagnostics = apply_book_neutrality(
                    raw_weights,
                    sector_by_symbol=sector_by_ticker,
                    dollar_neutral=dollar_neutral,
                    sector_neutral=sector_neutral,
                    gross_exposure_cap=gross_exposure,
                    max_weight_per_name=max_weight_per_name,
                    sector_max_net_weight=sector_max_net_weight,
                )
                held_allocations = {
                    symbol: replace(allocation, target_weight=new_weights.get(symbol, 0.0))
                    for symbol, allocation in allocations.items()
                }
            else:
                new_weights = {}
                held_allocations = {}

            for symbol in new_weights:
                if symbol not in held_weights:
                    entry_date_index_by_ticker[symbol] = rebalance_counter - 1
            for symbol in list(entry_date_index_by_ticker):
                if symbol not in new_weights:
                    entry_date_index_by_ticker.pop(symbol, None)

            all_symbols = set(new_weights) | set(held_weights)
            deltas_by_symbol = {
                symbol: new_weights.get(symbol, 0.0) - held_weights.get(symbol, 0.0) for symbol in all_symbols
            }
            turnover_this_rebalance = sum(abs(delta) for delta in deltas_by_symbol.values())
            total_turnover += turnover_this_rebalance
            cost_this_date = turnover_this_rebalance * (cost_bps_per_side + commission_bps) / 1e4
            # V5.2.1 (development/Problems.md) - honestly-approximate
            # per-order minimum-commission floor, see this function's own
            # docstring. No-op (0.0) unless both inputs are configured.
            if min_commission_usd > 0.0 and assumed_portfolio_value_usd > 0.0:
                names_traded = sum(1 for delta in deltas_by_symbol.values() if delta != 0.0)
                cost_this_date += names_traded * min_commission_usd / assumed_portfolio_value_usd
            total_cost_return += cost_this_date

            # V5.4.2 - Almgren-style impact model (optional, off by default).
            # Simplified date-level estimate: uses aggregate turnover and a
            # configured daily vol + eta to approximate sqrt-impact cost.
            if impact_model_config and impact_model_config.get("enabled", False):
                from evaluation.impact_model import compute_sqrt_impact_bps

                eta = float(impact_model_config.get("eta", 0.5))
                daily_vol = float(impact_model_config.get("daily_volatility", 0.02))
                adv = float(impact_model_config.get("avg_daily_dollar_volume", 50_000_000))
                pv = assumed_portfolio_value_usd if assumed_portfolio_value_usd > 0 else 1e6
                impact_bps = compute_sqrt_impact_bps(
                    trade_size_fraction=turnover_this_rebalance,
                    daily_volatility=daily_vol,
                    avg_daily_dollar_volume=adv,
                    portfolio_value=pv,
                    eta=eta,
                )
                impact_cost = impact_bps / 1e4
                cost_this_date += impact_cost
                total_cost_return += impact_cost

            num_rebalances += 1
            held_weights = new_weights

        for symbol in held_weights:
            held_days_by_ticker[symbol] = held_days_by_ticker.get(symbol, 0) + 1
        names_long_series.append(sum(1 for weight in held_weights.values() if weight > 0.0))
        names_short_series.append(sum(1 for weight in held_weights.values() if weight < 0.0))

        date_returns = dict(zip(eligible[ticker_column], eligible[forward_return_column]))
        # V5.2.1 - entry_lag_bars=0 (default) uses held_weights directly,
        # byte-identical to before this parameter existed. > 0 looks back
        # into weights_history instead - see this function's own docstring.
        if entry_lag_bars > 0:
            lag_index = len(weights_history) - entry_lag_bars
            effective_weights = weights_history[lag_index] if lag_index >= 0 else {}
        else:
            effective_weights = held_weights
        bar_return = sum(
            weight * float(date_returns.get(symbol, 0.0)) for symbol, weight in effective_weights.items()
        )
        net_return = bar_return - cost_this_date

        gross_returns.append(bar_return)
        net_returns.append(net_return)
        per_date_used.append(str(date))
        weights_history.append(dict(held_weights))
        gross_cumprod *= 1.0 + bar_return
        net_cumprod *= 1.0 + net_return
        net_running_peak = max(net_running_peak, net_cumprod)
        net_max_drawdown = min(net_max_drawdown, net_cumprod / net_running_peak - 1.0)

    if not per_date_used:
        return _empty_result(trading_days_per_year), held_days_by_ticker

    num_dates_used = len(per_date_used)
    years = num_dates_used / trading_days_per_year
    gross_array = np.asarray(gross_returns, dtype=float)
    net_array = np.asarray(net_returns, dtype=float)

    result = RankBookSimulationResult(
        gross_sharpe=_annualized_sharpe(gross_array, trading_days_per_year),
        net_sharpe=_annualized_sharpe(net_array, trading_days_per_year),
        gross_total_return=float(gross_cumprod - 1.0),
        net_total_return=float(net_cumprod - 1.0),
        net_max_drawdown=float(net_max_drawdown),
        annualized_turnover=float(total_turnover / years) if years > 0 else 0.0,
        cost_drag_annual_bps=float(total_cost_return / years * 10_000.0) if years > 0 else 0.0,
        num_rebalances=num_rebalances,
        num_dates_used=num_dates_used,
        mean_names_long=float(np.mean(names_long_series)) if names_long_series else 0.0,
        mean_names_short=float(np.mean(names_short_series)) if names_short_series else 0.0,
        per_date_net_return=[float(value) for value in net_returns],
        per_date=per_date_used,
        num_vetoed_rebalances=num_vetoed_rebalances,
        veto_reasons=dict(sorted(veto_reasons.items())),
    )
    return result, held_days_by_ticker


def simulate_rank_book(frame: pd.DataFrame, **kwargs) -> RankBookSimulationResult:
    """Public entry point - see _simulate_rank_book_core()'s docstring for
    the full algorithm. Discards held_days_by_ticker (only capacity_curve()
    needs it)."""
    result, _held_days_by_ticker = _simulate_rank_book_core(frame, **kwargs)
    return result


def capacity_curve(
    frame: pd.DataFrame,
    *,
    dollar_volume_column: str = "liquidity_log_dollar_volume",
    participation_cap: float,
    base_kwargs: dict,
    top_n_sweep: list[int],
) -> dict:
    """Breadth + capacity check (V5.1 Phase 0, an addition beyond the
    original roadmap table - see the V5.1 plan's own §1 "one thing missing
    from the list"): sweeps top_n==bottom_n across top_n_sweep, holding
    every other simulate_rank_book() kwarg fixed via base_kwargs, so a
    rank-IC concentrated in a handful of names (net_sharpe collapses as
    top_n shrinks toward the extreme) is visibly distinguishable from one
    genuinely spread across the cross-section.

    capacity_usd is a deliberately simple, honestly-approximate estimate,
    not a precision claim: among names actually held during the BASE run
    (base_kwargs's own top_n/bottom_n), the one with the lowest average
    dollar volume (dollar_volume_column, a log1p value - inverted with
    expm1 here, the correct inverse) is the binding constraint; scaling its
    average dollar volume by participation_cap and by the number of held
    names gives a rough total-book capacity ceiling. binding_ticker names
    exactly which held name limits it, so this is auditable rather than a
    black-box number.

    A held ticker with dollar_volume_column == 0.0 exactly (e.g. a forex
    pair - Yahoo Finance reports no real Volume for FX, so
    log1p(close*volume) is always 0.0 for them, see development/Problems.md)
    is EXCLUDED from the binding-ticker search: a true zero here means "no
    real liquidity signal for this asset," not "zero capacity," and letting
    it win the minimum would make one data-quality artifact dictate the
    whole book's capacity regardless of every other held name's real
    liquidity. If every held ticker lacks real volume data, this honestly
    degrades to capacity_usd=0.0 / binding_ticker=None, the same "can't
    estimate" result already returned when the base run holds nothing."""
    per_top_n: list[dict] = []
    base_held_days: dict[str, int] | None = None
    base_top_n = base_kwargs.get("top_n")

    for n in top_n_sweep:
        sweep_kwargs = dict(base_kwargs)
        sweep_kwargs["top_n"] = n
        sweep_kwargs["bottom_n"] = n
        result, held_days = _simulate_rank_book_core(frame, **sweep_kwargs)
        per_top_n.append({"top_n": n, "net_sharpe": result.net_sharpe})
        if n == base_top_n:
            base_held_days = held_days

    if base_held_days is None:
        _, base_held_days = _simulate_rank_book_core(frame, **base_kwargs)

    if not base_held_days:
        return {"capacity_usd": 0.0, "binding_ticker": None, "per_top_n": per_top_n}

    ticker_column = base_kwargs.get("ticker_column", "ticker")
    avg_log_dollar_volume = frame.groupby(ticker_column)[dollar_volume_column].mean()
    held_avg_dollar_volume = {
        ticker: float(np.expm1(avg_log_dollar_volume.get(ticker, 0.0))) for ticker in base_held_days
    }
    if not held_avg_dollar_volume:
        return {"capacity_usd": 0.0, "binding_ticker": None, "per_top_n": per_top_n}

    # Zero means "no real volume data for this ticker" (e.g. forex - see
    # this function's own docstring), not "zero liquidity" - exclude it
    # from the binding-ticker search so a data-quality artifact can't
    # dictate the whole book's capacity.
    tickers_with_real_volume = {ticker: value for ticker, value in held_avg_dollar_volume.items() if value > 0.0}
    if not tickers_with_real_volume:
        return {"capacity_usd": 0.0, "binding_ticker": None, "per_top_n": per_top_n}

    binding_ticker = min(tickers_with_real_volume, key=tickers_with_real_volume.get)
    capacity_usd = float(tickers_with_real_volume[binding_ticker] * participation_cap * len(held_avg_dollar_volume))
    return {"capacity_usd": capacity_usd, "binding_ticker": binding_ticker, "per_top_n": per_top_n}


def stress_test_costs(frame: pd.DataFrame, *, base_kwargs: dict, cost_multipliers: tuple = (1.0, 2.0, 3.0)) -> list[dict]:
    """One simulate_rank_book() run per cost multiplier, scaling BOTH
    cost_bps_per_side and commission_bps - answers "does the edge survive
    if real-world costs turn out to be 2x/3x the calibrated estimate",
    the robustness check item 12 of the V5.1 roadmap asks for."""
    results = []
    for multiplier in cost_multipliers:
        stressed_kwargs = dict(base_kwargs)
        stressed_kwargs["cost_bps_per_side"] = float(base_kwargs.get("cost_bps_per_side", 0.0)) * multiplier
        stressed_kwargs["commission_bps"] = float(base_kwargs.get("commission_bps", 0.0)) * multiplier
        result = simulate_rank_book(frame, **stressed_kwargs)
        results.append({"cost_multiplier": multiplier, **result.to_dict()})
    return results


def _bootstrap_mean_confidence_interval(
    values: list[float], n_resamples: int = 2000, confidence: float = 0.95, seed: int = 42
) -> dict:
    """Torch-free duplicate of train.py::bootstrap_ic_confidence_interval()'s
    resample-with-replacement bootstrap over a plain float series - same
    algorithm and defaults, deliberately reimplemented here (not imported)
    since train.py imports torch and this package must stay torch-free (see
    evaluation/__init__.py's docstring)."""
    if not values:
        return {"lower_bound": 0.0, "upper_bound": 0.0, "mean": 0.0}
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    resampled_means = np.empty(n_resamples)
    for i in range(n_resamples):
        resampled_means[i] = rng.choice(array, size=len(array), replace=True).mean()
    alpha = (1.0 - confidence) / 2.0
    return {
        "lower_bound": float(np.quantile(resampled_means, alpha)),
        "upper_bound": float(np.quantile(resampled_means, 1.0 - alpha)),
        "mean": float(array.mean()),
    }


def summarize_metric_stability(per_window_values: list[float], *, min_windows: int, max_sign_flip_fraction: float) -> dict:
    """Cross-window stability summary (used by Phase 4's walk-forward
    evaluation and Phase 5's ablation) - mirrors
    train.py::assess_ranking_quality()'s era-sign-instability check, one
    level up: a window whose sign disagrees with the overall mean's sign is
    a "flip", same concept as an opposite-sign era. num_windows below
    min_windows or a sign-flip fraction above max_sign_flip_fraction both
    fail "stable"."""
    values = [float(value) for value in per_window_values]
    num_windows = len(values)
    if num_windows == 0:
        return {
            "num_windows": 0, "mean": 0.0, "sign_flip_fraction": 0.0, "stable": False,
            "failures": ["no_windows"], "bootstrap": _bootstrap_mean_confidence_interval([]),
        }

    mean_value = float(np.mean(values))
    overall_positive = mean_value >= 0.0
    flips = sum(1 for value in values if (value >= 0.0) != overall_positive)
    sign_flip_fraction = flips / num_windows

    failures = []
    if num_windows < min_windows:
        failures.append("insufficient_windows")
    if sign_flip_fraction > max_sign_flip_fraction:
        failures.append("sign_flip_fraction_above_gate")

    return {
        "num_windows": num_windows,
        "mean": mean_value,
        "sign_flip_fraction": sign_flip_fraction,
        "stable": not failures,
        "failures": failures,
        "bootstrap": _bootstrap_mean_confidence_interval(values),
    }
