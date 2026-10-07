"""V5.5.0 round file (Problems.md #127-#129): the offline/live execution-parity
fixes. Cross-module regressions live here, committed together with their
fixes (AGENTS.md). Each section names the live bug it pins; main.py itself
has no unit coverage by design, so the pure functions it now calls carry the
tests, plus a structural guard that main.py still actually calls them."""

import ast
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from analyzer import build_market_analysis_decision
from execution.order_gate import (
    compute_fill_slippage_divergence_bps,
    liquidity_cost_fraction,
    resolve_fill_slippage_source,
    resolve_pending_order_action,
)
from portfolio.book_construction import (
    BookAllocation,
    apply_book_weight_floor,
    build_book_raw_weights,
    build_rank_based_book,
    remember_formed_book,
)
from risk.forex_risk import cap_forex_target_to_book_weight
from risk.rl_sizing import RL_SIZING_STATE_KEYS, rl_sizing_multiplier
from risk_controls import (
    compute_position_exit_tracking_update,
    evaluate_non_model_exit,
    is_cooldown_exempt,
    projected_signed_quantity,
)
from topology import build_market_topology, resolve_elevated_volatility_thresholds

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- limit orders


def test_pending_order_action_submits_when_nothing_in_flight():
    assert resolve_pending_order_action(None, True, 10, 3) == "submit"
    assert resolve_pending_order_action({}, True, 10, 3) == "submit"


def test_pending_order_action_keeps_a_fresh_same_direction_order():
    """The AMZN bug: a still-unfilled entry was re-submitted every bar."""
    pending = {"direction": "buy", "submitted_bar": 10}
    assert resolve_pending_order_action(pending, True, 11, 3) == "keep"
    assert resolve_pending_order_action(pending, True, 12, 3) == "keep"


def test_pending_order_action_replaces_a_stale_or_opposite_order():
    pending = {"direction": "buy", "submitted_bar": 10}
    assert resolve_pending_order_action(pending, True, 13, 3) == "cancel_replace"
    assert resolve_pending_order_action(pending, False, 11, 3) == "cancel_replace"
    assert resolve_pending_order_action({"direction": "buy", "submitted_bar": "x"}, True, 11, 3) == "cancel_replace"


def test_repeated_resubmission_never_resets_the_clock():
    """Replaying the old behavior: submit, then 'resubmit' every bar. With
    the resolver the original order is kept and times out on schedule."""
    pending = None
    submitted_bar = None
    actions = []
    for bar in range(10, 16):
        action = resolve_pending_order_action(pending, True, bar, 3)
        actions.append(action)
        if action in ("submit", "cancel_replace"):
            pending = {"direction": "buy", "submitted_bar": bar}
            submitted_bar = bar
    assert actions == ["submit", "keep", "keep", "cancel_replace", "keep", "keep"]
    assert submitted_bar == 13


# ---------------------------------------------------------------- slippage


def test_per_side_slippage_is_half_the_round_trip():
    payload = {"estimated_round_trip_cost": 0.004, "estimated_slippage": 0.001}
    assert resolve_fill_slippage_source("per_side") == "per_side"
    assert math.isclose(liquidity_cost_fraction(payload, "round_trip"), 0.004)
    assert math.isclose(liquidity_cost_fraction(payload, "per_side"), 0.002)
    assert math.isclose(liquidity_cost_fraction(payload, "impact_only"), 0.001)
    assert resolve_fill_slippage_source("bogus") == "round_trip"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "x", None])
def test_liquidity_cost_fraction_never_raises_on_bad_payload(bad):
    assert liquidity_cost_fraction({"estimated_round_trip_cost": bad}, "per_side") == 0.0


def test_slippage_divergence_uses_the_fill_bar_open():
    # 10 bps over the open, 4 bps expected -> +6 bps divergence.
    assert math.isclose(compute_fill_slippage_divergence_bps(100.10, 100.0, 4.0), 6.0, abs_tol=1e-9)
    assert compute_fill_slippage_divergence_bps(100.0, 100.0, 4.0) == -4.0


@pytest.mark.parametrize(
    "fill,reference,expected",
    [(0.0, 100.0, 1.0), (100.0, 0.0, 1.0), (float("nan"), 100.0, 1.0), (100.0, 100.0, float("inf")), ("a", 1, 1)],
)
def test_slippage_divergence_returns_none_on_unusable_input(fill, reference, expected):
    assert compute_fill_slippage_divergence_bps(fill, reference, expected) is None


def test_no_op_forex_and_kept_order_notes_are_not_audited_as_real_placements():
    from execution.order_gate import is_real_order_placement

    for note in ("kept_long_forex", "kept_short_forex", "forex_zero_delta_kept", "forex_zero_order_units",
                 "forex_resize_deadband_kept", "limit_order_already_pending", "forex_short_exposure_cap_reached"):
        assert is_real_order_placement(note, True) is False, note
    for note in ("entered_long_forex", "scaled_short_forex", "submitted_limit_long", "liquidated_on_sell"):
        assert is_real_order_placement(note, True) is True, note


# ---------------------------------------------------------------- cooldown / pending quantity


def test_only_forced_exits_of_open_positions_skip_the_cooldown():
    assert is_cooldown_exempt("sell", True, True) is True
    assert is_cooldown_exempt("sell", False, True) is False
    assert is_cooldown_exempt("buy", True, True) is False
    assert is_cooldown_exempt("short", True, True) is False
    assert is_cooldown_exempt("sell", True) is False  # a plain legacy sell signal stays rate-limited (#133)


def test_projected_quantity_adds_open_orders_and_ignores_garbage():
    assert projected_signed_quantity(0.0, 13168.0) == 13168.0
    assert projected_signed_quantity(-5000.0, -2000.0) == -7000.0
    assert projected_signed_quantity(float("nan"), 10.0) == 10.0
    assert projected_signed_quantity("x", None) == 0.0


def test_forex_sizing_against_projected_quantity_stops_stacking():
    """A forex order submitted on the equity tick is not filled yet on the
    forex tick; sizing off held quantity alone (0) re-submitted the target."""
    from risk_controls import compute_incremental_order_quantity

    target_units = 13168
    stale_delta = compute_incremental_order_quantity(target_units, 0.0)
    fixed_delta = compute_incremental_order_quantity(target_units, projected_signed_quantity(0.0, 13168.0))
    assert stale_delta == target_units  # the old behavior: submit it all again
    assert fixed_delta == 0


# ---------------------------------------------------------------- exit tracking


def test_untracked_held_position_is_adopted_as_an_entry():
    """Fills land one bar late, so was-flat -> invested is never observed;
    without adoption max_holding_bars could never fire."""
    update = compute_position_exit_tracking_update(
        True, True, 101.0, "hold", None, None, 7,
        has_entry_state=False, held_quantity=-50.0, average_entry_price=99.0,
    )
    assert update == {
        "action": "enter", "entry_bar_index": 7, "entry_price": 99.0,
        "peak_price_since_entry": 99.0, "direction": "short",
    }


def test_adoption_falls_back_to_signal_and_close_when_holding_is_unknown():
    update = compute_position_exit_tracking_update(True, True, 50.0, "short", None, None, 3, has_entry_state=False)
    assert update["direction"] == "short" and update["entry_price"] == 50.0
    update = compute_position_exit_tracking_update(
        True, True, 50.0, "hold", None, None, 3, has_entry_state=False, held_quantity=10.0, average_entry_price=float("nan"),
    )
    assert update["direction"] == "long" and update["entry_price"] == 50.0


def test_exit_tracking_defaults_are_unchanged():
    held = compute_position_exit_tracking_update(True, True, 105.0, "buy", 100.0, "long", 9)
    assert held == {"action": "hold", "peak_price_since_entry": 105.0}
    assert compute_position_exit_tracking_update(False, True, 100.0, "buy", None, None, 1)["action"] == "enter"
    assert compute_position_exit_tracking_update(True, False, 100.0, "sell", 100.0, "long", 1) == {"action": "clear"}


def test_adopted_position_now_reaches_the_max_holding_exit():
    adopted = compute_position_exit_tracking_update(
        True, True, 100.0, "hold", None, None, 5, has_entry_state=False, held_quantity=10.0, average_entry_price=100.0,
    )
    reason = evaluate_non_model_exit(
        26, True, 20, 0.15, adopted["entry_bar_index"], adopted["peak_price_since_entry"], adopted["direction"], 100.0
    )
    assert reason is not None and "holding" in reason


def test_adopted_short_trailing_stop_is_not_inverted():
    adopted = compute_position_exit_tracking_update(
        True, True, 100.0, "hold", None, None, 5, has_entry_state=False, held_quantity=-10.0, average_entry_price=100.0,
    )
    assert adopted["direction"] == "short"
    # price rallies 20% against the short: a SHORT trailing stop must fire
    reason = evaluate_non_model_exit(
        6, True, 20, 0.15, adopted["entry_bar_index"], adopted["peak_price_since_entry"], adopted["direction"], 120.0
    )
    assert reason == "trailing_stop_triggered"


# ---------------------------------------------------------------- book memory / floor / weights


def _allocation(role: str, rank: float) -> BookAllocation:
    return BookAllocation(
        role=role, book_role_multiplier=1.0 if role == "long" else -1.0, predicted_rank_20d=rank, book_reason="t"
    )


def test_remember_formed_book_keeps_the_last_real_book_through_a_veto():
    book = {"A": _allocation("long", 0.9)}
    assert remember_formed_book({}, book) == book
    assert remember_formed_book(book, {}) == book  # veto: memory survives
    assert remember_formed_book(book, None) == book
    newer = {"B": _allocation("long", 0.8)}
    assert remember_formed_book(book, newer) == newer
    assert remember_formed_book({}, {}) == {}


def test_hysteresis_is_applied_against_the_remembered_book_after_a_veto():
    """A veto used to erase the hysteresis anchor, so the next real rebalance
    churned an incumbent that was still inside the margin."""
    ranks = {f"T{i}": {"predicted_rank_20d": i / 20.0, "trading_eligible": True} for i in range(1, 21)}
    first = build_rank_based_book(ranks, top_n=3, bottom_n=3)
    assert {s for s, a in first.items() if a.role == "long"} == {"T20", "T19", "T18"}
    # T18 slips just below the cutoff while T15 climbs past it
    ranks["T18"]["predicted_rank_20d"], ranks["T15"]["predicted_rank_20d"] = 0.84, 0.86

    def longs(book):
        return {symbol for symbol, allocation in book.items() if allocation.role == "long"}

    with_memory = build_rank_based_book(
        ranks, top_n=3, bottom_n=3, previous_allocations=remember_formed_book(first, {}), hysteresis_rank_margin=0.05
    )
    wiped = build_rank_based_book(ranks, top_n=3, bottom_n=3, previous_allocations=None, hysteresis_rank_margin=0.05)
    assert longs(with_memory) == {"T20", "T19", "T18"}  # incumbent kept: no churn
    assert longs(wiped) == {"T20", "T19", "T15"}  # the old behavior: churned out


def test_weight_floor_bounds_the_multiplier_shrink_symmetrically():
    assert apply_book_weight_floor(0.01, 0.08, 0.5) == pytest.approx(0.04)
    assert apply_book_weight_floor(-0.01, -0.08, 0.5) == pytest.approx(-0.04)
    assert apply_book_weight_floor(0.06, 0.08, 0.5) == 0.06  # already above the floor
    assert apply_book_weight_floor(0.0, 0.08, 0.5) == 0.0  # a zeroed (blocked) trade stays zero


def test_weight_floor_is_a_no_op_when_disabled_or_for_liquidity_cuts():
    assert apply_book_weight_floor(0.01, 0.08, 0.0) == 0.01
    assert apply_book_weight_floor(0.01, 0.08, 0.5, skip_floor=True) == 0.01
    assert apply_book_weight_floor(0.01, 0.0, 0.5) == 0.01


def test_weight_floor_never_exceeds_the_book_weight():
    assert apply_book_weight_floor(0.001, 0.08, 5.0) == pytest.approx(0.08)
    assert apply_book_weight_floor(float("nan"), 0.08, 0.5) == 0.0


def test_book_raw_weights_match_the_live_formula():
    allocations = {
        "L": _allocation("long", 1.0),   # confidence 1.0 -> min(0.12, 0.25) = 0.12
        "S": _allocation("short", 0.0),  # confidence 1.0 -> -0.12
        "M": _allocation("long", 0.5),   # confidence 0.0 -> 0.10
    }
    weights = build_book_raw_weights(allocations, 0.12)
    assert weights == {"L": pytest.approx(0.12), "S": pytest.approx(-0.12), "M": pytest.approx(0.10)}
    assert build_book_raw_weights({"X": _allocation("long", float("nan"))}, 0.12) == {}
    assert build_book_raw_weights({"L": _allocation("long", 1.0)}, 0.25)["L"] == pytest.approx(0.25)


# ---------------------------------------------------------------- forex


def test_forex_target_is_capped_to_the_book_weight():
    assert cap_forex_target_to_book_weight(-4.2, 0.025) == -0.025  # several x NAV before the fix
    assert cap_forex_target_to_book_weight(0.9, -0.025) == 0.025
    assert cap_forex_target_to_book_weight(0.01, 0.025) == 0.01  # already smaller: untouched
    assert cap_forex_target_to_book_weight(float("nan"), 0.025) == 0.0
    assert cap_forex_target_to_book_weight(0.5, float("inf")) == 0.0


# ---------------------------------------------------------------- topology volatility


def test_resolver_keeps_a_bare_float_as_the_single_global_cutoff():
    assert resolve_elevated_volatility_thresholds(0.6, {"BTCUSD": "crypto"}) == (0.6, {})
    assert resolve_elevated_volatility_thresholds(None, {}) == (0.45, {})
    assert resolve_elevated_volatility_thresholds("bad", {}) == (0.45, {})
    assert resolve_elevated_volatility_thresholds(-1, {}) == (0.45, {})


def test_resolver_maps_asset_class_thresholds_onto_symbols():
    default, by_symbol = resolve_elevated_volatility_thresholds(
        {"default": 0.5, "crypto": 1.11, "forex": "bad", "bond": -3},
        {"BTCUSD": "crypto", "LTCUSD": "crypto", "AAPL": "equity", "EURUSD": "forex", "HYG": "bond", "X": None},
    )
    assert default == 0.5
    assert by_symbol == {"BTCUSD": 1.11, "LTCUSD": 1.11}


def _two_correlated_symbols():
    base = [0.01 * math.sin(i * 1.7) for i in range(25)]
    return {"CALM": base, "WILD": [value * 12.0 for value in base]}


def test_topology_flags_the_volatile_symbol_under_one_global_cutoff():
    result = build_market_topology(returns_by_symbol=_two_correlated_symbols(), correlation_threshold=0.5)
    risks = {node.symbol: node.topology_risk for node in result.nodes}
    assert risks["WILD"] == "elevated"
    assert risks["CALM"] == "normal"


def test_topology_per_symbol_threshold_stops_a_structurally_volatile_class_being_elevated():
    result = build_market_topology(
        returns_by_symbol=_two_correlated_symbols(),
        correlation_threshold=0.5,
        elevated_volatility_threshold_by_symbol={"WILD": 5.0},
    )
    risks = {node.symbol: node.topology_risk for node in result.nodes}
    assert risks["WILD"] == "normal"  # crypto-style: judged against its own class level


def test_topology_default_path_is_unchanged_when_no_per_symbol_map_is_given():
    plain = build_market_topology(returns_by_symbol=_two_correlated_symbols(), correlation_threshold=0.5)
    explicit = build_market_topology(
        returns_by_symbol=_two_correlated_symbols(), correlation_threshold=0.5, elevated_volatility_threshold_by_symbol={}
    )
    assert [n.topology_risk for n in plain.nodes] == [n.topology_risk for n in explicit.nodes]


# ---------------------------------------------------------------- RL sizing NaN guard


def _rl_model(scores_bias):
    keys = list(RL_SIZING_STATE_KEYS)
    return {
        "state_keys": keys,
        "actions": [0.6, 0.8, 1.0],
        "weights": [[0.0] * len(keys) for _ in scores_bias],
        "bias": list(scores_bias),
        "mean": [0.0] * len(keys),
        "scale": [1.0] * len(keys),
    }


def _rl_state():
    return {key: 0.0 for key in RL_SIZING_STATE_KEYS}


@pytest.mark.parametrize("position", [0, 1, 2])
def test_rl_sizing_non_finite_score_is_a_no_op_not_the_most_aggressive_shrink(position):
    bias = [0.1, 0.2, 0.3]
    bias[position] = float("nan")
    multiplier, reason = rl_sizing_multiplier(_rl_model(bias), _rl_state(), True)
    assert multiplier == 1.0
    assert reason == "rl_sizing_non_finite_score"


def test_rl_sizing_finite_scores_still_pick_the_argmax():
    multiplier, reason = rl_sizing_multiplier(_rl_model([0.1, 0.9, 0.2]), _rl_state(), True)
    assert multiplier == 0.8
    assert reason == "rl_sizing_policy_scaled_sizing"


# ---------------------------------------------------------------- sequence padding


def test_parallel_inference_padding_delegates_to_the_shared_helper():
    from data_pipeline.bar_synthesis import pad_sequence_history
    from inference.parallel_inference import _padded_sequence

    history = [[1.0, 2.0], [3.0, 4.0]]
    assert _padded_sequence(history, 4) == pad_sequence_history(history, 4)
    assert _padded_sequence([], 4) == []  # the pool path's historical empty-history contract


# ---------------------------------------------------------------- analyzer


def test_analyzer_reason_reports_the_real_topology_state():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.8, probability_up=0.7, target_weight=0.1,
        regime={"confidence": 0.6, "risk_regime": "risk_neutral", "risk_score": 0.0},
        gating={"decision_source": "baseline_and_experts"},
        trading_eligible=True, trade_lock_active=False,
        topology={"topology_risk": "normal", "topology_source": "deterministic"},
    )
    assert "topology_state=normal" in decision.reasons
    assert "topology_state=unknown" not in decision.reasons


# ---------------------------------------------------------------- factor exposure


def _synthetic_close_pivot(days=90, names=14, seed=3):
    rng = np.random.default_rng(seed)
    dates = [str(d.date()) for d in pd.bdate_range("2020-01-01", periods=days)]
    tickers = ["SPY"] + [f"T{i}" for i in range(names - 1)]
    prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, (days, names)), axis=0)
    return pd.DataFrame(prices, index=dates, columns=tickers)


def test_factor_exposure_recovers_a_pure_market_book():
    from evaluation.factor_neutralization_check import compute_book_factor_exposure

    pivot = _synthetic_close_pivot()
    forward_spy = pivot["SPY"].shift(-1) / pivot["SPY"] - 1.0
    book = (0.5 * forward_spy).fillna(0.0)
    result = compute_book_factor_exposure(list(pivot.index), book.tolist(), pivot)
    assert result["status"] == "OK"
    assert result["loadings"]["market"] == pytest.approx(0.5, abs=1e-6)
    assert result["r_squared"] == pytest.approx(1.0, abs=1e-6)


def test_alpha_sharpe_includes_the_regression_intercept():
    """compute_factor_exposure() averaged the residuals only; with an intercept in the
    design matrix they sum to ~0, so a book earning a constant 10 bps/day over its
    factor exposure reported alpha_sharpe == alpha_annualized_return_pct == 0."""
    from evaluation.factor_neutralization_check import compute_factor_exposure

    rng = np.random.default_rng(1)
    market = pd.Series(rng.normal(0.0003, 0.01, 400))
    book = 0.5 * market + 0.001 + pd.Series(rng.normal(0, 0.002, 400))
    result = compute_factor_exposure(book, market)
    assert result["alpha_annualized_return_pct"] == pytest.approx(25.2, abs=6.0)  # 0.001 * 252 * 100, +/- the intercept's own sampling error (~2.5)
    assert result["alpha_sharpe"] > 5.0
    assert result["loadings"]["market"] == pytest.approx(0.5, abs=0.05)
    assert all(isinstance(value, float) for value in result["factor_contribution_pct"].values())  # JSON-safe


def test_a_pure_market_book_has_no_alpha():
    from evaluation.factor_neutralization_check import compute_factor_exposure

    rng = np.random.default_rng(2)
    market = pd.Series(rng.normal(0.0003, 0.01, 400))
    result = compute_factor_exposure(0.7 * market, market)
    assert abs(result["alpha_annualized_return_pct"]) < 0.01


def test_factor_exposure_skips_cleanly_without_the_market_or_enough_dates():
    from evaluation.factor_neutralization_check import compute_book_factor_exposure

    pivot = _synthetic_close_pivot()
    no_spy = pivot.drop(columns=["SPY"])
    assert compute_book_factor_exposure(list(pivot.index), [0.0] * len(pivot), no_spy)["status"] == "SKIPPED"
    assert compute_book_factor_exposure(list(pivot.index), [0.0] * len(pivot), pd.DataFrame())["status"] == "SKIPPED"
    assert compute_book_factor_exposure(list(pivot.index[:5]), [0.0] * 5, pivot)["status"] == "SKIPPED"


def test_momentum_factor_has_no_lookahead():
    from evaluation.factor_neutralization_check import momentum_factor_forward_returns

    pivot = _synthetic_close_pivot()
    truncated = pivot.iloc[:60]
    full = momentum_factor_forward_returns(pivot)
    short = momentum_factor_forward_returns(truncated)
    shared = [date for date in short.index if date in full.index and date != truncated.index[-1]]
    assert shared
    # a decision date's factor value must not change when later data is added
    for date in shared:
        assert full[date] == pytest.approx(short[date])


# ---------------------------------------------------------------- retraining


def test_auto_rollback_status_reports_the_degradation_score_without_changing_the_decision():
    from retraining import orchestrator

    conn = MagicMock()
    decision = {"should_rollback": False, "to_version_id": None, "reason": "no_configured_trigger_fired", "failures": []}
    with patch("retraining.orchestrator.fetch_active_model_version", return_value=None), patch(
        "retraining.orchestrator.fetch_rollback_candidates", return_value=[]
    ), patch("retraining.orchestrator.select_rollback_target", return_value=decision):
        result = orchestrator.auto_rollback_status(
            conn, {}, degradation_overrides={"kill_switch_tripped": True, "net_sharpe_decay": True}
        )
    assert result["degradation_score"] == pytest.approx(0.65)
    assert result["decision"] == decision


# ---------------------------------------------------------------- rotation exit vs the legacy sleeve


def test_a_symbol_the_book_opened_becomes_owned_and_stays_owned_when_rotated_out():
    from portfolio.book_construction import update_book_owned_symbols

    owned: set[str] = set()
    assert update_book_owned_symbols(owned, "A", is_book_member=True, is_currently_invested=False) is False  # not filled yet
    assert update_book_owned_symbols(owned, "A", is_book_member=True, is_currently_invested=True) is True
    assert update_book_owned_symbols(owned, "A", is_book_member=False, is_currently_invested=True) is True  # rotated out
    assert update_book_owned_symbols(owned, "A", is_book_member=False, is_currently_invested=False) is False  # closed
    assert owned == set()


def test_a_sleeve_position_is_never_book_owned():
    from portfolio.book_construction import update_book_owned_symbols

    owned: set[str] = set()
    assert update_book_owned_symbols(owned, "SLEEVE", is_book_member=False, is_currently_invested=True) is False
    assert owned == set()


def test_rotation_exit_with_the_sleeve_off_is_the_pre_v550_rule_for_every_held_symbol():
    from portfolio.book_construction import is_rotation_exit_candidate

    assert is_rotation_exit_candidate(True, sleeve_enabled=False, is_book_owned=False) is True
    assert is_rotation_exit_candidate(True, sleeve_enabled=False, is_book_owned=True) is True
    assert is_rotation_exit_candidate(False, sleeve_enabled=False, is_book_owned=True) is False


def test_rotation_exit_with_the_sleeve_on_spares_sleeve_positions():
    """Otherwise a sleeve entry is liquidated the very next bar, and with exits no longer blocked by
    the trade cooldown the sleeve would buy/sell/buy every other bar - pure fee churn."""
    from portfolio.book_construction import is_rotation_exit_candidate

    assert is_rotation_exit_candidate(True, sleeve_enabled=True, is_book_owned=False) is False
    assert is_rotation_exit_candidate(True, sleeve_enabled=True, is_book_owned=True) is True
    assert is_rotation_exit_candidate(False, sleeve_enabled=True, is_book_owned=True) is False


def test_the_rotation_exit_decision_end_to_end_for_a_sleeve_entry_and_a_rotated_out_book_name():
    from portfolio.book_construction import (
        is_rotation_exit_candidate,
        should_exit_non_selected_book_symbol,
        update_book_owned_symbols,
    )

    owned = {"BOOK_NAME"}
    book_is_active = True
    decisions = {}
    for symbol in ("BOOK_NAME", "SLEEVE_NAME"):
        is_owned = update_book_owned_symbols(owned, symbol, is_book_member=False, is_currently_invested=True)
        decisions[symbol] = should_exit_non_selected_book_symbol(
            book_is_active, True, is_rotation_exit_candidate(True, True, is_owned)
        )
    assert decisions == {"BOOK_NAME": True, "SLEEVE_NAME": False}


# ---------------------------------------------------------------- structural wiring guard


MAIN_CALLS = (
    "resolve_pending_order_action(",
    "apply_legacy_sleeve_policy(",
    "compute_sleeve_gross_used(",
    "is_cooldown_exempt(",
    "projected_signed_quantity(",
    "remember_formed_book(",
    "cap_forex_target_to_book_weight(",
    "apply_book_weight_floor(",
    "build_book_raw_weights(",
    "update_book_owned_symbols(",
    "is_rotation_exit_candidate(",
    "compute_fill_slippage_divergence_bps(",
    "resolve_elevated_volatility_thresholds(",
    "collect_teardown_diagnostics(",
    "release_symbol_containers(",
)


def test_main_py_parses_and_still_calls_every_v550_fix():
    """main.py cannot be imported outside Lean, so a refactor could silently
    unwire a fix and every unit test above would stay green. Calls must
    exist as real Call nodes, not just mentions in comments."""
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    missing = [name for name in MAIN_CALLS if name.rstrip("(") not in called]
    assert not missing, f"main.py no longer calls: {missing}"


def test_main_py_never_relies_on_the_stdlib_time_module():
    """`from AlgorithmImports import *` exports Lean's `time` (datetime.time) and replaces any `time` main.py
    imported - `time.perf_counter()` crashed V5.5.0's first backtest on bar 1. main.py must not `import time`
    nor use `time.<attr>`; use `from time import perf_counter as _perf_counter` AFTER the star import."""
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    imports_time = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Import) and any(alias.name == "time" and alias.asname is None for alias in node.names)
    ]
    uses_time = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "time"
    ]
    assert not imports_time and not uses_time, f"import time at {imports_time}, time.<attr> at {uses_time}"
    star = next(n.lineno for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "AlgorithmImports")
    alias = next(n.lineno for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "time")
    assert alias > star, "the perf_counter alias must be imported AFTER the AlgorithmImports star import"


def test_config_ships_the_v550_keys_with_the_owner_decisions():
    import json

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    phase_v2 = config["phase_v2"]
    assert phase_v2["rolling_ic_gate"]["min_rolling_mean_ic"] == 0.05
    assert phase_v2["legacy_sleeve"]["enabled"] is True
    assert phase_v2["legacy_sleeve"]["max_gross_exposure"] == 0.1
    assert phase_v2["portfolio_book"]["min_rank_confidence_spread"] == 0.2831  # owner kept the spread gate
    assert phase_v2["liquidity"]["fill_slippage"]["source"] == "per_side"
    assert phase_v2["topology"]["elevated_volatility_threshold"]["crypto"] > 0.45
    assert phase_v2["costs"]["impact_model"]["enabled"] is False  # live impact is an owner decision
    assert config["phase9"]["portfolio"]["max_forex_short_exposure"] <= config["phase9"]["portfolio"]["max_short_exposure"]
