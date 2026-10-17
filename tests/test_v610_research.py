"""scripts/v610_research.py (V6.1.0): the pre-registered rule chain's pure pieces."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("v610_research", ROOT / "scripts" / "v610_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def _summary(sharpes, drawdown=-0.03):
    return research.phase_summary([{"net_sharpe": s, "net_max_drawdown": drawdown, "net_total_return": 0.01} for s in sharpes])


def test_dotted_changes_and_the_cadence_placeholder():
    config = {"phase_v2": {"portfolio_book": {"rebalance_every_bars": 20}, "costs": {"holding_bars": 10}}}
    merged = research.apply_dotted(config, {"portfolio_book.rebalance_every_bars": 15, "costs.holding_bars": "@cadence"})
    assert merged["phase_v2"]["costs"]["holding_bars"] == 15
    assert config["phase_v2"]["costs"]["holding_bars"] == 10  # never mutated


def test_every_phase_or_an_even_sample():
    assert research.phases_for(10, 20) == list(range(10))
    sample = research.phases_for(30, 10)
    assert len(sample) == 10 and sample[0] == 0 and max(sample) < 30


def test_a_variant_must_beat_the_base_on_most_phases_of_both_splits():
    base = {"validation": _summary([0.1, 0.2, 0.3]), "backtest": _summary([0.0, 0.1, 0.2])}
    good = {"validation": _summary([0.25, 0.3, 0.35]), "backtest": _summary([0.25, 0.3, 0.4])}
    lucky = {"validation": _summary([0.25, 0.3, 0.35]), "backtest": _summary([-0.5, -0.4, -0.3, 0.9, 1.0, 0.3, 0.35])}
    assert research.rule_verdict(base, good)["passes"]
    verdict = research.rule_verdict(base, lucky)
    assert not verdict["passes"] and not verdict["checks"]["beats_base_median_on_60pct_of_phases"]
    deeper = {"validation": _summary([0.25, 0.3, 0.35], -0.05), "backtest": _summary([0.25, 0.3, 0.4], -0.05)}
    assert not research.rule_verdict(base, deeper)["checks"]["drawdown_within_1pp"]


def test_branch_a_also_needs_the_as_live_margins_and_extra_checks_can_veto():
    base = {"validation": _summary([0.1]), "backtest": _summary([0.1])}
    better = {"validation": _summary([0.3]), "backtest": _summary([0.3])}
    assert research.decide({"ungated": base}, {"ungated": better}, "B")["adopted"]
    assert not research.decide({"ungated": base, "as_live": better}, {"ungated": better, "as_live": base}, "A")["adopted"]
    assert not research.decide({"ungated": base}, {"ungated": better}, "B", {"latency_within_1.5x": False})["adopted"]


def _ic(validation, backtest, t=2.5, swapped=None):
    entry = lambda value, hac: {"daily_mean_ic": value, "hac_t": hac, "non_overlapping_mean_ic": value}  # noqa: E731
    out = {"validation": {"decision_rank_20d": entry(validation, 1.0)}, "backtest": {"decision_rank_20d": entry(backtest, t)}}
    if swapped is not None:
        out["validation"]["decision_rank_20d_swapped_priority"] = entry(swapped[0], 1.0)
        out["backtest"]["decision_rank_20d_swapped_priority"] = entry(swapped[1], t)
    return out


def test_model_ic_clauses_compare_with_the_installed_models_by_the_seed_spread():
    model_ic = {"candidates": {
        "installed": {"ensemble": _ic(0.01, 0.03)},
        "ctl": {"ensemble": _ic(0.00, 0.03), "members_scored": {"a": _ic(0.00, 0.0), "b": _ic(0.02, 0.0)}},
        "good": {"ensemble": _ic(0.04, 0.05)}, "noise": {"ensemble": _ic(0.025, 0.05)},
    }}
    assert all(v for k, v in research.model_ic_checks(model_ic, "good").items() if k != "decision_priority")
    assert not research.model_ic_checks(model_ic, "noise")["validation_beats_control_by_seed_spread"]  # +0.015 < the 0.02 spread


def test_a_multitask_only_change_is_judged_on_the_swapped_priority_decision():
    # live serves the sequence first, so the two candidates' live decisions are identical; only the swapped one differs
    model_ic = {"candidates": {
        "installed": {"ensemble": _ic(0.01, 0.03, swapped=(0.01, 0.03))},
        "ctl": {"ensemble": _ic(0.01, 0.03, swapped=(0.01, 0.03)), "members_scored": {}},
        "mt_only": {"ensemble": _ic(0.01, 0.03, swapped=(0.05, 0.06))},
    }}
    checks = research.model_ic_checks(model_ic, "mt_only")
    assert checks["decision_priority"] == "swapped" and checks["validation_beats_control_by_seed_spread"]


def test_h1_weights_passing_heads_by_validation_ic_from_their_better_model():
    validation = {
        "decision_rank_20d": {"daily_mean_ic": 0.0},
        "multitask.sector_neutral_rank_20d": {"daily_mean_ic": 0.075},
        "sequence.sector_neutral_rank_20d": {"daily_mean_ic": 0.033},
        "multitask.residual_rank_5d": {"daily_mean_ic": 0.025},
        "multitask.rank_20d": {"daily_mean_ic": 0.06},
    }
    model_ic = {"candidates": {"installed": {"ensemble": {"validation": validation}}}}
    blend = research.head_blend_from_ic(model_ic, "installed", {"sector_neutral_rank_20d", "residual_rank_5d"})
    assert blend["heads"] == {"sector_neutral_rank_20d": 0.75, "residual_rank_5d": 0.25}
    assert blend["model_priority"][0] == "multitask"
    assert research.head_blend_from_ic(model_ic, "installed", set()) is None


def test_phases_map_in_order_when_run_serially(monkeypatch):
    monkeypatch.setattr(research, "_phase_worker", lambda phase: {"phase": phase, "net_sharpe": float(phase)})
    assert [row["phase"] for row in research.map_phases([3, 1, 2], workers=1)] == [3, 1, 2]
    assert research.map_phases([5], workers=4) == [{"phase": 5, "net_sharpe": 5.0}]  # one phase never forks


def test_a_legacy_variant_needs_a_positive_legacy_component_on_both_splits():
    paying = {"ungated": {"validation": {"legacy_net_return_median": 0.004}, "backtest": {"legacy_net_return_median": 0.02}}}
    bear_loss = {"ungated": {"validation": {"legacy_net_return_median": -0.009}, "backtest": {"legacy_net_return_median": 0.03}}}
    assert research.legacy_clause(paying) == {"legacy_component_positive_on_both_splits": True}
    assert research.legacy_clause(bear_loss) == {"legacy_component_positive_on_both_splits": False}
    base = {"validation": _summary([0.1, 0.2, 0.3]), "backtest": _summary([0.0, 0.1, 0.2])}
    good = {"validation": _summary([0.25, 0.3, 0.35]), "backtest": _summary([0.25, 0.3, 0.4])}
    verdict = research.decide({"ungated": base}, {"ungated": good}, "B", research.legacy_clause(bear_loss))
    assert verdict["ungated"]["passes"] and not verdict["adopted"]  # the margins pass, the extra clause vetoes
