"""scripts/v630_research.py (V6.3.0): the pre-registered clauses of R-KILL and R-STAGGER2."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("v630_research", ROOT / "scripts" / "v630_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def _split(sharpes, locked=(10,) * 10, cost=(80.0,) * 10):
    ordered = sorted(sharpes)
    return {"median_net_sharpe": ordered[len(ordered) // 2], "min_net_sharpe": ordered[0], "max_net_sharpe": ordered[-1],
            "median_net_max_drawdown": -0.05, "net_sharpe_by_phase": list(sharpes),
            "locked_dates_by_phase": list(locked), "cost_drag_by_phase": list(cost)}


def test_jaccard_and_the_empty_case():
    assert research.jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)
    assert research.jaccard([], []) == 1.0


def test_perturbation_is_seeded_and_only_adds_noise():
    dates = ["2024-01-02", "2024-01-03"]
    first = research.perturbation(dates, 1, {"2024-01-02": 0.01})
    assert first == research.perturbation(dates, 1, {"2024-01-02": 0.01})
    assert first != research.perturbation(dates, 2, {"2024-01-02": 0.01})
    assert first["2024-01-02"] == pytest.approx(0.01, abs=5 * research.NOISE_STD)


def test_kill_checks_need_stability_and_enough_locks():
    base = {"validation": _split([0.1] * 10, locked=[20] * 10), "backtest": _split([0.7] * 10, locked=[20] * 10)}
    few_locks = {"validation": _split([0.1] * 10, locked=[5] * 10), "backtest": _split([0.7] * 10, locked=[20] * 10)}
    assert all(research.kill_checks(base, base, 0.70, 0.85).values())
    checks = research.kill_checks(base, few_locks, 0.70, 0.60)
    assert not checks["stability_jaccard_ge_0.80"] and not checks["stability_not_below_ks0"]
    assert not checks["locks_ge_half_of_ks0_on_both_splits"]


def _variant(passes, gain, change, stability, extra_ok=True, backtest_median=0.8):
    return {"verdict": {"passes": passes, "backtest_gain": gain, "validation_change": change},
            "extra_checks": {"a": extra_ok}, "stability": stability,
            "scores": {"backtest": {"median_net_sharpe": backtest_median}}}


def test_kill_branch_a_takes_the_best_passing_variant():
    variants = {"KS1": _variant(True, 0.12, 0.0, 0.9, backtest_median=0.9), "KS2": _variant(True, 0.2, 0.0, 0.85, backtest_median=1.0)}
    assert research.kill_branch(variants) == ("A", "KS2")


def test_kill_branch_b_takes_the_most_stable_non_inferior_variant():
    variants = {"KS1": _variant(False, 0.01, -0.01, 0.95), "KS2": _variant(False, 0.05, 0.0, 0.90), "KS3": _variant(False, -0.05, 0.0, 0.99)}
    assert research.kill_branch(variants) == ("B", "KS1")


def test_kill_branch_c_when_nothing_is_safe():
    variants = {"KS1": _variant(True, 0.3, 0.1, 0.95, extra_ok=False)}
    assert research.kill_branch(variants) == ("C", None)


def test_stagger2_uses_iqr_and_the_worst_phase_not_the_range():
    base = {"validation": _split([-1.0, -0.5, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6]),
            "backtest": _split([0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3])}
    # one lucky phase widens the max-min range a lot but leaves the IQR and the worst phase alone
    lucky = {"validation": _split([-1.0, -0.5, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 3.0]), "backtest": base["backtest"]}
    assert all(research.stagger2_checks(base, lucky).values())
    worse = {"validation": _split([-1.5, -0.5, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6]), "backtest": base["backtest"]}
    assert not research.stagger2_checks(base, worse)["worst_phase_within_0.10_on_both_splits"]
    costly = {"validation": _split(base["validation"]["net_sharpe_by_phase"], cost=[120.0] * 10),
              "backtest": _split(base["backtest"]["net_sharpe_by_phase"], cost=[120.0] * 10)}
    assert not research.stagger2_checks(base, costly)["cost_drag_rise_le_30pct"]
