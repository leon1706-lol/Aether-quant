"""scripts/book_variant_research.py (V6.0.0, rule R-BOOK): the pre-registered decision, pure."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("book_variant_research", ROOT / "scripts" / "book_variant_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def _mode(validation, backtest, dd_validation=-0.04, dd_backtest=-0.04):
    return {"validation": {"net_sharpe": validation, "net_max_drawdown": dd_validation},
            "backtest": {"net_sharpe": backtest, "net_max_drawdown": dd_backtest}}


def _book(ungated, as_live=None):
    return {"ungated": ungated, "as_live": as_live or ungated}


def test_a_variant_must_gain_ten_points_on_the_backtest_and_stay_positive_on_both_splits():
    base = _book(_mode(0.20, 0.30))
    good = _book(_mode(0.19, 0.41))
    assert research.decide(base, good, "B")["adopted"]
    assert not research.decide(base, _book(_mode(0.19, 0.39)), "B")["adopted"]  # +0.09 on the backtest
    assert not research.decide(base, _book(_mode(0.17, 0.60)), "B")["adopted"]  # validation 0.03 worse
    assert not research.decide(base, _book(_mode(-0.01, 0.60)), "B")["adopted"]  # negative on validation
    assert not research.decide(base, _book(_mode(0.25, 0.60, dd_backtest=-0.06)), "B")["adopted"]  # drawdown 2 pp worse


def test_branch_a_also_needs_the_as_live_margins_but_not_positivity_there():
    base = _book(_mode(0.20, 0.30), _mode(-0.50, -0.20))
    variant_ok = _book(_mode(0.30, 0.50), _mode(-0.40, -0.05))
    variant_bad = _book(_mode(0.30, 0.50), _mode(-0.40, -0.15))
    assert research.decide(base, variant_ok, "A")["adopted"]
    assert not research.decide(base, variant_bad, "A")["adopted"]
    assert research.decide(base, variant_bad, "B")["adopted"]  # branch B ignores the as-live book


def test_a_head_that_fails_its_gate_cannot_be_adopted_whatever_it_earns():
    base, great = _book(_mode(0.2, 0.3)), _book(_mode(0.9, 0.9))
    verdict = research.decide(base, great, "B", head_status_ok=False)
    assert verdict["ungated"]["passes"] and not verdict["adopted"]


def test_head_status_inherits_the_owners_watchlist_only_for_the_installed_models():
    config = {"phase_v2": {"rank_signal": {"min_promotion_status": ["promotable", "watchlist"]}}}
    metrics = {"backtest": {"sector_neutral_rank_20d_ranking_quality": {"quality_status": "not_promotable"},
                            "rank_60d_ranking_quality": {"quality_status": "watchlist"}}}
    assert research.head_status_ok({"heads": {"rank_20d": 1.0}}, config, metrics)  # owner decision of 2026-10-13
    assert not research.head_status_ok({"heads": {"sector_neutral_rank_20d": 1.0}}, config, metrics)
    assert research.head_status_ok({"heads": {"rank_60d": 1.0}, "ml_dir": "ml/versions/x"}, config, metrics)
    assert not research.head_status_ok({"heads": {"rank_20d": 1.0}, "ml_dir": "ml/versions/x"}, config, metrics)
    assert research.head_status_ok({}, config, None)


def test_variants_merge_only_when_they_do_not_conflict():
    assert research.merge_variants(["B1", "B2a"])["config"] == {
        "portfolio_book.rebalance_every_bars": 20, "exits.max_holding_bars": 40, "portfolio_book.hysteresis_rank_margin": 0.10}
    assert research.merge_variants(["B2a", "B2b"]) == {}
    assert research.merge_variants(["B3", "B6"]) == {}
    assert research.merge_variants(["B3", "B4"])["heads"] == {"rank_20d": 1.0}


def test_the_greedy_combination_adds_in_validation_order_and_tests_each_step_against_the_running_best():
    scores = {"B1": _book(_mode(0.30, 0.50)), "B2a": _book(_mode(0.25, 0.70)), ("B1", "B2a"): _book(_mode(0.31, 0.52))}

    def evaluate(merged):
        if merged["config"] == research.merge_variants(["B2a"])["config"]:
            return scores["B2a"]
        return scores[("B1", "B2a")] if "portfolio_book.hysteresis_rank_margin" in merged["config"] else scores["B1"]

    base = _book(_mode(0.20, 0.30))
    chosen, log = research.greedy_combination(
        ["B1", "B2a"], {"B1": 0.30, "B2a": 0.25}, evaluate, base, "B", head_ok=lambda spec: True
    )
    assert chosen == ["B1"] and len(log) == 2  # B1 passes, then B1+B2a adds only +0.02 over B1: rejected
    assert log[1]["verdict"]["adopted"] is False
    assert pytest.approx(log[1]["verdict"]["ungated"]["backtest_gain"]) == 0.02
