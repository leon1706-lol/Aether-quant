"""scripts/v640_research.py's runtime (V6.6.6, #359): the scoring layer, the harness pool, every stage and the command, on the synthetic as-live harness
of research_fakes. The clauses are the real ones; only the simulation is a stand-in."""

from __future__ import annotations

import copy
import json
import multiprocessing
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import research_fakes
from script_loader import ROOT, load_script


@pytest.fixture
def research(monkeypatch):
    research_fakes.install(monkeypatch)
    return load_script("v640_research")


@pytest.fixture
def base_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def _args(**extra):
    base = dict(candidates_spec={}, dataset="d.csv", legacy_probability="l.csv", gate_warmup_days=0, max_phases=2, workers=1, score_blocked=False,
                legacy_components=None, model_ic_data=None, lean_run=None)
    base.update(extra)
    return SimpleNamespace(**base)


@pytest.fixture
def ctx(research, base_config, tmp_path):
    return research.Research(_args(), base_config, {}, tmp_path / "out" / "research.json")


def test_a_phase_is_scored_with_every_extra_the_job_asks_for(research, ctx):
    harness, _topology, _config = ctx.harness("validation")
    job = dict(harness=harness, mechanisms={}, resolved={"a": 1}, mode="ungated", tranches=2, dates=research_fakes.DATES, extras=("returns", "engaged", "equity"),
               overlay_fn=lambda date, ranks: ranks, candidate_metadata={"BTCUSD": {}}, frame_returns={day: {"EQ0": 0.01} for day in research_fakes.DATES}, equity_tickers={"EQ0", "EQ1"})
    research._JOB.clear()
    research._JOB.update(job)
    plain = research._phase_worker((0, None))
    assert {"net_sharpe", "returns", "engaged_sharpe", "all_sharpe", "equity_sharpe", "legacy_net_return", "locked_dates"} <= set(plain)
    seeded = research._phase_worker((1, 5))
    kwargs = harness.calls[-1]
    assert kwargs["gate"] == "off" and "kill_switch_extra_returns" in kwargs and kwargs["rank_overlay_fn"] and kwargs["candidate_metadata_by_ticker"] and kwargs["log_weights"] and seeded
    research._JOB.update(mode="as_live", overlay_fn=None, candidate_metadata=None, extras=())
    quiet = research._phase_worker((0, None))
    assert "returns" not in quiet and "gate" not in harness.calls[-1]
    research._JOB.clear()


def test_the_tasks_run_in_a_pool_only_on_linux_with_workers(research, ctx, monkeypatch):
    harness, _t, _c = ctx.harness("validation")
    research._JOB.clear()
    research._JOB.update(harness=harness, mechanisms={}, resolved={}, mode="as_live", dates=research_fakes.DATES, extras=())

    class Pool:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def map(self, function, tasks):
            return [function(task) for task in tasks]

    monkeypatch.setattr(multiprocessing, "get_context", lambda kind: SimpleNamespace(Pool=lambda count: Pool()))
    monkeypatch.setattr(sys, "platform", "linux")
    assert len(research.map_tasks([(0, None), (1, None)], workers=2)) == 2
    assert len(research.map_tasks([(0, None), (1, None)], workers=1)) == 2
    research._JOB.clear()


def test_the_context_resumes_from_its_memo_saves_and_logs_each_holdout_read_once(research, base_config, tmp_path):
    out = tmp_path / "r" / "research.json"
    out.parent.mkdir()
    out.with_suffix(".memo.json").write_text(json.dumps({"k": {"a": 1}}), encoding="utf-8")
    ctx = research.Research(_args(), base_config, {"l1_pass": True}, out)
    assert ctx.memo == {"k": {"a": 1}} and "l1_pass" not in ctx.report
    ctx.log_holdout_read("l1", "x")
    ctx.log_holdout_read("l1", "x")
    ctx.save()
    assert len(json.loads(out.read_text(encoding="utf-8"))["holdout_reads"]) == 1 and out.with_suffix(".memo.json").exists()


def test_harnesses_are_pooled_and_a_candidate_spec_redirects_the_models(research, base_config, tmp_path):
    spec = {"cand": {"dataset": "other.csv", "ml_dir": "ml/versions/x", "legacy_probability": "p.csv", "ensemble": True}}
    ctx = research.Research(_args(candidates_spec=spec), base_config, {}, tmp_path / "r.json")
    first, _t, config = ctx.harness("validation")
    again, _t, _c = ctx.harness("validation")
    assert first is again
    candidate, _t, candidate_config = ctx.harness(("backtest", "holdout"), model="cand", patch={"phase1.x": 1})
    assert candidate.kwargs["dataset_path"] == "other.csv" and candidate_config["phase_v2"]["model_ensemble"]["enabled"] is True and candidate_config["phase1"]["x"] == 1
    for index in range(6):
        ctx.harness("validation", patch={"phase1.k": index})
    assert len(ctx.pool) <= 4 and config is not None


def test_the_legacy_probability_is_swapped_only_inside_the_block(research, ctx):
    harness, _t, _c = ctx.harness("validation")
    original = harness.frame[research_fakes.LEGACY_COLUMN].copy()
    keys = list(zip(harness.frame["date"], harness.frame["ticker"]))
    with ctx.legacy_override(harness, {keys[0]: 0.99}):
        assert harness.frame[research_fakes.LEGACY_COLUMN].iloc[0] == 0.99 and harness.lagged_frame[research_fakes.LEGACY_COLUMN].iloc[0] == 0.99
    assert harness.frame[research_fakes.LEGACY_COLUMN].equals(original)


def test_scoring_is_memoised_and_covers_overlays_stability_and_overrides(research, ctx):
    first = ctx.score({}, mode="as_live", memo_tag="a")
    assert ctx.score({}, mode="as_live", memo_tag="a") is first and set(first) == {"validation", "backtest"}
    full = ctx.score({"rolling_ic_gate.late_bar_event_count": "once"}, specs={"backtest": "backtest"}, extras=("returns", "equity"), stability=True,
                     eligible_override={"BTCUSD"}, legacy_probabilities={("2024-01-02", "EQ0"): 0.9}, phases=2, memo_tag="b",
                     overlay={"mode": "blend", "weight": 0.5, "calibration": None, "probabilities": {("2024-01-02", "EQ0"): 0.6}})
    assert "stability_jaccard_median" in full["backtest"] and "returns_by_phase" in full["backtest"]
    harness, _t, _c = ctx.harness("backtest")
    apply = ctx.overlay_fn(harness, {"mode": "blend", "weight": 0.5, "calibration": None, "probabilities": {}})
    assert callable(apply) and apply("2024-01-02", {"EQ0": 0.4, "EQ1": 0.6})


def test_the_equity_sleeve_sharpe_and_false_lock_shares(research):
    result = SimpleNamespace(per_date=research_fakes.DATES, weights_log=[{"EQ0": 0.5, "BTCUSD": 0.5} for _ in research_fakes.DATES])
    returns = {day: {"EQ0": 0.01 * ((index % 3) - 1), "BTCUSD": 0.5} for index, day in enumerate(research_fakes.DATES)}
    assert research.equity_gross_sharpe(result, returns, {"EQ0"}) is not None
    summary = {"validation": {"locked_dates_lists": [research_fakes.DATES[2:5]], "returns_by_phase": []}}
    unlocked = {"validation": [{day: 0.01 * ((index % 5) - 2) for index, day in enumerate(research_fakes.DATES)}]}
    shared = research.false_lock_summary(summary, unlocked)
    assert "false_lock_share_by_phase" in shared["validation"]


def _all_pass(research, monkeypatch):
    monkeypatch.setattr(research, "verdict_as_live", lambda base, variant: {"passes": True, "checks": {}, "backtest_gain": 0.5, "validation_change": 0.5})
    monkeypatch.setattr(research, "all_pass", lambda checks: True)
    for name in ("l2_checks", "l5_checks", "l6_checks", "l7_checks", "l3_budget_checks", "l3_model_checks", "l4_checks", "l10_checks"):
        monkeypatch.setattr(research, name, lambda *a, **k: {"ok": True})


@pytest.mark.parametrize("winning", [False, True])
def test_the_simple_stages_adopt_only_what_passes(research, ctx, monkeypatch, winning):
    if winning:
        _all_pass(research, monkeypatch)
    for stage in (research.stage_dedupe, research.stage_l5, research.stage_l10):
        monkeypatch.setattr(research, "factor_shift", lambda ctx, patch: {"market": 0.0, "momentum": 0.0})
        result = stage(ctx)
        assert "variants" in result or "verdict" in result
    if winning:
        assert ctx.adopted["config"] and ctx.adopted["patch"]


@pytest.mark.parametrize("winning", [False, True])
def test_the_blocked_stages_wait_for_l1_and_then_adopt(research, ctx, monkeypatch, winning):
    assert research.stage_l6(ctx)["adopted"] is None and research.stage_l7(ctx)["adopted"] is None and "closed by its precondition" in research.stage_l6(ctx)["skipped"]
    ctx.report["l1_pass"] = True
    if winning:
        _all_pass(research, monkeypatch)
    six = research.stage_l6(ctx)
    seven = research.stage_l7(ctx)
    assert "variants" in six and "variants" in seven
    if winning:
        assert ctx.adopted["needs_live_path"] == ["tranches"] or ctx.adopted["tranches"] >= 1


def test_the_engaged_skill_stage_reads_the_gate_and_logs_the_holdout(research, ctx, monkeypatch):
    monkeypatch.setattr(research, "engaged_labels", lambda ctx, harness, config: {day: index % 2 == 0 for index, day in enumerate(research_fakes.DATES)})
    stage = research.stage_l1(ctx)
    assert set(stage["skill"]) == {"validation", "backtest", "holdout"} and ctx.report["l1_pass"] == stage["gate_protects_capital"]


def test_the_gate_labels_come_from_the_harness_gate(research, ctx):
    import evaluation.engaged_day_skill as skill

    harness, _t, config = ctx.harness("validation")
    seen = {}
    harness.gate_for = lambda frame, ic_floor=None, late_bar_event_count=None: seen.update(floor=ic_floor) or (lambda date: {"engaged": True})
    assert callable(skill.gate_labels)
    research.engaged_labels(ctx, harness, config)
    assert "floor" in seen


def test_the_main_group_frame_follows_the_rank_groups(research, ctx):
    harness, _t, _c = ctx.harness("validation")
    assert len(research.main_group_frame(harness)) == len(harness.lagged_frame)
    harness.rank_groups = {"EURUSD": "forex", "BTCUSD": "crypto"}
    narrowed = research.main_group_frame(harness)
    assert "EURUSD" not in set(narrowed["ticker"])
    harness.lagged_frame = harness.lagged_frame.drop(columns=["target_rank_20d"])
    assert "target_rank_20d" not in research.main_group_frame(harness).columns


def test_the_engaged_equity_ic_can_score_a_legacy_probability(research, ctx, monkeypatch):
    monkeypatch.setattr(research, "engaged_labels", lambda ctx, harness, config: {day: True for day in research_fakes.DATES})
    own = research.equity_engaged_ic(ctx, "validation", {}, None)
    probabilities = {(day, ticker): 0.5 + 0.01 * index for index, day in enumerate(research_fakes.DATES) for ticker in research_fakes.EQUITY}
    legacy = research.equity_engaged_ic(ctx, "validation", {}, None, probabilities)
    assert own is None or isinstance(own, float)
    assert legacy is None or isinstance(legacy, float)


def test_the_expert_ablation_disables_experts_that_add_nothing(research, ctx, monkeypatch, tmp_path):
    import build_legacy_probability

    components = pd.DataFrame({"date": research_fakes.DATES * 2, "ticker": ["EQ0"] * 30 + ["EQ1"] * 30})
    path = tmp_path / "components.csv"
    components.to_csv(path, index=False)
    ctx.args.legacy_components = str(path)
    monkeypatch.setattr(build_legacy_probability, "legacy_probability_from_components", lambda row, metrics, config, excluded: 0.5 + 0.01 * len(excluded))
    ics = iter([0.1] + [0.2, 0.2, 0.3, 0.3] * 2)
    monkeypatch.setattr(research, "equity_engaged_ic", lambda *args, **kwargs: next(ics, 0.1))
    stage = research.stage_l8(ctx)
    assert set(stage["contributions"]) == set(research.EXPERTS) and "decision" in stage
    monkeypatch.setattr(research, "equity_engaged_ic", lambda *args, **kwargs: 0.1)
    monkeypatch.setattr(research, "verdict_as_live", lambda base, variant: {"passes": True, "backtest_gain": 0.0, "validation_change": 0.0, "checks": {}})
    stage = research.stage_l8(ctx)
    assert stage["decision"]["disable"] and ctx.adopted["legacy_experts_disabled"]


def test_the_legacy_report_groups_ic_by_class_and_regime(research, ctx, monkeypatch):
    import evaluation.gate_audit as gate_audit

    monkeypatch.setattr(gate_audit, "daily_rank_ic", lambda part, score_column, target_column: {"2024-01-02": 0.1} if len(part) > 20 else {})
    report = research.legacy_ic_report(ctx)
    assert set(report) == {"validation", "backtest"} and any(key.startswith("cls:") for key in report["validation"])
    harness, _t, _c = ctx.harness("validation")
    harness.frame = harness.frame.drop(columns=["regime_trend_bullish", "regime_trend_bearish"])
    harness.lagged_frame = harness.frame
    assert research.legacy_ic_report(ctx)["validation"]


def test_the_model_stage_needs_a_candidate_ic_and_a_built_directory(research, ctx, monkeypatch):
    base = ctx.score({}, mode="as_live")
    assert "skipped" in research.model_stage(ctx, base)
    ctx.args.candidates_spec = {"v640_leg": {}}
    ctx.args.model_ic_data = {"anything": 1}
    monkeypatch.setattr(research, "model10_checks", lambda model_ic, name: {"validation_beats_installed_by_yardstick": True, "backtest_ic_not_below_installed_minus_yardstick": True, "backtest_hac_t_ge_2": True})
    assert research.model_stage(ctx, base)["adopted"] is False
    ctx.args.candidates_spec = {"v640_leg": {"ml_dir": "ml/versions/x", "latency_ratio": 1.0}}
    monkeypatch.setattr(research, "verdict_as_live", lambda b, v: {"passes": True, "validation_change": 1.0, "backtest_gain": 1.0, "checks": {}})
    stage = research.model_stage(ctx, base)
    assert stage["adopted"] is True and ctx.adopted["model"] == "v640_leg"


def test_the_calibration_picks_the_best_cross_fitted_method(research, monkeypatch):
    import evaluation.probability_calibration as calibration

    frame = pd.DataFrame({"head": [0.4, 0.6], "target_direction_20d": [0, 1]})
    for cross, report_extra, expected in (
        ({"raw": 0.7, "temperature": 0.6, "isotonic": 0.65}, {"temperature": 1.5}, "temperature"),
        ({"raw": 0.7, "temperature": 0.7, "isotonic": 0.6}, {"isotonic": {"x": [0.0, 1.0], "y": [0.0, 1.0]}}, "isotonic"),
        ({"raw": 0.7, "temperature": 0.6}, {"temperature": 0.0}, None),
        ({"raw": 0.7}, {}, None),
    ):
        monkeypatch.setattr(calibration, "calibration_report", lambda p, y, _c=cross, _e=report_extra: {"cross_fitted_log_loss": _c, "temperature": None, "isotonic": None, **_e})
        _report, chosen = research.calibration_for_head(frame, "head")
        assert (chosen or {}).get("method") == expected


def test_the_direction_overlay_stage_calibrates_two_heads_and_adopts_the_best(research, ctx, monkeypatch, tmp_path):
    import evaluation.model_predictions as model_predictions

    (tmp_path / "ml").mkdir()
    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    for name in ("multitask", "sequence"):
        (tmp_path / "ml" / f"{name}_model.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ml" / f"{name}_feature_schema.json").write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")
    monkeypatch.setattr(model_predictions, "predict_head", lambda frame, export, names, head, **kwargs: np.linspace(0.3, 0.7, len(frame)))
    monkeypatch.setattr(research, "calibration_for_head", lambda frame, column: ({"log_loss": 0.69 if len(frame) else None}, {"method": "temperature", "temperature": 1.2}))
    losing = research.stage_l2(ctx)
    assert set(losing["heads"]) == {"multitask", "sequence"} and losing["chosen_head"] in losing["heads"]
    _all_pass(research, monkeypatch)
    winning = research.stage_l2(ctx)
    assert winning["adopted"] and ctx.adopted["direction_overlay"]["head"] == winning["chosen_head"] and "direction_overlay" in ctx.adopted["needs_live_path"]


def test_the_legacy_budget_stage_runs_the_ic_report_and_the_model_stage(research, ctx, monkeypatch):
    monkeypatch.setattr(research, "legacy_ic_report", lambda ctx: {"validation": {}})
    monkeypatch.setattr(research, "model_stage", lambda ctx, base: {"skipped": "x"})
    assert research.stage_l3(ctx)["budget_adopted"] is None
    _all_pass(research, monkeypatch)
    assert research.stage_l3(ctx)["budget_adopted"] and ctx.adopted["config"]


def test_the_within_class_stage_reads_the_holdout_for_its_leader_only(research, ctx, monkeypatch):
    monkeypatch.setattr(research, "equity_engaged_ic", lambda *args, **kwargs: 0.05)
    nothing = research.stage_l4(ctx)
    assert nothing["holdout_loss_of_leader"]["variant"] is None or isinstance(nothing["holdout_loss_of_leader"]["loss"], float)
    monkeypatch.setattr(research, "verdict_as_live", lambda base, variant: {"passes": True, "checks": {}, "backtest_gain": 0.5, "validation_change": 0.5})
    monkeypatch.setattr(research, "l4_checks", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(research, "all_pass", lambda checks: True)
    chosen = research.stage_l4(ctx)
    assert chosen["adopted"] and ctx.adopted["patch"] is not None and ("holdout", "l4") != () and ctx.report["holdout_reads"]


def test_the_crypto_graduates_stage_bootstraps_trades_and_leaves_names_out(research, ctx, monkeypatch, tmp_path):
    import evaluation.backtest_audit as backtest_audit
    import evaluation.trade_bootstrap as trade_bootstrap

    ctx.args.lean_run = "backtests/run"
    monkeypatch.setattr(backtest_audit, "load_backtest_run", lambda path: {})
    monkeypatch.setattr(trade_bootstrap, "round_trips_from_closed_trades", lambda run, names: [{"pnl": 1.0, "ticker": sorted(names)[0] if names else "X"}])
    monkeypatch.setattr(trade_bootstrap, "bootstrap_mean_pnl", lambda values: {"lo": 0.0, "hi": 1.0})
    monkeypatch.setattr(trade_bootstrap, "top_k_share", lambda values, k: 0.5)
    monkeypatch.setattr(trade_bootstrap, "pnl_by_name", lambda trades: {"A": 1.0})
    monkeypatch.setattr(trade_bootstrap, "leave_one_name_out", lambda by_name: {"A": 0.5})
    monkeypatch.setattr(trade_bootstrap, "repeatable", lambda bootstrap, leave: True)
    stage = research.stage_l9(ctx)
    assert stage["core_repeatable"] is True and set(stage["leave_one_out"]) == set(research_fakes.CRYPTO)
    monkeypatch.setattr(research, "l9_decision", lambda on, off: {"keep_graduates": False, "graduates_beat_core_only_on": {}})
    research.stage_l9(ctx)
    assert ctx.adopted["graduates_off"] is True and ctx.adopted["config"]["class_weight_caps.crypto.core_only"] is True
    ctx.args.lean_run = None
    assert "lean_trades" not in research.stage_l9(ctx)


def test_the_factor_shift_compares_the_loadings_of_two_head_blends(research, ctx, monkeypatch):
    import evaluation.benchmark_comparison as benchmark_comparison
    import evaluation.factor_neutralization_check as factor_check

    monkeypatch.setattr(benchmark_comparison, "close_pivot_from_frame", lambda frame: frame)
    reports = iter([{"status": "OK", "loadings": {"market": 0.5, "momentum": 0.1}}, {"status": "OK", "loadings": {"market": 0.7}}, {"status": "SKIPPED"}, {"status": "SKIPPED"}])
    monkeypatch.setattr(factor_check, "compute_book_factor_exposure", lambda dates, returns, pivot: next(reports))
    shift = research.factor_shift(ctx, {"phase_v2.rank_signal.heads": {}})
    assert shift == {"market": pytest.approx(0.2), "momentum": pytest.approx(-0.1)}
    assert research.factor_shift(ctx, {}) == {"market": 0.0, "momentum": 0.0}


def test_smoke_trims_every_variant_table(research):
    saved = {name: dict(getattr(research, name)) for name in ("L2_VARIANTS", "LEGACY_VARIANTS", "L4_VARIANTS", "L5_VARIANTS", "L6_VARIANTS", "L7_VARIANTS", "L10_VARIANTS")}
    try:
        research.apply_smoke()
        assert all(len(getattr(research, name)) == 1 for name in saved) and research.LOO_PHASES == 2
    finally:
        for name, table in saved.items():
            getattr(research, name).clear()
            getattr(research, name).update(table)
        research.LOO_PHASES = 5


def test_the_command_runs_the_chosen_stages_and_writes_the_adopted_changes(research, base_config, tmp_path, monkeypatch):
    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    (tmp_path / "config.json").write_text(json.dumps(base_config), encoding="utf-8")
    out, adopted = tmp_path / "out" / "research.json", tmp_path / "out" / "adopted.json"
    candidates = tmp_path / "cand.json"
    candidates.write_text(json.dumps({"v640_leg": {}}), encoding="utf-8")
    model_ic = tmp_path / "ic.json"
    model_ic.write_text("{}", encoding="utf-8")
    monkeypatch.setitem(research.STAGES, "l5", lambda ctx: {"adopted": "R10/H20"})
    monkeypatch.setattr(sys, "argv", ["v640", "--legacy-probability", "l.csv", "--stages", "l5", "--smoke", "--candidates", str(candidates), "--model-ic", str(model_ic), "--out", str(out), "--adopted-config-out", str(adopted)])
    saved = copy.deepcopy({name: dict(getattr(research, name)) for name in ("L2_VARIANTS", "LEGACY_VARIANTS", "L4_VARIANTS", "L5_VARIANTS", "L6_VARIANTS", "L7_VARIANTS", "L10_VARIANTS")})
    try:
        assert research.main() == 0
    finally:
        for name, table in saved.items():
            getattr(research, name).clear()
            getattr(research, name).update(table)
        research.LOO_PHASES = 5
    assert json.loads(out.read_text(encoding="utf-8"))["l5"] == {"adopted": "R10/H20"} and adopted.exists()
