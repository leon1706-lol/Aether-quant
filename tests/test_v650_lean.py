"""scripts/v650_lean.py: the verdicts R-EDGE1 and R-LEAN19 as pure functions of the figures."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_SPEC = importlib.util.spec_from_file_location("v650_lean", ROOT / "scripts" / "v650_lean.py")
module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(module)

PASS = dict(e1=[1.1, 1.0, 1.2, 1.05, 0.9], e2_t=3.0, dsr=0.95, null_a=[0.0] * 40, null_b=[0.0] * 39 + [9.0], candidate_sharpe=1.5, early_sharpe=0.1, early_alpha=0.001)
BASE = {"lean_sharpe": -0.204, "strategy_sharpe": 0.268}


def _pool_entry(**overrides):
    entry = {"lean_sharpe": 0.0, "strategy_sharpe": 0.5, "annual_std": 0.07, "drawdown_pct": 10.0, "complete": True, "long_strategy_sharpe": 0.2}
    entry.update(overrides)
    return entry


def test_edge_passes_only_with_every_clause_at_its_exact_bar():
    result = module.judge_edge(**PASS)
    assert result["verified"] is True
    assert result["e1_median"] == 1.05


def test_each_edge_clause_can_fail_the_verdict_alone():
    for change, clause in (
        (dict(e1=[0.9] * 5), "E1"), (dict(e2_t=2.99), "E2"), (dict(dsr=0.949), "E3"),
        (dict(null_a=[9.0, 9.0] + [0.0] * 38), "E4"), (dict(null_b=[9.0, 9.0] + [0.0] * 38), "E4"), (dict(null_a=[0.0] * 39), "E4"),
        (dict(early_sharpe=0.0), "E5"), (dict(early_alpha=-0.001), "E5"),
    ):
        result = module.judge_edge(**{**PASS, **change})
        assert result["verified"] is False
        assert result["clauses"][clause] is False


def test_edge_treats_a_missing_figure_as_a_failure():
    result = module.judge_edge(**{**PASS, "e2_t": None, "dsr": None, "candidate_sharpe": None, "early_sharpe": None})
    assert result["clauses"] == {"E1": True, "E2": False, "E3": False, "E4": False, "E5": False}
    assert module.judge_edge(**{**PASS, "e1": [1.1, None, 1.1, 1.1, 1.1]})["clauses"]["E1"] is False


def test_fallback_installs_the_best_when_it_clears_every_clause():
    result = module.judge_fallback({"low": _pool_entry(strategy_sharpe=0.4), "high": _pool_entry(strategy_sharpe=0.6)}, BASE)
    assert result["best"] == "high"
    assert result["install"] == "high"


def test_leverage_alone_cannot_pass_the_fallback():
    # scaling BT11's strategy up lifts its Lean Sharpe past the bar, but leaves the ex-T-bill Sharpe where it was
    result = module.judge_fallback({"scaled_bt11": _pool_entry(lean_sharpe=-0.08, strategy_sharpe=0.268)}, BASE)
    assert result["install"] is None
    assert result["clauses"]["scaled_bt11"]["lean_sharpe"] is True
    assert result["clauses"]["scaled_bt11"]["strategy_sharpe"] is False


def test_fallback_clauses_are_the_rule_text():
    for change, clause in (
        (dict(lean_sharpe=-0.105), "lean_sharpe"), (dict(strategy_sharpe=0.367), "strategy_sharpe"), (dict(annual_std=0.101), "vol"),
        (dict(drawdown_pct=15.1), "drawdown"), (dict(complete=False), "complete"), (dict(long_strategy_sharpe=0.0), "long_window"),
    ):
        result = module.judge_fallback({"x": _pool_entry(**change)}, BASE)
        assert result["install"] is None
        assert result["clauses"]["x"][clause] is False


def test_fallback_never_passes_over_the_best_for_a_worse_candidate_that_clears():
    # the rule picks the best first and judges it: a failed best means nothing installs, not the runner-up
    result = module.judge_fallback({"best": _pool_entry(strategy_sharpe=2.0, drawdown_pct=30.0), "second": _pool_entry(strategy_sharpe=0.6)}, BASE)
    assert result["best"] == "best"
    assert result["install"] is None


def test_fallback_with_no_long_window_score_does_not_block():
    assert module.judge_fallback({"x": _pool_entry(long_strategy_sharpe=None)}, BASE)["install"] == "x"


def test_empty_pool_installs_nothing():
    assert module.judge_fallback({}, BASE) == {"best": None, "install": None, "clauses": {}}
