"""V6.4.3 round file: the findings of the Lean 4 proofs (formal/) and the non-finite audit of the verified functions.

Each block names the theorem or counterexample in formal/AetherFormal/ it pins down on the Python side.
"""

from __future__ import annotations

import math

import pytest

from audit.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain
from execution.cost_model import build_net_edge_decision, expected_fill_fee_bps
from execution.order_gate import resolve_fill_slippage, slippage_amount
from execution.reconciliation import reconcile_positions
from json_safety import sanitize_json_finite
from portfolio.book_neutrality import apply_book_neutrality
from portfolio.sleeve_guard import trailing_drawdown
from risk.kill_switch import evaluate_kill_switch
from risk.position_sizing import build_dynamic_position_sizing
from risk_controls import cap_target_weight

NON_FINITE = (math.nan, math.inf, -math.inf)


# --- BookNeutrality.lean: sector_cap_counterexample / sector_cap_with_reapply --------------------------------------

COUNTER_BOOK = {"a": 0.04, "b": -0.09, "c": 0.5, "d": 0.5}
COUNTER_SECTORS = {"a": "S0", "b": "S0", "c": "S1", "d": "S2"}
COUNTER_KWARGS = dict(sector_by_symbol=COUNTER_SECTORS, dollar_neutral=True, sector_neutral=True, gross_exposure_cap=10.0,
                      max_weight_per_name=1.0, sector_max_net_weight=0.05)


def test_shipped_pipeline_can_leave_a_two_sided_sector_above_its_cap():
    weights, diagnostics = apply_book_neutrality(COUNTER_BOOK, **COUNTER_KWARGS)
    assert diagnostics["per_sector_net"]["S0"] == pytest.approx(-9 / 140)
    assert abs(diagnostics["per_sector_net"]["S0"]) > 0.05
    assert weights["a"] + weights["c"] + weights["d"] == pytest.approx(-weights["b"])  # still dollar-neutral


def test_reapplying_the_sector_cap_keeps_every_sector_within_it():
    weights, diagnostics = apply_book_neutrality(COUNTER_BOOK, reapply_sector_cap_after_dollar_neutral=True, **COUNTER_KWARGS)
    assert all(abs(net) <= 0.05 + 1e-12 for net in diagnostics["per_sector_net"].values())
    assert "sector_cap_reapplied" in diagnostics["steps_applied"]
    assert all(abs(weights[s]) <= abs(COUNTER_BOOK[s]) and weights[s] * COUNTER_BOOK[s] >= 0 for s in weights)


def test_reapply_is_a_no_op_when_the_sector_step_is_off():
    plain, _ = apply_book_neutrality(COUNTER_BOOK, **dict(COUNTER_KWARGS, sector_neutral=False))
    again, diagnostics = apply_book_neutrality(COUNTER_BOOK, reapply_sector_cap_after_dollar_neutral=True,
                                               **dict(COUNTER_KWARGS, sector_neutral=False))
    assert plain == again
    assert "sector_cap_reapplied" not in diagnostics["steps_applied"]


# --- BookNeutrality.lean: old_clip_flips_shorts ---------------------------------------------------------------------

@pytest.mark.parametrize("cap", [0.0, -0.1])
def test_a_non_positive_per_name_cap_is_skipped_not_applied(cap):
    raw = {"a": 0.2, "b": -0.5}
    weights, diagnostics = apply_book_neutrality(raw, sector_by_symbol={}, dollar_neutral=False, sector_neutral=False,
                                                 gross_exposure_cap=10.0, max_weight_per_name=cap, sector_max_net_weight=0.1)
    assert weights == raw
    assert diagnostics["steps_applied"][0] == "per_name_cap_skipped_nonpositive_cap"


# --- RiskControls.lean: capTargetWeight_nonfinite --------------------------------------------------------------------

@pytest.mark.parametrize("target", NON_FINITE)
def test_cap_target_weight_blocks_a_non_finite_target(target):
    assert cap_target_weight(target, 0.2, 1.0) == (0.0, True)


def test_cap_target_weight_finite_behaviour_is_unchanged():
    assert cap_target_weight(0.3, 0.2, 1.0) == (0.3, False)
    assert cap_target_weight(-0.9, 0.5, 1.0) == (-0.5, False)
    assert cap_target_weight(0.1, 1.0, 1.0) == (0.0, True)


# --- PositionSizing.lean: size_nonfinite / size_le_cap / old_negative_product_escapes_cap ---------------------------

@pytest.mark.parametrize("base", NON_FINITE)
def test_sizing_a_non_finite_base_target_gives_zero(base):
    decision = build_dynamic_position_sizing(base, 0.8, 0.015, 0.1)
    assert decision.target_weight == 0.0


def test_a_negative_multiplier_bound_cannot_flip_the_trade_or_escape_the_cap():
    decision = build_dynamic_position_sizing(
        0.1, 0.8, 0.015, 0.1, predicted_rank_20d=0.0, rank_sizing_enabled=True, min_rank_multiplier=-50.0,
        max_rank_multiplier=1.25,
    )
    assert decision.target_weight == 0.0


def test_sizing_finite_behaviour_is_unchanged():
    decision = build_dynamic_position_sizing(-0.1, 1.0, 0.015, 0.2)
    assert decision.target_weight == pytest.approx(-0.1)


# --- SleeveGuard.lean: trailingDrawdown_nonpos_lookback ----------------------------------------------------------------

@pytest.mark.parametrize("lookback", [0, -3])
def test_trailing_drawdown_with_a_non_positive_lookback_reads_no_window(lookback):
    assert trailing_drawdown([1.0, -5.0, 2.0], lookback) == 0.0


def test_trailing_drawdown_finite_behaviour_is_unchanged():
    assert trailing_drawdown([1.0, -5.0, 2.0], 3) == pytest.approx(3.0)
    assert trailing_drawdown([1.0, -5.0, 2.0], 1) == 0.0


# --- HashChain.lean: truncation_undetected ----------------------------------------------------------------------------

def _chain(length: int) -> list[dict]:
    rows, prev = [], GENESIS_HASH
    for index in range(length):
        row = {"prev_hash": prev, "event_type": "e", "created_at": f"2026-11-02T00:00:{index:02d}", "payload": {"i": index}}
        row["hash"] = compute_entry_hash(prev, row["event_type"], row["created_at"], row["payload"])
        rows.append(row)
        prev = row["hash"]
    return rows


def test_truncating_the_newest_rows_is_invisible_without_an_anchor():
    rows = _chain(5)
    assert verify_chain(rows[:3]) == (True, None)


def test_an_anchored_tail_hash_detects_truncation():
    rows = _chain(5)
    assert verify_chain(rows[:3], expected_tail_hash=rows[-1]["hash"]) == (False, 3)
    assert verify_chain(rows, expected_tail_hash=rows[-1]["hash"]) == (True, None)


# --- Non-finite audit of the other verified functions (no change needed; pinned) --------------------------------------

@pytest.mark.parametrize("bad", NON_FINITE)
def test_slippage_never_reaches_a_fill_price_when_non_finite(bad):
    assert slippage_amount(bad, 10.0) == 0.0
    assert slippage_amount(100.0, bad) == 0.0
    assert resolve_fill_slippage("X", 100.0, {"X": bad}) == 0.0


def test_fill_fee_with_a_nan_fill_rate_stays_between_maker_and_taker():
    fee = expected_fill_fee_bps(True, math.nan, 2.0, 5.0)
    assert 2.0 <= fee <= 5.0


def test_net_edge_gate_fails_closed_on_a_nan_cost():
    decision = build_net_edge_decision(
        0.9, {"estimated_round_trip_cost": math.nan}, 1000.0, {"enabled": True, "edge_bps_per_rank_unit": 10.0}
    )
    assert decision.passes is False


@pytest.mark.parametrize("bad", NON_FINITE)
def test_kill_switch_treats_a_non_finite_metric_as_missing(bad):
    decision = evaluate_kill_switch({"drawdown_velocity_pct_per_bar": bad}, {"enabled": True, "max_drawdown_velocity_pct_per_bar": 0.01})
    assert "drawdown_velocity_above_cap" not in decision.triggers


@pytest.mark.parametrize("bad", NON_FINITE)
def test_reconciliation_fails_closed_on_a_non_finite_weight(bad):
    report = reconcile_positions({"A": bad}, {"A": 0.1}, weight_tolerance=0.01, value_tolerance_usd=10.0,
                                 portfolio_value=1000.0, max_tolerated_drift=0.05)
    assert report.breach is True


def test_sanitize_leaves_no_non_finite_number():
    cleaned = sanitize_json_finite({"a": [math.nan, 1.0, {"b": math.inf}], "c": (-math.inf, 2)})
    assert cleaned == {"a": [None, 1.0, {"b": None}], "c": [None, 2]}
