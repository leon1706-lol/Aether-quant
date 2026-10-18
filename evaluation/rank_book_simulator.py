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
    apply_class_weight_caps,
    build_book_raw_weights,
    build_rank_based_book,
    remember_formed_book,
)
from portfolio.book_neutrality import apply_book_neutrality
from portfolio.rank_signal import MAIN_RANK_GROUP, grouped_cross_sectional_rank_scores
from portfolio.sleeve_guard import evaluate_sleeve_guard, resolve_sleeve_guard_config
from risk.asset_class_router import asset_listed_on_venue
from risk.kill_switch import evaluate_kill_switch
from risk_controls import evaluate_non_model_exit, should_scale_position

DEFAULT_SECTOR_MAX_NET_WEIGHT = 0.05
# main.py's `_kill_switch_return_history` deque length.
_KILL_SWITCH_HISTORY_MAXLEN = 252
# NAV the per-name impact and minimum-commission terms assume when none is configured (config.json initial cash).
DEFAULT_ASSUMED_PORTFOLIO_VALUE_USD = 100_000.0


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
    # V5.7.0 - kill-switch lock days / frozen member decisions, 0 unless `kill_switch_config` is passed.
    num_kill_switch_locked_dates: int = 0
    num_kill_switch_frozen_decisions: int = 0
    kill_switch_locked_date_list: list = field(default_factory=list)
    # V5.8.0 - dates on which the sleeve guard kept the book flat (0 unless `sleeve_guard_config` is enabled).
    num_sleeve_guard_suspended_dates: int = 0
    # V5.7.0 - mean sum of |weight| and of signed weight over the dates used (NAV fractions), for sizing parity checks.
    mean_gross_exposure: float = 0.0
    mean_net_exposure: float = 0.0
    # V6.0.0: one {"date", "engaged", "reason", "locked"} per rebalance attempt (lean_calibration's decision agreement).
    rebalance_log: list = field(default_factory=list)
    # V6.0.0, with log_weights=True: the weights held after each date's rebalance, aligned with per_date.
    weights_log: list = field(default_factory=list)
    # V6.1.0: per-component net returns ({"main_book": {date: r}, "legacy": {date: r}}) when the legacy signal is modelled.
    per_date_component_returns: dict = field(default_factory=dict)

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


def _cap_new_entries(
    new_weights: dict[str, float], held_weights: dict[str, float], ranks: dict[str, float | None], max_positions: int
) -> dict[str, float]:
    """live's _apply_signal: a NEW entry is skipped once `max_positions` positions are open; held members always stay.
    Members are processed in conviction order (|rank - 0.5|, main.py's Pass 2 sort)."""
    kept = {symbol: weight for symbol, weight in new_weights.items() if symbol in held_weights}
    entries = sorted(
        (symbol for symbol in new_weights if symbol not in held_weights),
        key=lambda symbol: -abs(float(ranks.get(symbol) if ranks.get(symbol) is not None else 0.5) - 0.5),
    )
    room = max(0, max_positions - len(kept))
    for symbol in entries[:room]:
        kept[symbol] = new_weights[symbol]
    return kept


def _new_legacy_state() -> dict:
    return {"weights": {}, "history": [], "entry_index": {}, "peak": {}, "last_trade": {}, "band": {}, "previous": {}}


def _legacy_mark(state: dict, returns_today: dict[str, float]) -> float:
    """Return of the held legacy positions on a date that is not traded (a skipped weekend date)."""
    weights = state["history"][-1] if state["history"] else {}
    return sum(weight * float(returns_today.get(symbol, 0.0)) for symbol, weight in weights.items())


def _legacy_lagged_return(state: dict, date_returns: dict, entry_lag_bars: int, *, record: bool = False) -> float:
    """The legacy positions' return for this date: with an entry lag the weights held `entry_lag_bars` dates ago earn
    it (the order filled at the next open), exactly as the book. `record` appends today's weights to the history."""
    history = state["history"]
    if entry_lag_bars > 0:
        index = len(history) - entry_lag_bars
        weights = history[index] if index >= 0 else {}
    else:
        weights = state["weights"]
    value = sum(weight * float(date_returns.get(symbol, 0.0)) for symbol, weight in weights.items())
    if record:
        state["previous"] = weights
        history.append(dict(state["weights"]))
    return value


def _legacy_intraday(state: dict, eligible: pd.DataFrame, ticker_column: str, column: str) -> float:
    """The next session's open-to-close move earned by the legacy weights that changed today (next-open fill)."""
    current, previous = state["weights"], state["previous"]
    intraday = dict(zip(eligible[ticker_column].astype(str), eligible[column]))
    total = 0.0
    for symbol in set(current) | set(previous):
        delta = current.get(symbol, 0.0) - previous.get(symbol, 0.0)
        value = intraday.get(symbol)
        if delta != 0.0 and value == value and value is not None:
            total += delta * float(value)
    return total


def _legacy_step(state: dict, component: dict, *, eligible: pd.DataFrame, date: str, date_index: int, is_session: bool,
                 ticker_column: str, close_column: str, book_members: set[str], book_held: dict[str, float],
                 book_active: bool, kill_switch_locked: bool, candidate_metadata_by_ticker: dict,
                 cost_bps: float, commission_override, min_commission_usd_by_ticker: dict | None, pv_for_costs: float,
                 max_active_positions: int | None, cooldown_dates: int, resize_threshold_weight: float) -> tuple[float, float]:
    """One date of the legacy probability signal on non-members (main.py Pass 1c `_derive_signal` + Pass 2's non-member
    branch). Shared pure pieces: `data_pipeline.bar_synthesis.derive_signal` / `adaptive_sell_threshold` (the signal and
    its adaptive sell band, recorded for every symbol every date as Pass 1c does), `portfolio.legacy_sleeve.
    apply_legacy_sleeve_policy` (budget, per-name cap, no new entry while the book is vetoed), the member chain
    `component["weight_fn"]` (sizing, liquidity, net edge and the analyzer's verdict), `risk_controls.
    evaluate_non_model_exit` (age / trailing stop) and the live cooldown / position cap. A legacy "sell" closes a held
    position (analyzer Priority 0); the legacy signal never shorts (main.py's `already_flat`). Returns (cost, turnover)
    as NAV fractions."""
    from data_pipeline.bar_synthesis import adaptive_sell_threshold, derive_signal
    from portfolio.legacy_sleeve import apply_legacy_sleeve_policy

    signal = component["signal"]
    sleeve_config = component["sleeve_config"]
    probability_column = component["probability_column"]
    classes = set(component.get("asset_classes", ("equity", "crypto")))
    weight_fn = component.get("weight_fn")
    max_holding = component.get("max_holding_dates")
    stop_pct = component.get("trailing_stop_pct")
    weights = state["weights"]
    new_weights = dict(weights)
    if probability_column not in eligible.columns:
        return 0.0, 0.0
    rows = eligible.set_index(eligible[ticker_column].astype(str)).to_dict("index")
    for symbol in list(new_weights):  # backstop exits first, as Pass 2 checks them before the signal
        row = rows.get(symbol)
        close = float(row.get(close_column)) if row and row.get(close_column) == row.get(close_column) else None
        if close is None or close <= 0.0:
            continue
        reason = evaluate_non_model_exit(
            date_index, max_holding is not None, int(max_holding or 10**9), float(stop_pct) if stop_pct else 0.0,
            state["entry_index"].get(symbol, date_index), state["peak"].get(symbol), "long", close,
        ) if (max_holding is not None or stop_pct) else None
        if reason in ("max_holding_bars_reached", "trailing_stop_triggered"):
            new_weights.pop(symbol)
        elif state["peak"].get(symbol) is None or close > state["peak"][symbol]:
            state["peak"][symbol] = close
    gross_used = sum(abs(weight) for symbol, weight in new_weights.items() if symbol not in book_members)
    for symbol, row in rows.items():
        probability = row.get(probability_column)
        if probability is None or probability != probability:
            continue
        history = state["band"].setdefault(symbol, [])
        effective_sell = adaptive_sell_threshold(
            sell_threshold=signal["sell_threshold"], history=history, band_enabled=signal["band_enabled"],
            min_observations=signal["band_min_observations"], band_percentile=signal["band_percentile"],
        )
        name, confidence, target = derive_signal(
            float(probability), decision_threshold=signal["decision_threshold"], buy_threshold=signal["buy_threshold"],
            effective_sell_threshold=effective_sell, max_position_weight=signal["max_position_weight"],
        )
        history.append(float(probability))
        if len(history) > signal["band_window"]:
            del history[0]
        if not is_session or symbol in book_members or symbol in book_held:
            continue
        meta = candidate_metadata_by_ticker.get(symbol, {})
        if meta.get("asset_class") not in classes or not bool(meta.get("trading_eligible", True)):
            continue
        held = new_weights.get(symbol, 0.0)
        if name == "sell":
            if held:
                new_weights.pop(symbol)
            continue
        if name != "buy" or kill_switch_locked:
            continue  # analyzer Priority 1 blocks entries and resizes under the lock
        sized = float(weight_fn(symbol=symbol, date=date, base_weight=target, held_weight=held, confidence=confidence,
                                row=row)) if weight_fn else target
        if sized == held:
            continue
        policy = apply_legacy_sleeve_policy("buy", sized, False, held != 0.0, book_active, gross_used, sleeve_config)
        if policy["signal"] != "buy":
            continue
        wanted = float(policy["target_weight"])
        last = state["last_trade"].get(symbol)
        if held == 0.0:
            if cooldown_dates > 0 and last is not None and date_index - last < cooldown_dates:
                continue
            if max_active_positions is not None and len(new_weights) + len(book_held) >= int(max_active_positions):
                continue
            new_weights[symbol] = wanted
            gross_used = float(policy["sleeve_gross_used"])
        elif resize_threshold_weight <= 0.0 or should_scale_position(held, wanted, resize_threshold_weight):
            new_weights[symbol] = wanted
    cost, turnover = 0.0, 0.0
    for symbol in set(new_weights) | set(weights):
        delta = new_weights.get(symbol, 0.0) - weights.get(symbol, 0.0)
        if delta == 0.0:
            continue
        turnover += abs(delta)
        cost += abs(delta) * (cost_bps + commission_override(symbol)) / 1e4
        floor_usd = float((min_commission_usd_by_ticker or {}).get(symbol, 0.0))
        if floor_usd > 0.0:
            cost += max(0.0, floor_usd - abs(delta) * pv_for_costs * cost_bps / 1e4) / pv_for_costs
        state["last_trade"][symbol] = date_index
        if symbol not in new_weights:
            state["entry_index"].pop(symbol, None)
            state["peak"].pop(symbol, None)
        elif symbol not in weights:
            state["entry_index"][symbol] = date_index
    state["weights"] = new_weights
    return cost, turnover


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
    commission_bps_by_ticker: dict[str, float] | None = None,
    entry_veto_column: str | None = None,
    hysteresis_anchor_on_formed_book: bool | None = None,
    kill_switch_config: dict | None = None,
    kill_switch_sticky: bool = False,
    member_weight_fn=None,
    raw_weights_fn=None,
    impact_inputs_fn=None,
    min_commission_usd_by_ticker: dict[str, float] | None = None,
    rank_group_by_ticker: dict[str, str] | None = None,
    sleeve_guard_config: dict | None = None,
    venue_listing_dates: dict[str, dict] | None = None,
    class_weight_caps: dict[str, dict] | None = None,
    per_asset_class_slots: dict[str, tuple[int, int]] | None = None,
    rebalance_counter_start: int = 0,
    intraday_next_return_column: str | None = None,
    decision_overrides: dict[str, str] | None = None,
    log_weights: bool = False,
    rebalance_session_dates: set[str] | None = None,
    resize_threshold_weight: float = 0.0,
    trade_cooldown_dates: int = 0,
    trailing_stop_pct: float | None = None,
    close_column: str = "close",
    mid_cycle_member_updates: bool = False,
    accrue_skipped_dates: bool = False,
    kill_switch_extra_returns: dict[str, float] | None = None,
    legacy_component: dict | None = None,
    max_active_positions: int | None = None,
    cash_sweep: dict | None = None,
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

    V5.7.0 live mechanisms, all off by default (`evaluation.live_parity` builds them from the live config):
    - `hysteresis_anchor_on_formed_book` (default: follows `hold_positions_on_veto`) separates the anchor choice from
      the hold choice, which the lever attribution had confounded.
    - `kill_switch_config` (`phase_v2.risk.kill_switch`): `risk.kill_switch.evaluate_kill_switch` runs every date on the
      simulated net returns. A locked rebalance freezes member positions (analyzer Priority 1: entries and resizes become
      `reduce_risk`, exits still pass). `kill_switch_sticky=False` mirrors the backtest bypass that clears the lock each
      session, so the lock is re-derived every date; True latches the first trip for the rest of the run.
    - `member_weight_fn(symbol=, date=, base_weight=, held_weight=, predicted_rank=, row=)` returns the final target
      weight of one book member (live sizing chain, liquidity, net-edge gate; hold = return `held_weight`).
    - `raw_weights_fn(allocations, date)` replaces `build_book_raw_weights` (HRP).
    - `impact_inputs_fn(symbol, date) -> (daily_volatility, adv_usd) | None` charges the Almgren impact per name on its
      own traded notional; `min_commission_usd_by_ticker` tops up each traded name to the broker's dollar floor.

    V5.8.0, both off by default:
    - `rank_group_by_ticker` ({ticker: group}): percentiles are taken within each rank group and the spread gate reads
      only the main group's raw scores (main.py with `rank_signal.grouped_normalization`).
    - `sleeve_guard_config` (`phase_v2.sleeve_guards.<sleeve>`): `portfolio.sleeve_guard.evaluate_sleeve_guard` on this
      book's own simulated net returns (NAV fractions, nav=1.0); while suspended the book is flat and does not rebalance.
    - `class_weight_caps` (`portfolio.book_construction.resolve_class_weight_caps`): per-name / class-gross caps applied to the
      neutrality-adjusted weights before the member sizing chain, as main.py does (`phase_v2.class_weight_caps`).
    - `venue_listing_dates` (`risk.asset_class_router.load_venue_listing_dates`): a pair is not a candidate before its
      exchange listing date or inside a suspension (main.py with `venue_listing_guard.enabled`).

    V6.0.0, all off by default (todo lead 2, the Lean calibration):
    - `per_asset_class_slots` ({class: (top_n, bottom_n)}): the class-neutral book main.py already builds
      (`phase_v2.portfolio_book.per_asset_class_slots`), passed to the same `build_rank_based_book`.
    - `rebalance_counter_start`: the cadence counter's starting value. main.py counts equity sessions from the start of
      its warm-up, so a live run rebalances on a phase the split's first date does not share.
    - `intraday_next_return_column` (with `entry_lag_bars=1`): a market order decided on date D fills at the NEXT open,
      so the next session's open-to-close move is earned by the NEW weights, not the old ones; the column holds each
      row's next-session close/open - 1 (`evaluation.live_parity.add_next_intraday_return`).
    - `decision_overrides` ({date: "engaged" | "vetoed" | "locked"}): replays live's gate decisions instead of
      computing them (diagnostic: separates the gates' reading from execution).
    - `log_weights`: keep the post-rebalance weights of every date (`weights_log`) for a position-level comparison.
    - `rebalance_session_dates`: only these dates count toward the cadence and may rebalance or retry (main.py's
      `bar_index` advances on equity sessions only; an equity holiday with enough crypto/forex rows was a cadence step
      offline and none live). Returns still accrue on every date.
    - `resize_threshold_weight`: a held member keeps its weight unless the new target moves it by at least this much
      (`risk_controls.should_scale_position`, main.py's `position_scaling.rebalance_threshold_weight`).
    - `trade_cooldown_dates`: no new entry or direction flip within this many session dates of the symbol's last trade
      (a same-side resize is gated by the threshold alone); exits (the book's rotation, the age exit, the trailing stop)
      are exempt, as live's `is_cooldown_exempt` (`trade_cooldown_bars`).
    - `trailing_stop_pct`: live's trailing stop on daily closes (`risk_controls.evaluate_non_model_exit`), from the best
      close since entry, direction-aware.

    V6.1.0, all off by default (rule R-CAL2: each one replicates a main.py mechanism):
    - `mid_cycle_member_updates`: between rebalances live re-runs every member of the last ENGAGED book through the
      member chain on every session (`book_allocations = self._last_book_allocations`), so a member blocked on the
      rebalance day (kill-switch lock, net edge, cooldown) or closed by the age exit / trailing stop is entered as soon as
      it passes, and a held member is resized when its target moves past the threshold. After a veto there is no book
      (live's `_last_book_allocations` is empty) and nothing happens until the next engaged rebalance.
    - `accrue_skipped_dates`: a date with too few rows to rank (weekends: crypto only) still earns the held positions'
      return, folded into the previous date's return (live marks crypto every calendar day).
    - `kill_switch_extra_returns` ({date: NAV return}): P&L outside this simulation (sleeves, crypto outside the book)
      that live's kill switch reads, because it watches the whole portfolio value.
    - `legacy_component`: the legacy probability signal on non-members (main.py Pass 2 non-member branch), see
      `_legacy_step`; its P&L joins the returns and the kill switch and is reported per component.
    - `max_active_positions`: live's position count limit (`phase9.portfolio.max_active_positions`): a new entry is not
      taken while that many positions (book + legacy) are open; members are filled in conviction order.
    Exit costs (age exit, trailing stop, sleeve guard) are now part of the date's cost on a rebalance date too.

    V6.2.0, off by default: `cash_sweep` ({"returns_by_date": {date: T-bill ETF return}, "config":
    `portfolio.cash_sweep.resolve_cash_sweep_config`, "security_type_by_ticker", "book_gross_cap", "max_short_exposure",
    "other_budget", "neutral_budget", "min_commission_usd"}) holds idle NAV in the T-bill ETF as main.py does: sized at the end of each date
    from the book and legacy weights just decided and the next date's possible orders (`portfolio.cash_sweep`), filled a
    date later, earning the ETF's return as a third component (`per_date_component_returns["cash_sweep"]`). The kill
    switch reads the returns without it when `config["exclude_from_risk_controls"]` (live's strategy value ex-sweep).
    """
    sector_by_ticker = sector_by_ticker or {}
    candidate_metadata_by_ticker = candidate_metadata_by_ticker or {}
    as_live = bool(hold_positions_on_veto)
    anchor_on_formed_book = as_live if hysteresis_anchor_on_formed_book is None else bool(hysteresis_anchor_on_formed_book)
    kill_switch_active = bool(kill_switch_config) and bool((kill_switch_config or {}).get("enabled", False))
    kill_switch_returns: list[float] = []
    kill_switch_latched = False
    kill_switch_previous_drawdown: float | None = None
    kill_switch_consecutive_losses = 0
    num_kill_switch_locked_dates = 0
    num_kill_switch_frozen_decisions = 0
    kill_switch_locked_dates: list[str] = []
    pv_for_costs = assumed_portfolio_value_usd if assumed_portfolio_value_usd > 0 else DEFAULT_ASSUMED_PORTFOLIO_VALUE_USD
    formed_book: dict[str, BookAllocation] = {}
    last_rebalance_vetoed = False
    num_vetoed_rebalances = 0
    veto_reasons: dict[str, int] = {}
    entry_date_index_by_ticker: dict[str, int] = {}
    last_trade_index_by_ticker: dict[str, int] = {}
    peak_close_by_ticker: dict[str, float] = {}
    rebalance_log: list[dict] = []
    weights_log: list[dict] = []
    working = frame.dropna(subset=[prediction_column]).copy()
    unique_dates = sorted(working[date_column].unique())
    guard = resolve_sleeve_guard_config(sleeve_guard_config)
    guard_suspended_until: int | None = None
    num_sleeve_guard_suspended_dates = 0
    guard_resume_pending = False

    held_weights: dict[str, float] = {}
    held_allocations: dict[str, BookAllocation] = {}
    held_days_by_ticker: dict[str, int] = {}
    # V6.1.0 - live's book between rebalances: the last rebalance's allocations (empty after a veto), their weights before
    # the member chain (main.py's _book_target_weights) and the ranks the book was formed on.
    active_allocations: dict[str, BookAllocation] = {}
    active_base_weights: dict[str, float] = {}
    active_ranks: dict[str, float] = {}
    legacy_state = _new_legacy_state() if legacy_component else None
    book_component_returns: list[float] = []
    legacy_component_returns: list[float] = []
    kill_switch_cumprod = 1.0
    kill_switch_peak = 1.0
    sweep = cash_sweep or None
    sweep_weight = 0.0
    sweep_component_returns: list[float] = []

    gross_returns: list[float] = []
    net_returns: list[float] = []
    per_date_used: list = []
    names_long_series: list[int] = []
    names_short_series: list[int] = []
    gross_exposure_series: list[float] = []
    net_exposure_series: list[float] = []
    total_turnover = 0.0
    total_cost_return = 0.0
    num_rebalances = 0
    rebalance_counter = int(rebalance_counter_start)
    # V5.2.1 - one held_weights snapshot per processed date, appended AFTER
    # that date's own rebalance (if any) - see entry_lag_bars's docstring.
    weights_history: list[dict[str, float]] = []

    net_cumprod = 1.0
    gross_cumprod = 1.0
    net_running_peak = 1.0
    net_max_drawdown = 0.0

    def _commission_override_delta(symbol: str) -> float:
        # Per-ticker fee (e.g. a crypto exchange percentage) replaces the generic commission for that
        # ticker; 0.0 for everything else, so books without overrides cost exactly what they always did.
        if not commission_bps_by_ticker or symbol not in commission_bps_by_ticker:
            return 0.0
        return float(commission_bps_by_ticker[symbol]) - commission_bps

    for date in unique_dates:
        date_frame = working[working[date_column] == date]
        eligible = date_frame.dropna(subset=[forward_return_column])
        if len(eligible) < min_universe_size:
            if accrue_skipped_dates and net_returns:
                returns_today = dict(zip(eligible[ticker_column].astype(str), eligible[forward_return_column]))
                book_extra = sum(weight * float(returns_today.get(symbol, 0.0)) for symbol, weight in (weights_history[-1] if weights_history else {}).items())
                legacy_extra = _legacy_mark(legacy_state, returns_today) if legacy_state is not None else 0.0
                extra = book_extra + legacy_extra
                if extra:
                    previous = net_returns[-1]
                    net_cumprod = net_cumprod / (1.0 + previous) * (1.0 + previous + extra)
                    gross_cumprod = gross_cumprod / (1.0 + gross_returns[-1]) * (1.0 + gross_returns[-1] + extra)
                    net_returns[-1] = previous + extra
                    gross_returns[-1] += extra
                    book_component_returns[-1] += book_extra
                    legacy_component_returns[-1] += legacy_extra
                    net_running_peak = max(net_running_peak, net_cumprod)
                    net_max_drawdown = min(net_max_drawdown, net_cumprod / net_running_peak - 1.0)
                    if kill_switch_active and kill_switch_returns:
                        previous_portfolio = kill_switch_returns[-1]
                        kill_switch_cumprod = kill_switch_cumprod / (1.0 + previous_portfolio) * (1.0 + previous_portfolio + extra)
                        kill_switch_peak = max(kill_switch_peak, kill_switch_cumprod)
                        kill_switch_previous_drawdown = kill_switch_cumprod / kill_switch_peak - 1.0
                        kill_switch_returns[-1] = previous_portfolio + extra
            continue

        is_session = rebalance_session_dates is None or str(date) in rebalance_session_dates
        is_rebalance = is_session and (rebalance_counter % max(1, rebalance_every_bars)) == 0
        if retry_rebalance_after_veto and last_rebalance_vetoed and is_session:
            is_rebalance = True
        if decision_overrides is not None:
            is_rebalance = str(date) in decision_overrides  # replay: live's own rebalance dates
        if is_session:
            rebalance_counter += 1
        cost_this_date = 0.0
        date_returns = dict(zip(eligible[ticker_column], eligible[forward_return_column]))

        kill_switch_locked = False
        if kill_switch_active:
            # main.py's _refresh_risk_state() runs at the start of the tick on the portfolio value that already includes
            # today's price move on yesterday's positions; with entry_lag_bars > 0 that move is known before deciding.
            window = list(kill_switch_returns)
            today_return = None
            if entry_lag_bars > 0:
                lag_index = len(weights_history) - entry_lag_bars
                lagged_weights = weights_history[lag_index] if lag_index >= 0 else {}
                today_return = sum(weight * float(date_returns.get(symbol, 0.0)) for symbol, weight in lagged_weights.items())
                if legacy_state is not None:
                    today_return += _legacy_lagged_return(legacy_state, date_returns, entry_lag_bars)
                today_return += float((kill_switch_extra_returns or {}).get(str(date), 0.0))
                window.append(today_return)
            drawdown_velocity = None
            if kill_switch_previous_drawdown is not None:
                value_now = kill_switch_cumprod * (1.0 + (today_return or 0.0))
                drawdown_now = value_now / max(kill_switch_peak, value_now) - 1.0
                drawdown_velocity = abs(drawdown_now) - abs(kill_switch_previous_drawdown)
            decision = evaluate_kill_switch(
                {
                    "recent_bar_returns": window[-_KILL_SWITCH_HISTORY_MAXLEN:],
                    "drawdown_velocity_pct_per_bar": drawdown_velocity,
                    "live_rank_ic": None,
                    "consecutive_losses": kill_switch_consecutive_losses,
                    "slippage_divergence_bps": None,
                    "model_age_days": None,
                    "reconciliation_breach": False,
                },
                kill_switch_config,
            )
            if decision.tripped and kill_switch_sticky:
                kill_switch_latched = True
            kill_switch_locked = decision.tripped or kill_switch_latched
            if kill_switch_locked:
                num_kill_switch_locked_dates += 1
                kill_switch_locked_dates.append(str(date))

        # V5.5.0 - live's `exits.max_holding_bars` age exit (as-live only).
        if max_holding_dates is not None and held_weights:
            date_index = rebalance_counter - 1
            expired = [
                symbol
                for symbol in held_weights
                if date_index - entry_date_index_by_ticker.get(symbol, date_index) >= max_holding_dates
            ]
            if expired:
                exit_cost = (
                    sum(abs(held_weights[symbol]) for symbol in expired) * (cost_bps_per_side + commission_bps) / 1e4
                    + sum(abs(held_weights[symbol]) * _commission_override_delta(symbol) for symbol in expired) / 1e4
                )
                cost_this_date += exit_cost
                total_cost_return += exit_cost
                total_turnover += sum(abs(held_weights[symbol]) for symbol in expired)
                held_weights = {symbol: weight for symbol, weight in held_weights.items() if symbol not in expired}
                held_allocations = {
                    symbol: allocation for symbol, allocation in held_allocations.items() if symbol not in expired
                }
                for symbol in expired:
                    entry_date_index_by_ticker.pop(symbol, None)
                    peak_close_by_ticker.pop(symbol, None)
                    last_trade_index_by_ticker[symbol] = date_index

        if trailing_stop_pct is not None and held_weights and close_column in eligible.columns:
            date_index = rebalance_counter - 1
            closes_today = dict(zip(eligible[ticker_column].astype(str), eligible[close_column]))
            stopped = []
            for symbol, weight in held_weights.items():
                close = closes_today.get(symbol)
                if close is None or not close == close or close <= 0.0:
                    continue
                peak = peak_close_by_ticker.get(symbol)
                reason = evaluate_non_model_exit(
                    date_index, True, 10**9, float(trailing_stop_pct), entry_date_index_by_ticker.get(symbol, date_index),
                    peak, "long" if weight > 0 else "short", float(close),
                )
                if reason == "trailing_stop_triggered":
                    stopped.append(symbol)
                elif peak is None or (weight > 0 and close > peak) or (weight < 0 and close < peak):
                    peak_close_by_ticker[symbol] = float(close)
            if stopped:
                exit_cost = (
                    sum(abs(held_weights[symbol]) for symbol in stopped) * (cost_bps_per_side + commission_bps) / 1e4
                    + sum(abs(held_weights[symbol]) * _commission_override_delta(symbol) for symbol in stopped) / 1e4
                )
                cost_this_date += exit_cost
                total_cost_return += exit_cost
                total_turnover += sum(abs(held_weights[symbol]) for symbol in stopped)
                held_weights = {symbol: weight for symbol, weight in held_weights.items() if symbol not in stopped}
                held_allocations = {symbol: allocation for symbol, allocation in held_allocations.items() if symbol not in stopped}
                for symbol in stopped:
                    entry_date_index_by_ticker.pop(symbol, None)
                    peak_close_by_ticker.pop(symbol, None)
                    last_trade_index_by_ticker[symbol] = date_index

        if guard.enabled:
            guard_decision = evaluate_sleeve_guard(
                net_returns, 1.0, guard, current_bar=rebalance_counter - 1, suspended_until_bar=guard_suspended_until
            )
            guard_suspended_until = guard_decision["suspended_until_bar"]
            if not guard_decision["active"]:
                num_sleeve_guard_suspended_dates += 1
                if held_weights:
                    flattened = sum(abs(weight) for weight in held_weights.values())
                    exit_cost = flattened * (cost_bps_per_side + commission_bps) / 1e4 + sum(
                        abs(weight) * _commission_override_delta(symbol) for symbol, weight in held_weights.items()
                    ) / 1e4
                    cost_this_date += exit_cost
                    total_cost_return += exit_cost
                    total_turnover += flattened
                    held_weights = {}
                    held_allocations = {}
                    entry_date_index_by_ticker.clear()
                is_rebalance = False
                active_allocations, active_base_weights, active_ranks = {}, {}, {}
                guard_resume_pending = True
            elif guard_resume_pending:
                is_rebalance = True  # re-form the book on the first date the guard lets it trade again
                guard_resume_pending = False

        mid_cycle = bool(mid_cycle_member_updates and not is_rebalance and is_session and active_allocations)
        if is_rebalance or mid_cycle:
            if is_rebalance:
                raw_scores_by_ticker = {
                    str(ticker): float(rank) for ticker, rank in zip(eligible[ticker_column], eligible[prediction_column])
                }
                candidate_ranks = (
                    grouped_cross_sectional_rank_scores(raw_scores_by_ticker, rank_group_by_ticker)
                    if normalize_to_percentile
                    else raw_scores_by_ticker
                )
                spread_scores = raw_scores_by_ticker
                if rank_group_by_ticker:
                    spread_scores = {
                        ticker: score
                        for ticker, score in raw_scores_by_ticker.items()
                        if rank_group_by_ticker.get(ticker, MAIN_RANK_GROUP) == MAIN_RANK_GROUP
                    }
                book_candidates = {
                    ticker: {
                        "predicted_rank_20d": float(rank),
                        "trading_eligible": bool(candidate_metadata_by_ticker.get(ticker, {}).get("trading_eligible", True))
                        and asset_listed_on_venue(ticker, str(date), venue_listing_dates),
                        "asset_class": candidate_metadata_by_ticker.get(ticker, {}).get("asset_class"),
                    }
                    for ticker, rank in candidate_ranks.items()
                }
                gate_result = rolling_ic_gate_fn(str(date)) if rolling_ic_gate_fn is not None else None
                override = (decision_overrides or {}).get(str(date))
                if override is not None:
                    # a locked date still forms the book; the kill switch then freezes its entries and resizes
                    engaged = override in ("engaged", "locked")
                    gate_result = {"engaged": True, "reason": None} if engaged else {"engaged": False, "reason": "replayed_veto"}
                    kill_switch_locked = override == "locked"
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
                    min_rank_confidence_spread=0.0 if override in ("engaged", "locked") else min_rank_confidence_spread,
                    per_asset_class_slots=per_asset_class_slots or None,
                    previous_allocations=(formed_book if anchor_on_formed_book else held_allocations) or None,
                    hysteresis_rank_margin=hysteresis_rank_margin,
                    spread_check_ranks=spread_scores if normalize_to_percentile else None,
                    rolling_ic_gate_result=gate_result,
                    veto_reason_out=veto_reason_out,
                )
                last_rebalance_vetoed = not allocations
                if not allocations:
                    num_vetoed_rebalances += 1
                    veto_key = veto_reason_out.get("reason", "empty_book")
                    veto_reasons[veto_key] = veto_reasons.get(veto_key, 0) + 1
                formed_book = remember_formed_book(formed_book, allocations)
                rebalance_log.append(
                    {"date": str(date), "engaged": bool(allocations), "reason": None if allocations else veto_reason_out.get("reason", "empty_book"),
                     "locked": bool(kill_switch_locked)}
                )

                if not allocations and hold_positions_on_veto:
                    # Live parity: a vetoed rebalance leaves the existing book
                    # untouched (no turnover, no cost, no new positions).
                    new_weights = dict(held_weights)
                elif allocations:
                    long_symbols = [symbol for symbol, allocation in allocations.items() if allocation.role == "long"]
                    short_symbols = [symbol for symbol, allocation in allocations.items() if allocation.role == "short"]
                    raw_weights: dict[str, float] = {}
                    if raw_weights_fn is not None:
                        raw_weights = raw_weights_fn(allocations, str(date))
                    elif live_weighting:
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
                    if class_weight_caps:
                        new_weights = apply_class_weight_caps(
                            new_weights,
                            {ticker: meta.get("asset_class") for ticker, meta in candidate_metadata_by_ticker.items()},
                            class_weight_caps,
                        )
                    held_allocations = {
                        symbol: replace(allocation, target_weight=new_weights.get(symbol, 0.0))
                        for symbol, allocation in allocations.items()
                    }
                else:
                    new_weights = {}
                    held_allocations = {}
                active_allocations = dict(allocations) if allocations else {}
                active_base_weights = dict(new_weights) if allocations else {}
                active_ranks = {symbol: candidate_ranks.get(symbol) for symbol in allocations} if allocations else {}
            else:
                # live between rebalances: the same members, the same pre-chain weights, today's rows
                allocations = active_allocations
                candidate_ranks = active_ranks
                new_weights = dict(active_base_weights)
                override = None

            if member_weight_fn is not None and new_weights and allocations:
                rows_by_ticker = eligible.set_index(ticker_column).to_dict("index")
                adjusted_weights = {
                    symbol: float(
                        member_weight_fn(
                            symbol=symbol,
                            date=str(date),
                            base_weight=weight,
                            held_weight=held_weights.get(symbol, 0.0),
                            predicted_rank=candidate_ranks.get(symbol),
                            row=rows_by_ticker.get(symbol, {}),
                        )
                    )
                    for symbol, weight in new_weights.items()
                }
                new_weights = {symbol: weight for symbol, weight in adjusted_weights.items() if weight != 0.0}
                held_allocations = {symbol: allocation for symbol, allocation in held_allocations.items() if symbol in new_weights}

            if entry_veto_column and entry_veto_column in eligible.columns and new_weights:
                # Live's analyzer Priority 3 (elevated topology volatility) turns a NEW book entry into
                # reduce_risk; positions already held are not force-closed by it.
                vetoed_entries = {
                    str(ticker)
                    for ticker, flag in zip(eligible[ticker_column], eligible[entry_veto_column])
                    if flag == flag and float(flag) > 0.5
                }
                new_weights = {
                    symbol: weight
                    for symbol, weight in new_weights.items()
                    if symbol in held_weights or symbol not in vetoed_entries
                }
                held_allocations = {symbol: allocation for symbol, allocation in held_allocations.items() if symbol in new_weights}

            if kill_switch_locked and new_weights:
                # analyzer Priority 1: with the lock on, a member's entry or resize becomes reduce_risk (no trade);
                # only the exits (names the book dropped, handled by the missing keys) go through.
                frozen = {symbol: held_weights[symbol] for symbol in new_weights if symbol in held_weights}
                if allocations and is_rebalance:
                    num_kill_switch_frozen_decisions += len(new_weights)
                new_weights = frozen
                held_allocations = {symbol: allocation for symbol, allocation in held_allocations.items() if symbol in new_weights}

            if (resize_threshold_weight > 0.0 or trade_cooldown_dates > 0) and new_weights:
                date_index = rebalance_counter - 1
                adjusted = dict(new_weights)
                for symbol, target in new_weights.items():
                    held = held_weights.get(symbol, 0.0)
                    if target == held:
                        continue
                    same_side_hold = held != 0.0 and (held > 0) == (target > 0)
                    if same_side_hold and resize_threshold_weight > 0.0 and not should_scale_position(held, target, resize_threshold_weight):
                        adjusted[symbol] = held  # live: a trivial resize is not traded
                        continue
                    last = last_trade_index_by_ticker.get(symbol)
                    if not same_side_hold and trade_cooldown_dates > 0 and last is not None and date_index - last < trade_cooldown_dates:
                        adjusted[symbol] = held  # live: inside the cooldown a new entry or a flip is not traded
                new_weights = {symbol: weight for symbol, weight in adjusted.items() if weight != 0.0}
                held_allocations = {symbol: allocation for symbol, allocation in held_allocations.items() if symbol in new_weights}

            if max_active_positions is not None and new_weights:
                new_weights = _cap_new_entries(
                    new_weights, held_weights, candidate_ranks,
                    int(max_active_positions) - (len(legacy_state["weights"]) if legacy_state is not None else 0),
                )
                held_allocations = {symbol: allocation for symbol, allocation in held_allocations.items() if symbol in new_weights}

            for symbol in set(new_weights) | set(held_weights):
                if new_weights.get(symbol, 0.0) != held_weights.get(symbol, 0.0):
                    last_trade_index_by_ticker[symbol] = rebalance_counter - 1
                if symbol not in new_weights:
                    peak_close_by_ticker.pop(symbol, None)
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
            turnover_cost = turnover_this_rebalance * (cost_bps_per_side + commission_bps) / 1e4
            turnover_cost += sum(abs(delta) * _commission_override_delta(symbol) for symbol, delta in deltas_by_symbol.items()) / 1e4
            # V5.2.1 (development/Problems.md) - honestly-approximate
            # per-order minimum-commission floor, see this function's own
            # docstring. No-op (0.0) unless both inputs are configured.
            if min_commission_usd > 0.0 and assumed_portfolio_value_usd > 0.0:
                names_traded = sum(1 for delta in deltas_by_symbol.values() if delta != 0.0)
                turnover_cost += names_traded * min_commission_usd / assumed_portfolio_value_usd
            cost_this_date += turnover_cost
            total_cost_return += turnover_cost
            if min_commission_usd_by_ticker:
                # Top each traded name up to the broker's dollar floor: the rate leg is already in commission_bps*.
                floor_topup = 0.0
                for symbol, delta in deltas_by_symbol.items():
                    floor_usd = float(min_commission_usd_by_ticker.get(symbol, 0.0))
                    if floor_usd <= 0.0 or delta == 0.0:
                        continue
                    rate_bps = float(commission_bps_by_ticker.get(symbol, commission_bps)) if commission_bps_by_ticker else commission_bps
                    rate_usd = abs(delta) * pv_for_costs * rate_bps / 1e4
                    floor_topup += max(0.0, floor_usd - rate_usd) / pv_for_costs
                cost_this_date += floor_topup
                total_cost_return += floor_topup

            # V5.4.2 - Almgren-style sqrt impact (optional, off by default). Impact is a cost RATE on the notional
            # traded, so the NAV cost is rate x |delta weight|; V5.7.0 fixed the old date-level estimate, which
            # charged the rate itself as a fraction of NAV on a $1M book.
            if impact_model_config and impact_model_config.get("enabled", False):
                from evaluation.impact_model import compute_sqrt_impact_bps

                eta = float(impact_model_config.get("eta", 0.5))
                impact_cost = 0.0
                if impact_inputs_fn is not None:
                    for symbol, delta in deltas_by_symbol.items():
                        inputs = impact_inputs_fn(symbol, str(date))
                        if inputs is None or delta == 0.0:
                            continue
                        symbol_vol, symbol_adv = inputs
                        impact_cost += abs(delta) * compute_sqrt_impact_bps(
                            trade_size_fraction=abs(delta),
                            daily_volatility=float(symbol_vol),
                            avg_daily_dollar_volume=float(symbol_adv),
                            portfolio_value=pv_for_costs,
                            eta=eta,
                        ) / 1e4
                else:
                    impact_bps = compute_sqrt_impact_bps(
                        trade_size_fraction=turnover_this_rebalance,
                        daily_volatility=float(impact_model_config.get("daily_volatility", 0.02)),
                        avg_daily_dollar_volume=float(impact_model_config.get("avg_daily_dollar_volume", 50_000_000)),
                        portfolio_value=pv_for_costs,
                        eta=eta,
                    )
                    impact_cost = turnover_this_rebalance * impact_bps / 1e4
                cost_this_date += impact_cost
                total_cost_return += impact_cost

            if is_rebalance:
                num_rebalances += 1
            held_weights = new_weights

        legacy_net_return = 0.0
        if legacy_state is not None:
            legacy_cost, legacy_turnover = _legacy_step(
                legacy_state, legacy_component, eligible=eligible, date=str(date), date_index=rebalance_counter - 1,
                is_session=is_session, ticker_column=ticker_column, close_column=close_column,
                book_members=set(active_allocations) | set(formed_book), book_held=held_weights,
                book_active=bool(active_allocations), kill_switch_locked=kill_switch_locked,
                candidate_metadata_by_ticker=candidate_metadata_by_ticker,
                cost_bps=cost_bps_per_side + commission_bps, commission_override=_commission_override_delta,
                min_commission_usd_by_ticker=min_commission_usd_by_ticker, pv_for_costs=pv_for_costs,
                max_active_positions=max_active_positions, cooldown_dates=trade_cooldown_dates,
                resize_threshold_weight=resize_threshold_weight,
            )
            total_turnover += legacy_turnover
            total_cost_return += legacy_cost
            legacy_net_return = _legacy_lagged_return(legacy_state, date_returns, entry_lag_bars, record=True) - legacy_cost
            if intraday_next_return_column and entry_lag_bars == 1 and intraday_next_return_column in eligible.columns:
                legacy_net_return += _legacy_intraday(legacy_state, eligible, ticker_column, intraday_next_return_column)

        for symbol in held_weights:
            held_days_by_ticker[symbol] = held_days_by_ticker.get(symbol, 0) + 1
        names_long_series.append(sum(1 for weight in held_weights.values() if weight > 0.0))
        names_short_series.append(sum(1 for weight in held_weights.values() if weight < 0.0))

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
        if intraday_next_return_column and entry_lag_bars == 1 and intraday_next_return_column in eligible.columns:
            # The order filled at the next open: the next session's open-to-close move belongs to the new weights.
            changed = {
                symbol: held_weights.get(symbol, 0.0) - effective_weights.get(symbol, 0.0)
                for symbol in set(held_weights) | set(effective_weights)
            }
            intraday = dict(zip(eligible[ticker_column], eligible[intraday_next_return_column]))
            bar_return += sum(
                delta * float(intraday.get(symbol, 0.0) or 0.0)
                for symbol, delta in changed.items()
                if delta != 0.0 and intraday.get(symbol) == intraday.get(symbol)
            )
        net_return = bar_return - cost_this_date
        book_component_returns.append(net_return)
        legacy_component_returns.append(legacy_net_return)
        if legacy_state is not None:
            net_return += legacy_net_return
            bar_return += legacy_net_return
        strategy_net_return = net_return
        if sweep is not None:
            sweep_net, sweep_weight = _cash_sweep_step(
                sweep, sweep_weight, date=str(date), is_session=is_session, book_weights=held_weights,
                legacy_weights=legacy_state["weights"] if legacy_state is not None else {},
                rebalance_next=(not active_allocations) or (rebalance_counter % max(1, rebalance_every_bars)) == 0,
                formed_weights=active_base_weights, pv_for_costs=pv_for_costs,
            )
            sweep_component_returns.append(sweep_net)
            net_return += sweep_net
            bar_return += sweep_net
            total_cost_return += sweep.get("_last_cost", 0.0)
            if not sweep["config"]["exclude_from_risk_controls"]:
                strategy_net_return = net_return
        gross_exposure_series.append(sum(abs(weight) for weight in effective_weights.values()))
        net_exposure_series.append(sum(effective_weights.values()))

        gross_returns.append(bar_return)
        net_returns.append(net_return)
        per_date_used.append(str(date))
        weights_history.append(dict(held_weights))
        if log_weights:
            weights_log.append(dict(held_weights))
        gross_cumprod *= 1.0 + bar_return
        net_cumprod *= 1.0 + net_return
        net_running_peak = max(net_running_peak, net_cumprod)
        net_max_drawdown = min(net_max_drawdown, net_cumprod / net_running_peak - 1.0)
        if kill_switch_active:
            # live's kill switch watches the whole portfolio: this simulation plus anything modelled outside it
            portfolio_return = strategy_net_return + float((kill_switch_extra_returns or {}).get(str(date), 0.0))
            kill_switch_returns.append(portfolio_return)
            kill_switch_cumprod *= 1.0 + portfolio_return
            kill_switch_peak = max(kill_switch_peak, kill_switch_cumprod)
            kill_switch_previous_drawdown = kill_switch_cumprod / kill_switch_peak - 1.0
            kill_switch_consecutive_losses = kill_switch_consecutive_losses + 1 if portfolio_return < 0.0 else 0

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
        num_kill_switch_locked_dates=num_kill_switch_locked_dates,
        num_kill_switch_frozen_decisions=num_kill_switch_frozen_decisions,
        kill_switch_locked_date_list=kill_switch_locked_dates,
        num_sleeve_guard_suspended_dates=num_sleeve_guard_suspended_dates,
        mean_gross_exposure=float(np.mean(gross_exposure_series)) if gross_exposure_series else 0.0,
        mean_net_exposure=float(np.mean(net_exposure_series)) if net_exposure_series else 0.0,
        rebalance_log=rebalance_log,
        weights_log=weights_log,
        per_date_component_returns=(
            ({"main_book": dict(zip(per_date_used, book_component_returns)), "legacy": dict(zip(per_date_used, legacy_component_returns))}
             if legacy_state is not None else {})
            | ({"cash_sweep": dict(zip(per_date_used, sweep_component_returns))} if sweep is not None else {})
        ),
    )
    return result, held_days_by_ticker


def _cash_sweep_step(
    sweep: dict, weight: float, *, date: str, is_session: bool, book_weights: dict[str, float],
    legacy_weights: dict[str, float], rebalance_next: bool, formed_weights: dict[str, float], pv_for_costs: float,
) -> tuple[float, float]:
    """One date of the T-bill sweep: yesterday's sweep weight earns today's ETF return (it filled at today's open), then
    the new target is sized from the weights just decided (main.py sizes it after Pass 2 from holdings plus open
    orders) and traded when it moved by `min_trade_weight`. Returns (net return, new weight); the cost is left in
    `sweep["_last_cost"]` for the run's cost total."""
    from portfolio.cash_sweep import cash_sweep_target_weight, margin_fraction, strategy_reserve, sweep_order_needed

    config = sweep["config"]
    earned = weight * float(sweep["returns_by_date"].get(date, 0.0) or 0.0)
    sweep["_last_cost"] = 0.0
    if not is_session:
        return earned, weight
    types = sweep.get("security_type_by_ticker") or {}
    long_weight = short_weight = 0.0
    margin_inputs = []
    for symbol, value in list(book_weights.items()) + list(legacy_weights.items()):
        if value > 0.0:
            long_weight += value
        else:
            short_weight -= value
        margin_inputs.append((types.get(symbol, "equity"), value))
    book_long = sum(value for value in book_weights.values() if value > 0.0)
    book_short = -sum(value for value in book_weights.values() if value < 0.0)
    reserve = strategy_reserve(
        rebalance_next=rebalance_next, book_gross_cap=float(sweep.get("book_gross_cap", 1.0)),
        max_short_exposure=float(sweep.get("max_short_exposure", 0.3)),
        formed_long=sum(value for value in formed_weights.values() if value > 0.0),
        formed_short=-sum(value for value in formed_weights.values() if value < 0.0),
        book_long=book_long, book_short=book_short, other_budget_remaining=float(sweep.get("other_budget", 0.0)),
        neutral_budget=float(sweep.get("neutral_budget", 0.0)),
    )
    target = cash_sweep_target_weight(
        long_weight=long_weight, short_weight=short_weight, margin_used=margin_fraction(margin_inputs), reserve=reserve,
        config=config,
    )
    if not sweep_order_needed(weight, target, config["min_trade_weight"]):
        return earned, weight
    traded = abs(target - weight)
    cost = traded * config["cost_bps_per_side"] / 1e4
    if traded > 0.0 and pv_for_costs > 0.0:
        cost = max(cost, float(sweep.get("min_commission_usd", 1.0)) / pv_for_costs)
    sweep["_last_cost"] = cost
    return earned - cost, target


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
        if base_kwargs.get("commission_bps_by_ticker"):
            stressed_kwargs["commission_bps_by_ticker"] = {
                ticker: float(value) * multiplier for ticker, value in base_kwargs["commission_bps_by_ticker"].items()
            }
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
