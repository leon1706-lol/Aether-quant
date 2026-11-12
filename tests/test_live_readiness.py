"""execution/live_readiness.py (V6.6.5, #352): unknown fails, stale fails, and only a full pass is ready."""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from execution.live_readiness import DEFAULT_THRESHOLDS, GROUPS, build_scorecard, live_mode_allowed, render_markdown, resolve_thresholds

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)
GOOD = {
    "forward_sessions": 252, "forward_alpha_t": 2.4, "book_dsr": 0.97, "round_pbo": 0.2,
    "paper_trading_days": 130, "paper_rebalances": 8, "paper_bands_all_inside": True,
    "field_test": {"date": "2026-11-01", "all_passed": True, "passed": 9, "total": 9},
    "kill_switch_enabled": True, "reconciliation_trips_kill_switch": True, "max_total_drawdown_pct": 0.1,
    "secrets_all_safe": True, "postgres_dsn_safe": True, "audit_chain_valid": True, "telegram_configured": True,
    "backup_date": "2026-11-07", "image_digest": "sha256:abc",
    "verification": {"date": "2026-11-05", "all_passed": True, "summary": "35/35"}, "mutation_score": 0.95,
    "accounts_valid": True, "live_account_ok": True,
}


def test_everything_measured_and_passing_is_ready():
    card = build_scorecard(GOOD, now=NOW)
    assert card.ready and not card.blocking and {metric.group for metric in card.metrics} == set(GROUPS)
    assert card.to_dict()["counts"] == {"pass": len(card.metrics), "fail": 0, "unknown": 0}


def test_nothing_measured_is_all_unknown_and_not_ready():
    card = build_scorecard({}, now=NOW)
    assert not card.ready and all(metric.status == "unknown" for metric in card.metrics)
    assert "NOT READY" in render_markdown(card) and "Unknown counts as fail" in render_markdown(card)


def test_each_failure_mode():
    cases = {
        "forward_sessions": {"forward_sessions": 59},
        "book_dsr": {"book_dsr": 0.05},
        "round_pbo": {"round_pbo": 0.5},
        "field_test": {"field_test": {"date": "2026-07-01", "all_passed": True}},  # 130 days old
        "max_total_drawdown": {"max_total_drawdown_pct": 0.2},
        "backup": {"backup_date": "2026-10-01"},
        "verification": {"verification": {"date": "2026-11-05", "all_passed": False}},
        "live_account": {"live_account_ok": False},
        "secrets": {"secrets_all_safe": False},
    }
    for key, change in cases.items():
        card = build_scorecard({**GOOD, **change}, now=NOW)
        statuses = {metric.key: metric.status for metric in card.metrics}
        assert statuses[key] == "fail" and not card.ready, key
    assert build_scorecard({**GOOD, "forward_alpha_t": float("nan")}, now=NOW).metrics[1].status == "unknown"


def test_thresholds_tighten_from_config_and_ignore_junk():
    limits = resolve_thresholds({"thresholds": {"forward_sessions_min": 252, "book_dsr_min": "x", "unknown_key": 1, "round_pbo_max": True}})
    assert limits["forward_sessions_min"] == 252 and limits["book_dsr_min"] == DEFAULT_THRESHOLDS["book_dsr_min"] and "unknown_key" not in limits
    assert not build_scorecard({**GOOD, "forward_sessions": 100}, limits, now=NOW).ready


def test_the_live_gate_is_off_by_default():
    assert live_mode_allowed(None, enforce=False)
    assert not live_mode_allowed(None, enforce=True) and not live_mode_allowed({"ready": False}, enforce=True)
    assert live_mode_allowed({"ready": True}, enforce=True)


@settings(max_examples=200, deadline=None)
@given(st.sets(st.sampled_from(sorted(GOOD)), min_size=1))
def test_a_scorecard_missing_any_evidence_is_never_ready(dropped):
    evidence = {key: value for key, value in GOOD.items() if key not in dropped}
    assert not build_scorecard(evidence, now=NOW).ready


# V6.6.5 mutation check (seed 665): the pinned defaults and the exact boundaries the first tests left open


def test_the_defaults_are_the_documented_thresholds_in_config_json():
    import json
    from pathlib import Path

    config = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
    assert DEFAULT_THRESHOLDS == config["phase_v2"]["live_readiness"]["thresholds"]
    assert DEFAULT_THRESHOLDS["forward_sessions_min"] == 60 and DEFAULT_THRESHOLDS["paper_trading_days_min"] == 120
    assert DEFAULT_THRESHOLDS["paper_rebalances_min"] == 6 and DEFAULT_THRESHOLDS["field_test_max_age_days"] == 90
    assert DEFAULT_THRESHOLDS["backup_max_age_days"] == 7 and DEFAULT_THRESHOLDS["verification_max_age_days"] == 30


def _status(card, key):
    return next(metric.status for metric in card.metrics if metric.key == key)


def test_a_value_exactly_at_its_floor_or_ceiling_passes():
    at = {**GOOD, "forward_sessions": 60, "paper_rebalances": 6, "mutation_score": 0.9, "max_total_drawdown_pct": 0.15}
    card = build_scorecard(at, now=NOW)
    assert all(_status(card, key) == "pass" for key in ("forward_sessions", "paper_rebalances", "mutation_score", "max_total_drawdown"))
    below = build_scorecard({**GOOD, "forward_sessions": 59, "max_total_drawdown_pct": 0.150001}, now=NOW)
    assert _status(below, "forward_sessions") == "fail" and _status(below, "max_total_drawdown") == "fail"


def test_an_age_exactly_at_its_limit_passes_and_a_day_more_fails():
    at_limit = {**GOOD, "field_test": {**GOOD["field_test"], "date": "2026-08-10"},  # 90 days before NOW
                "backup_date": "2026-11-01",  # 7 days
                "verification": {**GOOD["verification"], "date": "2026-10-09"}}  # 30 days
    card = build_scorecard(at_limit, now=NOW)
    assert [_status(card, key) for key in ("field_test", "backup", "verification")] == ["pass", "pass", "pass"]
    over = {**GOOD, "field_test": {**GOOD["field_test"], "date": "2026-08-09"}, "backup_date": "2026-10-31",
            "verification": {**GOOD["verification"], "date": "2026-10-08"}}
    card = build_scorecard(over, now=NOW)
    assert [_status(card, key) for key in ("field_test", "backup", "verification")] == ["fail", "fail", "fail"]


def test_a_full_timestamp_counts_as_its_day():
    card = build_scorecard({**GOOD, "backup_date": "2026-11-07T23:59:59+00:00"}, now=NOW)
    assert _status(card, "backup") == "pass"


def test_metrics_and_scorecards_are_frozen():
    import dataclasses

    import pytest

    card = build_scorecard(GOOD, now=NOW)
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.ready = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.metrics[0].status = "pass"  # type: ignore[misc]
