"""evaluation/head_audit.py (V5.8.0, rule R-HEAD): every head/submodel against its own gate."""

from __future__ import annotations

import json

from evaluation.head_audit import audit_heads, load_head_metrics


def _metrics():
    rank = lambda status: {"quality_status": status, "failures": [] if status != "not_promotable" else ["t"]}  # noqa: E731
    model = {
        "validation": {"direction": {"mcc": 0.03}, "direction_5d": {"mcc": -0.01}},
        "backtest": {"direction": {"mcc": 0.02}, "direction_5d": {"mcc": 0.01},
                     "rank_5d_ranking_quality": rank("watchlist"), "rank_20d_ranking_quality": rank("not_promotable")},
        "magnitude_quality": {"quality_status": "stable"},
        "volatility_quality": {"quality_status": "unstable", "failures": ["ratio"]},
    }
    return {
        "multitask": model,
        "baseline": {"validation": {"mcc": 0.02}, "backtest": {"mcc": 0.03}},
        "gating": {"backtest": {"mcc": 0.01}},
        "experts": {"experts": {"bullish": {"quality_gate": {"quality_status": "watchlist"}},
                                "bearish": {"quality_gate": {"quality_status": "stable"}}},
                    "disabled_for_gating_experts": ["bearish"]},
        "rl_sizing": {"backtest_policy_expected_reward": -1.0, "backtest_constant_action_1_0_expected_reward": -0.5},
    }


def test_each_component_gets_its_own_gate():
    report = audit_heads(_metrics(), consumers={"multitask.rank_20d", "gating", "multitask.rank_5d"})
    rows = {row["component"]: row for row in report["rows"]}
    assert rows["multitask.rank_5d"]["passed"] and not rows["multitask.rank_20d"]["passed"]
    assert rows["multitask.magnitude"]["passed"] and not rows["multitask.volatility"]["passed"]
    assert rows["multitask.direction"]["passed"] and not rows["multitask.direction_5d"]["passed"]  # validation mcc < 0
    assert rows["expert.bullish"]["passed"] and not rows["expert.bearish"]["passed"]  # disabled for gating
    assert not rows["gating"]["passed"]  # below the baseline mcc
    assert not rows["rl_sizing"]["passed"]
    assert set(report["failing_in_decision_path"]) == {"multitask.rank_20d", "gating"}


def test_loader_reads_what_exists(tmp_path):
    (tmp_path / "multitask_training_metrics.json").write_text(json.dumps({"backtest": {}}))
    (tmp_path / "gating_training_metrics.json").write_text("{not json")
    loaded = load_head_metrics(tmp_path)
    assert set(loaded) == {"multitask", "gating"} and loaded["gating"] == {"_unreadable": True}
