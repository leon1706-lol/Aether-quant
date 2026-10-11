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
import math

import pandas as pd

from evaluation.rank_book_simulator import DEFAULT_ASSUMED_PORTFOLIO_VALUE_USD
from evaluation.rolling_ic_gate_calibration import build_event_buffer
from evaluation.rolling_ic_series import make_rolling_ic_state_fn
from execution.cost_model import build_net_edge_decision
from liquidity.market_liquidity import TYPICAL_DAILY_DOLLAR_VOLUME_BY_TYPE, build_liquidity_decision, cap_spread_proxy
from portfolio.book_construction import (
    apply_book_weight_floor,
    apply_hrp_weights,
    build_book_raw_weights,
    pct_returns_from_closes,
)
from portfolio.rolling_ic_gate import evaluate_rolling_ic_gate
from risk.position_sizing import build_dynamic_position_sizing, cost_sizing_multiplier

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
    state_fn=None,
):
    """A date -> gate-result callable for `rolling_ic_gate_fn`: the rolling-IC state as of that date (no lookahead)
    run through main.py's own `evaluate_rolling_ic_gate()`. The state comes from `make_rolling_ic_state_fn`, which
    equals `compute_rolling_ic_state()` on the events dated <= that date; it does not depend on the floor, so pass one
    shared `state_fn` to build several floor variants without re-resolving anything."""
    config = dict(gate_config)
    config["enabled"] = True
    if state_fn is None:
        state_fn = make_rolling_ic_state_fn(
            build_event_buffer(
                frame,
                raw_score_column=raw_score_column,
                ticker_column=ticker_column,
                date_column=date_column,
                close_column=close_column,
            ),
            horizon_days=int(config.get("horizon_days", 20)),
            rolling_window_days=int(config.get("rolling_window_days", 40)),
            min_names_per_date=int(config.get("min_names_per_date", 10)),
        )
    cache: dict[str, dict] = {}

    def gate_fn(date: str) -> dict:
        key = str(date)[:10]
        if key not in cache:
            cache[key] = evaluate_rolling_ic_gate(state_fn(key), config)
        return cache[key]

    return gate_fn


def _finite(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def build_live_member_weight_fn(
    config: dict,
    *,
    security_type_by_ticker: dict[str, str],
    nav: float = DEFAULT_ASSUMED_PORTFOLIO_VALUE_USD,
    core_crypto_tickers: set[str] | frozenset[str] | None = None,
    predicted_volatility_by_key: dict | None = None,
):
    """`member_weight_fn` for `simulate_rank_book`: the live per-member decision chain of `main.py`'s Pass 2 built
    from the SAME pure functions (nothing re-derived here): dynamic sizing (`build_dynamic_position_sizing`), the
    liquidity gate (`build_liquidity_decision` on the capped spread proxy), the reduce_size haircut, the net-edge
    decision and cost multiplier, the book weight floor, then the analyzer's verdicts for a book member (min confidence,
    liquidity block / thin market and a failing net edge on a new entry -> no trade; a held member keeps its weight).

    Offline approximations, all conservative to document: no learned-topology multiplier (live falls back to 1.0
    without a trained topology model), volatility comes from `rolling_volatility_20d` unless `predicted_volatility_by_key`
    ({(date, ticker): value}) supplies the multitask head, RL sizing is whatever the config says, and the regime override
    (Priority 2) uses the dataset's `regime_risk_off` flag."""
    phase_v2 = config.get("phase_v2", {})
    risk = phase_v2.get("dynamic_risk", {})
    book = phase_v2.get("portfolio_book", {})
    costs = phase_v2.get("costs", {})
    liquidity = phase_v2.get("liquidity", {})
    phase6 = config.get("phase6", {}).get("risk", {})
    max_position_weight = float(phase6.get("max_position_weight", 0.25))
    min_confidence = phase6.get("min_confidence_to_trade_book_selected")
    min_confidence = float(min_confidence if min_confidence is not None else phase6.get("min_confidence_to_trade", 0.12))
    floor_fraction = float(book.get("sizing_floor_fraction", 0.0))
    rank_sizing_applies = bool(book.get("rank_sizing_applies_to_members", True))
    spread_caps = dict(liquidity.get("max_spread_proxy_by_type", {}))
    fallback_ddv = {
        str(kind): float(value)
        for kind, value in liquidity.get("zero_volume_fallback_ddv_by_type", TYPICAL_DAILY_DOLLAR_VOLUME_BY_TYPE).items()
    }
    configured_cost_cap = liquidity.get("max_round_trip_cost_fraction")
    thresholds = {
        "thin_participation_threshold": float(liquidity.get("thin_participation_threshold", 0.002)),
        "high_impact_participation_threshold": float(liquidity.get("high_impact_participation_threshold", 0.01)),
        "blocked_participation_threshold": float(liquidity.get("blocked_participation_threshold", 0.05)),
        "min_daily_dollar_volume": float(liquidity.get("min_daily_dollar_volume", 100_000.0)),
        "high_impact_size_factor": float(liquidity.get("high_impact_size_factor", 0.5)),
        "slippage_factor": float(liquidity.get("slippage_factor", 0.1)),
        "max_round_trip_cost_fraction": float(configured_cost_cap) if configured_cost_cap is not None else None,
    }
    cost_sizing_enabled = bool(costs.get("cost_sizing_enabled", False))
    min_cost_multiplier = float(costs.get("min_cost_multiplier", 0.25))
    core = frozenset(core_crypto_tickers or ())
    forex_enabled = bool(phase_v2.get("forex_risk", {}).get("enabled", False))

    def member_weight_fn(*, symbol, date, base_weight, held_weight, predicted_rank, row, **_unused):
        if predicted_rank is None or not math.isfinite(float(predicted_rank)):
            return held_weight
        security_type = str(security_type_by_ticker.get(symbol, "equity"))
        if security_type == "forex" and not forex_enabled:
            return held_weight
        confidence = min(1.0, abs(float(predicted_rank) - 0.5) * 2.0)
        predicted_volatility = (predicted_volatility_by_key or {}).get((date, symbol))
        rolling_volatility = _finite(row.get("rolling_volatility_20d"))
        sizing = build_dynamic_position_sizing(
            base_weight,
            confidence,
            rolling_volatility,
            max_position_weight,
            target_daily_volatility=float(risk.get("target_daily_volatility", 0.015)),
            min_position_weight=float(risk.get("min_position_weight", 0.0)),
            low_volatility_threshold=float(risk.get("low_volatility_threshold", 0.01)),
            high_volatility_threshold=float(risk.get("high_volatility_threshold", 0.03)),
            min_volatility_multiplier=float(risk.get("min_volatility_multiplier", 0.35)),
            max_volatility_multiplier=float(risk.get("max_volatility_multiplier", 1.25)),
            max_leverage=float(risk.get("max_leverage", 1.0)),
            predicted_volatility=predicted_volatility,
            use_predicted_volatility=bool(risk.get("use_predicted_volatility", False)),
            predicted_rank_20d=float(predicted_rank),
            rank_sizing_enabled=bool(risk.get("rank_sizing_enabled", False)) and rank_sizing_applies,
            min_rank_multiplier=float(risk.get("min_rank_multiplier", 0.75)),
            max_rank_multiplier=float(risk.get("max_rank_multiplier", 1.25)),
        )
        target = float(sizing.target_weight)
        fallback = None
        if security_type == "forex":
            fallback = fallback_ddv.get("forex")
        elif security_type == "crypto" and symbol in core:
            fallback = fallback_ddv.get("crypto")
        liquidity_decision = build_liquidity_decision(
            close=_finite(row.get("close")),
            volume=_finite(row.get("volume")),
            target_weight=target,
            portfolio_value=nav,
            annualized_volatility=float(sizing.annualized_volatility),
            security_type=security_type,
            dynamic_spread=cap_spread_proxy(row.get("liquidity_spread_proxy"), security_type, spread_caps),
            zero_volume_fallback_ddv=fallback,
            **thresholds,
        )
        action = liquidity_decision.recommended_action
        if action == "reduce_size":
            target = float(liquidity_decision.adjusted_target_weight)
        net_edge = build_net_edge_decision(
            float(predicted_rank),
            liquidity_decision.to_dict(),
            abs(target - held_weight) * nav,
            costs,
            trade_direction=1 if target >= 0.0 else -1,
            security_type=security_type,
        )
        multiplier, _reason = cost_sizing_multiplier(
            net_edge.expected_edge_bps, net_edge.expected_cost_bps, cost_sizing_enabled, min_cost_multiplier
        )
        target *= multiplier
        if floor_fraction > 0.0 and security_type not in ("future", "option", "forex"):
            target = apply_book_weight_floor(target, base_weight, floor_fraction, skip_floor=(action == "reduce_size"))
        invested = held_weight != 0.0
        if confidence < min_confidence or action in ("block", "simulate_instead"):
            return held_weight
        if not invested and not net_edge.passes:
            return 0.0
        if float(row.get("regime_risk_off", 0.0) or 0.0) > 0.5 and phase_v2.get("regime", {}).get(
            "risk_off_override_min_severity"
        ) is None:
            return held_weight
        return target

    return member_weight_fn


def build_hrp_raw_weights_fn(
    frame: pd.DataFrame,
    *,
    window_bars: int = 25,
    gross_exposure: float = 1.0,
    max_position_weight: float = 0.25,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "close",
):
    """`raw_weights_fn` for the HRP book sizing path (`allocation_method="hrp"`): the live code feeds
    `apply_hrp_weights` each member's last `window_bars` closes (main.py's `symbol_windows` deque), and falls back to
    the rank formula when HRP returns nothing."""
    closes: dict[str, tuple[list[str], list[float]]] = {}
    for ticker, group in frame.sort_values(date_column).groupby(ticker_column):
        closes[str(ticker)] = ([str(d)[:10] for d in group[date_column]], [float(c) for c in group[close_column]])

    def raw_weights_fn(allocations, date):
        key = str(date)[:10]
        returns_by_symbol = {}
        for symbol in allocations:
            dates, values = closes.get(str(symbol), ([], []))
            end = bisect.bisect_right(dates, key)
            returns_by_symbol[symbol] = pct_returns_from_closes(values[max(0, end - window_bars) : end])
        hrp = apply_hrp_weights(allocations, returns_by_symbol, gross_exposure=gross_exposure)
        return dict(hrp) if hrp else build_book_raw_weights(allocations, max_position_weight)

    return raw_weights_fn


def build_impact_inputs_fn(
    frame: pd.DataFrame,
    *,
    security_type_by_ticker: dict[str, str],
    zero_volume_fallback_ddv_by_type: dict[str, float] | None = None,
    ticker_column: str = "ticker",
    date_column: str = "date",
):
    """`impact_inputs_fn` for the Almgren impact: (daily volatility, ADV in dollars) of one name on one date from the
    dataset's own `rolling_volatility_20d` and `liquidity_log_dollar_volume`; volume-less classes use the configured
    fallback ADV (the same one the liquidity gate uses)."""
    fallback = dict(zero_volume_fallback_ddv_by_type or TYPICAL_DAILY_DOLLAR_VOLUME_BY_TYPE)
    table: dict[tuple[str, str], tuple[float, float]] = {}
    if not {"rolling_volatility_20d", "liquidity_log_dollar_volume"} <= set(frame.columns):
        return lambda symbol, date: None  # a frame without the liquidity columns charges no per-name impact
    for ticker, date, volatility, log_dollar_volume in zip(
        frame[ticker_column], frame[date_column], frame["rolling_volatility_20d"], frame["liquidity_log_dollar_volume"]
    ):
        adv = math.expm1(_finite(log_dollar_volume))
        if adv <= 0.0:
            adv = float(fallback.get(str(security_type_by_ticker.get(str(ticker), "equity")), 0.0))
        table[(str(date)[:10], str(ticker))] = (_finite(volatility), adv)

    def impact_inputs_fn(symbol, date):
        return table.get((str(date)[:10], str(symbol)))

    return impact_inputs_fn


def build_live_mechanisms(
    config: dict,
    frame: pd.DataFrame,
    *,
    core_crypto_tickers: set[str] | frozenset[str] | None = None,
    nav: float | None = None,
    include: tuple[str, ...] = ("kill_switch", "member_sizing", "hrp", "impact"),
    predicted_volatility_by_key: dict | None = None,
) -> dict:
    """The optional live mechanisms of `build_as_live_kwargs`, built from the config: kill switch (+ whether a
    trip latches, i.e. no backtest bypass), the member sizing/liquidity/net-edge chain, HRP weights when
    `allocation_method == "hrp"`, and the per-name impact inputs. `include` lets a lever turn one off."""
    phase_v2 = config.get("phase_v2", {})
    book = phase_v2.get("portfolio_book", {})
    assets = config.get("phase1", {}).get("universe", {}).get("assets", [])
    security_types = {str(asset["ticker"]): str(asset.get("security_type", "equity")) for asset in assets}
    portfolio_nav = float(nav) if nav else float(config.get("runtime", {}).get("initial_cash", 0) or 0)
    if portfolio_nav <= 0.0:
        portfolio_nav = DEFAULT_ASSUMED_PORTFOLIO_VALUE_USD
    mechanisms: dict = {}
    if "kill_switch" in include:
        kill_switch = dict(phase_v2.get("risk", {}).get("kill_switch", {}))
        mechanisms["kill_switch_config"] = kill_switch or None
        mechanisms["kill_switch_sticky"] = not bool(phase_v2.get("backtest", {}).get("bypass_sticky_trade_lock", False))
    if "member_sizing" in include and {"close", "volume", "rolling_volatility_20d"} <= set(frame.columns):
        mechanisms["member_weight_fn"] = build_live_member_weight_fn(
            config,
            security_type_by_ticker=security_types,
            nav=portfolio_nav,
            core_crypto_tickers=core_crypto_tickers,
            predicted_volatility_by_key=predicted_volatility_by_key,
        )
    if "hrp" in include and str(book.get("allocation_method", "rank")) == "hrp":
        mechanisms["raw_weights_fn"] = build_hrp_raw_weights_fn(
            frame, max_position_weight=float(config.get("phase6", {}).get("risk", {}).get("max_position_weight", 0.25))
        )
    if "impact" in include:
        mechanisms["impact_inputs_fn"] = build_impact_inputs_fn(
            frame,
            security_type_by_ticker=security_types,
            zero_volume_fallback_ddv_by_type=phase_v2.get("liquidity", {}).get("zero_volume_fallback_ddv_by_type"),
        )
    return mechanisms


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
    topology_config: dict | None = None,
    kill_switch_config: dict | None = None,
    kill_switch_sticky: bool = False,
    member_weight_fn=None,
    raw_weights_fn=None,
    impact_inputs_fn=None,
) -> dict:
    """base_kwargs (idealized, from `phase1...net_performance`) + the live
    overrides, read from `phase_v2.portfolio_book` / `phase_v2.exits` - the
    ONE config source live uses (the idealized run reads net_performance, a
    second source that had drifted: sector cap 0.05 vs 0.15).

    V5.7.0: `hold_positions_on_veto` now follows `portfolio_book.hold_owned_positions_on_veto` (it was hardcoded True,
    so flipping the config changed live but not this run). The optional live mechanisms (kill switch, member sizing /
    liquidity / net-edge chain, HRP weights, per-name impact) are passed in already built; None leaves them off."""
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
        hold_positions_on_veto=bool(book_config.get("hold_owned_positions_on_veto", True)),
        # live's hysteresis anchor is the last NON-EMPTY book whether or not positions are held through a veto
        hysteresis_anchor_on_formed_book=True,
        retry_rebalance_after_veto=True,
        kill_switch_config=kill_switch_config,
        kill_switch_sticky=kill_switch_sticky,
        member_weight_fn=member_weight_fn,
        raw_weights_fn=raw_weights_fn,
        impact_inputs_fn=impact_inputs_fn,
        max_holding_dates=(
            int(exits_config["max_holding_bars"])
            if exits_config.get("enabled", False) and exits_config.get("max_holding_bars") is not None
            else None
        ),
        # analyzer Priority 3 (elevated topology volatility) cancels new book entries unless the config exempts members.
        entry_veto_column=(
            "topology_risk_elevated" if (topology_config or {}).get("elevated_veto_applies_to_book_members", True) else None
        ),
    )
    return kwargs
