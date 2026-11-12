"""execution/field_test.py (V6.6.5, #351): the injectors are inert unless every key is turned, and the judge."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from execution.field_test import (
    CHECKS, FieldTestPlan, field_test_allowed, field_test_log_line, field_test_target, inject_metrics, inject_reconciliation_drift, judge_field_test,
    parse_field_test_log, resolve_field_test_plan,
)

PLAN = resolve_field_test_plan({"enabled": True, "shock_after_bars": 20, "drawdown_shock_pct": 0.05, "drift_after_bars": 8, "drift_symbol": "BTCUSD", "drift_weight": 0.2})


def test_plan_resolution_defaults_to_off():
    assert resolve_field_test_plan(None) == FieldTestPlan() and not resolve_field_test_plan({"enabled": False, "shock_after_bars": 3}).enabled
    assert not resolve_field_test_plan({"enabled": True, "shock_after_bars": "x"}).enabled
    assert PLAN.enabled and PLAN.drift_symbol == "BTCUSD"


def test_allowed_only_with_every_key():
    lean_paper = "lean_paper_brokerage"
    assert field_test_allowed(PLAN, runtime_mode="paper", paper_brokerage=lean_paper, env_flag="1")
    assert field_test_allowed(PLAN, runtime_mode="observation", paper_brokerage="", env_flag="1")
    assert not field_test_allowed(PLAN, runtime_mode="paper", paper_brokerage=lean_paper, env_flag=None)
    assert not field_test_allowed(PLAN, runtime_mode="live", paper_brokerage=lean_paper, env_flag="1")
    assert not field_test_allowed(PLAN, runtime_mode="paper", paper_brokerage="interactive_brokers", env_flag="1")
    assert not field_test_allowed(FieldTestPlan(), runtime_mode="paper", paper_brokerage=lean_paper, env_flag="1")


@settings(max_examples=300, deadline=None)
@given(st.sampled_from(["backtest", "observation", "paper", "live", "", "LIVE"]),
       st.sampled_from(["lean_paper_brokerage", " lean_paper_brokerage ", "interactive_brokers", "coinbase", "", "LEAN_PAPER_BROKERAGE"]),
       st.one_of(st.none(), st.sampled_from(["0", "1", "true", ""])), st.booleans())
def test_never_allowed_where_real_money_could_move(mode, brokerage, flag, enabled):
    plan = FieldTestPlan(enabled=enabled)
    if field_test_allowed(plan, runtime_mode=mode, paper_brokerage=brokerage, env_flag=flag):
        assert flag == "1" and enabled and mode != "live"
        assert mode == "observation" or (mode == "paper" and brokerage.strip() == "lean_paper_brokerage")


def test_injectors_act_from_their_bar_and_copy():
    metrics = {"drawdown_velocity_pct_per_bar": 0.001}
    assert inject_metrics(metrics, PLAN, 19) == metrics
    shocked = inject_metrics(metrics, PLAN, 20)
    assert shocked["drawdown_velocity_pct_per_bar"] == 0.05 and shocked["field_test_injected"] and metrics == {"drawdown_velocity_pct_per_bar": 0.001}
    assert inject_metrics({"drawdown_velocity_pct_per_bar": None}, PLAN, 25)["drawdown_velocity_pct_per_bar"] == 0.05
    held = {"BTCUSD": 0.01}
    assert inject_reconciliation_drift(held, PLAN, 7) == held
    assert abs(inject_reconciliation_drift(held, PLAN, 8)["BTCUSD"] - 0.21) < 1e-12 and held == {"BTCUSD": 0.01}
    assert inject_reconciliation_drift({}, FieldTestPlan(), 99) == {}


def test_judge_passes_a_full_run_and_fails_what_did_not_run():
    evidence = {
        "runs": [{"orders_submitted": 4, "orders_filled": 4, "shock_bar": 20, "kill_switch_trip_bar": 20, "gross_after_trip": 0.0,
                  "reconciliation_breach": True, "reconciliation_audit_event": True}],
        "restart": {"started": True, "reconciliation_breach_on_start": False},
        "outages": [{"service": "redis", "engine_alive_after": True}, {"service": "postgres", "engine_alive_after": True}],
        "audit_chain_valid": True, "audit_entries": 12, "account_ids_in_audit": ["paper-a", "paper-b"], "state_dirs_distinct": True,
    }
    report = judge_field_test(evidence)
    assert report["all_passed"] and report["passed"] == len(CHECKS) == 9
    empty = judge_field_test({})
    assert empty["passed"] == 0 and all(check["status"] == "not_run" for check in empty["checks"].values())
    late = judge_field_test({**evidence, "runs": [{**evidence["runs"][0], "kill_switch_trip_bar": 30}]})
    assert not late["checks"]["kill_switch_tripped"]["pass"] and late["checks"]["kill_switch_tripped"]["status"] == "fail"


def test_target_row_fires_once_on_its_bar():
    plan = resolve_field_test_plan({"enabled": True, "order_after_bars": 3, "target_weights": {"ETHUSD": 0.2, "BTCUSD": 0.3}})
    assert plan.target_weights == (("BTCUSD", 0.3), ("ETHUSD", 0.2))
    assert [field_test_target(plan, bar) for bar in (1, 2, 4)] == [None, None, None]
    assert field_test_target(plan, 3) == {"BTCUSD": 0.3, "ETHUSD": 0.2}
    assert field_test_target(FieldTestPlan(), 3) is None and field_test_target(PLAN, 0) is None


def test_log_lines_round_trip_through_the_parser():
    text = "\n".join([
        "2026-11-10 12:00:00 " + field_test_log_line("order_row", 3, names=2),
        "noise line without the prefix",
        "2026-11-10 12:01:00 " + field_test_log_line("gross", 4, value=0.5, locked=False),
    ])
    events = parse_field_test_log(text)
    assert events == [{"event": "order_row", "bar": "3", "names": "2"}, {"event": "gross", "bar": "4", "locked": "False", "value": "0.5"}]


# V6.6.5 mutation check (seed 665): the boundaries the first tests left open

FULL = {
    "runs": [{"orders_submitted": 1, "orders_filled": 1, "shock_bar": 20, "kill_switch_trip_bar": 23, "gross_after_trip": 1e-6,
              "reconciliation_breach": True, "reconciliation_audit_event": True}],
    "restart": {"started": True, "reconciliation_breach_on_start": False},
    "outages": [{"service": "redis", "engine_alive_after": True}],
    "audit_chain_valid": True, "account_ids_in_audit": ["paper-a", "paper-b"], "state_dirs_distinct": True,
}


def _with_run(**changes):
    return {**FULL, "runs": [{**FULL["runs"][0], **changes}]}


def _passes(evidence, check):
    return judge_field_test(evidence)["checks"][check]["pass"]


def test_the_judge_boundaries_hold_exactly():
    assert judge_field_test(FULL)["all_passed"]  # one order, a trip 3 bars late, exposure at the tolerance
    assert not _passes(_with_run(orders_submitted=0), "orders_submitted")
    assert _passes(_with_run(kill_switch_trip_bar=20), "kill_switch_tripped")
    assert not _passes(_with_run(kill_switch_trip_bar=24), "kill_switch_tripped")
    assert not _passes(_with_run(kill_switch_trip_bar=19), "kill_switch_tripped")  # before the shock is not its trip
    assert not _passes(_with_run(gross_after_trip=0.01), "flat_after_trip") and not _passes(_with_run(gross_after_trip=None), "flat_after_trip")


def test_a_breach_needs_its_audit_event_and_the_reverse():
    assert not _passes(_with_run(reconciliation_audit_event=False), "reconciliation_breach_detected")
    assert not _passes(_with_run(reconciliation_breach=False), "reconciliation_breach_detected")


def test_a_restart_record_without_its_first_reconciliation_fails():
    assert not _passes({**FULL, "restart": {"started": True}}, "restart_restored")
    assert not _passes({**FULL, "restart": {"started": False, "reconciliation_breach_on_start": False}}, "restart_restored")


def test_accounts_need_two_ids_and_separate_state():
    assert not _passes({**FULL, "state_dirs_distinct": False}, "accounts_isolated")
    assert not _passes({**FULL, "account_ids_in_audit": ["paper-a", "paper-a"]}, "accounts_isolated")


def test_the_shock_starts_on_its_bar_and_needs_a_size_and_a_bar():
    plan = resolve_field_test_plan({"enabled": True, "shock_after_bars": 5, "drawdown_shock_pct": 0.05})
    assert "field_test_injected" not in inject_metrics({}, plan, 4) and inject_metrics({}, plan, 5)["field_test_injected"]
    no_size = resolve_field_test_plan({"enabled": True, "shock_after_bars": 5, "drawdown_shock_pct": 0.0})
    no_bar = resolve_field_test_plan({"enabled": True, "shock_after_bars": 0, "drawdown_shock_pct": 0.05})
    assert "field_test_injected" not in inject_metrics({}, no_size, 9) and "field_test_injected" not in inject_metrics({}, no_bar, 9)


def test_an_order_row_needs_a_positive_bar():
    plan = resolve_field_test_plan({"enabled": True, "order_after_bars": 0, "target_weights": {"BTCUSD": 0.3}})
    assert field_test_target(plan, 0) is None


def test_a_line_that_starts_with_the_prefix_is_parsed():
    assert parse_field_test_log(field_test_log_line("shock", 14)) == [{"event": "shock", "bar": "14"}]


def test_text_before_the_prefix_never_becomes_a_field():
    line = "engine=lean user=x 2026-11-11 Debug: " + field_test_log_line("shock", 14)
    assert parse_field_test_log(line) == [{"event": "shock", "bar": "14"}]


def test_a_plan_cannot_be_changed_in_place():
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        PLAN.enabled = False  # type: ignore[misc]
