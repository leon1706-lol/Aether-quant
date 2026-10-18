"""Staggered tranche book, offline (V6.2.0, todo lead 3 "phase luck", rule R-STAGGER).

The shipped book rebalances every 20 sessions on one phase, and which phase it lands on moves its validation Sharpe
between -1.02 and +0.57. K tranches - each the same book at 1/K of the gross cap and ceil(top/K) / ceil(bottom/K)
names, rebalancing at evenly spread phase offsets (`portfolio.book_construction.tranche_offsets`) - average that timing
luck out, the overlapping-portfolio construction of the momentum literature.

Offline the tranche book is the SUM of K phase-shifted runs of the calibrated simulator (`simulate_rank_book`), each
with `tranche_book_params`'s share of the book: returns are linear in weights, so the sum is the combined book's
return, except that (a) trades the tranches would net are each charged (conservative) and (b) the per-name / class /
position caps apply per tranche instead of to the sum. The kill switch watches the whole portfolio in live, so each
tranche's kill switch is fed the other tranches' returns from a first pass (`kill_switch_extra_returns`, the
mechanism V6.1.0 uses for P&L outside a simulation). The legacy signal runs once, in tranche 0, at its full budget.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from evaluation.rank_book_simulator import RankBookSimulationResult, simulate_rank_book
from portfolio.book_construction import tranche_book_params, tranche_offsets


def tranche_kwargs(kwargs: dict, tranches: int) -> list[dict]:
    """The K sub-book kwargs: tranche k's names, gross, position cap and phase (tranche 0 keeps the base phase)."""
    count = max(1, int(tranches))
    every = int(kwargs["rebalance_every_bars"])
    base_phase = int(kwargs.get("rebalance_counter_start", 0))
    params = tranche_book_params(int(kwargs["top_n"]), int(kwargs["bottom_n"]), float(kwargs["gross_exposure"]), count,
                                 kwargs.get("max_active_positions"))
    subs = []
    for index, offset in enumerate(tranche_offsets(every, count)):
        sub = dict(kwargs, top_n=params["top_n"], bottom_n=params["bottom_n"], gross_exposure=params["gross_exposure_cap"],
                   rebalance_counter_start=(base_phase - offset) % max(1, every))
        if kwargs.get("max_active_positions"):
            sub["max_active_positions"] = params["max_active_positions"]
        if index > 0:
            sub["legacy_component"] = None
        subs.append(sub)
    return subs


def simulate_tranche_book(frame, *, tranches: int = 1, simulate=simulate_rank_book, trading_days_per_year: int = 252,
                          **kwargs) -> RankBookSimulationResult:
    """`simulate_rank_book(frame, **kwargs)` for K = 1; for K > 1 the combined result of K staggered tranches (module
    docstring). `simulate` is injectable for tests; the cash sweep sizes from the whole book and is not supported here."""
    if int(tranches) <= 1:
        return simulate(frame, **kwargs)
    if kwargs.get("cash_sweep"):
        raise ValueError("the tranche book is scored ex-sweep (alpha); add the sweep to the combined book instead")
    subs = tranche_kwargs(kwargs, tranches)
    base_extra = dict(kwargs.get("kill_switch_extra_returns") or {})
    first = [simulate(frame, **sub) for sub in subs]
    results = first
    if kwargs.get("kill_switch_config"):
        returns = [dict(zip(result.per_date, result.per_date_net_return)) for result in first]
        results = []
        for index, sub in enumerate(subs):
            extra = dict(base_extra)
            for other, series in enumerate(returns):
                if other == index:
                    continue
                for date, value in series.items():
                    extra[date] = extra.get(date, 0.0) + value
            results.append(simulate(frame, **dict(sub, kill_switch_extra_returns=extra)))
    return combine_tranche_results(results, trading_days_per_year=trading_days_per_year)


def combine_tranche_results(results: list[RankBookSimulationResult], *, trading_days_per_year: int = 252) -> RankBookSimulationResult:
    """One result for the summed tranche book: per-date net returns added, Sharpe / drawdown / totals recomputed from the
    sum, turnover / cost / counts added, exposures added, per-component returns added by name."""
    dates = sorted({date for result in results for date in result.per_date})
    by_tranche = [dict(zip(result.per_date, result.per_date_net_return)) for result in results]
    net = np.asarray([sum(series.get(date, 0.0) for series in by_tranche) for date in dates], dtype=float)
    cumulative = np.cumprod(1.0 + net) if len(net) else np.asarray([1.0])
    peak = np.maximum.accumulate(cumulative)
    std = float(net.std(ddof=1)) if len(net) > 1 else 0.0
    sharpe = float(net.mean() / std * math.sqrt(trading_days_per_year)) if std > 0 else 0.0
    components: dict[str, dict[str, float]] = {}
    for result in results:
        for name, series in (result.per_date_component_returns or {}).items():
            target = components.setdefault(name, {})
            for date, value in series.items():
                target[date] = target.get(date, 0.0) + value
    locked = sorted({date for result in results for date in result.kill_switch_locked_date_list})
    veto_reasons: dict[str, int] = {}
    for result in results:
        for reason, count in result.veto_reasons.items():
            veto_reasons[reason] = veto_reasons.get(reason, 0) + count
    return replace(
        results[0],
        net_sharpe=sharpe, gross_sharpe=sharpe,
        net_total_return=float(cumulative[-1] - 1.0), gross_total_return=float(cumulative[-1] - 1.0),
        net_max_drawdown=float((cumulative / peak - 1.0).min()) if len(net) else 0.0,
        annualized_turnover=sum(result.annualized_turnover for result in results),
        cost_drag_annual_bps=sum(result.cost_drag_annual_bps for result in results),
        num_rebalances=sum(result.num_rebalances for result in results),
        num_dates_used=len(dates),
        mean_names_long=sum(result.mean_names_long for result in results),
        mean_names_short=sum(result.mean_names_short for result in results),
        per_date_net_return=[float(value) for value in net], per_date=dates,
        num_vetoed_rebalances=sum(result.num_vetoed_rebalances for result in results), veto_reasons=veto_reasons,
        num_kill_switch_locked_dates=len(locked), kill_switch_locked_date_list=locked,
        mean_gross_exposure=sum(result.mean_gross_exposure for result in results),
        mean_net_exposure=sum(result.mean_net_exposure for result in results),
        rebalance_log=[entry for result in results for entry in result.rebalance_log],
        weights_log=[], per_date_component_returns=components,
    )
