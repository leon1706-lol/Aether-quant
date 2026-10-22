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
from pathlib import Path

import pandas as pd

from analyzer.market_analyzer import build_market_analysis_decision
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
from risk.rl_sizing import build_rl_sizing_state, resolve_rl_shadow_guard, rl_excess_return, rl_shadow_guard_allows

# Asset classes whose bar lands AFTER the equity-session tick (forex 19:00/20:00,
# crypto ~midnight UTC): live decides them on the previous day's bar
# (main.py on_data() "borrowed bar" path), so offline must too.
LATE_BAR_ASSET_CLASSES = frozenset({"forex", "crypto"})
# Cross-asset inputs are built from the bars available strictly before the tick, so for a late-bar symbol they belong to
# the tick's own dataset row; the symbol's own price / volume / liquidity / sensitivity block is the previous row
# (measured on BT1 and BT2 snapshots of ETHUSD and EURUSD, Problems.md #172).
LATE_BAR_SAME_ROW_FEATURE_PREFIXES = (
    "peer_", "alt_", "topology_", "cs_momentum_rank", "bond_yield_curve", "bond_credit_spread", "macro_crypto_risk_appetite",
    "fx_carry",  # FRED-dated like alt_: live reads the rate as of the tick's date, which is the dataset row D's value
)


# V6.0.0 `phase1.features.late_bar_cross_asset: "own_tick"`: the topology / peer / cross-sectional momentum payloads are the
# symbol's own-tick ones, i.e. the previous dataset row's; only the FRED-dated and bond / macro-proxy blocks stay the tick's.
OWN_TICK_PAYLOAD_PREFIXES = ("peer_", "topology_", "cs_momentum_rank")


def late_bar_same_row_prefixes(config: dict | None) -> tuple[str, ...]:
    mode = str(((config or {}).get("phase1", {}).get("features", {}) or {}).get("late_bar_cross_asset", "equity_tick"))
    if mode != "own_tick":
        return LATE_BAR_SAME_ROW_FEATURE_PREFIXES
    return tuple(prefix for prefix in LATE_BAR_SAME_ROW_FEATURE_PREFIXES if prefix not in OWN_TICK_PAYLOAD_PREFIXES)


def forex_monday_payload_only(offline_row: dict | None, same_row_prefixes: tuple[str, ...]) -> dict | None:
    """A forex tick on a Monday holds Sunday's fill-forward bar, which has no dataset row (its previous row is Friday), so the
    own-price block cannot be compared; only the payload / FRED-dated features of the merged row are."""
    if offline_row is None:
        return None
    return {name: value for name, value in offline_row.items() if str(name).startswith(same_row_prefixes)}


def forex_tick_holds_fill_forward_bar(tick_date: str, previous_row_date: str | None, holidays: frozenset[int] = frozenset()) -> bool:
    """True when a forex tick on `tick_date` holds a Lean fill-forward bar: the calendar day before the tick (whose bar
    closes at the tick's midnight) is an open day - not a Saturday, not a Lean market holiday - with no dataset row. That
    covers Sunday before Monday and a weekday the zip has no bar for (2025-12-25, 2026-01-01); generalises the V6.0.0
    Monday-only rule (V6.1.0)."""
    from datetime import date as _date, timedelta

    held = _date.fromisoformat(str(tick_date)[:10]) - timedelta(days=1)
    if held.weekday() == 5 or held.toordinal() in holidays:
        return False
    return str(previous_row_date or "")[:10] != held.isoformat()


def late_bar_offline_row(
    previous_row: dict | None, same_row: dict | None, same_row_prefixes: tuple[str, ...] = LATE_BAR_SAME_ROW_FEATURE_PREFIXES
) -> dict | None:
    """The dataset row a late-bar symbol's live features at tick D correspond to: the previous row, with the features
    under `same_row_prefixes` taken from row D. None when the previous row is missing."""
    if previous_row is None:
        return None
    merged = dict(previous_row)
    for name, value in (same_row or {}).items():
        if str(name).startswith(same_row_prefixes):
            merged[name] = value
    return merged
ROOT_DIR = Path(__file__).resolve().parents[1]


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


def with_live_event_duplicates(
    frame: pd.DataFrame, late_bar_tickers: set[str] | frozenset[str] | None, *, ticker_column: str = "ticker"
) -> pd.DataFrame:
    """The rolling-IC event rows as live records them (V6.1.0, Problems.md #196). Pass 1c appends an event for every pending
    symbol on every tick, and a crypto pair is pending on BOTH its own midnight tick and the next equity tick (which re-scores
    the same bar), both stamped with that day's `Time.date()` and the same close: a late-bar symbol therefore enters the event
    buffer twice per date. Counting each once made the offline gate read +0.012 above the logged live value (same side of the
    floor on 73% of dates); the doubled events bring it to correlation 0.98, offset -0.0003 and 92% on the same side."""
    if not late_bar_tickers:
        return frame
    duplicated = frame[frame[ticker_column].astype(str).isin({str(t) for t in late_bar_tickers})]
    if duplicated.empty:
        return frame
    return pd.concat([frame, duplicated], ignore_index=True)


def make_rolling_ic_gate_fn(
    frame: pd.DataFrame,
    *,
    raw_score_column: str,
    gate_config: dict,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "close",
    state_fn=None,
    include_tickers: set[str] | frozenset[str] | None = None,
    late_bar_tickers: set[str] | frozenset[str] | None = None,
):
    """A date -> gate-result callable for `rolling_ic_gate_fn`: the rolling-IC state as of that date (no lookahead)
    run through main.py's own `evaluate_rolling_ic_gate()`. The state comes from `make_rolling_ic_state_fn`, which
    equals `compute_rolling_ic_state()` on the events dated <= that date; it does not depend on the floor, so pass one
    shared `state_fn` to build several floor variants without re-resolving anything. `include_tickers` (V5.8.0) keeps
    only those tickers' events - main.py feeds the buffer from the main rank group only when ranking is grouped.
    `late_bar_tickers` (V6.1.0) counts those tickers' events twice per date, as live records them
    (`with_live_event_duplicates`), unless the config's `late_bar_event_count` is "once" (V6.2.0)."""
    from portfolio.rolling_ic_gate import resolve_late_bar_event_count

    config = dict(gate_config)
    config["enabled"] = True
    if state_fn is None:
        if include_tickers is not None:
            frame = frame[frame[ticker_column].astype(str).isin(set(map(str, include_tickers)))]
        if resolve_late_bar_event_count(config) == "per_tick":
            frame = with_live_event_duplicates(frame, late_bar_tickers, ticker_column=ticker_column)
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
    rl_model: dict | None = None,
    daily_returns_by_date: dict[str, dict[str, float]] | None = None,
    topology_inputs_fn=None,
    use_live_analyzer: bool = False,
):
    """`member_weight_fn` for `simulate_rank_book`: the live per-member decision chain of `main.py`'s Pass 2 built
    from the SAME pure functions (nothing re-derived here): dynamic sizing (`build_dynamic_position_sizing`), the
    liquidity gate (`build_liquidity_decision` on the capped spread proxy), the reduce_size haircut, the net-edge
    decision and cost multiplier, the book weight floor, then the analyzer's verdicts for a book member (min confidence,
    liquidity block / thin market and a failing net edge on a new entry -> no trade; a held member keeps its weight).

    Offline approximations, all conservative to document: no learned-topology multiplier unless `topology_inputs_fn`
    ((symbol, date) -> {topology_source, topology_confidence, topology_disagreement} or None, see
    topology.learned_topology.learned_sizing_inputs) supplies it, volatility comes from `rolling_volatility_20d` unless `predicted_volatility_by_key`
    ({(date, ticker): value}) supplies the multitask head, RL sizing is whatever the config says, and the regime override
    (Priority 2) uses the dataset's `regime_risk_off` flag.

    V5.8.0 - RL sizing: with `rl_model` and `dynamic_risk.rl_sizing_enabled`, the member's sizing gets the same
    `rl_model` / `rl_state` / multiplier range main.py passes to `build_dynamic_position_sizing` (state from the row's
    raw feature columns, as train_rl_sizing.py builds it). With `dynamic_risk.rl_shadow_guard.enabled` the RL-vs-constant
    excess return of the positions this function sized is accumulated per date from `daily_returns_by_date`
    ({date: {ticker: target_return_1d}}) and `risk.rl_sizing.rl_shadow_guard_allows` switches RL off exactly as live.

    V6.1.0 - `use_live_analyzer`: the verdict comes from `analyzer.market_analyzer.build_market_analysis_decision` itself
    (the composite signal-quality score, topology isolation / elevation, the risk-off override at its configured
    severity, liquidity and the net-edge gate, in live's priority order) with the regime / topology inputs rebuilt from
    the dataset row; any action other than "trade" holds. The returned function also sizes a legacy-signal entry
    (`confidence=` the probability signal's confidence, `is_book_selected=False`); without a predicted rank the net-edge
    gate is skipped (fail-open, as `build_net_edge_decision` does for a missing rank)."""
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
    sizing_risk = phase_v2.get("dynamic_risk", {})  # main.py reads the topology sizing keys from dynamic_risk
    topology_sizing_enabled = bool(sizing_risk.get("topology_sizing_enabled", True)) and topology_inputs_fn is not None
    min_topology_multiplier = float(sizing_risk.get("min_topology_multiplier", 0.5))
    max_topology_multiplier = float(sizing_risk.get("max_topology_multiplier", 1.0))
    rl_enabled = bool(risk.get("rl_sizing_enabled", False)) and rl_model is not None
    analyzer_config = phase_v2.get("market_analyzer", {})
    regime_config = phase_v2.get("regime_detection", {})  # main.py's key (phase_v2.regime does not exist)
    severity = regime_config.get("risk_off_override_min_severity")
    book_floor = phase6.get("min_confidence_to_trade_book_selected")
    analyzer_settings = {
        "min_confidence_to_trade": float(phase6.get("min_confidence_to_trade", 0.12)),
        "min_confidence_to_trade_book_selected": float(book_floor) if book_floor is not None else None,
        "retrain_min_regime_confidence": float(analyzer_config.get("retrain_min_regime_confidence", 0.20)),
        "low_regime_confidence_threshold": float(analyzer_config.get("low_regime_confidence_threshold", 0.35)),
        "use_composite_signal_score": bool(analyzer_config.get("use_composite_signal_score", False)),
        "risk_off_override_min_severity": float(severity) if severity is not None else None,
        "topology_veto_applies_to_book_members": bool(phase_v2.get("topology", {}).get("elevated_veto_applies_to_book_members", True)),
    }
    rl_guard = resolve_rl_shadow_guard(risk.get("rl_shadow_guard"))
    rl_state_holder: dict = {"history": [], "positions": {}, "last_date": None, "allows": True}
    sorted_return_dates = sorted(daily_returns_by_date or {})

    def _advance_rl_guard(date: str) -> None:
        last = rl_state_holder["last_date"]
        if last == date:
            return
        if last is not None and rl_guard["enabled"] and rl_state_holder["positions"]:
            start = bisect.bisect_right(sorted_return_dates, last)
            end = bisect.bisect_right(sorted_return_dates, date)
            for day in sorted_return_dates[start:end]:
                rl_state_holder["history"].append(
                    rl_excess_return(rl_state_holder["positions"], daily_returns_by_date.get(day, {}))
                )
            rl_state_holder["allows"] = rl_shadow_guard_allows(rl_state_holder["history"], rl_guard)
        rl_state_holder["last_date"] = date

    def member_weight_fn(*, symbol, date, base_weight, held_weight, predicted_rank=None, row, confidence=None,
                         is_book_selected=True, **_unused):
        if rl_enabled:
            _advance_rl_guard(str(date)[:10])
        rank_known = predicted_rank is not None and math.isfinite(float(predicted_rank))
        if not rank_known and confidence is None:
            return held_weight
        security_type = str(security_type_by_ticker.get(symbol, "equity"))
        if security_type == "forex" and not forex_enabled:
            return held_weight
        if confidence is None:
            confidence = min(1.0, abs(float(predicted_rank) - 0.5) * 2.0)
        predicted_volatility = (predicted_volatility_by_key or {}).get((date, symbol))
        rolling_volatility = _finite(row.get("rolling_volatility_20d"))
        topology_inputs = (topology_inputs_fn(symbol, date) if topology_sizing_enabled else None) or {}
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
            predicted_rank_20d=float(predicted_rank) if rank_known else None,
            rank_sizing_enabled=bool(risk.get("rank_sizing_enabled", False)) and rank_sizing_applies,
            min_rank_multiplier=float(risk.get("min_rank_multiplier", 0.75)),
            max_rank_multiplier=float(risk.get("max_rank_multiplier", 1.25)),
            rl_model=rl_model if rl_enabled else None,
            rl_state=build_rl_sizing_state(row, confidence) if rl_enabled else None,
            rl_sizing_enabled=rl_enabled and rl_state_holder["allows"],
            min_rl_multiplier=float(risk.get("min_rl_multiplier", 0.6)),
            max_rl_multiplier=float(risk.get("max_rl_multiplier", 1.0)),
            topology_source=topology_inputs.get("topology_source"),
            topology_confidence=topology_inputs.get("topology_confidence"),
            topology_disagreement=topology_inputs.get("topology_disagreement"),
            min_topology_multiplier=min_topology_multiplier,
            max_topology_multiplier=max_topology_multiplier,
        )
        target = float(sizing.target_weight)
        rl_multiplier = float(sizing.rl_multiplier)
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
            float(predicted_rank) if rank_known else None,
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
        if use_live_analyzer:
            decision = build_market_analysis_decision(
                signal_name="buy" if target >= 0.0 else "short", confidence=float(confidence), probability_up=0.5,
                target_weight=target, regime=_row_regime(row), gating={"decision_source": "blend"}, trading_eligible=True,
                trade_lock_active=False, topology=_row_topology(row), liquidity=liquidity_decision.to_dict(),
                min_confidence_to_trade=analyzer_settings["min_confidence_to_trade"],
                retrain_min_regime_confidence=analyzer_settings["retrain_min_regime_confidence"],
                low_regime_confidence_threshold=analyzer_settings["low_regime_confidence_threshold"],
                use_composite_signal_score=analyzer_settings["use_composite_signal_score"],
                is_currently_invested=invested, net_edge=net_edge.to_dict(), is_book_selected=bool(is_book_selected),
                min_confidence_to_trade_book_selected=analyzer_settings["min_confidence_to_trade_book_selected"],
                risk_off_override_min_severity=analyzer_settings["risk_off_override_min_severity"],
                topology_veto_applies_to_book_members=analyzer_settings["topology_veto_applies_to_book_members"],
            )
            if decision.action != "trade":
                return held_weight
            if rl_enabled:
                if target != 0.0:
                    rl_state_holder["positions"][symbol] = (target, rl_multiplier)
                else:
                    rl_state_holder["positions"].pop(symbol, None)
            return target
        if confidence < min_confidence or action in ("block", "simulate_instead"):
            return held_weight
        if not invested and not net_edge.passes:
            return 0.0
        # analyzer Priority 2: risk_off overrides a directional trade only at the configured severity
        if float(row.get("regime_risk_off", 0.0) or 0.0) > 0.5 and (
            analyzer_settings["risk_off_override_min_severity"] is None
            or _finite(row.get("regime_signal_risk_score")) <= -analyzer_settings["risk_off_override_min_severity"]
        ):
            return held_weight
        if rl_enabled:
            if target != 0.0:
                rl_state_holder["positions"][symbol] = (target, rl_multiplier)
            else:
                rl_state_holder["positions"].pop(symbol, None)
        return target

    member_weight_fn.rl_state = rl_state_holder
    return member_weight_fn


def _row_regime(row: dict) -> dict:
    """The analyzer's regime payload from a dataset row (the model-input regime vector, drawdown 0.0; live's risk
    regime also reads the account drawdown, which an offline row cannot know)."""
    risk_regime = "risk_neutral"
    if float(row.get("regime_risk_off", 0.0) or 0.0) > 0.5:
        risk_regime = "risk_off"
    elif float(row.get("regime_risk_on", 0.0) or 0.0) > 0.5:
        risk_regime = "risk_on"
    return {
        "risk_regime": risk_regime,
        "risk_score": _finite(row.get("regime_signal_risk_score")),
        "confidence": _finite(row.get("regime_signal_confidence")),
    }


def _row_topology(row: dict) -> dict:
    """The analyzer's topology payload from a dataset row (its risk one-hots and correlation strength)."""
    risk = "normal"
    if float(row.get("topology_risk_isolated", 0.0) or 0.0) > 0.5:
        risk = "isolated"
    elif float(row.get("topology_risk_elevated", 0.0) or 0.0) > 0.5:
        risk = "elevated"
    return {"topology_risk": risk, "correlation_strength": _finite(row.get("topology_correlation_strength"))}


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
    rl_model_path: str | None = None,
    topology_inputs_fn=None,
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
        rl_model = None
        daily_returns_by_date = None
        if bool(phase_v2.get("dynamic_risk", {}).get("rl_sizing_enabled", False)):
            from risk.rl_sizing import load_rl_sizing_model

            rl_model = load_rl_sizing_model(Path(rl_model_path) if rl_model_path else ROOT_DIR / "ml" / "rl_sizing_model.json")
            if "target_return_1d" in frame.columns:
                daily_returns_by_date = {}
                for date, ticker, value in zip(frame["date"].astype(str), frame["ticker"].astype(str), frame["target_return_1d"]):
                    if value == value:
                        daily_returns_by_date.setdefault(date[:10], {})[ticker] = float(value)
        mechanisms["member_weight_fn"] = build_live_member_weight_fn(
            config,
            security_type_by_ticker=security_types,
            nav=portfolio_nav,
            core_crypto_tickers=core_crypto_tickers,
            predicted_volatility_by_key=predicted_volatility_by_key,
            rl_model=rl_model,
            daily_returns_by_date=daily_returns_by_date,
            topology_inputs_fn=topology_inputs_fn,
            use_live_analyzer="analyzer" in include,
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
    rank_group_by_ticker: dict[str, str] | None = None,
    rank_signal_config: dict | None = None,
    sector_relative_min_size: int = 3,
    venue_listing_dates: dict[str, dict] | None = None,
    class_weight_caps: dict[str, dict] | None = None,
    next_open_fills: bool = False,
    resize_threshold_weight: float = 0.0,
    trade_cooldown_bars: int = 0,
) -> dict:
    """base_kwargs (idealized, from `phase1...net_performance`) + the live
    overrides, read from `phase_v2.portfolio_book` / `phase_v2.exits` - the
    ONE config source live uses (the idealized run reads net_performance, a
    second source that had drifted: sector cap 0.05 vs 0.15).

    V5.7.0: `hold_positions_on_veto` now follows `portfolio_book.hold_owned_positions_on_veto` (it was hardcoded True,
    so flipping the config changed live but not this run). The optional live mechanisms (kill switch, member sizing /
    liquidity / net-edge chain, HRP weights, per-name impact) are passed in already built; None leaves them off.

    V6.0.0: `portfolio_book.per_asset_class_slots` goes to the same book builder live uses; `next_open_fills` makes a
    decided order earn from the next open (the frame needs `add_next_intraday_return`); the resize threshold
    (`functionality.position_scaling`), the entry cooldown (`phase6.risk.trade_cooldown_bars`) and the trailing stop
    (`exits.trailing_stop_pct`) gate trades as live does."""
    from portfolio.book_construction import normalize_per_asset_class_slots

    neutrality = book_config.get("neutrality", {})
    slots, _skipped = normalize_per_asset_class_slots(book_config.get("per_asset_class_slots"))
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
        rank_group_by_ticker=rank_group_by_ticker or None,
        sector_relative_rank=str((rank_signal_config or {}).get("normalization", "cross_sectional")) == "sector_relative",
        sector_relative_min_size=int(sector_relative_min_size),
        partial_adjust_fraction=float(book_config.get("tranche_adjust_fraction", 1.0)),
        venue_listing_dates=venue_listing_dates or None,
        class_weight_caps=class_weight_caps or None,
        per_asset_class_slots=slots or None,
        resize_threshold_weight=float(resize_threshold_weight),
        trade_cooldown_dates=int(trade_cooldown_bars),
        trailing_stop_pct=(
            float(exits_config["trailing_stop_pct"])
            if exits_config.get("enabled", False) and exits_config.get("trailing_stop_pct") is not None
            else None
        ),
        intraday_next_return_column=NEXT_INTRADAY_RETURN_COLUMN if next_open_fills else None,
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


NEXT_INTRADAY_RETURN_COLUMN = "next_intraday_return"


def add_next_intraday_return(frame, *, ticker_column: str = "ticker", date_column: str = "date"):
    """Adds `next_intraday_return`: each row's NEXT session close/open - 1 for the same ticker (NaN on its last row), the
    part of `target_return_1d` an order decided on this row's close earns after filling at the next open."""
    import numpy as np

    ordered = frame.sort_values([ticker_column, date_column])
    next_open = ordered.groupby(ticker_column)["open"].shift(-1)
    next_close = ordered.groupby(ticker_column)["close"].shift(-1)
    values = (next_close / next_open - 1.0).replace([np.inf, -np.inf], np.nan)
    frame[NEXT_INTRADAY_RETURN_COLUMN] = values.reindex(frame.index)
    return frame


def build_rank_groups(config: dict, asset_class_by_ticker: dict[str, str]) -> dict[str, str] | None:
    """{ticker: rank group} when `phase_v2.rank_signal.grouped_normalization` is on (main.py's `_rank_group_by_symbol`),
    else None: the as-live run then ranks one pool exactly as before."""
    from portfolio.rank_signal import rank_group_by_symbol

    if not bool(config.get("phase_v2", {}).get("rank_signal", {}).get("grouped_normalization", False)):
        return None
    groups = config.get("phase1", {}).get("target", {}).get("ranking", {}).get("separate_rank_groups")
    return rank_group_by_symbol(dict(asset_class_by_ticker), groups)


def main_group_tickers(rank_groups: dict[str, str] | None, tickers) -> set[str] | None:
    """Tickers whose events feed the rolling-IC gate (main group only), None when ranking is not grouped."""
    from portfolio.rank_signal import MAIN_RANK_GROUP

    if not rank_groups:
        return None
    return {str(ticker) for ticker in tickers if rank_groups.get(str(ticker), MAIN_RANK_GROUP) == MAIN_RANK_GROUP}


def load_live_venue_listing_dates(config: dict, root_dir) -> dict[str, dict] | None:
    """main.py's `venue_listing_dates`: the listing file when `phase_v2.venue_listing_guard.enabled`, else None."""
    from pathlib import Path

    from risk.asset_class_router import load_venue_listing_dates

    guard = config.get("phase_v2", {}).get("venue_listing_guard", {})
    if not guard.get("enabled", False):
        return None
    return load_venue_listing_dates(Path(root_dir) / guard.get("path", "data/reference/crypto_listing_dates.json")) or None


def build_cash_sweep_kwarg(config: dict, root_dir, *, force_enabled: bool = False) -> dict | None:
    """V6.2.0: `simulate_rank_book(cash_sweep=...)` from the live config, as main.py sizes the T-bill sweep: the ETF's
    forward close-to-close return per date (the dataset's target_return_1d convention), Lean's security types, the
    book's gross cap, live's short-exposure cap and the legacy / sleeve budgets at full size. None when the sweep is off
    (unless `force_enabled`, for a what-if) or its data zip is missing."""
    from evaluation.lean_attribution import LEAN_EQUITY_PRICE_SCALE, read_daily_closes
    from portfolio.cash_sweep import resolve_cash_sweep_config

    phase_v2 = config.get("phase_v2", {})
    sweep = resolve_cash_sweep_config(phase_v2.get("cash_sweep"))
    if not (sweep["enabled"] or force_enabled):
        return None
    closes = read_daily_closes(Path(root_dir) / sweep["data_path"], LEAN_EQUITY_PRICE_SCALE)
    if not closes:
        return None
    dates = sorted(closes)
    forward = {day: closes[after] / closes[day] - 1.0 for day, after in zip(dates, dates[1:]) if closes[day] > 0}
    legacy, bond, forex = phase_v2.get("legacy_sleeve", {}), phase_v2.get("bond_sleeve", {}), phase_v2.get("forex_risk", {})
    other = float(legacy.get("max_gross_exposure", 0.0)) if legacy.get("enabled") else 0.0
    neutral = (float(bond.get("gross_budget", 0.0)) if bond.get("enabled") else 0.0) + (
        float(forex.get("gross_budget", 0.0)) if forex.get("enabled") else 0.0)
    neutrality = (phase_v2.get("portfolio_book", {}) or {}).get("neutrality", {}) or {}
    return {
        "returns_by_date": forward,
        "config": dict(sweep, enabled=True),
        "security_type_by_ticker": {str(a["ticker"]): str(a.get("security_type", "equity")) for a in config["phase1"]["universe"]["assets"]},
        "book_gross_cap": float(neutrality.get("gross_exposure_cap", 1.0)),
        "max_short_exposure": float(config.get("phase9", {}).get("portfolio", {}).get("max_short_exposure", 0.30)),
        "other_budget": other,
        "neutral_budget": neutral,
        "min_commission_usd": 1.0,
    }
