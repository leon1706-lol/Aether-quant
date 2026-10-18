"""scripts/v620_research.py (V6.2.0): the R-MODEL10 IC clauses and R-STAGGER's extra clauses."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("v620_research", ROOT / "scripts" / "v620_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def _entry(validation_ic, backtest_ic, hac_t, swapped=None):
    def block(ic, t=None):
        return {"non_overlapping_mean_ic": ic, "daily_mean_ic": ic, "hac_t": t}

    validation = {"decision_rank_20d": block(validation_ic)}
    backtest = {"decision_rank_20d": block(backtest_ic, hac_t)}
    if swapped is not None:
        validation["decision_rank_20d_swapped_priority"] = block(swapped)
        backtest["decision_rank_20d_swapped_priority"] = block(backtest_ic, hac_t)
    return {"ensemble": {"validation": validation, "backtest": backtest}}


def test_r_model10_compares_against_the_installed_models_with_the_ensemble_yardstick():
    model_ic = {
        "candidates": {"installed": _entry(0.00, 0.07, 2.5), "good": _entry(0.05, 0.065, 2.2), "weak": _entry(0.02, 0.07, 2.4)},
        "bootstrap": {"decision_rank_20d": {"yardstick": 0.03}},
    }
    good = research.model10_checks(model_ic, "good")
    assert good["validation_beats_installed_by_yardstick"] and good["backtest_ic_not_below_installed_minus_yardstick"]
    assert good["backtest_hac_t_ge_2"] and good["yardstick"] == 0.03 and good["decision_priority"] == "live"
    assert not research.model10_checks(model_ic, "weak")["validation_beats_installed_by_yardstick"]
    model_ic["bootstrap"] = {}
    assert research.model10_checks(model_ic, "weak")["yardstick"] == 0.02  # no bootstrap: the floor


def _scores(low, high, cost):
    split = {"min_net_sharpe": low, "max_net_sharpe": high, "cost_drag_by_phase": [cost, cost]}
    return {"validation": split, "backtest": dict(split)}


def test_r_stagger_needs_the_phase_range_to_shrink_at_bounded_cost():
    base = _scores(-1.0, 0.6, 100.0)
    assert research.stagger_checks(base, _scores(-0.2, 0.4, 120.0)) == {
        "validation_phase_range_cut_ge_25pct": True, "cost_drag_rise_le_30pct": True}
    narrow_but_costly = research.stagger_checks(base, _scores(-0.2, 0.4, 140.0))
    assert narrow_but_costly["cost_drag_rise_le_30pct"] is False
    assert research.stagger_checks(base, _scores(-0.9, 0.5, 100.0))["validation_phase_range_cut_ge_25pct"] is False
