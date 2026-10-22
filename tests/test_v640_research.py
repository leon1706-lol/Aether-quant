"""scripts/v640_research.py (V6.4.0): every pre-registered clause and the stages that apply them, on synthetic summaries."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("v640_research", ROOT / "scripts" / "v640_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)

SPLITS = research.SPLITS


def summary(median=0.0, spread=0.2, drawdown=-0.05, turnover=3.0, cost=40.0, phases=10, **extra):
    """A split summary: `phases` Sharpes evenly spread +-`spread` around `median`."""
    sharpes = [median + spread * (2 * i / (phases - 1) - 1) for i in range(phases)]
    ordered = sorted(sharpes)
    data = {
        "median_net_sharpe": median, "min_net_sharpe": ordered[0], "max_net_sharpe": ordered[-1],
        "median_net_max_drawdown": drawdown, "median_net_total_return": median / 10, "phases": phases, "net_sharpe_by_phase": sharpes,
        "p10_net_sharpe": research.quantile(sharpes, 0.10), "p25_net_sharpe": research.quantile(sharpes, 0.25),
        "iqr_net_sharpe": research.interquartile_range(sharpes), "p05_net_max_drawdown": drawdown - 0.02,
        "cost_drag_by_phase": [cost] * phases, "median_turnover": turnover, "locked_dates_by_phase": [10] * phases,
        "legacy_net_return_median": 0.01,
    }
    data.update(extra)
    return data


def scores(validation=0.0, backtest=0.0, median=None, **kwargs):
    if median is not None:
        validation = backtest = median
    return {"validation": summary(median=validation, **kwargs), "backtest": summary(median=backtest, **kwargs)}


class FakeContext:
    """Stands in for `Research`: `score` answers from a table keyed by what a stage varies."""

    def __init__(self, table, l1_pass=True):
        self.table = table
        self.adopted = {"config": {}, "tranches": 1, "adjust_fraction": 1.0, "patch": {}, "model": None, "direction_overlay": None,
                        "needs_live_path": []}
        self.report = {"l1_pass": l1_pass}
        self.reads = []
        self.calls = []

    def score(self, changes, **kwargs):
        self.calls.append((dict(changes), kwargs))
        return self.table(changes, kwargs)

    def log_holdout_read(self, stage, what):
        self.reads.append((stage, what))


# ---------------------------------------------------------------- pure helpers


def test_quantile_interpolates():
    assert research.quantile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)
    assert research.quantile([5.0], 0.9) == 5.0
    assert research.quantile([0, 10], 0.25) == pytest.approx(2.5)


def test_extended_summary_adds_the_percentiles_and_per_phase_lists():
    rows = [{"net_sharpe": s, "net_total_return": s / 10, "net_max_drawdown": -0.04 - s / 100, "cost_drag_annual_bps": 30 + s,
             "annualized_turnover": 2.0 + s, "locked_dates": ["d"] * i, "legacy_net_return": 0.01, "engaged_sharpe": s + 0.1, "all_sharpe": s}
            for i, s in enumerate([-0.2, 0.0, 0.1, 0.3, 0.5])]
    out = research.extended_summary(rows)
    assert out["median_net_sharpe"] == 0.1 and out["p10_net_sharpe"] < out["p25_net_sharpe"] < out["median_net_sharpe"]
    assert out["locked_dates_by_phase"] == [0, 1, 2, 3, 4] and out["median_turnover"] == pytest.approx(2.1)
    assert out["engaged_sharpe_median"] == pytest.approx(0.2) and out["all_sharpe_by_phase"] == [-0.2, 0.0, 0.1, 0.3, 0.5]
    assert out["p05_net_max_drawdown"] <= out["median_net_max_drawdown"]


def test_patch_config_sets_root_paths_on_a_copy():
    base = {"phase1": {"target": {"ranking": {"separate_rank_groups": {"forex": ["forex"]}}}}, "phase_v2": {"rank_signal": {"heads": {}}}}
    patched = research.patch_config(base, {"phase1.target.ranking.separate_rank_groups": {"crypto": ["crypto"]},
                                           "phase_v2.rank_signal.heads": {"rank_20d": 1.0}})
    assert patched["phase1"]["target"]["ranking"]["separate_rank_groups"] == {"crypto": ["crypto"]}
    assert patched["phase_v2"]["rank_signal"]["heads"] == {"rank_20d": 1.0}
    assert base["phase1"]["target"]["ranking"]["separate_rank_groups"] == {"forex": ["forex"]}


def test_verdict_as_live_drops_only_the_positive_median_clause():
    base = scores(validation=-0.2, backtest=-0.1)
    better = scores(validation=-0.1, backtest=0.05, spread=0.1)
    ungated = research.rule_verdict(base, better)
    gated = research.verdict_as_live(base, better)
    assert "positive_median_on_both_splits" in ungated["checks"] and "positive_median_on_both_splits" not in gated["checks"]
    assert not ungated["passes"]
    assert gated["backtest_gain"] == pytest.approx(0.15)


def test_best_by_backtest():
    table = {"a": scores(backtest=0.1), "b": scores(backtest=0.4), "c": scores(backtest=0.2)}
    assert research.best_by_backtest(["a", "b", "c"], table) == "b" and research.best_by_backtest([], table) is None


def test_the_variant_grids_are_the_pre_registered_ones():
    assert len(research.L5_VARIANTS) == 8 and "R20/H40" not in research.L5_VARIANTS
    assert research.L5_VARIANTS["R10/H20"] == {"portfolio_book.rebalance_every_bars": 10, "exits.max_holding_bars": 20}
    assert set(research.L6_VARIANTS) == {"T2", "T2h", "T3", "T3h"} and set(research.L7_VARIANTS) == {"KD1", "KD2", "KD3", "KD4"}
    assert research.L10_VARIANTS["R3"]["rank_5d"] == 0.0 and research.MODEL_YARDSTICK == 0.034


# ---------------------------------------------------------------- the clauses


def test_l1_margins_and_the_owner_bar():
    margins = research.l1_margins({"ic_margin": 0.03}, {"engaged_sharpe_by_phase": [0.5, 0.6, 0.7], "all_sharpe_by_phase": [0.3, 0.3, 0.3]})
    assert margins["ic_margin"] == 0.03 and margins["sharpe_margin"] == pytest.approx(0.3)
    assert research.l1_margins({"ic_margin": None}, {})["sharpe_margin"] is None


def test_l2_turnover_clause():
    base = scores(turnover=3.0)
    assert research.l2_checks(base, scores(turnover=3.5))["turnover_rise_le_20pct"] is True
    assert research.l2_checks(base, scores(turnover=3.7))["turnover_rise_le_20pct"] is False


def test_l3_budget_clauses_and_the_model_clauses():
    verdict = {"validation_change": 0.05}
    assert research.l3_budget_checks(verdict, scores(), "LG-half") == {"validation_improves": True}
    assert research.l3_budget_checks({"validation_change": -0.01}, scores(), "LG-off") == {"validation_improves": False}
    assert "legacy_component_positive_on_both_splits" in research.l3_budget_checks(verdict, scores(), "LG-double")
    ic = {"validation_beats_installed_by_yardstick": True, "backtest_ic_not_below_installed_minus_yardstick": True, "backtest_hac_t_ge_2": True}
    ok = research.l3_model_checks(ic, {"passes": True, "validation_change": 0.1}, 1.2)
    assert research.all_pass(ok)
    assert not research.all_pass(research.l3_model_checks(ic, {"passes": True, "validation_change": 0.1}, 1.8))
    assert not research.all_pass(research.l3_model_checks(ic, {"passes": True, "validation_change": 0.1}, None))


def test_l4_clauses():
    base = scores(equity_sharpe_median=0.2)
    better = scores(equity_sharpe_median=0.4)
    verdict = {"backtest_gain": 0.0, "validation_change": 0.0}
    ic = {s: {"base": 0.02, "variant": 0.05} for s in SPLITS}
    assert research.all_pass(research.l4_checks(base, better, verdict, ic, 0.05))
    assert not research.all_pass(research.l4_checks(base, better, verdict, ic, 0.2))  # the holdout loses too much
    assert not research.all_pass(research.l4_checks(base, better, verdict, ic, None))
    assert not research.all_pass(research.l4_checks(base, better, {"backtest_gain": -0.1, "validation_change": 0.0}, ic, 0.0))
    assert not research.all_pass(research.l4_checks(base, scores(equity_sharpe_median=0.1), verdict, ic, 0.0))
    ic_down = {**ic, "validation": {"base": 0.05, "variant": 0.02}}
    assert not research.all_pass(research.l4_checks(base, better, verdict, ic_down, 0.0))


def test_l5_needs_median_and_p25_on_both_splits():
    base = scores(validation=0.1, backtest=0.1, spread=0.2)
    assert research.all_pass(research.l5_checks(base, scores(validation=0.2, backtest=0.3, spread=0.2)))
    assert not research.all_pass(research.l5_checks(base, scores(validation=0.2, backtest=0.3, spread=0.5)))  # wider -> lower p25
    assert not research.all_pass(research.l5_checks(base, scores(validation=0.05, backtest=0.3, spread=0.2)))


def test_l6_clauses_include_the_l1_precondition():
    base = scores(median=0.1, spread=0.3)
    tighter = scores(median=0.1, spread=0.2)
    assert research.all_pass(research.l6_checks(base, tighter, True))
    assert not research.all_pass(research.l6_checks(base, tighter, False))
    assert not research.all_pass(research.l6_checks(base, scores(median=0.1, spread=0.4), True))  # wider IQR / lower p10
    assert not research.all_pass(research.l6_checks(base, scores(median=0.1, spread=0.2, cost=60.0), True))  # cost drag +50%


def test_l7_clauses():
    def with_shares(share, drawdown=-0.05, median=0.0):
        return {s: summary(median=median, drawdown=drawdown, false_lock_share_by_phase=[share] * 10) for s in SPLITS}

    base = with_shares(0.40)
    assert research.all_pass(research.l7_checks(base, with_shares(0.30), 0.7, 0.8, True))
    assert not research.all_pass(research.l7_checks(base, with_shares(0.40), 0.7, 0.8, True))      # not strictly lower
    assert not research.all_pass(research.l7_checks(base, with_shares(0.30, drawdown=-0.06), 0.7, 0.8, True))  # p95 DD +1 pp
    assert not research.all_pass(research.l7_checks(base, with_shares(0.30), 0.7, 0.6, True))      # less stable
    assert not research.all_pass(research.l7_checks(base, with_shares(0.30, median=-0.05), 0.7, 0.8, True))  # Sharpe -0.05
    assert not research.all_pass(research.l7_checks(base, with_shares(0.30), 0.7, 0.8, False))     # L1 failed
    assert not research.all_pass(research.l7_checks(base, {s: summary() for s in SPLITS}, 0.7, 0.8, True))  # no false-lock data


def test_l8_disables_only_experts_that_never_help_and_only_if_non_inferior():
    contributions = {"bullish": {"validation": -0.01, "backtest": -0.02}, "bearish": {"validation": 0.01, "backtest": -0.02},
                     "sideways": {"validation": 0.0, "backtest": 0.0}, "volatility": {"validation": None, "backtest": -0.1}}
    safe = research.l8_decision(contributions, {"backtest_gain": 0.0, "validation_change": -0.01})
    assert safe["candidates_with_no_contribution"] == ["bullish", "sideways"] and safe["disable"] == ["bullish", "sideways"]
    unsafe = research.l8_decision(contributions, {"backtest_gain": -0.05, "validation_change": 0.0})
    assert unsafe["disable"] == [] and unsafe["candidates_with_no_contribution"] == ["bullish", "sideways"]
    assert research.l8_decision(contributions, None)["disable"] == []


def test_l9_keeps_graduates_only_if_they_win_on_both_splits():
    on, off = scores(validation=0.2, backtest=0.3), scores(validation=0.1, backtest=0.2)
    assert research.l9_decision(on, off)["keep_graduates"] is True
    assert research.l9_decision(scores(validation=0.05, backtest=0.3), off)["keep_graduates"] is False


def test_l10_clauses():
    assert research.all_pass(research.l10_checks({"passes": True}, {"market": 0.05, "momentum": -0.08}))
    assert not research.all_pass(research.l10_checks({"passes": True}, {"market": 0.15, "momentum": 0.0}))
    assert not research.all_pass(research.l10_checks({"passes": False}, {"market": 0.0, "momentum": 0.0}))


# ---------------------------------------------------------------- the stages, on a fake context


def test_dedupe_is_adopted_only_when_the_pooled_span_passes_and_reads_the_holdout():
    base = scores(validation=-0.4, backtest=-0.1)
    good = scores(validation=-0.3, backtest=0.05, spread=0.1)
    ctx = FakeContext(lambda changes, kwargs: good if "rolling_ic_gate.late_bar_event_count" in changes else base)
    stage = research.stage_dedupe(ctx)
    assert stage["adopted"] and ctx.adopted["config"] == research.DEDUPE_VARIANT and ctx.reads
    assert all(kwargs["specs"] == research.DEDUPE_SPECS for _c, kwargs in ctx.calls)
    ctx = FakeContext(lambda changes, kwargs: base)
    assert not research.stage_dedupe(ctx)["adopted"] and ctx.adopted["config"] == {}


def test_l5_adopts_the_best_passing_cell_and_writes_both_keys():
    base = scores(validation=0.0, backtest=0.0, spread=0.2)

    def table(changes, kwargs):
        rebalance, hold = changes.get("portfolio_book.rebalance_every_bars"), changes.get("exits.max_holding_bars")
        if (rebalance, hold) == (40, 60):
            return scores(validation=0.1, backtest=0.4, spread=0.2)
        if (rebalance, hold) == (40, 40):
            return scores(validation=0.1, backtest=0.3, spread=0.2)
        return base

    ctx = FakeContext(table)
    stage = research.stage_l5(ctx)
    assert stage["adopted"] == "R40/H60"
    assert ctx.adopted["config"] == {"portfolio_book.rebalance_every_bars": 40, "exits.max_holding_bars": 60}
    assert not research.stage_l5(FakeContext(lambda c, k: base))["adopted"]


def test_l6_cannot_ship_without_the_l1_precondition():
    base = scores(median=0.1, spread=0.4)

    def table(changes, kwargs):
        return scores(median=0.15, spread=0.2) if kwargs.get("tranches", 1) > 1 else base

    blocked = FakeContext(table, l1_pass=False)
    closed = research.stage_l6(blocked)
    assert closed["adopted"] is None and blocked.adopted["tranches"] == 1 and "precondition" in closed["skipped"] and not blocked.calls
    forced = FakeContext(table, l1_pass=False)
    forced.args = type("Args", (), {"score_blocked": True})()
    scored = research.stage_l6(forced)
    assert scored["adopted"] is None and scored["variants"] and forced.calls  # scored for the report, still cannot ship
    allowed = FakeContext(table, l1_pass=True)
    stage = research.stage_l6(allowed)
    assert stage["adopted"] in research.L6_VARIANTS and allowed.adopted["tranches"] >= 2 and "tranches" in allowed.adopted["needs_live_path"]
    assert set(stage["variants"][stage["adopted"]]) >= {"scores", "as_live_scores"}


def test_l10_adopts_through_a_patch_when_the_factor_shift_is_small(monkeypatch):
    base = scores(validation=0.0, backtest=0.0)
    better = scores(validation=0.05, backtest=0.3, spread=0.1)
    ctx = FakeContext(lambda changes, kwargs: better if kwargs["patch"].get("phase_v2.rank_signal.heads", {}).get("residual_rank_20d") == 0.2 else base)
    monkeypatch.setattr(research, "factor_shift", lambda c, patch: {"market": 0.02, "momentum": 0.01})
    stage = research.stage_l10(ctx)
    assert stage["adopted"] == "R1" and ctx.adopted["patch"]["phase_v2.rank_signal.heads"] == research.L10_VARIANTS["R1"]
    assert ctx.adopted["patch"]["phase_v2.rank_signal.demote_not_promotable_heads"] is False
    monkeypatch.setattr(research, "factor_shift", lambda c, patch: {"market": 0.5, "momentum": 0.0})
    assert research.stage_l10(FakeContext(lambda changes, kwargs: better if kwargs["patch"].get("phase_v2.rank_signal.heads", {}).get("residual_rank_20d") == 0.2 else base))["adopted"] is None


def test_false_lock_summary_uses_the_unlocked_books_forward_returns():
    days = [f"2024-01-{day:02d}" for day in range(1, 29)]
    strong = {day: 0.02 for day in days[1:12]}  # the unlocked book rallies on days 2-12
    returns = {day: strong.get(day, 0.0) for day in days}
    entry = {"locked_dates_lists": [days[:5], days[20:25]], "locked_dates_by_phase": [5, 5]}
    out = research.false_lock_summary({"validation": entry}, {"validation": [returns, returns]})
    assert out["validation"]["false_lock_share_by_phase"][0] >= 0.5  # most early locks precede the rally
    assert len(out["validation"]["false_lock_share_by_phase"]) == 1  # the late locks have no full 20-day window to judge
    assert "false_lock_share_median" in out["validation"]


def test_main_imports_cleanly_and_every_stage_is_registered():
    assert set(research.STAGES) == {"dedupe", "l1", "l8", "l2", "l3", "l4", "l5", "l6", "l7", "l9", "l10"}


def test_l7_is_closed_by_the_l1_precondition_without_scoring():
    ctx = FakeContext(lambda changes, kwargs: scores(), l1_pass=False)
    stage = research.stage_l7(ctx)
    assert stage["adopted"] is None and "precondition" in stage["skipped"] and not ctx.calls


def test_a_resumed_run_starts_from_the_shipped_config_not_the_previous_adoptions(tmp_path):
    previous = {"adopted": {"config": {"portfolio_book.rebalance_every_bars": 10}, "tranches": 3, "patch": {"x": 1}, "needs_live_path": ["tranches"]},
                "l1_pass": True, "holdout_reads": [{"stage": "l1", "what": "x"}]}
    ctx = research.Research(type("Args", (), {"candidates_spec": {}})(), {}, previous, tmp_path / "research.json")
    assert ctx.adopted == {"config": {}, "tranches": 1, "adjust_fraction": 1.0, "patch": {}, "model": None, "direction_overlay": None,
                           "needs_live_path": []}
    assert "l1_pass" not in previous and previous["holdout_reads"]  # reads already logged stay logged
